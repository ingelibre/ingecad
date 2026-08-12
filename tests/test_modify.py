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


# -- CHAMFER -------------------------------------------------------------------

def test_a_chamfer_cuts_each_line_by_its_own_distance():
    """Dist1 goes on the FIRST line picked — the pick order is the answer."""
    from tools.modify import ChamferTool

    h = Harness()
    a = h.msp.add_line((10, 0), (0, 0))
    b = h.msp.add_line((0, 10), (0, 0))
    ChamferTool.dist1, ChamferTool.dist2, ChamferTool.trim = 3.0, 4.0, True
    tool = ChamferTool(h.ctx)
    tool.start()
    h._entity = a
    tool.on_point((5.0, 0.0))
    h._entity = b
    tool.on_point((0.0, 5.0))

    kept = entities(h.document)
    assert len(kept) == 3
    bevel = [e for e in kept
             if abs(e.dxf.start.x - 3.0) < 1e-9 or abs(e.dxf.end.x - 3.0) < 1e-9]
    assert bevel, "no bevel line was created"
    ends = sorted((round(e.dxf.start.x, 6), round(e.dxf.start.y, 6),
                   round(e.dxf.end.x, 6), round(e.dxf.end.y, 6)) for e in kept)
    assert (0.0, 4.0, 0.0, 10.0) in ends or (0.0, 10.0, 0.0, 4.0) in ends


def test_chamfer_with_no_trim_keeps_both_originals():
    from tools.modify import ChamferTool

    h = Harness()
    a = h.msp.add_line((10, 0), (0, 0))
    b = h.msp.add_line((0, 10), (0, 0))
    ChamferTool.dist1 = ChamferTool.dist2 = 2.0
    ChamferTool.trim = False
    try:
        tool = ChamferTool(h.ctx)
        tool.start()
        h._entity = a
        tool.on_point((5.0, 0.0))
        h._entity = b
        tool.on_point((0.0, 5.0))
        assert len(entities(h.document)) == 3      # both originals + bevel
        assert a.is_alive and b.is_alive
    finally:
        ChamferTool.trim = True


def test_a_chamfer_that_does_not_fit_says_so_and_changes_nothing():
    from tools.modify import ChamferTool

    h = Harness()
    a = h.msp.add_line((10, 0), (0, 0))
    b = h.msp.add_line((0, 10), (0, 0))
    ChamferTool.dist1 = ChamferTool.dist2 = 50.0
    try:
        tool = ChamferTool(h.ctx)
        tool.start()
        h._entity = a
        tool.on_point((5.0, 0.0))
        h._entity = b
        tool.on_point((0.0, 5.0))
        assert "does not fit" in h.text
        assert len(entities(h.document)) == 2
    finally:
        ChamferTool.dist1 = ChamferTool.dist2 = 0.0


# -- ARRAY ---------------------------------------------------------------------

def test_a_rectangular_array_leaves_the_original_and_adds_the_rest():
    document = Document.new()
    line = document.modelspace().add_line((0, 0), (1, 0))
    command = modify.array_rect([line], rows=2, columns=3,
                                row_spacing=10.0, column_spacing=5.0)
    command.do(document)
    kept = entities(document)
    assert len(kept) == 6                       # 2x3 including the original
    starts = sorted((round(e.dxf.start.x, 6), round(e.dxf.start.y, 6))
                    for e in kept)
    assert starts == [(0, 0), (0, 10), (5, 0), (5, 10), (10, 0), (10, 10)]


def test_negative_spacing_arrays_down_and_to_the_left():
    document = Document.new()
    line = document.modelspace().add_line((0, 0), (1, 0))
    modify.array_rect([line], 2, 2, -10.0, -5.0).do(document)
    starts = sorted((round(e.dxf.start.x, 6), round(e.dxf.start.y, 6))
                    for e in entities(document))
    assert starts == [(-5, -10), (-5, 0), (0, -10), (0, 0)]


def test_a_full_polar_array_spaces_items_around_the_whole_circle():
    document = Document.new()
    circle = document.modelspace().add_circle((10, 0), 1)
    modify.array_polar([circle], (0, 0), count=4, fill_angle=360.0).do(document)
    centres = sorted((round(e.dxf.center.x, 6), round(e.dxf.center.y, 6))
                     for e in entities(document))
    assert centres == [(-10, 0), (0, -10), (0, 10), (10, 0)]


