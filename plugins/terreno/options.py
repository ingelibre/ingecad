# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Options > Terrain: the defaults GEOREF proposes."""
from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QSpinBox, QWidget)

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
        # the DEM (G2)
        source = prefs.dem_source()
        self.dem_url = QLineEdit(self)
        self.dem_url.setText(source.url_template)
        self.dem_url.setPlaceholderText("https://.../{z}/{x}/{y}.png")
        form.addRow(tr("DEM tiles URL ({z}/{x}/{y}):"), self.dem_url)
        self.dem_encoding = QComboBox(self)
        self.dem_encoding.addItem("Terrarium (AWS Terrain Tiles)", "terrarium")
        self.dem_encoding.addItem("Mapbox Terrain-RGB", "mapbox")
        self.dem_encoding.setCurrentIndex(max(0, self.dem_encoding.findData(source.encoding)))
        form.addRow(tr("DEM encoding:"), self.dem_encoding)
        self.dem_zoom = QSpinBox(self)
        self.dem_zoom.setRange(8, 15)
        self.dem_zoom.setValue(prefs.dem_zoom())
        form.addRow(tr("DEM zoom level (13 = about 18 m per pixel):"), self.dem_zoom)
        dem_note = QLabel(tr("AWS Terrain Tiles need no key; the data is a 30 m DEM (SRTM and others), "
                             "for preliminary design only. Tiles are kept in the cache folder."))
        dem_note.setWordWrap(True)
        form.addRow(dem_note)

    def apply(self) -> None:
        prefs.save_defaults(self.zone.value(), self.hemisphere.currentData() == "N",
                            tuple(box.value() for box in self.shift))
        prefs.save_dem(self.dem_url.text(), self.dem_encoding.currentData(), self.dem_zoom.value())
