# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Accented text in XDATA and XRECORDs survives Save as DWG and reopening.

Plugins keep their data there: an architecture plugin stores each wall's
record as JSON in XDATA ("Hormigón", "Fachada genérica") and its catalogues
in XRECORDs. Measured with the bundled LibreDWG, the R2000 intermediate
that ``write_dwg_intermediate`` writes is what keeps them. Converting an
R2010-or-later DXF instead, XDATA comes back as ``\\U+00f3`` escapes (which
the reader decodes) but XRECORDs lose their non-ASCII characters for good
("Ladrillo cerámico" -> "Ladrillo cermico"). These tests pin the behaviour
down, so changing the intermediate version or the converter cannot lose
plugin data silently: with an R2010 intermediate the first test fails.
"""
from __future__ import annotations

import pytest

from core.document import Document
from formats.dwg_bridge import find_dwg2dxf, find_dxf2dwg, load_dwg

needs_libredwg = pytest.mark.skipif(
    find_dwg2dxf() is None or find_dxf2dwg() is None,
    reason="LibreDWG tools not available",
)

APPID = "DEMO_PLUGIN"
RECORD = '{"material":"Hormigón","tipo":"Fachada genérica","año":2026,"ñ":"ç"}'


def _drawing():
    document = Document.new()
    doc = document.doc
    doc.appids.add(APPID)
    line = doc.modelspace().add_line((0, 0), (4, 0))
    line.set_xdata(APPID, [(1000, RECORD), (1000, "Muro de carga — planta baja")])
    catalogue = doc.rootdict.add_new_dict("DEMO_CATALOGUE")
    xrecord = catalogue.add_xrecord("TYPES")
    xrecord.reset([(1, "Ladrillo cerámico"), (1, "Lana mineral 0,035 W/mK")])
    return document, line.dxf.handle


@needs_libredwg
def test_accented_xdata_and_xrecords_survive_save_as_dwg(tmp_path):
    document, handle = _drawing()
    dwg = tmp_path / "plano.dwg"
    document.save_as(dwg)
    back = load_dwg(dwg).doc
    lines = list(back.modelspace().query("LINE"))
    assert len(lines) == 1
    xdata = [value for _code, value in lines[0].get_xdata(APPID)]
    assert xdata == [RECORD, "Muro de carga — planta baja"]
    catalogue = back.rootdict["DEMO_CATALOGUE"]
    assert [value for _code, value in catalogue["TYPES"].tags] == [
        "Ladrillo cerámico", "Lana mineral 0,035 W/mK"]


@needs_libredwg
def test_the_drawing_keeps_its_own_version_after_saving_as_dwg(tmp_path):
    """The R2000 downgrade is only for the converter's input: the open
    drawing is restored exactly (here, a new R2018 drawing)."""
    document, _handle = _drawing()
    before = document.doc.dxfversion
    document.save_as(tmp_path / "plano.dwg")
    assert document.doc.dxfversion == before
