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


# -- RECTANG: sticky corner settings + Area/Dimensions/Rotation ----------------

from tools.draw import PolygonTool, RectangTool  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_rect_state():
    RectangTool.chamfer = (0.0, 0.0)
    RectangTool.fillet = 0.0
    RectangTool.elevation = 0.0
    RectangTool.thickness = 0.0
    RectangTool.pl_width = 0.0
    RectangTool.rotation = 0.0
    PolygonTool.last_sides = 4
    PolygonTool.last_mode = "I"
    yield


def test_rectang_fillet_corners_and_sticky():
    h = Harness()
    tool = RectangTool(h.ctx)
    tool.start()
    assert tool.on_option("F")
    assert tool.on_option("2")
    tool.on_point((0.0, 0.0))
    tool.on_point((20.0, 10.0))
    pline = h.msp.query("LWPOLYLINE")[0]
    pts = pline.get_points("xyseb")
    assert len(pts) == 8
    arc_bulges = [p[4] for p in pts if p[4] != 0.0]
    assert len(arc_bulges) == 4
    assert all(b == pytest.approx(math.tan(math.pi / 8)) for b in arc_bulges)
    # sticky: the next RECTANG announces the state
    h2 = Harness()
    tool2 = RectangTool(h2.ctx)
    tool2.start()
    assert any("Fillet=2" in p for p in h2.prompts)


def test_rectang_chamfer_excludes_fillet():
    h = Harness()
    tool = RectangTool(h.ctx)
    tool.start()
    assert tool.on_option("F")
    assert tool.on_option("3")
    assert tool.on_option("C")
    assert tool.on_option("1")
    assert tool.on_option("2")               # d2
    assert RectangTool.fillet == 0.0         # chamfer cancels fillet
    assert RectangTool.chamfer == (1.0, 2.0)
    tool.on_point((0.0, 0.0))
    tool.on_point((20.0, 10.0))
    pts = h.msp.query("LWPOLYLINE")[0].get_points("xyseb")
    assert len(pts) == 8
    assert all(p[4] == 0.0 for p in pts)     # straight chamfer cuts


def test_rectang_too_big_fillet_falls_back_square():
    h = Harness()
    tool = RectangTool(h.ctx)
    tool.start()
    assert tool.on_option("F")
    assert tool.on_option("50")              # bigger than the rectangle
    tool.on_point((0.0, 0.0))
    tool.on_point((20.0, 10.0))
    pts = h.msp.query("LWPOLYLINE")[0].get_points("xyseb")
    assert len(pts) == 4                     # plain rectangle, like AutoCAD


def test_rectang_width_and_elevation_thickness():
    h = Harness()
    tool = RectangTool(h.ctx)
    tool.start()
    assert tool.on_option("W")
    assert tool.on_option("1.5")
    assert tool.on_option("E")
    assert tool.on_option("100")
    assert tool.on_option("T")
    assert tool.on_option("7")
    tool.on_point((0.0, 0.0))
    tool.on_point((20.0, 10.0))
    pline = h.msp.query("LWPOLYLINE")[0]
    pts = pline.get_points("xyseb")
    assert all(p[2] == 1.5 and p[3] == 1.5 for p in pts)
    assert pline.dxf.elevation == pytest.approx(100.0)
    assert pline.dxf.thickness == pytest.approx(7.0)


def test_rectang_dimensions_quadrant_placement():
    h = Harness()
    tool = RectangTool(h.ctx)
    tool.start()
    tool.on_point((10.0, 10.0))
    assert tool.on_option("D")
    assert tool.on_option("20")              # length
    assert tool.on_option("5")               # width
    tool.on_point((0.0, 0.0))                # pick lower-left quadrant
    pts = h.msp.query("LWPOLYLINE")[0].get_points("xyseb")
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    assert (min(xs), min(ys)) == (-10.0, 5.0)
    assert (max(xs), max(ys)) == (10.0, 10.0)


def test_rectang_area_by_length():
    h = Harness()
    tool = RectangTool(h.ctx)
    tool.start()
    tool.on_point((0.0, 0.0))
    assert tool.on_option("A")
    assert tool.on_option("100")             # area
    assert tool.on_option("L")
    assert tool.on_option("20")              # length -> width = 5
    pts = h.msp.query("LWPOLYLINE")[0].get_points("xyseb")
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    assert max(xs) == pytest.approx(20.0)
    assert max(ys) == pytest.approx(5.0)


