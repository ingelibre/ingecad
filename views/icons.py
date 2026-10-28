# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Painted line-art icons for the Draw and Modify toolbars.

Self-contained: each icon is drawn with QPainter into a pixmap, no image
files. Monochrome light strokes on transparent, sized for a 24 px toolbar.
Style echoes the classic AutoCAD toolbar glyphs (thin geometric line art).
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QIcon, QPainter, QPainterPath, QPen,
                           QPixmap, QPolygonF, QTransform)

# Sampled from AutoCAD's own dark-theme ribbon (2026-08-11 screenshot):
# the primary geometry is near-white and the SECOND object — the copies, the
# mirrored twin, the smaller scale, the array — is a light steel blue.
# There is no red anywhere in the modify glyphs; the only warm colour in the
# whole panel is the eraser's rubber.
_STROKE = QColor(0xF0, 0xF4, 0xF6)
_ACCENT = QColor(0x8F, 0xB8, 0xD8)
_ACTION = _ACCENT          # kept for the icons that used it; no red
_RUBBER = QColor(0xE3, 0xC2, 0x6E)
_RUBBER_TIP = QColor(0xD8, 0x6B, 0x62)
SIZE = 24


def _pen(p: QPainter, color: QColor, width: float = 1.4,
         style=Qt.SolidLine) -> None:
    pen = QPen(color, width, style)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)


def _tip(p: QPainter, x: float, y: float, ang: float, size: float = 4.5,
         color: QColor | None = None) -> None:
    """A solid arrowhead pointing along ``ang`` (degrees)."""
    a = math.radians(ang)
    back = math.radians(ang + 180)
    left = math.radians(ang + 150)
    right = math.radians(ang - 150)
    poly = QPolygonF([
        QPointF(x, y),
        QPointF(x + size * math.cos(left), y + size * math.sin(left)),
        QPointF(x + size * math.cos(right), y + size * math.sin(right)),
    ])
    p.save()
    colour = color or _ACTION
    p.setPen(QPen(colour, 1.0))
    p.setBrush(QBrush(colour))
    p.drawPolygon(poly)
    p.restore()


def _shaft(p: QPainter, x0: float, y0: float, x1: float, y1: float,
           color: QColor | None = None) -> None:
    """An arrow from (x0,y0) to (x1,y1), head at the far end."""
    colour = color or _ACTION
    p.save()
    _pen(p, colour, 1.3)
    p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
    p.restore()
    _tip(p, x1, y1, math.degrees(math.atan2(y1 - y0, x1 - x0)), color=colour)


def _canvas() -> tuple[QPixmap, QPainter]:
    pm = QPixmap(SIZE, SIZE)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(_STROKE, 1.4)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    return pm, p


def _node(p: QPainter, x: float, y: float) -> None:
    p.save()
    p.setPen(QPen(_ACCENT, 1.0))
    p.setBrush(QBrush(_ACCENT))
    p.drawRect(QRectF(x - 1.4, y - 1.4, 2.8, 2.8))
    p.restore()


# -- draw icons ----------------------------------------------------------------

def _line():
    pm, p = _canvas()
    p.drawLine(4, 19, 20, 5)
    _node(p, 4, 19)
    _node(p, 20, 5)
    p.end()
    return pm


def _circle():
    pm, p = _canvas()
    p.drawEllipse(QPointF(12, 12), 8, 8)
    _node(p, 12, 12)
    p.end()
    return pm


def _arc():
    pm, p = _canvas()
    path = QRectF(3, 6, 18, 18)
    p.drawArc(path, 20 * 16, 140 * 16)
    p.end()
    return pm


def _pline():
    pm, p = _canvas()
    poly = QPolygonF([QPointF(3, 18), QPointF(9, 8), QPointF(14, 15),
                      QPointF(21, 6)])
    p.drawPolyline(poly)
    for pt in poly:
        _node(p, pt.x(), pt.y())
    p.end()
    return pm


def _rectang():
    pm, p = _canvas()
    p.drawRect(QRectF(4, 6, 16, 12))
    p.end()
    return pm


def _polygon():
    pm, p = _canvas()
    pts = [QPointF(12 + 8 * math.cos(math.radians(90 + i * 72)),
                   12 + 8 * math.sin(math.radians(90 + i * 72)))
           for i in range(5)]
    p.drawPolygon(QPolygonF(pts))
    p.end()
    return pm


def _ellipse():
    pm, p = _canvas()
    p.drawEllipse(QRectF(3, 7, 18, 10))
    p.end()
    return pm


def _point():
    pm, p = _canvas()
    p.drawLine(12, 6, 12, 18)
    p.drawLine(6, 12, 18, 12)
    p.setBrush(QBrush(_STROKE))
    p.drawEllipse(QPointF(12, 12), 1.6, 1.6)
    p.end()
    return pm


def _text():
    pm, p = _canvas()
    from PySide6.QtGui import QFont
    f = QFont()
    f.setPixelSize(16)
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(0, 0, SIZE, SIZE), Qt.AlignCenter, "A")
    p.end()
    return pm


def _mtext():
    pm, p = _canvas()
    from PySide6.QtGui import QFont
    f = QFont()
    f.setPixelSize(11)
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(2, 1, SIZE, SIZE), Qt.AlignLeft | Qt.AlignVCenter, "A")
    p.setPen(QPen(_STROKE, 1.0))
    for y in (14, 18, 22):
        p.drawLine(4, y, 20, y)
    p.end()
    return pm


# -- modify icons --------------------------------------------------------------

def _arrow(p: QPainter, x: float, y: float, ang: float) -> None:
    """An open arrowhead in the current pen — used by the dimension icons."""
    for da in (150, -150):
        b = math.radians(ang + da)
        p.drawLine(QPointF(x, y),
                   QPointF(x + 5 * math.cos(b), y + 5 * math.sin(b)))


