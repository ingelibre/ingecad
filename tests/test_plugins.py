# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The plugin contract (docs/plugins.md), held from both sides.

What a plugin gets when it is on -- its command, alias, tool, menu, toolbar,
language pack and document hook -- and, the property the whole design
rests on, what the host looks like when it is off again: exactly as before.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core import i18n
from core.plugins import PluginManager, load_plugin

FIXTURE = Path(__file__).resolve().parent / "plugins_fixture"


# -- the loader, headless -----------------------------------------------------

def test_a_folder_with_a_spec_loads_and_a_missing_module_is_named():
    manager = PluginManager(host=None, bundled_dir=FIXTURE,
                            user_dir=FIXTURE / "no-such-dir")
    assert manager.discover() == ["ejemplo", "sin_dependencia"]
    sample = manager.loaded["ejemplo"]
    assert sample.available and sample.spec.name == "Sample"
    assert sample.spec.aliases == {"HQ": "HELLO"}
    broken = manager.loaded["sin_dependencia"]
    assert not broken.available
    assert broken.reason == "needs ingecad_no_such_module_xyz"
    assert manager.problems() == [("sin_dependencia", "needs ingecad_no_such_module_xyz")]


def test_a_broken_plugin_never_takes_the_app_down(tmp_path):
    folder = tmp_path / "roto"
    folder.mkdir()
    (folder / "__init__.py").write_text("raise RuntimeError('boom')\n")
    loaded = load_plugin(folder, bundled=False)
    assert not loaded.available
    assert "RuntimeError: boom" in loaded.reason
    (folder / "__init__.py").write_text("PLUGIN = 42\n")
    assert load_plugin(folder, bundled=False).reason == "PLUGIN is not a PluginSpec"


def test_bundled_plugins_default_to_on_and_user_ones_to_off(qapp):
    from PySide6.QtCore import QSettings

    settings = QSettings()
    for key in ("plugins/ejemplo/enabled",):
        settings.remove(key)
    bundled = PluginManager(host=None, bundled_dir=FIXTURE, user_dir=FIXTURE / "x")
    bundled.discover()
    assert bundled.enabled("ejemplo") is True
    user = PluginManager(host=None, bundled_dir=FIXTURE / "x", user_dir=FIXTURE)
    user.discover()
    assert user.enabled("ejemplo") is False
    # the choice persists, and a new manager reads it back
    settings.setValue("plugins/ejemplo/enabled", "false")
    try:
        again = PluginManager(host=None, bundled_dir=FIXTURE, user_dir=FIXTURE / "x")
        again.discover()
        assert again.enabled("ejemplo") is False
    finally:
        settings.remove("plugins/ejemplo/enabled")


# -- through the window ---------------------------------------------------------

def _window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document()
    win.plugins.scan_dir(FIXTURE, bundled=True)
    return win


def _menu_labels(win, title: str) -> list[str]:
    """The entries of the top-level menu called ``title``.

    The action list is held in a local on purpose: PySide hands back
    Python-owned wrappers for ``QMenuBar.actions()``, and letting them die
    inside a generator expression took the menu down with them ("Internal
    C++ object already deleted" on the very next line).
    """
    actions = win._menu_bar.actions()
    menu = next(a.menu() for a in actions if a.text() == title)
    entries = menu.actions()
    return [a.text() for a in entries]


def _snapshot(win) -> dict:
    """Everything a plugin can touch, so that 'no trace' is checkable."""
    from PySide6.QtWidgets import QToolBar

    from views.tool_controller import ALL_TOOL_CLASSES

    d = win.dispatcher
    return {
        "commands": sorted(d._commands),
        "known": d.known_names(),
        "aliases": dict(d.aliases),
        "tools": sorted(ALL_TOOL_CLASSES),
        "menus": [a.text() for a in win._menu_bar.actions()],
        "toolbars": sorted(t.objectName() for t in win.findChildren(QToolBar)
                           if t.parent() is win),
        "localized": sorted(i18n.command_names().items()),
        "packs": i18n.pack_dirs(),
    }


