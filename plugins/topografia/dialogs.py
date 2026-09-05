# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The import options: column order, label choice and text height, with a
preview of the first points so a wrong order is seen before it lands."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from core.i18n import tr

from .actions import LabelStyle
from .points import ORDERS, parse_points

PREVIEW_ROWS = 5


class ImportOptionsDialog(QDialog):
    def __init__(self, parent, text: str, order: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Import points"))
        self._text = text
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.order_box = QComboBox(self)
        for name in ORDERS:
            self.order_box.addItem(name, name)
        self.order_box.setCurrentIndex(max(0, list(ORDERS).index(order)))
        form.addRow(tr("Column order:"), self.order_box)

        self.height = QDoubleSpinBox(self)
        self.height.setRange(0.001, 10000.0)
        self.height.setDecimals(3)
        self.height.setValue(1.0)
        form.addRow(tr("Text height:"), self.height)

        labels = QHBoxLayout()
        self.number = QCheckBox(tr("Number"), self)
        self.elevation = QCheckBox(tr("Elevation"), self)
        self.description = QCheckBox(tr("Description"), self)
        for box in (self.number, self.elevation, self.description):
            box.setChecked(True)
            labels.addWidget(box)
        form.addRow(tr("Labels:"), labels)

        self.decimals = QSpinBox(self)
        self.decimals.setRange(0, 6)
        self.decimals.setValue(2)
        form.addRow(tr("Elevation decimals:"), self.decimals)

        self.preview = QLabel(self)
        self.preview.setTextFormat(0)          # plain text
        layout.addWidget(self.preview)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.order_box.currentIndexChanged.connect(lambda _i: self._refresh())
        self._refresh()

    def order(self) -> str:
        return str(self.order_box.currentData())

    def style(self) -> LabelStyle:
        chosen = tuple(kind for kind, box in (("number", self.number),
                                              ("elevation", self.elevation),
                                              ("description", self.description))
                       if box.isChecked())
        return LabelStyle(text_height=float(self.height.value()), labels=chosen,
                          decimals=int(self.decimals.value()))

    def _refresh(self) -> None:
        try:
            points = parse_points(self._text, self.order())
        except ValueError:
            self.preview.setText(tr("No points parse with this order."))
            return
        lines = [tr("Preview (first {n} of {total}):",
                    n=min(PREVIEW_ROWS, len(points)), total=len(points))]
        for p in points[:PREVIEW_ROWS]:
            lines.append(f"{p.name}   N={p.north:.3f}   E={p.east:.3f}   "
                         f"Z={p.z:.3f}   {p.desc}")
        self.preview.setText("\n".join(lines))