def _erase():
    """AutoCAD's eraser: a tilted rubber with its red tip on a blue line."""
    pm, p = _canvas()
    _pen(p, _ACCENT, 1.4)
    p.drawLine(3, 21, 19, 21)                       # the line being erased
    p.save()
    p.translate(12, 11)
    p.rotate(-45)
    _pen(p, _STROKE, 1.1)
    p.setBrush(QBrush(_RUBBER))                     # the body, tapered
    p.drawPolygon(QPolygonF([QPointF(-3.4, -10), QPointF(3.4, -10),
                             QPointF(3.4, 3), QPointF(-3.4, 3)]))
    p.setBrush(QBrush(_RUBBER_TIP))                 # and the rubber tip
    p.drawPolygon(QPolygonF([QPointF(-3.4, 3), QPointF(3.4, 3),
                             QPointF(2.2, 8), QPointF(-2.2, 8)]))
    p.restore()
    p.end()
    return pm


def _move():
    """Just the four-way arrow — AutoCAD draws no object here."""
    pm, p = _canvas()
    _pen(p, _STROKE, 1.3)
    p.drawLine(12, 5, 12, 19)
    p.drawLine(5, 12, 19, 12)
    for x, y, ang in ((12, 3, -90), (12, 21, 90), (3, 12, 180), (21, 12, 0)):
        _tip(p, x, y, ang, 4.0, _STROKE)
    p.end()
    return pm


def _copy():
    """The source above with its arrow, the copies below in blue."""
    pm, p = _canvas()
    _pen(p, _STROKE, 1.3)
    p.drawEllipse(QPointF(7, 7), 3.6, 3.6)          # the object
    p.drawLine(11, 5, 17, 5)                        # and where it goes
    _tip(p, 17, 8.5, 90, 3.6, _STROKE)
    p.drawLine(17, 5, 17, 7)
    _pen(p, _ACCENT, 1.3)
    p.drawEllipse(QPointF(9, 17), 4.0, 4.0)         # the copies
    p.drawEllipse(QPointF(16, 17), 4.0, 4.0)
    p.end()
    return pm


def _rotate():
    """An open circular arrow, nothing else."""
    pm, p = _canvas()
    _pen(p, _STROKE, 1.5)
    p.drawArc(QRectF(4, 5, 16, 16), -40 * 16, 305 * 16)
    _tip(p, 20.1, 8.2, -5, 4.8, _STROKE)
    p.end()
    return pm


def _mirror():
    """A shape and its reflection: the twin is the blue one."""
    pm, p = _canvas()
    _pen(p, _STROKE, 1.3)
    p.drawPolygon(QPolygonF([QPointF(11, 4), QPointF(11, 19), QPointF(4, 19)]))
    _pen(p, _ACCENT, 1.3)
    p.drawPolygon(QPolygonF([QPointF(13, 4), QPointF(13, 19), QPointF(20, 19)]))
    p.end()
    return pm


def _scale():
    """The big outline in white, what it scales to in blue."""
    pm, p = _canvas()
    _pen(p, _STROKE, 1.3)
    p.drawRect(QRectF(4, 4, 16, 16))
    _pen(p, _ACCENT, 1.3)
    p.drawRect(QRectF(4, 12, 8, 8))
    p.end()
    return pm


def _trim():
    """Scissors cutting a line — AutoCAD's own glyph for TRIM."""
    pm, p = _canvas()
    _pen(p, _STROKE, 1.2, Qt.DashLine)
    p.drawLine(6, 4, 20, 4)                         # the line being cut
    _pen(p, _STROKE, 1.3)
    p.drawLine(9, 6, 16, 16)                        # the blades
    p.drawLine(16, 6, 9, 16)
    p.drawEllipse(QPointF(8.5, 18), 2.4, 2.4)       # the handles
    p.drawEllipse(QPointF(16.5, 18), 2.4, 2.4)
    p.end()
    return pm


def _extend():
    """An arrow reaching the boundary it stops at."""
    pm, p = _canvas()
    _pen(p, _ACCENT, 1.3)
    p.drawLine(19, 4, 19, 20)                       # the boundary
    _pen(p, _STROKE, 1.3)
    p.drawLine(4, 12, 16, 12)
    _tip(p, 18, 12, 0, 4.2, _STROKE)
    p.end()
    return pm


def _fillet():
    """The rounded corner, with the stub of the corner it replaced."""
    pm, p = _canvas()
    _pen(p, _STROKE, 1.4)
    p.drawArc(QRectF(6, 5, 16, 16), 90 * 16, 90 * 16)
    p.drawLine(6, 13, 6, 20)
    p.drawLine(14, 5, 20, 5)
    _pen(p, _ACCENT, 1.2)
    p.drawLine(16, 8, 20, 8)                        # the trimmed corner
    p.end()
    return pm


def _chamfer():
    """Same idea as the fillet, cut straight."""
    pm, p = _canvas()
    _pen(p, _STROKE, 1.4)
    p.drawLine(6, 20, 6, 12)
    p.drawLine(6, 12, 14, 5)                        # the bevel
    p.drawLine(14, 5, 20, 5)
    _pen(p, _ACCENT, 1.2)
    p.drawLine(16, 8, 20, 8)
    p.end()
    return pm


def _array():
    """A grid of copies: the first one white, the rest blue."""
    pm, p = _canvas()
    for row in range(2):
        for col in range(2):
            # The original is the first one; the rest are its copies.
            _pen(p, _STROKE if (row, col) == (0, 0) else _ACCENT, 1.3)
            p.drawRect(QRectF(4 + col * 9, 4 + row * 9, 7, 7))
    p.end()
    return pm


