# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Phase 5 headless tests: selection, edit math, edit commands, edit tools."""
from __future__ import annotations

import math

import ezdxf
import pytest

from core import actions, editmath
from core.commands import History
from core.document import Document
from core.select import GeometryIndex
from tools.base import ToolContext
from tools.edit import (
    CopyTool, EraseTool, ExtendTool, FilletTool, MirrorTool, MoveTool,
    OffsetTool, RotateTool, ScaleTool, TrimTool,
)


def make_doc():
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    msp.add_line((0, 0), (100, 0))
    msp.add_circle((50, 50), 10)
    msp.add_lwpolyline([(200, 0), (250, 0), (250, 50)])
    return Document(doc)


# -- selection -----------------------------------------------------------------

def test_pick_window_crossing():
    document = make_doc()
    index = GeometryIndex(document)
    h_line = index.pick((50, 0.5), tolerance=2.0)
    assert document.doc.entitydb.get(h_line).dxftype() == "LINE"
    h_circle = index.pick((50, 61), tolerance=2.0)
    assert document.doc.entitydb.get(h_circle).dxftype() == "CIRCLE"
    assert index.pick((500, 500), tolerance=2.0) is None

    # window (fully inside): only the circle fits this rect
    inside = index.window((30, 30, 70, 70))
    assert [document.doc.entitydb.get(h).dxftype() for h in inside] == ["CIRCLE"]
    # crossing touches the line and the circle
    crossing = index.crossing((49, -5, 51, 45))
    kinds = sorted(document.doc.entitydb.get(h).dxftype() for h in crossing)
    assert kinds == ["CIRCLE", "LINE"]


# -- edit math -----------------------------------------------------------------

def test_trim_segment_middle_and_end():
    seg = (0.0, 0.0, 100.0, 0.0)
    cutters = [(30.0, -10.0, 30.0, 10.0), (70.0, -10.0, 70.0, 10.0)]
    pieces = editmath.trim_segment(seg, cutters, [], pick_t=0.5)
    assert pieces == [(0.0, 0.0, 30.0, 0.0), (70.0, 0.0, 100.0, 0.0)]
    pieces = editmath.trim_segment(seg, cutters, [], pick_t=0.1)
    assert pieces == [(30.0, 0.0, 100.0, 0.0)]
    assert editmath.trim_segment(seg, [(0, 5, 100, 5)], [], 0.5) is None


def test_trim_circle_to_arc():
    arc = editmath.trim_circle((0, 0), 10.0,
                               [(-20, 0, 20, 0)],   # horizontal through center
                               pick_angle=math.pi / 2)  # pick the top
    assert arc is not None
    a0, a1 = arc
    # survivor is the bottom half: from 0 sweeping ccw to 180 is the top...
    # ezdxf arcs ccw: bottom half runs 180 -> 360(0)
    assert a0 % 360 == pytest.approx(180.0)
    assert a1 % 360 == pytest.approx(0.0)


def test_extend_segment():
    seg = (0.0, 0.0, 40.0, 0.0)
    edge = [(100.0, -10.0, 100.0, 10.0)]
    out = editmath.extend_segment(seg, edge, [], pick_t=0.9)
    assert out == (0.0, 0.0, 100.0, 0.0)
    assert editmath.extend_segment(seg, edge, [], pick_t=0.1) is None


def test_offset_line_sides():
    seg = (0.0, 0.0, 10.0, 0.0)
    up = editmath.offset_line(seg, 2.0, (5.0, 5.0))
    assert up[1] == pytest.approx(2.0) and up[3] == pytest.approx(2.0)
    down = editmath.offset_line(seg, 2.0, (5.0, -5.0))
    assert down[1] == pytest.approx(-2.0)


def test_fillet_corner_and_arc():
    s1 = (0.0, 0.0, 10.0, 0.0)
    s2 = (12.0, 2.0, 12.0, 10.0)   # meets s1's line at (12, 0)
    n1, n2 = editmath.fillet_corner(s1, s2)
    assert n1 == (0.0, 0.0, 12.0, 0.0)
    assert n2 == (12.0, 0.0, 12.0, 10.0)

    result = editmath.fillet_arc((0, 0, 10, 0), (10, 0, 10, 10), 2.0)
    assert result is not None
    center, r, _a0, _a1, t1, t2 = result
    assert r == 2.0
    assert center[0] == pytest.approx(8.0) and center[1] == pytest.approx(2.0)
    assert t1[0] == pytest.approx(8.0) and t1[1] == pytest.approx(0.0)
    assert t2[0] == pytest.approx(10.0) and t2[1] == pytest.approx(2.0)


# -- edit commands with undo ---------------------------------------------------

def test_move_rotate_scale_mirror_undo():
    document = Document(ezdxf.new("R2018"))
    history = History(document)
    msp = document.modelspace()
    line = msp.add_line((0, 0), (10, 0))

    history.execute(actions.move_entities([line], 5, 5))
    assert line.dxf.start.x == pytest.approx(5)
    history.execute(actions.rotate_entities([line], (5, 5), 90))
    assert line.dxf.end.y == pytest.approx(15)
    history.execute(actions.scale_entities([line], (5, 5), 2))
    for _ in range(3):
        history.undo()
    assert line.dxf.start.x == pytest.approx(0)
    assert line.dxf.end.x == pytest.approx(10)
    assert line.dxf.end.y == pytest.approx(0)

    history.execute(actions.mirror_entities([line], (0, 20), (100, 20)))
    assert len(msp.query("LINE")) == 2
    mirrored = msp.query("LINE")[-1]
    assert mirrored.dxf.start.y == pytest.approx(40)
    history.undo()
    assert len(msp.query("LINE")) == 1


def test_erase_preserves_handle_on_undo():
    document = Document(ezdxf.new("R2018"))
    history = History(document)
    msp = document.modelspace()
    line = msp.add_line((0, 0), (1, 1))
    handle = line.dxf.handle
    history.execute(actions.EraseCommand([line]))
    assert len(msp) == 0
    history.undo()
    assert len(msp) == 1
    assert msp[0].dxf.handle == handle  # conservative undo: same entity


# -- edit tools ----------------------------------------------------------------

class Services:
    def __init__(self, document):
        self.index = GeometryIndex(document)

    def pick_entity(self, point):
        h = self.index.pick(point, 2.0)
        return self.index.entity(h) if h else None

    def edges_geometry(self, handles=None, exclude=None, near=None):
        if handles is None:
            handles = [e.dxf.handle for e in self.index.document.modelspace()]
        wanted = [h for h in handles if h != exclude]
        segs = [tuple(s) for s in self.index.segments_of(wanted)]
        circles = [((c[0], c[1]), c[2], c[4], c[5])
                   for c in self.index.circles_of(wanted)]
        return segs, circles


