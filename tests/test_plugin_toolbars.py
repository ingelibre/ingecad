# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A plugin may have several toolbars, buttons with a stable key, and
find its bars through the context (toolbars, ToolbarItem.key,
ctx.toolbar; level 2).

A third-party plugin wrapped the window's add_toolbar to build a second
bar of its own, tagged each button by hand, and read the window's
private dict of plugin bars to find them again.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QToolBar

from core.plugins import LoadedPlugin, PluginSpec, ToolbarItem, ToolbarSpec

PLUGIN = "ejemplo_barras"
EXTRA = f"plugin_{PLUGIN}_datos_toolbar"


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w.new_document()
    spec = PluginSpec(
        id=PLUGIN, name="Barras",
        toolbar=(ToolbarItem("Line", "LINE"),),
        toolbars=(ToolbarSpec("datos", "Data", (
            ToolbarItem("Circle", "CIRCLE", key="mi_circulo"),
            ToolbarItem("Arc", "ARC"))),))
    w.plugins.loaded[spec.id] = LoadedPlugin(spec.id, Path("."), False,
                                             spec=spec)
    assert w.plugins.activate(spec.id)
    yield w
    w.plugins.set_toolbar_enabled(PLUGIN, False)
    w.plugins.deactivate(PLUGIN)
    w.plugins.loaded.pop(PLUGIN, None)
    settings = QSettings()
    settings.remove(w.plugins.TOOLBAR_SETTING.format(id=PLUGIN))
    settings.remove(f"toolbars/{EXTRA}")
    w.document.dirty = False
    w.close()


def _bar(win, name):
    return win.findChild(QToolBar, name)


def test_every_bar_comes_with_the_plugin_s_toolbar_setting(win, qapp):
    assert win.plugins.has_toolbar(PLUGIN)
    ctx = win.plugins.context()
    assert ctx.toolbar(PLUGIN) is None                 # off by default
    win.plugins.set_toolbar_enabled(PLUGIN, True)
    main, extra = ctx.toolbar(PLUGIN), ctx.toolbar(PLUGIN, "datos")
    assert main is _bar(win, f"plugin_{PLUGIN}_toolbar")
    assert extra is _bar(win, EXTRA)
    assert extra.windowTitle() == "Data"
    keys = [a.property("plugin_key") for a in extra.actions()]
    assert keys == ["mi_circulo", "ARC"]
    win.plugins.set_toolbar_enabled(PLUGIN, False)
    qapp.processEvents()
    assert _bar(win, EXTRA) is None and ctx.toolbar(PLUGIN, "datos") is None


def test_a_button_runs_its_command(win):
    win.plugins.set_toolbar_enabled(PLUGIN, True)
    bar = win.plugins.context().toolbar(PLUGIN, "datos")
    bar.actions()[0].trigger()
    assert win.tools.tool is not None and win.tools.tool.name == "CIRCLE"


def test_hiding_one_bar_hides_only_it_and_is_remembered(win, qapp):
    win.plugins.set_toolbar_enabled(PLUGIN, True)
    qapp.processEvents()                 # on screen, as the user sees it
    extra = _bar(win, EXTRA)
    assert extra.toggleViewAction().isChecked()
    extra.toggleViewAction().trigger()
    qapp.processEvents()
    assert extra.isHidden()
    assert win.plugins.toolbar_enabled(PLUGIN)          # the others stay
    assert not _bar(win, f"plugin_{PLUGIN}_toolbar").isHidden()
    win.plugins.deactivate(PLUGIN)
    assert _bar(win, EXTRA) is None                      # no trace
    win.plugins.activate(PLUGIN)
    qapp.processEvents()
    assert not _bar(win, f"plugin_{PLUGIN}_toolbar").isHidden()   # control
    assert _bar(win, EXTRA).isHidden()


def test_the_old_private_view_still_answers(win):
    win.plugins.set_toolbar_enabled(PLUGIN, True)
    assert win._plugin_toolbars[PLUGIN] is win.plugins.context().toolbar(PLUGIN)
