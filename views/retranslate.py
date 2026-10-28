# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A live language switch reaches every widget, not only the menus (#74).

Every label was translated when it was built, and keeps only the result.
Switching language rebuilt the menus and left the rest -- the side tabs,
the status-bar toggles, the Xrefs palette, the toolbars' texts -- in the
language they were born in (Rafael saw them in English in a Spanish
interface). Here the English behind each text is found through the
catalog of the language being left, and translated again into the new
one. Texts that are no UI string (coordinates, layer names, a drawing's
own words) find no English and are left alone; table cells, which hold
the user's data, are never touched.
"""
from __future__ import annotations

import re

from PySide6.QtWidgets import (
    QAbstractButton,
    QDockWidget,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMenu,
    QTableWidget,
    QTabWidget,
    QToolBar,
    QTreeWidget,
    QWidget,
)

from core.i18n import tr

_SUFFIX = re.compile(r"^(.*\S) (\([^()]*\))$")      # "Linear (DIMLINEAR)", "Grid (F7)"


def _again(text: str, reverse: dict[str, str]) -> str:
    if not text:
        return text
    english = reverse.get(text)
    if english is not None:
        return tr(english)
    if tr(text) != text:                  # an English source string
        return tr(text)
    match = _SUFFIX.match(text)
    if match:
        head = _again(match.group(1), reverse)
        if head != match.group(1):
            return f"{head} {match.group(2)}"
    return text


def retranslate_tree(root: QWidget, previous: dict[str, str]) -> None:
    """Translate every UI text under ``root`` again; ``previous`` is the
    catalog of the language being left (i18n.catalog() before the switch)."""
    reverse = {}
    for english, translated in previous.items():
        reverse.setdefault(translated, english)

    def again(text: str) -> str:
        return _again(text, reverse)

    widgets = [root] + root.findChildren(QWidget)
    for widget in widgets:
        for action in widget.actions():
            action.setText(again(action.text()))
            action.setToolTip(again(action.toolTip()))
        if isinstance(widget, QAbstractButton):
            widget.setText(again(widget.text()))
        if isinstance(widget, (QAbstractButton, QLabel)):
            widget.setToolTip(again(widget.toolTip()))
        if isinstance(widget, QLabel) and not widget.text().startswith("<"):
            widget.setText(again(widget.text()))
        if isinstance(widget, QTabWidget):
            for i in range(widget.count()):
                widget.setTabText(i, again(widget.tabText(i)))
                widget.setTabToolTip(i, again(widget.tabToolTip(i)))
        if isinstance(widget, QTableWidget):
            for i in range(widget.columnCount()):
                item = widget.horizontalHeaderItem(i)
                if item is not None:
                    item.setText(again(item.text()))
        if isinstance(widget, QTreeWidget):
            header = widget.headerItem()
            for i in range(header.columnCount()):
                header.setText(i, again(header.text(i)))
        if isinstance(widget, (QDockWidget, QToolBar)):
            widget.setWindowTitle(again(widget.windowTitle()))
        if isinstance(widget, QGroupBox):
            widget.setTitle(again(widget.title()))
        if isinstance(widget, QMenu):
            widget.setTitle(again(widget.title()))
        if isinstance(widget, QLineEdit):
            widget.setPlaceholderText(again(widget.placeholderText()))