def test_turning_a_plugin_on_gives_it_everything_it_declared(qapp):
    win = _window(qapp)
    echoed = []
    win.command_line.echo = echoed.append
    try:
        assert win.plugins.activate("ejemplo")
        d = win.dispatcher
        assert "HELLO" in d._commands and "ECHOPT" in d._commands
        assert d.resolve_name("HQ") == "HELLO"                 # the alias
        d.submit("HELLO world")
        assert echoed[-1] == "Hello from the sample plugin world"
        d.submit("ECHOPT")                                   # the tool
        assert win.tools.tool is not None and win.tools.tool.name == "ECHOPT"
        win.tools.tool.on_point((1.0, 2.5))
        assert echoed[-1] == "(1.000, 2.500)"
        assert win.tools.tool is None                        # finished
        titles = [a.text() for a in win._menu_bar.actions()]
        assert "Sample" in titles                            # the menu
        labels = _menu_labels(win, "Sample")
        assert labels[0] == "Say hello" and labels[1] == "" and labels[2] == "Points"
        assert "plugin_ejemplo_toolbar" in _snapshot(win)["toolbars"]
        assert Path(FIXTURE / "ejemplo" / "i18n") in i18n.pack_dirs()
    finally:
        win.plugins.deactivate("ejemplo")
        win.close()


def test_turning_it_off_leaves_no_trace(qapp):
    """The property the design rests on: the host after off == before on."""
    win = _window(qapp)
    try:
        before = _snapshot(win)
        assert win.plugins.activate("ejemplo")
        during = _snapshot(win)
        assert during != before, "activation changed nothing: the test is void"
        assert "HELLO" in during["commands"] and "HQ" in during["aliases"]
        win.plugins.deactivate("ejemplo")
        assert _snapshot(win) == before
        # and it comes back whole a second time (nothing was consumed)
        assert win.plugins.activate("ejemplo")
        assert _snapshot(win) == during
        win.plugins.deactivate("ejemplo")
        assert _snapshot(win) == before
    finally:
        win.plugins.deactivate("ejemplo")
        win.close()


def test_the_plugin_pack_joins_the_language_and_leaves_with_it(qapp):
    """Spanish on: the plugin's menu reads in Spanish and HOLA runs HELLO.
    Plugin off: HOLA is unknown again and nothing of the pack remains."""
    win = _window(qapp)
    try:
        i18n.set_language("es")
        win.plugins.activate("ejemplo")
        assert win.dispatcher.resolve_name("HOLA") == "HELLO"
        assert win.dispatcher.resolve_name("HELLO") == "HELLO"     # English never lost
        assert i18n.tr("Say hello") == "Saludar"
        win._build_menus()
        assert "Ejemplo" in [a.text() for a in win._menu_bar.actions()]
        win.plugins.deactivate("ejemplo")
        assert "HOLA" not in i18n.command_names()
        assert i18n.tr("Say hello") == "Say hello"
        # the app's own catalog was never touched
        assert i18n.tr("Layer") != "Layer"
    finally:
        win.plugins.deactivate("ejemplo")
        i18n.set_language("en")
        win.close()


def test_an_alias_the_core_already_answers_to_is_not_taken(qapp):
    from core.plugins import PluginSpec

    win = _window(qapp)
    try:
        win.plugins.loaded["ejemplo"].spec = PluginSpec(
            id="ejemplo", name="Sample", commands={"HELLO": lambda ctx, *a: None},
            aliases={"L": "HELLO", "HQ": "HELLO"})
        assert win.plugins.activate("ejemplo")
        assert win.dispatcher.resolve_name("L") == "LINE"        # untouched
        assert win.dispatcher.resolve_name("HQ") == "HELLO"
        win.plugins.deactivate("ejemplo")
        assert win.dispatcher.resolve_name("L") == "LINE"
        assert win.dispatcher.resolve_name("HQ") != "HELLO"
    finally:
        win.plugins.deactivate("ejemplo")
        win.close()


