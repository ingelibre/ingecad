# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Select Linetype, and Load or Reload Linetypes — AutoCAD's two dialogs.

The Linetype Manager lists what a drawing has loaded in three columns,
**Linetype / Appearance / Description** (reference p. 1045), and the
Appearance column is a *drawn sample* of the pattern: it is how a drafter
tells CENTER from PHANTOM without reading. The Load button brings in
definitions from the standard library, because a drawing can only use the
linetypes loaded into it.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from core import linetypes as lt_ops
from core.i18n import tr

SAMPLE_W = 150
SAMPLE_H = 16
#: Pixels per drawing unit in a sample. Chosen so the classic quarter-inch
#: family (HIDDEN 0.375 units) reads as dashes and CENTER (2.0) shows about
#: three periods, the way the manager's list looks in AutoCAD.
UNIT_PX = 26.0


def pattern_pixmap(pattern, width: int = SAMPLE_W, height: int = SAMPLE_H,
                   color: QColor | None = None) -> QPixmap:
    """The Appearance column: the dash pattern drawn as a line.

    ``pattern`` is a LIN definition's dashes -- positive is a dash, negative
    a gap, 0.0 a dot -- in drawing units. The swatch is drawn at a FIXED
    number of pixels per drawing unit, so CENTER, CENTER2 and CENTERX2 look
    like what they are: the same shape at half, one and twice the size.
    Normalising each pattern to the swatch instead -- the obvious way --
    draws all three identically, which is exactly the difference the
    Appearance column exists to show. A pattern too long for one period at
    that scale (the ISO ones run to 30 units) is shrunk to fit one.
    """
    pen_color = color or QColor(235, 235, 235)
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, False)
    painter.setPen(QPen(pen_color, 1.4))
    y = height / 2.0
    dashes = [d for d in pattern if d is not None]
    total = sum(abs(d) for d in dashes)
    if not dashes or total <= 0.0:
        painter.drawLine(2, int(y), width - 2, int(y))   # CONTINUOUS
        painter.end()
        return pixmap
    usable = width - 4
    unit = UNIT_PX
    if total * unit > usable:
        unit = usable / total      # one full period, for the long ISO ones
    x = 2.0
    while x < width - 2:
        for dash in dashes:
            length = abs(dash) * unit
            if dash > 0:
                painter.drawLine(int(x), int(y), int(min(x + length, width - 2)),
                                 int(y))
            elif dash == 0:
                painter.drawPoint(int(x), int(y))
                length = max(length, 1.5)
            x += length
            if x >= width - 2:
                break
    painter.end()
    return pixmap


class SelectLinetypeDialog(QDialog):
    """The loaded linetypes, with their samples. ``result_name()`` answers."""

    def __init__(self, parent, document, current: str | None = None,
                 include_bylayer: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Select Linetype"))
        self.document = document
        self._name = current
        self._include_bylayer = include_bylayer

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("Loaded linetypes")))
        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(
            [tr("Linetype"), tr("Appearance"), tr("Description")])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setIconSize(QSize(SAMPLE_W, SAMPLE_H))
        self.table.verticalHeader().setDefaultSectionSize(SAMPLE_H + 6)
        self.table.doubleClicked.connect(self._accept_row)
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        load = QPushButton(tr("Load..."), self)
        load.setToolTip(tr("Load linetype definitions into this drawing"))
        load.clicked.connect(self._load)
        buttons.addWidget(load)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
                               parent=self)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)
        self.resize(520, 420)
        self._fill()

    # -- contents --------------------------------------------------------------
    def _rows(self) -> list[str]:
        names = lt_ops.loaded_names(self.document)
        if self._include_bylayer:
            names = ["ByLayer", "ByBlock"] + names
        return names

    def _fill(self) -> None:
        names = self._rows()
        self.table.setRowCount(len(names))
        for row, name in enumerate(names):
            item = QTableWidgetItem(name)
            self.table.setItem(row, 0, item)
            sample = QTableWidgetItem()
            if name.lower() in ("bylayer", "byblock"):
                sample.setText("—")
            else:
                sample.setIcon(QIcon(pattern_pixmap(
                    lt_ops.pattern_of(self.document, name))))
            self.table.setItem(row, 1, sample)
            self.table.setItem(row, 2, QTableWidgetItem(
                lt_ops.description_of(self.document, name)))
            if self._name and name.lower() == self._name.lower():
                self.table.selectRow(row)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.resizeColumnToContents(0)
        self.table.setColumnWidth(1, SAMPLE_W + 12)
        if self.table.currentRow() < 0 and names:
            self.table.selectRow(0)

    def _accept_row(self, *_args) -> None:
        self.accept()

    def _load(self) -> None:
        dialog = LoadLinetypesDialog(self, self.document)
        if not dialog.exec():
            return
        names = dialog.result_names()
        if not names:
            return
        window = self.parent().window() if self.parent() else None
        history = getattr(window, "history", None)
        command = lt_ops.LoadLinetypesCommand(names)
        if history is not None:
            history.execute(command)
        else:
            command.do(self.document)
        self._name = names[0]
        self._fill()

    def result_name(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.text() if item else None


class LoadLinetypesDialog(QDialog):
    """Load or Reload Linetypes: pick definitions from the library.

    AutoCAD reads them from ``acad.lin`` and lets you select several at
    once; ours come from :mod:`core.linetypes`, which says where each
    definition was taken from.
    """

    def __init__(self, parent, document) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Load or Reload Linetypes"))
        self.document = document

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("Available linetypes")))
        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(
            [tr("Linetype"), tr("Appearance"), tr("Description")])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setIconSize(QSize(SAMPLE_W, SAMPLE_H))
        self.table.verticalHeader().setDefaultSectionSize(SAMPLE_H + 6)
        layout.addWidget(self.table)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
                               parent=self)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)
        self.resize(520, 460)

        names = lt_ops.loadable_names(document)
        catalog = lt_ops.library()
        self.table.setRowCount(len(names))
        for row, name in enumerate(names):
            description, pattern = catalog[name.upper()]
            self.table.setItem(row, 0, QTableWidgetItem(name))
            sample = QTableWidgetItem()
            sample.setIcon(QIcon(pattern_pixmap(list(pattern))))
            self.table.setItem(row, 1, sample)
            self.table.setItem(row, 2, QTableWidgetItem(description))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        # ACAD_ISO02W100 is 14 characters: size the name column to the names
        # it holds instead of cutting them, once, after the rows are in.
        self.table.resizeColumnToContents(0)
        self.table.setColumnWidth(1, SAMPLE_W + 12)

    def result_names(self) -> list[str]:
        rows = {index.row() for index in self.table.selectedIndexes()}
        return [self.table.item(row, 0).text() for row in sorted(rows)]
