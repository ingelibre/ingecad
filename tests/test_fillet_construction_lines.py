# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""FILLET rounds xlines and rays with lines, as classic CAD does.

A tester lays out with construction lines and FILLET answered "FILLET
joins lines, arcs, circles and polyline segments.". The xline keeps the
side picked, from the fillet out to infinity: a ray. A ray keeps a ray, or
a line when the side picked runs back to its base.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    w = MainWindow()
    w.show()
    w.new_document()
    w.tools.osnap_on = False
    yield w
    w.document.dirty = False
    w.close()


def _pick(win, x, y):
    t = win.tools
    t.on_hover(x, y, threshold_world=0.3)
    t.on_click(x, y)


def _fillet(win, radius, first, second):
    win._on_command_submitted("FILLET")
    win._on_command_submitted("R")
    win._on_command_submitted(str(radius))
    _pick(win, *first)
    _pick(win, *second)
    win.tools.cancel()


def _of(win, kind):
    return [e for e in win.document.modelspace() if e.dxftype() == kind]


def _xy(v):
    return (v.x, v.y)


def _ends(line):
    """A line's ends, rounded, in a fixed order."""
    return sorted((round(v.x, 6) + 0.0, round(v.y, 6) + 0.0)
                  for v in (line.dxf.start, line.dxf.end))


def test_an_xline_and_a_line_at_radius_zero(win):
    from core import actions

    win.tools._execute(actions.add_xline((0, 0), 0.0))         # y = 0
    win.tools._execute(actions.add_line((10, -5), (10, 20)))
    _fillet(win, 0, (-5, 0), (10, 10))
    (ray,) = _of(win, "RAY")
    (line,) = _of(win, "LINE")
    assert not _of(win, "XLINE")
    assert _xy(ray.dxf.start) == pytest.approx((10, 0), abs=1e-6)
    assert _xy(ray.dxf.unit_vector) == pytest.approx((-1, 0), abs=1e-9)
    assert _ends(line) == [(10, 0), (10, 20)]


def test_an_xline_and_a_line_with_a_radius(win):
    from core import actions

    win.tools._execute(actions.add_xline((0, 0), 0.0))
    win.tools._execute(actions.add_line((10, -5), (10, 20)))
    _fillet(win, 2, (-5, 0), (10, 10))
    (ray,) = _of(win, "RAY")
    (arc,) = _of(win, "ARC")
    assert _xy(ray.dxf.start) == pytest.approx((8, 0), abs=1e-6)
    assert _xy(arc.dxf.center) == pytest.approx((8, 2), abs=1e-6)
    assert arc.dxf.radius == pytest.approx(2.0)


def test_two_xlines_leave_two_rays(win):
    from core import actions

    win.tools._execute(actions.add_xline((0, 0), 0.0))
    win.tools._execute(actions.add_xline((0, 0), 90.0))
    _fillet(win, 0, (5, 0), (0, 5))
    rays = _of(win, "RAY")
    assert len(rays) == 2 and not _of(win, "XLINE")
    dirs = sorted(_xy(r.dxf.unit_vector) for r in rays)
    assert dirs == [pytest.approx((0, 1), abs=1e-9),
                    pytest.approx((1, 0), abs=1e-9)]


def test_a_ray_picked_toward_its_base_becomes_a_line(win):
    from core import actions

    win.tools._execute(actions.add_ray((-20, 0), 0.0))         # from x=-20 on
    win.tools._execute(actions.add_line((10, -5), (10, 20)))
    _fillet(win, 0, (-5, 0), (10, 10))
    (line_a, line_b) = sorted(_of(win, "LINE"),
                              key=lambda e: e.dxf.start.y)
    assert not _of(win, "RAY")
    assert _ends(line_a) == [(-20, 0), (10, 0)]


def test_an_xline_with_an_arc_says_so(win):
    from core import actions

    win.tools._execute(actions.add_xline((0, 0), 0.0))
    win.tools._execute(actions.add_circle((0, 10), 3))
    _fillet(win, 1, (-5, 0), (0, 7))
    assert len(_of(win, "XLINE")) == 1
    assert "construction line" in win.command_line.history.toPlainText()
