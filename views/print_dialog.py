# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""PLOT dialog — paper, orientation, area, scale; PDF or system printer.

Kept to what a civil plan needs: pick the paper, plot the extents, the
current view or a window picked on the drawing, at Fit or a real 1:N metric
scale (drawing unit metres or millimetres), then save a vector PDF or send
to a printer.

Window (#52) works as AutoCAD's does: "Window <" closes the dialog, two
corners are picked on the drawing, and the dialog comes back with every
setting as it was and the window as the area. The dialog returns
:data:`PICK_WINDOW` and its :meth:`PrintDialog.state`; the main window
runs the pick and reopens it with that state.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from core.i18n import tr
from views import file_dialogs
from formats import pdf_out

#: exec() result: the user asked to pick a window on the drawing.
PICK_WINDOW = 2


class PrintDialog(QDialog):
    def __init__(self, window, state: dict | None = None) -> None:
        super().__init__(window)
        self._window_rect = None
        self.window = window
        self.setWindowTitle(tr("Plot"))
        self.setMinimumWidth(320)
        form = QFormLayout(self)

        self.paper = QComboBox(self)
        self.paper.addItems(list(pdf_out.PAPER_SIZES_MM))
        self.orientation = QComboBox(self)
        self.orientation.addItem(tr("Landscape"), True)
        self.orientation.addItem(tr("Portrait"), False)
        self.area = QComboBox(self)
        self._layout_name = getattr(window, "_active_layout", "Model")
        is_layout_tab = (self._layout_name != "Model"
                         and window.document is not None)
        if is_layout_tab:
            # AutoCAD's contract: a layout plots at 1:1 — the sheet maps
            # mm-to-mm and every viewport prints at its exact scale.
            self.area.addItem(tr("Layout (sheet at 1:1)"), "layout")
        self.area.addItem(tr("Extents"), "extents")
        self.area.addItem(tr("Current view"), "view")
        self.area.addItem(tr("Window"), "window")
        self.pick_btn = QPushButton(tr("Window <"), self)
        self.pick_btn.setToolTip(tr("Pick two corners of the area to plot"))
        self.pick_btn.clicked.connect(self._pick_window)
        self.area.currentIndexChanged.connect(self._on_area_changed)
        from core import units as unit_info

        self.scale = QComboBox(self)
        self.scale.addItem(tr("Fit to paper"), None)
        for num, den in unit_info.STANDARD_SCALES:
            self.scale.addItem(unit_info.scale_text(num, den), (num, den))
        # AutoCAD's custom scale: "1000 mm = 25 units" (PLOT, Plot Scale)
        self.scale.addItem(tr("Custom"), "custom")
        self.custom_mm = QDoubleSpinBox(self)
        self.custom_units = QDoubleSpinBox(self)
        for spin, value in ((self.custom_mm, 1.0), (self.custom_units, 1.0)):
            spin.setDecimals(6)
            spin.setRange(1e-6, 1e9)
            spin.setValue(value)
            spin.valueChanged.connect(self._show_meaning)
        custom = QWidget(self)
        row = QHBoxLayout(custom)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.custom_mm)
        row.addWidget(QLabel(tr("mm ="), self))
        row.addWidget(self.custom_units)
        row.addWidget(QLabel(tr("units"), self))
        self._custom_row = custom
        # What one drawing unit is, in mm: the drawing's own $INSUNITS
        # picks it (#68: a millimetre plan opened on Meters, so 1:100
        # plotted a thousand times too small); unitless stays on Meters,
        # what a survey plan without $INSUNITS almost always is.
        self.units = QComboBox(self)
        for name, mm in (("Millimeters", 1.0), ("Centimeters", 10.0),
                         ("Meters", 1000.0), ("Inches", 25.4), ("Feet", 304.8)):
            self.units.addItem(tr(name), mm)
        drawing_mm = 1000.0
        if is_layout_tab:
            # a layout is drawn in paper units, whatever the model's
            sheet = window.document.doc.layouts.get(self._layout_name)
            inches = int(sheet.dxf.get("plot_paper_units", 1) or 0) == 0
            drawing_mm = 25.4 if inches else 1.0
        elif window.document is not None:
            code = unit_info.insunits(window.document.doc)
            if code:
                drawing_mm = unit_info.MM_PER_INSUNIT.get(code, 1000.0)
        idx = self.units.findData(drawing_mm)
        self.units.setCurrentIndex(idx if idx >= 0 else 2)
        # AutoCAD's reading of a scale: "1 mm = 100 units"
        self.meaning = QLabel(self)
        self.scale.currentIndexChanged.connect(self._show_meaning)
        self.units.currentIndexChanged.connect(self._show_meaning)

        # Plot style table (pen assignments): the layout's own by default,
        # as the Page Setup left it; the folder's tables to choose from.
        from core import plotstyles

        self.style = QComboBox(self)
        self.style.addItem(tr("None"), "")
        for name in plotstyles.available():
            self.style.addItem(name, name)
        current = ""
        if window.document is not None:
            try:
                layout = (window.document.doc.layouts.get(self._layout_name)
                          if self._layout_name != "Model"
                          else window.document.doc.modelspace())
                current = str(layout.dxf_layout.dxf.get("current_style_sheet", "") or "")
            except Exception:                # noqa: BLE001 - no table then
                current = ""
        idx = self.style.findData(current)
        if idx < 0 and current:
            self.style.addItem(current, current)
            idx = self.style.count() - 1
        self.style.setCurrentIndex(max(idx, 0))

        form.addRow(tr("Paper size"), self.paper)
        form.addRow(tr("Orientation"), self.orientation)
        form.addRow(tr("Plot area"), self.area)
        form.addRow("", self.pick_btn)
        form.addRow(tr("Plot scale"), self.scale)
        form.addRow("", self._custom_row)
        form.addRow(tr("Drawing unit"), self.units)
        form.addRow("", self.meaning)
        form.addRow(tr("Plot style table"), self.style)
        # "Plot object lineweights", on by default as in AutoCAD
        self.lineweights = QCheckBox(tr("Plot object lineweights"), self)
        self.lineweights.setChecked(True)
        form.addRow("", self.lineweights)
        self.scale.currentIndexChanged.connect(self._on_scale_changed)

        buttons = QDialogButtonBox(self)
        preview_btn = QPushButton(tr("Preview..."), self)
        preview_btn.clicked.connect(self._preview)
        buttons.addButton(preview_btn, QDialogButtonBox.ActionRole)
        self._preview_btn = preview_btn
        pdf_btn = QPushButton(tr("Save PDF..."), self)
        printer_btn = QPushButton(tr("Print..."), self)
        buttons.addButton(pdf_btn, QDialogButtonBox.AcceptRole)
        buttons.addButton(printer_btn, QDialogButtonBox.ActionRole)
        buttons.addButton(QDialogButtonBox.Cancel)
        buttons.rejected.connect(self.reject)
        pdf_btn.clicked.connect(self._to_pdf)
        printer_btn.clicked.connect(self._to_printer)
        form.addRow(buttons)
        self._pdf_btn, self._printer_btn = pdf_btn, printer_btn
        if state:
            self._restore(state)
        elif is_layout_tab:
            self._from_page_setup(
                window.document.doc.layouts.get(self._layout_name))
        elif window.document is not None:
            self._from_page_setup(window.document.doc.modelspace())
        self._on_area_changed()
        self._on_scale_changed()
        self._show_meaning()

    def _on_scale_changed(self) -> None:
        self._custom_row.setVisible(self.scale.currentData() == "custom")
        self._show_meaning()

    def _show_meaning(self) -> None:
        """AutoCAD's reading of the scale: what one paper millimetre holds
        (1:100 on a millimetre plan: 1 mm = 100 millimeters)."""
        mm = self._mm_per_unit()
        self.meaning.setText("" if mm is None else tr(
            "1 mm on paper = {n:g} {unit}", n=1.0 / mm,
            unit=self.units.currentText().lower()))

    # -- Window: leave, pick, come back -----------------------------------------
    def state(self) -> dict:
        """Everything the user set, to reopen the dialog as it was."""
        return {"paper": self.paper.currentIndex(),
                "orientation": self.orientation.currentIndex(),
                "area": self.area.currentData(),
                "scale": self.scale.currentIndex(),
                "units": self.units.currentIndex(),
                "style": self.style.currentIndex(),
                "custom": (self.custom_mm.value(), self.custom_units.value()),
                "lineweights": self.lineweights.isChecked(),
                "window": self._window_rect}

    def _restore(self, state: dict) -> None:
        for combo, key in ((self.paper, "paper"), (self.orientation, "orientation"),
                           (self.scale, "scale"), (self.units, "units"),
                           (self.style, "style")):
            if state.get(key) is not None and 0 <= state[key] < combo.count():
                combo.setCurrentIndex(state[key])
        if state.get("custom"):
            self.custom_mm.setValue(state["custom"][0])
            self.custom_units.setValue(state["custom"][1])
        if state.get("lineweights") is not None:
            self.lineweights.setChecked(bool(state["lineweights"]))
        self._window_rect = state.get("window")
        idx = self.area.findData(state.get("area"))
        if idx >= 0:
            self.area.setCurrentIndex(idx)

    def _from_page_setup(self, layout) -> None:
        """Start from the tab's page setup (PAGESETUP there), as AutoCAD's
        Plot dialog does: paper, orientation, area and scale. A layout used
        to open on A4 landscape whatever its own sheet."""
        from core import layouts as layout_ops
        from core.layouts import FLAG_USE_STANDARD_SCALE, PLOT_TYPE_DISPLAY, \
            PLOT_TYPE_EXTENTS, PLOT_TYPE_LAYOUT

        dxf = layout.dxf
        if not dxf.hasattr("paper_width"):
            return                              # never set up: the defaults
        page = layout_ops.effective_page(layout)
        width, height = page["width"], page["height"]
        short, long_ = sorted((width, height))
        for i, (w, h) in enumerate(pdf_out.PAPER_SIZES_MM.values()):
            if abs(w - short) < 0.5 and abs(h - long_) < 0.5:
                self.paper.setCurrentIndex(i)
                break
        self.orientation.setCurrentIndex(self.orientation.findData(width >= height))
        area = {PLOT_TYPE_EXTENTS: "extents", PLOT_TYPE_DISPLAY: "view",
                PLOT_TYPE_LAYOUT: "layout"}.get(int(dxf.get("plot_type", 1) or 0))
        if area is not None and self.area.findData(area) >= 0:
            self.area.setCurrentIndex(self.area.findData(area))
        flags = int(dxf.get("plot_layout_flags", 0) or 0)
        if flags & FLAG_USE_STANDARD_SCALE and int(dxf.get("standard_scale_type", 0) or 0) == 0:
            self.scale.setCurrentIndex(0)       # scaled to fit
            return
        try:
            target = float(dxf.get("scale_numerator", 1.0)) / float(
                dxf.get("scale_denominator", 1.0))
        except (TypeError, ValueError, ZeroDivisionError):
            return
        # "1 mm = N units" is paper mm per drawing unit: find it in the list
        # for the drawing unit already chosen
        for i in range(1, self.scale.count()):
            ratio = self.scale.itemData(i)
            if not isinstance(ratio, tuple):
                continue                        # "Custom": no ratio to compare
            num, den = ratio
            if abs(self.units.currentData() * num / den - target) <= 1e-9 * max(target, 1.0):
                self.scale.setCurrentIndex(i)
                return
        # not in the list (1:37, 1000 mm = 25 units...): the page setup's own
        # ratio as the custom scale. Reaching "Custom" in the loop above used
        # to raise, and PLOT in such a layout opened nothing at all.
        self.custom_mm.setValue(float(dxf.get("scale_numerator", 1.0)))
        self.custom_units.setValue(float(dxf.get("scale_denominator", 1.0)))
        self.scale.setCurrentIndex(self.scale.findData("custom"))

    def _pick_window(self) -> None:
        idx = self.area.findData("window")
        self.area.setCurrentIndex(idx)
        self.done(PICK_WINDOW)

    # -- plot parameters -------------------------------------------------------
    def _layout_mode(self) -> bool:
        return self.area.currentData() == "layout"

    def _on_area_changed(self) -> None:
        # In layout mode paper/orientation/scale come from the page setup.
        manual = not self._layout_mode()
        for widget in (self.paper, self.orientation, self.scale, self.units):
            widget.setEnabled(manual)
        # Window: nothing to plot until a window has been picked
        window_area = self.area.currentData() == "window"
        self.pick_btn.setVisible(window_area)
        ready = not window_area or self._window_rect is not None
        self._pdf_btn.setEnabled(ready)
        self._printer_btn.setEnabled(ready)
        self._preview_btn.setEnabled(ready)

    def _mm_per_unit(self):
        """Paper mm per drawing unit; None to fit the page."""
        ratio = self.scale.currentData()
        if ratio is None:
            return None                         # fit
        if ratio == "custom":
            # paper mm per drawing unit, as typed: 1000 mm = 25 units is
            # 1:25 on a drawing in metres, whatever the unit list says
            return self.custom_mm.value() / self.custom_units.value()
        num, den = ratio
        return self.units.currentData() * num / den

    def _area_rect(self):
        if self.area.currentData() == "view":
            return self.window.viewport._view_world_rect()
        if self.area.currentData() == "window":
            return self._window_rect
        return None                             # extents

    def _ctb(self) -> str:
        return self.style.currentData() or ""

    def _plot_on(self, printer) -> None:
        if self._layout_mode():
            pdf_out.plot_layout(self.window.document, printer,
                                self._layout_name, ctb=self._ctb())
            return
        pdf_out.plot(
            self.window.document, printer,
            layout_name=getattr(self.window, "_active_layout", None),
            area=self._area_rect(),
            mm_per_unit=self._mm_per_unit(), ctb=self._ctb(),
            lineweights=self.lineweights.isChecked())

    def _preview(self) -> None:
        """Preview: the plot as it will come out, in the system's PDF viewer
        (a temporary file; nothing is saved next to the drawing)."""
        import tempfile

        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        handle, path = tempfile.mkstemp(prefix="ingecad-preview-",
                                        suffix=".pdf")
        import os

        os.close(handle)
        if self._layout_mode():
            (width, height), _sheet = pdf_out.layout_sheet(
                self.window.document, self._layout_name)
            printer = pdf_out.make_pdf_printer_mm(path, width, height)
        else:
            printer = pdf_out.make_pdf_printer(
                path, self.paper.currentText(),
                landscape=self.orientation.currentData())
        self._plot_on(printer)
        self.last_preview = path
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # -- outputs ---------------------------------------------------------------
    def _to_pdf(self) -> None:
        name = self.window.document.name if self.window.document else "plano"
        path, _f = file_dialogs.get_save_file(
            self, tr("Save PDF"), f"{Path(name).stem}.pdf", "PDF (*.pdf)",
            preferred=self.window.document.path if self.window.document else None)
        if not path:
            return
        if self._layout_mode():
            (width, height), _sheet = pdf_out.layout_sheet(
                self.window.document, self._layout_name)
            printer = pdf_out.make_pdf_printer_mm(path, width, height)
        else:
            printer = pdf_out.make_pdf_printer(
                path, self.paper.currentText(),
                landscape=self.orientation.currentData())
        self._plot_on(printer)
        self.window.command_line.echo(tr("PDF saved: {p}", p=path))
        self.accept()

    def _to_printer(self) -> None:
        from PySide6.QtGui import QPageLayout, QPageSize
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter

        printer = QPrinter(QPrinter.HighResolution)
        if self._layout_mode():
            from PySide6.QtCore import QSizeF

            (width, height), _sheet = pdf_out.layout_sheet(
                self.window.document, self._layout_name)
            printer.setPageSize(QPageSize(QSizeF(width, height),
                                          QPageSize.Millimeter))
        else:
            size_id = getattr(QPageSize, self.paper.currentText(), QPageSize.A4)
            printer.setPageSize(QPageSize(size_id))
            printer.setPageOrientation(
                QPageLayout.Landscape if self.orientation.currentData()
                else QPageLayout.Portrait)
        dlg = QPrintDialog(printer, self)
        if dlg.exec():
            self._plot_on(printer)
            self.accept()
