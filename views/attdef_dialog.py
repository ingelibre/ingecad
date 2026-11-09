# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Attribute Definition dialog (ATTDEF, p. 163) -- also BATTMAN's Edit
Attribute, which shows the same fields for an existing definition.

Mode / Attribute / Insertion Point / Text Settings, in AutoCAD's layout and
wording. The values come out as a dict the tools turn into a Command; the
dialog itself changes nothing.
"""
from __future__ import annotations

from typing import Optional

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
    QLineEdit,
    QVBoxLayout,
)

from core import attributes as att
from core import text_justify
from core.i18n import tr

#: Justification names in the dialog's dropdown, in TEXT's order: the
#: Properties panel's list (core.text_justify), labels translated alike.
JUSTIFICATIONS = [name for _label, name in text_justify.JUSTIFICATIONS]

#: The definition made last in this process, per document id: "Align below
#: previous attribute definition" places the next one under it.
_LAST: dict = {}


def remember_definition(document, attdef) -> None:
    _LAST[id(document)] = attdef


def last_definition(document):
    attdef = _LAST.get(id(document))
    if attdef is None or not getattr(attdef, "is_alive", False):
        return None
    return attdef


def below(attdef) -> tuple[float, float]:
    """Where a definition aligned below ``attdef`` starts: one text line
    down (AutoCAD uses 5/3 of the height between attribute lines)."""
    insert = attdef.dxf.insert
    height = float(attdef.dxf.height or 2.5)
    return (insert.x, insert.y - height * 5.0 / 3.0)


class AttDefDialog(QDialog):
    def __init__(self, window, document, previous=None, attdef=None) -> None:
        super().__init__(window)
        self.document = document
        self.attdef = attdef             # editing an existing definition
        self.previous = previous
        self.setWindowTitle(tr("Edit Attribute") if attdef is not None
                            else tr("Attribute Definition"))
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        root.addLayout(top)

        # -- Mode -------------------------------------------------------------
        modes = QGroupBox(tr("Mode"), self)
        grid = QVBoxLayout(modes)
        self.invisible = QCheckBox(tr("Invisible"), modes)
        self.constant = QCheckBox(tr("Constant"), modes)
        self.verify = QCheckBox(tr("Verify"), modes)
        self.preset = QCheckBox(tr("Preset"), modes)
        self.lock_position = QCheckBox(tr("Lock position"), modes)
        self.multiline = QCheckBox(tr("Multiple lines"), modes)
        self.multiline.setEnabled(False)          # single-line only, for now
        self.multiline.setToolTip(tr("Multiple-line attributes are not "
                                     "supported yet."))
        for box in (self.invisible, self.constant, self.verify, self.preset,
                    self.lock_position, self.multiline):
            grid.addWidget(box)
        self.constant.toggled.connect(self._sync_constant)
        top.addWidget(modes)

        # -- Attribute --------------------------------------------------------
        attribute = QGroupBox(tr("Attribute"), self)
        form = QFormLayout(attribute)
        self.tag = QLineEdit(attribute)
        self.tag.setMaxLength(255)
        self.prompt_edit = QLineEdit(attribute)
        self.default = QLineEdit(attribute)
        form.addRow(tr("Tag:"), self.tag)
        form.addRow(tr("Prompt:"), self.prompt_edit)
        form.addRow(tr("Default:"), self.default)
        top.addWidget(attribute, 1)

        bottom = QHBoxLayout()
        root.addLayout(bottom)

        # -- Insertion Point ---------------------------------------------------
        insertion = QGroupBox(tr("Insertion Point"), self)
        grid = QGridLayout(insertion)
        self.on_screen = QCheckBox(tr("Specify on-screen"), insertion)
        self.on_screen.setChecked(True)
        grid.addWidget(self.on_screen, 0, 0, 1, 2)
        self.x = QDoubleSpinBox(insertion)
        self.y = QDoubleSpinBox(insertion)
        self.z = QDoubleSpinBox(insertion)
        for i, (label, spin) in enumerate((("X:", self.x), ("Y:", self.y),
                                           ("Z:", self.z))):
            spin.setRange(-1e12, 1e12)
            spin.setDecimals(4)
            grid.addWidget(QLabelFor(label, insertion), i + 1, 0)
            grid.addWidget(spin, i + 1, 1)
        self.z.setEnabled(False)
        self.on_screen.toggled.connect(self._sync_on_screen)
        bottom.addWidget(insertion)

        # -- Text Settings -----------------------------------------------------
        settings = QGroupBox(tr("Text Settings"), self)
        form = QFormLayout(settings)
        self.justification = QComboBox(settings)
        for label, name in text_justify.JUSTIFICATIONS:
            self.justification.addItem(tr(label), name)
        self.style = QComboBox(settings)
        for name in sorted(s.dxf.name for s in document.doc.styles):
            self.style.addItem(name)
        current_style = str(document.doc.header.get("$TEXTSTYLE", "Standard"))
        if self.style.findText(current_style) >= 0:
            self.style.setCurrentText(current_style)
        self.annotative = QCheckBox(tr("Annotative"), settings)
        self.annotative.setEnabled(False)
        self.height = QDoubleSpinBox(settings)
        self.height.setRange(0.0001, 1e9)
        self.height.setDecimals(4)
        self.rotation = QDoubleSpinBox(settings)
        self.rotation.setRange(-360.0, 360.0)
        self.rotation.setDecimals(4)
        self.boundary_width = QDoubleSpinBox(settings)
        self.boundary_width.setRange(0.0, 1e9)
        self.boundary_width.setEnabled(False)     # multiline only
        form.addRow(tr("Justification:"), self.justification)
        form.addRow(tr("Text style:"), self.style)
        form.addRow("", self.annotative)
        form.addRow(tr("Text height:"), self.height)
        form.addRow(tr("Rotation:"), self.rotation)
        form.addRow(tr("Boundary width:"), self.boundary_width)
        bottom.addWidget(settings, 1)

        self.align_below = QCheckBox(
            tr("Align below previous attribute definition"), self)
        self.align_below.setEnabled(previous is not None and attdef is None)
        self.align_below.toggled.connect(self._sync_align_below)
        root.addWidget(self.align_below)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._fill_defaults()
        self.style.currentTextChanged.connect(self._sync_fixed_height)
        self._sync_fixed_height()
        self._sync_constant(self.constant.isChecked())

    # -- state ------------------------------------------------------------------
    def _fill_defaults(self) -> None:
        from tools.attributes import AttDefCliTool
        from tools.draw import TextTool

        if self.attdef is not None:
            a = self.attdef
            mode = att.AttMode.of(a)
            self.tag.setText(str(a.dxf.tag))
            self.prompt_edit.setText(str(a.dxf.get("prompt", "") or ""))
            self.default.setText(att.default_of(a))
            self.height.setValue(float(a.dxf.height or 2.5))
            self.rotation.setValue(float(a.dxf.get("rotation", 0.0)))
            style = str(a.dxf.get("style", "Standard"))
            if self.style.findText(style) >= 0:
                self.style.setCurrentText(style)
            self.on_screen.setChecked(False)
            self.on_screen.setEnabled(False)
            insert = a.dxf.insert
            self.x.setValue(insert.x)
            self.y.setValue(insert.y)
            self.z.setValue(insert.z)
            for box in (self.x, self.y):
                box.setEnabled(False)
            align = a.get_align_enum().name if hasattr(a, "get_align_enum") \
                else "LEFT"
            index = self.justification.findData(align)
            if index >= 0:
                self.justification.setCurrentIndex(index)
            self.justification.setEnabled(False)
        else:
            mode = AttDefCliTool.mode
            last = AttDefCliTool._last
            self.height.setValue(last[0] if last else TextTool.default_height)
            self.rotation.setValue(last[1] if last else TextTool.last_rotation)
        self.invisible.setChecked(mode.invisible)
        self.constant.setChecked(mode.constant)
        self.verify.setChecked(mode.verify)
        self.preset.setChecked(mode.preset)
        self.lock_position.setChecked(mode.lock_position)

    def _sync_constant(self, constant: bool) -> None:
        # Constant: no prompt, and the "default" IS the value (p. 165)
        self.prompt_edit.setEnabled(not constant)
        self.verify.setEnabled(not constant)
        self.preset.setEnabled(not constant)

    def _sync_on_screen(self, on: bool) -> None:
        for box in (self.x, self.y):
            box.setEnabled(not on and not self.align_below.isChecked())

    def _sync_align_below(self, on: bool) -> None:
        self.on_screen.setEnabled(not on)
        self._sync_on_screen(self.on_screen.isChecked() or on)
        if on and self.previous is not None:
            x, y = below(self.previous)
            self.x.setValue(x)
            self.y.setValue(y)
            self.height.setValue(float(self.previous.dxf.height or 2.5))
            self.rotation.setValue(
                float(self.previous.dxf.get("rotation", 0.0)))
            style = str(self.previous.dxf.get("style", "Standard"))
            if self.style.findText(style) >= 0:
                self.style.setCurrentText(style)

    def _sync_fixed_height(self, *_args) -> None:
        """A text style with a fixed height decides the height (p. 166)."""
        name = self.style.currentText()
        fixed = 0.0
        try:
            if name in self.document.doc.styles:
                fixed = float(self.document.doc.styles.get(name).dxf.height
                              or 0.0)
        except Exception:  # noqa: BLE001
            fixed = 0.0
        if fixed > 0:
            self.height.setValue(fixed)
        self.height.setEnabled(fixed <= 0)

    def _accept(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        tag = self.tag.text().strip().upper().replace(" ", "")
        if not tag or "!" in tag:
            QMessageBox.warning(self, tr("Attribute Definition"),
                                tr("Invalid tag name."))
            return
        self.accept()

    def mode(self) -> att.AttMode:
        return att.AttMode(
            invisible=self.invisible.isChecked(),
            constant=self.constant.isChecked(),
            verify=self.verify.isChecked() and not self.constant.isChecked(),
            preset=self.preset.isChecked() and not self.constant.isChecked(),
            lock_position=self.lock_position.isChecked(),
            multiline=False)

    def values(self) -> dict:
        prev = self.previous if self.align_below.isChecked() else None
        return {
            "tag": self.tag.text().strip().upper().replace(" ", ""),
            "prompt": "" if self.constant.isChecked()
            else self.prompt_edit.text(),
            "default": self.default.text(),
            "mode": self.mode(),
            "on_screen": self.on_screen.isChecked() and prev is None,
            "x": self.x.value(), "y": self.y.value(),
            "align": self.justification.currentData() or "LEFT",
            "style": self.style.currentText() or None,
            "height": self.height.value(),
            "rotation": self.rotation.value(),
            "align_below": prev is not None,
            "below": below(prev) if prev is not None else None,
        }


def QLabelFor(text: str, parent):   # noqa: N802 - a tiny widget factory
    from PySide6.QtWidgets import QLabel

    return QLabel(text, parent)
