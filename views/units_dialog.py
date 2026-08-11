# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""UNITS — AutoCAD's Drawing Units dialog.

The groups and their wording come from the Command Reference (Drawing Units
Dialog Box, p.2001, and Direction Control, p.2003): Length type/precision,
Angle type/precision plus Clockwise, Insertion scale, a live Sample Output,
and the Direction… button. The Lighting group is not here — it sets the unit
for photometric lights, and IngeCAD does not render.

Values land in the DXF header ($LUNITS/$LUPREC/$AUNITS/$AUPREC/$INSUNITS/
$ANGDIR/$ANGBASE), which is where AutoCAD keeps them, so they survive the
round trip whether or not we act on them.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from core import units as units_mod
from core.i18n import tr
from core.units import Units

# Length types in the order the dialog lists them (alphabetical, as AutoCAD).
_LENGTH_TYPES = [
    (units_mod.ARCHITECTURAL, "Architectural"),
    (units_mod.DECIMAL, "Decimal"),
    (units_mod.ENGINEERING, "Engineering"),
    (units_mod.FRACTIONAL, "Fractional"),
    (units_mod.SCIENTIFIC, "Scientific"),
]

_ANGLE_TYPES = [
    (units_mod.DEG, "Decimal Degrees"),
    (units_mod.DEG_MIN_SEC, "Deg/Min/Sec"),
    (units_mod.GRADS, "Grads"),
    (units_mod.RADIANS, "Radians"),
    (units_mod.SURVEYOR, "Surveyor's Units"),
]

# What "Units to scale inserted content" offers. Unitless first, like AutoCAD,
# then the metric ladder a civil drawing actually uses, then the imperial ones.
_INSUNITS = [0, 4, 5, 14, 6, 7, 1, 2, 10, 3]

# The sample value AutoCAD shows in Sample Output.
_SAMPLE_LENGTH = 1.5
_SAMPLE_ANGLE = 45.0


