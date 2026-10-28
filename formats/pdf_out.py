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


class _PlotRenderContext:
    """Built by :func:`_plot_context`: ezdxf's RenderContext with a .ctb's
    pens applied to every colour -- explicit colour, grayscale, screening --
    including true-colour entities (by their nearest ACI, as AutoCAD plots
    them). Lineweights come through ezdxf itself (``plot_styles``)."""


def _plot_context(doc, table):
    from ezdxf import colors as _colors
    from ezdxf.addons.drawing import RenderContext

    if table is None or table.named:
        return RenderContext(doc, export_mode=True)

    class PlotRenderContext(RenderContext):
        def _true_entity_color(self, true_color, aci):
            if true_color is not None:
                rgb = tuple(true_color)
                aci = _nearest_aci(rgb)
            elif 0 < aci < 256:
                rgb = _colors.int2rgb(_colors.DXF_DEFAULT_COLORS[aci])
                if aci == 7:
                    rgb = _hex_to_rgb(self.current_layout_properties.default_color)
            else:
                return self.current_layout_properties.default_color
            return "#%02x%02x%02x" % tuple(table.pen_color(aci, rgb))

    return PlotRenderContext(doc, ctb=table.table, export_mode=True)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _nearest_aci(rgb) -> int:
    from ezdxf import colors as _colors

    best, best_d = 7, None
    for aci in range(1, 256):
        r, g, b = _colors.int2rgb(_colors.DXF_DEFAULT_COLORS[aci])
        d = (r - rgb[0]) ** 2 + (g - rgb[1]) ** 2 + (b - rgb[2]) ** 2
        if best_d is None or d < best_d:
            best, best_d = aci, d
    return best


def plot_style_for(document, layout_name: str | None, ctb: str | None):
    """The table to plot with: the caller's choice, else the layout's own
    ``current_style_sheet`` (Page Setup), else none; an empty name means none."""
    from core import plotstyles

    if ctb is None:
        layout = None
        if layout_name and layout_name in document.doc.layouts:
            layout = document.doc.layouts.get(layout_name)
        elif not layout_name or layout_name == "Model":
            layout = document.doc.modelspace()
        try:
            ctb = str(layout.dxf_layout.dxf.get("current_style_sheet", "") or "")
        except Exception:                 # noqa: BLE001 - no layout, no table
            ctb = ""
    return plotstyles.load(ctb) if ctb else None


def build_graphics_scene(document, layout_name: str | None = None,
                         ctb: str | None = None):
    """Replay a layout into a QGraphicsScene (vector items, world coords).

    ``ctb`` names the plot style table (see core.plotstyles); None takes the
    layout's own, "" plots with none.
    """
    from PySide6.QtWidgets import QGraphicsScene

    from render.backend import TolerantFrontend, pick_layout

    if layout_name and layout_name != "Model" \
            and layout_name in document.doc.layouts:
        layout = document.doc.layouts.get(layout_name)
    else:
        layout, _name = pick_layout(document)
    scene = QGraphicsScene()
    backend = _plot_backend_class()(scene)
    # export_mode: render as plotted — layers with Plot off are skipped
    # (they still display on screen, exactly AutoCAD's Plot column).
    context = _plot_context(document.doc,
                            plot_style_for(document, layout_name, ctb))
    # The canvas's frontend, so the plot obeys the same rules the screen
    # does: a dimension's block drawn in the dimension's colour (ISO-25 is
    # ByBlock), MULTILEADER content instead of its baked proxy picture, a
    # malformed entity skipped instead of blanking the page.
    # Paper is white: AutoCAD plots model space on white too, never on the
    # screen's dark background, and ACI 7 follows the background to black
    # (#62: a model-space PDF came out dark blue with white lines).
    from ezdxf.addons.drawing.properties import LayoutProperties

    sheet = LayoutProperties.from_layout(layout)
    sheet.set_colors("#ffffff")
    # POINT symbols at the size the canvas shows them ($PDSIZE <= 0 is
    # relative to the view, which ezdxf alone draws 1 unit wide)
    from ezdxf.addons.drawing.config import Configuration

    from render.backend import _flatten_distance, min_dash_length, point_size

    size = point_size(document)
    # the paper shows what the screen cannot: a tenth of its tolerance
    from render.backend import construction_length

    config = Configuration(min_dash_length=min_dash_length(
        _flatten_distance(layout) * 0.1, document),
        infinite_line_length=construction_length(_flatten_distance(layout)))
    if size is not None:
        config = config.with_changes(pdsize=size)
    TolerantFrontend(context, backend, config).draw_layout(
        layout, finalize=False, layout_properties=sheet)
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


_PLOT_BACKEND = None


