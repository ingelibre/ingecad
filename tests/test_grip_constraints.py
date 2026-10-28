# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A hot grip takes its point the way a command's point is taken (#60,
Arthur): ORTHO from where the grip was grabbed, and object snaps that need
a base -- PERpendicular -- from there too. Driven by real mouse events on
the canvas: click the grip, move, click."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest

from core import actions


def _window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document()
    win.resize(1000, 700)
    win.show()
    qapp.processEvents()
    return win


def _screen(win, x, y) -> QPoint:
    sx, sy = win.viewport.view.world_to_screen(x, y)
    return QPoint(round(sx), round(sy))


def _grab_move_drop(qapp, win, grip, via, drop):
    vp = win.viewport
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, pos=_screen(win, *grip))
    qapp.processEvents()
    assert win.tools._grip_drag is not None, "the grip did not get hot"
    for x, y in (via, drop):
        # the viewport's own move handler, not QTest.mouseMove: under xcb
        # (the CI) that moves the real pointer and the event lands later,
        # after the click -- which then dropped the end unsnapped
        pos = QPointF(_screen(win, x, y))
        vp.mouseMoveEvent(QMouseEvent(
            QEvent.Type.MouseMove, pos, vp.mapToGlobal(pos),
            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier))
        qapp.processEvents()
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, pos=_screen(win, *drop))
    qapp.processEvents()


def test_a_text_moved_by_its_grip_obeys_ortho(qapp):
    win = _window(qapp)
    try:
        win.tools._execute(actions.add_text((0, 0), "A", 2.5))
        text = next(e for e in win.document.modelspace() if e.dxftype() == "TEXT")
        win.viewport.view.zoom_extents(-20, -20, 40, 40)
        win.tools.selection = {text.dxf.handle}
        win.tools.ortho_on = True
        win.tools.osnap_on = False
        _grab_move_drop(qapp, win, (0, 0), (5, 1), (12, 3))
        ins = text.dxf.insert
        assert (ins.x, ins.y) == pytest.approx((12, 0), abs=0.2)
    finally:
        win.document.dirty = False
        win.close()


def test_a_line_end_dragged_by_its_grip_snaps_perpendicular(qapp):
    win = _window(qapp)
    try:
        win.tools._execute(actions.add_line((-10, 0), (30, 0)))       # the target
        win.tools._execute(actions.add_line((0, 10), (8, 14)))       # the one we edit
        moved = [e for e in win.document.modelspace() if e.dxftype() == "LINE"][-1]
        win.viewport.view.zoom_extents(-20, -10, 40, 30)
        win.tools.ortho_on = False
        win.tools.osnap_on = True
        win.tools.osnap_modes = {"PER"}
        win.tools.selection = {moved.dxf.handle}
        # drag the far end (8, 14) near the target, a little off the foot of
        # the perpendicular from the grabbed point: it must land ON the foot
        _grab_move_drop(qapp, win, (8, 14), (8, 5), (8.6, 0.4))
        end = moved.dxf.end
        assert (end.x, end.y) == pytest.approx((8, 0), abs=0.05)
    finally:
        win.document.dirty = False
        win.close()


@pytest.mark.parametrize("modes", [None, {"PER"}])
def test_a_line_shortens_by_dragging_its_end_grip_along_itself(qapp, modes):
    """Rafael's seventh review, 29:13-29:37: "no consigo menguar esto" -- the
    end grip dragged back along the line left it full length. PER measures
    from the grabbed point, which lies on the line, so its foot was the grip
    itself and won: the drop landed where the drag began. Lengthening worked,
    because beyond the end the foot falls off the segment. With the default
    modes, and with PER alone."""
    win = _window(qapp)
    try:
        win.tools._execute(actions.add_line((0, 0), (48, 0)))
        line = [e for e in win.document.modelspace() if e.dxftype() == "LINE"][-1]
        win.viewport.view.zoom_extents(-10, -20, 60, 20)
        win.tools.ortho_on = False
        win.tools.osnap_on = True
        if modes is not None:
            win.tools.osnap_modes = set(modes)
        win.tools.selection = {line.dxf.handle}
        _grab_move_drop(qapp, win, (48, 0), (40, 0), (30, 0))
        end = line.dxf.end
        assert (end.x, end.y) == pytest.approx((30, 0), abs=0.3), (
            "the line did not shorten")
    finally:
        win.document.dirty = False
        win.close()
