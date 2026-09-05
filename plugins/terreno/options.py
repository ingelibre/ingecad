# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Options > Terrain: the defaults GEOREF proposes."""
from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
                               QSpinBox, QWidget)

from core.i18n import tr

from . import prefs


class TerrainOptionsPage(QWidget):
    """Built by the Options dialog with ``(dialog, window)``; its
    ``apply()`` runs with the other pages on OK and Apply."""

    def __init__(self, dialog, window) -> None:
        super().__init__(dialog)
        form = QFormLayout(self)
        self.zone = QSpinBox(self)
        self.zone.setRange(1, 60)
        self.zone.setValue(prefs.default_zone())
        form.addRow(tr("Default UTM zone:"), self.zone)
        self.hemisphere = QComboBox(self)
        self.hemisphere.addItem(tr("North"), "N")
        self.hemisphere.addItem(tr("South"), "S")
        self.hemisphere.setCurrentIndex(0 if prefs.default_northern() else 1)
        form.addRow(tr("Default hemisphere:"), self.hemisphere)
        row = QHBoxLayout()
        self.shift: list[QDoubleSpinBox] = []
        for value in prefs.default_shift():
            box = QDoubleSpinBox(self)
            box.setRange(-2000.0, 2000.0)
            box.setDecimals(3)
            box.setSuffix(" m")
            box.setValue(value)
            row.addWidget(box)
            self.shift.append(box)
        form.addRow(tr("PSAD56 to WGS84 shift (dX, dY, dZ):"), row)
        note = QLabel(tr("EPSG:1208 for Peru: -279, 175, -379 m (±16 m). "
                         "Older plans of Peru are in PSAD56; GPS and Google Earth use WGS84."))
        note.setWordWrap(True)
        form.addRow(note)

    def apply(self) -> None:
        prefs.save_defaults(self.zone.value(), self.hemisphere.currentData() == "N",
                            tuple(box.value() for box in self.shift))
