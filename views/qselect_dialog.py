# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Quick Select dialog (p. 1585), control for control."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
)

from core import qselect
from core.i18n import tr


class QuickSelectDialog(QDialog):
    def __init__(self, parent, document, selection: list) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Quick Select"))
        self.document = document
        self._selection = list(selection)
        root = QVBoxLayout(self)
        form = QFormLayout()

        self.apply_to = QComboBox(self)
        self.apply_to.addItem(tr("Entire drawing"), "drawing")
        if self._selection:
            self.apply_to.addItem(tr("Current selection"), "selection")
            self.apply_to.setCurrentIndex(1)
        self.apply_to.currentIndexChanged.connect(lambda *_: self._fill_types())
        form.addRow(tr("Apply to:"), self.apply_to)

        self.object_type = QComboBox(self)
        self.object_type.currentIndexChanged.connect(
            lambda *_: self._fill_properties())
        form.addRow(tr("Object type:"), self.object_type)

        self.property = QComboBox(self)
        self.property.currentIndexChanged.connect(
            lambda *_: self._fill_operators())
        form.addRow(tr("Properties:"), self.property)

        self.operator = QComboBox(self)
        self.operator.currentIndexChanged.connect(lambda *_: self._sync_value())
        form.addRow(tr("Operator:"), self.operator)

        self.value = QLineEdit(self)
        form.addRow(tr("Value:"), self.value)
        root.addLayout(form)

        box = QGroupBox(tr("How to apply"), self)
        inner = QVBoxLayout(box)
        self.include = QRadioButton(tr("Include in new selection set"), box)
        self.include.setChecked(True)
        self.exclude = QRadioButton(tr("Exclude from new selection set"), box)
        inner.addWidget(self.include)
        inner.addWidget(self.exclude)
        root.addWidget(box)

        self.append = QRadioButton(tr("Append to current selection set"), self)
        self.append.setAutoExclusive(False)
        root.addWidget(self.append)

        self.summary = QLabel("", self)
        self.summary.setStyleSheet("color: #9aa0a6;")
        root.addWidget(self.summary)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
                                   self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._fill_types()
        self.resize(420, 380)

    # -- the dependent combos -------------------------------------------------
    def _pool(self) -> list:
        if self.apply_to.currentData() == "selection" and self._selection:
            return self._selection
        return list(self.document.modelspace())

    def _fill_types(self) -> None:
        self.object_type.blockSignals(True)
        self.object_type.clear()
        # "If the filtering criteria are being applied to the entire drawing,
        # the Object Type list includes all object types. Otherwise, the list
        # includes only the object types of the selected objects." (p. 1585)
        self.object_type.addItem(tr("Multiple"), None)
        for kind in qselect.object_types(self._pool()):
            self.object_type.addItem(kind.title(), kind)
        if self.object_type.count() == 2:
            self.object_type.setCurrentIndex(1)
        self.object_type.blockSignals(False)
        self._fill_properties()

    def _fill_properties(self) -> None:
        self.property.blockSignals(True)
        self.property.clear()
        for key, label, kind in qselect.properties_for(
                self.object_type.currentData()):
            self.property.addItem(tr(label), (key, kind))
        self.property.blockSignals(False)
        self._fill_operators()

    def _fill_operators(self) -> None:
        data = self.property.currentData()
        kind = data[1] if data else "text"
        self.operator.blockSignals(True)
        self.operator.clear()
        for op in qselect.operators_for(kind):
            self.operator.addItem(tr(qselect.operator_label(op)), op)
        self.operator.blockSignals(False)
        self._sync_value()

    def _sync_value(self) -> None:
        select_all = self.operator.currentData() == qselect.SELECT_ALL
        self.value.setEnabled(not select_all)
        self.summary.setText(
            tr("Select All ignores the value and takes every object of the "
               "chosen type.") if select_all else "")

    # -- the result -----------------------------------------------------------
    def result_entities(self) -> list:
        data = self.property.currentData() or ("layer", "text")
        return qselect.select(self._pool(), self.object_type.currentData(),
                              data[0], self.operator.currentData(),
                              self.value.text(), data[1],
                              exclude=self.exclude.isChecked())

    def append_to_selection(self) -> bool:
        return self.append.isChecked()
