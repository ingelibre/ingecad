# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The v0.5 definition of done, end to end: the surveyor's CSV becomes a
boundary snapped to the points, its chart and report, a surface with its
contours, the profile of an axis, a graded pad -- and the DWG that comes
out holds nothing a colleague's CAD would not understand."""
from __future__ import annotations

from pathlib import Path

import pytest

from core import actions as core_actions
from core.commands import History
from core.document import Document
from plugins.topografia import actions, grading
from plugins.topografia.points import parse_points
from plugins.topografia.tin import build_tin

SURVEY = Path(__file__).resolve().parent / "data" / "levantamiento-arequipa.csv"
PLAIN_DXF = {"POINT", "TEXT", "MTEXT", "LINE", "LWPOLYLINE", "POLYLINE", "3DFACE", "HATCH", "SOLID"}


def test_the_municipal_case_from_csv_to_a_plain_dwg(tmp_path):
    from formats.dwg_bridge import find_dwg2dxf, find_dxf2dwg, load_dwg

    document = Document.new()
    history = History(document)
    points = parse_points(SURVEY.read_text(encoding="utf-8"), "PNEZD")
    history.execute(actions.import_points(document, points, actions.LabelStyle(text_height=0.4)))
    msp = document.doc.modelspace()

    # the boundary, on the surveyed corners exactly (what NOD snap gives)
    lot = [(p.east, p.north) for p in points if p.desc.startswith("LOTE")]
    history.execute(core_actions.add_polyline(lot, closed=True))
    boundary = [e for e in msp if e.dxftype() == "LWPOLYLINE"][-1]
    assert actions.polygon_data(boundary).area == pytest.approx(1523.77, abs=0.01)
    history.execute(actions.annotate(document, [boundary], actions.AnnotationStyle(text_height=0.6)))
    history.execute(actions.construction_table(document, boundary, (lot[0][0] + 60, lot[0][1] + 40),
                                               actions.ChartStyle(text_height=0.7)))
    m = actions.memoria_for(document, boundary, "LOTE 1", "Arequipa", 0, {0: "Calle"})
    assert m.area == pytest.approx(1523.77, abs=0.01)
    history.execute(actions.memoria_mtext(document, (lot[0][0] + 60, lot[0][1] - 20), m.text(), 0.5))

    # the surface, its contours and labels
    ents = [e for e in msp if e.dxftype() == "POINT"] + [boundary]
    pts, breaklines = actions.surface_inputs(ents)
    tin = build_tin(pts, breaklines, name="TERRENO", max_edge=25.0)
    history.execute(actions.build_surface(document, tin))
    history.execute(actions.draw_contours(document, tin, 0.25, 4))
    contours = actions.contour_entities(document)
    assert len(contours) >= 4
    history.execute(actions.label_contours(document, contours, 0.5, spacing=20.0, decimals=2))

    # the profile of an axis across the lot, and a graded pad
    E0, N0 = lot[0]
    axis = msp.add_lwpolyline([(E0 + 6.0, N0 + 1.0), (E0 + 14.0, N0 + 44.0)])
    history.execute(actions.draw_profile(document, tin, axis, (E0 + 60.0, N0 - 60.0), 5.0, 1.0, 10.0, 0.5))
    pad = [(E0 + 8.0, N0 + 12.0), (E0 + 22.0, N0 + 12.0), (E0 + 22.0, N0 + 36.0), (E0 + 8.0, N0 + 36.0)]
    z_of = grading.platform_plane(pad[0], tin.z_at(*pad[0]) - 0.35)
    result = actions.grade_platform(tin, pad, z_of, grading.SlopeSpec(1.0, 1.5), 1.0, "CANCHA")
    assert result.closed
    history.execute(actions.draw_platform(document, result))
    cut, fill = actions.volumes_between(document, "TERRENO", "CANCHA")
    assert cut == pytest.approx(29.72, abs=0.05) and fill == pytest.approx(13.08, abs=0.05)

    # nothing but plain entities, and every one of them survives the DWG
    kinds = {e.dxftype() for e in msp}
    assert kinds <= PLAIN_DXF, kinds - PLAIN_DXF
    before = len(list(msp))
    dxf = tmp_path / "municipal.dxf"
    document.save_as(dxf)
    again = Document.load(dxf)
    assert len(list(again.doc.modelspace())) == before
    assert len(actions.survey_points(again)) == 96
    assert actions.surface_names(again) == ["TERRENO", "CANCHA"]
    assert len(actions.contour_entities(again)) == len(contours)

    if find_dxf2dwg() is None or find_dwg2dxf() is None:
        pytest.skip("LibreDWG converters not built")
    dwg = tmp_path / "municipal.dwg"
    document.save_as(dwg, "r2000")
    loaded = load_dwg(dwg)
    doc = loaded[0] if isinstance(loaded, tuple) else loaded
    back = Document(doc) if not isinstance(doc, Document) else doc
    assert len(actions.survey_points(back)) == 96
    assert {e.dxftype() for e in back.doc.modelspace()} <= PLAIN_DXF
    assert len(list(back.doc.modelspace())) == before
