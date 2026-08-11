# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""STRETCH, BREAK and JOIN, headless."""
from __future__ import annotations

import math

import pytest

from core import modify
from core.commands import History
from core.document import Document
from tools.base import ToolContext
from tools.modify import BreakTool, JoinTool, StretchTool


class Harness:
    def __init__(self, entity=None, rects=()):
        self.document = Document.new()
        self.history = History(self.document)
        self.out: list[str] = []
        self.finished = False
        self._entity = entity
        self._rects = list(rects)
        self.ctx = ToolContext(
            execute=self.history.execute,
            prompt=self.out.append,
            echo=self.out.append,
            finish=lambda: setattr(self, "finished", True),
            services=self,
        )

    def pick_entity(self, point):
        return self._entity

    def crossing_rects(self):
        return list(self._rects)

    @property
    def msp(self):
        return self.document.modelspace()

    @property
    def text(self) -> str:
        return "\n".join(self.out)


def entities(document):
    return list(document.modelspace())


# -- STRETCH -------------------------------------------------------------------

def test_only_the_caught_end_of_a_line_moves():
    h = Harness(rects=[(9.0, -1.0, 11.0, 1.0)])
    line = h.msp.add_line((0, 0), (10, 0))
    tool = StretchTool(h.ctx)
    tool.start()
    tool.on_selection([line])
    tool.on_point((0.0, 0.0))
    tool.on_point((0.0, 5.0))
    assert (line.dxf.start.x, line.dxf.start.y) == pytest.approx((0.0, 0.0))
    assert (line.dxf.end.x, line.dxf.end.y) == pytest.approx((10.0, 5.0))


def test_an_object_fully_inside_the_window_moves_whole():
    h = Harness(rects=[(-1.0, -1.0, 11.0, 1.0)])
    line = h.msp.add_line((0, 0), (10, 0))
    tool = StretchTool(h.ctx)
    tool.start()
    tool.on_selection([line])
    tool.on_point((0.0, 0.0))
    tool.on_point((2.0, 3.0))
    assert (line.dxf.start.x, line.dxf.start.y) == pytest.approx((2.0, 3.0))
    assert (line.dxf.end.x, line.dxf.end.y) == pytest.approx((12.0, 3.0))


def test_a_circle_moves_only_when_its_centre_is_caught():
    """A circle has nothing to stretch: AutoCAD moves it, by its centre."""
    h = Harness(rects=[(-1.0, -1.0, 1.0, 1.0)])
    caught = h.msp.add_circle((0, 0), 5)
    missed = h.msp.add_circle((20, 0), 5)
    tool = StretchTool(h.ctx)
    tool.start()
    tool.on_selection([caught, missed])
    tool.on_point((0.0, 0.0))
    tool.on_point((0.0, 4.0))
    assert caught.dxf.center.y == pytest.approx(4.0)
    assert missed.dxf.center.y == pytest.approx(0.0)


def test_stretching_a_polyline_moves_only_the_caught_vertices():
    h = Harness(rects=[(9.0, 9.0, 11.0, 11.0)])
    poly = h.msp.add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 10)])
    tool = StretchTool(h.ctx)
    tool.start()
    tool.on_selection([poly])
    tool.on_point((0.0, 0.0))
    tool.on_point((3.0, 0.0))
    points = [(p[0], p[1]) for p in poly.get_points("xy")]
    assert points[0] == pytest.approx((0.0, 0.0))
    assert points[1] == pytest.approx((10.0, 0.0))
    assert points[2] == pytest.approx((13.0, 10.0))   # the caught one
    assert points[3] == pytest.approx((0.0, 10.0))


def test_a_stretched_arc_stays_an_arc_with_the_same_bulge():
    """Dragging one end of an arc has to leave an arc, not a chord."""
    h = Harness(rects=[(9.0, -1.0, 11.0, 1.0)])
    arc = h.msp.add_arc((0, 0), 10, start_angle=0, end_angle=90)
    before = modify.bulge_of_arc(arc.dxf.start_angle, arc.dxf.end_angle)
    tool = StretchTool(h.ctx)
    tool.start()
    tool.on_selection([arc])
    tool.on_point((0.0, 0.0))
    tool.on_point((5.0, 0.0))          # drag the start end +5 in x
    after = modify.bulge_of_arc(arc.dxf.start_angle, arc.dxf.end_angle)
    assert after == pytest.approx(before, rel=1e-6)
    # The moved end really is where it was dragged to.
    start = (arc.dxf.center.x + arc.dxf.radius
             * math.cos(math.radians(arc.dxf.start_angle)),
             arc.dxf.center.y + arc.dxf.radius
             * math.sin(math.radians(arc.dxf.start_angle)))
    assert start == pytest.approx((15.0, 0.0), abs=1e-6)


def test_stretch_undoes_exactly():
    h = Harness(rects=[(9.0, -1.0, 11.0, 1.0)])
    line = h.msp.add_line((0, 0), (10, 0))
    tool = StretchTool(h.ctx)
    tool.start()
    tool.on_selection([line])
    tool.on_point((0.0, 0.0))
    tool.on_point((0.0, 5.0))
    h.history.undo()
    assert (line.dxf.end.x, line.dxf.end.y) == pytest.approx((10.0, 0.0))