def _stretch():
    """A shape with one side pulled out of true, and the arrow that did it."""
    pm, p = _canvas()
    _pen(p, _STROKE, 1.3)
    p.drawPolyline(QPolygonF([QPointF(*xy) for xy in
                              ((5, 20), (5, 4), (15, 4), (19, 20))]))
    _pen(p, _ACCENT, 1.3)
    p.drawLine(5, 20, 19, 20)                       # the edge that moved
    p.drawLine(12, 16, 17, 16)
    _tip(p, 19, 16, 0, 3.6, _ACCENT)
    p.end()
    return pm


def _offset():
    """Nested parallels — the offset copy inside, in blue."""
    pm, p = _canvas()
    _pen(p, _STROKE, 1.3)
    p.drawPolyline(QPolygonF([QPointF(*xy) for xy in
                              ((19, 4), (5, 4), (5, 20), (19, 20))]))
    _pen(p, _ACCENT, 1.3)
    p.drawPolyline(QPolygonF([QPointF(*xy) for xy in
                              ((19, 9), (10, 9), (10, 15), (19, 15))]))
    p.end()
    return pm


def _explode():
    """A block whose pieces have come apart."""
    pm, p = _canvas()
    _pen(p, _STROKE, 1.3)
    p.drawRect(QRectF(3, 3, 8, 8))
    p.drawRect(QRectF(3, 13, 8, 8))
    _pen(p, _ACCENT, 1.3)
    p.drawRect(QRectF(13, 3, 8, 8))
    p.drawRect(QRectF(13, 13, 8, 8))
    p.end()
    return pm


def _break():
    """One object, now two, with the gap between them."""
    pm, p = _canvas()
    _pen(p, _STROKE, 1.4)
    p.drawLine(3, 12, 9, 12)
    _pen(p, _ACCENT, 1.4)
    p.drawLine(15, 12, 21, 12)
    _pen(p, _STROKE, 1.1)
    p.drawLine(9, 7, 9, 17)                         # where it was cut
    p.drawLine(15, 7, 15, 17)
    p.end()
    return pm


def _join():
    """Two pieces below, the single object they become above."""
    pm, p = _canvas()
    _pen(p, _STROKE, 1.4)
    p.drawLine(3, 17, 10, 17)
    p.drawLine(14, 17, 21, 17)
    _pen(p, _ACCENT, 1.4)
    p.drawLine(3, 8, 21, 8)
    _pen(p, _STROKE, 1.1)
    p.drawLine(12, 15, 12, 10)
    _tip(p, 12, 8.5, -90, 3.4, _STROKE)
    p.end()
    return pm


def _matchprop():
    """The brush that carries one object's look onto another."""
    pm, p = _canvas()
    _pen(p, _STROKE, 1.3)
    p.drawRect(QRectF(2, 14, 7, 7))                 # the source
    _pen(p, _ACCENT, 1.3)
    p.drawRect(QRectF(15, 14, 7, 7))                # the destination
    p.save()
    p.translate(12, 8)
    p.rotate(30)
    _pen(p, _STROKE, 1.2)
    p.setBrush(QBrush(_RUBBER))
    p.drawRect(QRectF(-3, -8, 6, 8))                # the handle
    p.setBrush(QBrush(_ACCENT))
    p.drawRect(QRectF(-3, 0, 6, 4))                 # the bristles
    p.restore()
    p.end()
    return pm


def _pedit():
    """A polyline with its vertices, one of them picked up."""
    pm, p = _canvas()
    _pen(p, _STROKE, 1.3)
    p.drawPolyline(QPolygonF([QPointF(*xy) for xy in
                              ((3, 18), (9, 8), (15, 15), (21, 5))]))
    p.save()
    p.setPen(QPen(_STROKE, 1.0))
    p.setBrush(Qt.NoBrush)
    for x, y in ((3, 18), (15, 15), (21, 5)):
        p.drawRect(QRectF(x - 1.8, y - 1.8, 3.6, 3.6))
    p.setPen(QPen(_ACCENT, 1.0))
    p.setBrush(QBrush(_ACCENT))
    p.drawRect(QRectF(9 - 2.1, 8 - 2.1, 4.2, 4.2))  # the one being edited
    p.restore()
    p.end()
    return pm


def _hatch():
    pm, p = _canvas()
    p.drawRect(QRectF(4, 4, 16, 16))                 # the boundary
    p.save()
    p.setPen(QPen(_ACCENT, 1.2))
    for i in range(4):                               # ANSI31-style diagonals
        offset = 4 + i * 4
        p.drawLine(QPointF(4, 4 + offset), QPointF(4 + offset, 4))
    p.restore()
    p.end()
    return pm


def _insert():
    pm, p = _canvas()
    p.drawRect(QRectF(6, 6, 12, 12))                 # the block
    p.drawLine(QPointF(9, 12), QPointF(15, 12))      # its geometry
    p.drawLine(QPointF(12, 9), QPointF(12, 15))
    _node(p, 6, 18)                                  # insertion point
    p.end()
    return pm


def _xline():
    pm, p = _canvas()
    p.drawLine(2, 15, 22, 9)                         # edge-to-edge line
    _node(p, 9, 13)                                  # root point
    _node(p, 16, 11)                                 # through point
    p.end()
    return pm


def _ray():
    pm, p = _canvas()
    p.drawLine(5, 18, 22, 7)                         # off one edge only
    _node(p, 5, 18)                                  # anchored start
    p.end()
    return pm


def _divide():
    pm, p = _canvas()
    p.drawLine(3, 12, 21, 12)
    for x in (8, 12, 16):                            # equal thirds
        _node(p, x, 12)
    p.end()
    return pm