def _plot_backend_class():
    """ezdxf's PyQtBackend, plotting a linetype's dot as a dot (#87).

    The dot of DASHDOT, CENTER or PHANTOM arrives as a zero-length line
    (core.ezdxf_patches), which ezdxf turns into a "point" one DEVICE pixel
    wide: a 0.02 mm speck at 1200 dpi, gone on paper. AutoCAD plots it as
    round as the pen is wide, and so does :class:`_PenDot`.
    """
    global _PLOT_BACKEND
    if _PLOT_BACKEND is not None:
        return _PLOT_BACKEND
    from ezdxf.addons.drawing.pyqt import PyQtBackend
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QBrush
    from PySide6.QtWidgets import QAbstractGraphicsShapeItem

    class _PenDot(QAbstractGraphicsShapeItem):
        """A filled circle as wide as its pen: in device pixels while the
        pen is cosmetic, in scene units once it is physical."""

        def __init__(self, x: float, y: float, pen) -> None:
            super().__init__()
            self.location = QPointF(x, y)
            self.setPen(pen)

        def _radius(self, view_scale: float = 1.0) -> float:
            pen = self.pen()
            if pen.isCosmetic():
                return max(pen.widthF(), 1.0) / 2.0 / view_scale
            return pen.widthF() / 2.0

        def boundingRect(self) -> QRectF:
            r = 0.5 if self.pen().isCosmetic() else self._radius()
            return QRectF(self.location.x() - r, self.location.y() - r,
                          2 * r, 2 * r)

        def paint(self, painter, option, widget=None) -> None:
            from ezdxf.addons.drawing.pyqt import _get_x_scale
            from PySide6.QtCore import Qt

            r = self._radius(_get_x_scale(painter.transform()) or 1.0)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(self.pen().color()))
            painter.drawEllipse(self.location, r, r)

    class _PlotBackend(PyQtBackend):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            #: entity types being drawn, innermost last
            self._entering: list = []

        def enter_entity(self, entity, properties) -> None:
            super().enter_entity(entity, properties)
            self._entering.append(entity.dxftype())

        def exit_entity(self, entity) -> None:
            super().exit_entity(entity)
            if self._entering:
                self._entering.pop()

        def _add_item(self, item, entity_handle) -> None:
            super()._add_item(item, entity_handle)
            if self._entering and self._entering[-1] in ("XLINE", "RAY"):
                # far past the drawing (render.backend.construction_length):
                # not part of what "Extents" plots
                item.setData(_CONSTRUCTION_ROLE, True)
                self._scene._ingecad_construction = True

        def draw_line(self, start, end, properties) -> None:
            if start.x == end.x and start.y == end.y:
                self._dot(start, properties)
            else:
                super().draw_line(start, end, properties)

        def draw_solid_lines(self, lines, properties) -> None:
            rest = []
            for s, e in lines:
                if s.x == e.x and s.y == e.y:
                    self._dot(s, properties)
                else:
                    rest.append((s, e))
            if rest:
                super().draw_solid_lines(rest, properties)

        def draw_filled_paths(self, paths, properties) -> None:
            # ezdxf outlines a filled path with the entity's pen: on paper
            # every TrueType letter and solid hatch grew by its layer's
            # lineweight and small text plotted as blots. AutoCAD gives
            # TrueType text and solid fills no lineweight, like ezdxf's
            # own filled polygons (a SOLID).
            from ezdxf.addons.drawing.pyqt import _CosmeticPath
            from ezdxf.npshapes import to_qpainter_path

            paths = list(paths)
            if not paths:
                return
            item = _CosmeticPath(to_qpainter_path(paths))
            item.setPen(self._no_line)
            item.setBrush(self._get_fill_brush(properties.color))
            self._add_item(item, properties.handle)

        def _dot(self, at, properties) -> None:
            item = _PenDot(at.x, at.y, self._get_pen(properties))
            self._add_item(item, properties.handle)

    _PLOT_BACKEND = _PlotBackend
    return _PLOT_BACKEND


#: QGraphicsItem data role marking an XLINE's or a RAY's strokes
_CONSTRUCTION_ROLE = 0x0100 + 7


def scene_extents(scene) -> QRectF:
    """World-coordinate bounding rect of everything in the graphics scene
    but construction lines, which reach far past the drawing and which
    AutoCAD's Extents leaves out too (#98)."""
    if not getattr(scene, "_ingecad_construction", False):
        return scene.itemsBoundingRect()
    rect = QRectF()
    for item in scene.items():
        if not item.data(_CONSTRUCTION_ROLE):
            rect = rect.united(item.sceneBoundingRect())
    return rect if not rect.isNull() else scene.itemsBoundingRect()


_PT_TO_MM = 25.4 / 72.0
# Thinnest plotted stroke: AutoCAD's fine-pen practice (never a 0-width
# hairline that disappears on high-resolution devices).
_MIN_PLOT_MM = 0.1