class Harness:
    def __init__(self, document=None):
        self.document = document or Document(ezdxf.new("R2018"))
        self.history = History(self.document)
        self.services = Services(self.document)
        self.prompts: list[str] = []
        self.finished = False
        self.ctx = ToolContext(
            execute=self._execute,
            prompt=self.prompts.append,
            echo=self.prompts.append,
            finish=lambda: setattr(self, "finished", True),
            services=self.services,
        )

    def _execute(self, cmd):
        self.history.execute(cmd)
        self.services.index.invalidate()

    @property
    def msp(self):
        return self.document.modelspace()


def test_erase_and_move_tools():
    h = Harness()
    line = h.msp.add_line((0, 0), (10, 0))
    tool = EraseTool(h.ctx)
    tool.start()
    tool.on_selection([line])
    assert len(h.msp) == 0 and h.finished

    h = Harness()
    line = h.msp.add_line((0, 0), (10, 0))
    tool = MoveTool(h.ctx)
    tool.start()
    tool.on_selection([line])
    tool.on_point((0, 0))
    tool.on_point((5, 7))
    assert line.dxf.start.y == pytest.approx(7)


def test_copy_tool_multiple():
    h = Harness()
    line = h.msp.add_line((0, 0), (1, 0))
    tool = CopyTool(h.ctx)
    tool.start()
    tool.on_selection([line])
    tool.on_point((0, 0))
    tool.on_point((10, 0))
    tool.on_point((20, 0))
    assert len(h.msp.query("LINE")) == 3
    tool.on_enter()
    assert h.finished


def test_trim_tool_line_between_cutters():
    h = Harness()
    target = h.msp.add_line((0, 0), (100, 0))
    h.msp.add_line((30, -10), (30, 10))
    h.msp.add_line((70, -10), (70, 10))
    tool = TrimTool(h.ctx)
    tool.start()
    tool.on_selection([])          # Enter: all entities are edges
    tool.on_point((50, 0))         # pick the middle span
    lines = sorted(
        (l.dxf.start.x, l.dxf.end.x)
        for l in h.msp.query("LINE") if l.dxf.start.y == 0 and l.dxf.end.y == 0
    )
    assert lines == [(0.0, 30.0), (70.0, 100.0)]
    # undo restores the original entity
    h.history.undo()
    assert any(l.dxf.end.x == 100 for l in h.msp.query("LINE"))


def test_trim_circle_with_circle_edges():
    # The classic workflow: two intersecting circles, both preselected as
    # cutting edges, click the arc span to remove — circle becomes an ARC.
    h = Harness()
    c1 = h.msp.add_circle((0.0, 0.0), 10.0)
    c2 = h.msp.add_circle((12.0, 0.0), 10.0)
    tool = TrimTool(h.ctx)
    tool.start()
    tool.on_selection([c1, c2])     # noun-verb: both circles are edges
    tool.on_point((10.0, 0.0))      # pick c1's right arc (inside c2)
    assert len(h.msp.query("CIRCLE")) == 1     # c1 replaced
    arcs = h.msp.query("ARC")
    assert len(arcs) == 1
    arc = arcs[0]
    assert arc.dxf.center.x == pytest.approx(0.0)
    assert arc.dxf.radius == pytest.approx(10.0)
    # the removed span contains angle 0 (the pick); the survivor does not
    a0 = arc.dxf.start_angle % 360
    a1 = arc.dxf.end_angle % 360
    sweep = (a1 - a0) % 360
    assert ((0.0 - a0) % 360) > sweep      # 0 deg is outside the survivor
    # crossings at (6, +/-8): +/- atan2(8, 6) = +/-53.13 deg from c1
    expected = math.degrees(math.atan2(8.0, 6.0))
    assert a0 == pytest.approx(expected, abs=1e-6)
    assert a1 == pytest.approx(360.0 - expected, abs=1e-6)
    # trimming continues (multiple picks) until Enter
    tool.on_enter()
    assert h.finished


def test_trim_polyline_self_crossing_tails():
    # The user's sketch: an open polyline whose last segment crosses the
    # first one, leaving two tails at the corner. Both trim away using the
    # polyline itself as the cutting edge.
    h = Harness()
    pl = h.msp.add_lwpolyline(
        [(-2.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, -3.0)])
    tool = TrimTool(h.ctx)
    tool.start()
    tool.on_selection([])          # all edges (self-trim included anyway)
    tool.on_point((-1.0, 0.0))     # left tail of the first segment
    pls = h.msp.query("LWPOLYLINE")
    assert len(pls) == 1
    pts = [(round(x, 6), round(y, 6)) for x, y in pls[0].get_points("xy")]
    assert pts[0] == (0.0, 0.0)    # tail removed, starts at the crossing
    # now the bottom tail of the (new) last segment
    tool.on_point((0.0, -2.0))
    pls = h.msp.query("LWPOLYLINE")
    assert len(pls) == 1
    pts = [(round(x, 6), round(y, 6)) for x, y in pls[0].get_points("xy")]
    assert pts == [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]
    # undo restores the original polyline both times
    h.history.undo()
    h.history.undo()
    pts = [(round(x, 6), round(y, 6))
           for x, y in h.msp.query("LWPOLYLINE")[0].get_points("xy")]
    assert pts[0] == (-2.0, 0.0) and pts[-1] == (0.0, -3.0)


def test_trim_polyline_by_crossing_window():
    # The general gesture: a crossing rect over the polyline tail trims it.
    h = Harness()
    h.msp.add_lwpolyline(
        [(-2.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, -3.0)])
    tool = TrimTool(h.ctx)
    tool.start()
    tool.on_selection([])
    # crossing rect around the left tail (x in [-2, 0])
    pl = h.msp.query("LWPOLYLINE")[0]
    tool.on_target_entities([pl], (-1.8, -0.5, -0.5, 0.5))
    pts = [(round(x, 6), round(y, 6))
           for x, y in h.msp.query("LWPOLYLINE")[0].get_points("xy")]
    assert pts[0] == (0.0, 0.0)


def test_trim_closed_polyline_opens_ring():
    h = Harness()
    h.msp.add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 10)], close=True)
    h.msp.add_line((-5, 5), (15, 5))     # horizontal cutter
    tool = TrimTool(h.ctx)
    tool.start()
    tool.on_selection([])
    tool.on_point((0.0, 7.5))            # left side, above the cutter
    pls = h.msp.query("LWPOLYLINE")
    assert len(pls) == 1 and not pls[0].closed
    ys = [round(y, 6) for _x, y in pls[0].get_points("xy")]
    assert 5.0 in ys                     # the ring opened at the cutter


