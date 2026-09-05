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
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from core.paths import app_root


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
    breaking the start-up.
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


@dataclass
class PluginContext:
    """What a plugin's command handler receives as its first argument."""

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
    def available(self) -> bool:
        return self.spec is not None and not self.missing and not self.error

    @property
    def reason(self) -> str:
        """Why it cannot be turned on, in plain words (empty when it can)."""
        if self.error:
            return self.error
        if self.missing:
            return "needs " + ", ".join(self.missing)
        return ""


@dataclass
class _Activation:
    commands: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    pack_dir: Optional[Path] = None
    toolbar: bool = False


# -- where plugins live --------------------------------------------------------

def bundled_plugins_dir() -> Path:
    return app_root() / "plugins"


def user_plugins_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "IngeCAD" / "plugins"


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
            if spec.i18n_dir is not None and Path(spec.i18n_dir).is_dir():
                host.add_pack_dir(Path(spec.i18n_dir))
                record.pack_dir = Path(spec.i18n_dir)
            if spec.toolbar:
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


def _bind(handler: Callable, ctx: PluginContext) -> Callable:
    def run(*args):
        return handler(ctx, *args)
    return run


def _starter(ctx: PluginContext, name: str) -> Callable:
    def run(*args):
        ctx.start_tool(name)
    return run
