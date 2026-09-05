# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Topography plugin, T6 in the drawing: a platform graded on the ground
surface -- daylight line, hachures, design faces -- and the volume between
two drawn surfaces, each an undo step."""
from __future__ import annotations

import pytest

from core.commands import History
from core.document import Document
from plugins.topografia import actions, grading
from plugins.topografia.tin import build_tin
from tools.base import ToolContext

SQUARE = [(40.0, 40.0), (60.0, 40.0), (60.0, 60.0), (40.0, 60.0)]


def _ground():
    return build_tin([(i * 10.0, j * 10.0, 100.0) for i in range(11) for j in range(11)], name="TERRENO")


def _document():
    document = Document.new()
    history = History(document)
    history.execute(actions.build_surface(document, _ground()))
    return document, history


def test_a_platform_lands_as_daylight_hachures_and_a_second_surface():
    document, history = _document()
    ground = actions.read_surface(document, "TERRENO")
    z_of = grading.platform_plane(SQUARE[0], 98.0)
    result = actions.grade_platform(ground, SQUARE, z_of, grading.SlopeSpec(1.0, 1.0), 1.0, "PLATAFORMA")
    assert result.closed and result.design is not None and result.fill == pytest.approx(0.0, abs=1e-6)
    history.execute(actions.draw_platform(document, result))
    msp = document.doc.modelspace()
    day = [e for e in msp if e.dxftype() == "POLYLINE" and e.dxf.layer == "TOPO-LINEA-CERO"]
    assert len(day) == 1 and day[0].is_closed and len(day[0].vertices) == len(result.daylight)
    assert all(abs(v.dxf.location.z - 100.0) < 1e-9 for v in day[0].vertices)      # on the ground
    hachures = [e for e in msp if e.dxftype() == "LINE" and e.dxf.layer == "TOPO-TALUDES"]
    assert len(hachures) == len(result.daylight)
    assert actions.surface_names(document) == ["TERRENO", "PLATAFORMA"]
    faces = actions.surface_faces(document, "PLATAFORMA")
    assert len(faces) == len(result.design.triangles)
    assert {f.dxf.layer for f in faces} == {"TOPO-TIN-DISENO"}
    # the drawn surfaces measure the same as the computed ones
    cut, fill = actions.volumes_between(document, "TERRENO", "PLATAFORMA")
    assert cut == pytest.approx(result.cut, rel=1e-6) and fill == pytest.approx(0.0, abs=1e-6)
    assert actions.volumes_between(document, "TERRENO", "NADA") is None
    history.execute(actions.volume_label(document, (0.0, 0.0), "TERRENO", "PLATAFORMA", cut, fill))
    texts = [e.dxf.text for e in msp if e.dxftype() == "TEXT"]
    assert f"CUT {cut:.1f} m³" in texts and "FILL 0.0 m³" in texts
    history.undo()
    history.undo()
    assert actions.surface_names(document) == ["TERRENO"]
    assert not [e for e in msp if e.dxf.layer in ("TOPO-LINEA-CERO", "TOPO-TALUDES")]


# -- tools, headless --------------------------------------------------------------------------

class _Services:
    def __init__(self, document):
        self.document = document


class _Harness:
    def __init__(self):
        self.document, self.history = _document()
        self.finished = False
        self.echoed: list[str] = []
        self.ctx = ToolContext(
            execute=self.history.execute, prompt=self.echoed.append,
            echo=self.echoed.append, finish=lambda: setattr(self, "finished", True),
            undo_last=self.history.undo, services=_Services(self.document))

    @property
    def msp(self):
        return self.document.doc.modelspace()


def test_platform_daylight_and_voltin_tools_headless():
    from plugins.topografia.tools import DaylightTool, PlatformTool, VoltinTool

    h = _Harness()
    poly = h.msp.add_lwpolyline(SQUARE, close=True)
    tool = PlatformTool(h.ctx)
    tool.start()
    tool.on_selection([poly])
    assert tool.on_option("98")                       # elevation: 2 m of cut
    tool.on_enter()                                   # flat
    assert tool.on_option("1")                        # cut 1:1
    assert tool.on_option("1")                        # fill 1:1
    tool.on_enter()                                   # no benches
    assert tool.on_option("CANCHA")                   # name
    assert h.finished
    assert "CANCHA" in actions.surface_names(h.document)
    assert any("Daylight line closed" in line for line in h.echoed)
    assert any(line.startswith("CANCHA: cut ") for line in h.echoed)

    h.finished = False
    h.echoed.clear()
    line_only = DaylightTool(h.ctx)
    line_only.start()
    line_only.on_selection([poly])
    assert line_only.on_option("102")                 # 2 m of fill
    for _ in range(4):                                # slope, cut, fill, bench defaults
        line_only.on_enter()
    assert h.finished
    assert actions.surface_names(h.document) == ["TERRENO", "CANCHA"]      # no new surface
    day = [e for e in h.msp if e.dxftype() == "POLYLINE" and e.dxf.layer == "TOPO-LINEA-CERO"]
    assert len(day) == 2

    h.finished = False
    h.echoed.clear()
    vol = VoltinTool(h.ctx)
    vol.start()
    vol.on_enter()                                    # base TERRENO
    assert vol.on_option("CANCHA")
    assert any("CANCHA vs TERRENO: cut" in line for line in h.echoed)
    vol.on_point((0.0, 0.0))
    assert h.finished
    assert any(e.dxftype() == "TEXT" and e.dxf.text.startswith("CUT ") for e in h.msp)

    lonely = _Harness()
    VoltinTool(lonely.ctx).start()
    assert lonely.finished and "Two surfaces are needed" in lonely.echoed[-1]
