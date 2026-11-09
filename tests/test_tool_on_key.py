# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The running tool may take a free function key (Tool.on_key; level 2).

The architecture plugin put a window-wide shortcut on F5 while its wall
tool ran, to flip the wall's justification. The keys the core leaves
free, F4 to F6, now go to the running tool.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest

from core.plugins import LoadedPlugin, PluginSpec
from tools.base import Tool

PLUGIN = "ejemplo_teclas"


class Wall(Tool):
    keys: list = []

    def start(self) -> None:
        self.name = "WALLKEY"
        self.prompt("Specify start point:")

    def on_point(self, point) -> None:
        self.ctx.finish()

    def on_key(self, key: str) -> bool:
        Wall.keys.append(key)
        return key == "F5"


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w.activateWindow()
    QTest.qWaitForWindowActive(w, 5000)
    w.new_document()
    spec = PluginSpec(id=PLUGIN, name="Teclas", tools={"WALLKEY": Wall})
    w.plugins.loaded[spec.id] = LoadedPlugin(spec.id, Path("."), False,
                                             spec=spec)
    assert w.plugins.activate(spec.id)
    Wall.keys = []
    yield w
    w.plugins.deactivate(spec.id)
    w.plugins.loaded.pop(spec.id, None)
    w.document.dirty = False
    w.close()


def _press(win, key):
    QTest.keySequence(win, QKeySequence(key))


def test_a_free_key_reaches_the_running_tool(win):
    win._on_command_submitted("WALLKEY")
    _press(win, "F5")
    _press(win, "F6")
    assert Wall.keys == ["F5", "F6"]
    assert win.tools.tool is not None


def test_without_a_tool_nobody_hears_it(win):
    _press(win, "F5")
    assert Wall.keys == []


def test_the_core_keys_stay_the_core_s(win):
    win._on_command_submitted("WALLKEY")
    ortho = win.tools.ortho_on
    _press(win, "F8")
    assert Wall.keys == []
    assert win.tools.ortho_on != ortho
