# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""ZOOM Window takes its corners like any point prompt (#80, Arthur).

The window was a drag on the canvas with no object snaps. AutoCAD asks
"Specify first corner:" and "Specify opposite corner:" and the snaps
work there, in the Model tab and in a layout.
"""
from __future__ import annotations

import pytest

from core import actions


def _type(win, text):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    edit = win.command_line.input
    edit.setFocus()
    QTest.keyClicks(edit, text)
    QTest.keyClick(edit, Qt.Key_Return)


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    window = MainWindow()
    window.show()
    window.resize(1000, 700)
    window.new_document()
    qapp.processEvents()
    yield window
    window.document.dirty = False
    window.close()


def test_zoom_window_corners_snap_to_the_ends_of_a_line(win):
    t = win.tools
    t._execute(actions.add_line((100, 200), (160, 230)))
    _type(win, "ZOOM")
    _type(win, "W")
    assert t.tool is not None and t.tool.name == "ZOOMWINDOW"
    assert "first corner" in win.command_line.history.toPlainText().splitlines()[-1]
    t.osnap_on = True
    t.osnap_modes = {"END"}
    # each click lands a little off the end: the END snap corrects it
    for x, y in ((100.4, 199.7), (159.6, 230.3)):
        t.on_hover(x, y, threshold_world=2.0)
        assert t.snap_hit is not None
        t.on_click(x, y)
    assert t.tool is None
    x0, y0, x1, y1 = win.viewport._view_world_rect()
    # the window fits the line exactly in one direction, centred on it
    assert ((x0 + x1) / 2, (y0 + y1) / 2) == pytest.approx((130, 215))
    assert (x1 - x0 == pytest.approx(60)) or (y1 - y0 == pytest.approx(30))


def test_typed_corners_work_too(win):
    for text in ("Z", "W", "0,0", "40,10"):
        _type(win, text)
    x0, y0, x1, y1 = win.viewport._view_world_rect()
    assert ((x0 + x1) / 2, (y0 + y1) / 2) == pytest.approx((20, 5))
