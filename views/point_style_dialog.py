# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""DDPTYPE: AutoCAD's Point Style dialog (#69).

Twenty point shapes in four rows of five, the point size, and whether that
size is relative to the screen (a percentage of the view) or in absolute
drawing units. The values are $PDMODE and $PDSIZE (core.points).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QRadioButton,
    QToolButton,
    QVBoxLayout,
)

from core import points
from core.i18n import tr

_ICON = 40


def point_icon(mode: int, color) -> QIcon:
    """The symbol PDMODE ``mode`` draws, as the dialog shows it."""
    pixmap = QPixmap(_ICON, _ICON)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(color, 1.6))
    c = QPointF(_ICON / 2, _ICON / 2)
    r = _ICON * 0.3
    shape = mode & 7
    if shape == 0:
        painter.setBrush(color)
        painter.drawEllipse(c, 1.8, 1.8)
        painter.setBrush(Qt.BrushStyle.NoBrush)
    elif shape == 2:
        painter.drawLine(QPointF(c.x() - r, c.y()), QPointF(c.x() + r, c.y()))
        painter.drawLine(QPointF(c.x(), c.y() - r), QPointF(c.x(), c.y() + r))
    elif shape == 3:
        d = r * 0.75
        painter.drawLine(QPointF(c.x() - d, c.y() - d), QPointF(c.x() + d, c.y() + d))
        painter.drawLine(QPointF(c.x() - d, c.y() + d), QPointF(c.x() + d, c.y() - d))
    elif shape == 4:
        painter.drawLine(c, QPointF(c.x(), c.y() - r * 0.6))
    if mode & 32:
        painter.drawEllipse(c, r * 0.6, r * 0.6)
    if mode & 64:
        painter.drawRect(QRectF(c.x() - r * 0.6, c.y() - r * 0.6, r * 1.2, r * 1.2))
    painter.end()
    return QIcon(pixmap)


class PointStyleDialog(QDialog):
    def __init__(self, parent, doc) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Point Style"))
        layout = QVBoxLayout(self)
        grid = QGridLayout()
        self.shapes = QButtonGroup(self)
        self.shapes.setExclusive(True)
        color = self.palette().text().color()
        current = points.pdmode(doc)
        for i, mode in enumerate(points.MODES):
            button = QToolButton(self)
            button.setCheckable(True)
            button.setIcon(point_icon(mode, color))
            button.setIconSize(QSize(_ICON, _ICON))
            button.setChecked(mode == current)
            self.shapes.addButton(button, mode)
            grid.addWidget(button, i // 5, i % 5)
        layout.addLayout(grid)

        form = QFormLayout()
        self.size = QDoubleSpinBox(self)
        self.size.setDecimals(4)
        self.size.setRange(0.0, 1e9)
        size = points.pdsize(doc)
        self.relative = QRadioButton(tr("Set Size Relative to Screen"), self)
        self.absolute = QRadioButton(tr("Set Size in Absolute Units"), self)
        if size > 0:
            self.absolute.setChecked(True)
            self.size.setValue(size)
        else:
            self.relative.setChecked(True)
            self.size.setValue(5.0 if size == 0 else -size)
        self.relative.toggled.connect(self._update_suffix)
        form.addRow(tr("Point Size:"), self.size)
        layout.addLayout(form)
        layout.addWidget(self.relative)
        layout.addWidget(self.absolute)
        self._update_suffix()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _update_suffix(self) -> None:
        self.size.setSuffix(" %" if self.relative.isChecked() else "")

    def values(self) -> tuple[int, float]:
        """($PDMODE, $PDSIZE): a relative size is stored negative."""
        mode = self.shapes.checkedId()
        size = self.size.value()
        if self.relative.isChecked():
            size = -size
        return (mode if mode in points.MODES else 0), size
