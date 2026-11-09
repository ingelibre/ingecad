# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Shift or Ctrl + right-click with a hot grip opens the object snap
menu, and the snap chosen lasts that grip's drop only.

Any right click dropped the hot grip, Shift held or not: the one-shot
snap menu a command offers could not be reached while stretching a grip.
A plugin filtered the viewport's events to get it.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from tests.test_grip_typed_point import _hot_end_grip, _type, win  # noqa: F401


@pytest.mark.parametrize("modifier", [Qt.ShiftModifier, Qt.ControlModifier])
def test_modified_right_click_keeps_the_grip_and_opens_the_menu(
        win, qapp, modifier):
    _hot_end_grip(win)
    opened = []
    win.show_osnap_menu = lambda pos: opened.append(pos)
    QTest.mouseClick(win.viewport, Qt.RightButton, modifier, QPoint(200, 200))
    qapp.processEvents()
    assert opened and win.tools.grip_hot()
    QTest.mouseClick(win.viewport, Qt.RightButton, Qt.NoModifier,
                     QPoint(200, 200))                      # the control
    assert not win.tools.grip_hot()


def test_the_snap_chosen_lasts_the_drop_only(win):
    _type(win, "LINE", "0,20", "10,20", "")
    line = _hot_end_grip(win)
    tools = win.tools
    assert tools.set_osnap_override({"MID"})
    tools.on_hover(5.3, 20.4, threshold_world=1.0)
    assert tools.snap_hit is not None and tools.snap_hit.kind == "MID"
    tools.finish_grip_drag(*tools.grip_target(5.3, 20.4))
    assert (line.dxf.end.x, line.dxf.end.y) == (5, 20)
    assert tools.osnap_override is None
