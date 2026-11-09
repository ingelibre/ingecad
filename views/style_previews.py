# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Preview graphics for the Styles panel — BricsCAD-style thumbnails.

A text style is drawn as a sample string in its font, width factor and oblique
angle; a dimension style is drawn as a small dimension (extension lines, arrows
sized by DIMASZ, text sized by DIMTXT) so the settings read at a glance.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QTransform,
)

_BG = QColor(244, 244, 244)
_FG = QColor(25, 25, 25)
_SAMPLE = "AaBbCc 0123"

# Rough .shx -> family hints; TTF/OTF use the file's base name as the family.
_SHX_FAMILY = {
    "txt": "monospace", "monotxt": "monospace",
    "romans": "serif", "romant": "serif", "italic": "serif",
    "isocp": "sans-serif", "isocpeur": "sans-serif", "simplex": "sans-serif",
}


def font_family(font_name: str) -> str:
    name = (font_name or "txt").strip()
    low = name.lower()
    if low.endswith((".ttf", ".otf", ".ttc")):
        return name.rsplit(".", 1)[0]
    stem = low.rsplit(".", 1)[0]
    return _SHX_FAMILY.get(stem, "sans-serif")


def _tile(w: int, h: int) -> tuple[QPixmap, QPainter]:
    pm = QPixmap(w, h)
    pm.fill(_BG)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    return pm, p


def blank_pixmap(w: int, h: int) -> QPixmap:
    """An empty tile, shown while a thumbnail is still to be drawn."""
    pm, p = _tile(w, h)
    p.end()
    return pm


def text_style_pixmap(props: dict, w: int = 150, h: int = 34,
                      sample: str = _SAMPLE) -> QPixmap:
    pm, p = _tile(w, h)
    f = QFont(font_family(props.get("font", "txt")))
    f.setPixelSize(max(8, int(h * 0.5)))
    p.setFont(f)
    p.setPen(QPen(_FG))
    width = props.get("width", 1.0) or 1.0
    oblique = props.get("oblique", 0.0) or 0.0
    t = QTransform()
    t.translate(6, h * 0.72)
    t.scale(width, 1.0)
    if oblique:
        t.shear(-math.tan(math.radians(oblique)), 0.0)
    p.setTransform(t)
    p.drawText(QPointF(0, 0), sample)
    p.end()
    return pm


def _arrow(p: QPainter, tip: QPointF, direction: int, size: float) -> None:
    """Filled dimension arrowhead pointing outward from the dimension line."""
    dx = direction * size
    base_y = size * 0.35
    poly = QPolygonF([
        tip,
        QPointF(tip.x() + dx, tip.y() - base_y),
        QPointF(tip.x() + dx, tip.y() + base_y),
    ])
    p.setBrush(QBrush(_FG))
    p.setPen(Qt.NoPen)
    p.drawPolygon(poly)


def dim_style_pixmap(props: dict, w: int = 150, h: int = 60) -> QPixmap:
    pm, p = _tile(w, h)
    pen = QPen(_FG)
    pen.setWidthF(1.0)
    p.setPen(pen)

    txt = float(props.get("dimtxt", 2.5) or 2.5)
    asz = float(props.get("dimasz", 2.5) or 2.5)
    exe = float(props.get("dimexe", 1.25) or 1.25)
    exo = float(props.get("dimexo", 0.625) or 0.625)
    dec = int(props.get("dimdec", 2) or 0)

    # Map model units to pixels so DIMTXT/DIMASZ differences show. The measured
    # span is a fixed 25 units drawn across most of the tile width.
    span = 25.0
    left, right = 16.0, w - 16.0
    scale = (right - left) / span
    dim_y = h * 0.62
    top = h * 0.16

    # extension lines (offset from the "geometry", overshoot past the dim line)
    for x in (left, right):
        p.drawLine(QPointF(x, top + exo * scale),
                   QPointF(x, dim_y + exe * scale))
    # dimension line
    p.drawLine(QPointF(left, dim_y), QPointF(right, dim_y))
    # arrowheads
    a = max(3.0, asz * scale)
    _arrow(p, QPointF(left, dim_y), +1, a)
    _arrow(p, QPointF(right, dim_y), -1, a)
    # measurement text, centered above the dimension line
    f = QFont(font_family(props.get("dimtxsty", "Standard")))
    f.setPixelSize(max(7, int(txt * scale)))
    p.setFont(f)
    p.setPen(QPen(_FG))
    label = f"{span:.{dec}f}"
    fm = p.fontMetrics()
    tx = (left + right) / 2 - fm.horizontalAdvance(label) / 2
    p.drawText(QPointF(tx, dim_y - a - 2), label)
    p.end()
    return pm


#: Entities read for one block thumbnail: a title block of a real plan has
#: thousands, and the tile is 60 pixels tall.
_BLOCK_ENTITY_LIMIT = 3000


def block_pixmap(doc, name: str, w: int = 150, h: int = 60) -> QPixmap:
    """A block definition drawn to fit the tile, nested references and all.

    Outlines only (a text is its box, a hatch its boundary): enough to tell
    one block from another in a list, and cheap enough to draw while the
    list is on screen."""
    from itertools import islice

    from ezdxf import disassemble

    pm, p = _tile(w, h)
    lines: list = []
    points: list = []
    try:
        block = doc.blocks.get(name)
        entities = islice(disassemble.recursive_decompose(block),
                          _BLOCK_ENTITY_LIMIT) if block is not None else ()
        for primitive in disassemble.to_primitives(entities):
            try:
                path = primitive.path
                if path is not None and len(path):
                    lines.append(path)
                else:
                    pts = [(v.x, v.y) for v in
                           islice(primitive.vertices(), 2000)]
                    if len(pts) == 1:
                        points.append(pts[0])
                    elif pts:
                        lines.append(pts)
            except Exception:             # noqa: BLE001 - one odd entity
                continue
    except Exception:                     # noqa: BLE001 - a broken block
        lines, points = [], []

    xs: list = []
    ys: list = []
    for item in lines:
        if isinstance(item, list):
            pts = item
        else:
            pts = [(v.x, v.y) for v in item.control_vertices()]
        xs.extend(x for x, _ in pts)
        ys.extend(y for _, y in pts)
    xs.extend(x for x, _ in points)
    ys.extend(y for _, y in points)
    finite = [v for v in xs + ys if math.isfinite(v)]
    if not xs or len(finite) != len(xs) + len(ys):
        p.end()
        return pm
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    span = max(x1 - x0, y1 - y0)
    margin = 5.0
    if span <= 0:
        scale = 1.0
    else:
        scale = min((w - 2 * margin) / max(x1 - x0, span * 1e-9),
                    (h - 2 * margin) / max(y1 - y0, span * 1e-9))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

    def to_tile(x: float, y: float) -> QPointF:
        return QPointF(w / 2 + (x - cx) * scale, h / 2 - (y - cy) * scale)

    pen = QPen(_FG)
    pen.setWidthF(1.0)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    distance = (span / 200.0) if span > 0 else 0.01
    for item in lines:
        if isinstance(item, list):
            pts = item
        else:
            pts = [(v.x, v.y) for v in item.flattening(distance)]
        if len(pts) >= 2:
            p.drawPolyline(QPolygonF([to_tile(x, y) for x, y in pts]))
    p.setBrush(QBrush(_FG))
    for x, y in points:
        p.drawEllipse(to_tile(x, y), 1.2, 1.2)
    p.end()
    return pm
