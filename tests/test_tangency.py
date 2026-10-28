# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""TRIM and EXTEND at tangency points (issue #14).

A tangency is an intersection of multiplicity two. The old routine went
through the quadratic's discriminant, whose sign at a tangency is rounding
noise: one of Rafael's tangent lines "missed" the circle and the other
"crossed it twice at the same point", so TRIM found nothing to cut.
"""
from __future__ import annotations

import math

import ezdxf
import pytest

from core import editmath
from tests.test_editing import Harness
from tools.edit import ExtendTool, TrimTool

# Straight from Rafael's drawing (review 5): circle 8B and the two lines
# 89 and 8C, both drawn tangent to it with the TAN object snap.
C = (96.52487440677733, 35.89057912536276)
R = 20.0
LINE_89 = (116.5248744067773, 5.776607380449992,
           116.5248744067773, 39.37660738044997)
LINE_8C = (81.52487440677734, 60.97660738044995,
           102.0192966848205, 55.12105815815192)


def test_rafaels_tangent_lines_touch_the_circle_once():
    # 8C's discriminant came out negative, 89's gave two equal roots
    assert len(editmath.line_circle_intersections(LINE_89, C, R)) == 1
    assert editmath.line_circle_intersections(LINE_8C, C, R) == [1.0]


def test_rafaels_circle_trims_between_its_two_tangents():
    a1 = math.atan2(LINE_89[1] + 0.8962 * (LINE_89[3] - LINE_89[1]) - C[1],
                    LINE_89[0] - C[0])
    a2 = math.atan2(LINE_8C[3] - C[1], LINE_8C[2] - C[0])
    arc = editmath.trim_circle(C, R, [LINE_89, LINE_8C], (a1 + a2) / 2)
    assert arc is not None
    start, end = arc
    # the short arc between the tangency points is gone
    assert end == pytest.approx(0.0, abs=1e-6)
    assert start == pytest.approx(math.degrees(a2) % 360, abs=1e-6)


def test_rafaels_stub_past_the_tangency_trims():
    pieces = editmath.trim_segment(LINE_89, [], [(C, R)], pick_t=0.97)
    assert pieces is not None and len(pieces) == 1
    assert pieces[0][3] == pytest.approx(C[1])        # cut at the tangency


def test_extend_to_a_tangent_circle():
    stub = (C[0] + R, 5.0, C[0] + R, 30.0)
    extended = editmath.extend_segment(stub, [], [(C, R)], pick_t=0.9)
    assert extended is not None
    assert extended[3] == pytest.approx(C[1])


@pytest.mark.parametrize("origin", [(0.0, 0.0), (529_876.0, 8_573_039.0)])
def test_tangent_circles_and_lines_at_any_coordinates(origin):
    # near the origin and at UTM magnitudes, where doubles carry 1e-9
    ox, oy = origin
    c1, c2 = (ox + 0.0, oy + 0.0), (ox + 30.0, oy + 0.0)
    assert len(editmath.circle_circle_intersections(c1, 10.0, c2, 20.0)) == 1
    touching = (ox + 10.0, oy - 5.0, ox + 10.0, oy + 5.0)   # x = 10: tangent
    assert editmath.line_circle_intersections(touching, c1, 10.0) \
        == pytest.approx([0.5])
    # and a real crossing still gives two points
    crossing = (ox + 5.0, oy - 20.0, ox + 5.0, oy + 20.0)
    assert len(editmath.line_circle_intersections(crossing, c1, 10.0)) == 2


def test_trim_tool_cuts_rafaels_circle_between_its_tangents():
    # the workflow of the video, through the real tool and pick index
    h = Harness()
    h.msp.add_line(LINE_89[:2], LINE_89[2:])
    h.msp.add_line(LINE_8C[:2], LINE_8C[2:])
    circle = h.msp.add_circle(C, R)
    h.services.index.invalidate()
    tool = TrimTool(h.ctx)
    tool.start()
    tool.on_selection([])
    a = math.radians(40.0)                     # between the two tangencies
    tool.on_point((C[0] + R * math.cos(a), C[1] + R * math.sin(a)))
    arcs = h.msp.query("ARC")
    assert len(arcs) == 1, h.prompts
    assert circle.dxf.handle not in [e.dxf.handle for e in h.msp]
    assert arcs[0].dxf.end_angle % 360 == pytest.approx(0.0, abs=1e-6)


def test_trim_tool_cuts_a_ttr_circle_between_its_lines():
    h = Harness()
    h.msp.add_line((0, 0), (100, 0))
    h.msp.add_line((0, 0), (0, 100))
    circle = h.msp.add_circle((20, 20), 20)           # tangent to both axes
    h.services.index.invalidate()
    tool = TrimTool(h.ctx)
    tool.start()
    tool.on_selection([])
    tool.on_point((20 - 20 * math.cos(math.radians(45)),
                   20 - 20 * math.sin(math.radians(45))))   # the corner arc
    arcs = h.msp.query("ARC")
    assert len(arcs) == 1 and circle.dxf.handle not in \
        [e.dxf.handle for e in h.msp]
    assert (arcs[0].dxf.start_angle % 360, arcs[0].dxf.end_angle % 360) \
        == pytest.approx((270.0, 180.0))


def test_extend_tool_reaches_a_tangent_circle():
    h = Harness()
    h.msp.add_circle((20, 20), 20)
    line = h.msp.add_line((40, -30), (40, 0))          # x = 40 touches at y 20
    h.services.index.invalidate()
    tool = ExtendTool(h.ctx)
    tool.start()
    tool.on_selection([])
    tool.on_point((40, -1))
    ends = [(l.dxf.start.y, l.dxf.end.y) for l in h.msp.query("LINE")]
    assert ends == [pytest.approx((-30.0, 20.0))]
    assert line is not None


# -- EXTEND an ARC (Rafael's seventh review, 08:46) ------------------------------

def _arc_and_tangent_line(h):
    """An R26 arc from 10° to 150°, and a line tangent to its circle at -10°
    -- outside the arc, so the line can never reach it: the ARC has to be
    extended to the line, as AutoCAD does. IngeCAD answered "EXTEND supports
    LINE and PLINE for now"."""
    r = 26.0
    h.msp.add_arc((0, 0), r, 10, 150)
    t = math.radians(-10)
    touch = (r * math.cos(t), r * math.sin(t))
    down = (math.sin(t), -math.cos(t))
    h.msp.add_line(touch, (touch[0] + 15 * down[0], touch[1] + 15 * down[1]))
    h.services.index.invalidate()
    return r