def _measure():
    pm, p = _canvas()
    p.drawLine(3, 12, 21, 12)
    p.save()
    p.setPen(QPen(_ACCENT, 1.2))
    for x in (8, 13):                                # fixed step, remainder
        p.drawLine(QPointF(x, 9), QPointF(x, 15))
    p.restore()
    p.end()
    return pm


def _spline():
    """The classic Draw-toolbar spline: an S-curve through fit points."""
    from PySide6.QtGui import QPainterPath

    pm, p = _canvas()
    path = QPainterPath()
    path.moveTo(4, 19)
    path.cubicTo(9, 8, 12, 21, 16, 12)
    path.quadTo(18, 7.5, 20, 5)
    p.drawPath(path)
    p.save()
    p.setPen(QPen(_ACCENT, 1.2))
    for x, y in ((4, 19), (11, 14.6), (20, 5)):
        p.drawRect(QRectF(x - 1.4, y - 1.4, 2.8, 2.8))
    p.restore()
    p.end()
    return pm


def _revcloud():
    """A closed cloud of outward scallops, like BricsCAD's toolbar icon:
    semicircles bulging outward over the chords of an oval."""
    import math

    from PySide6.QtGui import QPainterPath

    pm, p = _canvas()
    cx, cy, rx, ry = 12.0, 12.5, 8.4, 6.2
    n = 5                      # five fat scallops read better tiny than eight
    pts = [(cx + rx * math.cos(2 * math.pi * i / n),
            cy + ry * math.sin(2 * math.pi * i / n)) for i in range(n)]
    path = QPainterPath()
    for i in range(n):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % n]
        mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
        r = math.hypot(bx - ax, by - ay) / 2.0
        start = math.degrees(math.atan2(-(ay - my), ax - mx))
        if i == 0:
            path.moveTo(ax, ay)
        path.arcTo(QRectF(mx - r, my - r, 2 * r, 2 * r), start, -180)
    p.drawPath(path)
    p.end()
    return pm


# -- application menu icons (File / Edit / View / Insert / Format) --------------

def _sheet(p: QPainter, x=6, y=3, w=12, h=17, fold=4) -> None:
    """A page with a folded corner (the File-menu document glyph)."""
    p.drawLine(QPointF(x, y), QPointF(x + w - fold, y))
    p.drawLine(QPointF(x + w - fold, y), QPointF(x + w, y + fold))
    p.drawLine(QPointF(x + w, y + fold), QPointF(x + w, y + h))
    p.drawLine(QPointF(x + w, y + h), QPointF(x, y + h))
    p.drawLine(QPointF(x, y + h), QPointF(x, y))
    p.drawLine(QPointF(x + w - fold, y), QPointF(x + w - fold, y + fold))
    p.drawLine(QPointF(x + w - fold, y + fold), QPointF(x + w, y + fold))


def _new():
    pm, p = _canvas()
    _sheet(p)
    p.end()
    return pm


def _open():
    pm, p = _canvas()
    p.drawLine(3, 19, 3, 7)                          # folder back
    p.drawLine(3, 7, 9, 7)
    p.drawLine(9, 7, 11, 9)
    p.drawLine(11, 9, 18, 9)
    p.drawLine(18, 9, 18, 12)
    p.save()
    p.setPen(QPen(_ACCENT, 1.4))                     # open front flap
    p.drawLine(3, 19, 7, 12)
    p.drawLine(7, 12, 21, 12)
    p.drawLine(21, 12, 17, 19)
    p.drawLine(17, 19, 3, 19)
    p.restore()
    p.end()
    return pm


def _saveas():
    pm, p = _canvas()
    p.drawRect(QRectF(4, 4, 16, 16))                 # the diskette
    p.drawRect(QRectF(8, 4, 8, 5))                   # shutter
    p.drawRect(QRectF(7, 12, 10, 8))                 # label
    p.end()
    return pm


def _save():
    """The diskette alone — SAVE, next to Save As's labelled one."""
    pm, p = _canvas()
    p.drawRect(QRectF(4, 4, 16, 16))                 # the diskette
    p.drawRect(QRectF(9, 4, 7, 5))                   # shutter
    p.drawRect(QRectF(7, 13, 10, 7))                 # label
    p.save()
    p.setPen(QPen(_ACCENT, 1.2))
    p.drawLine(9, 16, 15, 16)                        # a written line
    p.restore()
    p.end()
    return pm


def _zoom_previous():
    """The magnifier with a back arrow — ZOOM Previous."""
    pm, p = _canvas()
    _magnifier(p)
    p.save()
    p.setPen(QPen(_ACCENT, 1.4))
    p.drawLine(13, 10, 7, 10)                        # arrow back
    p.drawLine(7, 10, 10, 7)
    p.drawLine(7, 10, 10, 13)
    p.restore()
    p.end()
    return pm


def _plotprint():
    pm, p = _canvas()
    p.drawRect(QRectF(4, 9, 16, 8))                  # printer body
    p.drawLine(8, 9, 8, 4)                           # sheet in
    p.drawLine(8, 4, 16, 4)
    p.drawLine(16, 4, 16, 9)
    p.save()
    p.setPen(QPen(_ACCENT, 1.4))
    p.drawLine(8, 17, 8, 21)                         # sheet out
    p.drawLine(8, 21, 16, 21)
    p.drawLine(16, 21, 16, 17)
    p.restore()
    p.end()
    return pm


def _undo():
    pm, p = _canvas()
    p.drawArc(QRectF(5, 7, 14, 12), 0, 180 * 16)
    p.drawLine(QPointF(5, 13), QPointF(5, 18))
    _arrow(p, 5, 18, 90)
    p.end()
    return pm


