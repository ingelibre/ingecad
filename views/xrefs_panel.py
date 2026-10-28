# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""External References palette (XREF / EXTERNALREFERENCES, issue #33).

AutoCAD's palette lists every reference with its status, type and path
-- drawings, raster images and PDFs alike (Rafael, review 6: ours listed
only the DWGs) -- and offers Attach (DWG, Image, PDF), Detach, Reload
and Unload. Here it is a tab of the
right sidebar (managers live there, not in modal dialogs), refreshed when
a drawing opens or an xref changes. Every button routes through the same
Commands and helpers the -XREF command line uses (core.xrefs), so undo
and the picture agree whichever way the user went.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QMenu, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from core import xrefs
from core.i18n import tr

COLUMNS = ("Reference Name", "Status", "Type", "Saved Path")


class XrefsPanel(QWidget):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.table = QTableWidget(0, len(COLUMNS), self)
        self.table.setHorizontalHeaderLabels([tr(c) for c in COLUMNS])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        self.attach_btn = QPushButton(tr("Attach..."), self)
        self.detach_btn = QPushButton(tr("Detach"), self)
        self.reload_btn = QPushButton(tr("Reload"), self)
        self.unload_btn = QPushButton(tr("Unload"), self)
        for button in (self.attach_btn, self.detach_btn, self.reload_btn,
                       self.unload_btn):
            button.setFocusPolicy(Qt.NoFocus)
            row.addWidget(button)
        layout.addLayout(row)
        # AutoCAD's Attach button opens a choice of what to attach
        self._attach_menu = QMenu(self)
        for label, command in ((tr("Attach DWG..."), "XATTACH"),
                               (tr("Attach Image..."), "IMAGEATTACH"),
                               (tr("Attach PDF..."), "PDFATTACH")):
            action = self._attach_menu.addAction(label)
            action.triggered.connect(
                lambda _=False, c=command: self.window.tools.start_tool(c))
        self.attach_btn.setMenu(self._attach_menu)
        self.detach_btn.clicked.connect(self._detach)
        self.reload_btn.clicked.connect(self._reload)
        self.unload_btn.clicked.connect(self._unload)
        self.table.itemSelectionChanged.connect(self._sync_buttons)
        self._sync_buttons()

    # -- contents ------------------------------------------------------------------
    def refresh(self) -> None:
        document = getattr(self.window, "document", None)
        self.table.setRowCount(0)
        if document is None:
            self._sync_buttons()
            return
        kinds = {"image": tr("Raster image"), "pdf": tr("PDF (as image)")}
        for ref in xrefs.references(document) + xrefs.image_references(document):
            r = self.table.rowCount()
            self.table.insertRow(r)
            kind = kinds.get(ref.kind) or (tr("Overlay") if ref.overlay else tr("Attach"))
            cells = (ref.name, tr(ref.status), kind, ref.path)
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == 0:
                    item.setData(Qt.UserRole, (ref.kind, ref.handle or ref.name))
                if ref.status == "Not found":
                    item.setForeground(Qt.red)
                elif ref.status == "Unloaded":
                    item.setForeground(Qt.gray)
                self.table.setItem(r, c, item)
        self._sync_buttons()

    def selected(self) -> tuple[str, str] | None:
        """(kind, key) of the selected row: ("dwg", block name) or
        ("image"/"pdf", IMAGEDEF handle)."""
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return item.data(Qt.UserRole) if item is not None else None

    def selected_name(self) -> str | None:
        """The selected DRAWING reference's name (the -XREF actions)."""
        chosen = self.selected()
        return chosen[1] if chosen is not None and chosen[0] == "dwg" else None

    def _sync_buttons(self) -> None:
        chosen = self.selected()
        self.detach_btn.setEnabled(chosen is not None)
        self.reload_btn.setEnabled(chosen is not None)
        self.unload_btn.setEnabled(chosen is not None and chosen[0] == "dwg")
        self.attach_btn.setEnabled(getattr(self.window, "document", None) is not None)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        # images are attached by tools that do not report here: the tab
        # reads the drawing whenever it comes into view
        self.refresh()
        super().showEvent(event)

    # -- actions ---------------------------------------------------------------------
    def _detach(self) -> None:
        chosen = self.selected()
        if chosen is not None and chosen[0] != "dwg":
            self.window.tools._execute(xrefs.DetachImageCommand(chosen[1]))
            self.window.command_line.echo(tr("Image detached."))
            self.window.xrefs_changed()
            return
        name = self.selected_name()
        if name is None:
            return
        self.window.tools._execute(xrefs.DetachXrefCommand(name))
        self.window.command_line.echo(tr("Xref {name} detached.", name=name))
        self.window.xrefs_changed()

    def _reload(self) -> None:
        chosen = self.selected()
        if chosen is not None and chosen[0] != "dwg":
            # an image is read from its file by every regen: one regen reloads it
            self.window.command_line.echo(tr("Image reloaded."))
            self.window.xrefs_changed()
            return
        name = self.selected_name()
        if name is None:
            return
        xrefs.reload(self.window.document, [name])
        self.window.command_line.echo(tr("Xref {name} reloaded.", name=name))
        self.window.xrefs_changed()

    def _unload(self) -> None:
        name = self.selected_name()
        if name is None:
            return
        xrefs.unload(self.window.document, [name])
        self.window.command_line.echo(tr("Xref {name} unloaded.", name=name))
        self.window.xrefs_changed()
