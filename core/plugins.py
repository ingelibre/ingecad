# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Plugins: the contract, the loader and the on/off state (docs/plugins.md).

A plugin is a Python package (``plugins/<id>/`` in the app, or
``~/.config/IngeCAD/plugins/<id>/`` for the user's own) whose ``__init__``
exposes ``PLUGIN``, a :class:`PluginSpec`. Activating it registers its
commands, tools and aliases, merges its language packs, and adds its menu
and toolbar; deactivating removes exactly that -- the test suite holds the
host to "no trace left" on every bundled plugin. The core knows nothing of
topography or networks: it knows how to activate and deactivate.

This module is headless: the GUI side of the contract is a *host* object
(the main window) with a handful of duck-typed methods, listed under
:class:`PluginManager`. Tests can pass any object with those methods.
"""
from __future__ import annotations

import importlib.util
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from core.paths import app_root

#: The level of the plugin contract this IngeCAD offers. A plugin states the
#: level it was written for in ``PluginSpec.api_version``; one that needs a
#: higher level uses hooks this IngeCAD does not have, so it is listed with
#: the reason and never activated half-working. Raised by one each time the
#: contract grows (docs/plugins.md says what every level added); a level is
#: never taken back, so a plugin for an older level keeps working.
API_VERSION = 2


# -- what a plugin declares ----------------------------------------------------

@dataclass(frozen=True)
class MenuItem:
    """One entry of the plugin's menu: ``label`` (English, translated when
    the menu is built) runs ``command`` like typing it."""

    label: str
    command: str
    icon: Optional[Path] = None


@dataclass(frozen=True)
class Submenu:
    label: str
    items: tuple = ()


#: A separator line in a plugin menu.
SEPARATOR = "---"


@dataclass(frozen=True)
class ToolbarItem:
    label: str
    command: str
    icon: Optional[Path] = None


class _Consumed:
    """An input filter's answer: "I took it, nothing else runs"."""

    def __repr__(self) -> str:
        return "CONSUMED"


#: Returned by an input filter that handled the input itself.
CONSUMED = _Consumed()

#: The text an input filter receives when Esc is pressed.
ESCAPE = "\x1b"


@dataclass(frozen=True)
class InputState:
    """Where the input arrives, for an input filter to decide on."""

    tool: str = ""            # the running command's tool name, "" if none
    selecting: bool = False   # at a "Select objects:" prompt
    grip_hot: bool = False    # a grip is held, no command running
    prompt: str = ""          # the prompt on screen, as shown


@dataclass
class PluginSpec:
    """Everything the host needs to know about a plugin.

    ``commands`` map an English command name to ``handler(ctx, *args)``;
    ``tools`` map a command name to a :class:`tools.base.Tool` subclass, and
    a tool without a handler of its own gets one that starts it. ``aliases``
    are AutoCAD-style shortcuts (``CN`` -> ``CONTOUR``); one that the user's
    PGP file or the core already defines is left alone. ``i18n_dir`` holds
    ``<lang>/ui.json`` and ``<lang>/commands.json`` in the same shape as the
    app's ``i18n/``. ``requires`` names importable modules the plugin needs;
    a missing one lists the plugin as unavailable with the reason instead of
    breaking the start-up. ``api_version`` is the contract level the plugin
    was written for (:data:`API_VERSION`); a level this IngeCAD does not
    reach lists it as unavailable the same way.
    """

    id: str
    name: str
    version: str = "0.1"
    description: str = ""
    requires: tuple[str, ...] = ()
    commands: dict[str, Callable] = field(default_factory=dict)
    tools: dict[str, type] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    menu: tuple = ()
    toolbar: tuple = ()
    options_page: Optional[Callable] = None
    i18n_dir: Optional[Path] = None
    on_document_open: Optional[Callable] = None
    api_version: int = 1
    on_regen_done: Optional[Callable] = None
    on_selection_changed: Optional[Callable] = None
    grip_handlers: dict = field(default_factory=dict)
    input_filters: tuple = ()


