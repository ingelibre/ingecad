# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Select Color dialog — AutoCAD's Index Color tab.

The full 255-color ACI palette, laid out the way AutoCAD lays it: the big
10-249 grid, the nine standard colors, the six grays 250-255, and the
ByLayer / ByBlock buttons. True Color and Color Books are not offered.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from core.i18n import tr

BYLAYER = 256
BYBLOCK = 0


def aci_qcolor(aci: int) -> QColor:
    from ezdxf.colors import aci2rgb

    try:
        r, g, b = aci2rgb(aci)
    except (ValueError, IndexError):
        return QColor(160, 160, 160)
    return QColor(r, g, b)


class SelectColorDialog(QDialog):
    """Returns the picked ACI via ``result_aci()`` (256=ByLayer, 0=ByBlock)."""

    SWATCH = 16

    def __init__(self, parent=None, current: int | None = None,
                 include_bylayer: bool = True) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Select Color"))
        self._aci = current if current is not None else 7

        layout = QVBoxLayout(self)

        # The 10-249 grid, 24 columns like AutoCAD's Index Color tab.
        grid = QGridLayout()
        grid.setSpacing(1)
        for i, aci in enumerate(range(10, 250)):
            grid.addWidget(self._swatch(aci), i % 10, i // 10)
        layout.addLayout(grid)

        row = QHBoxLayout()
        row.setSpacing(2)
        row.addWidget(QLabel(tr("Standard:")))
        for aci in range(1, 10):
            row.addWidget(self._swatch(aci, size=22))
        row.addSpacing(10)
        row.addWidget(QLabel(tr("Grays:")))
        for aci in range(250, 256):
            row.addWidget(self._swatch(aci, size=22))
        row.addStretch(1)
        layout.addLayout(row)

        special = QHBoxLayout()
        if include_bylayer:
            bylayer = QPushButton(tr("ByLayer"))
            bylayer.clicked.connect(lambda: self._pick(BYLAYER))
            special.addWidget(bylayer)
            byblock = QPushButton(tr("ByBlock"))
            byblock.clicked.connect(lambda: self._pick(BYBLOCK))
            special.addWidget(byblock)
        self._label = QLabel()
        special.addStretch(1)
        special.addWidget(self._label)
        layout.addLayout(special)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_label()

    def _swatch(self, aci: int, size: int | None = None) -> QPushButton:
        side = size or self.SWATCH
        button = QPushButton()
        button.setFixedSize(side, side)
        button.setToolTip(tr("Color {n}", n=aci))
        color = aci_qcolor(aci)
        button.setStyleSheet(
            f"background: rgb({color.red()},{color.green()},{color.blue()});"
            "border: 1px solid #333;")
        button.clicked.connect(lambda _=False, a=aci: self._pick(a))
        return button

    def _pick(self, aci: int) -> None:
        self._aci = aci
        self._update_label()

    def _update_label(self) -> None:
        if self._aci == BYLAYER:
            name = tr("ByLayer")
        elif self._aci == BYBLOCK:
            name = tr("ByBlock")
        else:
            name = tr("Color {n}", n=self._aci)
        self._label.setText(name)

    def result_aci(self) -> int:
        return self._aci