def _redo():
    pm, p = _canvas()
    p.drawArc(QRectF(5, 7, 14, 12), 0, 180 * 16)
    p.drawLine(QPointF(19, 13), QPointF(19, 18))
    _arrow(p, 19, 18, 90)
    p.end()
    return pm


def _cutclip():
    pm, p = _canvas()
    p.drawLine(8, 4, 14, 16)                         # blades
    p.drawLine(16, 4, 10, 16)
    p.drawEllipse(QPointF(8.5, 18), 2.5, 2.5)        # handles
    p.drawEllipse(QPointF(15.5, 18), 2.5, 2.5)
    p.end()
    return pm


def _copyclip():
    pm, p = _canvas()
    _sheet(p, 4, 6, 10, 14, 3)
    p.save()
    p.setPen(QPen(_ACCENT, 1.4))
    _sheet(p, 10, 3, 10, 14, 3)
    p.restore()
    p.end()
    return pm


def _pasteclip():
    pm, p = _canvas()
    p.drawRect(QRectF(4, 4, 14, 17))                 # clipboard
    p.drawRect(QRectF(8, 2, 6, 4))                   # clip
    p.save()
    p.setPen(QPen(_ACCENT, 1.4))
    _sheet(p, 10, 9, 10, 12, 3)                      # the pasted sheet
    p.restore()
    p.end()
    return pm


def _magnifier(p: QPainter) -> None:
    p.drawEllipse(QPointF(10, 10), 7, 7)
    p.drawLine(QPointF(15, 15), QPointF(21, 21))


def _zoom_extents():
    pm, p = _canvas()
    _magnifier(p)
    p.save()
    p.setPen(QPen(_ACCENT, 1.2))
    for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3)):    # outward arrows
        p.drawLine(QPointF(10, 10), QPointF(10 + dx, 10 + dy))
    p.restore()
    p.end()
    return pm


def _zoom_window():
    pm, p = _canvas()
    _magnifier(p)
    p.save()
    p.setPen(QPen(_ACCENT, 1.2))
    p.drawRect(QRectF(7, 7, 6, 6))
    p.restore()
    p.end()
    return pm


def _finger(x0: float, y0: float, x1: float, y1: float, w: float) -> QPainterPath:
    """A rounded finger from its base (x0, y0) to its tip (x1, y1)."""
    length = math.hypot(x1 - x0, y1 - y0)
    path = QPainterPath()
    path.addRoundedRect(QRectF(-w / 2, -length, w, length + w / 2), w / 2, w / 2)
    turn = QTransform()
    turn.translate(x0, y0)
    turn.rotate(math.degrees(math.atan2(x1 - x0, -(y1 - y0))))
    return turn.map(path)


def hand_shape(closed: bool = False):
    """The hand, in a 24-unit box: (outline path, crease lines).

    One drawing for the PAN icon and for the canvas cursor, open while
    hovering and closed while dragging (#32; Marco picked the fist from
    three proposals, 2026-09-27): palm, four spread fingers and the thumb
    out to the left -- or a fist seen from the front, four knuckles with
    the creases between them and the thumb's line down the left.
    """
    hand = QPainterPath()
    if not closed:
        hand.addRoundedRect(QRectF(6.6, 10.6, 11.0, 10.4), 4.2, 4.2)
        for finger in (_finger(8.1, 12.0, 7.4, 4.6, 2.5),      # index
                       _finger(10.9, 12.0, 10.9, 3.2, 2.5),    # middle
                       _finger(13.7, 12.0, 14.4, 4.0, 2.5),    # ring
                       _finger(16.2, 13.0, 17.8, 6.8, 2.3),    # little
                       _finger(7.4, 17.0, 3.2, 11.8, 2.6)):    # thumb
            hand = hand.united(finger)
        return hand.simplified(), []
    hand.addRoundedRect(QRectF(6.2, 9.0, 12.4, 12.2), 5.0, 5.0)    # palm
    heel = QPainterPath()
    heel.addEllipse(QPointF(8.2, 16.2), 3.6, 4.4)                  # thumb mound
    hand = hand.united(heel)
    for x, top in ((8.3, 7.2), (11.0, 6.2), (13.7, 6.6), (16.3, 8.0)):
        hand = hand.united(_finger(x, 11.5, x, top, 2.7))          # knuckles
    creases = [((9.65, 8.4), (9.65, 10.4)), ((12.35, 7.9), (12.35, 10.2)),
               ((15.0, 8.6), (15.0, 10.6)), ((7.0, 9.4), (7.0, 13.6))]
    return hand.simplified(), creases


def draw_hand(p: QPainter, closed: bool, ink: QColor, fill=None,
              width: float = 1.3) -> None:
    """:func:`hand_shape` stroked in ``ink`` (and filled, if given)."""
    path, creases = hand_shape(closed)
    pen = QPen(ink, width)
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setCapStyle(Qt.RoundCap)
    p.save()
    p.setPen(pen)
    p.setBrush(fill if fill is not None else Qt.NoBrush)
    p.drawPath(path)
    for a, b in creases:
        p.drawLine(QPointF(*a), QPointF(*b))
    p.restore()


def _pan():
    # AutoCAD's open hand, in outline like the rest of the set
    pm, p = _canvas()
    draw_hand(p, closed=False, ink=_STROKE)
    p.end()
    return pm


def _chevron(pointing_right: bool):
    # The sidebar handle's chevron: it points the way the sidebar will go
    # (right folds it away, left brings it back), as in IngeTrazo.
    pm, p = _canvas()
    pen = QPen(_STROKE, 3.0)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    tip, back = (15.5, 9.5) if pointing_right else (8.5, 14.5)
    p.drawPolyline(QPolygonF([QPointF(back, 5.5), QPointF(tip, 12),
                              QPointF(back, 18.5)]))
    p.end()
    return pm


