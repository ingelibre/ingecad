# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Justified text keeps its place through Save as DWG (#95).

A user opened a DXF, saved it as DWG and reopened it: every centred text
sat at X = 0, Y = 0. ezdxf writes a justified TEXT with its insertion point
equal to its alignment point (AutoCAD computes the left baseline instead);
LibreDWG's writer took "equal" for "unused" and left the alignment point out
of the DWG, which reads back -- in LibreDWG and in ODA alike -- as 0,0.
Fixed in the vendored LibreDWG (tools/libredwg-patches, encode.c).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from formats.dwg_bridge import find_dxf2dwg

_ALIGNMENTS = ("LEFT", "CENTER", "RIGHT", "MIDDLE", "TOP_LEFT", "TOP_CENTER",
               "MIDDLE_CENTER", "BOTTOM_RIGHT", "ALIGNED", "FIT")


@pytest.mark.skipif(find_dxf2dwg() is None, reason="LibreDWG not available")
def test_every_justification_survives_save_as_dwg(tmp_path: Path):
    from ezdxf.enums import TextEntityAlignment

    from core.templates import new_document
    from formats.dwg_bridge import load_dwg

    document = new_document("mm")
    msp = document.doc.modelspace()
    where = {}
    for i, name in enumerate(_ALIGNMENTS):
        p = (500_000.0 + 30 * i, 8_000_000.0 + i)      # UTM, far from 0,0
        text = msp.add_text(name, height=2.5)
        if name in ("ALIGNED", "FIT"):
            text.set_placement(p, (p[0] + 20, p[1]),
                               align=getattr(TextEntityAlignment, name))
        else:
            text.set_placement(p, align=getattr(TextEntityAlignment, name))
        where[name] = p
    # ATTDEF goes through the same DWG fields: a centred tag also moved
    tag = msp.add_attdef("NOMBRE", insert=(500_100.0, 8_000_050.0), height=2.5)
    tag.set_placement((500_100.0, 8_000_050.0),
                      align=TextEntityAlignment.MIDDLE_CENTER)
    path = tmp_path / "texts.dwg"
    document.save_as(path)

    back = load_dwg(path)
    found = {t.dxf.text: t for t in back.doc.modelspace().query("TEXT")}
    assert set(found) == set(_ALIGNMENTS)
    for name, p in where.items():
        _align, point, _second = found[name].get_placement()
        assert (point.x, point.y) == pytest.approx(p), name
    (attdef,) = back.doc.modelspace().query("ATTDEF")
    _align, point, _second = attdef.get_placement()
    assert (point.x, point.y) == pytest.approx((500_100.0, 8_000_050.0))