def test_a_partial_polar_array_spans_the_angle_end_to_end():
    """3 items over 90 degrees sit at 0, 45 and 90 — not at 0, 30, 60."""
    document = Document.new()
    circle = document.modelspace().add_circle((10, 0), 1)
    modify.array_polar([circle], (0, 0), count=3, fill_angle=90.0).do(document)
    angles = sorted(round(math.degrees(math.atan2(e.dxf.center.y,
                                                  e.dxf.center.x)) % 360.0)
                    for e in entities(document))
    assert angles == [0, 45, 90]


def test_an_array_undoes_to_the_single_original():
    document = Document.new()
    line = document.modelspace().add_line((0, 0), (1, 0))
    command = modify.array_rect([line], 3, 3, 1.0, 1.0)
    command.do(document)
    assert len(entities(document)) == 9
    command.undo(document)
    assert len(entities(document)) == 1


def test_the_array_prompts_run_the_rectangular_flow():
    from tools.modify import ArrayTool

    h = Harness()
    line = h.msp.add_line((0, 0), (1, 0))
    tool = ArrayTool(h.ctx)
    tool.start()
    tool.on_selection([line])
    assert "Rectangular/Polar" in h.text
    tool.on_option("R")
    tool.on_option("2")        # rows
    tool.on_option("2")        # columns
    tool.on_option("10")       # row spacing
    tool.on_option("5")        # column spacing
    assert len(entities(h.document)) == 4
    assert h.finished


# -- MATCHPROP -----------------------------------------------------------------

def test_matchprop_copies_layer_colour_and_linetype():
    from tools.modify import MatchPropTool

    h = Harness()
    h.document.doc.layers.add("MUROS")
    source = h.msp.add_line((0, 0), (1, 0), dxfattribs={
        "layer": "MUROS", "color": 3, "linetype": "DASHED"})
    target = h.msp.add_line((0, 5), (1, 5))
    tool = MatchPropTool(h.ctx)
    tool.start()
    h._entity = source
    tool.on_point((0.5, 0.0))
    h._entity = target
    tool.on_point((0.5, 5.0))
    assert target.dxf.layer == "MUROS"
    assert target.dxf.color == 3
    assert target.dxf.linetype == "DASHED"


def test_matchprop_leaves_the_geometry_alone():
    h = Harness()
    source = h.msp.add_line((0, 0), (1, 0), dxfattribs={"color": 5})
    target = h.msp.add_circle((10, 10), 3)
    modify.match_properties(source, [target]).do(h.document)
    assert target.dxf.color == 5
    assert (target.dxf.center.x, target.dxf.center.y) == pytest.approx((10, 10))
    assert target.dxf.radius == pytest.approx(3.0)


def test_matchprop_undoes_every_target_individually():
    h = Harness()
    source = h.msp.add_line((0, 0), (1, 0), dxfattribs={"color": 5})
    a = h.msp.add_line((0, 1), (1, 1), dxfattribs={"color": 1})
    b = h.msp.add_line((0, 2), (1, 2), dxfattribs={"color": 2})
    command = modify.match_properties(source, [a, b])
    command.do(h.document)
    assert (a.dxf.color, b.dxf.color) == (5, 5)
    command.undo(h.document)
    assert (a.dxf.color, b.dxf.color) == (1, 2)


def test_matchprop_copies_the_text_style_between_texts():
    h = Harness()
    h.document.doc.styles.add("TITULOS", font="arial.ttf")
    source = h.msp.add_text("A", height=1, dxfattribs={"style": "TITULOS"})
    target = h.msp.add_text("B", height=1)
    modify.match_properties(source, [target]).do(h.document)
    assert target.dxf.style == "TITULOS"


# -- PEDIT ---------------------------------------------------------------------