class DirectionControlDialog(QDialog):
    """Direction Control: which way is angle zero, from the same reference."""

    def __init__(self, parent, base_angle: float) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Direction Control"))
        box = QGroupBox(tr("Base Angle"))
        grid = QGridLayout(box)
        self._buttons = {}
        for row, (angle, label) in enumerate(
                ((0.0, tr("East")), (90.0, tr("North")),
                 (180.0, tr("West")), (270.0, tr("South")))):
            button = QRadioButton(f"{label}\t{angle:g}°")
            grid.addWidget(button, row, 0)
            self._buttons[angle] = button
        self._other = QRadioButton(tr("Other"))
        grid.addWidget(self._other, 4, 0)
        self._angle = QDoubleSpinBox()
        self._angle.setRange(-360.0, 360.0)
        self._angle.setDecimals(4)
        self._angle.setValue(float(base_angle))
        grid.addWidget(self._angle, 4, 1)

        if base_angle in self._buttons:
            self._buttons[base_angle].setChecked(True)
        else:
            self._other.setChecked(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(box)
        layout.addWidget(buttons)

    def base_angle(self) -> float:
        for angle, button in self._buttons.items():
            if button.isChecked():
                return angle
        return float(self._angle.value())


class UnitsDialog(QDialog):
    def __init__(self, window, units: Units, angdir: int = 0,
                 angbase: float = 0.0) -> None:
        super().__init__(window)
        self.setWindowTitle(tr("Drawing Units"))
        self._angbase = float(angbase)

        # -- Length ----------------------------------------------------------
        length_box = QGroupBox(tr("Length"))
        length_form = QFormLayout(length_box)
        self.length_type = QComboBox()
        for value, label in _LENGTH_TYPES:
            self.length_type.addItem(tr(label), value)
        self._select(self.length_type, units.lunits)
        self.length_precision = QComboBox()
        length_form.addRow(tr("Type:"), self.length_type)
        length_form.addRow(tr("Precision:"), self.length_precision)

        # -- Angle -----------------------------------------------------------
        angle_box = QGroupBox(tr("Angle"))
        angle_form = QFormLayout(angle_box)
        self.angle_type = QComboBox()
        for value, label in _ANGLE_TYPES:
            self.angle_type.addItem(tr(label), value)
        self._select(self.angle_type, units.aunits)
        self.angle_precision = QComboBox()
        for digits in range(0, 9):
            self.angle_precision.addItem(str(digits), digits)
        self._select(self.angle_precision, units.auprec)
        self.clockwise = QCheckBox(tr("Clockwise"))
        self.clockwise.setChecked(bool(angdir))
        angle_form.addRow(tr("Type:"), self.angle_type)
        angle_form.addRow(tr("Precision:"), self.angle_precision)
        angle_form.addRow("", self.clockwise)

        # -- Insertion scale --------------------------------------------------
        insert_box = QGroupBox(tr("Insertion scale"))
        insert_layout = QVBoxLayout(insert_box)
        insert_layout.addWidget(
            QLabel(tr("Units to scale inserted content:")))
        self.insunits = QComboBox()
        seen = list(_INSUNITS)
        if units.insunits not in seen:
            seen.append(units.insunits)
        for value in seen:
            self.insunits.addItem(
                tr(units_mod.INSUNIT_NAMES.get(value, "Unitless")), value)
        self._select(self.insunits, units.insunits)
        insert_layout.addWidget(self.insunits)

        # -- Sample output ----------------------------------------------------
        sample_box = QGroupBox(tr("Sample Output"))
        sample_layout = QVBoxLayout(sample_box)
        self.sample = QLabel()
        sample_layout.addWidget(self.sample)

        direction = QPushButton(tr("Direction..."))
        direction.clicked.connect(self._edit_direction)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(direction)
        bottom.addStretch(1)
        bottom.addWidget(buttons)

        layout = QVBoxLayout(self)
        layout.addWidget(length_box)
        layout.addWidget(angle_box)
        layout.addWidget(insert_box)
        layout.addWidget(sample_box)
        layout.addLayout(bottom)

        self.length_type.currentIndexChanged.connect(self._rebuild_precision)
        self.length_precision.currentIndexChanged.connect(self._update_sample)
        self.angle_type.currentIndexChanged.connect(self._update_sample)
        self.angle_precision.currentIndexChanged.connect(self._update_sample)
        self._rebuild_precision(preferred=units.luprec)

    # -- helpers ---------------------------------------------------------------
    @staticmethod
    def _select(combo: QComboBox, value) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _rebuild_precision(self, _index: int = -1, preferred: int | None = None) -> None:
        """Decimal formats count digits; fractional ones name the denominator.

        Same underlying $LUPREC either way — architectural precision 4 means
        1/16, which is 2**4 (-UNITS, p.2005).
        """
        if preferred is None:
            preferred = self.length_precision.currentData()
        if preferred is None:
            preferred = 4
        lunits = self.length_type.currentData()
        self.length_precision.blockSignals(True)
        self.length_precision.clear()
        if lunits in (units_mod.ARCHITECTURAL, units_mod.FRACTIONAL):
            for digits in range(0, 9):
                denominator = 2 ** digits
                self.length_precision.addItem(
                    "1" if digits == 0 else f"1/{denominator}", digits)
        else:
            for digits in range(0, 9):
                sample = "0" if digits == 0 else "0." + "0" * digits
                self.length_precision.addItem(sample, digits)
        self._select(self.length_precision, preferred)
        self.length_precision.blockSignals(False)
        self._update_sample()

    def _edit_direction(self) -> None:
        dialog = DirectionControlDialog(self, self._angbase)
        if dialog.exec():
            self._angbase = dialog.base_angle()
            self._update_sample()

    def _update_sample(self) -> None:
        units = self.values()
        self.sample.setText(
            f"{units.length(_SAMPLE_LENGTH)}\n{units.angle(_SAMPLE_ANGLE)}")

    # -- results ---------------------------------------------------------------
    def values(self) -> Units:
        return Units(
            lunits=self.length_type.currentData(),
            luprec=self.length_precision.currentData() or 0,
            aunits=self.angle_type.currentData(),
            auprec=self.angle_precision.currentData() or 0,
            insunits=self.insunits.currentData(),
        )

    def angdir(self) -> int:
        return 1 if self.clockwise.isChecked() else 0

    def angbase(self) -> float:
        return self._angbase
