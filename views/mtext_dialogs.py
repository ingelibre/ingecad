# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The MTEXT editor's dialogs: Background Mask and Static Columns.

Both mirror the AutoCAD dialogs of the same names (Command Reference
pp. 1234 and 1232): the mask with its border offset factor (1.0–5.0, 1.5
default, "the value is based on the text height") and fill colour or
drawing-background choice; the columns with count, height and gutter —
the reference's default gutter is "five times the default mtext text
height".
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from core.i18n import tr


class BackgroundMaskDialog(QDialog):
    """Returns ("off",) or (aci | "canvas", scale) via ``result_bg``."""

    def __init__(self, parent, current) -> None:
        super().__init__(parent)
        from views.layers_panel import fill_color_combo

        self.setWindowTitle(tr("Background Mask"))
        self.use_mask = QCheckBox(tr("Use background mask"))

        self.offset = QDoubleSpinBox()
        self.offset.setRange(1.0, 5.0)
        self.offset.setSingleStep(0.1)
        self.offset.setValue(1.5)
        self.offset.setToolTip(
            tr("Border around the text, as a factor of the text height"))

        fill = QGroupBox(tr("Fill Color"))
        fill_layout = QVBoxLayout(fill)
        self.use_color = QRadioButton(tr("Color:"))
        self.use_color.setChecked(True)
        self.color = QComboBox()
        fill_color_combo(self.color, include_bylayer=False)
        self.use_canvas = QRadioButton(tr("Use drawing background color"))
        fill_layout.addWidget(self.use_color)
        fill_layout.addWidget(self.color)
        fill_layout.addWidget(self.use_canvas)

        form = QFormLayout()
        form.addRow(self.use_mask)
        form.addRow(tr("Border offset factor:"), self.offset)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(fill)
        layout.addWidget(buttons)

        if current and current[0] != "off":
            self.use_mask.setChecked(True)
            colour, scale = current
            self.offset.setValue(float(scale))
            if colour == "canvas":
                self.use_canvas.setChecked(True)
            else:
                index = self.color.findData(int(colour))
                if index >= 0:
                    self.color.setCurrentIndex(index)

    def result_bg(self) -> tuple:
        if not self.use_mask.isChecked():
            return ("off",)
        colour = "canvas" if self.use_canvas.isChecked() \
            else int(self.color.currentData() or 7)
        return (colour, float(self.offset.value()))


class StaticColumnsDialog(QDialog):
    """Returns (count, height, gutter) via ``result_columns``."""

    def __init__(self, parent, current, *, char_height: float,
                 width: float) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Column Settings"))

        self.count = QSpinBox()
        self.count.setRange(2, 20)
        self.count.setValue(3)

        self.height = QDoubleSpinBox()
        self.height.setRange(0.01, 1e6)
        self.height.setDecimals(2)
        # A workable default: the text's own box height is unknown here, so
        # offer ten lines of text.
        self.height.setValue(round(char_height * 10, 2))

        self.gutter = QDoubleSpinBox()
        self.gutter.setRange(0.0, 1e6)
        self.gutter.setDecimals(2)
        # "The gutter value is five times the default mtext text height."
        self.gutter.setValue(round(char_height * 5, 2))

        if current:
            count, height, gutter = current
            self.count.setValue(int(count))
            self.height.setValue(float(height))
            self.gutter.setValue(float(gutter))

        form = QFormLayout()
        form.addRow(tr("Column Number:"), self.count)
        form.addRow(tr("Height:"), self.height)
        form.addRow(tr("Gutter:"), self.gutter)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def result_columns(self) -> tuple:
        return (int(self.count.value()), float(self.height.value()),
                float(self.gutter.value()))