def test_rectang_area_includes_fillet_loss():
    h = Harness()
    tool = RectangTool(h.ctx)
    tool.start()
    assert tool.on_option("F")
    assert tool.on_option("1")
    tool.on_point((0.0, 0.0))
    assert tool.on_option("A")
    assert tool.on_option("100")
    assert tool.on_option("L")
    assert tool.on_option("20")
    pts = h.msp.query("LWPOLYLINE")[0].get_points("xyseb")
    ys = [p[1] for p in pts]
    # width = (100 + (4-pi)*1) / 20, so the FINAL area is exactly 100
    assert max(ys) == pytest.approx((100.0 + (4.0 - math.pi)) / 20.0)


def test_rectang_rotation():
    h = Harness()
    tool = RectangTool(h.ctx)
    tool.start()
    tool.on_point((0.0, 0.0))
    assert tool.on_option("R")
    assert tool.on_option("90")
    tool.on_point((0.0, 20.0))               # along rotated +X
    pts = h.msp.query("LWPOLYLINE")[0].get_points("xyseb")
    xs = [round(p[0], 6) for p in pts]
    ys = [round(p[1], 6) for p in pts]
    assert max(ys) == pytest.approx(20.0)
    assert min(xs) < 0 or max(xs) == pytest.approx(0.0)
    assert RectangTool.rotation == 90.0      # sticky


# -- POLYGON: Edge, Inscribed/Circumscribed, orientation -----------------------

def test_polygon_inscribed_typed_radius_bottom_edge_horizontal():
    h = Harness()
    tool = PolygonTool(h.ctx)
    tool.start()
    assert tool.on_option("4")
    tool.on_point((0.0, 0.0))                # center
    assert tool.on_option("I")
    assert tool.on_option("10")              # typed radius
    pts = h.msp.query("LWPOLYLINE")[0].get_points("xyseb")
    ys = sorted(round(p[1], 6) for p in pts)
    # square inscribed r=10 with horizontal bottom edge: vertices at ±45°
    assert ys[0] == ys[1] == pytest.approx(-10.0 * math.sin(math.pi / 4))


def test_polygon_circumscribed_typed_radius():
    h = Harness()
    tool = PolygonTool(h.ctx)
    tool.start()
    assert tool.on_option("6")
    tool.on_point((0.0, 0.0))
    assert tool.on_option("C")
    assert tool.on_option("10")              # apothem = 10
    pts = h.msp.query("LWPOLYLINE")[0].get_points("xyseb")
    # bottom edge midpoint at (0, -10): its two vertices have y = -10
    ys = sorted(round(p[1], 6) for p in pts)
    assert ys[0] == ys[1] == pytest.approx(-10.0)
    assert PolygonTool.last_mode == "C"      # sticky <C> default


def test_polygon_dragged_pick_is_vertex():
    h = Harness()
    tool = PolygonTool(h.ctx)
    tool.start()
    assert tool.on_option("5")
    tool.on_point((0.0, 0.0))
    assert tool.on_option("I")
    tool.on_point((7.0, 3.0))                # dragged: this IS a vertex
    pts = h.msp.query("LWPOLYLINE")[0].get_points("xyseb")
    assert any(abs(p[0] - 7.0) < 1e-9 and abs(p[1] - 3.0) < 1e-9
               for p in pts)


def test_polygon_edge_ccw():
    h = Harness()
    tool = PolygonTool(h.ctx)
    tool.start()
    assert tool.on_option("4")
    assert tool.on_option("E")
    tool.on_point((0.0, 0.0))
    tool.on_point((10.0, 0.0))
    pts = h.msp.query("LWPOLYLINE")[0].get_points("xyseb")
    ys = [p[1] for p in pts]
    assert max(ys) == pytest.approx(10.0)    # body above the edge (CCW)
    assert len(pts) == 4


def test_polygon_sides_default_is_session_sticky():
    h = Harness()
    tool = PolygonTool(h.ctx)
    tool.start()
    assert tool.on_option("6")
    tool.on_point((0.0, 0.0))
    assert tool.on_option("I")
    assert tool.on_option("5")
    tool2 = PolygonTool(h.ctx)
    tool2.start()
    assert "<6>" in h.prompts[-1]            # POLYSIDES remembered
    tool2.on_enter()                         # accept 6
    tool2.on_point((50.0, 0.0))
    tool2.on_point((60.0, 0.0))              # mode default I + dragged pick
    plines = h.msp.query("LWPOLYLINE")
    assert len(plines[1].get_points("xyseb")) == 6


