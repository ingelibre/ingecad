# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Topography plugin, T2: polygons -- annotation, the construction chart,
areas, subdivision by area, the UTM grid -- and the survey that looks real.
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from core.commands import History
from core.document import Document
from plugins.topografia import actions, geometry
from plugins.topografia.points import parse_points
from tools.base import ToolContext

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]        # CCW
SURVEY = Path(__file__).resolve().parent / "data" / "levantamiento-arequipa.csv"


# -- geometry ---------------------------------------------------------------------------

def test_area_perimeter_turn_and_angles_of_a_square():
    assert geometry.area(SQUARE) == 100.0
    assert geometry.perimeter(SQUARE) == 40.0
    assert not geometry.is_clockwise(SQUARE)
    assert geometry.is_clockwise(geometry.oriented(SQUARE, True))
    assert geometry.oriented(SQUARE, True)[0] == SQUARE[0]          # same first vertex
    assert geometry.interior_angles(SQUARE) == pytest.approx([90.0] * 4)
    assert [s.azimuth for s in geometry.sides(SQUARE)] == pytest.approx([90.0, 0.0, 270.0, 180.0])
    assert geometry.centroid(SQUARE) == pytest.approx((5.0, 5.0))


def test_interior_angles_sum_for_a_concave_lot_either_way_round():
    lot = [(0, 0), (40, 0), (40, 30), (20, 12), (0, 30)]           # an arrow, CCW
    for pts in (lot, geometry.oriented(lot, True)):
        angles = geometry.interior_angles(pts)
        assert sum(angles) == pytest.approx((len(pts) - 2) * 180.0)
        assert max(angles) > 180.0                                  # the notch


def test_cut_parallel_to_a_side_leaves_exactly_the_area_asked():
    cut = geometry.cut_parallel_to_side(SQUARE, 0, 40.0)          # side (0,0)-(10,0)
    assert cut.area_left == pytest.approx(40.0, abs=1e-6)
    assert cut.area_right == pytest.approx(60.0, abs=1e-6)
    xs, ys = sorted(p[0] for p in (cut.start, cut.end)), [cut.start[1], cut.end[1]]
    assert xs == pytest.approx([0.0, 10.0]) and ys == pytest.approx([4.0, 4.0])
    # the same asked from the far side: the piece hugs THAT side
    cut2 = geometry.cut_parallel_to_side(SQUARE, 2, 25.0)         # side (10,10)-(0,10)
    assert cut2.area_left == pytest.approx(25.0, abs=1e-6)
    assert cut2.start[1] == pytest.approx(7.5)


def test_cut_through_a_pivot_and_by_two_points():
    cut = geometry.cut_through_point(SQUARE, (5.0, 0.0), 50.0)
    assert cut.area_left == pytest.approx(50.0, abs=1e-6)
    assert cut.start == pytest.approx((5.0, 0.0))
    assert cut.end[1] == pytest.approx(10.0)                        # reaches the far side
    two = geometry.cut_by_two_points(SQUARE, (0.0, 2.0), (10.0, 6.0))
    assert two.area_left + two.area_right == pytest.approx(100.0)
    assert two.area_left == pytest.approx(60.0)                    # left of the line = above
    assert geometry.contains(SQUARE, (5.0, 5.0)) and not geometry.contains(SQUARE, (11.0, 5.0))
    assert geometry.contains(SQUARE, (10.0, 5.0))                  # boundary counts


def test_grid_values_and_the_nearest_side():
    assert geometry.grid_values(229140.0, 229180.0, 10.0) == [229140.0, 229150.0, 229160.0, 229170.0, 229180.0]
    assert geometry.grid_values(5.0, 4.0, 10.0) == []
    assert geometry.nearest_side(SQUARE, (5.0, -1.0)).index == 0
    assert geometry.nearest_side(SQUARE, (11.0, 5.0)).index == 1
    assert geometry.project_on_boundary(SQUARE, (5.0, -1.0)) == pytest.approx((5.0, 0.0))


