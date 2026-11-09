# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Holding Ctrl turns an arc the other way round, as classic CAD does.

ARC by start, centre and end -- in either order -- sweeps counterclockwise;
with Ctrl down it reaches the same end clockwise. In PLINE's arc mode the
tangent arc bends to the other side. The key is read from the viewport,
while the cursor moves (the preview) and at the click.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.maybe_save_changes = lambda: True
    w.resize(1200, 800)
    w.show()
    w.new_document()
    yield w
    w.document.dirty = False
    w.close()


def _type(win, *texts):
    for text in texts:
        win._on_command_submitted(text)


def _arc(win):
    (arc,) = win.document.modelspace().query("ARC")
    return (round(arc.dxf.start_angle % 360, 6),
            round(arc.dxf.end_angle % 360, 6))


def _ctrl(win, down: bool) -> None:
    """The key itself, pressed over the drawing."""
    if down:
        QTest.keyPress(win.viewport, Qt.Key_Control)
    else:
        QTest.keyRelease(win.viewport, Qt.Key_Control)


def test_start_center_end_sweeps_counterclockwise(win):
    _type(win, "ARC", "10,0", "C", "0,0", "0,10")
    assert _arc(win) == (0.0, 90.0)


def test_ctrl_reaches_the_same_end_clockwise(win):
    _type(win, "ARC", "10,0", "C", "0,0")
    _ctrl(win, True)
    assert win.tools.ctrl_held
    # the preview turns with the key, before any click
    win.tools._cursor = (0.0, 10.0)
    xs = [p[0] for seg in win.tools.tool.preview_segments((0.0, 10.0))
          for p in seg]
    assert min(xs) < -9.0, "the preview still goes the short way"
    _type(win, "0,10")
    _ctrl(win, False)
    # the entity is stored counterclockwise: from the end round to the start
    assert _arc(win) == (90.0, 0.0)
    assert not win.tools.ctrl_held


def test_ctrl_turns_start_end_center_too(win):
    _ctrl(win, True)
    _type(win, "ARC", "10,0", "E", "0,10", "0,0")
    _ctrl(win, False)
    assert _arc(win) == (90.0, 0.0)


def test_released_before_the_click_it_changes_nothing(win):
    _type(win, "ARC", "10,0", "C", "0,0")
    _ctrl(win, True)
    _ctrl(win, False)
    _type(win, "0,10")
    assert _arc(win) == (0.0, 90.0)


def test_pline_arc_bends_the_other_way(win):
    def bulge(ctrl):
        _type(win, "PLINE", "0,0", "10,0", "A")
        _ctrl(win, ctrl)
        _type(win, "10,10", "")
        _ctrl(win, False)
        pl = list(win.document.modelspace().query("LWPOLYLINE"))[-1]
        return [round(p[4], 6) for p in pl.get_points("xyseb")][1]

    assert bulge(False) == pytest.approx(1.0)       # tangent: a half circle
    assert bulge(True) == pytest.approx(-1.0)