def test_a_tool_name_the_core_owns_is_refused_whole(qapp):
    from core.plugins import PluginSpec

    win = _window(qapp)
    try:
        before = _snapshot(win)
        win.plugins.loaded["ejemplo"].spec = PluginSpec(
            id="ejemplo", name="Sample", tools={"LINE": object})
        assert win.plugins.activate("ejemplo") is False
        assert _snapshot(win) == before
        assert "already registered" in win.plugins.loaded["ejemplo"].reason
    finally:
        win.close()


def test_the_document_hook_hears_new_and_opened_drawings(qapp):
    import importlib

    win = _window(qapp)
    try:
        win.plugins.activate("ejemplo")
        module = importlib.import_module("ingecad_plugin_ejemplo")
        module.OPENED.clear()
        win.new_document()
        assert module.OPENED and module.OPENED[-1] is win.document
    finally:
        win.plugins.deactivate("ejemplo")
        win.document.dirty = False
        win.close()


def test_the_manager_dialog_toggles_a_plugin(qapp):
    from PySide6.QtCore import QSettings, Qt

    from views.plugins_dialog import PluginsDialog

    win = _window(qapp)
    settings = QSettings()
    try:
        dialog = PluginsDialog(win)
        rows = {dialog.list.item(i).data(Qt.UserRole): dialog.list.item(i)
                for i in range(dialog.list.count())}
        assert {"ejemplo", "sin_dependencia"} <= set(rows)    # plus the bundled ones
        assert not (rows["sin_dependencia"].flags() & Qt.ItemIsUserCheckable)
        assert "needs ingecad_no_such_module_xyz" in rows["sin_dependencia"].text()
        rows["ejemplo"].setCheckState(Qt.Checked)
        assert win.plugins.is_active("ejemplo")
        assert "HELLO" in win.dispatcher._commands
        rows["ejemplo"].setCheckState(Qt.Unchecked)
        assert not win.plugins.is_active("ejemplo")
        assert "HELLO" not in win.dispatcher._commands
        assert str(settings.value("plugins/ejemplo/enabled")).lower() == "false"
    finally:
        settings.remove("plugins/ejemplo/enabled")
        win.plugins.deactivate("ejemplo")
        win.close()


def test_the_plugins_command_and_menu_entry_exist(qapp):
    win = _window(qapp)
    try:
        assert "PLUGINS" in win.dispatcher._commands
        assert "Plugins..." in _menu_labels(win, "Tools")
    finally:
        win.close()


def test_every_bundled_plugin_leaves_no_trace(qapp):
    """The invariant, on the plugins that actually ship: each one off and
    on again returns the host to exactly what it was."""
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        bundled = [pid for pid, p in win.plugins.loaded.items() if p.bundled]
        if not bundled:
            pytest.skip("no bundled plugin under plugins/ yet")
        for pid in bundled:
            assert win.plugins.is_active(pid), f"{pid} is not on by default"
            on = _snapshot(win)
            win.plugins.deactivate(pid)
            off = _snapshot(win)
            assert off != on, f"{pid}: turning it off changed nothing"
            assert win.plugins.activate(pid)
            assert _snapshot(win) == on, f"{pid}: not the same after off/on"
    finally:
        win.close()


# -- the packages carry plugins/ --------------------------------------------------

def test_every_package_ships_the_plugins_folder():
    root = Path(__file__).resolve().parent.parent
    assert (root / "plugins" / "__init__.py").is_file()
    flatpak = (root / "packaging" / "flatpak" / "org.ingecad.IngeCAD.yml").read_text()
    copy_line = next(l for l in flatpak.splitlines() if "cp -a main.py" in l)
    assert " plugins " in copy_line
    spec = (root / "packaging" / "ingecad.spec").read_text()
    assert '(str(ROOT / "plugins"), "plugins")' in spec
