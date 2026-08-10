# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""PAGESETUP dialog — AutoCAD's Page Setup, group by group.

Two columns like the classic dialog: Printer/plotter, Paper size, Plot
area and Plot offset on the left; Plot scale, Plot style table, Shaded
viewport options, Plot options and Drawing orientation on the right.
Every group maps to its real PLOTSETTINGS fields, so a colleague's page
setup round-trips even for settings IngeCAD does not act on yet (CTB
rendering, shaded viewports). On accept the caller applies the values via
core.layouts.page_setup_command, which writes the DXF fields directly —
the layout's viewports are never touched (ezdxf's own page_setup() would
destroy them).
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QSpinBox,
    QWidget,
)

from core import layouts as layout_ops
from core.i18n import tr

_CUSTOM = "custom"

# The metric scale list AutoCAD shows (plus enlargements). (num, den).
_SCALES = [(1, 1), (1, 2), (1, 4), (1, 5), (1, 8), (1, 10), (1, 16),
           (1, 20), (1, 25), (1, 30), (1, 40), (1, 50), (1, 100),
           (1, 200), (1, 500), (1, 1000), (2, 1), (4, 1), (10, 1)]

_STYLE_SHEETS = ["", "monochrome.ctb", "acad.ctb", "Grayscale.ctb",
                 "Screening 100%.ctb"]


def _scale_text(num, den):
    return f"{num:g}:{den:g}"


