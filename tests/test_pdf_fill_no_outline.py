# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Filled areas plot at their true size, with no lineweight outline.

ezdxf outlines a filled path with the entity's pen: once plotting made the
pens physical, every TrueType letter and every solid hatch grew by its
layer's lineweight and small text came out as blots. AutoCAD plots
TrueType text and solid fills without lineweight.
"""
from __future__ import annotations

import pytest


def _ink_width_mm(document, px_per_mm: float = 20.0) -> float:
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QImage, QPainter

    from formats.pdf_out import (_use_physical_pens, build_graphics_scene,
                                 scene_extents)

    scene = build_graphics_scene(document)
    _use_physical_pens(scene)                   # 1 scene unit = 1 paper mm
    box = scene_extents(scene).adjusted(-2, -2, 2, 2)
    w, h = int(box.width() * px_per_mm), int(box.height() * px_per_mm)
    image = QImage(w, h, QImage.Format_ARGB32)
    image.fill(Qt.white)
    painter = QPainter(image)
    scene.render(painter, QRectF(0, 0, w, h), box)
    painter.end()
    row = h // 2
    inked = [x for x in range(w) if image.pixelColor(x, row).lightness() < 128]
    return (inked[-1] - inked[0] + 1) / px_per_mm


@pytest.mark.parametrize("fill", ["HATCH", "SOLID"])
def test_a_solid_fill_on_a_thick_layer_plots_its_true_width(qapp, fill):
    from core.templates import new_document

    document = new_document("mm")
    document.doc.layers.add("GRUESA", lineweight=50)        # 0.50 mm
    msp = document.doc.modelspace()
    square = [(0, 0), (10, 0), (10, 10), (0, 10)]
    if fill == "HATCH":
        hatch = msp.add_hatch(dxfattribs={"layer": "GRUESA"})
        hatch.paths.add_polyline_path(square)
        hatch.set_solid_fill()
    else:
        msp.add_solid([square[0], square[1], square[3], square[2]],
                      dxfattribs={"layer": "GRUESA"})
    assert _ink_width_mm(document) == pytest.approx(10.0, abs=0.1)


def test_truetype_letters_get_no_pen(qapp):
    from PySide6.QtCore import Qt

    from core.templates import new_document
    from formats.pdf_out import _use_physical_pens, build_graphics_scene

    document = new_document("mm")
    document.doc.layers.add("GRUESA", lineweight=50)
    document.doc.styles.add("TT", font="DejaVuSans.ttf")
    document.doc.modelspace().add_text(
        "Lote 12", height=2.5, dxfattribs={"layer": "GRUESA", "style": "TT"})
    scene = build_graphics_scene(document)
    _use_physical_pens(scene)
    filled = [i for i in scene.items()
              if hasattr(i, "brush") and i.brush().style() != Qt.NoBrush]
    assert filled
    assert all(i.pen().style() == Qt.NoPen for i in filled)
