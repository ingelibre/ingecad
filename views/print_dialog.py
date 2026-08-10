# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""PLOT dialog — paper, orientation, area, scale; PDF or system printer.

Kept to what a civil plan needs: pick the paper, plot the extents or the
current view, at Fit or a real 1:N metric scale (drawing unit metres or
millimetres), then save a vector PDF or send to a printer.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QPushButton,
)

from core.i18n import tr
from formats import pdf_out


class PrintDialog(QDialog):
    def __init__(self, window) -> None:
        super().__init__(window)
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
        self.area.currentIndexChanged.connect(self._on_area_changed)
        self.scale = QComboBox(self)
        self.scale.addItem(tr("Fit to paper"), None)
        for n in pdf_out.COMMON_SCALES:
            self.scale.addItem(f"1:{n}", n)
        self.units = QComboBox(self)
        self.units.addItem(tr("Meters"), 1000.0)       # 1 unit = 1000 mm
        self.units.addItem(tr("Millimeters"), 1.0)

        form.addRow(tr("Paper size"), self.paper)
        form.addRow(tr("Orientation"), self.orientation)
        form.addRow(tr("Plot area"), self.area)
        form.addRow(tr("Scale"), self.scale)
        form.addRow(tr("Drawing unit"), self.units)

        buttons = QDialogButtonBox(self)
        pdf_btn = QPushButton(tr("Save PDF..."), self)
        printer_btn = QPushButton(tr("Print..."), self)
        buttons.addButton(pdf_btn, QDialogButtonBox.AcceptRole)
        buttons.addButton(printer_btn, QDialogButtonBox.ActionRole)
        buttons.addButton(QDialogButtonBox.Cancel)
        buttons.rejected.connect(self.reject)
        pdf_btn.clicked.connect(self._to_pdf)
        printer_btn.clicked.connect(self._to_printer)
        form.addRow(buttons)
        self._on_area_changed()

    # -- plot parameters -------------------------------------------------------
    def _layout_mode(self) -> bool:
        return self.area.currentData() == "layout"

    def _on_area_changed(self) -> None:
        # In layout mode paper/orientation/scale come from the page setup.
        manual = not self._layout_mode()
        for widget in (self.paper, self.orientation, self.scale, self.units):
            widget.setEnabled(manual)

    def _mm_per_unit(self):
        n = self.scale.currentData()
        if n is None:
            return None                         # fit
        return self.units.currentData() / n     # 1:N metric

    def _area_rect(self):
        if self.area.currentData() == "view":
            return self.window.viewport._view_world_rect()
        return None                             # extents

    def _plot_on(self, printer) -> None:
        if self._layout_mode():
            pdf_out.plot_layout(self.window.document, printer,
                                self._layout_name)
            return
        pdf_out.plot(
            self.window.document, printer,
            layout_name=getattr(self.window, "_active_layout", None),
            area=self._area_rect(),
            mm_per_unit=self._mm_per_unit())

    # -- outputs ---------------------------------------------------------------
    def _to_pdf(self) -> None:
        name = self.window.document.name if self.window.document else "plano"
        path, _f = QFileDialog.getSaveFileName(
            self, tr("Save PDF"), f"{name}.pdf", "PDF (*.pdf)")
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
