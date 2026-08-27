# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Find and Replace dialog (p. 809): Find What, Replace With, Find Where,
the results list, Replace / Replace All, and Zoom to the highlighted result."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from core import find_text
from core.i18n import tr


class FindReplaceDialog(QDialog):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.setWindowTitle(tr("Find and Replace"))
        self._results: list = []
        root = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Find what:"), self))
        self.needle = QLineEdit(self)
        self.needle.returnPressed.connect(self.find)
        row.addWidget(self.needle, 1)
        root.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Replace with:"), self))
        self.replacement = QLineEdit(self)
        row.addWidget(self.replacement, 1)
        root.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Find where:"), self))
        self.where = QComboBox(self)
        self.where.addItem(tr("Entire drawing"), "drawing")
        self.where.addItem(tr("Current layout"), "layout")
        if window.tools.selection:
            self.where.addItem(tr("Selected objects"), "selection")
            self.where.setCurrentIndex(2)   # the default when one exists
        row.addWidget(self.where, 1)
        root.addLayout(row)

        row = QHBoxLayout()
        self.match_case = QCheckBox(tr("Match case"), self)
        self.whole_word = QCheckBox(tr("Find whole words only"), self)
        row.addWidget(self.match_case)
        row.addWidget(self.whole_word)
        row.addStretch(1)
        root.addLayout(row)

        self.list = QTreeWidget(self)
        self.list.setColumnCount(3)
        self.list.setHeaderLabels([tr("Location"), tr("Object"), tr("Text")])
        self.list.itemDoubleClicked.connect(lambda *_: self.zoom_to())
        root.addWidget(self.list, 1)

        row = QHBoxLayout()
        for label, slot in ((tr("Find"), self.find),
                            (tr("Replace"), self.replace),
                            (tr("Replace All"), self.replace_all),
                            (tr("Zoom to"), self.zoom_to),
                            (tr("Select"), self.select_results)):
            button = QPushButton(label, self)
            button.clicked.connect(slot)
            row.addWidget(button)
        close = QPushButton(tr("Close"), self)
        close.clicked.connect(self.accept)
        row.addWidget(close)
        root.addLayout(row)
        self.resize(620, 420)

    # -- scope ----------------------------------------------------------------
    def _pool(self) -> list:
        document = self.window.document
        where = self.where.currentData()
        if where == "selection":
            return self.window.tools._selection_entities()
        if where == "layout":
            name = getattr(self.window, "_active_layout", "Model")
            layout = (document.doc.modelspace() if name == "Model"
                      else document.doc.layouts.get(name))
            return list(layout)
        out = []
        for layout in document.doc.layouts:
            out.extend(layout)
        return out

    def _location(self, entity) -> str:
        return (tr("Model") if not entity.dxf.get("paperspace", 0)
                else tr("Paper space"))

    # -- actions --------------------------------------------------------------
    def find(self) -> None:
        self._results = find_text.search(
            self._pool(), self.needle.text(),
            self.match_case.isChecked(), self.whole_word.isChecked())
        self.list.clear()
        for entity in self._results:
            text = find_text.read_text(entity).replace("\n", " ")
            QTreeWidgetItem(self.list, [self._location(entity),
                                        entity.dxftype().title(), text[:80]])
        if self._results:
            self.list.setCurrentItem(self.list.topLevelItem(0))
        self.window.command_line.echo(
            tr("{count} object(s) found.", count=len(self._results)))

    def _current(self):
        index = self.list.indexOfTopLevelItem(self.list.currentItem())
        if 0 <= index < len(self._results):
            return self._results[index]
        return None

    def replace(self) -> None:
        entity = self._current()
        if entity is None:
            return
        self._run([entity])

    def replace_all(self) -> None:
        if not self._results:
            self.find()
        if self._results:
            self._run(list(self._results))

    def _run(self, entities) -> None:
        command = find_text.ReplaceTextCommand(
            entities, self.needle.text(), self.replacement.text(),
            self.match_case.isChecked())
        self.window.history.execute(command)
        self.window.regen_in_memory()
        self.window.command_line.echo(
            tr("{count} object(s) changed.", count=len(entities)))
        self.find()

    def zoom_to(self) -> None:
        entity = self._current()
        if entity is None:
            return
        self.window.zoom_to_entity(entity)

    def select_results(self) -> None:
        self.window.tools.selection = {e.dxf.handle for e in self._results
                                       if e.dxf.handle}
        self.window.tools.changed.emit()
