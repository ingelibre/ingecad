# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Phase 8 plot: vector PDF output at scale, y-flip correctness, layouts."""
from __future__ import annotations

import os
import sys

import pytest

from core.document import Document
from formats import pdf_out


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def _doc_with_marker():
    """A line along the bottom and a small circle at the TOP-left."""
    doc = Document.new()
    msp = doc.modelspace()
    msp.add_line((0, 0), (100, 0))          # bottom edge
    msp.add_circle((10, 90), 5)             # near the top
    return doc


def test_graphics_scene_builds(app):
    doc = _doc_with_marker()
    scene = pdf_out.build_graphics_scene(doc)
    r = pdf_out.scene_extents(scene)
    assert r.width() > 90
    assert r.height() > 80


def test_pdf_plot_writes_vector_file(app, tmp_path):
    doc = _doc_with_marker()
    path = str(tmp_path / "plan.pdf")
    printer = pdf_out.make_pdf_printer(path, "A4", landscape=True)
    pdf_out.plot(doc, printer)              # fit extents
    assert os.path.exists(path)
    assert os.path.getsize(path) > 1000     # real content, not an empty page


def test_pdf_plot_at_scale(app, tmp_path):
    # 1:100 with metres: 100 m wide area -> 1000 mm on paper (clipped by A4,
    # but the transform must not fit-shrink it). Just verify it renders.
    doc = _doc_with_marker()
    path = str(tmp_path / "scaled.pdf")
    printer = pdf_out.make_pdf_printer(path, "A4", landscape=True)
    pdf_out.plot(doc, printer, area=(0, 0, 20, 10), mm_per_unit=10.0)
    assert os.path.getsize(path) > 500


def test_y_flip_top_stays_top(app):
    """Render with the same flip math into an image: the circle drawn at
    world TOP must land in the TOP half of the page, not mirrored."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    doc = _doc_with_marker()
    scene = pdf_out.build_graphics_scene(doc)
    w, h = 200, 200
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(0xFFFFFFFF)
    painter = QPainter(img)
    # same transform pdf_out.plot applies (page.y() = 0 here)
    painter.translate(0.0, h)
    painter.scale(1.0, -1.0)
    target = QRectF(0, 0, w, h)
    # a margin round the 0..100 square: the base line sits ON y=0, and
    # this test only passed while the plot's dark background made every
    # pixel "dark" (#62)
    source = QRectF(-5, -5, 110, 110)
    scene.render(painter, target, source)
    painter.end()

    def dark_pixels(y0, y1):
        n = 0
        for y in range(y0, y1):
            for x in range(0, w, 2):
                if QImage.pixel(img, x, y) & 0xFF < 100:
                    n += 1
        return n

    top = dark_pixels(0, h // 3)            # circle territory
    bottom = dark_pixels(2 * h // 3, h)     # bottom line territory
    assert top > 0                          # circle visible near the top
    assert bottom > 0                       # base line near the bottom


def test_build_scene_layout_by_name():
    import ezdxf
    from render.backend import build_scene

    doc = Document.new()
    doc.modelspace().add_line((0, 0), (5, 5))
    layout = doc.doc.layouts.new("Plancha1")
    layout.add_line((0, 0), (100, 0))
    model_scene = build_scene(doc, "Model")
    sheet_scene = build_scene(doc, "Plancha1")
    assert model_scene.lines.vertex_count > 0
    assert sheet_scene.lines.vertex_count > 0
    assert sheet_scene.background is not None   # paper-white layout


def test_plot_draws_a_dimension_in_the_dimensions_colour(qapp) -> None:
    """The plot replays the drawing through the canvas's frontend, so a
    dimension's block -- ByBlock in ISO-25 -- is drawn in the dimension's
    colour on paper as on screen. Through ezdxf's stock Frontend the same
    scene came out entirely in the page's default colour."""
    from core import actions
    from core.commands import History
    from core.document import Document
    from formats.pdf_out import build_graphics_scene

    document = Document.new()
    document.doc.layers.add("cotas", color=1)
    document.doc.header["$CLAYER"] = "cotas"
    History(document).execute(actions.dim_linear((0, 0), (50, 0), (25, 10)))
    scene = build_graphics_scene(document, "Model")
    from PySide6.QtCore import Qt

    colours = set()
    for item in scene.items():
        pen = getattr(item, "pen", None)
        if pen is not None and pen().style() != Qt.PenStyle.NoPen:
            colours.add(pen().color().name())
        brush = getattr(item, "brush", None)
        if brush is not None and brush().style() != Qt.BrushStyle.NoBrush:
            colours.add(brush().color().name())
    assert colours == {"#ff0000"}


def test_a_model_space_pdf_plots_on_white_with_dark_lines(app, tmp_path):
    # #62: the plot kept the screen's dark model background, with ACI 7
    # lines in white -- a plotter would have spent its ink on the page.
    from PySide6.QtCore import QSize
    from PySide6.QtPdf import QPdfDocument

    doc = _doc_with_marker()
    path = str(tmp_path / "model.pdf")
    printer = pdf_out.make_pdf_printer(path, "A4", landscape=True)
    pdf_out.plot(doc, printer, layout_name="Model")
    pdf = QPdfDocument()
    pdf.load(path)
    from PySide6.QtGui import QImage, QPainter

    page = pdf.render(0, QSize(600, 424))
    img = QImage(page.size(), QImage.Format_RGB32)
    img.fill(0xFFFFFFFF)                    # what QtPdf leaves unpainted
    painter = QPainter(img)
    painter.drawImage(0, 0, page)
    painter.end()
    pixels = [img.pixelColor(x, y).lightness()
              for y in range(0, img.height(), 3) for x in range(0, img.width(), 3)]
    assert sum(p > 240 for p in pixels) > 0.9 * len(pixels)    # white paper
    assert sum(p < 80 for p in pixels) > 0                     # dark lines on it


