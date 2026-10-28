# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A plot from the Model tab carries the layers' lineweights, at its scale.

Its pens were left cosmetic (screen pixels), so every line of a staircase
plan plotted at 1:25 came out a 1 px hairline whatever its layer said; and
the Plot dialog had no custom "1000 mm = 25 units" scale nor a lineweight
switch. Found reproducing a YouTuber's drawing session.
"""
from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter

from core.document import Document
from formats import pdf_out

DPI = 600


class _Page:
    """What plot() asks of a printer: the page and its resolution."""

    class Unit:
        DevicePixel = 0

    def __init__(self, width_px, height_px):
        self._rect = QRect(0, 0, width_px, height_px)

    def pageRect(self, _unit):
        return self._rect

    def resolution(self):
        return DPI


def _thickness_px(lineweight: int, lineweights: bool = True) -> int:
    document = Document.new()
    doc = document.doc
    doc.layers.add("GRUESA", lineweight=lineweight)
    msp = document.modelspace()
    msp.add_line((0, 0.5), (1, 0.5), dxfattribs={"layer": "GRUESA"})
    image = QImage(1000, 1000, QImage.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    # 1:25 in metres: 40 paper mm per unit -- a 1 m square is 40 mm, 945 px
    pdf_out.plot(document, _Page(1000, 1000), area=(0, 0, 1, 1),
                 mm_per_unit=40.0, painter=painter, lineweights=lineweights)
    painter.end()
    column = [image.pixelColor(500, y).lightness() < 128 for y in range(1000)]
    return sum(column)


def test_layer_lineweights_plot_in_paper_millimetres(qapp):
    # 0.60 mm at 600 dpi is 14 px; a 1 px hairline was all that came out
    assert 12 <= _thickness_px(60) <= 16
    assert _thickness_px(60, lineweights=False) <= 3


def test_the_custom_scale_reads_mm_per_unit(qapp):
    from views.main_window import MainWindow
    from views.print_dialog import PrintDialog

    win = MainWindow()
    win.new_document()
    dialog = PrintDialog(win)
    dialog.scale.setCurrentIndex(dialog.scale.findData("custom"))
    dialog.custom_mm.setValue(1000)
    dialog.custom_units.setValue(25)
    assert dialog._mm_per_unit() == 40.0
    assert dialog.lineweights.isChecked()
    dialog.reject()
    win.document.dirty = False
    win.close()


def test_plotted_pens_have_butt_ends(qapp):
    """Qt's square cap stretched every dash by half a pen each way and
    closed the gaps of a fine HIDDEN line on paper; AutoCAD plots butt."""
    from PySide6.QtCore import Qt

    document = Document.new()
    document.modelspace().add_line((0, 0), (1, 0))
    scene = pdf_out.build_graphics_scene(document)
    pdf_out._use_physical_pens(scene, 40.0)
    caps = {item.pen().capStyle() for item in scene.items()
            if hasattr(item, "pen")}
    assert caps == {Qt.FlatCap}
