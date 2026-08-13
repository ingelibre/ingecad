# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Accents survive Save-as-DWG (LibreDWG issue #1393)."""
from core.document import Document
from core.encoding import (INTERMEDIATE_DXF_VERSION, decode_escapes,
                           decode_escapes_in_document, escape_non_ascii,
                           write_dwg_intermediate)

ACC = "CAÑERÍA Ø m² Nº45°"


def test_escaping_is_reversible_and_leaves_ascii_alone():
    assert escape_non_ascii("PLANTA 1:100") == "PLANTA 1:100"
    assert escape_non_ascii("Nº 45°") == "N\\U+00BA 45\\U+00B0"
    assert decode_escapes("N\\U+00BA 45\\U+00B0") == "Nº 45°"
    assert decode_escapes(escape_non_ascii(ACC)) == ACC
    # MTEXT formatting codes are ASCII and must pass through untouched
    fmt = "{\\C1;ROJO} y \\P otra"
    assert escape_non_ascii(fmt) == fmt
    assert decode_escapes(fmt) == fmt


def test_escaping_survives_beyond_the_basic_plane():
    assert decode_escapes(escape_non_ascii("plano 𝜋 fin")) == "plano 𝜋 fin"


def test_the_intermediate_dxf_is_r2000_and_restores_the_document(tmp_path):
    """Pre-R13 input makes dxf2dwg return an empty DWG (LibreDWG #1386), so
    the intermediate always goes out as R2000 — and the caller's drawing must
    not notice that its version was borrowed for the write."""
    doc = Document.new()
    msp = doc.modelspace()
    mtext = msp.add_mtext(ACC, dxfattribs={"char_height": 2, "insert": (0, 5)})
    blk = doc.doc.blocks.new("BÑ")
    inner = blk.add_mtext(ACC, dxfattribs={"char_height": 1})
    version_before = doc.doc.dxfversion

    out = tmp_path / "inter.dxf"
    write_dwg_intermediate(doc.doc, out)

    body = out.read_text(encoding="cp1252", errors="replace")
    assert INTERMEDIATE_DXF_VERSION in body
    # the text goes out as the user typed it: LibreDWG PR #1375 carries the
    # accents through now, so nothing is escaped on our side any more
    assert "\\U+00D1" not in body
    assert "CAÑERÍA" in out.read_text(encoding="cp1252", errors="replace")

    assert doc.doc.dxfversion == version_before
    assert mtext.text == ACC and inner.text == ACC


def test_reading_back_decodes_the_escapes_everywhere(tmp_path):
    doc = Document.new()
    doc.modelspace().add_mtext("N\\U+00BA 3", dxfattribs={"char_height": 1})
    blk = doc.doc.blocks.new("B2")
    blk.add_mtext("cota 45\\U+00B0", dxfattribs={"char_height": 1})

    assert decode_escapes_in_document(doc.doc) == 2
    assert doc.modelspace()[0].text == "Nº 3"
    assert list(blk)[0].text == "cota 45°"
    # idempotent: a second pass finds nothing left to do
    assert decode_escapes_in_document(doc.doc) == 0