# -- the survey that looks real ---------------------------------------------------------

def test_the_synthetic_survey_reads_like_a_real_one():
    """96 points of a lot in Arequipa (UTM 19S): control, the lot's five
    vertices, fence, house, street and spot heights -- the file the tests
    and Marco's BricsCAD check share."""
    text = SURVEY.read_text(encoding="utf-8")
    points = parse_points(text, "PNEZD")
    assert len(points) == 96
    assert points[0].desc == "EST-1" and points[1].desc == "BM-1"
    lot = [(p.east, p.north) for p in points if p.desc.startswith("LOTE")]
    assert len(lot) == 5
    assert 1500.0 < geometry.area(lot) < 1550.0                    # ~1 523.8 m2
    assert not geometry.is_clockwise(lot)
    assert sum(geometry.interior_angles(lot)) == pytest.approx(540.0)
    zs = [p.z for p in points]
    assert 2333.0 < min(zs) and max(zs) < 2337.0                    # Arequipa, sloping
    assert all(229100 < p.east < 229200 and 8181300 < p.north < 8181400 for p in points)


# -- actions -------------------------------------------------------------------------------

def _document():
    document = Document.new()
    return document, History(document)


def _texts(document):
    return [e for e in document.doc.modelspace() if e.dxftype() == "TEXT"]


def test_a_line_gets_its_distance_above_and_its_bearing_below():
    document, history = _document()
    msp = document.doc.modelspace()
    line = msp.add_line((0, 0), (10, 0))
    history.execute(actions.annotate(document, [line]))
    texts = _texts(document)
    assert [t.dxf.text for t in texts] == ["10.00", "N 90°00'00\" E"]
    assert texts[0].dxf.insert.y > 0 > texts[1].dxf.insert.y
    assert {t.dxf.layer for t in texts} == {"TOPO-ROTULOS"}
    assert texts[0].dxf.rotation == 0.0
    # a line drawn right-to-left reads the same way up, with the reverse bearing
    back = msp.add_line((10, 5), (0, 5))
    history.execute(actions.annotate(document, [back], actions.AnnotationStyle(mode="bearing")))
    assert _texts(document)[-1].dxf.text == "N 90°00'00\" W"
    assert _texts(document)[-1].dxf.rotation == 0.0
    # vertical: rotated to read upward; azimuth style
    up = msp.add_line((0, 0), (0, 10))
    history.execute(actions.annotate(document, [up], actions.AnnotationStyle(azimuth=True)))
    assert _texts(document)[-1].dxf.text == "0.0000°"
    assert _texts(document)[-1].dxf.rotation == pytest.approx(90.0)
    history.undo()
    assert len(_texts(document)) == 3


def test_a_polyline_is_annotated_segment_by_segment_and_an_arc_with_its_data():
    document, history = _document()
    msp = document.doc.modelspace()
    poly = msp.add_lwpolyline(SQUARE, close=True)
    arc = msp.add_arc((0, 0), 10.0, 0.0, 90.0)
    history.execute(actions.annotate(document, [poly, arc]))
    texts = [t.dxf.text for t in _texts(document)]
    assert texts.count("10.00") == 4 and len(texts) == 9
    assert texts[-1].startswith("L=15.71  R=10.00  D=90°00'00\"  C=14.14")