def _regen():
    pm, p = _canvas()
    p.drawArc(QRectF(5, 5, 14, 14), 30 * 16, 300 * 16)
    _arrow(p, 17.1, 8.5, 145)
    p.end()
    return pm


def _layers():
    pm, p = _canvas()
    # the classic stacked-sheets layers glyph
    for i, y in enumerate((6, 11, 16)):
        if i == 1:
            p.save()
            p.setPen(QPen(_ACCENT, 1.4))
        poly = QPolygonF([QPointF(12, y - 3), QPointF(21, y + 1),
                          QPointF(12, y + 5), QPointF(3, y + 1)])
        p.drawPolygon(poly)
        if i == 1:
            p.restore()
    p.end()
    return pm


def _linetype():
    pm, p = _canvas()
    p.drawLine(3, 6, 21, 6)                          # continuous
    for x0, x1 in ((3, 8), (11, 16), (19, 21)):      # dashed
        p.drawLine(x0, 12, x1, 12)
    for x0, x1 in ((3, 7), (10, 11), (14, 18), (21, 21)):  # dash-dot
        p.drawLine(x0, 18, x1, 18)
    p.end()
    return pm


def _textstyle():
    pm, p = _canvas()
    from PySide6.QtGui import QFont
    f = QFont()
    f.setPixelSize(15)
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(2, 4, 12, 18), Qt.AlignCenter, "A")
    f.setItalic(True)
    p.setFont(f)
    p.save()
    p.setPen(QPen(_ACCENT, 1.2))
    p.drawText(QRectF(11, 4, 12, 18), Qt.AlignCenter, "A")
    p.restore()
    p.end()
    return pm


def _block():
    pm, p = _canvas()
    p.drawRect(QRectF(4, 8, 12, 12))                 # the geometry
    p.drawLine(QPointF(7, 14), QPointF(13, 14))
    p.drawLine(QPointF(10, 11), QPointF(10, 17))
    p.save()
    p.setPen(QPen(_ACCENT, 1.4))                     # "create": plus badge
    p.drawLine(QPointF(19, 4), QPointF(19, 10))
    p.drawLine(QPointF(16, 7), QPointF(22, 7))
    p.restore()
    p.end()
    return pm


# -- dimension icons (classic Dimension toolbar glyphs) -------------------------

def _dim_arrows(p: QPainter, x1: float, x2: float, y: float) -> None:
    """A dimension line with inward arrowheads at both ends."""
    p.drawLine(QPointF(x1, y), QPointF(x2, y))
    _arrow(p, x1, y, 180)
    _arrow(p, x2, y, 0)


def _dimlinear():
    pm, p = _canvas()
    p.save()
    p.setPen(QPen(_ACCENT, 1.4))
    p.drawLine(4, 6, 20, 6)                          # the measured edge
    p.restore()
    p.drawLine(4, 8, 4, 20)                          # extension lines
    p.drawLine(20, 8, 20, 20)
    _dim_arrows(p, 4, 20, 17)
    p.end()
    return pm


def _dimaligned():
    pm, p = _canvas()
    p.save()
    p.setPen(QPen(_ACCENT, 1.4))
    p.drawLine(3, 12, 15, 3)                         # slanted edge
    p.restore()
    p.drawLine(3, 12, 9, 20)                         # extension lines
    p.drawLine(15, 3, 21, 11)
    p.drawLine(QPointF(9, 20), QPointF(21, 11))      # aligned dim line
    _arrow(p, 9, 20, 143)
    _arrow(p, 21, 11, -37)
    p.end()
    return pm


def _dimangular():
    pm, p = _canvas()
    p.save()
    p.setPen(QPen(_ACCENT, 1.4))
    p.drawLine(4, 20, 20, 20)                        # the two legs
    p.drawLine(4, 20, 16, 6)
    p.restore()
    p.drawArc(QRectF(4 - 9, 20 - 9, 18, 18), 0, 50 * 16)
    p.end()
    return pm


def _dimarc():
    pm, p = _canvas()
    p.save()
    p.setPen(QPen(_ACCENT, 1.4))
    p.drawArc(QRectF(5, 8, 14, 14), 20 * 16, 140 * 16)   # the arc
    p.restore()
    p.drawArc(QRectF(2, 3, 20, 20), 25 * 16, 130 * 16)   # dimension arc
    p.end()
    return pm


def _dimordinate():
    pm, p = _canvas()
    _node(p, 5, 18)                                  # the feature
    p.drawLine(5, 18, 5, 11)                         # ordinate leader
    p.drawLine(5, 11, 12, 7)
    p.drawLine(12, 7, 19, 7)
    p.drawLine(4, 21, 9, 21)                         # datum axis hint
    p.end()
    return pm


def _dimradius():
    pm, p = _canvas()
    p.save()
    p.setPen(QPen(_ACCENT, 1.4))
    p.drawEllipse(QPointF(10, 14), 8, 8)
    p.restore()
    p.drawLine(QPointF(10, 14), QPointF(21, 4))      # radius leader
    _arrow(p, 15.7, 8.8, -42)
    p.end()
    return pm


def _dimdiameter():
    pm, p = _canvas()
    p.save()
    p.setPen(QPen(_ACCENT, 1.4))
    p.drawEllipse(QPointF(12, 12), 8, 8)
    p.restore()
    p.drawLine(QPointF(4, 20), QPointF(20, 4))       # through-diameter
    _arrow(p, 6.3, 17.7, 135)
    _arrow(p, 17.7, 6.3, -45)
    p.end()
    return pm


def _dimbaseline():
    pm, p = _canvas()
    p.drawLine(4, 3, 4, 21)                          # shared first ext line
    p.drawLine(14, 8, 14, 21)
    p.drawLine(20, 3, 20, 14)
    _dim_arrows(p, 4, 14, 18)
    _dim_arrows(p, 4, 20, 11)
    p.end()
    return pm


