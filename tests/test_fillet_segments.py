# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""FILLET keeps the picked side of crossing lines, and takes polyline
segments as AutoCAD does (FILLET, p. 801).

GeoCad Yaguarete (Fernando Bellocchio's plugin) had to add all of it:
everything that comes from QGIS is a polyline, and on crossing lines the
old rule kept the end farther from the corner -- often the other side.
"""
from __future__ import annotations

import math

import pytest

from test_editing import Harness
from tools.edit import FilletTool


def _fillet(h, radius, pick1, pick2):
    tool = FilletTool(h.ctx)
    type(tool).radius = radius
    tool.start()
    tool.on_point(pick1)
    tool.on_point(pick2)
    return tool


def _poly(h, points, closed=False):
    poly = h.msp.add_lwpolyline(points, format="xy")
    poly.closed = closed
    return poly


def _rows(poly):
    return [(round(x, 6), round(y, 6), round(b, 6))
            for x, y, *_sw, b in poly.get_points("xyseb")]


def test_crossing_lines_keep_the_picked_sides():
    h = Harness()
    h.msp.add_line((0, 0), (20, 0))
    h.msp.add_line((10, -10), (10, 10))
    _fillet(h, 2.0, (17, 0), (10, 7))            # right of one, top of other
    lines = sorted((round(l.dxf.start.x, 6), round(l.dxf.start.y, 6),
                    round(l.dxf.end.x, 6), round(l.dxf.end.y, 6))
                   for l in h.msp.query("LINE"))
    assert lines == [(10, 2, 10, 10), (12, 0, 20, 0)], lines
    arc = h.msp.query("ARC")[0]
    assert (arc.dxf.center.x, arc.dxf.center.y) == pytest.approx((12, 2))


def test_two_adjacent_segments_of_a_polyline_round_their_corner():
    h = Harness()
    poly = _poly(h, [(0, 0), (10, 0), (10, 10)])
    _fillet(h, 2.0, (5, 0), (10, 5))
    [result] = h.msp.query("LWPOLYLINE")
    assert _rows(result) == [(0, 0, 0), (8, 0, round(math.tan(math.pi / 8), 6)),
                             (10, 2, 0), (10, 10, 0)]
    h.history.undo()
    assert _rows(h.msp.query("LWPOLYLINE")[0]) == [(0, 0, 0), (10, 0, 0),
                                                  (10, 10, 0)]
    assert poly.is_alive


def test_a_segment_between_two_is_replaced_by_the_fillet():
    h = Harness()
    _poly(h, [(0, 0), (9, 0), (10, 1), (10, 10)])
    _fillet(h, 2.0, (4, 0), (10, 6))
    [result] = h.msp.query("LWPOLYLINE")
    assert [r[:2] for r in _rows(result)] == [(0, 0), (8, 0), (10, 2), (10, 10)]


def test_a_closed_polyline_rounds_across_its_closing_vertex():
    h = Harness()
    _poly(h, [(0, 0), (10, 0), (10, 10), (0, 10)], closed=True)
    _fillet(h, 1.0, (0, 5), (5, 0))               # the corner at (0, 0)
    [result] = h.msp.query("LWPOLYLINE")
    assert result.closed
    points = {r[:2] for r in _rows(result)}
    assert (0, 0) not in points and {(0, 1), (1, 0)} <= points


def test_a_line_joins_a_polyline_at_its_end():
    h = Harness()
    _poly(h, [(0, 10), (0, 0), (10, 0)])
    h.msp.add_line((12, 2), (12, 10))
    _fillet(h, 0.0, (5, 0), (12, 6))
    assert not h.msp.query("LINE"), "the line was not joined"
    [result] = h.msp.query("LWPOLYLINE")
    assert [r[:2] for r in _rows(result)] == [(0, 10), (0, 0), (12, 0), (12, 10)]


def test_two_polylines_join_by_their_end_segments():
    h = Harness()
    _poly(h, [(0, 10), (0, 0), (10, 0)])
    _poly(h, [(20, 20), (12, 20), (12, 3)])
    _fillet(h, 2.0, (5, 0), (12, 10))
    [result] = h.msp.query("LWPOLYLINE")
    xy = [r[:2] for r in _rows(result)]
    assert xy[:2] == [(0, 10), (0, 0)] and xy[-2:] == [(12, 20), (20, 20)]
    assert (10, 0) in xy and (12, 2) in xy


def test_a_middle_segment_will_not_join_a_line():
    h = Harness()
    poly = _poly(h, [(0, 0), (10, 0), (10, 10), (20, 10)])
    h.msp.add_line((5, 3), (5, 20))
    _fillet(h, 0.0, (10, 5), (5, 15))
    assert poly.is_alive and len(h.msp.query("LINE")) == 1
    assert any("end segments" in p or "segmentos" in p for p in h.prompts)
