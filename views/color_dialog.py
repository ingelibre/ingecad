# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Select Color dialog — AutoCAD's Index Color tab.

The full 255-color ACI palette, laid out the way AutoCAD lays it: the big
10-249 grid, the nine standard colors, the six grays 250-255, and the
ByLayer / ByBlock buttons. True Color and Color Books are not offered.

It is also the ONE place the UI resolves an index: ``aci_qcolor`` (the
swatch colour), ``ACI_NAMES`` (the nine standard names), ``swatch_icon``
(the chip a combo shows) and the ByLayer / ByBlock sentinels. Every colour
combo, the layers table, the MTEXT editor and the toolbar ask here.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
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

#: The nine standard colours -- the ones every colour combo lists by name.
STANDARD_ACIS = tuple(range(1, 10))
ACI_NAMES = {
    1: "Red", 2: "Yellow", 3: "Green", 4: "Cyan", 5: "Blue",
    6: "Magenta", 7: "White", 8: "Gray", 9: "Light gray",
}


def aci_label(aci: int) -> str:
    """What a combo or the status line calls index ``aci``: the translated
    standard name for 1-9, "Color n" for the rest. Three places composed
    this on their own, and two of them disagreed on a 25 ("Color 25"
    against a bare "25")."""
    name = ACI_NAMES.get(aci)
    return tr(name) if name else tr("Color {n}", n=aci)


def aci_qcolor(aci: int) -> QColor:
    """What colour index ``aci`` looks like on a swatch: ezdxf's palette for
    1-255, a neutral grey chip for ByLayer, ByBlock and garbage.

    The one answer. The layers panel used to keep its own table of the nine
    standard colours and fall back here for the rest -- two answers for the
    same index. (What an ENTITY with ACI 7 draws as is a different
    question: it flips against the canvas, and the render context answers
    it.)
    """
    from ezdxf.colors import aci2rgb

    try:
        r, g, b = aci2rgb(aci)
    except (ValueError, IndexError):
        return QColor(160, 160, 160)
    return QColor(r, g, b)


def swatch_icon(index: int, size: int = 13) -> QIcon:
    """The colour chip a combo or a table shows next to an index."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.fillRect(1, 1, size - 2, size - 2, aci_qcolor(index))
    p.setPen(QPen(QColor(70, 70, 70)))
    p.drawRect(1, 1, size - 3, size - 3)
    p.end()
    return QIcon(pm)


class SelectColorDialog(QDialog):
    """Returns the picked ACI via ``result_aci()`` (256=ByLayer, 0=ByBlock)."""

    #: Side of one swatch of the 10-249 grid, in pixels. It was 16 and
    #: Marco asked for "un poco más grande, como 1.5x": aiming at a colour
    #: is the whole job of this dialog, and 24 px is about the size
    #: AutoCAD's Index Color tab gives them on a normal screen.
    SWATCH = 24
    #: The nine standard colours and the six greys, which get their own
    #: rows, keep their proportion to the grid.
    SWATCH_ROW = 32

    def __init__(self, parent=None, current: int | None = None,
                 include_bylayer: bool = True) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Select Color"))
        self._aci = current if current is not None else 7

        layout = QVBoxLayout(self)

        # The 10-249 grid, 24 columns like AutoCAD's Index Color tab.
        grid = QGridLayout()
        grid.setSpacing(2)
        for i, aci in enumerate(range(10, 250)):
            grid.addWidget(self._swatch(aci), i % 10, i // 10)
        layout.addLayout(grid)

        row = QHBoxLayout()
        row.setSpacing(2)
        row.addWidget(QLabel(tr("Standard:")))
        for aci in range(1, 10):
            row.addWidget(self._swatch(aci, size=self.SWATCH_ROW))
        row.addSpacing(10)
        row.addWidget(QLabel(tr("Grays:")))
        for aci in range(250, 256):
            row.addWidget(self._swatch(aci, size=self.SWATCH_ROW))
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