def test_extend_tool_and_shift_flip():
    h = Harness()
    target = h.msp.add_line((0, 0), (40, 0))
    h.msp.add_line((100, -10), (100, 10))
    tool = ExtendTool(h.ctx)
    tool.start()
    tool.on_selection([])
    tool.on_point((38, 0))         # near the right end
    stretched = [l for l in h.msp.query("LINE") if l.dxf.end.y == 0]
    assert any(l.dxf.end.x == pytest.approx(100) for l in stretched)


def test_fillet_zero_radius():
    h = Harness()
    l1 = h.msp.add_line((0, 0), (10, 0))
    l2 = h.msp.add_line((12, 2), (12, 10))
    tool = FilletTool(h.ctx)
    type(tool).radius = 0.0
    tool.start()
    tool.on_point((5, 0))
    tool.on_point((12, 6))
    xs = sorted((l.dxf.start.x, l.dxf.start.y, l.dxf.end.x, l.dxf.end.y)
                for l in h.msp.query("LINE"))
    assert (0.0, 0.0, 12.0, 0.0) in xs
    assert (12.0, 0.0, 12.0, 10.0) in xs


def _fillet_parallel(radius):
    """#15: offset a line by 4, fillet the pair: a semicircle of radius 2 at
    the end of the FIRST line nearest its pick, whatever the radius is.
    The first line stays as it is; the second is trimmed to the arc."""
    h = Harness()
    first = h.msp.add_line((0, 0), (10, 0))
    h.msp.add_line((-5, 4), (20, 4))
    tool = FilletTool(h.ctx)
    type(tool).radius = radius
    tool.start()
    tool.on_point((8, 0))           # near the right end of the first line
    tool.on_point((3, 4))
    lines = sorted((round(l.dxf.start.x, 6), round(l.dxf.start.y, 6),
                    round(l.dxf.end.x, 6), round(l.dxf.end.y, 6))
                   for l in h.msp.query("LINE"))
    arcs = list(h.msp.query("ARC"))
    return h, first, lines, arcs


@pytest.mark.parametrize("radius", [5.0, 0.0])
def test_fillet_parallel_lines_joins_them_with_a_semicircle(radius):
    h, first, lines, arcs = _fillet_parallel(radius)
    assert first.is_alive and (0.0, 0.0, 10.0, 0.0) in lines
    assert (-5.0, 4.0, 10.0, 4.0) in lines        # trimmed to the arc
    assert len(arcs) == 1
    arc = arcs[0]
    assert (arc.dxf.center.x, arc.dxf.center.y) == (pytest.approx(10),
                                                    pytest.approx(2))
    assert arc.dxf.radius == pytest.approx(2)
    # the half that bulges outward, beyond the lines' ends
    assert arc.dxf.start_angle % 360 == pytest.approx(270)
    assert arc.dxf.end_angle % 360 == pytest.approx(90)
    assert FilletTool.radius == radius            # the setting is untouched
    h.history.undo()
    assert not list(h.msp.query("ARC"))


def _run_fillet(h, radius, pick1, pick2):
    tool = FilletTool(h.ctx)
    FilletTool.radius = radius
    tool.start()
    tool.on_point(pick1)
    tool.on_point(pick2)