@dataclass
class PluginContext:
    """What a plugin's command handler receives as its first argument.

    Everything a plugin may ask of the running window goes through here,
    so it never reads the window's private state (which changes from one
    release to the next). Level 2 of the contract added everything after
    :meth:`start_tool`.
    """

    host: object                     # the main window, or a test double
    echo: Callable[[str], None]

    @property
    def document(self):
        return getattr(self.host, "document", None)

    def execute(self, command) -> None:
        """Run an undoable Command through the host's history."""
        self.host.tools._execute(command)

    def start_tool(self, name: str) -> None:
        self.host.tools.start_tool(name)

    # -- level 2 ---------------------------------------------------------------
    def run_command(self, *answers) -> None:
        """Type ``answers`` at the command line, one after the other, as
        the user would: ``ctx.run_command("CIRCLE", "0,0", "5")``."""
        for answer in answers:
            self.host._on_command_submitted(str(answer))

    @property
    def active_layout(self) -> str:
        """The tab in view: ``"Model"`` or a layout's name."""
        return getattr(self.host, "_active_layout", "Model")

    @property
    def selection(self) -> list:
        """The selected entities (live ones only)."""
        tools = getattr(self.host, "tools", None)
        return list(tools.selected_entities()) if tools is not None else []

    def select(self, entities) -> int:
        """Make ``entities`` the selection, as a pick would (a locked
        layer's stay out with no command running); returns how many."""
        return self.host.tools.select_entities(entities)

    @property
    def pick_tolerance(self) -> float:
        """The pickbox's half-size in drawing units at the current zoom."""
        return float(self.host.tools.pick_tolerance())

    def redraw(self, entities=None) -> None:
        """Show ``entities`` again with their current look, without a
        regen; with none, just repaint the drawing area."""
        if entities:
            self.host.tools.redraw_entities(list(entities))
        else:
            self.host.viewport.update()

    def regen(self) -> None:
        """Rebuild the whole drawing in the background (REGEN); the
        plugins' ``on_regen_done`` hear when it is in view."""
        self.host.regen_in_memory()

    # -- undo steps (level 2) ----------------------------------------------------
    def mark(self) -> int:
        """Where the undo history stands now, for :meth:`fold_since` and
        :meth:`undo_to`."""
        return self.host.history.depth

    def fold_since(self, mark: int, name: str) -> None:
        """Make everything executed since ``mark`` one undo step."""
        self.host.history.fold(min(mark, self.host.history.depth), name)
        self._refresh()

    def undo_to(self, mark: int) -> None:
        """Undo everything executed since ``mark``, leaving nothing to
        redo, and show the drawing as it was."""
        tools = self.host.tools
        for command in self.host.history.undo_to(mark):
            tools.after_history_change(command)
        self._refresh()

    @contextmanager
    def transaction(self, name: str):
        """Several commands as one undo step::

            with ctx.transaction("Parcel"):
                ctx.execute(...)
                ctx.execute(...)

        If the block raises, what it executed is undone and the error goes
        on to the caller."""
        start = self.mark()
        try:
            yield self
        except BaseException:
            self.undo_to(start)
            raise
        self.fold_since(start, name)

    def _refresh(self) -> None:
        changed = getattr(getattr(self.host, "tools", None), "changed", None)
        if changed is not None:
            changed.emit()


@dataclass
class LoadedPlugin:
    """A discovered plugin: its spec, or why it could not be loaded."""

    id: str
    location: Path
    bundled: bool
    spec: Optional[PluginSpec] = None
    error: str = ""
    missing: tuple[str, ...] = ()

    @property
    def too_new(self) -> bool:
        """Written for a contract level this IngeCAD does not offer."""
        return self.spec is not None and needed_api(self.spec) > API_VERSION

    @property
    def available(self) -> bool:
        return (self.spec is not None and not self.missing and not self.error
                and not self.too_new)

    @property
    def reason(self) -> str:
        """Why it cannot be turned on, in plain words (empty when it can)."""
        if self.error:
            return self.error
        if self.too_new:
            from core.i18n import tr

            return tr("needs plugin API {need}; this IngeCAD offers {have}. "
                      "Update IngeCAD.", need=needed_api(self.spec),
                      have=API_VERSION)
        if self.missing:
            return "needs " + ", ".join(self.missing)
        return ""

    @property
    def screenshot(self) -> Optional[Path]:
        """The picture its card shows in the extension manager, if any."""
        return plugin_screenshot(self.location)


@dataclass
class _Activation:
    commands: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    pack_dir: Optional[Path] = None
    toolbar: bool = False
    grip_types: list[str] = field(default_factory=list)


# -- where plugins live --------------------------------------------------------

def bundled_plugins_dir() -> Path:
    return app_root() / "plugins"


def user_plugins_dir() -> Path:
    from core.paths import user_config_dir

    return user_config_dir() / "plugins"


#: A plugin declares the picture of its card in the extension manager by
#: shipping one of these files beside its ``__init__.py`` (the first found
#: wins). A file, not a spec field: the folder travels whole in every
#: package (PyInstaller datas, the Flatpak's ``cp -a``), the picture shows
#: even when the plugin cannot be imported, and no network is asked.
SCREENSHOT_FILES = ("screenshot.jpg", "screenshot.jpeg", "screenshot.png")