def test_extend_stretches_an_arc_to_a_tangent_line():
    h = Harness()
    r = _arc_and_tangent_line(h)
    tool = ExtendTool(h.ctx)
    tool.start()
    tool.on_selection([])                                   # every edge
    near_start = (r * math.cos(math.radians(14)), r * math.sin(math.radians(14)))
    tool.on_point(near_start)
    arc = next(iter(h.msp.query("ARC")))
    assert arc.dxf.start_angle % 360 == pytest.approx(350.0, abs=1e-6)
    assert arc.dxf.end_angle == pytest.approx(150.0)
    h.history.undo()
    arc = next(iter(h.msp.query("ARC")))
    assert arc.dxf.start_angle == pytest.approx(10.0), "not one undo step"


def test_extend_stretches_the_arc_end_nearest_the_pick():
    h = Harness()
    h.msp.add_arc((0, 0), 10, 0, 90)
    h.msp.add_line((-20, 5), (5, 5))       # meets the circle at x = -8.66
    h.services.index.invalidate()
    tool = ExtendTool(h.ctx)
    tool.start()
    tool.on_selection([])
    tool.on_point((1.0, 9.9))                               # near the 90° end
    arc = next(iter(h.msp.query("ARC")))
    assert arc.dxf.start_angle == pytest.approx(0.0)
    assert arc.dxf.end_angle == pytest.approx(150.0)        # where y = 5, x < 0
