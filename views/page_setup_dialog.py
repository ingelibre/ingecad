# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""PAGESETUP dialog — paper size, orientation and margins of one layout.

Everything in mm (all PLOTSETTINGS lengths are stored in mm anyway). On
accept the caller applies the values through core.layouts.page_setup_command,
which writes the DXF fields directly — the layout's viewports are never
touched (ezdxf's own page_setup() would destroy them).
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from core import layouts as layout_ops
from core.i18n import tr

_CUSTOM = "custom"


class PageSetupDialog(QDialog):
    def __init__(self, window, layout) -> None:
        super().__init__(window)
        self.setWindowTitle(tr("Page Setup — {name}", name=layout.name))
        self.setMinimumWidth(340)
        form = QFormLayout(self)

        current = layout_ops.effective_page(layout)
        cur_w, cur_h = current["width"], current["height"]
        landscape = cur_w >= cur_h
        portrait_dims = (min(cur_w, cur_h), max(cur_w, cur_h))

        self.paper = QComboBox(self)
        match_index = None
        for i, (name, w, h) in enumerate(layout_ops.PAPER_SIZES):
            self.paper.addItem(f"{name}  ({w:g} × {h:g} mm)", (name, w, h))
            if abs(w - portrait_dims[0]) < 0.5 and abs(h - portrait_dims[1]) < 0.5:
                match_index = i
        self.paper.addItem(tr("Custom..."), _CUSTOM)
        self.paper.setCurrentIndex(
            match_index if match_index is not None else self.paper.count() - 1)
        self.paper.currentIndexChanged.connect(self._on_paper_changed)

        self.orientation = QComboBox(self)
        self.orientation.addItem(tr("Landscape"), True)
        self.orientation.addItem(tr("Portrait"), False)
        self.orientation.setCurrentIndex(0 if landscape else 1)

        def mm_spin(value, maximum=5000.0):
            spin = QDoubleSpinBox(self)
            spin.setRange(0.0, maximum)
            spin.setDecimals(1)
            spin.setSuffix(" mm")
            spin.setValue(value)
            return spin

        # Custom size row (enabled only for Custom): portrait dims.
        self.custom_w = mm_spin(portrait_dims[0])
        self.custom_h = mm_spin(portrait_dims[1])
        size_row = QWidget(self)
        size_lay = QHBoxLayout(size_row)
        size_lay.setContentsMargins(0, 0, 0, 0)
        size_lay.addWidget(self.custom_w)
        size_lay.addWidget(QLabel("×", self))
        size_lay.addWidget(self.custom_h)

        m_top, m_right, m_bottom, m_left = current["margins"]
        self.margin_top = mm_spin(max(m_top, 0.0), 200.0)
        self.margin_right = mm_spin(max(m_right, 0.0), 200.0)
        self.margin_bottom = mm_spin(max(m_bottom, 0.0), 200.0)
        self.margin_left = mm_spin(max(m_left, 0.0), 200.0)
        margins_row = QWidget(self)
        margins_lay = QHBoxLayout(margins_row)
        margins_lay.setContentsMargins(0, 0, 0, 0)
        for label, spin in ((tr("T"), self.margin_top), (tr("R"), self.margin_right),
                            (tr("B"), self.margin_bottom), (tr("L"), self.margin_left)):
            margins_lay.addWidget(QLabel(label, self))
            margins_lay.addWidget(spin)

        form.addRow(tr("Paper size"), self.paper)
        form.addRow(tr("Size"), size_row)
        form.addRow(tr("Orientation"), self.orientation)
        form.addRow(tr("Margins"), margins_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self._on_paper_changed()

    def _on_paper_changed(self) -> None:
        data = self.paper.currentData()
        is_custom = data == _CUSTOM
        self.custom_w.setEnabled(is_custom)
        self.custom_h.setEnabled(is_custom)
        if not is_custom:
            _name, w, h = data
            self.custom_w.setValue(w)
            self.custom_h.setValue(h)

    def values(self) -> tuple:
        """(width, height, (top, right, bottom, left), size_name) — width and
        height already carry the chosen orientation."""
        data = self.paper.currentData()
        if data == _CUSTOM:
            name = ""
            w, h = self.custom_w.value(), self.custom_h.value()
        else:
            name, w, h = data
        if self.orientation.currentData():
            w, h = max(w, h), min(w, h)          # landscape
        else:
            w, h = min(w, h), max(w, h)          # portrait
        margins = (self.margin_top.value(), self.margin_right.value(),
                   self.margin_bottom.value(), self.margin_left.value())
        return w, h, margins, name