# -- ELLIPSE: axis swap, Rotation, Arc -----------------------------------------

from tools.draw import EllipseTool, TextTool  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_text_state():
    TextTool.default_height = 2.5
    TextTool.last_rotation = 0.0
    TextTool._last_final = None
    yield


def test_ellipse_first_axis_may_be_minor():
    # official rule: the first axis defines the MINOR axis when the other
    # half-axis is longer — swap, never clamp
    center, major, ratio = actions.ellipse_from_axis((-5, 0), (5, 0), 12.0)
    assert center == (0.0, 0.0)
    assert (major[0], major[1]) == (pytest.approx(0.0), pytest.approx(12.0))
    assert ratio == pytest.approx(5.0 / 12.0)


def test_ellipse_rotation_projected_circle():
    h = Harness()
    tool = EllipseTool(h.ctx)
    tool.start()
    tool.on_point((0.0, 0.0))
    tool.on_point((20.0, 0.0))
    assert tool.on_option("R")
    assert tool.on_option("60")               # minor = major * cos(60) = 0.5
    e = h.msp.query("ELLIPSE")[0]
    assert e.dxf.ratio == pytest.approx(0.5)
    # invalid band 89.4..90.6 rejected
    h2 = Harness()
    tool2 = EllipseTool(h2.ctx)
    tool2.start()
    tool2.on_point((0.0, 0.0))
    tool2.on_point((20.0, 0.0))
    assert tool2.on_option("R")
    assert tool2.on_option("90")
    assert any("Invalid rotation" in p for p in h2.prompts)
    assert not h2.msp.query("ELLIPSE")


def test_ellipse_arc_angles():
    h = Harness()
    tool = EllipseTool(h.ctx)
    tool.start()
    assert tool.on_option("A")                # elliptical arc
    tool.on_point((-10.0, 0.0))
    tool.on_point((10.0, 0.0))
    assert tool.on_option("5")                # other half-axis
    assert tool.on_option("0")                # start angle
    assert tool.on_option("90")               # end angle
    e = h.msp.query("ELLIPSE")[0]
    assert e.dxf.start_param == pytest.approx(0.0)
    # true angle 90 == parameter pi/2 on the axis
    assert e.dxf.end_param == pytest.approx(math.pi / 2.0)


def test_ellipse_arc_included_and_angle_param_mapping():
    h = Harness()
    tool = EllipseTool(h.ctx)
    tool.start()
    assert tool.on_option("A")
    tool.on_point((-10.0, 0.0))
    tool.on_point((10.0, 0.0))
    assert tool.on_option("5")                # ratio 0.5
    assert tool.on_option("45")               # start TRUE angle 45
    assert tool.on_option("I")                # included
    assert tool.on_option("90")
    e = h.msp.query("ELLIPSE")[0]
    # true angle 45 with ratio .5 -> param = atan2(sin45, .5*cos45)
    expected = math.atan2(math.sin(math.radians(45)),
                          0.5 * math.cos(math.radians(45)))
    assert e.dxf.start_param == pytest.approx(expected)


def test_ellipse_arc_parameter_mode():
    h = Harness()
    tool = EllipseTool(h.ctx)
    tool.start()
    assert tool.on_option("A")
    tool.on_point((-10.0, 0.0))
    tool.on_point((10.0, 0.0))
    assert tool.on_option("5")
    assert tool.on_option("P")                # parameter mode
    assert tool.on_option("30")               # start param 30 deg exactly
    assert tool.on_option("120")              # end param
    e = h.msp.query("ELLIPSE")[0]
    assert e.dxf.start_param == pytest.approx(math.radians(30))
    assert e.dxf.end_param == pytest.approx(math.radians(120))


# -- TEXT: Justify + Style -----------------------------------------------------

def _type_text(tool, text):
    for ch in text:
        tool.on_char(ch)


