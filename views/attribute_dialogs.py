# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Attribute dialogs of a block REFERENCE.

* :class:`EnhancedAttributeEditor` -- EATTEDIT (p. 715) and the double-click
  on a reference with attributes: Attribute / Text Options / Properties tabs;
  what changed comes out as ``(attrib, prop, value)`` triples for one
  undoable Command.
* :class:`InsertAttributesDialog` -- the Edit Attributes dialog INSERT shows
  when ATTDIA is 1: one line per prompted definition with its default.
* :class:`EditAttDefDialog` -- DDEDIT on a loose attribute DEFINITION (p.
  523): its tag, prompt and default.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core import attributes as att
from core.i18n import tr


class EnhancedAttributeEditor(QDialog):
    def __init__(self, window, insert) -> None:
        super().__init__(window)
        self.insert = insert
        self.attribs = [a for a in insert.attribs if a.is_alive]
        self.setWindowTitle(tr("Enhanced Attribute Editor"))
        self.resize(560, 380)
        root = QVBoxLayout(self)
        root.addWidget(QLabel(tr("Block: {name}", name=insert.dxf.name), self))
        self.tabs = QTabWidget(self)
        root.addWidget(self.tabs, 1)

        # -- Attribute tab ---------------------------------------------------
        page = QWidget(self.tabs)
        layout = QVBoxLayout(page)
        self.table = QTableWidget(len(self.attribs), 3, page)
        self.table.setHorizontalHeaderLabels([tr("Tag"), tr("Prompt"),
                                              tr("Value")])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self._values: list[str] = []
        doc = insert.doc
        defs = {str(a.dxf.tag): a
                for a in att.attdefs_of(doc, str(insert.dxf.name))} if doc else {}
        for row, attrib in enumerate(self.attribs):
            tag = str(attrib.dxf.tag)
            prompt = ""
            if tag in defs:
                prompt = str(defs[tag].dxf.get("prompt", "") or "")
            for col, text in enumerate((tag, prompt, str(attrib.dxf.text or ""))):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                self.table.setItem(row, col, item)
            self._values.append(str(attrib.dxf.text or ""))
        layout.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Value:"), page))
        self.value = QLineEdit(page)
        self.value.textEdited.connect(self._value_edited)
        row.addWidget(self.value, 1)
        layout.addLayout(row)
        self.tabs.addTab(page, tr("Attribute"))

        # -- Text Options tab ------------------------------------------------
        page = QWidget(self.tabs)
        form = QFormLayout(page)
        self.style = QComboBox(page)
        if doc is not None:
            for name in sorted(s.dxf.name for s in doc.styles):
                self.style.addItem(name)
        self.height = QDoubleSpinBox(page)
        self.height.setRange(0.0001, 1e9)
        self.height.setDecimals(4)
        self.rotation = QDoubleSpinBox(page)
        self.rotation.setRange(-360.0, 360.0)
        self.rotation.setDecimals(4)
        form.addRow(tr("Text style:"), self.style)
        form.addRow(tr("Height:"), self.height)
        form.addRow(tr("Rotation:"), self.rotation)
        self.tabs.addTab(page, tr("Text Options"))

        # -- Properties tab --------------------------------------------------
        page = QWidget(self.tabs)
        form = QFormLayout(page)
        self.layer = QComboBox(page)
        if doc is not None:
            for name in sorted(layer.dxf.name for layer in doc.layers):
                self.layer.addItem(name)
        self.color = QComboBox(page)
        self.color.addItem(tr("ByLayer"), 256)
        self.color.addItem(tr("ByBlock"), 0)
        for aci, name in ((1, tr("Red")), (2, tr("Yellow")), (3, tr("Green")),
                          (4, tr("Cyan")), (5, tr("Blue")), (6, tr("Magenta")),
                          (7, tr("White"))):
            self.color.addItem(name, aci)
        form.addRow(tr("Layer:"), self.layer)
        form.addRow(tr("Color:"), self.color)
        self.tabs.addTab(page, tr("Properties"))

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        # per attribute edits of the two other tabs: prop -> {row: value}
        self._props: dict = {}
        self._row = -1
        self.table.currentCellChanged.connect(lambda r, *_: self._show(r))
        for widget, prop in ((self.style, "style"), (self.layer, "layer")):
            widget.currentTextChanged.connect(
                lambda text, p=prop: self._set(p, text))
        self.color.currentIndexChanged.connect(
            lambda i: self._set("color", self.color.itemData(i)))
        self.height.valueChanged.connect(lambda v: self._set("height", v))
        self.rotation.valueChanged.connect(lambda v: self._set("rotation", v))
        if self.attribs:
            self.table.setCurrentCell(0, 2)
            self._show(0)

    # -- editing --------------------------------------------------------------
    def _show(self, row: int) -> None:
        if not 0 <= row < len(self.attribs):
            return
        self._row = -1                    # silence the setters while filling
        attrib = self.attribs[row]
        self.value.setText(self._values[row])
        edits = {p: self._props.get(p, {}).get(row) for p in
                 ("style", "height", "rotation", "layer", "color")}
        style = edits["style"] or str(attrib.dxf.get("style", "Standard"))
        if self.style.findText(style) >= 0:
            self.style.setCurrentText(style)
        self.height.setValue(edits["height"] if edits["height"] is not None
                             else float(attrib.dxf.height or 2.5))
        self.rotation.setValue(
            edits["rotation"] if edits["rotation"] is not None
            else float(attrib.dxf.get("rotation", 0.0)))
        layer = edits["layer"] or str(attrib.dxf.layer)
        if self.layer.findText(layer) >= 0:
            self.layer.setCurrentText(layer)
        color = edits["color"] if edits["color"] is not None \
            else int(attrib.dxf.get("color", 256))
        index = self.color.findData(color)
        self.color.setCurrentIndex(index if index >= 0 else 0)
        self._row = row

    def _value_edited(self, text: str) -> None:
        row = self._row
        if row < 0:
            return
        self._values[row] = text
        item = self.table.item(row, 2)
        if item is not None:
            item.setText(text)

    def _set(self, prop: str, value) -> None:
        if self._row < 0:
            return
        self._props.setdefault(prop, {})[self._row] = value

    def set_value(self, row: int, text: str) -> None:
        """Programmatic edit (tests): the Value field of ``row``."""
        self.table.setCurrentCell(row, 2)
        self._show(row)
        self.value.setText(text)
        self._value_edited(text)

    def changes(self) -> list:
        """``(attrib, prop, value)`` for everything that differs from the
        entity -- an untouched dialog changes nothing."""
        out = []
        for row, attrib in enumerate(self.attribs):
            if self._values[row] != str(attrib.dxf.text or ""):
                out.append((attrib, "text", self._values[row]))
            for prop, rows in self._props.items():
                if row not in rows:
                    continue
                value = rows[row]
                current = attrib.dxf.get(prop, None)
                if prop in ("height", "rotation"):
                    current = float(current or 0.0)
                    if abs(float(value) - current) < 1e-9:
                        continue
                elif prop == "color":
                    if int(value) == int(current if current is not None else 256):
                        continue
                elif str(value) == str(current if current is not None
                                       else ("Standard" if prop == "style"
                                             else "0")):
                    continue
                out.append((attrib, prop, value))
        return out