def test_enter_at_the_second_prompt_uses_the_first_point_as_displacement():
    h = Harness(rects=[(-1e9, -1e9, 1e9, 1e9)])
    line = h.msp.add_line((0, 0), (10, 0))
    tool = StretchTool(h.ctx)
    tool.start()
    tool.on_selection([line])
    tool.on_point((2.0, 3.0))
    tool.on_enter()
    assert (line.dxf.start.x, line.dxf.start.y) == pytest.approx((2.0, 3.0))


# -- BREAK ---------------------------------------------------------------------

def test_breaking_a_line_leaves_the_two_outer_pieces():
    h = Harness()
    line = h.msp.add_line((0, 0), (10, 0))
    h._entity = line
    tool = BreakTool(h.ctx)
    tool.start()
    tool.on_point((3.0, 0.0))          # picks the object AND the first point
    tool.on_point((7.0, 0.0))
    kept = [e for e in entities(h.document) if e.dxftype() == "LINE"]
    assert len(kept) == 2
    spans = sorted((round(e.dxf.start.x, 6), round(e.dxf.end.x, 6))
                   for e in kept)
    assert spans == [(0.0, 3.0), (7.0, 10.0)]


def test_breaking_at_one_point_splits_without_a_gap():
    h = Harness()
    line = h.msp.add_line((0, 0), (10, 0))
    h._entity = line
    tool = BreakTool(h.ctx)
    tool.start()
    tool.on_point((4.0, 0.0))
    tool.on_point((4.0, 0.0))
    kept = [e for e in entities(h.document) if e.dxftype() == "LINE"]
    assert len(kept) == 2
    total = sum(abs(e.dxf.end.x - e.dxf.start.x) for e in kept)
    assert total == pytest.approx(10.0)


def test_the_first_point_option_overrides_the_pick():
    h = Harness()
    line = h.msp.add_line((0, 0), (10, 0))
    h._entity = line
    tool = BreakTool(h.ctx)
    tool.start()
    tool.on_point((9.0, 0.0))          # pick, would be the first point
    assert tool.on_option("F") is True
    tool.on_point((2.0, 0.0))          # the real first point
    tool.on_point((5.0, 0.0))
    kept = sorted((round(e.dxf.start.x, 6), round(e.dxf.end.x, 6))
                  for e in entities(h.document) if e.dxftype() == "LINE")
    assert kept == [(0.0, 2.0), (5.0, 10.0)]


def test_breaking_a_circle_leaves_the_complementary_arc():
    document = Document.new()
    circle = document.modelspace().add_circle((0, 0), 10)
    command = modify.break_entity(circle, (10.0, 0.0), (0.0, 10.0))
    command.do(document)
    kept = entities(document)
    assert len(kept) == 1 and kept[0].dxftype() == "ARC"
    # Counter-clockwise from the second point back to the first: 90 -> 360.
    assert kept[0].dxf.start_angle == pytest.approx(90.0)
    assert kept[0].dxf.end_angle == pytest.approx(0.0)


def test_breaking_an_arc_keeps_the_two_outer_sweeps():
    document = Document.new()
    arc = document.modelspace().add_arc((0, 0), 10, start_angle=0,
                                        end_angle=180)
    p1 = (10 * math.cos(math.radians(60)), 10 * math.sin(math.radians(60)))
    p2 = (10 * math.cos(math.radians(120)), 10 * math.sin(math.radians(120)))
    modify.break_entity(arc, p1, p2).do(document)
    kept = sorted(entities(document),
                  key=lambda e: e.dxf.start_angle)
    assert [round(e.dxf.start_angle) for e in kept] == [0, 120]
    assert [round(e.dxf.end_angle) for e in kept] == [60, 180]


def test_a_broken_piece_keeps_the_layer_and_colour_of_the_original():
    document = Document.new()
    document.doc.layers.add("MUROS")
    line = document.modelspace().add_line(
        (0, 0), (10, 0), dxfattribs={"layer": "MUROS", "color": 3})
    modify.break_entity(line, (3, 0), (7, 0)).do(document)
    for piece in entities(document):
        assert piece.dxf.layer == "MUROS"
        assert piece.dxf.color == 3


def test_break_undoes_back_to_the_original_entity():
    document = Document.new()
    line = document.modelspace().add_line((0, 0), (10, 0))
    command = modify.break_entity(line, (3, 0), (7, 0))
    command.do(document)
    assert len(entities(document)) == 2
    command.undo(document)
    kept = entities(document)
    assert len(kept) == 1
    assert kept[0].dxf.end.x == pytest.approx(10.0)


def test_text_cannot_be_broken_and_says_so():
    h = Harness()
    text = h.msp.add_text("HOLA", height=2)
    text.set_placement((0, 0))
    h._entity = text
    tool = BreakTool(h.ctx)
    tool.start()
    tool.on_point((0.0, 0.0))
    assert "cannot be broken" in h.text
    assert h.finished