def test_text_justify_center():
    from ezdxf.enums import TextEntityAlignment

    h = Harness()
    tool = TextTool(h.ctx)
    tool.start()
    assert tool.on_option("J")
    assert tool.on_option("C")                # Center
    tool.on_point((50.0, 20.0))
    tool.on_enter()                           # height default
    tool.on_enter()                           # rotation default
    _type_text(tool, "EJE")
    tool.finish_typing()
    t = h.msp.query("TEXT")[0]
    assert t.get_align_enum() == TextEntityAlignment.CENTER
    p = t.get_placement()[1]
    assert (p.x, p.y) == (pytest.approx(50.0), pytest.approx(20.0))


def test_text_justify_keyword_direct_and_mc():
    from ezdxf.enums import TextEntityAlignment

    h = Harness()
    tool = TextTool(h.ctx)
    tool.start()
    assert tool.on_option("MC")               # direct at the first prompt
    tool.on_point((5.0, 5.0))
    tool.on_enter()
    tool.on_enter()
    _type_text(tool, "X")
    tool.finish_typing()
    t = h.msp.query("TEXT")[0]
    assert t.get_align_enum() == TextEntityAlignment.MIDDLE_CENTER


def test_text_align_two_points_no_height_prompt():
    from ezdxf.enums import TextEntityAlignment

    h = Harness()
    tool = TextTool(h.ctx)
    tool.start()
    assert tool.on_option("A")                # Align
    tool.on_point((0.0, 0.0))
    tool.on_point((30.0, 0.0))
    assert tool.typing                        # straight to typing: no height
    _type_text(tool, "LINDERO")
    tool.finish_typing()
    t = h.msp.query("TEXT")[0]
    assert t.get_align_enum() == TextEntityAlignment.ALIGNED


def test_text_style_option_and_fixed_height_skip():
    h = Harness()
    doc = h.document.doc
    doc.styles.new("TITULO", dxfattribs={"height": 5.0})

    class Window:
        document = h.document

    class Services:
        window = Window()

    h.ctx.services = Services()
    tool = TextTool(h.ctx)
    tool.start()
    assert tool.on_option("S")
    assert tool.on_option("TITULO")
    assert doc.header["$TEXTSTYLE"] == "TITULO"
    tool.on_point((0.0, 0.0))
    # fixed-height style: the height prompt is skipped entirely
    assert any("rotation angle" in p for p in h.prompts)
    tool.on_enter()                           # rotation default -> typing
    _type_text(tool, "PLANO")
    tool.finish_typing()
    t = h.msp.query("TEXT")[0]
    assert t.dxf.style == "TITULO"
    assert t.dxf.height == pytest.approx(5.0)


def test_text_enter_repeats_below_previous():
    h = Harness()
    tool = TextTool(h.ctx)
    tool.start()
    tool.on_point((0.0, 10.0))
    tool.on_enter()
    tool.on_enter()
    _type_text(tool, "uno")
    tool.finish_typing()
    tool2 = TextTool(h.ctx)
    tool2.start()
    tool2.on_enter()                          # documented: repeat below
    assert tool2.typing
    _type_text(tool2, "dos")
    tool2.finish_typing()
    texts = {t.dxf.text: t.dxf.insert.y for t in h.msp.query("TEXT")}
    assert texts["dos"] == pytest.approx(
        texts["uno"] - 1.5 * TextTool.default_height)


# -- -HATCH: the command-line hatch --------------------------------------------

from tools.blocks import HatchCliTool, HatchTool  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_hatch_state():
    HatchTool._last = {"pattern": "SOLID", "scale": 1.0, "angle": 0.0,
                       "color": 256}
    HatchCliTool._style = actions.HATCH_STYLE_NORMAL
    HatchCliTool._user = (0.0, 1.0, False)
    HatchCliTool._retain = False
    yield


def _cli_hatch(h):
    tool = HatchCliTool(h.ctx)
    tool.start()
    return tool


def test_minus_hatch_draw_boundary_and_pattern():
    h = Harness()
    tool = _cli_hatch(h)
    assert tool.on_option("P")
    assert tool.on_option("ANSI31")
    assert tool.on_option("2")               # scale
    assert tool.on_option("45")              # angle
    assert tool.on_option("W")               # draW boundary
    assert tool.on_option("")                # retain <N>
    tool.on_point((0.0, 0.0))
    tool.on_point((10.0, 0.0))
    tool.on_point((10.0, 10.0))
    assert tool.on_option("C")               # close the loop
    tool.on_enter()                          # apply
    hatch = h.msp.query("HATCH")[0]
    assert hatch.dxf.pattern_name == "ANSI31"
    assert hatch.dxf.pattern_scale == pytest.approx(2.0)
    assert hatch.dxf.pattern_angle == pytest.approx(45.0)
    assert not h.msp.query("LWPOLYLINE")     # boundary not retained


