# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Hatch style picker — the classic AutoCAD "Hatch and Gradient" dialog.

Choose a pattern (SOLID plus the 172 predefined ACAD/ISO patterns) from a
swatch gallery, then set angle, scale and color. Returns the settings the
HATCH tool applies. Pattern previews are drawn from the pattern definition so
the orientation reads like AutoCAD's palette.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from core import actions
from core.i18n import tr

_SWATCH = 44
#: One cell of the palette grid: the swatch, plus room for two lines of a
#: name like V_MASONRY300x150 under it.
_CELL_W = 104
_CELL_H = _SWATCH + 34
_TILE_BG = QColor(232, 232, 232)
_TILE_FG = QColor(30, 30, 30)


def _pattern_pixmap(name: str) -> QPixmap:
    """One swatch of the gallery, drawn from the pattern's own definition.

    A predefined pattern is a list of line families, each
    ``[angle, base point, offset, dashes]`` in the pattern's units: the
    offset says how far apart the lines of that family are (and how much
    each one slides along itself), and the dashes are its dash/gap/dot
    lengths -- acad.pat's own notation. Drawing it that way is what makes
    ANSI31 (one 45-degree family), ANSI37 (two crossed) and BRICK (a
    staggered grid) look like themselves, which is the whole job of the
    palette. The swatch used to draw a fixed fan of lines from the angle
    alone, so half the gallery looked the same.
    """
    pm = QPixmap(_SWATCH, _SWATCH)
    pm.fill(_TILE_BG)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(QPen(_TILE_FG, 1))
    if name.upper() == "SOLID":
        p.fillRect(2, 2, _SWATCH - 4, _SWATCH - 4, _TILE_FG)
        p.end()
        return pm
    defn = actions.pattern_definition(name)
    if not defn:
        p.drawLine(4, _SWATCH - 4, _SWATCH - 4, 4)
        p.end()
        return pm
    # Show about four line spacings across the tile, whatever units the
    # pattern is defined in (ANSI31 spaces at 2.2, AR-B816 at 8, GRAVEL at
    # 500). The MEDIAN spacing sets the scale, not the largest: GRAVEL is
    # 41 families whose offsets range 25..508, and scaling to the largest
    # squeezed the other forty into a black square.
    spacings = sorted(abs(line[2][1]) or abs(line[2][0]) for line in defn
                      if abs(line[2][1]) or abs(line[2][0]))
    typical = spacings[len(spacings) // 2] if spacings else 1.0
    unit = _SWATCH / (4.0 * typical)
    # A swatch is 44 px: past a few dozen strokes per family it stops being
    # a pattern and becomes ink.
    per_family = 40 if len(defn) <= 8 else 8
    for line in defn:
        _draw_family(p, line[0], line[1], line[2], line[3], unit, per_family)
    p.end()
    return pm


def _draw_family(p: QPainter, angle_deg: float, base, offset, dashes,
                 unit: float, limit: int = 40) -> None:
    """One family of parallel lines of a hatch pattern, tiled over the swatch."""
    ang = math.radians(angle_deg)
    ca, sa = math.cos(ang), math.sin(ang)
    # the offset is given in the line's own frame: x along it, y across
    step_x = (offset[0] * ca - offset[1] * sa) * unit
    step_y = (offset[0] * sa + offset[1] * ca) * unit
    if abs(step_x) < 1e-9 and abs(step_y) < 1e-9:
        return
    bx = _SWATCH / 2.0 + base[0] * unit
    by = _SWATCH / 2.0 - base[1] * unit          # screen y grows downward
    reach = _SWATCH * 1.5
    step = math.hypot(step_x, step_y)
    count = min(int(reach / step) + 2 if step else 0, limit)
    pattern = [d * unit for d in dashes] if dashes else None
    for k in range(-count, count + 1):
        ox, oy = bx + k * step_x, by - k * step_y
        if pattern:
            _draw_dashed(p, ox, oy, ca, -sa, pattern, reach)
        else:
            p.drawLine(QPointF(ox - ca * reach, oy + sa * reach),
                       QPointF(ox + ca * reach, oy - sa * reach))


def _draw_dashed(p: QPainter, ox: float, oy: float, dx: float, dy: float,
                 pattern, reach: float) -> None:
    """A line of dashes/gaps/dots along (dx, dy) through (ox, oy)."""
    period = sum(abs(v) for v in pattern)
    if period <= 0:
        p.drawLine(QPointF(ox - dx * reach, oy - dy * reach),
                   QPointF(ox + dx * reach, oy + dy * reach))
        return
    t = -reach
    # start on a period boundary so neighbouring lines stay in step
    t -= t % period
    while t < reach:
        for value in pattern:
            # a sub-pixel dash is invisible or, repeated thousands of
            # times, a black tile: give it something to draw
            length = max(abs(value), 1.0) if value else max(0.8, period * 0.02)
            if value > 0:
                p.drawLine(QPointF(ox + dx * t, oy + dy * t),
                           QPointF(ox + dx * (t + length),
                                   oy + dy * (t + length)))
            elif value == 0:
                p.drawPoint(QPointF(ox + dx * t, oy + dy * t))
            t += length
            if t >= reach:
                break


class HatchDialog(QDialog):
    # A curated common set floated to the top; the rest follow alphabetically.
    COMMON = ["SOLID", "ANSI31", "ANSI32", "ANSI33", "ANSI37", "NET",
              "LINE", "ANGLE", "EARTH", "GRAVEL", "AR-CONC", "DOTS",
              "GRASS", "BRICK", "HONEY", "SQUARE"]

    def __init__(self, parent, settings: dict) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Hatch"))
        self.setMinimumWidth(360)

        self.gallery = QListWidget(self)
        self.gallery.setViewMode(QListWidget.IconMode)
        self.gallery.setIconSize(QSize(_SWATCH, _SWATCH))
        self.gallery.setResizeMode(QListWidget.Adjust)
        self.gallery.setMovement(QListWidget.Static)
        self.gallery.setSpacing(4)
        self.gallery.setMinimumHeight(260)
        # A GRID, not a row of boxes as wide as their names. Left to itself
        # an icon view sizes every cell to its own label, so a palette that
        # holds both TRANS and V_MASONRY300x150 comes out ragged -- Marco:
        # "en la ventana de hatch está desordenado". A fixed cell, uniform
        # sizes and centred, wrapping labels line the swatches up in columns
        # the way AutoCAD's pattern palette does.
        self.gallery.setGridSize(QSize(_CELL_W, _CELL_H))
        self.gallery.setUniformItemSizes(True)
        self.gallery.setWordWrap(True)
        # V_MASONRY200x100 and V_MASONRY300x150 differ in their tail: elide
        # the middle, or six cells read "V_MASONR..." and mean nothing.
        self.gallery.setTextElideMode(Qt.ElideMiddle)

        # AutoCAD's palette splits the predefined patterns into tabs: ANSI,
        # ISO and Other Predefined. With 172 of them, that is the difference
        # between choosing and hunting.
        self.category = QComboBox(self)
        for label, key in ((tr("Common"), "COMMON"), (tr("All"), "ALL"),
                           ("ANSI", "ANSI"), ("ISO", "ISO"),
                           (tr("Other predefined"), "OTHER")):
            self.category.addItem(label, key)
        self.category.currentIndexChanged.connect(self._fill_gallery)

        self._current_pattern = settings.get("pattern", "SOLID").upper()
        start = "COMMON" if self._current_pattern in self.COMMON else "ALL"
        self.category.setCurrentIndex(self.category.findData(start))
        self._fill_gallery()

        self.angle = QDoubleSpinBox(self)
        self.angle.setRange(-360, 360)
        self.angle.setValue(settings.get("angle", 0.0))
        self.scale = QDoubleSpinBox(self)
        self.scale.setRange(0.0001, 100000)
        self.scale.setDecimals(4)
        self.scale.setValue(settings.get("scale", 1.0))

        from views.layers_panel import fill_color_combo
        self.color = QComboBox(self)
        fill_color_combo(self.color)
        idx = self.color.findData(settings.get("color", 256))
        self.color.setCurrentIndex(idx if idx >= 0 else 0)

        form = QFormLayout()
        form.addRow(tr("Angle"), self.angle)
        form.addRow(tr("Scale"), self.scale)
        form.addRow(tr("Color"), self.color)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel(tr("Pattern:"), self))
        top.addStretch(1)
        top.addWidget(QLabel(tr("Category:"), self))
        top.addWidget(self.category)
        layout.addLayout(top)
        layout.addWidget(self.gallery, 1)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _names_for(self, key: str) -> list:
        every = actions.hatch_pattern_names()
        if key == "COMMON":
            return [n for n in self.COMMON if n == "SOLID" or n in every]
        if key == "ANSI":
            return [n for n in every if n.startswith("ANSI")]
        if key == "ISO":
            return [n for n in every if n.startswith(("ACAD_ISO", "ISO"))]
        if key == "OTHER":
            return [n for n in every
                    if not n.startswith(("ANSI", "ACAD_ISO", "ISO"))]
        return ["SOLID"] + [n for n in every if n != "SOLID"]

    def _fill_gallery(self) -> None:
        key = self.category.currentData() or "ALL"
        chosen = self._current_pattern
        self.gallery.clear()
        for name in self._names_for(key):
            item = QListWidgetItem(QIcon(_pattern_pixmap(name)), name)
            item.setData(Qt.UserRole, name)
            item.setToolTip(name)          # the cell may wrap a long one
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            item.setSizeHint(QSize(_CELL_W, _CELL_H))
            self.gallery.addItem(item)
            if name == chosen:
                self.gallery.setCurrentItem(item)
        if self.gallery.currentRow() < 0 and self.gallery.count():
            self.gallery.setCurrentRow(0)
        self.gallery.currentItemChanged.connect(self._remember)

    def _remember(self, current, _previous) -> None:
        if current is not None:
            self._current_pattern = current.data(Qt.UserRole)

    def settings(self) -> dict:
        item = self.gallery.currentItem()
        pattern = item.data(Qt.UserRole) if item else "SOLID"
        return {
            "pattern": pattern,
            "angle": self.angle.value(),
            "scale": self.scale.value(),
            "color": self.color.currentData(),
        }
