# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Drawing Recovery — what a crash left behind.

AutoCAD's Drawing Recovery Manager (reference p. 659) "displays a list of
all drawing files that were open at the time of a program or system
failure", offering the automatic save (.sv$) next to the original drawing,
with the details of each; opening and saving one removes it from the list.

This is the same list, minus the preview thumbnail: what is offered per
drawing is its automatic save, when it was written, and how much of the
drawing it holds — the three things that answer "is this worth opening?".
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from core import autosave
from core.i18n import tr


def _age(stamp: float) -> str:
    minutes = max(0, int((time.time() - stamp) // 60))
    if minutes < 60:
        return tr("{n} min ago", n=minutes)
    hours = minutes // 60
    if hours < 24:
        return tr("{n} h ago", n=hours)
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(stamp))


class DrawingRecoveryDialog(QDialog):
    """Lists the recoverable drawings; ``chosen()`` is the one to open."""

    def __init__(self, parent=None, entries=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Drawing Recovery"))
        self._entries = list(entries if entries is not None
                             else autosave.recoverable())
        self._chosen = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            tr("These drawings were open when IngeCAD closed unexpectedly. "
               "Their automatic saves are still here:")))

        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(
            [tr("Drawing"), tr("Saved"), tr("Objects"), tr("Size")])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.doubleClicked.connect(self._open)
        layout.addWidget(self.table)
        self._fill()

        buttons = QHBoxLayout()
        self._open_btn = QPushButton(tr("Open"), self)
        self._open_btn.clicked.connect(self._open)
        buttons.addWidget(self._open_btn)
        remove = QPushButton(tr("Remove"), self)
        remove.setToolTip(tr("Delete this automatic save"))
        remove.clicked.connect(self._remove)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        box = QDialogButtonBox(QDialogButtonBox.Close, parent=self)
        box.rejected.connect(self.reject)
        layout.addWidget(box)
        self.resize(620, 300)

    def _fill(self) -> None:
        self.table.setRowCount(len(self._entries))
        for row, entry in enumerate(self._entries):
            drawing = entry.get("drawing")
            name = drawing.name if drawing else tr("Unnamed drawing")
            item = QTableWidgetItem(name)
            item.setToolTip(str(drawing) if drawing else "")
            self.table.setItem(row, 0, item)
            self.table.setItem(row, 1,
                               QTableWidgetItem(_age(entry["saved_at"])))
            self.table.setItem(row, 2,
                               QTableWidgetItem(str(entry.get("entities", 0))))
            self.table.setItem(row, 3, QTableWidgetItem(
                tr("{n:.1f} MB", n=entry.get("size", 0) / 1e6)))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        if self._entries:
            self.table.selectRow(0)

    def _current(self):
        row = self.table.currentRow()
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def _open(self, *_args) -> None:
        entry = self._current()
        if entry is None:
            return
        self._chosen = entry
        self.accept()

    def _remove(self) -> None:
        entry = self._current()
        if entry is None:
            return
        autosave.forget(entry)
        self._entries.remove(entry)
        self._fill()
        if not self._entries:
            self.reject()

    def chosen(self) -> dict | None:
        """The entry the user asked to open, or None."""
        return self._chosen


def offer_recovery(window) -> bool:
    """Show the manager if a crash left anything. True if a drawing opened.

    Called at startup, before the blank drawing: the recovered work is what
    the user came back for.
    """
    entries = autosave.recoverable()
    if not entries:
        return False
    dialog = DrawingRecoveryDialog(window, entries)
    dialog.exec()
    entry = dialog.chosen()
    if entry is None:
        return False
    window.open_path(Path(entry["autosave"]))
    # It is a rescue, not the drawing itself: it must not overwrite the
    # original on the next Ctrl+S, and it IS unsaved work.
    document = window.document
    if document is not None:
        document.path = entry.get("drawing")
        document.dirty = True
        window.setWindowTitle(f"IngeCAD — {document.name}")
    autosave.forget(entry)
    return True
