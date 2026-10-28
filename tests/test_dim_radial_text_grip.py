# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The text grip of a radius or diameter dimension re-lays it out.

Rafael's sixth review (#67): dragging a radial dimension's text around the
circle moved the number alone -- the dimension line and the arrow stayed
where they were, pointing at nothing. In AutoCAD the line turns to follow
the text and the arrow walks around the circle.
"""
from __future__ import annotations

import math

import pytest

from core import actions
from core.select import entity_grips


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


def _line_angles(win, dim):
    """Directions (degrees) from the centre of every line end in the block."""
    angles = set()
    for e in win.document.doc.blocks[dim.dxf.geometry]:
        if e.dxftype() != "LINE":
            continue
        for p in (e.dxf.start, e.dxf.end):
            if math.hypot(p.x, p.y) > 1.0:
                angles.add(round(math.degrees(math.atan2(p.y, p.x))) % 360)
    return angles


@pytest.mark.parametrize("make", [actions.dim_radius, actions.dim_diameter])
def test_the_line_follows_the_dragged_text(win, make):
    win.tools._execute(make((0.0, 0.0), 10.0, (14.0, 0.0)))
    dim = [e for e in win.document.modelspace() if e.dxftype() == "DIMENSION"][-1]
    assert 0 in _line_angles(win, dim)
    handle = dim.dxf.handle
    grip = next((x, y, role, handle, i)
                for i, (x, y, role) in enumerate(entity_grips(dim))
                if role == "dim_text")
    win.tools.selection = {handle}
    win.tools.begin_grip_drag(grip)
    win.tools.update_grip_drag(0.0, 16.0)
    win.tools.finish_grip_drag(0.0, 16.0)
    assert 90 in _line_angles(win, dim), "the line stayed where it was"
    assert 0 not in _line_angles(win, dim)
    win.history.undo()
    assert 0 in _line_angles(win, dim)
