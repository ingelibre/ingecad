# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Topography plugin, T5 in the drawing: the profile with its bands, a
polyline adopted as grade line, the sections, the earthworks table and
CSV -- each an undo step, all readable by any CAD."""
from __future__ import annotations

from pathlib import Path

import pytest

from core.commands import History
from core.document import Document
from plugins.topografia import actions, alignment, profile
from plugins.topografia.tin import build_tin
from tools.base import ToolContext


def _flat(z0: float = 100.0):
    return build_tin([(i * 10.0, j * 10.0, z0) for i in range(21) for j in range(21)])


def _document(tin=None):
    document = Document.new()
    history = History(document)
    if tin is not None:
        history.execute(actions.build_surface(document, tin))
    return document, history


def _texts(document):
    return [e.dxf.text for e in document.doc.modelspace() if e.dxftype() == "TEXT"]


def test_the_profile_is_drawn_with_its_bands_and_carries_its_frame():
    tin = build_tin([(i * 10.0, j * 10.0, 100.0 + 0.05 * i * 10.0) for i in range(21) for j in range(21)])
    document, history = _document(tin)
    msp = document.doc.modelspace()
    axis = msp.add_lwpolyline([(10.0, 100.0), (110.0, 100.0)])
    history.execute(actions.draw_profile(document, tin, axis, (300.0, 0.0), 25.0, 1.0, 10.0, 1.0, "EJE-1"))
    anchors = actions.profile_entities(document)
    assert len(anchors) == 1
    frame = actions.ProfileFrame.from_entity(anchors[0])
    assert frame.name == "EJE-1" and frame.axis_handle == axis.dxf.handle and frame.step == 25.0
    assert frame.vscale == 10.0 and frame.hscale == 1.0
    # the ground line: 5 stations, elevation 100.5 .. 105.5 mapped through the frame
    pts = [(v.x, v.y) for v in anchors[0].vertices_in_wcs()]
    assert len(pts) == 5
    s, z = frame.to_chainage(*pts[0])
    assert (s, z) == pytest.approx((0.0, 100.5))
    s, z = frame.to_chainage(*pts[-1])
    assert (s, z) == pytest.approx((100.0, 105.5))
    texts = _texts(document)
    assert "0+000.00" in texts and "0+100.00" in texts and "100.50" in texts and "105.50" in texts
    assert "STATION" in texts and "GROUND" in texts and "GRADE" not in texts
    assert any(t.startswith("PROFILE EJE-1") for t in texts)
    assert anchors[0].dxf.layer == "TOPO-PERFIL"
    history.undo()
    assert not actions.profile_entities(document) and not _texts(document)


def test_a_polyline_on_the_profile_becomes_the_grade_line_and_the_volumes_follow(tmp_path):
    tin = _flat()
    document, history = _document(tin)
    msp = document.doc.modelspace()
    axis = msp.add_lwpolyline([(10.0, 100.0), (110.0, 100.0)])
    history.execute(actions.draw_profile(document, tin, axis, (300.0, 0.0), 10.0, 1.0, 10.0, 1.0, "EJE"))
    anchor = actions.profile_entities(document)[0]
    frame = actions.ProfileFrame.from_entity(anchor)
    # a design line from 1 m of fill to 1 m of cut, drawn in profile coordinates
    design = msp.add_lwpolyline([frame.to_drawing(0.0, 101.0), frame.to_drawing(100.0, 99.0)])
    found = actions.frame_of(document, design)
    assert found is not None and found[0] is anchor
    history.execute(actions.register_grade(document, design, anchor, frame))
    assert actions.is_grade(design) and design.dxf.layer == "TOPO-RASANTE"
    assert actions.grade_profile_anchor(document, design) is anchor
    grade = actions.grade_of(design, frame)
    assert grade == pytest.approx([(0.0, 101.0), (100.0, 99.0)])
    assert "-2.00 %" in _texts(document)
    template = profile.Template(width=6.0, cut_hv=1.0, fill_hv=1.0)
    rows = actions.earthworks_rows(tin, axis, grade, frame.step, template)
    assert len(rows) == 11 and rows[0].fill_area == pytest.approx(7.0)
    assert rows[-1].mass == pytest.approx(0.0, abs=0.05)
    history.execute(actions.earthworks_table(document, rows, (300.0, -100.0), name="EJE"))
    texts = _texts(document)
    assert "EARTHWORKS EJE" in texts and "CUT AREA" in texts and "0+050.00" in texts
    csv = actions.earthworks_csv(rows)
    assert csv.splitlines()[0].startswith("station,ground_z,design_z")
    assert len(csv.splitlines()) == 12
    history.undo()
    history.undo()
    assert not actions.is_grade(design) and design.dxf.layer == "0"
    # a profile drawn with the grade shows the GRADE band
    history.execute(actions.draw_profile(document, tin, axis, (300.0, 200.0), 10.0, 1.0, 10.0, 1.0,
                                         "EJE", grade=grade))
    assert "GRADE" in _texts(document)


def test_sections_are_drawn_one_per_station_with_the_design_when_given():
    tin = _flat()
    document, history = _document(tin)
    axis = document.doc.modelspace().add_lwpolyline([(50.0, 50.0), (150.0, 50.0)])
    history.execute(actions.draw_sections(document, tin, axis, (400.0, 0.0), 50.0, 15.0))
    sections = [e for e in document.doc.modelspace()
                if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "TOPO-SECCIONES"]
    assert len(sections) == 3                                       # 0, 50, 100
    assert "0+050.00" in _texts(document)
    history.undo()
    grade = [(0.0, 99.0), (100.0, 99.0)]
    history.execute(actions.draw_sections(document, tin, axis, (400.0, 0.0), 50.0, 15.0,
                                          grade=grade, template=profile.Template(6.0, 1.0, 1.0)))
    designs = [e for e in document.doc.modelspace()
               if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "TOPO-RASANTE"]
    assert len(designs) == 3
    assert any(t.startswith("cut 7.00  fill 0.00") for t in _texts(document))


# -- tools, headless ---------------------------------------------------------------------------

class _Services:
    def __init__(self, document):
        self.document = document


class _Harness:
    def __init__(self, tin):
        self.document = Document.new()
        self.history = History(self.document)
        self.history.execute(actions.build_surface(self.document, tin))
        self.finished = False
        self.echoed: list[str] = []
        self.answers: list = []
        self.ctx = ToolContext(
            execute=self.history.execute, prompt=self.echoed.append,
            echo=self.echoed.append, finish=lambda: setattr(self, "finished", True),
            ask_text=lambda prompt, default="": self.answers.pop(0) if self.answers else None,
            undo_last=self.history.undo, services=_Services(self.document))

    @property
    def msp(self):
        return self.document.doc.modelspace()


def test_the_four_tools_run_end_to_end_headless(tmp_path):
    from plugins.topografia.tools import GradeLineTool, ProfileTool, SectionsTool, VolumesTool

    h = _Harness(_flat())
    axis = h.msp.add_lwpolyline([(10.0, 100.0), (110.0, 100.0)])
    tool = ProfileTool(h.ctx)
    tool.start()
    tool.on_selection([axis])
    assert tool.on_option("10")                                      # step
    tool.on_enter()                                                  # H 1:1000
    assert tool.on_option("100")                                     # V 1:100
    tool.on_point((300.0, 0.0))
    assert h.finished and any("Profile drawn: 11 stations" in line for line in h.echoed)
    anchor = actions.profile_entities(h.document)[0]
    frame = actions.ProfileFrame.from_entity(anchor)
    assert frame.vscale == pytest.approx(10.0)

    design = h.msp.add_lwpolyline([frame.to_drawing(0.0, 101.0), frame.to_drawing(100.0, 99.0)])
    h.finished = False
    grade = GradeLineTool(h.ctx)
    grade.start()
    grade.on_selection([design])
    assert h.finished and actions.is_grade(design)
    assert any("slopes -2.00 %" in line for line in h.echoed)

    h.finished = False
    sections = SectionsTool(h.ctx)
    sections.start()
    sections.on_selection([axis, design])
    assert sections.on_option("50")                                  # step
    sections.on_enter()                                              # width 15
    sections.on_enter()                                              # platform 6
    sections.on_enter()                                              # cut 1:1
    assert sections.on_option("1")                                   # fill 1:1
    sections.on_point((400.0, 0.0))
    assert h.finished and any("3 sections drawn" in line for line in h.echoed)

    h.finished = False
    out = tmp_path / "vol.csv"
    h.answers = [str(out)]
    volumes = VolumesTool(h.ctx)
    volumes.start()
    volumes.on_selection([design])
    volumes.on_enter()                                               # platform 6
    volumes.on_enter()                                               # cut 1:1
    assert volumes.on_option("1")                                    # fill 1:1
    assert volumes.on_option("P")                                    # prismoidal
    assert any("over 11 stations" in line for line in h.echoed)
    volumes.on_point((300.0, -200.0))
    assert h.finished
    assert out.exists() and len(out.read_text().splitlines()) == 12
    assert "EARTHWORKS EJE" in _texts(h.document)
