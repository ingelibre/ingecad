# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""CHAMFER as the reference has it (p. 313): lines and polyline segments,
Distance and Angle methods, Polyline, Multiple, Undo, picked sides kept,
properties kept.

GeoCad Yaguarete (Fernando Bellocchio's plugin) had to add most of it: ours
took lines only, dropped their layer, left a zero-length line at distance
0 and offered two options.
"""
from __future__ import annotations

import pytest

from core import trimmode
from test_editing import Harness
from tools.modify import ChamferTool


@pytest.fixture(autouse=True)
def reset():
    saved = (ChamferTool.dist1, ChamferTool.dist2, ChamferTool.length,
             ChamferTool.angle, ChamferTool.method)
    trimmode.set_trimmode(True)
    yield
    (ChamferTool.dist1, ChamferTool.dist2, ChamferTool.length,
     ChamferTool.angle, ChamferTool.method) = saved
    trimmode.set_trimmode(True)


def _run(h, *steps):
    tool = ChamferTool(h.ctx)
    tool.start()
    for step in steps:
        if isinstance(step, tuple):
            tool.on_point(step)
        elif step == "":
            tool.on_enter()
        else:
            tool.on_option(step)
    return tool


def _lines(h):
    return sorted((round(l.dxf.start.x, 6), round(l.dxf.start.y, 6),
                   round(l.dxf.end.x, 6), round(l.dxf.end.y, 6))
                  for l in h.msp.query("LINE"))


def test_distance_zero_meets_at_the_corner_without_a_zero_line():
    h = Harness()
    h.msp.add_line((0, 0), (8, 0))
    h.msp.add_line((10, 2), (10, 10))
    _run(h, "D", "0", "0", (4, 0), (10, 6))
    assert _lines(h) == [(0, 0, 10, 0), (10, 0, 10, 10)]


def test_each_piece_keeps_its_line_properties():
    h = Harness()
    h.document.doc.layers.add("MUROS")
    h.msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "MUROS", "color": 1})
    h.msp.add_line((10, 0), (10, 10), dxfattribs={"layer": "MUROS", "color": 1})
    _run(h, "D", "2", "2", (4, 0), (10, 6))
    assert {(l.dxf.layer, l.dxf.color) for l in h.msp.query("LINE")} == {
        ("MUROS", 1)}, "a piece came out on the current layer"
    assert len(h.msp.query("LINE")) == 3


def test_crossing_lines_keep_the_picked_sides():
    h = Harness()
    h.msp.add_line((0, 0), (20, 0))
    h.msp.add_line((10, -10), (10, 10))
    _run(h, "D", "2", "3", (17, 0), (10, 7))
    assert _lines(h) == [(10, 3, 10, 10), (12, 0, 10, 3), (12, 0, 20, 0)]


def test_the_angle_method():
    h = Harness()
    h.msp.add_line((0, 0), (10, 0))
    h.msp.add_line((10, 0), (10, 10))
    # 2 along the first line at 45 degrees: 2 along the second too
    _run(h, "A", "2", "45", (4, 0), (10, 6))
    assert (8, 0, 10, 2) in _lines(h) or (10, 2, 8, 0) in _lines(h)
    assert ChamferTool.method == "A"


def test_two_segments_of_a_polyline_are_bevelled_inside_it():
    h = Harness()
    h.msp.add_lwpolyline([(0, 0), (10, 0), (10, 10)])
    _run(h, "D", "2", "2", (5, 0), (10, 5))
    [poly] = h.msp.query("LWPOLYLINE")
    assert [tuple(round(v, 6) for v in p) for p in poly.get_points("xy")] == [
        (0, 0), (8, 0), (10, 2), (10, 10)]


def test_a_line_joins_a_polyline_end_with_its_bevel():
    h = Harness()
    h.msp.add_lwpolyline([(0, 10), (0, 0), (10, 0)])
    h.msp.add_line((12, 2), (12, 10))
    _run(h, "D", "1", "1", (5, 0), (12, 6))
    assert not h.msp.query("LINE")
    [poly] = h.msp.query("LWPOLYLINE")
    assert [tuple(round(v, 6) for v in p) for p in poly.get_points("xy")] == [
        (0, 10), (0, 0), (11, 0), (12, 1), (12, 10)]


def test_polyline_option_bevels_every_corner():
    h = Harness()
    square = h.msp.add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 10)])
    square.closed = True
    _run(h, "D", "1", "1", "P", (5, 0))
    [poly] = h.msp.query("LWPOLYLINE")
    assert len(poly) == 8
    assert any("4" in p for p in h.prompts)


def test_multiple_and_undo():
    h = Harness()
    h.ctx.undo_last = h.history.undo
    h.msp.add_line((0, 0), (10, 0))
    h.msp.add_line((10, 0), (10, 10))
    tool = _run(h, "D", "1", "1", "M", (5, 0), (10, 5))
    assert len(h.msp.query("LINE")) == 3
    assert not h.finished, "Multiple asks again"
    tool.on_option("U")
    assert len(h.msp.query("LINE")) == 2
