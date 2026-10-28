# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""PUBLISH (p. 1509): several layouts into one multi-page PDF (issue #41).

AutoCAD's Publish dialog lists the sheets of the drawing with a check box
each, the plot style table to use, and publishes to a single file. This is
that, reduced to what a plan set needs: pick the layouts, in tab order, one
PDF, every page the size of its sheet at 1:1.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QListWidget, QListWidgetItem, QPushButton)

from core import plotstyles
from core.i18n import tr
from formats import pdf_out
from views import file_dialogs


def publish_selection(dialog) -> list[str]:
    """The checked layout names, in list (tab) order -- pure, for tests."""
    return [dialog.layouts.item(i).text()
            for i in range(dialog.layouts.count())
            if dialog.layouts.item(i).checkState() == Qt.Checked]


class PublishDialog(QDialog):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.setWindowTitle(tr("Publish"))
        self.setMinimumWidth(360)
        form = QFormLayout(self)
        self.layouts = QListWidget(self)
        document = window.document
        names = [n for n in document.doc.layouts.names_in_taborder() if n != "Model"]
        for name in names:
            item = QListWidgetItem(name, self.layouts)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
        form.addRow(tr("Sheets to publish"), self.layouts)
        self.style = QComboBox(self)
        self.style.addItem(tr("None"), "")
        for name in plotstyles.available():
            self.style.addItem(name, name)
        current = ""
        active = getattr(window, "_active_layout", "Model")
        if active in document.doc.layouts and active != "Model":
            current = str(document.doc.layouts.get(active).dxf_layout.dxf.get(
                "current_style_sheet", "") or "")
        idx = self.style.findData(current)
        self.style.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow(tr("Plot style table"), self.style)
        buttons = QDialogButtonBox(self)
        go = QPushButton(tr("Publish to PDF..."), self)
        buttons.addButton(go, QDialogButtonBox.AcceptRole)
        buttons.addButton(QDialogButtonBox.Cancel)
        buttons.rejected.connect(self.reject)
        go.clicked.connect(self._publish)
        form.addRow(buttons)

    def _publish(self) -> None:
        names = publish_selection(self)
        if not names:
            self.window.command_line.echo(tr("No sheets selected."))
            return
        document = self.window.document
        path, _f = file_dialogs.get_save_file(
            self, tr("Publish to PDF"), f"{Path(document.name).stem}.pdf", "PDF (*.pdf)",
            preferred=document.path)
        if not path:
            return
        pages = pdf_out.publish(document, names, path,
                                ctb=self.style.currentData())
        self.window.command_line.echo(
            tr("Published {n} sheet(s) to {p}", n=pages, p=path))
        self.accept()
