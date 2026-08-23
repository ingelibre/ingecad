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

        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Description:"), self))
        self.description = QLineEdit(self)
        self.description.setMaxLength(64)     # "up to 64 characters" (p.863)
        self.description.editingFinished.connect(self._save_description)
        row.addWidget(self.description, 1)
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

        # "Change Group -- Add / Remove" (p.863-864), plus Find Name.
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Change Group:"), self))
        for label, slot in ((tr("Add"), self.add_objects),
                            (tr("Remove"), self.remove_objects),
                            (tr("Find Name"), self.find_name)):
            button = QPushButton(label, self)
            button.clicked.connect(slot)
            row.addWidget(button)
        root.addLayout(row)

        # "When the PICKSTYLE system variable is set to 0, no groups are
        # selectable" (p.862) -- the escape hatch for editing ONE member.
        self.pickstyle = QCheckBox(tr("Group selection (PICKSTYLE)"), self)
        self.pickstyle.toggled.connect(self._toggle_pickstyle)
        root.addWidget(self.pickstyle)

        self.hint = QLabel(
            tr("New groups the current selection. Selecting one object of a "
               "selectable group selects the whole group."), self)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #9aa0a6;")
        root.addWidget(self.hint)

        close = QPushButton(tr("Close"), self)
        close.clicked.connect(self.accept)
        root.addWidget(close)
        self.resize(500, 460)
        self.refresh()

    # -- data -----------------------------------------------------------------
    @property
    def document(self):
        return self.window.document

    def refresh(self) -> None:
        # Keep the row the user is working on. Rebuilding the list dropped
        # it, so every action that ends in a refresh (Add, Remove, the
        # Selectable switch) left nothing selected -- and the NEXT action
        # silently did nothing, because it had no group to act on.
        keep = self._current_name()
        self.list.clear()
        restore = None
        for name, group in group_ops.all_groups(self.document):
            selectable = group_ops.is_selectable(self.document, name)
            item = QTreeWidgetItem(self.list, [
                name, tr("Yes") if selectable else tr("No"),
                str(len(list(group)))])
            if name == keep:
                restore = item
        if restore is not None:
            self.list.setCurrentItem(restore)
        elif self.list.topLevelItemCount():
            self.list.setCurrentItem(self.list.topLevelItem(0))
        self._sync()

    def _current_name(self) -> str | None:
        item = self.list.currentItem()
        return item.text(0) if item is not None else None

    def _sync(self) -> None:
        name = self._current_name()
        self.name.setText(name or "")
        self.description.setText(
            group_ops.description(self.document, name) if name else "")
        self.description.setEnabled(bool(name))
        self.selectable.blockSignals(True)
        self.selectable.setChecked(
            bool(name) and group_ops.is_selectable(self.document, name))
        self.selectable.setEnabled(bool(name))
        self.selectable.blockSignals(False)
        self.pickstyle.blockSignals(True)
        self.pickstyle.setChecked(group_ops.pickstyle(self.document) != 0)
        self.pickstyle.blockSignals(False)

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

    def add_objects(self) -> None:
        """Add: the current selection joins the selected group."""
        name = self._current_name()
        if not name:
            return
        entities = self._picked(name, inside=False)
        if entities is None:
            return
        self.window.history.execute(
            group_ops.ChangeGroupMembersCommand(name, entities, add=True))
        self.window.command_line.echo(
            tr("{count} object(s) added to {name}.", count=len(entities),
               name=name))
        self.refresh()

    def remove_objects(self) -> None:
        """Remove: the selected objects leave the group, staying in the
        drawing. "If you remove all the group's objects, the group remains
        defined" (p.863)."""
        name = self._current_name()
        if not name:
            return
        entities = self._picked(name, inside=True)
        if entities is None:
            return
        self.window.history.execute(
            group_ops.ChangeGroupMembersCommand(name, entities, add=False))
        self.window.command_line.echo(
            tr("{count} object(s) removed from {name}.", count=len(entities),
               name=name))
        self.refresh()

    def _picked(self, name: str, inside: bool):
        """The current selection, filtered to what the operation can act on.

        A selectable group swallows its whole membership on a pick, so
        Remove would otherwise be handed the entire group every time.
        """
        entities = self.window.tools._selection_entities()
        if not entities:
            QMessageBox.information(
                self, tr("Object Grouping"),
                tr("Select the objects first."))
            return None
        members = {e.dxf.handle for e in group_ops.members(self.document, name)}
        wanted = [e for e in entities
                  if (e.dxf.handle in members) == inside]
        if not wanted:
            QMessageBox.information(
                self, tr("Object Grouping"),
                tr("Those objects are already in {name}.", name=name)
                if inside is False else
                tr("None of the selected objects belong to {name}.",
                   name=name))
            return None
        return wanted

    def find_name(self) -> None:
        """"Lists the groups to which an object belongs" (p.863)."""
        entities = self.window.tools._selection_entities()
        if not entities:
            QMessageBox.information(
                self, tr("Object Grouping"),
                tr("Select the objects first."))
            return
        lines = []
        for entity in entities[:20]:
            names = group_ops.groups_of(self.document, entity)
            lines.append(f"{entity.dxftype()} {entity.dxf.handle}: "
                         + (", ".join(names) if names else tr("(none)")))
        QMessageBox.information(self, tr("Group Member List"),
                                "\n".join(lines))

    def _save_description(self) -> None:
        name = self._current_name()
        if name:
            group_ops.set_description(self.document, name,
                                      self.description.text())

    def _toggle_pickstyle(self, state: bool) -> None:
        group_ops.set_pickstyle(self.document, 1 if state else 0)
        self.window.command_line.echo(
            tr("Group selection on.") if state else tr("Group selection off."))

    def _toggle_selectable(self, state: bool) -> None:
        name = self._current_name()
        if name:
            group_ops.set_selectable(self.document, name, state)
            self.refresh()
