# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The status bar's selection filter: tick the object types a pick may
take (core.pickfilter). Every tick applies at once; ticking them all
switches the filter off."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout)

from core import pickfilter
from core.i18n import tr


class PickFilterPopup(QFrame):
    def __init__(self, window) -> None:
        super().__init__(window, Qt.Popup)
        self.window = window
        self.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        self.list = QListWidget(self)
        layout.addWidget(self.list)
        buttons = QHBoxLayout()
        self.all_btn = QPushButton(tr("Select all"), self)
        self.none_btn = QPushButton(tr("Clear all"), self)
        buttons.addWidget(self.all_btn)
        buttons.addWidget(self.none_btn)
        layout.addLayout(buttons)
        self.all_btn.clicked.connect(lambda: self._tick_all(True))
        self.none_btn.clicked.connect(lambda: self._tick_all(False))

        document = window.document
        present = (pickfilter.labels_in(document.current_space())
                   if document is not None else [])
        allowed = window.tools.pick_filter
        # an unticked type stays listed even if none is left in the drawing
        labels = sorted(set(present) | set(allowed or ()))
        self.list.blockSignals(True)
        for label in labels:
            item = QListWidgetItem(pickfilter.display(label), self.list)
            item.setData(Qt.UserRole, label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            on = allowed is None or label in allowed
            item.setCheckState(Qt.Checked if on else Qt.Unchecked)
        self.list.blockSignals(False)
        self.list.itemChanged.connect(lambda _item: self._apply())
        rows = max(1, min(len(labels), 14))
        row_height = self.list.sizeHintForRow(0) if labels else 20
        self.list.setFixedHeight(rows * row_height + 2 * self.list.frameWidth() + 4)
        self.setMinimumWidth(200)

    def _items(self) -> list:
        return [self.list.item(i) for i in range(self.list.count())]

    def _tick_all(self, on: bool) -> None:
        self.list.blockSignals(True)
        for item in self._items():
            item.setCheckState(Qt.Checked if on else Qt.Unchecked)
        self.list.blockSignals(False)
        self._apply()

    def _apply(self) -> None:
        items = self._items()
        ticked = {i.data(Qt.UserRole) for i in items if i.checkState() == Qt.Checked}
        everything = len(ticked) == len(items)
        self.window.set_pick_filter(None if everything else ticked)
