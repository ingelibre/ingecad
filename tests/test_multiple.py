# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""MULTIPLE: AutoCAD's way to keep a command running until Esc.

Rafael's seventh review (13:50-15:00) asked for a dimension tool that stays
active "until I press Escape" -- he right-clicked Repeat after every radius.
AutoCAD answers with the MULTIPLE prefix (and with DIM, which IngeCAD has).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from core import actions


def _window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document()
    win.show()
    qapp.processEvents()
    return win


def _type(win, text):
    edit = win.command_line.input
    edit.setFocus()
    if text:
        QTest.keyClicks(edit, text)
    QTest.keyClick(edit, Qt.Key_Return)


def _dims(win):
    return [e for e in win.document.modelspace() if e.dxftype() == "DIMENSION"]


def test_multiple_dimradius_keeps_dimensioning_until_esc(qapp):
    win = _window(qapp)
    try:
        t = win.tools
        t._execute(actions.add_circle((0, 0), 10.0))
        t._execute(actions.add_circle((50, 0), 10.0))
        t.osnap_on = False
        _type(win, "MULTIPLE")
        _type(win, "DIMRADIUS")
        for cx in (0, 50):
            assert t.tool is not None, "the command is not running"
            t.on_hover(cx + 10, 0, threshold_world=1.0)
            t.on_click(cx + 10, 0)                       # the circle
            t.on_hover(cx + 20, 5, threshold_world=1.0)
            t.on_click(cx + 20, 5)                       # the line's location
            qapp.processEvents()                         # MULTIPLE restarts
        assert len(_dims(win)) == 2
        assert t.tool is not None and t.tool.name.upper() == "DIMRADIUS"
        QTest.keyClick(win.command_line.input, Qt.Key_Escape)
        qapp.processEvents()
        assert t.tool is None and t.repeat_name is None, "Esc did not end it"
    finally:
        win.document.dirty = False
        win.close()