def _dimcontinue():
    pm, p = _canvas()
    p.drawLine(3, 8, 3, 21)
    p.drawLine(12, 8, 12, 21)
    p.drawLine(21, 8, 21, 21)
    _dim_arrows(p, 3, 12, 17)
    _dim_arrows(p, 12, 21, 17)
    p.end()
    return pm


def _dimcenter():
    pm, p = _canvas()
    p.save()
    p.setPen(QPen(_ACCENT, 1.4))
    p.drawEllipse(QPointF(12, 12), 8, 8)
    p.restore()
    p.drawLine(9, 12, 15, 12)                        # the center mark
    p.drawLine(12, 9, 12, 15)
    p.drawLine(2, 12, 6, 12)                         # center lines
    p.drawLine(18, 12, 22, 12)
    p.drawLine(12, 2, 12, 6)
    p.drawLine(12, 18, 12, 22)
    p.end()
    return pm


def _dimtedit():
    pm, p = _canvas()
    p.drawLine(3, 8, 3, 21)
    p.drawLine(21, 8, 21, 21)
    _dim_arrows(p, 3, 21, 17)
    from PySide6.QtGui import QFont
    f = QFont()
    f.setPixelSize(10)
    f.setBold(True)
    p.setFont(f)
    p.save()
    p.setPen(QPen(_ACCENT, 1.2))
    p.drawText(QRectF(6, 1, 12, 12), Qt.AlignCenter, "A")
    p.restore()
    p.end()
    return pm


def _dimstyle():
    pm, p = _canvas()
    p.drawLine(3, 6, 3, 18)
    p.drawLine(21, 6, 21, 18)
    _dim_arrows(p, 3, 21, 14)
    p.save()
    p.setPen(QPen(_ACCENT, 1.6))                     # the styling brush
    p.drawLine(QPointF(14, 21), QPointF(21, 14))
    p.drawLine(QPointF(13, 22), QPointF(15, 20))
    p.restore()
    p.end()
    return pm


# -- layout / paper-space icons -------------------------------------------------

def _mview():
    pm, p = _canvas()
    p.drawRect(QRectF(3, 4, 18, 16))                 # the sheet
    p.save()
    p.setPen(QPen(_ACCENT, 1.4))
    p.drawRect(QRectF(7, 8, 10, 8))                  # the floating viewport
    p.restore()
    p.end()
    return pm


def _vplock():
    pm, p = _canvas()
    p.drawRect(QRectF(3, 6, 11, 11))                 # the viewport
    p.save()
    p.setPen(QPen(_ACCENT, 1.4))
    p.drawRect(QRectF(13, 13, 8, 7))                 # padlock body
    p.drawArc(QRectF(14.5, 9, 5, 7), 0, 180 * 16)    # shackle
    p.restore()
    p.end()
    return pm


def _pagesetup():
    pm, p = _canvas()
    p.drawRect(QRectF(5, 3, 14, 18))                 # the sheet
    p.save()
    pen = QPen(_ACCENT, 1.1)
    pen.setStyle(Qt.DashLine)
    p.setPen(pen)
    p.drawRect(QRectF(7.5, 5.5, 9, 13))              # printable margin
    p.restore()
    p.end()
    return pm


def _layout():
    pm, p = _canvas()
    p.drawRect(QRectF(3, 3, 18, 13))                 # the sheet
    p.save()
    p.setPen(QPen(_ACCENT, 1.4))
    p.drawRect(QRectF(4, 18, 6, 4))                  # the layout tabs
    p.drawRect(QRectF(12, 18, 6, 4))
    p.restore()
    p.end()
    return pm


_PAINTERS = {
    "LINE": _line, "CIRCLE": _circle, "ARC": _arc, "PLINE": _pline,
    "RECTANG": _rectang, "POLYGON": _polygon, "ELLIPSE": _ellipse,
    "POINT": _point, "TEXT": _text, "MTEXT": _mtext,
    "ERASE": _erase, "MOVE": _move, "COPY": _copy, "ROTATE": _rotate,
    "SCALE": _scale, "MIRROR": _mirror, "OFFSET": _offset, "TRIM": _trim,
    "EXTEND": _extend, "FILLET": _fillet, "CHAMFER": _chamfer,
    "EXPLODE": _explode, "STRETCH": _stretch, "BREAK": _break,
    "JOIN": _join, "ARRAY": _array, "MATCHPROP": _matchprop,
    "PEDIT": _pedit,
    "HATCH": _hatch, "-HATCH": _hatch, "INSERT": _insert,
    "XLINE": _xline, "RAY": _ray, "DIVIDE": _divide, "MEASURE": _measure,
    "REVCLOUD": _revcloud, "SPLINE": _spline,
    "DIMLINEAR": _dimlinear, "DIMALIGNED": _dimaligned,
    "DIMANGULAR": _dimangular, "DIMARC": _dimarc,
    "DIMORDINATE": _dimordinate, "DIMRADIUS": _dimradius,
    "DIMDIAMETER": _dimdiameter, "DIMBASELINE": _dimbaseline,
    "DIMCONTINUE": _dimcontinue, "DIMCENTER": _dimcenter,
    "DIMTEDIT": _dimtedit, "DIMSTYLE": _dimstyle,
    "MVIEW": _mview, "VPLOCK": _vplock, "PAGESETUP": _pagesetup,
    "LAYOUT": _layout,
    # application menus (File / Edit / View / Insert / Format)
    "NEW": _new, "OPEN": _open, "SAVE": _save, "SAVEAS": _saveas,
    "PLOT": _plotprint,
    "UNDO": _undo, "REDO": _redo,
    "CUTCLIP": _cutclip, "COPYCLIP": _copyclip, "PASTECLIP": _pasteclip,
    "ZOOM_EXTENTS": _zoom_extents, "ZOOM_WINDOW": _zoom_window,
    "ZOOM_PREVIOUS": _zoom_previous,
    "PAN": _pan, "REGEN": _regen,
    "SIDEBAR_FOLD": lambda: _chevron(True),
    "SIDEBAR_UNFOLD": lambda: _chevron(False),
    "LAYER": _layers, "LINETYPE": _linetype, "STYLE": _textstyle,
    "BLOCK": _block,
}


