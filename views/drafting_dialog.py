# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Drafting Settings (DSETTINGS): Snap and Grid, Polar Tracking, Object Snap.

AutoCAD's dialog (reference p. 664), tab for tab, with what IngeCAD has an
answer for. It opens from Tools > Drafting Settings..., from the Settings
entry of the status-bar toggles' right-click menu (on the matching tab),
and from the object-snap dropdown as before.

The values it edits live where AutoCAD keeps them: GRIDUNIT, SNAPUNIT and
GRIDMAJOR in the drawing (its *Active VPORT, through an undoable Command),
the polar angles and the grid behaviour per user (see core.drafting).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core import drafting
from core.i18n import tr
from views.osnap_dialog import OsnapModesPanel

TAB_SNAP_GRID = 0
TAB_POLAR = 1
TAB_OSNAP = 2


class SnapGridPanel(QWidget):
    """Snap and Grid tab: spacings (in the drawing) and grid behaviour."""

    def __init__(self, parent, document, snap_on: bool, grid_on: bool) -> None:
        super().__init__(parent)
        drawing = document.doc if document is not None else None
        unit = drafting.grid_unit(drawing) if drawing is not None else 10.0
        snap = drafting.snap_unit(drawing) if drawing is not None else 0.0
        major = drafting.grid_major(drawing) if drawing is not None else 5

        self.snap_on = QCheckBox(tr("Snap On (F9)"))
        self.snap_on.setChecked(bool(snap_on))
        self.grid_on = QCheckBox(tr("Grid On (F7)"))
        self.grid_on.setChecked(bool(grid_on))

        def spin(value: float) -> QDoubleSpinBox:
            box = QDoubleSpinBox()
            box.setDecimals(4)
            box.setRange(0.0001, 1e9)
            box.setValue(value)
            return box

        snap_group = QGroupBox(tr("Snap spacing"))
        snap_form = QFormLayout(snap_group)
        self.snap_follows_grid = QCheckBox(
            tr("Snap follows the grid on screen (adaptive)"))
        self.snap_follows_grid.setChecked(snap <= 0.0)
        self.snap_spacing = spin(snap if snap > 0.0 else unit)
        self.snap_spacing.setEnabled(snap > 0.0)
        self.snap_follows_grid.toggled.connect(
            lambda on: self.snap_spacing.setEnabled(not on))
        snap_form.addRow(self.snap_follows_grid)
        snap_form.addRow(tr("Snap X spacing:"), self.snap_spacing)

        grid_group = QGroupBox(tr("Grid spacing"))
        grid_form = QFormLayout(grid_group)
        self.grid_spacing = spin(unit)
        grid_form.addRow(tr("Grid X spacing:"), self.grid_spacing)
        self.grid_major = QSpinBox()
        self.grid_major.setRange(2, 100)
        self.grid_major.setValue(major)
        grid_form.addRow(tr("Major line every:"), self.grid_major)

        behaviour = QGroupBox(tr("Grid behavior"))
        behaviour_layout = QVBoxLayout(behaviour)
        self.adaptive = QCheckBox(tr("Adaptive grid"))
        self.adaptive.setToolTip(
            tr("Limits the density of the grid when zoomed out."))
        self.adaptive.setChecked(drafting.grid_adaptive())
        self.subdivide = QCheckBox(tr("Allow subdivision below grid spacing"))
        self.subdivide.setToolTip(
            tr("Generates additional, more closely spaced grid lines when "
               "zoomed in, as many per major line as set above."))
        self.subdivide.setChecked(drafting.grid_subdivide())
        behaviour_layout.addWidget(self.adaptive)
        behaviour_layout.addWidget(self.subdivide)

        hint = QLabel(tr("Equal X and Y spacing. The grid spacing, the snap "
                         "spacing and the major-line frequency are saved in "
                         "the drawing, as AutoCAD does."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #9aa0a6;")

        top = QHBoxLayout()
        top.addWidget(self.snap_on)
        top.addWidget(self.grid_on)
        top.addStretch(1)
        columns = QHBoxLayout()
        columns.addWidget(snap_group, 1)
        columns.addWidget(grid_group, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top)
        layout.addLayout(columns)
        layout.addWidget(behaviour)
        layout.addWidget(hint)
        layout.addStretch(1)

    def values(self) -> dict:
        return {
            "snap_on": self.snap_on.isChecked(),
            "grid_on": self.grid_on.isChecked(),
            "grid": float(self.grid_spacing.value()),
            "snap": (0.0 if self.snap_follows_grid.isChecked()
                     else float(self.snap_spacing.value())),
            "major": int(self.grid_major.value()),
            "adaptive": self.adaptive.isChecked(),
            "subdivide": self.subdivide.isChecked(),
        }


class PolarPanel(QWidget):
    """Polar Tracking tab: increment, additional angles, tracking settings,
    angle measurement -- POLARANG, POLARADDANG, POLARMODE."""

    def __init__(self, parent, polar_on: bool) -> None:
        super().__init__(parent)
        mode = drafting.polar_mode()

        self.polar_on = QCheckBox(tr("Polar Tracking On (F10)"))
        self.polar_on.setChecked(bool(polar_on))

        angles = QGroupBox(tr("Polar Angle Settings"))
        angles_form = QFormLayout(angles)
        self.increment = QComboBox()
        self.increment.setEditable(True)
        for value in drafting.POLAR_INCREMENTS:
            self.increment.addItem(f"{value:g}", value)
        current = drafting.polar_increment()
        index = self.increment.findData(current)
        if index >= 0:
            self.increment.setCurrentIndex(index)
        else:
            self.increment.setEditText(f"{current:g}")
        angles_form.addRow(tr("Increment angle:"), self.increment)
        self.use_additional = QCheckBox(tr("Additional angles"))
        self.use_additional.setChecked(bool(mode & drafting.POLAR_ADDITIONAL))
        self.additional = QListWidget()
        self.additional.setMaximumHeight(90)
        for value in drafting.polar_additional():
            self.additional.addItem(f"{value:g}")
        self.additional.setEnabled(self.use_additional.isChecked())
        buttons = QVBoxLayout()
        self.new_button = QPushButton(tr("New"))
        self.delete_button = QPushButton(tr("Delete"))
        self.new_button.clicked.connect(self._new_angle)
        self.delete_button.clicked.connect(self._delete_angle)
        for b in (self.new_button, self.delete_button):
            b.setEnabled(self.use_additional.isChecked())
            buttons.addWidget(b)
        buttons.addStretch(1)
        self.use_additional.toggled.connect(self._toggle_additional)
        additional_row = QHBoxLayout()
        additional_row.addWidget(self.additional, 1)
        additional_row.addLayout(buttons)
        angles_form.addRow(self.use_additional)
        angles_form.addRow(additional_row)

        tracking = QGroupBox(tr("Object Snap Tracking Settings"))
        tracking_layout = QVBoxLayout(tracking)
        self.track_ortho = QRadioButton(tr("Track orthogonally only"))
        self.track_polar = QRadioButton(tr("Track using all polar angle settings"))
        (self.track_polar if mode & drafting.POLAR_OTRACK_ALL
         else self.track_ortho).setChecked(True)
        tracking_layout.addWidget(self.track_ortho)
        tracking_layout.addWidget(self.track_polar)

        measure = QGroupBox(tr("Polar Angle measurement"))
        measure_layout = QVBoxLayout(measure)
        self.absolute = QRadioButton(tr("Absolute"))
        self.relative = QRadioButton(tr("Relative to last segment"))
        (self.relative if mode & drafting.POLAR_RELATIVE
         else self.absolute).setChecked(True)
        measure_layout.addWidget(self.absolute)
        measure_layout.addWidget(self.relative)

        right = QVBoxLayout()
        right.addWidget(tracking)
        right.addWidget(measure)
        right.addStretch(1)
        columns = QHBoxLayout()
        columns.addWidget(angles, 1)
        columns.addLayout(right, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.polar_on)
        layout.addLayout(columns)
        layout.addStretch(1)

    def _toggle_additional(self, on: bool) -> None:
        self.additional.setEnabled(on)
        self.new_button.setEnabled(on)
        self.delete_button.setEnabled(on)

    def _new_angle(self) -> None:
        if self.additional.count() >= 10:
            return
        self.additional.addItem("0")
        item = self.additional.item(self.additional.count() - 1)
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        self.additional.setCurrentItem(item)
        self.additional.editItem(item)

    def _delete_angle(self) -> None:
        row = self.additional.currentRow()
        if row >= 0:
            self.additional.takeItem(row)

    def increment_value(self) -> float:
        data = self.increment.currentData()
        text = self.increment.currentText().strip().replace(",", ".")
        try:
            value = float(text)
        except ValueError:
            value = float(data) if data is not None else drafting.DEFAULT_POLAR_INCREMENT
        if not 0.0 < value <= 90.0:
            value = drafting.DEFAULT_POLAR_INCREMENT
        return value

    def additional_values(self) -> list[float]:
        texts = [self.additional.item(i).text()
                 for i in range(self.additional.count())]
        return drafting.parse_angles(";".join(texts))

    def mode_value(self) -> int:
        bits = 0
        if self.relative.isChecked():
            bits |= drafting.POLAR_RELATIVE
        if self.track_polar.isChecked():
            bits |= drafting.POLAR_OTRACK_ALL
        if self.use_additional.isChecked():
            bits |= drafting.POLAR_ADDITIONAL
        return bits


class DraftingSettingsDialog(QDialog):
    """DSETTINGS. ``apply`` is called with the dialog on OK; the window
    reads each panel and applies what changed."""

    def __init__(self, parent, document, *, osnap_modes, osnap_on: bool,
                 polar_on: bool, snap_on: bool, grid_on: bool,
                 tab: int = TAB_OSNAP) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Drafting Settings"))
        self.tabs = QTabWidget(self)
        self.snap_grid = SnapGridPanel(self, document, snap_on, grid_on)
        self.polar = PolarPanel(self, polar_on)
        self.panel = OsnapModesPanel(self, osnap_modes, osnap_on)
        self.tabs.addTab(self.snap_grid, tr("Snap and Grid"))
        self.tabs.addTab(self.polar, tr("Polar Tracking"))
        self.tabs.addTab(self.panel, tr("Object Snap"))
        self.tabs.setCurrentIndex(tab)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(buttons)

    # the Object Snap API the dropdown and the tests have always used
    def modes(self) -> set:
        return self.panel.modes()

    def osnap_on(self) -> bool:
        return self.panel.osnap_on()