def plugin_screenshot(folder: Path) -> Optional[Path]:
    for name in SCREENSHOT_FILES:
        path = Path(folder) / name
        if path.is_file():
            return path
    return None


def needed_api(spec: PluginSpec) -> int:
    """The contract level ``spec`` asks for; a value that is not a whole
    number reads as the first level."""
    value = getattr(spec, "api_version", 1)
    return value if isinstance(value, int) and value >= 1 else 1


def missing_requirements(spec: PluginSpec) -> tuple[str, ...]:
    """The modules of ``spec.requires`` this interpreter cannot import."""
    out = []
    for name in spec.requires:
        try:
            found = importlib.util.find_spec(name)
        except (ImportError, ValueError):
            found = None
        if found is None:
            out.append(name)
    return tuple(out)


def load_plugin(folder: Path, bundled: bool) -> LoadedPlugin:
    """Import ``folder/__init__.py`` as its own module and read ``PLUGIN``.

    Loaded by path on purpose: a bundled plugin ships as data files in the
    frozen builds, and a user plugin lives outside every package.
    """
    plugin_id = folder.name
    init = folder / "__init__.py"
    loaded = LoadedPlugin(plugin_id, folder, bundled)
    if not init.is_file():
        loaded.error = "no __init__.py"
        return loaded
    module_name = f"ingecad_plugin_{plugin_id}"
    try:
        module_spec = importlib.util.spec_from_file_location(
            module_name, init, submodule_search_locations=[str(folder)])
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module_name] = module
        module_spec.loader.exec_module(module)
        spec = getattr(module, "PLUGIN", None)
    except Exception as exc:                      # a broken plugin never
        sys.modules.pop(module_name, None)        # takes the app down
        loaded.error = f"{type(exc).__name__}: {exc}"
        return loaded
    if not isinstance(spec, PluginSpec):
        loaded.error = "PLUGIN is not a PluginSpec"
        return loaded
    if spec.id != plugin_id:
        loaded.error = f"PLUGIN.id is {spec.id!r} but the folder is {plugin_id!r}"
        return loaded
    loaded.spec = spec
    loaded.missing = missing_requirements(spec)
    return loaded


# -- the manager ---------------------------------------------------------------