def _ends(e):
    if e.dxftype() == "LINE":
        return [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
    return [tuple(e.start_point)[:2], tuple(e.end_point)[:2]]


def _meets(a, b):
    return any(math.dist(p, q) < 1e-9 for p in _ends(a) for q in _ends(b))


def test_fillet_line_and_arc_is_tangent_to_both_and_trims_them():
    """#16: radius 5 between a line and an arc -- Rafael's everyday case."""
    h = Harness()
    h.msp.add_line((0, 0), (30, 0))
    h.msp.add_arc((50, 20), 15, 180, 300)
    _run_fillet(h, 5.0, (25, 0), (50 + 15 * math.cos(math.radians(240)),
                                  20 + 15 * math.sin(math.radians(240))))
    lines = list(h.msp.query("LINE"))
    arcs = sorted(h.msp.query("ARC"), key=lambda a: a.dxf.radius)
    assert len(lines) == 1 and len(arcs) == 2
    fillet, trimmed = arcs
    c = fillet.dxf.center
    assert fillet.dxf.radius == pytest.approx(5)
    assert c.y == pytest.approx(5)                           # tangent to y=0
    assert math.dist((c.x, c.y), (50, 20)) == pytest.approx(20)  # outside R15
    assert _meets(fillet, lines[0]) and _meets(fillet, trimmed)
    assert (0.0, 0.0) in [tuple(map(float, p)) for p in _ends(lines[0])]
    h.history.undo()
    assert len(list(h.msp.query("ARC"))) == 1
    assert list(h.msp.query("LINE"))[0].dxf.end.x == pytest.approx(30)


def test_fillet_two_arcs():
    h = Harness()
    h.msp.add_arc((0, 0), 10, 0, 180)
    h.msp.add_arc((30, 0), 10, 0, 180)
    _run_fillet(h, 6.0, (10 * math.cos(math.radians(20)),
                         10 * math.sin(math.radians(20))),
                (30 + 10 * math.cos(math.radians(160)),
                 10 * math.sin(math.radians(160))))
    arcs = list(h.msp.query("ARC"))
    fillet = next(a for a in arcs if a.dxf.radius == pytest.approx(6))
    others = [a for a in arcs if a is not fillet]
    c = fillet.dxf.center
    assert math.dist((c.x, c.y), (0, 0)) == pytest.approx(16)
    assert math.dist((c.x, c.y), (30, 0)) == pytest.approx(16)
    assert len(others) == 2 and all(_meets(fillet, o) for o in others)


def test_fillet_leaves_a_circle_whole():
    h = Harness()
    circle = h.msp.add_circle((50, 20), 15)
    h.msp.add_line((0, 0), (30, 0))
    _run_fillet(h, 5.0, (35, 20), (25, 0))
    assert circle.is_alive and circle.dxf.radius == 15
    fillet = next(a for a in h.msp.query("ARC"))
    line = next(iter(h.msp.query("LINE")))
    assert _meets(fillet, line)


def test_fillet_radius_zero_line_and_arc_meet_at_the_corner():
    h = Harness()
    h.msp.add_line((0, 0), (40, 0))
    h.msp.add_arc((50, 10), 15, 200, 300)        # crosses y = 0
    _run_fillet(h, 0.0, (5, 0), (50 + 15 * math.cos(math.radians(280)),
                                 10 + 15 * math.sin(math.radians(280))))
    line = next(iter(h.msp.query("LINE")))
    arc = next(iter(h.msp.query("ARC")))
    assert len(list(h.msp.query("ARC"))) == 1           # no fillet arc
    assert _meets(line, arc)


def _fillet_tool(h, radius=5.0):
    FilletTool.radius = radius
    h.ctx.undo_last = h.history.undo
    tool = FilletTool(h.ctx)
    tool.start()
    return tool


def _corner(h):
    h.msp.add_line((0, 0), (20, 0))
    h.msp.add_line((20, 0), (20, 20))


def test_fillet_prompts_follow_autocad():
    """Command Reference, FILLET: the settings line, the options, and the
    second prompt with its Shift hint."""
    h = Harness()
    _corner(h)
    tool = _fillet_tool(h, 5.0)
    assert h.prompts[-2] == "Current settings: Mode = TRIM, Radius = 5.0000"
    assert h.prompts[-1] == ("Select first object or "
                             "[Undo/Polyline/Radius/Trim/Multiple]:")
    tool.on_option("R")
    assert h.prompts[-1] == "Specify fillet radius <5.0000>:"
    tool.on_option("3")
    assert FilletTool.radius == 3.0
    assert h.prompts[-1].startswith("Select first object or [Undo/")
    tool.on_point((10, 0))
    assert h.prompts[-1] == "Select second object or shift-select to apply corner:"


def test_fillet_shift_on_the_second_pick_makes_a_corner():
    h = Harness()
    h.msp.add_line((0, 0), (18, 0))
    h.msp.add_line((20, 2), (20, 20))
    tool = _fillet_tool(h, 5.0)
    tool.on_point((10, 0))
    tool.shift = True
    tool.on_point((20, 10))
    assert not list(h.msp.query("ARC"))               # radius 0 this once
    ends = sorted((round(l.dxf.end.x, 6), round(l.dxf.end.y, 6))
                  for l in h.msp.query("LINE"))
    assert (20.0, 0.0) in ends or any(
        (round(l.dxf.start.x, 6), round(l.dxf.start.y, 6)) == (20.0, 0.0)
        for l in h.msp.query("LINE"))
    assert FilletTool.radius == 5.0                   # the setting stays


def test_fillet_no_trim_keeps_the_edges_and_is_shared_with_chamfer():
    from core import trimmode
    from tools.modify import ChamferTool

    h = Harness()
    _corner(h)
    tool = _fillet_tool(h, 5.0)
    try:
        tool.on_option("T")
        assert h.prompts[-1] == "Enter Trim mode option [Trim/No trim] <Trim>:"
        tool.on_option("N")
        assert trimmode.trimmode() is False
        tool.on_point((10, 0))
        tool.on_point((20, 10))
        assert len(list(h.msp.query("LINE"))) == 2    # both untouched
        assert len(list(h.msp.query("ARC"))) == 1
        chamfer = ChamferTool(h.ctx)
        chamfer.start()
        assert any("NOTRIM" in p for p in h.prompts[-2:])   # one TRIMMODE
    finally:
        trimmode.set_trimmode(True)


def test_fillet_multiple_and_undo():
    h = Harness()
    _corner(h)
    h.msp.add_line((0, 40), (20, 40))
    h.msp.add_line((20, 40), (20, 60))
    tool = _fillet_tool(h, 5.0)
    tool.on_option("M")
    tool.on_point((10, 0))
    tool.on_point((20, 10))
    assert h.prompts[-1].startswith("Select first object or [Undo/")
    tool.on_point((10, 40))
    tool.on_point((20, 50))
    assert len(list(h.msp.query("ARC"))) == 2
    tool.on_option("U")                               # the last one only
    assert len(list(h.msp.query("ARC"))) == 1
    tool.on_enter()
    assert h.finished


def test_fillet_polyline_rounds_every_corner():
    h = Harness()
    pl = h.msp.add_lwpolyline([(0, 0), (20, 0), (20, 10), (0, 10)], close=True)
    tool = _fillet_tool(h, 2.0)
    tool.on_option("P")
    assert h.prompts[-1] == "Select 2D polyline:"
    tool.on_point((10, 0))
    assert "4 lines were filleted" in h.prompts
    new = next(iter(h.msp.query("LWPOLYLINE")))
    assert not pl.is_alive or pl is not new
    bulges = [round(b, 4) for *_xy, b in new.get_points("xyb")]
    assert bulges.count(0.4142) == 4


def test_extend_ignores_phantom_arc_circle():
    # User repro: a trimmed circle (now an ARC) must NOT act as its full
    # phantom circle — EXTEND has to reach the real edge beyond it.
    h = Harness()
    # arc: right half-circle only (from -90 to 90 deg), center (50, 0) r=10
    h.msp.add_arc((50.0, 0.0), 10.0, -90.0, 90.0)
    h.msp.add_line((80.0, -10.0), (80.0, 10.0))   # the real boundary
    target = h.msp.add_line((20.0, 0.0), (30.0, 0.0))
    tool = ExtendTool(h.ctx)
    tool.start()
    tool.on_selection([])
    tool.on_point((29.0, 0.0))    # extend to the right
    lines = [l for l in h.msp.query("LINE") if l.dxf.start.y == 0]
    # the phantom left side of the circle would stop it at x=40; the real
    # first boundary on the sweep is the arc's right side at x=60
    assert any(l.dxf.end.x == pytest.approx(60.0) for l in lines)


def test_extend_polyline_ends():
    # The V-shaped polyline: both tips extend to a boundary above.
    h = Harness()
    h.msp.add_lwpolyline([(2.0, 8.0), (5.0, 2.0), (8.0, 8.0)])
    h.msp.add_line((-10.0, 10.0), (20.0, 10.0))   # boundary
    tool = ExtendTool(h.ctx)
    tool.start()
    tool.on_selection([])
    tool.on_point((7.5, 7.0))     # near the (8,8) tip
    pts = h.msp.query("LWPOLYLINE")[0].get_points("xy")
    assert (round(pts[-1][0], 6), round(pts[-1][1], 6)) == (9.0, 10.0)
    tool.on_point((2.4, 7.2))     # near the start tip
    pts = h.msp.query("LWPOLYLINE")[0].get_points("xy")
    assert (round(pts[0][0], 6), round(pts[0][1], 6)) == (1.0, 10.0)
    # undo twice restores the original V
    h.history.undo()
    h.history.undo()
    pts = h.msp.query("LWPOLYLINE")[0].get_points("xy")
    assert (round(pts[0][0], 6), round(pts[0][1], 6)) == (2.0, 8.0)
    assert (round(pts[-1][0], 6), round(pts[-1][1], 6)) == (8.0, 8.0)


def test_offset_tool_line():
    h = Harness()
    h.msp.add_line((0, 0), (100, 0))
    tool = OffsetTool(h.ctx)
    tool.start()
    assert tool.on_option("5")
    tool.on_point((50, 0.5))       # pick the line
    tool.on_point((50, 30))        # side: above
    news = [l for l in h.msp.query("LINE") if l.dxf.start.y != 0]
    assert len(news) == 1 and news[0].dxf.start.y == pytest.approx(5.0)


# -- grips ---------------------------------------------------------------------

def test_grip_geometry_and_edits():
    from core.select import apply_grip_edit, entity_grips

    doc = Document(ezdxf.new("R2018"))
    msp = doc.modelspace()

    line = msp.add_line((0, 0), (10, 0))
    grips = entity_grips(line)
    assert [(round(x), round(y), r) for x, y, r in grips] == [
        (0, 0, "end"), (5, 0, "mid"), (10, 0, "end")]
    apply_grip_edit(line, 2, "end", (10, 5))
    assert tuple(line.dxf.end)[:2] == (10.0, 5.0)
    apply_grip_edit(line, 1, "mid", (100, 100))   # mid moves whole line
    assert line.dxf.start.x == pytest.approx(95.0)

    circle = msp.add_circle((0, 0), 5)
    g = entity_grips(circle)
    assert g[0][2] == "center" and len(g) == 5
    apply_grip_edit(circle, 1, "quadrant", (8, 0))
    assert circle.dxf.radius == pytest.approx(8.0)
    apply_grip_edit(circle, 0, "center", (3, 3))
    assert circle.dxf.center.x == pytest.approx(3.0)

    pl = msp.add_lwpolyline([(0, 0), (10, 0), (10, 10)])
    apply_grip_edit(pl, 1, "vertex", (12, 3))
    pts = [(round(p[0]), round(p[1])) for p in pl.get_points("xy")]
    assert pts[1] == (12, 3)


def test_grip_edit_undo_via_snapshot():
    from core.actions import SnapshotCommand
    from core.select import apply_grip_edit

    doc = Document(ezdxf.new("R2018"))
    line = doc.modelspace().add_line((0, 0), (10, 0))
    history = History(doc)

    snap = SnapshotCommand([line])
    apply_grip_edit(line, 2, "end", (10, 8))
    snap.commit(doc)
    history._undo.append(snap)
    assert tuple(line.dxf.end)[:2] == (10.0, 8.0)
    history.undo()
    assert tuple(line.dxf.end)[:2] == (10.0, 0.0)
    history.redo()
    assert tuple(line.dxf.end)[:2] == (10.0, 8.0)


# -- OFFSET: the whole prompt tree ---------------------------------------------

class OffsetHarness:
    """Feeds an OffsetTool the way the controller does."""

    def __init__(self):
        from core.commands import History
        from core.document import Document
        from tools.base import ToolContext

        self.document = Document.new()
        self.history = History(self.document)
        self.out: list[str] = []
        self.finished = False
        self.entity = None
        self.ctx = ToolContext(
            execute=self.history.execute,
            prompt=self.out.append,
            echo=self.out.append,
            finish=lambda: setattr(self, "finished", True),
            undo_last=self.history.undo,
            services=self,
        )

    def pick_entity(self, point):
        return self.entity

    @property
    def msp(self):
        return self.document.modelspace()

    @property
    def text(self) -> str:
        return "\n".join(self.out)


def _offset_tool(h):
    from tools.edit import OffsetTool

    OffsetTool.distance = 10.0
    OffsetTool.erase_source = False
    OffsetTool.layer_mode = "source"
    tool = OffsetTool(h.ctx)
    tool.start()
    return tool


def test_the_offset_distance_can_be_picked_with_two_points():
    """AutoCAD takes a distance OR two points at that prompt."""
    h = OffsetHarness()
    line = h.msp.add_line((0, 0), (10, 0))
    h.entity = line
    tool = _offset_tool(h)
    tool.on_point((0.0, 0.0))          # first point of the measurement
    assert "second point" in h.text
    tool.on_point((0.0, 3.0))          # 3 units apart
    assert "Offset distance = 3" in h.text
    tool.on_point((5.0, 0.0))          # pick the object
    tool.on_point((5.0, 8.0))          # the side
    made = [e for e in h.msp if e is not line]
    assert len(made) == 1
    assert made[0].dxf.start.y == pytest.approx(3.0)


def test_typing_the_distance_still_works_and_sticks():
    from tools.edit import OffsetTool

    h = OffsetHarness()
    line = h.msp.add_line((0, 0), (10, 0))
    h.entity = line
    tool = _offset_tool(h)
    assert tool.on_option("2.5") is True
    tool.on_point((5.0, 0.0))
    tool.on_point((5.0, 8.0))
    made = [e for e in h.msp if e is not line]
    assert made[0].dxf.start.y == pytest.approx(2.5)
    assert OffsetTool.distance == pytest.approx(2.5)   # sticky for next time


def test_enter_accepts_the_current_distance():
    h = OffsetHarness()
    line = h.msp.add_line((0, 0), (10, 0))
    h.entity = line
    tool = _offset_tool(h)
    tool.on_enter()                    # <10>
    tool.on_point((5.0, 0.0))
    tool.on_point((5.0, 50.0))
    made = [e for e in h.msp if e is not line]
    assert made[0].dxf.start.y == pytest.approx(10.0)


def test_through_offsets_the_object_to_the_picked_point():
    h = OffsetHarness()
    line = h.msp.add_line((0, 0), (10, 0))
    h.entity = line
    tool = _offset_tool(h)
    assert tool.on_option("T") is True
    tool.on_point((5.0, 0.0))          # the object
    assert "through point" in h.text
    tool.on_point((5.0, 7.0))          # it must pass through here
    made = [e for e in h.msp if e is not line]
    assert made[0].dxf.start.y == pytest.approx(7.0)


def test_the_offset_keeps_the_source_layer_unless_told_otherwise():
    from tools.edit import OffsetTool

    h = OffsetHarness()
    h.document.doc.layers.add("MUROS")
    line = h.msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "MUROS"})
    h.entity = line
    tool = _offset_tool(h)
    tool.on_option("5")
    tool.on_point((5.0, 0.0))
    tool.on_point((5.0, 8.0))
    made = [e for e in h.msp if e is not line]
    assert made[0].dxf.layer == "MUROS"

    # Layer > Current puts it on the current layer instead.
    h2 = OffsetHarness()
    h2.document.doc.layers.add("MUROS")
    line2 = h2.msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "MUROS"})
    h2.entity = line2
    tool2 = _offset_tool(h2)
    tool2.on_option("L")
    tool2.on_option("C")
    tool2.on_option("5")
    tool2.on_point((5.0, 0.0))
    tool2.on_point((5.0, 8.0))
    made2 = [e for e in h2.msp if e is not line2]
    assert made2[0].dxf.layer == "0"
    OffsetTool.layer_mode = "source"


