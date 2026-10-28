# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Typed answers at "Select objects:", as AutoCAD's SELECT takes them.

Found by the release tour (2026-10-10): anything typed at a Select Objects
prompt but Enter was ignored -- "MOVE, ALL, Enter", the AutoCAD hand's
first reflex, did nothing. Every test types on the command line.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    window = MainWindow()
    window.show()
    window.new_document()
    qapp.processEvents()
    for start, end in (("0,0", "10,0"), ("0,5", "10,5"), ("20,0", "30,0")):
        for text in ("LINE", start, end, ""):
            _type(window, text)
    yield window
    window.document.dirty = False
    window.close()


def _type(win, text):
    edit = win.command_line.input
    edit.setFocus()
    if text:
        QTest.keyClicks(edit, text)
    QTest.keyClick(edit, Qt.Key_Return)


def _lines(win):
    return list(win.document.modelspace().query("LINE"))


def _history(win):
    return win.command_line.history.toPlainText()


def test_move_all(win):
    for text in ("MOVE", "ALL", "", "0,0", "0,100"):
        _type(win, text)
    assert all(l.dxf.start.y >= 100 for l in _lines(win))
    assert "3 found" in _history(win) or "3 encontrado(s)" in _history(win)


def test_erase_last(win):
    for text in ("ERASE", "L", ""):
        _type(win, text)
    assert sorted(l.dxf.start.x for l in _lines(win)) == [0.0, 0.0]


def test_previous_takes_the_last_commands_set(win):
    for text in ("MOVE", "W", "-1,-1", "11,1", "", "0,0", "0,50"):
        _type(win, text)
    moved = [l for l in _lines(win) if l.dxf.start.y >= 50]
    assert len(moved) == 1, "Window took only the line fully inside"
    for text in ("MOVE", "P", "", "0,0", "0,10"):
        _type(win, text)
    assert moved[0].dxf.start.y == pytest.approx(60)


def test_crossing_takes_what_it_touches(win):
    for text in ("ERASE", "C", "5,-1", "6,6", ""):
        _type(win, text)
    assert [l.dxf.start.x for l in _lines(win)] == [20.0]


def test_remove_mode_and_undo(win):
    for text in ("ERASE", "ALL", "R", "C", "19,-1", "21,1", "A", "U", ""):
        _type(win, text)
    # ALL (3), remove the third, then Add mode and U undid that removal
    assert _lines(win) == []


def test_an_invalid_answer_says_so_and_asks_again(win):
    for text in ("ERASE", "XYZ"):
        _type(win, text)
    text = _history(win)
    assert "Invalid selection" in text or "Selección no válida" in text
    assert win.tools._selecting_for is not None, "still selecting"
    win.tools.cancel()