# -- JOIN ----------------------------------------------------------------------

def test_two_collinear_lines_join_into_one():
    h = Harness()
    a = h.msp.add_line((0, 0), (4, 0))
    b = h.msp.add_line((6, 0), (10, 0))
    tool = JoinTool(h.ctx)
    tool.start()
    tool.on_selection([a, b])
    kept = entities(h.document)
    assert len(kept) == 1 and kept[0].dxftype() == "LINE"
    assert kept[0].dxf.start.x == pytest.approx(0.0)
    assert kept[0].dxf.end.x == pytest.approx(10.0)


def test_lines_that_are_not_collinear_are_refused_with_a_reason():
    h = Harness()
    a = h.msp.add_line((0, 0), (4, 0))
    b = h.msp.add_line((0, 5), (4, 5))     # parallel, apart, not touching
    tool = JoinTool(h.ctx)
    tool.start()
    tool.on_selection([a, b])
    assert "collinear" in h.text or "contiguous" in h.text
    assert len(entities(h.document)) == 2   # nothing was destroyed


def test_arcs_of_the_same_circle_join_counterclockwise():
    h = Harness()
    a = h.msp.add_arc((0, 0), 10, start_angle=0, end_angle=90)
    b = h.msp.add_arc((0, 0), 10, start_angle=90, end_angle=180)
    tool = JoinTool(h.ctx)
    tool.start()
    tool.on_selection([a, b])
    kept = entities(h.document)
    assert len(kept) == 1 and kept[0].dxftype() == "ARC"
    assert kept[0].dxf.start_angle == pytest.approx(0.0)
    assert kept[0].dxf.end_angle == pytest.approx(180.0)


def test_arcs_of_different_circles_are_refused():
    h = Harness()
    a = h.msp.add_arc((0, 0), 10, start_angle=0, end_angle=90)
    b = h.msp.add_arc((0, 0), 7, start_angle=90, end_angle=180)
    tool = JoinTool(h.ctx)
    tool.start()
    tool.on_selection([a, b])
    assert "same circle" in h.text


def test_a_contiguous_chain_becomes_one_polyline():
    h = Harness()
    a = h.msp.add_line((0, 0), (10, 0))
    b = h.msp.add_line((10, 0), (10, 10))
    c = h.msp.add_lwpolyline([(10, 10), (0, 10)])
    tool = JoinTool(h.ctx)
    tool.start()
    tool.on_selection([a, b, c])
    kept = entities(h.document)
    assert len(kept) == 1 and kept[0].dxftype() == "LWPOLYLINE"
    points = [(round(p[0], 6), round(p[1], 6))
              for p in kept[0].get_points("xy")]
    assert points == [(0, 0), (10, 0), (10, 10), (0, 10)]


def test_a_chain_joined_out_of_order_and_reversed_still_works():
    """Real selections arrive in click order, not in drawing order."""
    h = Harness()
    a = h.msp.add_line((0, 0), (10, 0))
    b = h.msp.add_line((10, 10), (10, 0))     # drawn backwards
    tool = JoinTool(h.ctx)
    tool.start()
    tool.on_selection([b, a])
    kept = entities(h.document)
    assert len(kept) == 1
    points = [(round(p[0], 6), round(p[1], 6))
              for p in kept[0].get_points("xy")]
    assert points in ([(10, 10), (10, 0), (0, 0)], [(0, 0), (10, 0), (10, 10)])


def test_a_gap_in_the_chain_is_refused():
    h = Harness()
    a = h.msp.add_line((0, 0), (10, 0))
    b = h.msp.add_line((11, 0), (11, 10))
    tool = JoinTool(h.ctx)
    tool.start()
    tool.on_selection([a, b])
    assert "contiguous" in h.text or "collinear" in h.text
    assert len(entities(h.document)) == 2


def test_joining_an_arc_into_a_chain_keeps_it_curved():
    """The arc must survive as a bulge, not be flattened into a chord."""
    h = Harness()
    line = h.msp.add_line((0, 0), (10, 0))
    arc = h.msp.add_arc((10, 5), 5, start_angle=270, end_angle=0)
    tool = JoinTool(h.ctx)
    tool.start()
    tool.on_selection([line, arc])
    kept = entities(h.document)
    assert len(kept) == 1 and kept[0].dxftype() == "LWPOLYLINE"
    bulges = [p[4] for p in kept[0].get_points("xyseb")]
    assert any(abs(b) > 1e-9 for b in bulges), "the arc was flattened"


def test_join_undoes_back_to_the_pieces():
    h = Harness()
    a = h.msp.add_line((0, 0), (4, 0))
    b = h.msp.add_line((6, 0), (10, 0))
    tool = JoinTool(h.ctx)
    tool.start()
    tool.on_selection([a, b])
    assert len(entities(h.document)) == 1
    h.history.undo()
    assert len(entities(h.document)) == 2
