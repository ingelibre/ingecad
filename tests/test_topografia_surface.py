# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Topography plugin, T3 in the drawing: the surface as 3DFACEs, read
back, flipped, cut, grown and clipped -- every step an undo step."""
from __future__ import annotations

from pathlib import Path

import pytest

from core.commands import History
from core.document import Document
from plugins.topografia import actions, geometry
from plugins.topografia.points import parse_points
from plugins.topografia.tin import build_tin
from tools.base import ToolContext

SURVEY = Path(__file__).resolve().parent / "data" / "levantamiento-arequipa.csv"


def _document():
    document = Document.new()
    return document, History(document)


def _faces(document):
    return [e for e in document.doc.modelspace() if e.dxftype() == "3DFACE"]


def test_the_survey_becomes_a_surface_of_faces_that_reads_back_exactly():
    document, history = _document()
    points = parse_points(SURVEY.read_text(encoding="utf-8"), "PNEZD")
    history.execute(actions.import_points(document, points))
    entities = [e for e in document.doc.modelspace() if e.dxftype() == "POINT"]
    lot = [(p.east, p.north) for p in points if p.desc.startswith("LOTE")]
    boundary = document.doc.modelspace().add_lwpolyline(lot, close=True)
    pts, breaklines = actions.surface_inputs(entities + [boundary])
    assert len(pts) == 96 and len(breaklines) == 1 and len(breaklines[0]) == 6
    tin = build_tin(pts, breaklines, name="LOTE")
    history.execute(actions.build_surface(document, tin))
    faces = _faces(document)
    assert len(faces) == len(tin.triangles) > 150
    assert {f.dxf.layer for f in faces} == {"TOPO-TIN"}
    assert actions.surface_names(document) == ["LOTE"]
    again = actions.read_surface(document, "LOTE")
    assert len(again.points) == len(tin.points) and len(again.triangles) == len(tin.triangles)
    assert again.stats()["area_2d"] == pytest.approx(tin.stats()["area_2d"])
    # the lot's sides are edges of the surface (the breakline held)
    edges = again.edges()
    index = {(round(p[0], 6), round(p[1], 6)): i for i, p in enumerate(again.points)}
    for k in range(5):
        u = index[(round(lot[k][0], 6), round(lot[k][1], 6))]
        v = index[(round(lot[(k + 1) % 5][0], 6), round(lot[(k + 1) % 5][1], 6))]
        assert ((u, v) if u < v else (v, u)) in edges
    history.undo()
    assert not _faces(document)


def _square_surface():
    document, history = _document()
    tin = build_tin([(0, 0, 0.0), (10, 0, 0.0), (10, 10, 4.0), (0, 10, 4.0)])
    history.execute(actions.build_surface(document, tin))
    return document, history


def test_flip_delete_insert_and_clip_each_undo():
    document, history = _square_surface()
    faces = _faces(document)
    assert len(faces) == 2
    hit = actions.nearest_edge(faces, (5.0, 5.0))
    assert hit is not None
    before = actions.read_surface(document).edges()
    history.execute(actions.flip_edge(document, hit[0], hit[1]))
    after = actions.read_surface(document).edges()
    assert len(_faces(document)) == 2 and after != before
    assert actions.read_surface(document).z_at(5.0, 5.0) == pytest.approx(2.0)
    history.undo()
    assert actions.read_surface(document).edges() == before

    faces = _faces(document)
    history.execute(actions.delete_faces([actions.face_at(faces, (1.0, 1.0))]))
    assert len(_faces(document)) == 1
    history.undo()
    assert len(_faces(document)) == 2

    command = actions.insert_point(document, _faces(document), (5.0, 5.0, 9.0))
    history.execute(command)
    grown = actions.read_surface(document)
    assert len(grown.triangles) == 4 and grown.z_at(5.0, 5.0) == pytest.approx(9.0)
    assert grown.stats()["bad_edges"] == 0
    history.undo()
    assert len(_faces(document)) == 2
    assert actions.insert_point(document, _faces(document), (50.0, 50.0, 1.0)) is None

    history.execute(actions.clip_surface(_faces(document), [(0, 0), (10, 0), (10, 4), (0, 4)]))
    assert len(_faces(document)) == 1
    history.undo()
    assert len(_faces(document)) == 2


# -- the tools, headless -----------------------------------------------------------

class _Services:
    def __init__(self, document):
        self.document = document
        self.picked = None

    def pick_entity(self, point):
        return self.picked


class _Harness:
    def __init__(self):
        self.document = Document.new()
        self.history = History(self.document)
        self.finished = False
        self.echoed: list[str] = []
        self.services = _Services(self.document)
        self.ctx = ToolContext(
            execute=self.history.execute, prompt=self.echoed.append,
            echo=self.echoed.append, finish=lambda: setattr(self, "finished", True),
            undo_last=self.history.undo, services=self.services)

    @property
    def msp(self):
        return self.document.doc.modelspace()


def test_tin_tool_builds_from_the_selection_and_reports():
    from plugins.topografia.tools import TinCheckTool, TinTool

    h = _Harness()
    for x, y, z in [(0, 0, 1), (10, 0, 2), (10, 10, 3), (0, 10, 4), (5, 5, 9)]:
        h.msp.add_point((x, y, z))
    tool = TinTool(h.ctx)
    tool.start()
    tool.on_selection(list(h.msp))
    assert tool.on_option("LOTE")                                 # the name
    tool.on_enter()                                              # no max edge
    assert h.finished
    assert len(_faces(h.document)) == 4
    assert any("LOTE: 4 triangles, 5 points" in line for line in h.echoed)
    h2 = _Harness()
    h2.msp.add_point((0, 0, 0))
    TinTool(h2.ctx).on_selection(list(h2.msp))
    assert h2.finished and "at least three points" in h2.echoed[-1]
    check = TinCheckTool(h.ctx)
    check.start()
    assert "LOTE: 4 triangles" in h.echoed[-1]


def test_tinedit_tool_flips_deletes_inserts_and_clips():
    from plugins.topografia.tools import TinEditTool

    h = _Harness()
    tin = build_tin([(0, 0, 0.0), (10, 0, 0.0), (10, 10, 4.0), (0, 10, 4.0)])
    h.history.execute(actions.build_surface(h.document, tin))
    tool = TinEditTool(h.ctx)
    tool.start()
    assert tool.on_option("F")
    tool.on_point((5.0, 5.0))
    assert "Edge flipped." in h.echoed
    assert tool.on_option("I")
    tool.on_point((5.0, 5.0))
    assert tool.on_option("9")
    assert len(_faces(h.document)) == 4
    assert tool.on_option("D")
    tool.on_point((1.0, 1.0))
    assert len(_faces(h.document)) == 3
    boundary = h.msp.add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 10)], close=True)
    h.services.picked = boundary
    assert tool.on_option("C")
    tool.on_point((10.0, 5.0))
    assert len(_faces(h.document)) == 3                           # all inside: nothing removed
    tool.on_enter()
    assert h.finished
