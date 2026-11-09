# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The spacebar is Enter, with the focus on the canvas too (#112).

In the command line Space already ended a prompt and, on an empty one,
repeated the last command. Pressed over the drawing -- where the hands are
while drawing -- it did nothing: the canvas forwards the keys it types to
the command line, and Space's text is blank, so it was dropped.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w.new_document()
    w.tools.osnap_on = False
    yield w
    w.document.dirty = False
    w.close()


def _type(win, *texts):
    for text in texts:
        win._on_command_submitted(text)


def _space_on_canvas(win, qapp):
    win.viewport.setFocus()
    qapp.processEvents()
    QTest.keyClick(win.viewport, Qt.Key_Space)
    qapp.processEvents()


def _tool(win):
    return win.tools.tool.name if win.tools.tool is not None else None


def test_space_over_the_canvas_ends_the_command(win, qapp):
    _type(win, "LINE", "0,0", "10,0")
    assert _tool(win) == "LINE"
    _space_on_canvas(win, qapp)
    assert _tool(win) is None
    assert len(win.document.modelspace().query("LINE")) == 1


def test_space_over_the_canvas_repeats_the_last_command(win, qapp):
    _type(win, "CIRCLE", "0,0", "5")
    assert _tool(win) is None
    _space_on_canvas(win, qapp)
    assert _tool(win) == "CIRCLE"


def test_space_in_the_empty_command_line_repeats_too(win, qapp):
    _type(win, "CIRCLE", "0,0", "5")
    edit = win.command_line.input
    edit.setFocus()
    qapp.processEvents()
    QTest.keyClick(edit, Qt.Key_Space)
    qapp.processEvents()
    assert _tool(win) == "CIRCLE"


def test_typed_over_the_canvas_space_still_runs_what_was_typed(win, qapp):
    win.viewport.setFocus()
    qapp.processEvents()
    QTest.keyClicks(win.viewport, "C")
    QTest.keyClick(win.viewport, Qt.Key_Space)
    qapp.processEvents()
    assert _tool(win) == "CIRCLE"
