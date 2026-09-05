# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Tools > Plugins...: the manager (docs/plugins.md).

The QGIS shape without the store: one row per plugin found, a checkbox
that turns it on or off at once, and the description of the selected one.
A plugin that cannot run (a module it needs is missing, or it failed to
load) is listed greyed out with the reason, never hidden.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from core.i18n import tr


class PluginsDialog(QDialog):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.manager = window.plugins
        self.setWindowTitle(tr("Plugins"))
        self.resize(520, 360)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("A plugin adds a menu of its own. Turn it "
                                   "off and everything it added goes away.")))
        self.list = QListWidget(self)
        layout.addWidget(self.list, 1)
        self.details = QLabel(self)
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.details)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self._fill()
        self.list.itemChanged.connect(self._toggled)
        self.list.currentItemChanged.connect(lambda cur, _prev: self._describe(cur))
        if self.list.count():
            self.list.setCurrentRow(0)

    def _fill(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for pid, loaded in sorted(self.manager.loaded.items()):
            spec = loaded.spec
            name = tr(spec.name) if spec is not None else pid
            text = f"{name}  ({tr('Version {v}', v=spec.version)})" if spec else name
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, pid)
            if loaded.available:
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable
                              | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if self.manager.is_active(pid)
                                   else Qt.Unchecked)
            else:
                item.setText(f"{text} — {tr('unavailable: {reason}', reason=loaded.reason)}")
                item.setFlags(Qt.ItemIsSelectable)      # greyed, uncheckable
            self.list.addItem(item)
        self.list.blockSignals(False)
        if not self.list.count():
            self.details.setText(tr("No plugins found."))

    def _toggled(self, item: QListWidgetItem) -> None:
        pid = item.data(Qt.UserRole)
        self.manager.set_enabled(pid, item.checkState() == Qt.Checked)

    def _describe(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        loaded = self.manager.loaded.get(item.data(Qt.UserRole))
        if loaded is None:
            return
        lines = []
        if loaded.spec is not None and loaded.spec.description:
            lines.append(tr(loaded.spec.description))
        lines.append(tr("Bundled with IngeCAD") if loaded.bundled
                     else tr("Installed by you"))
        lines.append(tr("Location: {path}", path=str(loaded.location)))
        if not loaded.available:
            lines.append(tr("unavailable: {reason}", reason=loaded.reason))
        self.details.setText("\n".join(lines))
