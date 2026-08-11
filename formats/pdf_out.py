# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Plot to PDF or a system printer, at a real scale (Phase 8).

The ezdxf drawing frontend replays the layout into a QGraphicsScene through
PyQtBackend (true vector graphics — lines stay lines in the PDF), and
QGraphicsScene.render maps a world-area rectangle onto the printable page at
the requested scale. 1:N metric scaling: one paper mm equals N drawing mm, so
a drawing in metres plots 1:100 with ``mm_per_unit = 1000 / 100``.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

# Paper sizes in mm (portrait), the ones a civil plan actually uses.
PAPER_SIZES_MM = {
    "A4": (210.0, 297.0),
    "A3": (297.0, 420.0),
    "A2": (420.0, 594.0),
    "A1": (594.0, 841.0),
    "A0": (841.0, 1189.0),
    "Letter": (215.9, 279.4),
}

# Common metric plot scales (denominators of 1:N).
COMMON_SCALES = (10, 20, 25, 50, 75, 100, 125, 200, 250, 500, 1000, 2000)


def build_graphics_scene(document, layout_name: str | None = None):
    """Replay a layout into a QGraphicsScene (vector items, world coords)."""
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.pyqt import PyQtBackend
    from PySide6.QtWidgets import QGraphicsScene

    from render.backend import pick_layout

    if layout_name and layout_name != "Model" \
            and layout_name in document.doc.layouts:
        layout = document.doc.layouts.get(layout_name)
    else:
        layout, _name = pick_layout(document)
    scene = QGraphicsScene()
    backend = PyQtBackend(scene)
    # export_mode: render as plotted — layers with Plot off are skipped
    # (they still display on screen, exactly AutoCAD's Plot column).
    context = RenderContext(document.doc, export_mode=True)
    Frontend(context, backend).draw_layout(layout, finalize=False)
    if getattr(layout, "is_any_paperspace", False):
        # Viewport frames plot only when the page setup asks for them
        # (plot_layout_flags bit 1, off by AutoCAD's own default — clean
        # sheets are what a signed plan wants).
        try:
            flags = int(layout.dxf.get_default("plot_layout_flags"))
        except Exception:
            flags = 0
        if flags & 1:
            from render.backend import _draw_viewport_borders

            _draw_viewport_borders(layout, context, backend)
    backend.finalize()
    return scene


def scene_extents(scene) -> QRectF:
    """World-coordinate bounding rect of everything in the graphics scene."""
    return scene.itemsBoundingRect()


_PT_TO_MM = 25.4 / 72.0
# Thinnest plotted stroke: AutoCAD's fine-pen practice (never a 0-width
# hairline that disappears on high-resolution devices).
_MIN_PLOT_MM = 0.1


def _use_physical_pens(scene) -> None:
    """Convert the backend's cosmetic pens (points, fixed device pixels —
    a screen convention) into physical widths in scene units.

    Only valid when the scene units are paper mm (a layout plot): the
    0.25 mm default lineweight arrives as a 0.708 pt cosmetic pen, which a
    1200 dpi printer would render as an invisible 0.015 mm hairline.
    """
    from PySide6.QtCore import Qt

    for item in scene.items():
        if not hasattr(item, "pen"):
            continue
        pen = item.pen()
        if pen.style() == Qt.NoPen:
            continue
        pen.setCosmetic(False)
        pen.setWidthF(max(pen.widthF() * _PT_TO_MM, _MIN_PLOT_MM))
        item.setPen(pen)


def plot(document, printer, layout_name: str | None = None,
         area: tuple[float, float, float, float] | None = None,
         mm_per_unit: float | None = None,
         physical_pens: bool = False) -> None:
    """Render onto ``printer`` (PDF file or a physical printer).

    ``area`` is the world rect (x0, y0, x1, y1) to plot; None plots the
    extents. ``mm_per_unit`` fixes the scale (paper mm per drawing unit);
    None fits the area to the page. The plot is centred on the page.
    """
    scene = build_graphics_scene(document, layout_name)
    if physical_pens:
        _use_physical_pens(scene)
    if area is None:
        r = scene_extents(scene)
        area = (r.left(), r.top(), r.right(), r.bottom())
    x0, y0, x1, y1 = area
    aw, ah = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)

    painter = QPainter(printer)
    try:
        page = printer.pageRect(printer.Unit.DevicePixel)
        px_per_mm = printer.resolution() / 25.4
        if mm_per_unit is None:
            px_per_unit = min(page.width() / aw, page.height() / ah)
        else:
            px_per_unit = mm_per_unit * px_per_mm
        tw, th = aw * px_per_unit, ah * px_per_unit
        tx = page.x() + (page.width() - tw) / 2.0
        ty = page.y() + (page.height() - th) / 2.0

        # DXF is y-up, the page is y-down: flip the painter and hand render()
        # a target rect expressed in the flipped coordinate system.
        painter.translate(0.0, page.y() * 2 + page.height())
        painter.scale(1.0, -1.0)
        target = QRectF(tx, page.y() * 2 + page.height() - (ty + th), tw, th)
        source = QRectF(x0, y0, aw, ah)
        scene.render(painter, target, source)
    finally:
        painter.end()


def layout_sheet(document, layout_name: str):
    """((width_mm, height_mm), sheet_rect) of a paperspace layout's paper."""
    from core.layouts import paper_frame

    layout = document.doc.layouts.get(layout_name)
    sheet = paper_frame(layout)["sheet"]
    x0, y0, x1, y1 = sheet
    return (x1 - x0, y1 - y0), sheet


def plot_layout(document, printer, layout_name: str) -> None:
    """Plot a paperspace layout at 1:1 — the sheet maps mm-to-mm onto the
    page, so every viewport prints at its exact scale (the AutoCAD
    contract: layouts plot at 1:1, the scale lives in the viewports)."""
    _size, sheet = layout_sheet(document, layout_name)
    printer.setFullPage(True)   # the sheet IS the page; margins are drawn
    plot(document, printer, layout_name, area=sheet, mm_per_unit=1.0,
         physical_pens=True)    # scene units are paper mm on a layout


def make_pdf_printer_mm(path: str, width_mm: float, height_mm: float):
    """A vector-PDF QPrinter with an exact page size in mm (layout plots)."""
    from PySide6.QtCore import QSizeF
    from PySide6.QtGui import QPageSize
    from PySide6.QtPrintSupport import QPrinter

    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(path)
    printer.setPageSize(QPageSize(QSizeF(width_mm, height_mm),
                                  QPageSize.Millimeter))
    printer.setFullPage(True)
    return printer


def make_pdf_printer(path: str, paper: str = "A4", landscape: bool = True):
    """A QPrinter configured for vector PDF output."""
    from PySide6.QtGui import QPageLayout, QPageSize
    from PySide6.QtPrintSupport import QPrinter

    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(path)
    size_id = getattr(QPageSize, paper, QPageSize.A4)
    printer.setPageSize(QPageSize(size_id))
    printer.setPageOrientation(
        QPageLayout.Landscape if landscape else QPageLayout.Portrait)
    return printer
