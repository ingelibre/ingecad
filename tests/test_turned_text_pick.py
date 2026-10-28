# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A turned text is picked by its own rectangle, not by its box.

The box of a label at 45 degrees is mostly empty paper: a click there took
the text, and the selection outline was a huge square. GeoCad Yaguarete
(Fernando Bellocchio's plugin) had to patch both.
"""
from __future__ import annotations

import ezdxf
import numpy as np
import pytest

from core.document import Document
from core.select import GeometryIndex


def _texts():
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    left = msp.add_text("CALLE LOS PINOS", dxfattribs={
        "height": 2.5, "rotation": 45, "insert": (0, 0)})
    centred = msp.add_text("AV. EJERCITO", dxfattribs={
        "height": 2.5, "rotation": 30})
    centred.set_placement((100, 0), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
    mtext = msp.add_mtext("LOTE 12\\PMZ B", dxfattribs={
        "char_height": 2.0, "insert": (200, 0), "rotation": 60})
    return Document(doc), (left, centred, mtext)


@pytest.mark.parametrize("which", [0, 1, 2])
def test_the_turned_rectangle_fills_exactly_the_texts_box(which):
    document, texts = _texts()
    text = texts[which]
    quad = GeometryIndex._text_quad(text)
    box = GeometryIndex._text_extents(text)
    assert quad is not None
    assert (quad[:, 0].min(), quad[:, 1].min(),
            quad[:, 0].max(), quad[:, 1].max()) == pytest.approx(box, abs=1e-6)


def test_a_click_in_the_empty_corner_of_the_box_misses():
    document, (left, _c, _m) = _texts()
    index = GeometryIndex(document)
    x0, y0, x1, y1 = GeometryIndex._text_extents(left)
    # the box's top-left corner is far from a text running at 45 degrees
    assert index.pick((x0 + 0.5, y1 - 0.5), 0.2) is None
    quad = GeometryIndex._text_quad(left)
    middle = quad.mean(axis=0)
    assert index.pick(tuple(middle), 0.2) == left.dxf.handle
    assert left.dxf.handle not in index.pick_all((x0 + 0.5, y1 - 0.5), 0.2)


def test_the_selection_is_outlined_by_the_turned_rectangle():
    document, (left, _c, _m) = _texts()
    index = GeometryIndex(document)
    segs, _circles, boxes = index.highlight_of([left.dxf.handle])
    assert len(boxes) == 0, "the axis box is still drawn"
    assert len(segs) == 4
    corners = {tuple(np.round(r[:2], 6)) for r in segs}
    expected = {tuple(np.round(c, 6)) for c in GeometryIndex._text_quad(left)}
    assert corners == expected


def test_a_moved_turned_text_is_picked_where_it_went():
    document, (left, _c, _m) = _texts()
    index = GeometryIndex(document)
    index.pick((0, 0), 0.1)                    # build
    middle = GeometryIndex._text_quad(left).mean(axis=0)
    left.translate(50, 50, 0)
    index.translate_handles([left.dxf.handle], 50, 50)
    assert index.pick(tuple(middle + 50), 0.2) == left.dxf.handle