class PageSetupDialog(QDialog):
    def __init__(self, window, layout) -> None:
        super().__init__(window)
        self.setWindowTitle(tr("Page Setup — {name}", name=layout.name))
        self.setMinimumWidth(680)
        dxf = layout.dxf

        current = layout_ops.effective_page(layout)
        cur_w, cur_h = current["width"], current["height"]
        landscape = cur_w >= cur_h
        portrait_dims = (min(cur_w, cur_h), max(cur_w, cur_h))
        try:
            rotation = int(dxf.get("plot_rotation", 0) or 0) % 4
        except (TypeError, ValueError):
            rotation = 0
        try:
            flags = int(dxf.get_default("plot_layout_flags"))
        except Exception:
            flags = int(dxf.get("plot_layout_flags", 0) or 0)

        def mm_spin(value, lo=0.0, hi=5000.0):
            spin = QDoubleSpinBox(self)
            spin.setRange(lo, hi)
            spin.setDecimals(1)
            spin.setSuffix(" mm")
            spin.setValue(value)
            return spin

        grid = QGridLayout(self)

        # -- Printer/plotter ---------------------------------------------------
        printer_group = QGroupBox(tr("Printer/plotter"), self)
        printer_form = QFormLayout(printer_group)
        self.device = QComboBox(self)
        self.device.addItem(tr("None"), "")
        self.device.addItem("DWG To PDF.pc3", "DWG To PDF.pc3")
        current_device = str(dxf.get("plot_configuration_file", "") or "")
        if current_device and self.device.findData(current_device) < 0:
            # a colleague's plotter name: keep it selectable, never lose it
            self.device.addItem(current_device, current_device)
        self.device.setCurrentIndex(max(0, self.device.findData(current_device)))
        printer_form.addRow(tr("Name:"), self.device)

        # -- Paper size --------------------------------------------------------
        paper_group = QGroupBox(tr("Paper size"), self)
        paper_form = QFormLayout(paper_group)
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
        paper_form.addRow(self.paper)

        self.custom_w = mm_spin(portrait_dims[0])
        self.custom_h = mm_spin(portrait_dims[1])
        size_row = QWidget(self)
        size_lay = QHBoxLayout(size_row)
        size_lay.setContentsMargins(0, 0, 0, 0)
        size_lay.addWidget(self.custom_w)
        size_lay.addWidget(QLabel("×", self))
        size_lay.addWidget(self.custom_h)
        paper_form.addRow(tr("Size:"), size_row)

        m_top, m_right, m_bottom, m_left = current["margins"]
        self.margin_top = mm_spin(max(m_top, 0.0), hi=200.0)
        self.margin_right = mm_spin(max(m_right, 0.0), hi=200.0)
        self.margin_bottom = mm_spin(max(m_bottom, 0.0), hi=200.0)
        self.margin_left = mm_spin(max(m_left, 0.0), hi=200.0)
        margins_row = QWidget(self)
        margins_lay = QHBoxLayout(margins_row)
        margins_lay.setContentsMargins(0, 0, 0, 0)
        for label, spin in ((tr("T"), self.margin_top), (tr("R"), self.margin_right),
                            (tr("B"), self.margin_bottom), (tr("L"), self.margin_left)):
            margins_lay.addWidget(QLabel(label, self))
            margins_lay.addWidget(spin)
        paper_form.addRow(tr("Printable margins:"), margins_row)

        # -- Plot area ---------------------------------------------------------
        area_group = QGroupBox(tr("Plot area"), self)
        area_form = QFormLayout(area_group)
        self.area = QComboBox(self)
        self.area.addItem(tr("Layout"), layout_ops.PLOT_TYPE_LAYOUT)
        self.area.addItem(tr("Extents"), layout_ops.PLOT_TYPE_EXTENTS)
        self.area.addItem(tr("Display"), layout_ops.PLOT_TYPE_DISPLAY)
        try:
            plot_type = int(dxf.get("plot_type", 5) or 5)
        except (TypeError, ValueError):
            plot_type = 5
        idx = self.area.findData(plot_type)
        self.area.setCurrentIndex(idx if idx >= 0 else 0)
        self.area.currentIndexChanged.connect(self._on_area_changed)
        area_form.addRow(tr("What to plot:"), self.area)

        # -- Plot offset -------------------------------------------------------
        offset_group = QGroupBox(tr("Plot offset (origin set to printable area)"), self)
        offset_form = QFormLayout(offset_group)
        try:
            off_x = float(dxf.get("plot_origin_x_offset", 0.0) or 0.0)
            off_y = float(dxf.get("plot_origin_y_offset", 0.0) or 0.0)
        except (TypeError, ValueError):
            off_x = off_y = 0.0
        self.offset_x = mm_spin(off_x, lo=-5000.0)
        self.offset_y = mm_spin(off_y, lo=-5000.0)
        self.center_plot = QCheckBox(tr("Center the plot"), self)
        self.center_plot.setChecked(bool(flags & layout_ops.FLAG_PLOT_CENTERED))
        offset_form.addRow("X:", self.offset_x)
        offset_form.addRow("Y:", self.offset_y)
        offset_form.addRow(self.center_plot)

        # -- Plot scale --------------------------------------------------------
        scale_group = QGroupBox(tr("Plot scale"), self)
        scale_form = QFormLayout(scale_group)
        try:
            std_type = int(dxf.get("standard_scale_type", 16) or 0)
        except (TypeError, ValueError):
            std_type = 16
        self.fit_to_paper = QCheckBox(tr("Fit to paper"), self)
        self.fit_to_paper.setChecked(std_type == 0)
        self.fit_to_paper.toggled.connect(self._on_fit_toggled)
        self.scale = QComboBox(self)
        for num, den in _SCALES:
            self.scale.addItem(_scale_text(num, den), (num, den))
        self.scale.addItem(tr("Custom"), _CUSTOM)
        try:
            num = float(dxf.get("scale_numerator", 1.0) or 1.0)
            den = float(dxf.get("scale_denominator", 1.0) or 1.0)
        except (TypeError, ValueError):
            num = den = 1.0
        # manual match: Qt's findData compares QVariants and misses tuples
        idx = -1
        if num == int(num) and den == int(den):
            for i in range(self.scale.count()):
                if self.scale.itemData(i) == (int(num), int(den)):
                    idx = i
                    break
        self.scale.setCurrentIndex(idx if idx >= 0 else self.scale.count() - 1)
        self.scale.currentIndexChanged.connect(self._on_scale_changed)
        self.scale_num = mm_spin(num)
        self.scale_num.setSuffix(" mm")
        self.scale_den = QDoubleSpinBox(self)
        self.scale_den.setRange(0.001, 1e6)
        self.scale_den.setDecimals(3)
        self.scale_den.setValue(den)
        custom_row = QWidget(self)
        custom_lay = QHBoxLayout(custom_row)
        custom_lay.setContentsMargins(0, 0, 0, 0)
        custom_lay.addWidget(self.scale_num)
        custom_lay.addWidget(QLabel("=", self))
        custom_lay.addWidget(self.scale_den)
        custom_lay.addWidget(QLabel(tr("units"), self))
        self.scale_lineweights = QCheckBox(tr("Scale lineweights"), self)
        self.scale_lineweights.setChecked(
            bool(flags & layout_ops.FLAG_SCALE_LINEWEIGHTS))
        scale_form.addRow(self.fit_to_paper)
        scale_form.addRow(tr("Scale:"), self.scale)
        scale_form.addRow(custom_row)
        scale_form.addRow(self.scale_lineweights)

        # -- Plot style table --------------------------------------------------
        style_group = QGroupBox(tr("Plot style table (pen assignments)"), self)
        style_form = QFormLayout(style_group)
        self.style_sheet = QComboBox(self)
        self.style_sheet.setEditable(True)
        self.style_sheet.addItem(tr("None"), "")
        for name in _STYLE_SHEETS[1:]:
            self.style_sheet.addItem(name, name)
        current_style = str(dxf.get("current_style_sheet", "") or "")
        idx = self.style_sheet.findData(current_style)
        if idx >= 0:
            self.style_sheet.setCurrentIndex(idx)
        else:
            self.style_sheet.addItem(current_style, current_style)
            self.style_sheet.setCurrentIndex(self.style_sheet.count() - 1)
        style_form.addRow(self.style_sheet)

        # -- Shaded viewport options ------------------------------------------
        shade_group = QGroupBox(tr("Shaded viewport options"), self)
        shade_form = QFormLayout(shade_group)
        self.shade_plot = QComboBox(self)
        for label, code in ((tr("As displayed"), 0), (tr("Wireframe"), 1),
                            (tr("Hidden"), 2)):
            self.shade_plot.addItem(label, code)
        try:
            self.shade_plot.setCurrentIndex(max(0, self.shade_plot.findData(
                int(dxf.get("shade_plot_mode", 0) or 0))))
        except (TypeError, ValueError):
            pass
        self.shade_quality = QComboBox(self)
        for label, code in ((tr("Draft"), 0), (tr("Preview"), 1),
                            (tr("Normal"), 2), (tr("Presentation"), 3),
                            (tr("Maximum"), 4)):
            self.shade_quality.addItem(label, code)
        try:
            idx = self.shade_quality.findData(
                int(dxf.get("shade_plot_resolution_level", 2) or 2))
        except (TypeError, ValueError):
            idx = -1
        self.shade_quality.setCurrentIndex(idx if idx >= 0 else 2)
        self.shade_dpi = QSpinBox(self)
        self.shade_dpi.setRange(72, 4800)
        try:
            self.shade_dpi.setValue(int(dxf.get("shade_plot_custom_dpi", 300) or 300))
        except (TypeError, ValueError):
            self.shade_dpi.setValue(300)
        shade_form.addRow(tr("Shade plot:"), self.shade_plot)
        shade_form.addRow(tr("Quality:"), self.shade_quality)
        shade_form.addRow(tr("DPI:"), self.shade_dpi)

        # -- Plot options ------------------------------------------------------
        options_group = QGroupBox(tr("Plot options"), self)
        options_form = QFormLayout(options_group)
        self.plot_lineweights = QCheckBox(tr("Plot object lineweights"), self)
        self.plot_lineweights.setChecked(
            bool(flags & layout_ops.FLAG_PRINT_LINEWEIGHTS))
        self.plot_styles = QCheckBox(tr("Plot with plot styles"), self)
        self.plot_styles.setChecked(bool(flags & layout_ops.FLAG_PLOT_PLOTSTYLES))
        self.paperspace_last = QCheckBox(tr("Plot paperspace last"), self)
        self.paperspace_last.setChecked(
            bool(flags & layout_ops.FLAG_DRAW_VIEWPORTS_FIRST))
        self.hide_paperspace = QCheckBox(tr("Hide paperspace objects"), self)
        self.hide_paperspace.setChecked(bool(flags & layout_ops.FLAG_PLOT_HIDDEN))
        for box in (self.plot_lineweights, self.plot_styles,
                    self.paperspace_last, self.hide_paperspace):
            options_form.addRow(box)

        # -- Drawing orientation -----------------------------------------------
        orient_group = QGroupBox(tr("Drawing orientation"), self)
        orient_form = QFormLayout(orient_group)
        self.portrait = QRadioButton(tr("Portrait"), self)
        self.landscape = QRadioButton(tr("Landscape"), self)
        (self.landscape if landscape else self.portrait).setChecked(True)
        self.upside_down = QCheckBox(tr("Plot upside-down"), self)
        self.upside_down.setChecked(rotation in (2, 3))
        orient_form.addRow(self.portrait)
        orient_form.addRow(self.landscape)
        orient_form.addRow(self.upside_down)

        # legacy accessor kept for callers/tests that read orientation as a
        # combo-like object: currentData() -> landscape?
        self.orientation = _OrientationProxy(self)

        # -- assemble: two columns, AutoCAD order ------------------------------
        grid.addWidget(printer_group, 0, 0)
        grid.addWidget(paper_group, 1, 0)
        grid.addWidget(area_group, 2, 0)
        grid.addWidget(offset_group, 3, 0)
        grid.addWidget(scale_group, 0, 1, 2, 1)
        grid.addWidget(style_group, 2, 1)
        grid.addWidget(shade_group, 3, 1)
        grid.addWidget(options_group, 4, 0)
        grid.addWidget(orient_group, 4, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        grid.addWidget(buttons, 5, 0, 1, 2)

        self._on_paper_changed()
        self._on_area_changed()
        self._on_fit_toggled()
        self._on_scale_changed()

    # -- interactions ----------------------------------------------------------
    def _on_paper_changed(self) -> None:
        data = self.paper.currentData()
        is_custom = data == _CUSTOM
        self.custom_w.setEnabled(is_custom)
        self.custom_h.setEnabled(is_custom)
        if not is_custom:
            _name, w, h = data
            self.custom_w.setValue(w)
            self.custom_h.setValue(h)

    def _on_area_changed(self) -> None:
        # AutoCAD: "Center the plot" is disabled when plotting the Layout
        # (the sheet already sits at the origin).
        is_layout = self.area.currentData() == layout_ops.PLOT_TYPE_LAYOUT
        self.center_plot.setEnabled(not is_layout)

    def _on_fit_toggled(self) -> None:
        fit = self.fit_to_paper.isChecked()
        self.scale.setEnabled(not fit)
        self._on_scale_changed()

    def _on_scale_changed(self) -> None:
        fit = self.fit_to_paper.isChecked()
        is_custom = self.scale.currentData() == _CUSTOM
        self.scale_num.setEnabled(not fit and is_custom)
        self.scale_den.setEnabled(not fit and is_custom)
        if not is_custom and self.scale.currentData() is not None:
            num, den = self.scale.currentData()
            self.scale_num.setValue(num)
            self.scale_den.setValue(den)

    # -- result ---------------------------------------------------------------
    def values(self) -> dict:
        """Keyword arguments for core.layouts.page_setup_command."""
        data = self.paper.currentData()
        if data == _CUSTOM:
            name = ""
            w, h = self.custom_w.value(), self.custom_h.value()
        else:
            name, w, h = data
        if self.landscape.isChecked():
            w, h = max(w, h), min(w, h)
        else:
            w, h = min(w, h), max(w, h)
        return dict(
            width=w,
            height=h,
            margins=(self.margin_top.value(), self.margin_right.value(),
                     self.margin_bottom.value(), self.margin_left.value()),
            size_name=name,
            upside_down=self.upside_down.isChecked(),
            device=self.device.currentData(),
            plot_type=self.area.currentData(),
            offset=(self.offset_x.value(), self.offset_y.value()),
            centered=self.center_plot.isChecked(),
            fit_to_paper=self.fit_to_paper.isChecked(),
            scale=(self.scale_num.value(), self.scale_den.value()),
            scale_lineweights=self.scale_lineweights.isChecked(),
            style_sheet=(self.style_sheet.currentData()
                         if self.style_sheet.currentData() is not None
                         else self.style_sheet.currentText()),
            plot_lineweights=self.plot_lineweights.isChecked(),
            plot_styles=self.plot_styles.isChecked(),
            paperspace_last=self.paperspace_last.isChecked(),
            hide_paperspace=self.hide_paperspace.isChecked(),
            shade_plot=self.shade_plot.currentData(),
            shade_quality=self.shade_quality.currentData(),
            shade_dpi=self.shade_dpi.value(),
        )


class _OrientationProxy:
    """Backward-compatible view of the orientation radios (combo-like)."""

    def __init__(self, dialog: PageSetupDialog) -> None:
        self._dialog = dialog

    def currentData(self) -> bool:
        return self._dialog.landscape.isChecked()

    def setCurrentIndex(self, index: int) -> None:
        # 0 = landscape, 1 = portrait (same order the old combo used)
        (self._dialog.landscape if index == 0
         else self._dialog.portrait).setChecked(True)