def test_the_construction_chart_lists_every_side_clockwise_with_area_and_perimeter():
    document, history = _document()
    msp = document.doc.modelspace()
    poly = msp.add_lwpolyline(SQUARE, close=True)
    data = actions.polygon_data(poly, actions.ChartStyle())
    assert [r[0] for r in data.rows] == ["V1", "V2", "V3", "V4"]
    assert data.rows[0][1] == "V1-V2" and data.rows[3][1] == "V4-V1"
    assert data.rows[0][3] == "N 0°00'00\" E"                       # clockwise: north first
    assert data.rows[0][4] == "90°00'00\""
    assert (data.rows[0][5], data.rows[0][6]) == ("0.00", "0.00")
    assert data.area == 100.0 and data.perimeter == 40.0
    history.execute(actions.construction_table(document, poly, (50.0, 50.0)))
    texts = [t.dxf.text for t in _texts(document)]
    assert "CONSTRUCTION CHART" in texts and "V1-V2" in texts
    assert "100.00 m²" in texts and "40.00 m" in texts
    assert texts.count("V1") == 2                                   # a row and the vertex label
    lines = [e for e in msp if e.dxftype() == "LINE"]
    assert len(lines) == (1 + 1 + 6 + 1) + 2 + 6                    # rows+title+header+2 footer, borders, verticals
    assert all(e.dxf.layer == "TOPO-CUADROS" for e in lines)
    history.undo()
    assert not _texts(document) and not [e for e in msp if e.dxftype() == "LINE"]
    azimuth = actions.polygon_data(poly, actions.ChartStyle(azimuth=True, clockwise=None))
    assert azimuth.rows[0][3] == "90.0000°"                         # as drawn: east first


def test_areas_subdivision_and_the_grid():
    document, history = _document()
    msp = document.doc.modelspace()
    poly = msp.add_lwpolyline(SQUARE, close=True)
    circle = msp.add_circle((30, 30), 2.0)
    assert actions.area_of(poly) == 100.0
    assert actions.area_of(circle) == pytest.approx(math.pi * 4.0)
    assert actions.area_of(msp.add_line((0, 0), (1, 1))) is None
    # a lot with an arc side: a 10 x 10 square whose top side bulges out
    # as a semicircle of radius 5 adds pi * 25 / 2
    arched = msp.add_lwpolyline([(0, 0, 0, 0, 0), (10, 0, 0, 0, 0), (10, 10, 0, 0, 1.0), (0, 10, 0, 0, 0)],
                                format="xyseb", close=True)
    assert actions.area_of(arched) == pytest.approx(100.0 + math.pi * 25.0 / 2.0, rel=1e-3)
    msp.delete_entity(arched)                       # the polyline counts below are the square's

    cut = geometry.cut_parallel_to_side(SQUARE, 0, 40.0)
    history.execute(actions.subdivide(document, poly, cut, split=True))
    polylines = [e for e in msp if e.dxftype() == "LWPOLYLINE"]
    assert len(polylines) == 2 and poly not in polylines
    pieces = sorted(geometry.area(geometry.polygon_vertices(p)) for p in polylines)
    assert pieces == pytest.approx([40.0, 60.0])
    cut_line = [e for e in msp if e.dxftype() == "LINE" and e.dxf.layer == "TOPO-SUBDIV"]
    assert len(cut_line) == 1
    history.undo()
    assert [e for e in msp if e.dxftype() == "LWPOLYLINE"] == [poly]

    history.execute(actions.utm_grid(document, 229140.0, 8181320.0, 229180.0, 8181350.0, 10.0))
    grid_lines = [e for e in msp if e.dxftype() == "LINE" and e.dxf.layer == "TOPO-RETICULA"]
    assert len(grid_lines) == 5 * 4 * 2                            # crosses at 5 x 4 nodes
    labels = [t.dxf.text for t in _texts(document) if t.dxf.layer == "TOPO-RETICULA"]
    assert "E 229 140" in labels and "N 8 181 350" in labels and len(labels) == 9


# -- the tools, headless ---------------------------------------------------------------------

class _Services:
    def __init__(self, document):
        self.document = document


class _Harness:
    def __init__(self):
        self.document = Document.new()
        self.history = History(self.document)
        self.finished = False
        self.echoed: list[str] = []
        self.ctx = ToolContext(
            execute=self.history.execute, prompt=self.echoed.append,
            echo=self.echoed.append, finish=lambda: setattr(self, "finished", True),
            undo_last=self.history.undo, services=_Services(self.document))

    @property
    def msp(self):
        return self.document.doc.modelspace()