def _window_with(insunits, length):
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document("mm")
    win.document.doc.header["$INSUNITS"] = insunits
    msp = win.document.modelspace()
    msp.add_line((0, 0), (length, 0))
    msp.add_line((0, 0), (0, length / 10))       # so the extents have height
    return win


def test_the_plot_scales_include_full_size_and_enlargements(app):
    # #68 (Rafael): Fit, then 1:10 ... 1:2000 -- no 1:1, 1:2, 1:5, 2:1, 5:1.
    from views.print_dialog import PrintDialog

    win = _window_with(4, 100.0)
    try:
        dialog = PrintDialog(win)
        offered = {dialog.scale.itemText(i) for i in range(dialog.scale.count())}
        assert {"1:1", "1:2", "1:5", "1:100", "1:1000", "2:1", "5:1"} <= offered
    finally:
        win.close()


@pytest.mark.parametrize("insunits, expected", [(4, "Millimeters"), (5, "Centimeters"),
                                                (6, "Meters"), (0, "Meters")])
def test_the_drawing_unit_starts_on_the_drawings_own(app, insunits, expected):
    # #68: a millimetre plan opened on Meters, and 1:100 came out tiny
    from core.i18n import tr
    from views.print_dialog import PrintDialog

    win = _window_with(insunits, 100.0)
    try:
        dialog = PrintDialog(win)
        assert dialog.units.currentText() == tr(expected)
    finally:
        win.close()


def test_one_to_one_on_a_millimetre_plan_prints_true_size(app, tmp_path):
    # the line is 100 drawing units = 100 mm; at 1:1 it must measure 100 mm
    # on the PDF page, and the dialog must say so in AutoCAD's words
    from PySide6.QtCore import QSize
    from PySide6.QtPdf import QPdfDocument

    from views.print_dialog import PrintDialog

    win = _window_with(4, 100.0)
    try:
        dialog = PrintDialog(win)
        dialog.scale.setCurrentIndex(dialog.scale.findText("1:1"))
        assert dialog._mm_per_unit() == pytest.approx(1.0)
        assert dialog.meaning.text().startswith("1 mm on paper = 1 ")
        path = str(tmp_path / "full.pdf")
        dialog._plot_on(pdf_out.make_pdf_printer(path, "A4", landscape=True))
    finally:
        win.close()
    pdf = QPdfDocument()
    pdf.load(path)
    px_per_mm = 4
    img = pdf.render(0, QSize(297 * px_per_mm, 210 * px_per_mm))
    row_dark = {}
    for y in range(img.height()):
        xs = [x for x in range(img.width())
              if img.pixelColor(x, y).alpha() > 0 and img.pixelColor(x, y).lightness() < 128]
        if len(xs) > len(row_dark.get("xs", [])):
            row_dark = {"y": y, "xs": xs}
    width_mm = (max(row_dark["xs"]) - min(row_dark["xs"])) / px_per_mm
    assert width_mm == pytest.approx(100.0, abs=1.0)


def test_plot_in_a_layout_starts_from_that_layouts_page_setup(app):
    # PLOT in a layout opened on A4 landscape whatever the sheet, and the
    # drawing unit was the model's: Extents at 1:1 on a metre plan plotted
    # the sheet a thousand times too big.
    from core import layouts as layout_ops
    from core.i18n import tr
    from views.print_dialog import PrintDialog

    win = _window_with(6, 100.0)                    # a plan in metres
    try:
        name = win.document.doc.layouts.names_in_taborder()[1]
        sheet = win.document.doc.layouts.get(name)
        layout_ops.page_setup_command(
            sheet, 297.0, 420.0, (5, 5, 5, 5), "ISO A3",
            plot_type=layout_ops.PLOT_TYPE_EXTENTS).do(win.document)
        win.switch_layout(name)
        dialog = PrintDialog(win)
        assert dialog.paper.currentText() == "A3"
        assert dialog.orientation.currentData() is False       # portrait
        assert dialog.area.currentData() == "extents"
        assert dialog.units.currentText() == tr("Millimeters")
        dialog.scale.setCurrentIndex(dialog.scale.findText("1:1"))
        assert dialog._mm_per_unit() == 1.0
    finally:
        win.document.dirty = False
        win.close()


def test_plot_opens_in_a_layout_whose_scale_is_not_in_the_list(app):
    # A page setup at a scale outside the list (1:37 here, a custom one
    # from another program in the field) raised on the "Custom" entry while
    # the dialog was built, and PLOT in that layout opened nothing.
    from core import layouts as layout_ops
    from views.print_dialog import PrintDialog

    win = _window_with(4, 1000.0)                   # a plan in millimetres
    try:
        name = win.document.doc.layouts.names_in_taborder()[1]
        sheet = win.document.doc.layouts.get(name)
        layout_ops.page_setup_command(
            sheet, 297.0, 420.0, (5, 5, 5, 5), "ISO A3",
            plot_type=layout_ops.PLOT_TYPE_EXTENTS,
            fit_to_paper=False, scale=(1.0, 37.0)).do(win.document)
        win.switch_layout(name)
        dialog = PrintDialog(win)
        assert dialog.scale.currentData() == "custom"
        assert dialog._mm_per_unit() == pytest.approx(1.0 / 37.0)
    finally:
        win.document.dirty = False
        win.close()