def test_pedit_closes_and_reopens_a_polyline():
    from tools.modify import PeditTool

    h = Harness()
    poly = h.msp.add_lwpolyline([(0, 0), (10, 0), (10, 10)])
    h._entity = poly
    tool = PeditTool(h.ctx)
    tool.start()
    tool.on_point((5.0, 0.0))
    assert "Close" in h.text
    tool.on_option("C")
    assert poly.closed is True
    tool.on_option("O")
    assert poly.closed is False


def test_pedit_sets_the_width_of_every_segment():
    from tools.modify import PeditTool

    h = Harness()
    poly = h.msp.add_lwpolyline([(0, 0), (10, 0), (10, 10)])
    h._entity = poly
    tool = PeditTool(h.ctx)
    tool.start()
    tool.on_point((5.0, 0.0))
    tool.on_option("W")
    tool.on_option("0.5")
    widths = [(p[2], p[3]) for p in poly.get_points("xyseb")]
    assert all(w == pytest.approx((0.5, 0.5)) for w in widths)


def test_pedit_reverse_flips_the_direction_and_the_bulges():
    h = Harness()
    poly = h.msp.add_lwpolyline(
        [(0, 0, 0, 0, 0.5), (10, 0, 0, 0, 0), (10, 10, 0, 0, 0)],
        format="xyseb")
    modify.polyline_edit(poly, "reverse").do(h.document)
    rows = poly.get_points("xyseb")
    assert [(round(p[0], 6), round(p[1], 6)) for p in rows] == [
        (10, 10), (10, 0), (0, 0)]
    # The bulge that belonged to the first span now belongs to the last,
    # with the opposite sign — otherwise the arc would flip to the wrong side.
    assert rows[1][4] == pytest.approx(-0.5)


def test_pedit_offers_to_turn_a_line_into_a_polyline():
    from tools.modify import PeditTool

    h = Harness()
    line = h.msp.add_line((0, 0), (10, 0))
    h._entity = line
    tool = PeditTool(h.ctx)
    tool.start()
    tool.on_point((5.0, 0.0))
    assert "not a polyline" in h.text
    tool.on_option("Y")
    kept = entities(h.document)
    assert len(kept) == 1 and kept[0].dxftype() == "LWPOLYLINE"


def test_pedit_declining_the_conversion_leaves_the_line_alone():
    from tools.modify import PeditTool

    h = Harness()
    line = h.msp.add_line((0, 0), (10, 0))
    h._entity = line
    tool = PeditTool(h.ctx)
    tool.start()
    tool.on_point((5.0, 0.0))
    tool.on_option("N")
    assert h.finished
    kept = entities(h.document)
    assert len(kept) == 1 and kept[0].dxftype() == "LINE"


def test_matchprop_dimension_copies_style_overrides_and_rerenders():
    """The reference's Dimension special property (p. 1081): style AND
    properties — and the destination must LOOK matched, which means its
    block re-renders (setting dimstyle alone changed nothing visible)."""
    from core import styles as styles_mod
    from core.document import Document
    from core.commands import History
    from core.modify import match_properties

    doc = Document.new()
    styles_mod.install_default_styles(doc, unit_factor=1.0, overwrite=True)
    msp = doc.modelspace()
    src = msp.add_linear_dim(base=(0, 30), p1=(0, 0), p2=(20, 0),
                             dimstyle="Acot-100").render().dimension
    dst = msp.add_linear_dim(base=(40, 30), p1=(40, 0), p2=(60, 0),
                             dimstyle="ISO-25").render().dimension

    def text_height(dim):
        block = doc.doc.blocks.get(dim.dxf.geometry)
        return [e for e in block if e.dxftype() == "MTEXT"][0].dxf.char_height

    assert text_height(src) == 250.0        # 2.5 x dimscale 100
    assert text_height(dst) == 2.5
    old_block = dst.dxf.geometry
    history = History(doc)
    command = match_properties(src, [dst])
    assert command.needs_regen
    history.execute(command)
    assert dst.dxf.dimstyle == "Acot-100"
    assert dst.dxf.geometry != old_block    # re-rendered
    assert text_height(dst) == 250.0        # LOOKS matched
    history.undo()
    assert dst.dxf.dimstyle == "ISO-25"
    assert text_height(dst) == 2.5          # look restored too
    assert dst.dxf.geometry in doc.doc.blocks