def test_erase_removes_the_source_after_offsetting():
    from tools.edit import OffsetTool

    h = OffsetHarness()
    line = h.msp.add_line((0, 0), (10, 0))
    h.entity = line
    tool = _offset_tool(h)
    tool.on_option("E")
    tool.on_option("Y")
    tool.on_option("4")
    tool.on_point((5.0, 0.0))
    tool.on_point((5.0, 8.0))
    remaining = list(h.msp)
    assert len(remaining) == 1 and remaining[0] is not line
    OffsetTool.erase_source = False


def test_offset_repeats_until_exit():
    h = OffsetHarness()
    line = h.msp.add_line((0, 0), (10, 0))
    h.entity = line
    tool = _offset_tool(h)
    tool.on_option("2")
    for _ in range(3):
        tool.on_point((5.0, 0.0))
        tool.on_point((5.0, 8.0))
    assert len([e for e in h.msp if e is not line]) == 3
    assert not h.finished
    tool.on_option("X")
    assert h.finished


def test_the_cursor_switches_between_points_and_objects_within_offset():
    """Distance is a point phase (crosshair); picking the object is not."""
    h = OffsetHarness()
    line = h.msp.add_line((0, 0), (10, 0))
    h.entity = line
    tool = _offset_tool(h)
    assert tool.entity_picker is False        # measuring a distance
    tool.on_option("5")
    assert tool.entity_picker is True         # choosing the object
    tool.on_point((5.0, 0.0))
    assert tool.entity_picker is False        # aiming at the side


