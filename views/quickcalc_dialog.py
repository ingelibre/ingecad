# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The QuickCalc calculator (p. 1589).

Its documented areas, and what this one has:

* **Input box** and **History area** — both, with the history's "copy a
  selected expression" as a double-click that puts it back in the input.
* **Number pad** and **Scientific area** — both.
* **Units Conversion area** — Length, Area, Volume and Angular, which is the
  reference's own list of unit types.
* **Toolbar**: Clear, Clear History and Paste Value to Command Line.

Left out, because they need a point picked on the canvas while the
calculator is open: Get Coordinates, Distance Between Two Points, Angle of
Line, and Two Lines Defined by Four Points. IngeCAD already answers those
three questions as commands — ID, DIST and the DIST prompt's angle — and a
button that cannot pick would be a lie.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import calc
from core.i18n import tr


class QuickCalcDialog(QDialog):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.setWindowTitle(tr("QuickCalc"))
        root = QVBoxLayout(self)

        self.input = QLineEdit(self)
        self.input.returnPressed.connect(self.evaluate)
        root.addWidget(self.input)

        row = QHBoxLayout()
        for label, slot in ((tr("Clear"), lambda: self.input.clear()),
                            (tr("Clear History"), self._clear_history),
                            (tr("Paste to command line"), self.paste)):
            button = QPushButton(label, self)
            button.clicked.connect(slot)
            row.addWidget(button)
        root.addLayout(row)

        root.addWidget(QLabel(tr("History"), self))
        self.history = QListWidget(self)
        self.history.itemDoubleClicked.connect(
            lambda item: self.input.setText(item.text().split(" = ")[0]))
        root.addWidget(self.history, 1)

        root.addWidget(self._pad())
        root.addWidget(self._units())
        close = QPushButton(tr("Close"), self)
        close.clicked.connect(self.accept)
        root.addWidget(close)
        self.resize(360, 560)

    # -- the pads -------------------------------------------------------------
    def _pad(self) -> QWidget:
        page = QWidget(self)
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 0, 0, 0)
        keys = ["7", "8", "9", "/", "sqrt(",
                "4", "5", "6", "*", "sin(",
                "1", "2", "3", "-", "cos(",
                "0", ".", "(", ")", "tan(",
                "pi", "^", "+", "ln(", "log("]
        for index, key in enumerate(keys):
            # a function key reads without its bracket ("sqrt"), but the
            # bracket key itself is the bracket
            label = key if key in "()" else key.rstrip("(")
            button = QPushButton(label, page)
            text = "**" if key == "^" else key
            button.clicked.connect(
                lambda _=False, t=text: self.input.insert(t))
            grid.addWidget(button, index // 5, index % 5)
        equals = QPushButton("=", page)
        equals.clicked.connect(self.evaluate)
        grid.addWidget(equals, 5, 0, 1, 5)
        return page

    def _units(self) -> QWidget:
        page = QWidget(self)
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.addWidget(QLabel(tr("Units conversion"), page), 0, 0, 1, 3)
        self.family = QComboBox(page)
        self.family.addItems(list(calc.UNITS))
        self.family.currentIndexChanged.connect(lambda *_: self._fill_units())
        grid.addWidget(self.family, 1, 0, 1, 3)
        self.from_unit = QComboBox(page)
        self.to_unit = QComboBox(page)
        grid.addWidget(self.from_unit, 2, 0)
        grid.addWidget(QLabel("→", page), 2, 1)
        grid.addWidget(self.to_unit, 2, 2)
        convert = QPushButton(tr("Convert the value"), page)
        convert.clicked.connect(self.convert)
        grid.addWidget(convert, 3, 0, 1, 3)
        self._fill_units()
        return page

    def _fill_units(self) -> None:
        names = list(calc.UNITS[self.family.currentText()])
        for box in (self.from_unit, self.to_unit):
            box.blockSignals(True)
            box.clear()
            box.addItems(names)
            box.blockSignals(False)
        self.to_unit.setCurrentIndex(min(1, len(names) - 1))

    # -- actions --------------------------------------------------------------
    def evaluate(self) -> None:
        text = self.input.text()
        try:
            value = calc.evaluate(text)
        except calc.CalcError as exc:
            self.window.command_line.echo(
                tr("QuickCalc: {reason}", reason=str(exc)))
            return
        self.history.addItem(f"{text} = {value:g}")
        self.input.setText(f"{value:g}")

    def convert(self) -> None:
        try:
            value = calc.evaluate(self.input.text())
        except calc.CalcError:
            return
        result = calc.convert(value, self.family.currentText(),
                              self.from_unit.currentText(),
                              self.to_unit.currentText())
        self.history.addItem(
            f"{value:g} {self.from_unit.currentText()} = "
            f"{result:g} {self.to_unit.currentText()}")
        self.input.setText(f"{result:g}")

    def paste(self) -> None:
        """"Pastes the value in the Input box at the Command prompt"."""
        self.window.command_line.input.setText(self.input.text())
        self.window.command_line.input.setFocus()
        self.accept()

    def _clear_history(self) -> None:
        self.history.clear()