def test_ctable_tool_places_the_chart_where_clicked_after_the_options():
    from plugins.topografia.tools import ConstructionTableTool

    h = _Harness()
    poly = h.msp.add_lwpolyline(SQUARE, close=True)
    tool = ConstructionTableTool(h.ctx)
    tool.start()
    tool.on_selection([h.msp.add_line((0, 0), (1, 1)), poly])
    assert tool.on_option("A")                                      # azimuth
    assert tool.on_option("O")                                      # counterclockwise
    tool.on_point((50.0, 50.0))
    assert h.finished
    texts = [t.dxf.text for t in h.msp if t.dxftype() == "TEXT"]
    assert "AZIMUTH" in texts and "90.0000°" in texts
    assert any("Area 100.00 m²" in line for line in h.echoed)


def test_subdiv_tool_parallel_flow_draws_the_cut_and_can_split():
    from plugins.topografia.tools import SubdivideTool

    h = _Harness()
    poly = h.msp.add_lwpolyline(SQUARE, close=True)
    tool = SubdivideTool(h.ctx)
    tool.start()
    tool.on_selection([poly])
    tool.on_enter()                                                 # Parallel (default)
    tool.on_point((5.0, -1.0))                                      # the bottom side
    assert tool.on_option("40")
    assert any("Pieces: 40.00 m² and 60.00 m²" in line for line in h.echoed)
    assert tool.on_option("Y")
    assert h.finished
    polylines = [e for e in h.msp if e.dxftype() == "LWPOLYLINE"]
    assert len(polylines) == 2
    # two points, no split: only the cut line lands
    h2 = _Harness()
    poly2 = h2.msp.add_lwpolyline(SQUARE, close=True)
    tool2 = SubdivideTool(h2.ctx)
    tool2.start()
    tool2.on_selection([poly2])
    assert tool2.on_option("T")
    tool2.on_point((0.0, 5.0))
    tool2.on_point((10.0, 5.0))
    tool2.on_enter()                                                # No
    assert h2.finished
    assert len([e for e in h2.msp if e.dxftype() == "LWPOLYLINE"]) == 1
    assert len([e for e in h2.msp if e.dxftype() == "LINE"]) == 1


def test_annotate_areasum_and_grid_tools_headless():
    from plugins.topografia.tools import AnnotateTool, AreaSumTool, UtmGridTool

    h = _Harness()
    poly = h.msp.add_lwpolyline(SQUARE, close=True)
    tool = AnnotateTool(h.ctx)
    tool.start()
    tool.on_selection([poly])
    assert tool.on_option("D")                                      # distances only
    tool.on_enter()
    assert h.finished
    assert [t.dxf.text for t in h.msp if t.dxftype() == "TEXT"] == ["10.00"] * 4

    h2 = _Harness()
    a = h2.msp.add_lwpolyline(SQUARE, close=True)
    b = h2.msp.add_circle((30, 30), 1.0)
    area = AreaSumTool(h2.ctx)
    area.start()
    area.on_selection([a, b, h2.msp.add_line((0, 0), (1, 0))])
    assert any("Total area: 103.14 m² (2 objects)" in line for line in h2.echoed)
    area.on_point((20.0, 20.0))
    assert h2.finished
    assert [t.dxf.text for t in h2.msp if t.dxftype() == "TEXT"] == ["TOTAL AREA = 103.14 m²"]

    h3 = _Harness()
    h3.msp.add_lwpolyline(SQUARE, close=True)
    grid = UtmGridTool(h3.ctx)
    grid.start()
    assert grid.on_option("E")                                      # extents of the drawing
    assert grid.on_option("5")
    assert grid.on_option("L")                                      # full lines
    assert h3.finished
    lines = [e for e in h3.msp if e.dxftype() == "LINE" and e.dxf.layer == "TOPO-RETICULA"]
    assert len(lines) == 3 + 3                                      # x = 0, 5, 10 and y = 0, 5, 10