# -- OFFSET on polylines -------------------------------------------------------

def _rows(points, bulges=None):
    bulges = bulges or [0.0] * len(points)
    return [(p[0], p[1], 0.0, 0.0, b) for p, b in zip(points, bulges)]


def test_a_closed_polyline_offsets_inward_like_ezdxfs_own_answer():
    """ezdxf.math.offset_vertices_2d is the oracle for the straight case."""
    from ezdxf.math import offset_vertices_2d

    from core.polyoffset import offset_polyline

    square = [(0, 0), (10, 0), (10, 10), (0, 10)]
    rows, closed = offset_polyline(_rows(square), True, 1.0, (5.0, 5.0))
    ours = [(round(r[0], 6), round(r[1], 6)) for r in rows]
    theirs = [(round(v.x, 6), round(v.y, 6))
              for v in offset_vertices_2d(square, 1.0, closed=True)]
    assert ours == theirs
    assert closed is True


def test_the_pick_side_decides_inward_or_outward():
    from core.polyoffset import offset_polyline

    square = [(0, 0), (10, 0), (10, 10), (0, 10)]
    inward, _ = offset_polyline(_rows(square), True, 1.0, (5.0, 5.0))
    outward, _ = offset_polyline(_rows(square), True, 1.0, (-5.0, 5.0))
    assert (round(inward[0][0], 6), round(inward[0][1], 6)) == (1.0, 1.0)
    assert (round(outward[0][0], 6), round(outward[0][1], 6)) == (-1.0, -1.0)


def test_a_corner_moves_further_than_the_offset_distance():
    """The vertex of a right angle moves by d*sqrt(2), not by d.

    Moving every vertex sideways by the distance is the tempting wrong
    implementation; it leaves the sides non-parallel.
    """
    from core.polyoffset import offset_polyline

    rows, _ = offset_polyline(_rows([(0, 0), (10, 0), (10, 10)]), False,
                              2.0, (5.0, 5.0))
    corner = (rows[1][0], rows[1][1])
    assert corner == pytest.approx((8.0, 2.0))
    assert math.dist(corner, (10.0, 0.0)) == pytest.approx(2.0 * math.sqrt(2))


def test_an_arc_segment_stays_an_arc_and_goes_concentric():
    from core.polyoffset import offset_polyline

    bulge = math.tan(math.radians(90) / 4)      # a quarter turn
    rows, _ = offset_polyline(
        _rows([(0, 0), (10, 0), (20, 10), (20, 20)], [0.0, bulge, 0.0, 0.0]),
        False, 2.0, (5.0, 5.0))
    assert rows[1][4] == pytest.approx(bulge, rel=1e-6)   # same sweep
    # Concentric about (10,10): the offset arc runs from (10,2) to (18,10).
    assert (rows[1][0], rows[1][1]) == pytest.approx((10.0, 2.0))
    assert (rows[2][0], rows[2][1]) == pytest.approx((18.0, 10.0))


def test_an_offset_that_swallows_the_shape_is_refused():
    from core.polyoffset import offset_polyline

    # A circle-like closed arc pair offset inward past its own centre.
    rows = _rows([(0, 0), (10, 0)], [1.0, 1.0])
    assert offset_polyline(rows, True, 50.0, (5.0, 0.1)) is None


def test_offsetting_a_polyline_through_the_command(qapp=None):
    h = OffsetHarness()
    poly = h.msp.add_lwpolyline([(0, 0), (10, 0), (10, 10)])
    h.entity = poly
    tool = _offset_tool(h)
    tool.on_option("2")
    tool.on_point((5.0, 0.0))          # pick the polyline
    tool.on_point((5.0, 5.0))          # inner side
    made = [e for e in h.msp if e is not poly]
    assert len(made) == 1
    assert made[0].dxftype() == "LWPOLYLINE"
    points = [(round(p[0], 6), round(p[1], 6))
              for p in made[0].get_points("xy")]
    assert points == [(0.0, 2.0), (8.0, 2.0), (8.0, 10.0)]


def test_an_old_style_polyline_can_be_offset_too():
    h = OffsetHarness()
    poly = h.msp.add_polyline2d([(0, 0), (10, 0), (10, 10)])
    h.entity = poly
    tool = _offset_tool(h)
    tool.on_option("2")
    tool.on_point((5.0, 0.0))
    tool.on_point((5.0, 5.0))
    made = [e for e in h.msp if e is not poly]
    assert len(made) == 1 and made[0].dxftype() == "LWPOLYLINE"


def test_through_works_on_a_polyline():
    h = OffsetHarness()
    poly = h.msp.add_lwpolyline([(0, 0), (10, 0), (10, 10)])
    h.entity = poly
    tool = _offset_tool(h)
    tool.on_option("T")
    tool.on_point((5.0, 0.0))
    tool.on_point((5.0, 3.0))          # it must pass through here
    made = [e for e in h.msp if e is not poly]
    points = [(round(p[0], 6), round(p[1], 6))
              for p in made[0].get_points("xy")]
    assert points[0] == (0.0, 3.0)


def test_a_closed_polyline_offsets_closed():
    h = OffsetHarness()
    poly = h.msp.add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 10)],
                                close=True)
    h.entity = poly
    tool = _offset_tool(h)
    tool.on_option("1")
    tool.on_point((5.0, 0.0))
    tool.on_point((5.0, 5.0))
    made = [e for e in h.msp if e is not poly][0]
    assert made.closed is True
    assert len(list(made.get_points("xy"))) == 4


