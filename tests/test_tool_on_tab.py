# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Tab goes to the running tool's own fields (Tool.on_tab).

CAD dynamic input moves between a length and an angle with Tab, fixing
the one typed. A tool with fields of its own -- the architecture plugin's
temporary dimensions of a wall or a door -- gets Tab and Shift+Tab with
what is typed in the command line, in the command line or over the
canvas. A tool that does not want it leaves Tab to Qt, as before.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from core.plugins import LoadedPlugin, PluginSpec
from tools.base import Tool

PLUGIN = "ejemplo_tab"


class Fields(Tool):
    got: list = []
    wants = True

    def start(self) -> None:
        self.name = "FIELDS"
        self.prompt("Specify next point:")

    def on_point(self, point) -> None:
        self.ctx.finish()

    def on_tab(self, text: str, backwards: bool = False) -> bool:
        Fields.got.append((text, backwards))
        return Fields.wants


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w.activateWindow()
    QTest.qWaitForWindowActive(w, 5000)
    w.new_document()
    spec = PluginSpec(id=PLUGIN, name="Tab", tools={"FIELDS": Fields})
    w.plugins.loaded[spec.id] = LoadedPlugin(spec.id, Path("."), False,
                                             spec=spec)
    assert w.plugins.activate(spec.id)
    Fields.got, Fields.wants = [], True
    yield w
    w.plugins.deactivate(spec.id)
    w.plugins.loaded.pop(spec.id, None)
    w.document.dirty = False
    w.close()


def test_tab_in_the_command_line_takes_the_typed_text(win):
    win._on_command_submitted("FIELDS")
    edit = win.command_line.input
    edit.setFocus()
    QTest.keyClicks(edit, "5")
    QTest.keyClick(edit, Qt.Key_Tab)
    QTest.keyClick(edit, Qt.Key_Backtab, Qt.ShiftModifier)
    assert Fields.got == [("5", False), ("", True)]
    assert edit.text() == ""
    assert edit.hasFocus()                # the focus did not move on
    assert win.tools.tool is not None


def test_tab_over_the_canvas(win):
    win._on_command_submitted("FIELDS")
    QTest.keyClicks(win.command_line.input, "30")
    win.viewport.setFocus()
    QTest.keyClick(win.viewport, Qt.Key_Tab)
    assert Fields.got == [("30", False)]
    assert win.command_line.input.text() == ""


def test_a_tool_that_does_not_use_it_keeps_the_text(win):
    Fields.wants = False
    win._on_command_submitted("FIELDS")
    edit = win.command_line.input
    edit.setFocus()
    QTest.keyClicks(edit, "7")
    QTest.keyClick(edit, Qt.Key_Tab)
    assert Fields.got == [("7", False)]
    assert edit.text() == "7"


def test_without_a_tool_nobody_hears_it(win):
    edit = win.command_line.input
    edit.setFocus()
    QTest.keyClick(edit, Qt.Key_Tab)
    assert Fields.got == []


def test_the_default_tool_does_not_take_it():
    assert Tool.on_tab(object.__new__(Tool), "5") is False