class InsertAttributesDialog(QDialog):
    """The Edit Attributes dialog INSERT shows with ATTDIA = 1: the
    definitions' prompts down the left, their defaults editable."""

    def __init__(self, window, block_name: str, attdefs) -> None:
        super().__init__(window)
        self.setWindowTitle(tr("Edit Attributes"))
        self.attdefs = list(attdefs)
        root = QVBoxLayout(self)
        root.addWidget(QLabel(tr("Block name: {name}", name=block_name), self))
        form = QFormLayout()
        self.edits: list[QLineEdit] = []
        for attdef in self.attdefs:
            edit = QLineEdit(att.default_of(attdef), self)
            form.addRow(att.prompt_of(attdef), edit)
            self.edits.append(edit)
        root.addLayout(form, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def values(self) -> dict:
        return {str(a.dxf.tag): e.text() for a, e in zip(self.attdefs, self.edits)}


class EditAttDefDialog(QDialog):
    """Edit Attribute Definition (DDEDIT, p. 523): the double-click on an
    attribute definition edits its tag, prompt and default value."""

    def __init__(self, window, attdef) -> None:
        super().__init__(window)
        self.setWindowTitle(tr("Edit Attribute Definition"))
        self.attdef = attdef
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.tag = QLineEdit(str(attdef.dxf.get("tag", "")), self)
        self.prompt = QLineEdit(str(attdef.dxf.get("prompt", "") or ""), self)
        self.default = QLineEdit(att.default_of(attdef), self)
        form.addRow(tr("Tag:"), self.tag)
        form.addRow(tr("Prompt:"), self.prompt)
        form.addRow(tr("Default:"), self.default)
        root.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.tag.selectAll()

    def _accept(self) -> None:
        if att.normal_tag(self.tag.text()):
            self.accept()
        else:
            self.tag.setFocus()       # a definition needs its tag

    def command(self):
        """The edit as one undoable Command, or None when nothing changed."""
        return att.edit_definition(self.attdef, self.tag.text(),
                                   self.prompt.text(), self.default.text())
