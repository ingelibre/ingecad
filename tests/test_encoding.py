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


def test_the_intermediate_dxf_escapes_mtext_and_restores_the_document(tmp_path):
    doc = Document.new()
    msp = doc.modelspace()
    text = msp.add_text(ACC, dxfattribs={"height": 2})
    mtext = msp.add_mtext(ACC, dxfattribs={"char_height": 2, "insert": (0, 5)})
    blk = doc.doc.blocks.new("BÑ")
    inner = blk.add_mtext(ACC, dxfattribs={"char_height": 1})
    version_before = doc.doc.dxfversion

    out = tmp_path / "inter.dxf"
    write_dwg_intermediate(doc.doc, out)

    # the file went out as the version the DWG will have
    body = out.read_text(encoding="cp1252", errors="replace")
    assert INTERMEDIATE_DXF_VERSION in body
    assert "\\U+00D1" in body                      # the Ñ, escaped
    # TEXT is left as characters: it round-trips correctly that way
    assert "\\U+00D1ER" not in text.dxf.text

    # and the caller's document is exactly as it was
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
