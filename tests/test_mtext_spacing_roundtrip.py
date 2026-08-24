# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Save as DWG must not stack a paragraph's lines on top of each other.

Marco, an hour into dogfooding v0.4.4: original.dwg looked right, the copy
saved from IngeCAD drew every two-line label as two lines superimposed on
one. The text and its ``\\P`` survived; what the round trip corrupted was
``line_spacing_factor`` 1.0 -> 0.0 (plus flow_direction and spacing style
1 -> 0). Root cause: DXF says "absent group means default", ezdxf therefore
omits groups equal to their default, and LibreDWG's DXF importer stores a
missing group as ZERO instead of applying the default — the same family as
its MINSERT bug (upstream #1385).

Two defences, both pinned here:
* the intermediate DXF writes every optional group explicitly, and
* files already saved with the broken writer are repaired on open (0 is not
  a valid spacing factor, so the repair can never touch a real value).
"""
from __future__ import annotations

from pathlib import Path

import ezdxf
import pytest

from core import encoding
from core.document import Document
from formats.dwg_bridge import find_dxf2dwg, load_dwg, write_dwg


def _doc_with_two_line_label():
    doc = ezdxf.new("R2018", setup=True)
    doc.modelspace().add_mtext(
        "Tubo Negro Rectangular\\P2\"x4\"xE=2.5mm",
        dxfattribs={"char_height": 0.17, "insert": (10.0, 5.0),
                    "attachment_point": 7})
    return doc


def test_intermediate_dxf_writes_default_groups_explicitly(tmp_path):
    doc = _doc_with_two_line_label()
    out = tmp_path / "inter.dxf"
    encoding.write_dwg_intermediate(doc, out)
    back = ezdxf.readfile(out)
    mt = next(e for e in back.modelspace() if e.dxftype() == "MTEXT")
    assert mt.dxf.get("line_spacing_factor", None) == 1.0, (
        "the default spacing must be written out — LibreDWG turns a missing "
        "group into 0.0 and the paragraph collapses onto one line")
    assert mt.dxf.get("line_spacing_style", None) == 1
    assert mt.dxf.get("flow_direction", None) == 1


def test_document_is_untouched_after_writing_the_intermediate(tmp_path):
    """force_optional lives in a wrapped constructor: it must not leak."""
    from ezdxf.lldxf.tagwriter import TagWriter

    doc = _doc_with_two_line_label()
    version = doc.dxfversion
    encoding.write_dwg_intermediate(doc, tmp_path / "inter.dxf")
    assert doc.dxfversion == version
    # a writer built AFTER the save must behave normally again
    plain = tmp_path / "plain.dxf"
    doc.saveas(plain)
    back = ezdxf.readfile(plain)
    mt = next(e for e in back.modelspace() if e.dxftype() == "MTEXT")
    assert mt.dxf.get("line_spacing_factor", None) is None, (
        "the constructor patch leaked: ordinary saves now force optionals")


@pytest.mark.skipif(find_dxf2dwg() is None, reason="LibreDWG not available")
def test_line_spacing_survives_the_full_dwg_round_trip(tmp_path):
    document = Document(_doc_with_two_line_label())
    dwg = tmp_path / "label.dwg"
    document.save_as(dwg)
    back = load_dwg(dwg)
    mt = next(e for e in back.modelspace() if e.dxftype() == "MTEXT")
    assert mt.dxf.get("line_spacing_factor", 1.0) == 1.0
    assert mt.dxf.get("line_spacing_style", 1) == 1
    assert mt.dxf.get("flow_direction", 1) == 1
    assert "\\P" in mt.text


def test_repair_normalizes_the_zeroed_fields():
    doc = _doc_with_two_line_label()
    mt = next(e for e in doc.modelspace() if e.dxftype() == "MTEXT")
    # ezdxf's setters validate and would silently fix these, so inject the
    # corrupt values the way the DXF loader stores them — that is exactly
    # how a broken file arrives.
    mt.dxf.__dict__["line_spacing_factor"] = 0.0
    mt.dxf.__dict__["line_spacing_style"] = 0
    mt.dxf.__dict__["flow_direction"] = 0
    changed = encoding.repair_invalid_defaults(doc)
    assert changed == 1
    assert mt.dxf.line_spacing_factor == 1.0
    assert mt.dxf.line_spacing_style == 1
    assert mt.dxf.flow_direction == 1


def test_repair_leaves_real_values_alone():
    """0.8 is a legitimate tightened spacing — repair must never touch it."""
    doc = _doc_with_two_line_label()
    mt = next(e for e in doc.modelspace() if e.dxftype() == "MTEXT")
    mt.dxf.line_spacing_factor = 0.8
    mt.dxf.line_spacing_style = 2        # "exact", also legitimate
    mt.dxf.flow_direction = 3            # top-to-bottom, legitimate
    assert encoding.repair_invalid_defaults(doc) == 0
    assert mt.dxf.line_spacing_factor == 0.8
    assert mt.dxf.line_spacing_style == 2
    assert mt.dxf.flow_direction == 3


def test_repair_ignores_untouched_mtext():
    assert encoding.repair_invalid_defaults(_doc_with_two_line_label()) == 0
