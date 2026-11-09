# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""What is typed with a grip held is the grip's point.

With a grip hot and no command running, the keyboard went to the command
line: an "L" started LINE with the grip still in the hand, and a typed
"@5,0" was an unknown command. Classic CAD's grip mode asks "Specify
stretch point" and reads the answer as a point. A plugin patched the
controller's text handling to get that.
"""
from __future__ import annotations

import pytest


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


def _type(win, *answers):
    for answer in answers:
        win._on_command_submitted(answer)


def _hot_end_grip(win):
    """A line 0,0-10,0, selected, its end grip taken as a click takes it."""
    _type(win, "LINE", "0,0", "10,0", "", "ZOOM", "E")
    line = next(e for e in win.document.modelspace().query("LINE")
                if (e.dxf.start.x, e.dxf.start.y) == (0, 0))
    tools = win.tools
    tools.on_hover(5, 0, threshold_world=0.5)
    tools.on_click(5, 0)
    assert tools.selection == {line.dxf.handle}
    grip = next(g for g in tools.grip_points()
                if (round(g[0], 6), round(g[1], 6)) == (10.0, 0.0))
    tools.begin_grip_drag(grip)
    assert tools.grip_hot()
    return line


def _history(win):
    return win.command_line.history.toPlainText()


def test_a_relative_point_moves_the_grip(win):
    line = _hot_end_grip(win)
    assert "Specify stretch point" in _history(win)
    _type(win, "@5,2")
    assert not win.tools.grip_hot()
    assert (line.dxf.end.x, line.dxf.end.y) == pytest.approx((15.0, 2.0))
    assert "Unknown command" not in _history(win)
    _type(win, "U")
    assert (line.dxf.end.x, line.dxf.end.y) == pytest.approx((10.0, 0.0))


def test_an_absolute_point_moves_the_grip(win):
    line = _hot_end_grip(win)
    _type(win, "20,5")
    assert (line.dxf.end.x, line.dxf.end.y) == pytest.approx((20.0, 5.0))


def test_a_letter_does_not_start_a_command(win):
    line = _hot_end_grip(win)
    _type(win, "L")
    assert win.tools.tool is None
    assert win.tools.grip_hot()
    assert "Expects a point or eXit" in _history(win)
    assert (line.dxf.end.x, line.dxf.end.y) == pytest.approx((10.0, 0.0))


def test_exit_lets_the_grip_go(win):
    line = _hot_end_grip(win)
    win.tools.update_grip_drag(30, 30)
    _type(win, "X")
    assert not win.tools.grip_hot()
    assert (line.dxf.end.x, line.dxf.end.y) == pytest.approx((10.0, 0.0))


def _marker_pixels(win) -> int:
    """Pixels of the object snap marker's colour the tool layer paints."""
    from PySide6.QtGui import QColor, QImage, QPainter

    vp = win.viewport
    image = QImage(vp.width(), vp.height(), QImage.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    vp._draw_tool_feedback(painter)
    painter.end()
    marker = vp.MARKER_COLOR.rgb()
    return sum(1 for y in range(image.height()) for x in range(image.width())
               if image.pixel(x, y) == marker)


def test_a_hot_grip_shows_where_it_snaps(win):
    win.tools.osnap_on = True
    _type(win, "LINE", "20,10", "30,10", "")
    _hot_end_grip(win)
    _type(win, "ZOOM", "E")
    win.tools.on_hover(20.05, 10.05)
    assert win.tools.snap_hit is not None
    assert _marker_pixels(win) > 0
