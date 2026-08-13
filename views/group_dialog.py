# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Object Grouping dialog (p. 861): "displays, identifies, names, and
changes object groups"."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from core import groups as group_ops
from core.i18n import tr


class ObjectGroupingDialog(QDialog):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.setWindowTitle(tr("Object Grouping"))
        root = QVBoxLayout(self)

        root.addWidget(QLabel(tr("Group Name"), self))
        self.list = QTreeWidget(self)
        self.list.setColumnCount(3)
        self.list.setHeaderLabels([tr("Group Name"), tr("Selectable"),
                                   tr("Objects")])
        self.list.currentItemChanged.connect(lambda *_: self._sync())
        root.addWidget(self.list, 1)

        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Group Identification:"), self))
        self.name = QLineEdit(self)
        self.name.setMaxLength(31)
        row.addWidget(self.name, 1)
        root.addLayout(row)

        self.selectable = QCheckBox(tr("Selectable"), self)
        self.selectable.toggled.connect(self._toggle_selectable)
        root.addWidget(self.selectable)

        row = QHBoxLayout()
        for label, slot in ((tr("New"), self.create),
                            (tr("Highlight"), self.highlight),
                            (tr("Rename"), self.rename),
                            (tr("Ungroup"), self.ungroup)):
            button = QPushButton(label, self)
            button.clicked.connect(slot)
            row.addWidget(button)
        root.addLayout(row)

        self.hint = QLabel(
            tr("New groups the current selection. Selecting one object of a "
               "selectable group selects the whole group."), self)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #9aa0a6;")
        root.addWidget(self.hint)

        close = QPushButton(tr("Close"), self)
        close.clicked.connect(self.accept)
        root.addWidget(close)
        self.resize(460, 380)
        self.refresh()

    # -- data -----------------------------------------------------------------
    @property
    def document(self):
        return self.window.document

    def refresh(self) -> None:
        self.list.clear()
        for name, group in group_ops.all_groups(self.document):
            selectable = group_ops.is_selectable(self.document, name)
            QTreeWidgetItem(self.list, [
                name, tr("Yes") if selectable else tr("No"),
                str(len(list(group)))])
        self._sync()

    def _current_name(self) -> str | None:
        item = self.list.currentItem()
        return item.text(0) if item is not None else None

    def _sync(self) -> None:
        name = self._current_name()
        self.name.setText(name or "")
        self.selectable.blockSignals(True)
        self.selectable.setChecked(
            bool(name) and group_ops.is_selectable(self.document, name))
        self.selectable.setEnabled(bool(name))
        self.selectable.blockSignals(False)

    # -- actions --------------------------------------------------------------
    def create(self) -> None:
        entities = self.window.tools._selection_entities()
        if not entities:
            QMessageBox.information(
                self, tr("Object Grouping"),
                tr("Select the objects to group first."))
            return
        name = group_ops.normalize(self.name.text())
        if not group_ops.valid_name(name):
            QMessageBox.warning(
                self, tr("Object Grouping"),
                tr("A group name is up to 31 characters of letters, digits, "
                   "$, - and _, with no spaces."))
            return
        if any(name == existing
               for existing, _g in group_ops.all_groups(self.document)):
            QMessageBox.warning(self, tr("Object Grouping"),
                                tr("That group already exists."))
            return
        self.window.history.execute(
            group_ops.CreateGroupCommand(name, entities))
        self.window.command_line.echo(
            tr("Group {name}: {count} object(s).", name=name,
               count=len(entities)))
        self.refresh()

    def rename(self) -> None:
        old = self._current_name()
        new = group_ops.normalize(self.name.text())
        if not old or old == new:
            return
        if not group_ops.valid_name(new):
            QMessageBox.warning(
                self, tr("Object Grouping"),
                tr("A group name is up to 31 characters of letters, digits, "
                   "$, - and _, with no spaces."))
            return
        try:
            self.document.doc.groups.rename(old, new)
            self.document.dirty = True
        except Exception as exc:
            QMessageBox.warning(self, tr("Object Grouping"), str(exc))
        self.refresh()

    def ungroup(self) -> None:
        name = self._current_name()
        if not name:
            return
        self.window.history.execute(group_ops.DeleteGroupCommand(name))
        self.window.command_line.echo(tr("Group {name} removed.", name=name))
        self.refresh()

    def highlight(self) -> None:
        """"Shows the members of the selected group in the drawing area"."""
        name = self._current_name()
        if not name:
            return
        for existing, group in group_ops.all_groups(self.document):
            if existing != name:
                continue
            self.window.tools.selection = {
                e.dxf.handle for e in group if e.dxf.handle}
            self.window.tools.changed.emit()
            return

    def _toggle_selectable(self, state: bool) -> None:
        name = self._current_name()
        if name:
            group_ops.set_selectable(self.document, name, state)
            self.refresh()
