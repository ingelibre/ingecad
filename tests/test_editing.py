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
