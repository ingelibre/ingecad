# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""BOUNDARY keeps curves curved (#83, Arthur with 0.6.6).

The boundary was made of the tracer's chords, so along an arc it drifted
off the curve -- "clearances" that showed when zooming in. AutoCAD makes
the arc a curved polyline segment. Each case: BOUNDARY typed, a click
inside the region, and the polyline measured against the original curve.
"""
from __future__ import annotations

import math

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


def _boundary(win, point):
    before = set(e.dxf.handle for e in win.document.modelspace().query("LWPOLYLINE"))
    win.dispatcher.submit("BOUNDARY")
    win.tools.on_click(*point)
    win.tools.on_text("")
    made = [e for e in win.document.modelspace().query("LWPOLYLINE")
            if e.dxf.handle not in before]
    assert len(made) == 1
    return made[0]


def _off_curve(poly, center, radius) -> float:
    """How far the polyline's curved segments are from the circle: their
    ends off it, and their own centre and radius against it."""
    from core.dimassoc import _bulge_arc

    rows = list(poly.get_points("xyb"))
    worst = 0.0
    for i, (x, y, b) in enumerate(rows):
        if abs(b) < 1e-12:
            continue
        q = rows[(i + 1) % len(rows)]
        cx, cy, r, *_ = _bulge_arc((x, y), (q[0], q[1]), b)
        for px, py in ((x, y), (q[0], q[1])):
            worst = max(worst, abs(math.hypot(px - center[0], py - center[1]) - radius))
        worst = max(worst, math.hypot(cx - center[0], cy - center[1]), abs(r - radius))
    return worst


def test_a_region_with_an_arc_side_gets_one_curved_segment(win):
    t = win.tools
    # a room 10 x 5 whose top is a half circle of radius 5
    t._execute(actions.add_line((0, 0), (10, 0)))
    t._execute(actions.add_line((10, 0), (10, 5)))
    t._execute(actions.add_line((0, 5), (0, 0)))
    t._execute(actions.add_arc_geom(((5, 5), 5, 0, 180)))
    poly = _boundary(win, (5, 2))
    rows = list(poly.get_points("xyb"))
    assert len(rows) == 4, rows             # 3 straight sides + 1 arc
    bulges = [b for _x, _y, b in rows if abs(b) > 1e-9]
    assert len(bulges) == 1 and abs(bulges[0]) == pytest.approx(1.0, abs=1e-6)
    # every point of the curved segment lies on the arc (it was ~0.0006 off)
    assert _off_curve(poly, (5, 5), 5) < 1e-9


def test_a_circle_becomes_two_half_circles(win):
    win.tools._execute(actions.add_circle((0, 0), 3))
    poly = _boundary(win, (0.5, 0.5))
    rows = list(poly.get_points("xyb"))
    assert len(rows) == 2
    assert [abs(b) for *_p, b in rows] == pytest.approx([1.0, 1.0], abs=1e-6)
    assert _off_curve(poly, (0, 0), 3) < 1e-9


def test_a_straight_chord_stays_straight(win):
    t = win.tools
    t._execute(actions.add_circle((0, 0), 5))
    t._execute(actions.add_line((-6, 3), (6, 3)))     # cuts the cap off
    poly = _boundary(win, (0, 4))
    rows = list(poly.get_points("xyb"))
    assert len(rows) == 2
    straight = [r for r in rows if abs(r[2]) < 1e-12]
    assert len(straight) == 1, "the chord became a curve"