# -- live previews: the ghost turns and grows ----------------------------------

def _rotate_tool():
    from core.commands import History
    from core.document import Document
    from tools.base import ToolContext
    from tools.edit import RotateTool

    class H:
        pass

    h = H()
    h.document = Document.new()
    h.history = History(h.document)
    h.out = []
    h.finished = False
    h.ctx = ToolContext(execute=h.history.execute, prompt=h.out.append,
                        echo=h.out.append,
                        finish=lambda: setattr(h, "finished", True))
    tool = RotateTool(h.ctx)
    tool.start()
    return h, tool


def test_rotate_previews_the_turn_about_the_base_point():
    h, tool = _rotate_tool()
    rect = h.document.modelspace().add_lwpolyline(
        [(0, 0), (20, 0), (20, 12), (0, 12)], close=True)
    tool.on_selection([rect])
    assert tool.ghost_placement((5.0, 5.0)) is None      # no base point yet

    tool.on_point((0.0, 0.0))                            # the corner
    assert tool.ghost_entities == [rect]
    assert tool.ghost_base == (0.0, 0.0)
    angle, factor = tool.ghost_placement((10.0, 10.0))
    assert angle == pytest.approx(45.0)
    assert factor == pytest.approx(1.0)
    assert tool.ghost_placement((0.0, 10.0))[0] == pytest.approx(90.0)


def test_the_rotate_preview_follows_the_reference_angle():
    h, tool = _rotate_tool()
    rect = h.document.modelspace().add_lwpolyline([(0, 0), (10, 0), (10, 5)])
    tool.on_selection([rect])
    tool.on_point((0.0, 0.0))
    tool.on_option("R")
    tool.on_option("30")                                 # reference = 30
    # Now the preview shows the angle RELATIVE to the reference.
    assert tool.ghost_placement((10.0, 10.0))[0] == pytest.approx(15.0)


def test_scale_previews_the_growth_and_a_picked_point_sets_it():
    from core.commands import History
    from core.document import Document
    from tools.base import ToolContext
    from tools.edit import ScaleTool

    class H:
        pass

    h = H()
    h.document = Document.new()
    h.history = History(h.document)
    h.finished = False
    h.ctx = ToolContext(execute=h.history.execute, prompt=lambda t: None,
                        echo=lambda t: None,
                        finish=lambda: setattr(h, "finished", True))
    line = h.document.modelspace().add_line((0, 0), (10, 0))
    tool = ScaleTool(h.ctx)
    tool.start()
    tool.on_selection([line])
    tool.on_point((0.0, 0.0))
    assert tool.ghost_base == (0.0, 0.0)
    assert tool.ghost_placement((3.0, 0.0))[1] == pytest.approx(3.0)
    tool.on_point((3.0, 0.0))                            # pick the factor
    assert line.dxf.end.x == pytest.approx(30.0)
    assert h.finished


def test_the_ghost_placement_matrix_turns_about_the_base(qapp):
    """The transform itself, in numbers: a vertex must land where the
    rotation says it does. A wrong multiplication order still looks like a
    rotation on screen — around the wrong point."""
    from PySide6.QtGui import QVector4D

    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document()
    try:
        vp = win.viewport
        vp.view.width, vp.view.height = 400, 400
        origin = (100.0, 50.0)          # the scene's float32 origin
        base = (110.0, 50.0)
        # A vertex stored at (10, 0) sits at world (110, 50) — the base
        # itself — so it must not move whatever the angle is.
        m = vp._mvp_about(origin[0], origin[1], base, 90.0, 1.0)
        at_base = m.map(QVector4D(10.0, 0.0, 0.0, 1.0))
        expected = vp._mvp(0.0, 0.0).map(QVector4D(110.0, 50.0, 0.0, 1.0))
        assert at_base.x() == pytest.approx(expected.x(), abs=1e-4)
        assert at_base.y() == pytest.approx(expected.y(), abs=1e-4)

        # A vertex 10 to the right of the base turns to 10 above it.
        m = vp._mvp_about(origin[0], origin[1], base, 90.0, 1.0)
        turned = m.map(QVector4D(20.0, 0.0, 0.0, 1.0))
        expected = vp._mvp(0.0, 0.0).map(QVector4D(110.0, 60.0, 0.0, 1.0))
        assert turned.x() == pytest.approx(expected.x(), abs=1e-4)
        assert turned.y() == pytest.approx(expected.y(), abs=1e-4)

        # And a factor of 2 doubles the distance from the base: a vertex at
        # world 120, ten to the right of the base, lands twenty away at 130.
        m = vp._mvp_about(origin[0], origin[1], base, 0.0, 2.0)
        grown = m.map(QVector4D(20.0, 0.0, 0.0, 1.0))
        expected = vp._mvp(0.0, 0.0).map(QVector4D(130.0, 50.0, 0.0, 1.0))
        assert grown.x() == pytest.approx(expected.x(), abs=1e-4)
    finally:
        win.close()


