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
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF

_STROKE = QColor(210, 210, 210)
_ACCENT = QColor(90, 170, 255)
SIZE = 24


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

def _erase():
    pm, p = _canvas()
    p.drawLine(5, 5, 19, 19)
    p.drawLine(19, 5, 5, 19)
    p.end()
    return pm


def _arrow(p: QPainter, x: float, y: float, ang: float) -> None:
    a = math.radians(ang)
    for da in (150, -150):
        b = math.radians(ang + da)
        p.drawLine(QPointF(x, y),
                   QPointF(x + 5 * math.cos(b), y + 5 * math.sin(b)))


def _move():
    pm, p = _canvas()
    p.drawLine(12, 4, 12, 20)
    p.drawLine(4, 12, 20, 12)
    _arrow(p, 12, 4, -90)
    _arrow(p, 12, 20, 90)
    _arrow(p, 4, 12, 180)
    _arrow(p, 20, 12, 0)
    p.end()
    return pm


def _copy():
    pm, p = _canvas()
    p.drawRect(QRectF(4, 8, 10, 10))
    p.drawRect(QRectF(10, 4, 10, 10))
    p.end()
    return pm


def _rotate():
    pm, p = _canvas()
    p.drawArc(QRectF(4, 4, 16, 16), 30 * 16, 260 * 16)
    _arrow(p, 19, 8, 120)
    p.end()
    return pm


def _scale():
    pm, p = _canvas()
    p.drawRect(QRectF(4, 12, 8, 8))
    p.drawRect(QRectF(9, 5, 11, 11))
    p.drawLine(6, 18, 18, 6)
    p.end()
    return pm


def _mirror():
    pm, p = _canvas()
    p.drawLine(12, 3, 12, 21)
    tri1 = QPolygonF([QPointF(10, 7), QPointF(4, 12), QPointF(10, 17)])
    tri2 = QPolygonF([QPointF(14, 7), QPointF(20, 12), QPointF(14, 17)])
    p.drawPolyline(tri1)
    p.drawPolyline(tri2)
    p.end()
    return pm


def _offset():
    pm, p = _canvas()
    p.drawLine(5, 4, 5, 20)
    p.save()
    p.setPen(QPen(_STROKE, 1.4, Qt.DashLine))
    p.drawLine(13, 4, 13, 20)
    p.restore()
    p.end()
    return pm


def _trim():
    pm, p = _canvas()
    p.drawLine(4, 15, 20, 15)
    p.save()
    p.setPen(QPen(_ACCENT, 1.4))
    p.drawLine(12, 5, 12, 22)
    p.restore()
    # scissor nick
    p.drawLine(10, 13, 14, 17)
    p.end()
    return pm


def _extend():
    pm, p = _canvas()
    p.save()
    p.setPen(QPen(_ACCENT, 1.4))
    p.drawLine(19, 5, 19, 20)
    p.restore()
    p.drawLine(4, 13, 19, 13)
    _arrow(p, 19, 13, 0)
    p.end()
    return pm


def _fillet():
    pm, p = _canvas()
    p.drawLine(5, 20, 5, 11)
    p.drawArc(QRectF(5, 5, 12, 12), 90 * 16, 90 * 16)
    p.drawLine(11, 5, 20, 5)
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


def _revcloud():
    pm, p = _canvas()
    for cx, cy in ((7, 9), (12, 7), (17, 9), (18, 14), (13, 16), (7, 15)):
        p.drawArc(QRectF(cx - 3, cy - 3, 6, 6), 0, 300 * 16)
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
    "EXTEND": _extend, "FILLET": _fillet,
    "HATCH": _hatch, "-HATCH": _hatch, "INSERT": _insert,
    "XLINE": _xline, "RAY": _ray, "DIVIDE": _divide, "MEASURE": _measure,
    "REVCLOUD": _revcloud,
    "DIMLINEAR": _dimlinear, "DIMALIGNED": _dimaligned,
    "DIMANGULAR": _dimangular, "DIMARC": _dimarc,
    "DIMORDINATE": _dimordinate, "DIMRADIUS": _dimradius,
    "DIMDIAMETER": _dimdiameter, "DIMBASELINE": _dimbaseline,
    "DIMCONTINUE": _dimcontinue, "DIMCENTER": _dimcenter,
    "DIMTEDIT": _dimtedit, "DIMSTYLE": _dimstyle,
    "MVIEW": _mview, "VPLOCK": _vplock, "PAGESETUP": _pagesetup,
    "LAYOUT": _layout,
}


def command_icon(name: str) -> QIcon:
    painter = _PAINTERS.get(name)
    return QIcon(painter()) if painter else QIcon()