def test_minus_hatch_retain_boundary_polyline():
    h = Harness()
    tool = _cli_hatch(h)
    assert tool.on_option("W")
    assert tool.on_option("Y")               # retain
    tool.on_point((0.0, 0.0))
    tool.on_point((10.0, 0.0))
    tool.on_point((10.0, 10.0))
    tool.on_enter()                          # Enter closes the loop
    tool.on_enter()                          # apply (SOLID default)
    assert len(h.msp.query("HATCH")) == 1
    pline = h.msp.query("LWPOLYLINE")[0]
    assert pline.closed


def test_minus_hatch_style_suffix_and_ignore_drops_islands():
    h = Harness()
    # outer square with an island circle, via the region machinery fake
    outer = [(0, 0), (20, 0), (20, 20), (0, 20)]
    island = [(8, 8), (12, 8), (12, 12), (8, 12)]

    class Services:
        def hatch_region_at(self, point):
            return (outer, [island])

    h.ctx.services = Services()
    tool = _cli_hatch(h)
    assert tool.on_option("P")
    assert tool.on_option("ANSI31,I")        # Ignore style via suffix
    assert tool.on_option("")                # scale default
    assert tool.on_option("")                # angle default
    tool.on_point((1.0, 1.0))                # internal point
    tool.on_enter()
    hatch = h.msp.query("HATCH")[0]
    assert hatch.dxf.hatch_style == actions.HATCH_STYLE_IGNORE
    assert len(hatch.paths) == 1             # island dropped

    # the style is session-sticky (like the HP* sysvars) — reset to check
    # that Normal keeps the island as a hole and records style 0
    HatchCliTool._style = actions.HATCH_STYLE_NORMAL
    h2 = Harness()
    h2.ctx.services = Services()
    tool2 = _cli_hatch(h2)
    tool2.on_point((1.0, 1.0))
    tool2.on_enter()
    hatch2 = h2.msp.query("HATCH")[0]
    assert hatch2.dxf.hatch_style == actions.HATCH_STYLE_NORMAL
    assert len(hatch2.paths) == 2


def test_minus_hatch_user_defined_double():
    h = Harness()
    tool = _cli_hatch(h)
    assert tool.on_option("P")
    assert tool.on_option("U")
    assert tool.on_option("30")              # angle
    assert tool.on_option("2.5")             # spacing
    assert tool.on_option("Y")               # double
    assert tool.on_option("W")
    assert tool.on_option("")
    tool.on_point((0.0, 0.0))
    tool.on_point((10.0, 0.0))
    tool.on_point((10.0, 10.0))
    assert tool.on_option("C")
    tool.on_enter()
    hatch = h.msp.query("HATCH")[0]
    assert hatch.dxf.pattern_name == "U"
    assert hatch.dxf.pattern_type == 0       # user-defined
    assert hatch.dxf.pattern_double == 1
    lines = hatch.pattern.lines
    assert len(lines) == 2                   # double: second set at 90
    assert lines[0].angle == pytest.approx(30.0)
    assert lines[1].angle == pytest.approx(120.0)


def test_minus_hatch_advanced_style_and_color():
    h = Harness()
    tool = _cli_hatch(h)
    assert tool.on_option("A")
    assert tool.on_option("O")               # Outer
    assert HatchCliTool._style == actions.HATCH_STYLE_OUTER
    assert tool.on_option("CO")
    assert tool.on_option("1")               # red
    assert tool.settings["color"] == 1
    assert tool.on_option("CO")
    assert tool.on_option(".")               # back to ByLayer
    assert tool.settings["color"] == 256


def test_minus_hatch_question_lists_patterns():
    h = Harness()
    tool = _cli_hatch(h)
    assert tool.on_option("P")
    assert tool.on_option("?")
    assert any("ANSI31" in p for p in h.prompts)
    assert tool.on_option("NOPE123")
    assert any("Unknown pattern" in p for p in h.prompts)


def test_minus_hatch_alias():
    from core.aliases import DEFAULT_ALIASES, resolve

    assert resolve("-H", DEFAULT_ALIASES) == "-HATCH"