def _win_with_layers(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document("mm")
    doc = win.document
    doc.doc.layers.add("MUROS", color=1)
    doc.doc.layers.add("EJES", color=5)
    doc.doc.header["$CLAYER"] = "0"      # the current layer is NOT the target's
    return win


def test_trim_keeps_the_properties_of_what_it_cut(qapp):
    """Marco trimmed lines on a layer and the pieces came back on layer 0.
    A trimmed line IS that line, shortened: in AutoCAD it keeps its layer,
    colour, linetype and lineweight, and here it was being created fresh on
    whatever layer happened to be current."""
    win = _win_with_layers(qapp)
    try:
        doc = win.document
        msp = doc.modelspace()
        doc.doc.appids.add("COLEGA")
        target = msp.add_line((0, 0), (100, 0), dxfattribs={
            "layer": "MUROS", "color": 30, "lineweight": 50, "ltscale": 2.5})
        target.set_xdata("COLEGA", [(1000, "dato ajeno")])
        cutters = [msp.add_line((30, -10), (30, 10), dxfattribs={"layer": "EJES"}),
                   msp.add_line((70, -10), (70, 10), dxfattribs={"layer": "EJES"})]
        win.tools._invalidate_geometry()

        win.tools.selection = {c.dxf.handle for c in cutters}
        win.tools.start_tool("TRIM")
        win.tools.on_click(50.0, 0.0, False)

        cut = {c.dxf.handle for c in cutters}
        pieces = [e for e in msp if e.dxftype() == "LINE"
                  and e.dxf.handle not in cut]
        assert len(pieces) == 2
        for piece in pieces:
            assert piece.dxf.layer == "MUROS"
            assert piece.dxf.color == 30
            assert piece.dxf.lineweight == 50
            assert abs(piece.dxf.ltscale - 2.5) < 1e-9
            # somebody else's data hangs off that object and travels with it
            assert [t.value for t in piece.get_xdata("COLEGA")] == ["dato ajeno"]
    finally:
        win.document.dirty = False
        win.close()


def test_extend_keeps_the_properties_too(qapp):
    win = _win_with_layers(qapp)
    try:
        doc = win.document
        msp = doc.modelspace()
        target = msp.add_line((0, 0), (40, 0),
                              dxfattribs={"layer": "MUROS", "color": 30})
        boundary = msp.add_line((80, -10), (80, 10),
                                dxfattribs={"layer": "EJES"})
        win.tools._invalidate_geometry()

        win.tools.selection = {boundary.dxf.handle}
        win.tools.start_tool("EXTEND")
        win.tools.on_click(35.0, 0.0, False)

        pieces = [e for e in msp if e.dxftype() == "LINE"
                  and e.dxf.handle != boundary.dxf.handle]
        assert len(pieces) == 1
        assert pieces[0].dxf.layer == "MUROS" and pieces[0].dxf.color == 30
        assert pieces[0].dxf.end.x > 79        # it really did extend
    finally:
        win.document.dirty = False
        win.close()


def test_a_fillet_arc_takes_the_layer_only_when_both_edges_agree(qapp):
    """The trimmed pieces keep their own object's properties. The new arc has
    no object of its own: it takes them when both edges agree and leaves the
    current settings to decide when they do not."""
    from core.modify import common_style_source

    win = _win_with_layers(qapp)
    try:
        msp = win.document.modelspace()
        same_a = msp.add_line((0, 0), (50, 0), dxfattribs={"layer": "MUROS"})
        same_b = msp.add_line((50, 0), (50, 50), dxfattribs={"layer": "MUROS"})
        assert common_style_source([same_a, same_b]) is same_a

        other = msp.add_line((0, 0), (50, 0), dxfattribs={"layer": "EJES"})
        assert common_style_source([same_a, other]) is None
        assert common_style_source([]) is None
    finally:
        win.document.dirty = False
        win.close()


# -- OFFSET simplifies a shape it cannot follow (#58, Riccardo) ---------------

_RICCARDO = [(0, 0, 0, 0, 0), (11, 0, 0, 0, 0), (11, 12, 0, 0, 1),
             (9, 12, 0, 0, -1), (4.5, 12, 0, 0, 1), (0, 12, 0, 0, 0)]


def _check_clean_offset(rows, closed, source, distance):
    """No loop left: the result never crosses itself, and every point of it
    is at least ``distance`` from the original shape."""
    from core import polyoffset as P

    original = P.elements_of(source, True)
    result = P.elements_of(rows, closed)
    for element in result:
        for s in (0.05, 0.25, 0.5, 0.75, 0.95):
            point = P._point_at(element, s)
            assert min(P.distance_to(point, o) for o in original) \
                >= distance - 1e-6, f"{point} is inside the offset distance"
    n = len(result)
    for i in range(n):
        for j in range(i + 2, n):
            if closed and i == 0 and j == n - 1:
                continue
            assert not P._crossings(result[i], result[j]), "the offset crosses itself"


@pytest.mark.parametrize("distance", [1.0, 2.0, 3.0])
def test_an_inward_offset_drops_what_no_longer_fits(distance):
    from core.polyoffset import offset_polylines

    pieces = offset_polylines(_RICCARDO, True, distance, (5.5, 5.0))
    assert len(pieces) == 1
    rows, closed = pieces[0]
    assert closed
    _check_clean_offset(rows, closed, _RICCARDO, distance)


@pytest.mark.parametrize("distance", [1.0, 2.0, 3.0])
def test_an_outward_offset_closes_the_cup_it_cannot_follow(distance):
    from core.polyoffset import offset_polylines

    pieces = offset_polylines(_RICCARDO, True, distance, (-5.0, 5.0))
    assert len(pieces) == 1
    rows, closed = pieces[0]
    _check_clean_offset(rows, closed, _RICCARDO, distance)
    # past the cup's radius (2.25) the cup is gone: no arc that turns back in
    has_cup = any(r[4] < 0 for r in rows)
    assert has_cup == (distance < 2.25)


def test_an_offset_too_large_for_the_shape_gives_nothing():
    from core.polyoffset import offset_polylines

    assert offset_polylines(_RICCARDO, True, 6.0, (5.5, 5.0)) == []


_HOURGLASS = [(0, 0), (8, 0), (8, 4), (12, 4), (12, 0), (20, 0), (20, 10),
              (12, 10), (12, 6), (8, 6), (8, 10), (0, 10)]


def test_an_offset_that_pinches_a_neck_gives_two_islands():
    from core.polyoffset import offset_polylines

    source = _rows(_HOURGLASS)
    pieces = offset_polylines(source, True, 1.5, (4.0, 5.0))
    assert len(pieces) == 2
    for rows, closed in pieces:
        assert closed
        _check_clean_offset(rows, closed, source, 1.5)
    centres = sorted(sum(r[0] for r in rows) / len(rows) for rows, _c in pieces)
    assert centres[0] < 8 < 12 < centres[1]


def test_offset_command_adds_every_island(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document()
    try:
        win.tools._execute(actions.add_polyline(_HOURGLASS, closed=True))
        before = len(win.document.modelspace().query("LWPOLYLINE"))
        win.dispatcher.submit("OFFSET")
        win.tools.on_text("1.5")
        win.tools.on_click(0.0, 5.0)          # the polyline
        win.tools.on_click(4.0, 5.0)          # inside
        win.tools.on_text("")                 # Enter ends OFFSET
        assert len(win.document.modelspace().query("LWPOLYLINE")) == before + 2
        win._cmd_undo()
        assert len(win.document.modelspace().query("LWPOLYLINE")) == before
    finally:
        win.document.dirty = False
        win.close()


def test_an_arc_extended_past_zero_degrees_keeps_angles_in_range():
    """Found by the release tour: an arc from 0° to 90° extended down to a
    line came out with a start angle of -11.5°. AutoCAD writes [0, 360)."""
    import math

    h = Harness()
    h.msp.add_line((-6.0, -1.0), (6.0, -1.0))
    h.msp.add_arc((0.0, 0.0), 5.0, 0.0, 90.0)
    tool = ExtendTool(h.ctx)
    tool.start()
    tool.on_selection([])
    tool.on_point((4.33, 2.5))           # near the 0° end
    arc = h.msp.query("ARC")[0]
    want = 360.0 - math.degrees(math.asin(0.2))
    assert 0.0 <= arc.dxf.start_angle < 360.0
    assert arc.dxf.start_angle == pytest.approx(want)
    assert arc.dxf.end_angle == pytest.approx(90.0)
