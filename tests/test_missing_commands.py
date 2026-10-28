# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""LENGTHEN, ALIGN, BOUNDARY, DONUT and SCALETEXT (#38), headless.

Every command is checked twice: the action's geometry with exact undo, and
the tool driven the way the command line drives it (points, typed options,
Enter) with AutoCAD's prompts and option letters.
"""
from __future__ import annotations

import math

import pytest

from core import actions, modify
from core.commands import History
from core.document import Document
from core.hatch_boundary import region_at_point
from tools.align import AlignTool
from tools.base import ToolContext
from tools.boundary import BoundaryTool
from tools.donut import DonutTool
from tools.lengthen import LengthenTool
from tools.scaletext import ScaleTextTool


class Harness:
    def __init__(self):
        self.document = Document.new()
        self.history = History(self.document)
        self.out: list[str] = []
        self.finished = False
        self.picks: list = []
        self.ctx = ToolContext(
            execute=self.history.execute,
            prompt=self.out.append,
            echo=self.out.append,
            finish=lambda: setattr(self, "finished", True),
            undo_last=lambda: self.history.undo(),
            services=self,
        )

    def pick_entity(self, point):
        return self.picks.pop(0) if self.picks else None

    def hatch_region_at(self, point):
        return region_at_point(list(self.msp), point)

    @property
    def msp(self):
        return self.document.modelspace()

    @property
    def text(self) -> str:
        return "\n".join(self.out)


def _xy(v):
    return (v.x, v.y)


# -- LENGTHEN ------------------------------------------------------------------

def test_lengthen_delta_moves_the_end_nearest_the_pick():
    h = Harness()
    line = h.msp.add_line((0, 0), (10, 0))
    h.history.execute(modify.lengthen(line, (9.0, 0.5), "DE", 5.0))
    assert _xy(line.dxf.end) == pytest.approx((15.0, 0.0))
    assert _xy(line.dxf.start) == pytest.approx((0.0, 0.0))
    h.history.undo()
    assert _xy(line.dxf.end) == pytest.approx((10.0, 0.0))
    # the other end, a negative delta trims (LENGTHEN, p. 1035)
    h.history.execute(modify.lengthen(line, (1.0, 0.0), "DE", -4.0))
    assert _xy(line.dxf.start) == pytest.approx((4.0, 0.0))


def test_lengthen_percent_total_and_dynamic_on_a_line():
    h = Harness()
    line = h.msp.add_line((0, 0), (10, 0))
    h.history.execute(modify.lengthen(line, (10, 0), "P", 150.0))
    assert _xy(line.dxf.end) == pytest.approx((15.0, 0.0))
    h.history.execute(modify.lengthen(line, (15, 0), "T", 4.0))
    assert _xy(line.dxf.end) == pytest.approx((4.0, 0.0))
    # dynamic: the end follows the point projected onto the line's direction
    h.history.execute(modify.lengthen(line, (4, 0), "DY", new_end=(20.0, 7.0)))
    assert _xy(line.dxf.end) == pytest.approx((20.0, 0.0))
    for _ in range(3):
        h.history.undo()
    assert _xy(line.dxf.end) == pytest.approx((10.0, 0.0))


def test_lengthen_an_arc_by_angle_and_by_length():
    h = Harness()
    arc = h.msp.add_arc((0, 0), 10, 0, 90)
    assert modify.arc_included_angle(arc) == pytest.approx(90.0)
    assert modify.object_length(arc) == pytest.approx(math.pi * 5)
    h.history.execute(modify.lengthen(arc, (0, 10), "DEA", 30.0))     # the end at 90°
    assert (arc.dxf.start_angle, arc.dxf.end_angle) == pytest.approx((0.0, 120.0))
    h.history.execute(modify.lengthen(arc, (10, 0), "TA", 45.0))      # the start at 0°
    assert (arc.dxf.start_angle % 360, arc.dxf.end_angle) == pytest.approx((75.0, 120.0))
    # a total LENGTH on an arc is an angle of length / radius
    h.history.execute(modify.lengthen(arc, (0, 10), "T", math.pi * 10))
    assert modify.arc_included_angle(arc) == pytest.approx(180.0)
    h.history.undo(); h.history.undo(); h.history.undo()
    assert (arc.dxf.start_angle, arc.dxf.end_angle) == pytest.approx((0.0, 90.0))


def test_lengthen_refuses_closed_objects_and_keeps_a_polyline_whole():
    h = Harness()
    circle = h.msp.add_circle((0, 0), 5)
    assert modify.lengthen(circle, (5, 0), "DE", 1.0) is None
    closed = h.msp.add_lwpolyline([(0, 0), (10, 0), (10, 10)], close=True)
    assert modify.lengthen(closed, (10, 10), "DE", 1.0) is None
    pline = h.msp.add_lwpolyline([(0, 0), (10, 0), (10, 10)])
    assert modify.object_length(pline) == pytest.approx(20.0)
    h.history.execute(modify.lengthen(pline, (10, 9), "T", 25.0))
    assert list(pline.get_points("xy"))[-1] == pytest.approx((10.0, 15.0))
    # a delta that would eat the whole end segment is refused, not applied
    assert modify.lengthen(pline, (10, 15), "DE", -30.0) is None


def test_lengthen_tool_reports_then_changes_with_autocad_prompts():
    h = Harness()
    line = h.msp.add_line((0, 0), (10, 0))
    tool = LengthenTool(h.ctx)
    tool.start()
    assert "Select an object or [DElta/Percent/Total/DYnamic]:" in h.out[-1]
    h.picks = [line]
    tool.on_point((5.0, 0.0))                     # picking only reports
    assert "Current length: 10.0000" in h.text
    assert _xy(line.dxf.end) == pytest.approx((10.0, 0.0))
    assert tool.on_option("DE") is True
    assert "Enter delta length or [Angle] <0>:" in h.out[-1]
    assert tool.on_option("5") is True
    assert "Select an object to change or [Undo]:" in h.out[-1]
    h.picks = [line]
    tool.on_point((9.0, 0.0))
    assert _xy(line.dxf.end) == pytest.approx((15.0, 0.0))
    h.picks = [line]
    tool.on_point((14.0, 0.0))                    # the loop goes on
    assert _xy(line.dxf.end) == pytest.approx((20.0, 0.0))
    assert tool.on_option("U") is True            # Undo peels the last one
    assert _xy(line.dxf.end) == pytest.approx((15.0, 0.0))
    tool.on_enter()
    assert h.finished
    # the delta is the next default, as AutoCAD keeps it
    tool2 = LengthenTool(h.ctx)
    tool2.start()
    tool2.on_option("DE")
    assert "<5>" in h.out[-1]


def test_lengthen_tool_angle_branch_and_dynamic_mode():
    h = Harness()
    arc = h.msp.add_arc((0, 0), 10, 0, 90)
    tool = LengthenTool(h.ctx)
    tool.start()
    tool.on_option("T")
    assert "Specify total length or [Angle]" in h.out[-1]
    tool.on_option("A")
    assert "Specify total angle <57>:" in h.out[-1]
    tool.on_option("180")
    h.picks = [arc]
    tool.on_point((0.0, 10.0))
    assert modify.arc_included_angle(arc) == pytest.approx(180.0)
    tool.on_enter()

    line = h.msp.add_line((0, 0), (10, 0))
    tool = LengthenTool(h.ctx)
    tool.start()
    tool.on_option("DY")
    assert "Select an object to change or [Undo]:" in h.out[-1]
    h.picks = [line]
    tool.on_point((9.0, 0.0))
    assert "Specify new end point:" in h.out[-1]
    assert tool.entity_picker is False, "the new end is a snapped point"
    tool.on_point((25.0, 3.0))
    assert _xy(line.dxf.end) == pytest.approx((25.0, 0.0))
    assert tool.entity_picker is True


# -- ALIGN ---------------------------------------------------------------------

def test_align_one_pair_moves_two_pairs_rotate_and_may_scale():
    h = Harness()
    line = h.msp.add_line((0, 0), (10, 0))
    h.history.execute(modify.align_entities([line], [(0, 0)], [(5, 5)]))
    assert _xy(line.dxf.start) == pytest.approx((5.0, 5.0))
    assert _xy(line.dxf.end) == pytest.approx((15.0, 5.0))
    h.history.undo()
    h.history.execute(modify.align_entities(
        [line], [(0, 0), (10, 0)], [(0, 0), (0, 20)], scale=False))
    assert _xy(line.dxf.end) == pytest.approx((0.0, 10.0)), "rotated, not scaled"
    h.history.undo()
    h.history.execute(modify.align_entities(
        [line], [(0, 0), (10, 0)], [(0, 0), (0, 20)], scale=True))
    assert _xy(line.dxf.end) == pytest.approx((0.0, 20.0)), "scaled onto the pair"
    h.history.undo()
    assert _xy(line.dxf.end) == pytest.approx((10.0, 0.0))


def test_align_tool_follows_the_prompt_sequence():
    h = Harness()
    line = h.msp.add_line((0, 0), (10, 0))
    tool = AlignTool(h.ctx)
    tool.start()
    tool.on_selection([line])
    assert "Specify first source point:" in h.out[-1]
    tool.on_point((0.0, 0.0))
    assert "Specify first destination point:" in h.out[-1]
    tool.on_point((0.0, 0.0))
    assert "Specify second source point or <continue>:" in h.out[-1]
    tool.on_point((10.0, 0.0))
    assert "Specify second destination point:" in h.out[-1]
    tool.on_point((0.0, 20.0))
    assert "Specify third source point or <continue>:" in h.out[-1]
    tool.on_enter()                               # <continue>
    assert "Scale objects based on alignment points? [Yes/No] <N>:" in h.out[-1]
    assert tool.on_option("Y") is True
    assert h.finished
    assert _xy(line.dxf.end) == pytest.approx((0.0, 20.0))

    # one pair + Enter = a move, no scale question
    h2 = Harness()
    line = h2.msp.add_line((0, 0), (10, 0))
    tool = AlignTool(h2.ctx)
    tool.start()
    tool.on_selection([line])
    tool.on_point((0.0, 0.0))
    tool.on_point((3.0, 4.0))
    tool.on_enter()
    assert h2.finished
    assert "Scale objects" not in h2.text
    assert _xy(line.dxf.start) == pytest.approx((3.0, 4.0))


# -- BOUNDARY ------------------------------------------------------------------

def _square(h, x0=0, y0=0, size=10):
    h.msp.add_line((x0, y0), (x0 + size, y0))
    h.msp.add_line((x0 + size, y0), (x0 + size, y0 + size))
    h.msp.add_line((x0 + size, y0 + size), (x0, y0 + size))
    h.msp.add_line((x0, y0 + size), (x0, y0))


def test_boundary_makes_a_closed_polyline_from_an_internal_point():
    h = Harness()
    _square(h)
    tool = BoundaryTool(h.ctx)
    tool.start()
    assert "Specify internal point or [Advanced options]:" in h.out[-1]
    tool.on_point((5.0, 5.0))
    polys = h.msp.query("LWPOLYLINE")
    assert len(polys) == 1 and polys[0].closed
    xs = sorted({round(p[0], 6) for p in polys[0].get_points("xy")})
    ys = sorted({round(p[1], 6) for p in polys[0].get_points("xy")})
    assert xs == [0.0, 10.0] and ys == [0.0, 10.0]
    assert "1 loop(s) extracted." in h.text
    tool.on_enter()
    assert h.finished and "BOUNDARY created 1 polyline(s)" in h.text
    h.history.undo()
    assert len(h.msp.query("LWPOLYLINE")) == 0
    # the four lines are untouched: BOUNDARY adds, it never replaces
    assert len(h.msp.query("LINE")) == 4


def test_boundary_islands_follow_the_island_detection_option():
    h = Harness()
    _square(h)
    h.msp.add_circle((5, 5), 2)                   # an island
    tool = BoundaryTool(h.ctx)
    tool.start()
    tool.on_point((1.0, 1.0))
    assert len(h.msp.query("LWPOLYLINE")) == 2, "outer loop and the island"
    assert "2 loop(s) extracted." in h.text
    tool.on_enter()
    h.history.undo()                              # one undo step for both
    assert len(h.msp.query("LWPOLYLINE")) == 0

    tool = BoundaryTool(h.ctx)
    tool.start()
    assert tool.on_option("A") is True
    assert "Enter an option [Boundary set/Island detection/Object type]:" in h.out[-1]
    assert tool.on_option("I") is True
    assert "Do you want island detection? [Yes/No] <Y>:" in h.out[-1]
    assert tool.on_option("N") is True
    assert "Specify internal point or [Advanced options]:" in h.out[-1]
    tool.on_point((1.0, 1.0))
    assert len(h.msp.query("LWPOLYLINE")) == 1, "no island without detection"
    BoundaryTool._islands = True                  # session-sticky: reset for others


def test_boundary_region_type_is_declined_and_a_miss_says_so():
    h = Harness()
    tool = BoundaryTool(h.ctx)
    tool.start()
    tool.on_option("A")
    tool.on_option("O")
    assert "Enter type of boundary object [Region/Polyline] <Polyline>:" in h.out[-1]
    tool.on_option("R")
    assert "does not create regions" in h.text
    tool.on_point((5.0, 5.0))                     # nothing encloses it
    assert "No closed boundary found at that point." in h.text
    assert len(h.msp) == 0


# -- DONUT ---------------------------------------------------------------------

def test_donut_is_a_closed_wide_polyline_of_two_half_circles():
    h = Harness()
    h.history.execute(actions.add_donut((5, 5), 2.0, 4.0))
    donut = h.msp[-1]
    assert donut.dxftype() == "LWPOLYLINE" and donut.closed
    rows = list(donut.get_points("xyseb"))
    assert len(rows) == 2
    # centre line radius = mean of the diameters / 2; width = their difference
    assert rows[0][:2] == pytest.approx((3.5, 5.0))
    assert rows[1][:2] == pytest.approx((6.5, 5.0))
    assert all(r[2] == pytest.approx(1.0) and r[3] == pytest.approx(1.0) for r in rows)
    assert all(r[4] == pytest.approx(1.0) for r in rows), "half-circle bulges"
    h.history.undo()
    assert len(h.msp) == 0
    # inside 0: a filled circle, width = the outside diameter
    rows = actions.donut_vertices((0, 0), 0.0, 3.0)
    assert rows[0][2] == pytest.approx(1.5) and rows[0][0] == pytest.approx(-0.75)


def test_donut_tool_repeats_centres_until_enter_and_keeps_the_diameters():
    h = Harness()
    DonutTool._inside, DonutTool._outside = 0.5, 1.0
    tool = DonutTool(h.ctx)
    tool.start()
    assert "Specify inside diameter of donut <0.5000>:" in h.out[-1]
    assert tool.on_option("2") is True
    assert "Specify outside diameter of donut <1.0000>:" in h.out[-1]
    assert tool.on_option("6") is True
    assert "Specify center of donut or <exit>:" in h.out[-1]
    tool.on_point((0.0, 0.0))
    tool.on_point((20.0, 0.0))
    assert len(h.msp.query("LWPOLYLINE")) == 2
    assert "Specify center of donut or <exit>:" in h.out[-1]
    tool.on_enter()
    assert h.finished
    tool2 = DonutTool(h.ctx)
    tool2.start()
    assert "<2.0000>" in h.out[-1], "DONUTID remembers the last value"
    tool2.on_enter()                              # accept both defaults
    assert "<6.0000>" in h.out[-1]
    tool2.on_enter()
    tool2.on_point((40.0, 0.0))
    rows = list(h.msp[-1].get_points("xyseb"))
    assert rows[0][2] == pytest.approx(2.0)      # (6 - 2) / 2
    DonutTool._inside, DonutTool._outside = 0.5, 1.0


# -- SCALETEXT -----------------------------------------------------------------

def test_scaletext_scales_each_text_about_its_own_base_point():
    h = Harness()
    a = h.msp.add_text("A", dxfattribs={"height": 2.5, "insert": (10, 20)})
    b = h.msp.add_text("B", dxfattribs={"height": 5.0, "insert": (100, 200)})
    m = h.msp.add_mtext("M", dxfattribs={"char_height": 2.0, "insert": (0, 0)})
    h.history.execute(modify.scale_texts([a, b, m], "E", height=10.0))
    assert a.dxf.height == pytest.approx(10.0) and b.dxf.height == pytest.approx(10.0)
    assert m.dxf.char_height == pytest.approx(10.0)
    # Existing: the insertion points do not move (SCALETEXT, p. 1698)
    assert _xy(a.dxf.insert) == pytest.approx((10.0, 20.0))
    assert _xy(b.dxf.insert) == pytest.approx((100.0, 200.0))
    assert _xy(m.dxf.insert) == pytest.approx((0.0, 0.0))
    h.history.undo()                              # ONE step for all three
    assert a.dxf.height == pytest.approx(2.5) and b.dxf.height == pytest.approx(5.0)
    assert m.dxf.char_height == pytest.approx(2.0)
    # a scale factor instead of a height
    h.history.execute(modify.scale_texts([a, b], "E", factor=2.0))
    assert a.dxf.height == pytest.approx(5.0) and b.dxf.height == pytest.approx(10.0)


def test_scaletext_base_point_options_pin_the_chosen_corner():
    h = Harness()
    t = h.msp.add_text("HOLA", dxfattribs={"height": 2.5, "insert": (10, 20)})
    top_right = modify.scaletext_base_point(t, "TR")
    # the top of the capitals as drawn: 22.5 with Arial, a little lower
    # with the Liberation twin standing in for it on a Linux without Arial
    from ezdxf.tools.text_size import text_size

    assert top_right[0] > 10.0
    assert top_right[1] == pytest.approx(20.0 + text_size(t).cap_height)
    assert 22.3 < top_right[1] <= 22.5
    h.history.execute(modify.scale_texts([t], "TR", factor=2.0))
    assert t.dxf.height == pytest.approx(5.0)
    # the top-right corner stayed where it was: the insert moved left and down
    after = modify.scaletext_base_point(t, "TR")
    assert after == pytest.approx(top_right, abs=1e-6)
    assert t.dxf.insert.x < 10.0 and t.dxf.insert.y < 20.0
    # the inverse: Existing keeps the insert and lets the corner move
    h.history.undo()
    h.history.execute(modify.scale_texts([t], "E", factor=2.0))
    assert _xy(t.dxf.insert) == pytest.approx((10.0, 20.0))
    assert modify.scaletext_base_point(t, "TR") != pytest.approx(top_right)


def test_scaletext_tool_prompts_match_and_scale_factor_paths():
    h = Harness()
    a = h.msp.add_text("A", dxfattribs={"height": 2.5, "insert": (0, 0)})
    ref = h.msp.add_text("R", dxfattribs={"height": 7.0, "insert": (50, 0)})
    ScaleTextTool._last_height = None
    tool = ScaleTextTool(h.ctx)
    tool.start()
    tool.on_selection([a, h.msp.add_line((0, 0), (1, 1))])   # the line is ignored
    assert ("Enter a base point option for scaling [Existing/Left/Center/Middle/"
            "Right/TL/TC/TR/ML/MC/MR/BL/BC/BR] <Existing>:") in h.out[-1]
    tool.on_enter()                               # <Existing>
    assert ("Specify new model height or [Paper height/Match object/Scale factor] "
            "<2.5000>:") in h.out[-1]
    assert tool.on_option("P") is True
    assert "annotative" in h.text
    assert tool.on_option("M") is True
    assert "Select a text object with the desired height:" in h.out[-1]
    h.picks = [ref]
    tool.on_point((50.0, 0.0))
    assert a.dxf.height == pytest.approx(7.0)
    assert h.finished and "1 text object(s) changed." in h.text

    h2 = Harness()
    a = h2.msp.add_text("A", dxfattribs={"height": 2.5, "insert": (0, 0)})
    tool = ScaleTextTool(h2.ctx)
    tool.start()
    tool.on_selection([a])
    assert tool.on_option("BL") is True
    assert tool.on_option("S") is True
    assert "Specify scale factor or [Reference] <2.0000>:" in h2.out[-1]
    assert tool.on_option("R") is True
    assert "Specify reference length <1.0000>:" in h2.out[-1]
    tool.on_option("2")
    assert "Specify new length:" in h2.out[-1]
    tool.on_option("6")                           # factor 3
    assert a.dxf.height == pytest.approx(7.5)
    assert h2.finished


# -- the registry, the aliases, the menus ---------------------------------------

def test_the_commands_are_registered_with_their_autocad_aliases():
    from core import aliases
    from views.tool_controller import ALL_TOOL_CLASSES

    for name in ("LENGTHEN", "ALIGN", "BOUNDARY", "-BOUNDARY", "DONUT", "SCALETEXT"):
        assert name in ALL_TOOL_CLASSES, name
    for alias, command in (("LEN", "LENGTHEN"), ("AL", "ALIGN"), ("BO", "BOUNDARY"),
                           ("DO", "DONUT")):
        assert aliases.DEFAULT_ALIASES[alias] == command


def test_typing_the_alias_starts_the_tool_in_the_window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    try:
        for typed, name in (("LEN", "LENGTHEN"), ("DO", "DONUT"), ("BO", "BOUNDARY"),
                            ("AL", "ALIGN"), ("SCALETEXT", "SCALETEXT")):
            win._on_command_submitted(typed)
            qapp.processEvents()
            active = win.tools.tool
            selecting = win.tools._selecting_for
            assert (active is not None and active.name == name) or (
                selecting is not None and type(selecting).__name__.upper().startswith(
                    name.replace("-", "")[:5])), (typed, active, selecting)
            win.tools.cancel()
            qapp.processEvents()
    finally:
        win.document.dirty = False
        win.close()
