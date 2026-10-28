# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Intersection snap on curves (#82, Arthur with 0.6.6 on Windows).

INT answered only where two straight segments crossed: arcs, circles and
a polyline's curved segments never offered one. Each case here is the
cursor passed over the crossing with only INT on, as the user does.
"""
from __future__ import annotations

import pytest

from core import actions


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


def _hover(win, x, y):
    t = win.tools
    if t.tool is None:
        win.dispatcher.submit("LINE")        # snaps answer a point prompt
    t.osnap_on = True
    t.osnap_modes = {"INT"}
    t.on_hover(x, y, threshold_world=1.0)
    return t.snap_hit


@pytest.mark.parametrize("build, cursor, expected", [
    # two circles
    (lambda: [actions.add_circle((0, 0), 5), actions.add_circle((6, 0), 5)],
     (3.2, 4.1), (3.0, 4.0)),
    # an arc and a line
    (lambda: [actions.add_arc_geom(((0, 0), 5, 0, 180)), actions.add_line((-6, 3), (6, 3))],
     (4.2, 3.1), (4.0, 3.0)),
    # a polyline's curved segment and a line
    (lambda: [actions.add_polyline_ex([(0, -5, 0, 0, -1), (0, 5, 0, 0, 0), (10, 5, 0, 0, 0)]),
              actions.add_line((-10, 0), (20, 0))],
     (-4.8, 0.2), (-5.0, 0.0)),
])
def test_int_snaps_where_curves_cross(win, build, cursor, expected):
    for command in build():
        win.tools._execute(command)
    hit = _hover(win, *cursor)
    assert hit is not None and hit.kind == "INT"
    assert (hit.x, hit.y) == pytest.approx(expected)


def test_no_int_outside_an_arcs_sweep(win):
    win.tools._execute(actions.add_arc_geom(((0, 0), 5, 0, 90)))
    win.tools._execute(actions.add_line((-10, -3), (10, -3)))
    assert _hover(win, 4.0, -3.0) is None
