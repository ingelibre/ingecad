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
_TILE_BG = QColor(232, 232, 232)
_TILE_FG = QColor(30, 30, 30)


def _pattern_pixmap(name: str) -> QPixmap:
    pm = QPixmap(_SWATCH, _SWATCH)
    pm.fill(_TILE_BG)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, False)
    p.setPen(QPen(_TILE_FG, 1))
    if name.upper() == "SOLID":
        p.fillRect(2, 2, _SWATCH - 4, _SWATCH - 4, _TILE_FG)
        p.end()
        return pm
    defn = actions._std_patterns().get(name.upper())
    if defn:
        for line in defn:
            angle = line[0]
            dashed = bool(line[3])
            _draw_family(p, _SWATCH, angle, _SWATCH / 4.0, dashed)
    else:
        p.drawLine(4, _SWATCH - 4, _SWATCH - 4, 4)
    p.end()
    return pm


def _draw_family(p: QPainter, size: int, angle_deg: float,
                 spacing: float, dashed: bool) -> None:
    ang = math.radians(angle_deg)
    dx, dy = math.cos(ang), math.sin(ang)
    nx, ny = -dy, dx                    # normal direction
    length = size * 1.6
    pen = QPen(_TILE_FG, 1)
    if dashed:
        pen.setStyle(Qt.DashLine)
    p.setPen(pen)
    k = -size
    cx0, cy0 = size / 2.0, size / 2.0
    while k <= 2 * size:
        cx, cy = cx0 + nx * (k - cx0), cy0 + ny * (k - cy0)
        p.drawLine(QPointF(cx - dx * length, cy - dy * length),
                   QPointF(cx + dx * length, cy + dy * length))
        k += spacing


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
        self.gallery.setMinimumHeight(220)

        names = list(self.COMMON)
        for n in actions.hatch_pattern_names():
            if n not in names:
                names.append(n)
        current = settings.get("pattern", "SOLID").upper()
        for n in names:
            it = QListWidgetItem(QIcon(_pattern_pixmap(n)), n)
            it.setData(Qt.UserRole, n)
            self.gallery.addItem(it)
            if n == current:
                self.gallery.setCurrentItem(it)
        if self.gallery.currentRow() < 0:
            self.gallery.setCurrentRow(0)

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
        lbl = QLabel(tr("Pattern:"), self)
        layout.addWidget(lbl)
        layout.addWidget(self.gallery, 1)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def settings(self) -> dict:
        item = self.gallery.currentItem()
        pattern = item.data(Qt.UserRole) if item else "SOLID"
        return {
            "pattern": pattern,
            "angle": self.angle.value(),
            "scale": self.scale.value(),
            "color": self.color.currentData(),
        }