class PluginManager:
    """Discovers plugins, remembers which are on, activates them on a host.

    The host is duck-typed; the main window implements it, tests may pass
    anything with these methods::

        register_command(name, handler)     unregister_command(name)
        register_tools(mapping, owner)      unregister_tools(names, owner)
        add_alias(alias, command) -> bool   remove_alias(alias)
        add_pack_dir(path)                  remove_pack_dir(path)
        add_toolbar(spec)                   remove_toolbar(plugin_id)
        menus_changed()                     echo(text)
    """

    SETTING = "plugins/{id}/enabled"
    #: A plugin's toolbar is OFF by default: the menu is what a plugin adds,
    #: the toolbar is the user's to switch on (Tools > Plugins). Nobody who
    #: only draws should find a strip of survey buttons on their screen.
    TOOLBAR_SETTING = "plugins/{id}/toolbar"

    def __init__(self, host=None, bundled_dir: Optional[Path] = None,
                 user_dir: Optional[Path] = None) -> None:
        self.host = host
        self._dirs: list[tuple[Path, bool]] = [
            (bundled_dir if bundled_dir is not None else bundled_plugins_dir(), True),
            (user_dir if user_dir is not None else user_plugins_dir(), False),
        ]
        self.loaded: dict[str, LoadedPlugin] = {}
        self._active: dict[str, _Activation] = {}

    # -- discovery ---------------------------------------------------------------
    def scan_dir(self, folder: Path, bundled: bool) -> list[str]:
        """Load every plugin folder under ``folder``; returns the ids found.

        Folders whose name starts with ``_`` or ``.`` are skipped, so a
        package's own ``__pycache__`` never reads as a plugin.
        """
        found = []
        if not folder.is_dir():
            return found
        for sub in sorted(folder.iterdir()):
            if not sub.is_dir() or sub.name[:1] in ("_", "."):
                continue
            if sub.name in self.loaded:
                continue          # the first location wins (bundled first)
            self.loaded[sub.name] = load_plugin(sub, bundled)
            found.append(sub.name)
        return found

    def discover(self) -> list[str]:
        for folder, bundled in self._dirs:
            self.scan_dir(folder, bundled)
        return sorted(self.loaded)

    @property
    def user_dir(self) -> Path:
        """Where the user's own plugins live (the extension center installs
        there)."""
        return next(folder for folder, bundled in self._dirs if not bundled)

    def forget(self, plugin_id: str) -> None:
        """Turn the plugin off and drop it and its modules, as if it had
        never been found -- before its folder is replaced or deleted."""
        self.deactivate(plugin_id)
        self.loaded.pop(plugin_id, None)
        module_name = f"ingecad_plugin_{plugin_id}"
        for name in [n for n in sys.modules
                     if n == module_name or n.startswith(module_name + ".")]:
            del sys.modules[name]

    def reload(self, plugin_id: str) -> Optional[LoadedPlugin]:
        """Load a user plugin afresh from its folder (just installed or
        updated); it is switched on again if it was on. None if gone."""
        was_active = self.is_active(plugin_id)
        loaded = self.loaded.get(plugin_id)
        if loaded is not None and loaded.bundled:
            return loaded                 # the app's own never change here
        self.forget(plugin_id)
        folder = self.user_dir / plugin_id
        if not folder.is_dir():
            return None
        importlib.invalidate_caches()     # the folder's listing changed
        self.loaded[plugin_id] = loaded = load_plugin(folder, bundled=False)
        if was_active:
            self.activate(plugin_id)
        return loaded

    def problems(self) -> list[tuple[str, str]]:
        """``(id, reason)`` for every plugin that cannot be turned on."""
        return [(pid, p.reason) for pid, p in sorted(self.loaded.items())
                if not p.available]

    # -- on/off state --------------------------------------------------------------
    def enabled(self, plugin_id: str) -> bool:
        """Wanted on? Bundled plugins default to on, user ones to off."""
        loaded = self.loaded.get(plugin_id)
        default = bool(loaded and loaded.bundled)
        try:
            from PySide6.QtCore import QSettings

            raw = QSettings().value(self.SETTING.format(id=plugin_id), None)
        except Exception:
            raw = None
        if raw is None:
            return default
        return str(raw).lower() in ("true", "1", "yes")

    def set_enabled(self, plugin_id: str, flag: bool) -> None:
        """Persist the choice and apply it at once."""
        try:
            from PySide6.QtCore import QSettings

            QSettings().setValue(self.SETTING.format(id=plugin_id),
                                 "true" if flag else "false")
        except Exception:
            pass
        if flag:
            self.activate(plugin_id)
        else:
            self.deactivate(plugin_id)

    def is_active(self, plugin_id: str) -> bool:
        return plugin_id in self._active

    # -- the toolbar, the user's choice -----------------------------------------------
    def has_toolbar(self, plugin_id: str) -> bool:
        loaded = self.loaded.get(plugin_id)
        return bool(loaded and loaded.spec is not None and loaded.spec.toolbar)

    def toolbar_enabled(self, plugin_id: str) -> bool:
        """Does the user want this plugin's toolbar shown? Off until asked."""
        try:
            from PySide6.QtCore import QSettings

            raw = QSettings().value(self.TOOLBAR_SETTING.format(id=plugin_id), None)
        except Exception:
            raw = None
        return str(raw).lower() in ("true", "1", "yes") if raw is not None else False

    def set_toolbar_enabled(self, plugin_id: str, flag: bool) -> None:
        """Persist the choice and show or hide the toolbar at once."""
        try:
            from PySide6.QtCore import QSettings

            QSettings().setValue(self.TOOLBAR_SETTING.format(id=plugin_id),
                                 "true" if flag else "false")
        except Exception:
            pass
        record = self._active.get(plugin_id)
        if record is None or self.host is None or not self.has_toolbar(plugin_id):
            return
        if flag and not record.toolbar:
            self.host.add_toolbar(self.loaded[plugin_id].spec)
            record.toolbar = True
        elif not flag and record.toolbar:
            self.host.remove_toolbar(plugin_id)
            record.toolbar = False

    def active_specs(self) -> list[PluginSpec]:
        """The specs currently on, in id order (menu order, toolbar order)."""
        return [self.loaded[pid].spec for pid in sorted(self._active)]

    def activate_enabled(self) -> list[str]:
        """Turn on every available plugin whose setting says so."""
        out = []
        for pid in sorted(self.loaded):
            if self.loaded[pid].available and self.enabled(pid):
                if self.activate(pid):
                    out.append(pid)
        return out

    # -- activation ----------------------------------------------------------------
    def context(self) -> PluginContext:
        host = self.host
        echo = getattr(host, "echo", None) or (lambda text: None)
        return PluginContext(host=host, echo=echo)

    def activate(self, plugin_id: str) -> bool:
        """Register everything the spec declares; False if unavailable."""
        if plugin_id in self._active:
            return True
        loaded = self.loaded.get(plugin_id)
        if loaded is None or not loaded.available or self.host is None:
            return False
        spec, host = loaded.spec, self.host
        ctx = self.context()
        record = _Activation()
        self._active[plugin_id] = record
        try:
            # tools first: a command that starts a tool must find it
            host.register_tools(dict(spec.tools), spec.id)
            record.tools = list(spec.tools)
            for name, handler in spec.commands.items():
                host.register_command(name, _bind(handler, ctx))
                record.commands.append(name.upper())
            for name in spec.tools:
                if name.upper() not in record.commands:
                    host.register_command(name, _starter(ctx, name))
                    record.commands.append(name.upper())
            for alias, command in spec.aliases.items():
                if host.add_alias(alias, command):
                    record.aliases.append(alias.upper())
            if spec.grip_handlers:
                from core import select

                for dxftype, handler in spec.grip_handlers.items():
                    select.register_grip_handler(dxftype, handler, spec.id)
                    record.grip_types.append(dxftype)
            if spec.i18n_dir is not None and Path(spec.i18n_dir).is_dir():
                host.add_pack_dir(Path(spec.i18n_dir))
                record.pack_dir = Path(spec.i18n_dir)
            if spec.toolbar and self.toolbar_enabled(spec.id):
                host.add_toolbar(spec)
                record.toolbar = True
            host.menus_changed()
        except Exception as exc:
            self.deactivate(plugin_id)
            loaded.error = f"failed to activate: {type(exc).__name__}: {exc}"
            ctx.echo(f"{spec.name}: {loaded.error}")
            return False
        return True

    def deactivate(self, plugin_id: str) -> None:
        """Remove exactly what :meth:`activate` added, and nothing else."""
        record = self._active.pop(plugin_id, None)
        if record is None or self.host is None:
            return
        host = self.host
        for name in record.commands:
            host.unregister_command(name)
        for alias in record.aliases:
            host.remove_alias(alias)
        if record.grip_types:
            from core import select

            for dxftype in record.grip_types:
                select.unregister_grip_handler(dxftype, plugin_id)
        if record.tools:
            host.unregister_tools(record.tools, plugin_id)
        if record.pack_dir is not None:
            host.remove_pack_dir(record.pack_dir)
        if record.toolbar:
            host.remove_toolbar(plugin_id)
        host.menus_changed()

    # -- events --------------------------------------------------------------------
    def document_opened(self, document) -> None:
        """A drawing was created or opened: let each active plugin look at
        it (read its saved datum, index its own objects...)."""
        ctx = self.context()
        for spec in self.active_specs():
            hook = spec.on_document_open
            if hook is None:
                continue
            try:
                hook(ctx, document)
            except Exception as exc:
                ctx.echo(f"{spec.name}: {type(exc).__name__}: {exc}")

    def filter_input(self, text: str, state: InputState):
        """Hand what was typed (``""`` for Enter, :data:`ESCAPE` for Esc)
        to each active plugin's input filters in turn. A filter returns
        None to leave it, a new text to pass on instead, or
        :data:`CONSUMED` to take it. Returns the text to act on, or
        CONSUMED."""
        ctx = None
        for spec in self.active_specs():
            for keep in spec.input_filters:
                if ctx is None:
                    ctx = self.context()
                try:
                    answer = keep(ctx, text, state)
                except Exception as exc:
                    ctx.echo(f"{spec.name}: {type(exc).__name__}: {exc}")
                    continue
                if answer is CONSUMED:
                    return CONSUMED
                if isinstance(answer, str):
                    text = answer
        return text

    def regen_done(self, layout: str) -> None:
        """A regen of ``layout`` is now on screen."""
        self._tell("on_regen_done", layout)

    def selection_changed(self) -> None:
        """The selection is another set now (``ctx.selection`` has it)."""
        self._tell("on_selection_changed")

    def _tell(self, hook_name: str, *args) -> None:
        """Call each active plugin's ``hook_name(ctx, *args)``; a plugin
        that raises is named at the command line, the rest still hear."""
        ctx = self.context()
        for spec in self.active_specs():
            hook = getattr(spec, hook_name, None)
            if hook is None:
                continue
            try:
                hook(ctx, *args)
            except Exception as exc:
                ctx.echo(f"{spec.name}: {type(exc).__name__}: {exc}")


def _bind(handler: Callable, ctx: PluginContext) -> Callable:
    def run(*args):
        return handler(ctx, *args)
    return run


def _starter(ctx: PluginContext, name: str) -> Callable:
    def run(*args):
        ctx.start_tool(name)
    return run
