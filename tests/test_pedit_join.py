# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""PEDIT Join (reference p.1437): lines and arcs into one polyline.

A tester called it "a very important function in the workflow" (#89):
the AutoCAD hand draws a contour with LINE, then PEDIT, picks a line,
answers Y, Join, selects the rest -- and expects one polyline, closed when
the contour closes, so that AREA and HATCH take it. Every test types on
the command line.
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
    yield window
    window.document.dirty = False
    window.close()


def _type(win, text):
    edit = win.command_line.input
    edit.setFocus()
    if text:
        QTest.keyClicks(edit, text)
    QTest.keyClick(edit, Qt.Key_Return)


def _draw(win, *points):
    _type(win, "LINE")
    for point in points:
        _type(win, point)
    _type(win, "")


def _kinds(win):
    return sorted(e.dxftype() for e in win.document.modelspace())


def _history(win):
    return win.command_line.history.toPlainText()


def test_a_closed_contour_of_lines_becomes_one_closed_polyline(win):
    _draw(win, "0,0", "10,0", "10,5", "0,5", "0,0")
    picked = win.document.modelspace().query("LINE")[0]
    picked.dxf.layer = "MUROS"           # the polyline is the picked line
    for text in ("PEDIT", "5,0", "Y", "J", "ALL", ""):
        _type(win, text)
    assert "3 segments added to polyline" in _history(win) \
        or "3 segmentos añadidos a la polilínea" in _history(win)
    _type(win, "")                       # eXit
    assert win.tools.tool is None

    assert _kinds(win) == ["LWPOLYLINE"]
    (poly,) = win.document.modelspace().query("LWPOLYLINE")
    assert poly.closed
    assert sorted((round(x, 9), round(y, 9)) for x, y in poly.get_points("xy")) \
        == [(0, 0), (0, 5), (10, 0), (10, 5)]
    assert poly.dxf.layer == "MUROS"

    win.history.undo()                   # the join...
    assert _kinds(win) == ["LINE", "LINE", "LINE", "LWPOLYLINE"]
    win.history.undo()                   # ...then the conversion
    assert _kinds(win) == ["LINE"] * 4


def test_join_takes_an_arc_and_leaves_what_does_not_touch(win):
    _draw(win, "0,0", "10,0")
    _type(win, "ARC")                    # from the line's end, bulging up
    for text in ("10,0", "15,5", "20,0"):
        _type(win, text)
    _draw(win, "50,50", "60,50")         # far away: not part of the chain
    for text in ("PEDIT", "5,0", "Y", "J", "ALL", "", ""):
        _type(win, text)

    assert _kinds(win) == ["LINE", "LWPOLYLINE"]
    (poly,) = win.document.modelspace().query("LWPOLYLINE")
    assert not poly.closed
    rows = poly.get_points("xyb")
    assert [(round(x, 6), round(y, 6)) for x, y, _b in rows] == [
        (0, 0), (10, 0), (20, 0)]
    assert rows[1][2] == pytest.approx(-1.0)   # a half circle, clockwise
    (line,) = win.document.modelspace().query("LINE")
    assert line.dxf.start.x == pytest.approx(50)


def test_a_closed_polyline_cannot_take_more(win):
    _type(win, "RECTANG")
    for text in ("0,0", "10,5"):
        _type(win, text)
    _draw(win, "10,5", "20,5")
    for text in ("PEDIT", "0,2", "J"):
        _type(win, text)
    assert "Cannot join to a closed polyline." in _history(win) \
        or "No se puede juntar a una polilínea cerrada." in _history(win)
    _type(win, "")
    assert _kinds(win) == ["LINE", "LWPOLYLINE"]
