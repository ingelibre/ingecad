# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Select Similar Settings dialog (p. 1727): which properties must match
for an object of the same type to count as similar."""
from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)

from core.i18n import tr
from core.similar import DEFAULT_KEYS, PROPERTIES

SETTING_KEYS = "select/similar_keys"


def saved_keys() -> frozenset:
    """The ticked properties, remembered between sessions like AutoCAD's."""
    raw = QSettings().value(SETTING_KEYS, None)
    if raw is None:
        return DEFAULT_KEYS
    known = {key for key, _l, _r in PROPERTIES}
    return frozenset(k for k in str(raw).split(",") if k in known)


def save_keys(keys) -> None:
    QSettings().setValue(SETTING_KEYS, ",".join(sorted(keys)))


class SelectSimilarSettingsDialog(QDialog):
    def __init__(self, parent, keys=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Select Similar Settings"))
        active = set(saved_keys() if keys is None else keys)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            tr("Objects of the same type are similar when these match:"), self))
        self._boxes = {}
        for key, label, _read in PROPERTIES:
            box = QCheckBox(tr(label), self)
            box.setChecked(key in active)
            self._boxes[key] = box
            layout.addWidget(box)
        hint = QLabel(tr("Name applies to blocks; Object style is the text or "
                         "dimension style that draws the object."), self)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #9aa0a6;")
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
                                   self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def keys(self) -> frozenset:
        return frozenset(k for k, box in self._boxes.items() if box.isChecked())