def _use_physical_pens(scene, mm_per_unit: float = 1.0,
                       lineweights: bool = True) -> None:
    """Convert the backend's cosmetic pens (points, fixed device pixels —
    a screen convention) into physical widths in scene units.

    ``mm_per_unit`` is how many paper mm one scene unit becomes: 1 on a
    layout, the plot scale in model space -- where the pens were left
    cosmetic, so a plan plotted from the Model tab came out all in 1 px
    hairlines whatever its layers' lineweights (a YouTuber's staircase at
    1:25). The 0.25 mm default lineweight arrives as a 0.708 pt cosmetic
    pen, which a 1200 dpi printer would render as an invisible 0.015 mm
    hairline. ``lineweights`` off is AutoCAD's "Plot object lineweights"
    cleared: every line at the thinnest pen.
    """
    from PySide6.QtCore import Qt

    for item in scene.items():
        if not hasattr(item, "pen"):
            continue
        pen = item.pen()
        if pen.style() == Qt.NoPen:
            continue
        pen.setCosmetic(False)
        width_mm = max(pen.widthF() * _PT_TO_MM, _MIN_PLOT_MM) \
            if lineweights else _MIN_PLOT_MM
        pen.setWidthF(width_mm / mm_per_unit)
        # butt ends, AutoCAD's plot default: Qt's square cap stretched every
        # dash by half a pen each way, closing the gaps of a fine HIDDEN
        pen.setCapStyle(Qt.FlatCap)
        item.setPen(pen)


def plot(document, printer, layout_name: str | None = None,
         area: tuple[float, float, float, float] | None = None,
         mm_per_unit: float | None = None,
         physical_pens: bool = True, ctb: str | None = None,
         painter: QPainter | None = None, lineweights: bool = True) -> None:
    """Render onto ``printer`` (PDF file or a physical printer).

    ``area`` is the world rect (x0, y0, x1, y1) to plot; None plots the
    extents. ``mm_per_unit`` fixes the scale (paper mm per drawing unit);
    None fits the area to the page. The plot is centred on the page.
    ``ctb`` is the plot style table (None: the layout's own). ``painter``
    lets PUBLISH draw several pages with one painter; None opens and closes
    its own.
    """
    scene = build_graphics_scene(document, layout_name, ctb)
    if area is None:
        r = scene_extents(scene)
        area = (r.left(), r.top(), r.right(), r.bottom())
    x0, y0, x1, y1 = area
    aw, ah = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)

    own_painter = painter is None
    if own_painter:
        painter = QPainter(printer)
    painter.save()
    try:
        page = printer.pageRect(printer.Unit.DevicePixel)
        px_per_mm = printer.resolution() / 25.4
        if mm_per_unit is None:
            px_per_unit = min(page.width() / aw, page.height() / ah)
        else:
            px_per_unit = mm_per_unit * px_per_mm
        if physical_pens:
            # pens in paper mm, at the scale this plot has
            _use_physical_pens(scene, px_per_unit / px_per_mm, lineweights)
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
        painter.restore()
        if own_painter:
            painter.end()


def layout_sheet(document, layout_name: str):
    """((width_mm, height_mm), sheet_rect) of a paperspace layout's paper."""
    from core.layouts import paper_frame

    layout = document.doc.layouts.get(layout_name)
    sheet = paper_frame(layout)["sheet"]
    x0, y0, x1, y1 = sheet
    return (x1 - x0, y1 - y0), sheet


def plot_layout(document, printer, layout_name: str,
                ctb: str | None = None, painter: QPainter | None = None) -> None:
    """Plot a paperspace layout at 1:1 — the sheet maps mm-to-mm onto the
    page, so every viewport prints at its exact scale (the AutoCAD
    contract: layouts plot at 1:1, the scale lives in the viewports)."""
    _size, sheet = layout_sheet(document, layout_name)
    printer.setFullPage(True)   # the sheet IS the page; margins are drawn
    plot(document, printer, layout_name, area=sheet, mm_per_unit=1.0,
         physical_pens=True, ctb=ctb, painter=painter)   # paper mm on a layout


def publish(document, layout_names, path: str, ctb: str | None = None) -> int:
    """PUBLISH: several layouts into ONE multi-page PDF, each page the
    size of its sheet, each layout at 1:1. Returns the number of pages."""
    from PySide6.QtCore import QSizeF
    from PySide6.QtGui import QPageSize

    names = [n for n in layout_names if n in document.doc.layouts and n != "Model"]
    if not names:
        return 0
    (width, height), _sheet = layout_sheet(document, names[0])
    printer = make_pdf_printer_mm(path, width, height)
    painter = QPainter(printer)
    try:
        for index, name in enumerate(names):
            if index:
                (width, height), _sheet = layout_sheet(document, name)
                printer.setPageSize(QPageSize(QSizeF(width, height),
                                              QPageSize.Millimeter))
                printer.newPage()
            plot_layout(document, printer, name, ctb=ctb, painter=painter)
    finally:
        painter.end()
    return len(names)


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
