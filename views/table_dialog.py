# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Insert Table dialog — the Command Reference's fields, simplified to
what IngeCAD's plain-geometry tables use: columns, column width, data rows,
row height, text height, optional title and header texts."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from core.i18n import tr


class InsertTableDialog(QDialog):
    def __init__(self, parent, char_height: float = 2.5) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Insert Table"))

        self.columns = QSpinBox()
        self.columns.setRange(1, 100)
        self.columns.setValue(5)

        self.col_width = QDoubleSpinBox()
        self.col_width.setRange(0.01, 1e6)
        self.col_width.setDecimals(2)
        self.col_width.setValue(round(char_height * 10, 2))

        self.data_rows = QSpinBox()
        self.data_rows.setRange(1, 1000)
        self.data_rows.setValue(10)

        self.row_height = QDoubleSpinBox()
        self.row_height.setRange(0.01, 1e6)
        self.row_height.setDecimals(2)
        # One line plus the cell margins, like the default table style.
        self.row_height.setValue(round(char_height * 1.8, 2))

        self.text_height = QDoubleSpinBox()
        self.text_height.setRange(0.01, 1e6)
        self.text_height.setDecimals(2)
        self.text_height.setValue(round(char_height, 2))

        self.with_title = QCheckBox(tr("Title row"))
        self.with_title.setChecked(True)
        self.title = QLineEdit()
        self.title.setPlaceholderText(tr("Title"))
        self.with_header = QCheckBox(tr("Header row"))
        self.with_header.setChecked(True)

        form = QFormLayout()
        form.addRow(tr("Columns:"), self.columns)
        form.addRow(tr("Column width:"), self.col_width)
        form.addRow(tr("Data rows:"), self.data_rows)
        form.addRow(tr("Row height:"), self.row_height)
        form.addRow(tr("Text height:"), self.text_height)
        form.addRow(self.with_title, self.title)
        form.addRow(self.with_header)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def result_table(self) -> dict:
        return {
            "cols": int(self.columns.value()),
            "col_width": float(self.col_width.value()),
            "data_rows": int(self.data_rows.value()),
            "row_height": float(self.row_height.value()),
            "text_height": float(self.text_height.value()),
            "title": (self.title.text() or tr("Title")) \
                if self.with_title.isChecked() else "",
            "headers": [""] if self.with_header.isChecked() else None,
        }