def command_icon(name: str) -> QIcon:
    painter = _PAINTERS.get(name)
    return QIcon(painter()) if painter else QIcon()


# -- Layers panel states (#100) -------------------------------------------------
# They were font glyphs -- a bulb, a sun, a padlock, a printer as emoji -- and
# a machine without a desktop's fonts drew empty boxes in their place. The
# two padlocks also looked alike at 11 px (GeoCad's review). Painted here,
# each pair differs in shape AND colour.
_LAMP = QColor(0xF2, 0xC9, 0x4C)
_DIM = QColor(0x6B, 0x6B, 0x72)
_DIM_FILL = QColor(0x3A, 0x3A, 0x40)
_ICE = QColor(0x8F, 0xC8, 0xF0)
_NO = QColor(0xD8, 0x6B, 0x62)


def _bulb(on: bool):
    pm, p = _canvas()
    p.setPen(QPen(_LAMP if on else _DIM, 1.4))
    p.setBrush(QBrush(_LAMP if on else _DIM_FILL))
    p.drawEllipse(QPointF(12, 10), 6.5, 6.5)          # the glass
    p.setBrush(QBrush(_STROKE if on else _DIM))
    p.setPen(Qt.NoPen)
    p.drawRect(QRectF(9, 16.5, 6, 4.5))               # the screw base
    p.end()
    return pm


def _sun():
    pm, p = _canvas()
    _pen(p, _LAMP, 1.6)
    for k in range(8):
        a = math.radians(45 * k)
        p.drawLine(QPointF(12 + 6.5 * math.cos(a), 12 + 6.5 * math.sin(a)),
                   QPointF(12 + 9.5 * math.cos(a), 12 + 9.5 * math.sin(a)))
    p.setBrush(QBrush(_LAMP))
    p.drawEllipse(QPointF(12, 12), 4.2, 4.2)
    p.end()
    return pm


def _snowflake():
    pm, p = _canvas()
    _pen(p, _ICE, 1.6)
    for k in range(3):
        a = math.radians(90 + 60 * k)
        dx, dy = 9 * math.cos(a), 9 * math.sin(a)
        p.drawLine(QPointF(12 - dx, 12 - dy), QPointF(12 + dx, 12 + dy))
        for sign in (1, -1):                         # the little V at each end
            ex, ey = 12 + sign * dx, 12 + sign * dy
            for turn in (35, -35):
                b = a + math.radians(turn) + (math.pi if sign > 0 else 0)
                p.drawLine(QPointF(ex, ey),
                           QPointF(ex + 3.5 * math.cos(b), ey + 3.5 * math.sin(b)))
    p.end()
    return pm


def _padlock(locked: bool):
    pm, p = _canvas()
    colour = _LAMP if locked else _STROKE
    _pen(p, colour, 2.0)
    p.setBrush(Qt.NoBrush)
    shackle = QPainterPath()
    if locked:                                        # closed, both legs in
        shackle.moveTo(7.5, 12)
        shackle.lineTo(7.5, 8)
        shackle.arcTo(QRectF(7.5, 3.5, 9, 9), 180, -180)
        shackle.lineTo(16.5, 12)
    else:                                             # open: lifted, one leg out
        shackle.moveTo(16.5, 12)
        shackle.lineTo(16.5, 6)
        shackle.arcTo(QRectF(16.5, 1.5, 7, 9), 180, -180)
        shackle.lineTo(23.5, 7.5)
    p.drawPath(shackle)
    p.setPen(QPen(colour, 1.4))
    p.setBrush(QBrush(colour) if locked else Qt.NoBrush)
    p.drawRoundedRect(QRectF(5, 11.5, 14, 10), 1.5, 1.5)
    p.end()
    return pm


def _printer(plots: bool):
    pm, p = _canvas()
    _pen(p, _STROKE if plots else _DIM, 1.4)
    p.drawRect(QRectF(7, 3, 10, 6))                   # paper in
    p.drawRoundedRect(QRectF(3, 9, 18, 8), 1.5, 1.5)  # the body
    p.drawRect(QRectF(7, 14, 10, 7))                  # paper out
    if not plots:
        _pen(p, _NO, 2.2)
        p.drawLine(QPointF(4, 21), QPointF(20, 3))
    p.end()
    return pm


_LAYER_STATES = {
    ("on", True): lambda: _bulb(True), ("on", False): lambda: _bulb(False),
    ("thaw", True): _sun, ("thaw", False): _snowflake,
    ("lock", False): lambda: _padlock(False), ("lock", True): lambda: _padlock(True),
    ("plot", True): lambda: _printer(True), ("plot", False): lambda: _printer(False),
}
_layer_state_cache: dict = {}


def layer_state_icon(kind: str, state: bool) -> QIcon:
    """The Layers panel's state icons: ``on`` (bulb lit or not), ``thaw``
    (sun, or snowflake when frozen), ``lock`` (padlock, closed when True),
    ``plot`` (printer, struck out when False)."""
    key = (kind, bool(state))
    icon = _layer_state_cache.get(key)
    if icon is None:
        icon = _layer_state_cache[key] = QIcon(_LAYER_STATES[key]())
    return icon
