# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""AutoCAD-parity audit wave 1: ARC (11 methods), CIRCLE (D/TTR/<last>),
LINE (Continue + real Undo), PLINE (arc mode, widths, length, undo)."""
from __future__ import annotations

import math

import pytest

from core import actions
from core.commands import History
from core.document import Document
from tools import draw as draw_mod
from tools.base import ToolContext
from tools.draw import ArcTool, CircleTool, LineTool, PlineTool


@pytest.fixture(autouse=True)
def _fresh_state():
    draw_mod.reset_chain()
    CircleTool.last_radius = None
    PlineTool.current_width = 0.0
    yield


class Harness:
    def __init__(self):
        self.document = Document.new()
        self.history = History(self.document)
        self.prompts: list[str] = []
        self.finished = False
        self.ctx = ToolContext(
            execute=self.history.execute,
            prompt=self.prompts.append,
            echo=self.prompts.append,
            finish=self._finish,
            undo_last=self.history.undo,
        )

    def _finish(self):
        self.finished = True

    @property
    def msp(self):
        return self.document.modelspace()

    def arcs(self):
        return list(self.msp.query("ARC"))


def _arc_tuple(arc):
    c = arc.dxf.center
    return (round(c.x, 6), round(c.y, 6), round(arc.dxf.radius, 6),
            round(arc.dxf.start_angle % 360.0, 4),
            round(arc.dxf.end_angle % 360.0, 4))


# -- arc geometry --------------------------------------------------------------

def test_arc_sca_negative_angle_is_clockwise():
    center, r, a1, a2, end, ccw = actions.arc_sca((1, 0), (0, 0), -90.0)
    assert not ccw
    assert (round(a1), round(a2)) == (-90, 0)      # stored CCW, swapped
    assert end == pytest.approx((0.0, -1.0))


def test_arc_scl_minor_and_major():
    # radius 1, chord sqrt(2) -> 90 degrees minor
    _c, _r, a1, a2, _e, ccw = actions.arc_scl((1, 0), (0, 0), math.sqrt(2.0))
    assert ccw and (a2 - a1) % 360.0 == pytest.approx(90.0)
    _c, _r, a1, a2, _e, _ = actions.arc_scl((1, 0), (0, 0), -math.sqrt(2.0))
    assert (a2 - a1) % 360.0 == pytest.approx(270.0)
    with pytest.raises(ValueError):
        actions.arc_scl((1, 0), (0, 0), 3.0)       # chord > 2R


def test_arc_sea_center_side():
    center, r, a1, a2, _e, ccw = actions.arc_sea((1, 0), (0, 1), 90.0)
    assert ccw
    assert center == pytest.approx((0.0, 0.0), abs=1e-9)
    assert r == pytest.approx(1.0)
    # negative: same endpoints, swept clockwise (center on the other side)
    center, _r, _a1, _a2, end, ccw = actions.arc_sea((1, 0), (0, 1), -90.0)
    assert not ccw
    assert center == pytest.approx((1.0, 1.0), abs=1e-9)
    assert end == pytest.approx((0.0, 1.0))


def test_arc_ser_minor_major_and_misfit():
    center, r, *_ = actions.arc_ser((1, 0), (0, 1), 1.0)
    assert center == pytest.approx((0.0, 0.0), abs=1e-9)
    center, r, *_rest = actions.arc_ser((1, 0), (0, 1), -1.0)
    assert center == pytest.approx((1.0, 1.0), abs=1e-9)
    with pytest.raises(ValueError):
        actions.arc_ser((0, 0), (10, 0), 1.0)      # chord doesn't fit


def test_arc_sed_direction_and_tangent_chain():
    geom = actions.arc_sed((0, 0), (2, 0), 90.0)   # up, curling right: CW
    center, r, _a1, _a2, end, ccw = geom
    assert center == pytest.approx((1.0, 0.0), abs=1e-9)
    assert r == pytest.approx(1.0)
    assert not ccw
    # tangent at the end continues downward (-90)
    assert actions.arc_end_tangent(geom) % 360.0 == pytest.approx(270.0)


# -- ARC tool: the method tree -------------------------------------------------

def test_arc_start_center_angle():
    h = Harness()
    tool = ArcTool(h.ctx)
    tool.start()
    tool.on_point((1.0, 0.0))                      # start
    assert tool.on_option("C")                     # Center
    tool.on_point((0.0, 0.0))                      # center
    assert tool.on_option("A")                     # Angle
    assert tool.on_option("90")
    assert h.finished
    arc = h.arcs()[0]
    assert _arc_tuple(arc) == (0.0, 0.0, 1.0, 0.0, 90.0)


def test_arc_start_end_radius_negative_is_major():
    h = Harness()
    tool = ArcTool(h.ctx)
    tool.start()
    tool.on_point((1.0, 0.0))
    assert tool.on_option("E")
    tool.on_point((0.0, 1.0))
    assert tool.on_option("R")
    assert tool.on_option("-1")
    arc = h.arcs()[0]
    c = arc.dxf.center
    assert (c.x, c.y) == (pytest.approx(1.0), pytest.approx(1.0))


def test_arc_start_end_direction():
    h = Harness()
    tool = ArcTool(h.ctx)
    tool.start()
    tool.on_point((0.0, 0.0))
    assert tool.on_option("E")
    tool.on_point((2.0, 0.0))
    assert tool.on_option("D")
    assert tool.on_option("90")
    arc = h.arcs()[0]
    assert arc.dxf.radius == pytest.approx(1.0)


def test_arc_center_start_length():
    h = Harness()
    tool = ArcTool(h.ctx)
    tool.start()
    assert tool.on_option("C")                     # center-first
    tool.on_point((0.0, 0.0))
    tool.on_point((1.0, 0.0))                      # start
    assert tool.on_option("L")
    assert tool.on_option(str(math.sqrt(2.0)))     # 90-degree chord
    arc = h.arcs()[0]
    assert (arc.dxf.end_angle - arc.dxf.start_angle) % 360.0 \
        == pytest.approx(90.0)


def test_arc_continue_is_tangent_to_last_line():
    h = Harness()
    line = LineTool(h.ctx)
    line.start()
    line.on_point((0.0, 0.0))
    line.on_point((10.0, 0.0))                     # direction 0
    line.on_enter()
    tool = ArcTool(h.ctx)
    tool.start()
    tool.on_enter()                                # Continue
    tool.on_point((12.0, 2.0))
    arc = h.arcs()[0]
    # tangent to +X at (10,0): center sits straight above/below the start
    assert arc.dxf.center.x == pytest.approx(10.0)


def test_arc_sce_ray_rule_ignores_distance():
    h = Harness()
    tool = ArcTool(h.ctx)
    tool.start()
    tool.on_point((1.0, 0.0))
    assert tool.on_option("C")
    tool.on_point((0.0, 0.0))
    tool.on_point((0.0, 99.0))                     # far point: only the ray counts
    arc = h.arcs()[0]
    assert _arc_tuple(arc) == (0.0, 0.0, 1.0, 0.0, 90.0)


# -- CIRCLE: Diameter, <last> default, TTR -------------------------------------

def test_circle_diameter_and_last_radius_default():
    h = Harness()
    tool = CircleTool(h.ctx)
    tool.start()
    tool.on_point((0.0, 0.0))
    assert tool.on_option("D")
    assert tool.on_option("10")                    # diameter -> radius 5
    circle = h.msp.query("CIRCLE")[0]
    assert circle.dxf.radius == pytest.approx(5.0)
    assert CircleTool.last_radius == pytest.approx(5.0)

    tool2 = CircleTool(h.ctx)
    tool2.start()
    tool2.on_point((20.0, 0.0))
    assert "<5>" in h.prompts[-1]                  # CIRCLERAD default shown
    tool2.on_enter()                               # accept <last>
    circles = h.msp.query("CIRCLE")
    assert circles[1].dxf.radius == pytest.approx(5.0)


def test_circle_ttr_line_line():
    h = Harness()
    l1 = h.msp.add_line((0.0, 0.0), (100.0, 0.0))     # X axis
    l2 = h.msp.add_line((0.0, 0.0), (0.0, 100.0))     # Y axis

    class Services:
        def pick_entity(self, point):
            return l1 if abs(point[1]) < abs(point[0]) else l2

    h.ctx.services = Services()
    tool = CircleTool(h.ctx)
    tool.start()
    assert tool.on_option("T")
    tool.on_point((50.0, 0.5))                     # pick the X axis
    tool.on_point((0.5, 50.0))                     # pick the Y axis
    assert tool.on_option("10")                    # radius
    circle = h.msp.query("CIRCLE")[0]
    # tangent to both axes in the first quadrant (near the picks)
    assert (circle.dxf.center.x, circle.dxf.center.y) \
        == (pytest.approx(10.0), pytest.approx(10.0))


def test_circle_ttr_line_circle():
    h = Harness()
    l1 = h.msp.add_line((-100.0, 0.0), (100.0, 0.0))
    c1 = h.msp.add_circle((0.0, 30.0), 10.0)

    class Services:
        def pick_entity(self, point):
            return c1 if point[1] > 10 else l1

    h.ctx.services = Services()
    tool = CircleTool(h.ctx)
    tool.start()
    assert tool.on_option("TTR")
    tool.on_point((0.0, -0.5))                     # the line, from below
    tool.on_point((0.0, 19.0))                     # the circle, bottom side
    assert tool.on_option("10")
    circle = h.msp.query("CIRCLE")[-1]             # the NEW circle, not c1
    # tangent to the X axis (center y = 10) and to the circle externally
    assert circle.dxf.center.y == pytest.approx(10.0)
    d = math.hypot(circle.dxf.center.x - 0.0, circle.dxf.center.y - 30.0)
    assert d == pytest.approx(20.0)                # 10 + 10: external tangency


def test_circle_ttr_impossible_reports():
    h = Harness()
    c1 = h.msp.add_circle((0.0, 0.0), 5.0)
    c2 = h.msp.add_circle((100.0, 0.0), 5.0)

    class Services:
        def pick_entity(self, point):
            return c1 if point[0] < 50 else c2

    h.ctx.services = Services()
    tool = CircleTool(h.ctx)
    tool.start()
    tool.on_option("T")
    tool.on_point((5.0, 0.0))
    tool.on_point((95.0, 0.0))
    assert tool.on_option("1")                     # far too small
    assert not h.msp.query("CIRCLE")[2:]           # only the two originals
    assert any("does not exist" in p for p in h.prompts)


# -- LINE: Continue + real Undo ------------------------------------------------

def test_line_undo_erases_the_segment_for_real():
    h = Harness()
    tool = LineTool(h.ctx)
    tool.start()
    tool.on_point((0.0, 0.0))
    tool.on_point((10.0, 0.0))
    tool.on_point((10.0, 10.0))
    assert len(h.msp.query("LINE")) == 2
    assert tool.on_option("U")
    assert len(h.msp.query("LINE")) == 1           # entity gone, not just point
    tool.on_point((20.0, 0.0))                     # draw on from (10, 0)
    lines = h.msp.query("LINE")
    assert len(lines) == 2
    end = lines[-1].dxf.end
    assert (end.x, end.y) == (20.0, 0.0)


def test_line_continue_from_last_line():
    h = Harness()
    first = LineTool(h.ctx)
    first.start()
    first.on_point((0.0, 0.0))
    first.on_point((10.0, 5.0))
    first.on_enter()
    second = LineTool(h.ctx)
    second.start()
    second.on_enter()                              # Continue
    second.on_point((20.0, 5.0))
    lines = h.msp.query("LINE")
    start = lines[-1].dxf.start
    assert (start.x, start.y) == (10.0, 5.0)


def test_line_continue_from_arc_locks_tangent():
    h = Harness()
    arc = ArcTool(h.ctx)
    arc.start()
    arc.on_point((1.0, 0.0))
    arc.on_option("C")
    arc.on_point((0.0, 0.0))
    arc.on_option("A")
    arc.on_option("90")                            # ends at (0,1), tangent 180
    tool = LineTool(h.ctx)
    tool.start()
    tool.on_enter()                                # Continue: tangent locked
    assert any("Length of line" in p for p in h.prompts)
    assert tool.on_option("5")                     # typed length
    line = h.msp.query("LINE")[-1]
    end = line.dxf.end
    assert (end.x, end.y) == (pytest.approx(-5.0), pytest.approx(1.0))


# -- PLINE: arc mode, widths, length, undo, close ------------------------------

def _pline_entity(h):
    plines = h.msp.query("LWPOLYLINE")
    assert plines, "no polyline created"
    return plines[-1]


def test_pline_arc_mode_tangent_bulge():
    h = Harness()
    tool = PlineTool(h.ctx)
    tool.start()
    tool.on_point((0.0, 0.0))
    tool.on_point((10.0, 0.0))                     # straight, direction 0
    assert tool.on_option("A")                     # arc mode
    tool.on_point((12.0, 2.0))                     # tangent 90-degree arc
    tool.on_enter()
    pline = _pline_entity(h)
    pts = pline.get_points("xyseb")
    assert len(pts) == 3
    assert pts[0][4] == pytest.approx(0.0)         # straight segment
    assert pts[1][4] == pytest.approx(math.tan(math.radians(90) / 4.0))


def test_pline_width_and_taper():
    h = Harness()
    tool = PlineTool(h.ctx)
    tool.start()
    tool.on_point((0.0, 0.0))
    assert tool.on_option("W")
    assert tool.on_option("2")                     # starting width
    assert tool.on_option("0")                     # ending width (taper)
    tool.on_point((10.0, 0.0))
    tool.on_enter()
    pts = _pline_entity(h).get_points("xyseb")
    assert (pts[0][2], pts[0][3]) == (2.0, 0.0)
    # the ending width becomes the uniform width for the NEXT invocation
    assert PlineTool.current_width == 0.0


def test_pline_halfwidth_doubles():
    h = Harness()
    tool = PlineTool(h.ctx)
    tool.start()
    tool.on_point((0.0, 0.0))
    assert tool.on_option("H")
    assert tool.on_option("1")                     # half-width 1 = width 2
    tool.on_enter_defaults = None
    assert tool.on_option("")                      # Enter: end = start
    tool.on_point((5.0, 0.0))
    tool.on_enter()
    pts = _pline_entity(h).get_points("xyseb")
    assert (pts[0][2], pts[0][3]) == (2.0, 2.0)


def test_pline_length_continues_collinear():
    h = Harness()
    tool = PlineTool(h.ctx)
    tool.start()
    tool.on_point((0.0, 0.0))
    tool.on_point((3.0, 4.0))                      # direction 53.13
    assert tool.on_option("L")
    assert tool.on_option("5")                     # same direction, length 5
    tool.on_enter()
    pts = _pline_entity(h).get_points("xyseb")
    assert pts[2][0] == pytest.approx(6.0)
    assert pts[2][1] == pytest.approx(8.0)


def test_pline_undo_and_close():
    h = Harness()
    tool = PlineTool(h.ctx)
    tool.start()
    tool.on_point((0.0, 0.0))
    tool.on_point((10.0, 0.0))
    tool.on_point((10.0, 10.0))
    tool.on_point((99.0, 99.0))                    # mistake
    assert tool.on_option("U")                     # take it back
    assert tool.on_option("C")                     # close
    pline = _pline_entity(h)
    assert pline.closed
    assert len(pline.get_points("xyseb")) == 3


def test_pline_arc_close_uses_arc_segment():
    h = Harness()
    tool = PlineTool(h.ctx)
    tool.start()
    tool.on_point((0.0, 0.0))
    tool.on_point((10.0, 0.0))
    assert tool.on_option("A")
    assert tool.on_option("CL")                    # close with an arc
    pline = _pline_entity(h)
    assert pline.closed
    pts = pline.get_points("xyseb")
    assert pts[-1][4] != 0.0                       # closing segment has bulge


def test_pline_arc_radius_endpoint():
    h = Harness()
    tool = PlineTool(h.ctx)
    tool.start()
    tool.on_point((0.0, 0.0))
    assert tool.on_option("A")
    assert tool.on_option("R")
    assert tool.on_option("1")
    tool.on_point((0.0, 2.0))                      # half circle radius 1
    tool.on_enter()
    pts = _pline_entity(h).get_points("xyseb")
    assert abs(pts[0][4]) == pytest.approx(1.0)    # bulge 1 = 180 degrees


def test_pline_second_pt_three_point_arc():
    h = Harness()
    tool = PlineTool(h.ctx)
    tool.start()
    tool.on_point((1.0, 0.0))
    assert tool.on_option("A")
    assert tool.on_option("S")
    tool.on_point((0.0, 1.0))                      # through the top
    tool.on_point((-1.0, 0.0))                     # half circle
    tool.on_enter()
    pts = _pline_entity(h).get_points("xyseb")
    assert abs(pts[0][4]) == pytest.approx(1.0)
