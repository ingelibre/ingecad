# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""LibreDWG bridge tests. Skipped when the satellite tools are not present
(CI does not build LibreDWG yet); they always run on dev machines with the
vendor/ build."""
from __future__ import annotations

import ezdxf
import pytest

from core.document import Document
from formats import dwg_bridge
from formats.dwg_bridge import (
    DwgBridgeError,
    dwg_to_dxf,
    dxf_to_dwg,
    find_dwg2dxf,
    find_dxf2dwg,
    load_dwg,
)

needs_libredwg = pytest.mark.skipif(
    find_dwg2dxf() is None or find_dxf2dwg() is None,
    reason="LibreDWG tools not available",
)


def _sample_doc():
    doc = ezdxf.new("R2000")
    msp = doc.modelspace()
    msp.add_line((1.25, 2.5), (300.75, 400.125))
    msp.add_circle((50.0, 60.0), 12.5)
    return doc


@needs_libredwg
def test_dxf_dwg_dxf_roundtrip(tmp_path):
    dxf = tmp_path / "plan.dxf"
    _sample_doc().saveas(dxf)

    dwg = tmp_path / "plan.dwg"
    dxf_to_dwg(dxf, dwg)
    assert dwg.stat().st_size > 0

    # Document.load is the app's real path: LibreDWG output needs ezdxf's
    # recover mode (it emits some handle-0 entities strict readfile rejects).
    back = dwg_to_dxf(dwg)
    doc2 = Document.load(back).doc
    lines = doc2.modelspace().query("LINE")
    assert len(lines) == 1
    start = lines[0].dxf.start
    assert start.x == pytest.approx(1.25) and start.y == pytest.approx(2.5)
    circles = doc2.modelspace().query("CIRCLE")
    assert len(circles) == 1
    assert circles[0].dxf.radius == pytest.approx(12.5)


def test_empty_salvage_raises_actionable_error(tmp_path, monkeypatch):
    # Real bench case (BASE COTAHUASI.dwg): LibreDWG emits broken DXF where
    # recover salvages a big entitydb but modelspace comes out empty. The user
    # must get an actionable message, not a blank drawing.
    doc = ezdxf.new("R2018")
    block = doc.blocks.new("ORPHANED")
    for i in range(150):
        block.add_line((i, 0.0), (i, 1.0))
    fake_dxf = tmp_path / "salvaged.dxf"
    doc.saveas(fake_dxf)

    monkeypatch.setattr(dwg_bridge, "dwg_to_dxf", lambda p: fake_dxf)
    with pytest.raises(DwgBridgeError, match="could not fully convert"):
        load_dwg(tmp_path / "colega.dwg")


def test_paperspace_only_sheet_is_not_rejected(tmp_path, monkeypatch):
    # ArchiCAD-published sheet: empty modelspace, content in a paperspace
    # layout. load_dwg must NOT reject it as a broken salvage.
    doc = ezdxf.new("R2018")
    psp = doc.layout("Layout1")
    for i in range(60):
        psp.add_line((i, 0.0), (i, 297.0))
    block = doc.blocks.new("DRAWING_1")
    for i in range(120):
        block.add_line((i, 0.0), (i, 1.0))
    fake_dxf = tmp_path / "sheet.dxf"
    doc.saveas(fake_dxf)

    monkeypatch.setattr(dwg_bridge, "dwg_to_dxf", lambda p: fake_dxf)
    document = load_dwg(tmp_path / "lamina.dwg")
    assert len(document.modelspace()) == 0
    assert any(len(lay) for lay in document.doc.layouts if lay.name != "Model")


@needs_libredwg
def test_accented_paths_survive(tmp_path):
    # skp2dae gotcha family: paths with accents and spaces must work.
    folder = tmp_path / "planos año"
    folder.mkdir()
    dxf = folder / "detalle ñandú.dxf"
    _sample_doc().saveas(dxf)
    dwg = folder / "detalle ñandú.dwg"
    dxf_to_dwg(dxf, dwg)
    back = dwg_to_dxf(dwg)
    assert len(Document.load(back).modelspace().query("LINE")) == 1
