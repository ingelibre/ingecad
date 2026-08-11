# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Object Snap settings — AutoCAD's Drafting Settings, Object Snap tab.

The list is the one the status-bar dropdown shows, with the same marker
glyph beside each mode so the tick and the thing that appears on screen are
recognisably the same object. Modes that are not implemented are listed
disabled with the reason, rather than offered as a tick that does nothing.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from core import osnap as osnap_modes
from core.i18n import tr

MARKER_PX = 16


def marker_icon(kind: str, checked: bool | None = None) -> QIcon:
    """The AutoSnap glyph for a mode, drawn like the viewport draws it.

    ``checked`` composes AutoCAD's tick to the left of the glyph. Qt draws
    either a checkmark or an icon in a menu, never both, so the tick has to
    live inside the pixmap for the list to read like AutoCAD's.
    """
    from PySide6.QtCore import QPointF
    from views.viewport import Viewport

    width = MARKER_PX if checked is None else MARKER_PX * 2
    pixmap = QPixmap(width, MARKER_PX)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    if checked:
        painter.setPen(QPen(Qt.white, 1.6))
        painter.drawLine(QPointF(2, 8), QPointF(5, 12))
        painter.drawLine(QPointF(5, 12), QPointF(11, 4))
    from core.snap import PRIORITY

    if kind in PRIORITY:
        painter.setPen(QPen(Viewport.MARKER_COLOR, 1.2))
        # Borrow the viewport's own painter so the two can never drift
        # apart; a mode with no marker of its own draws nothing rather than
        # borrowing someone else's.
        Viewport._draw_snap_marker(_MarkerStub(), painter, kind,
                                   width - MARKER_PX / 2, MARKER_PX / 2)
    painter.end()
    return QIcon(pixmap)


class _MarkerStub:
    """Just enough of a Viewport for _draw_snap_marker: its marker size."""

    from views.viewport import Viewport as _V

    MARKER_SIZE = _V.MARKER_SIZE * 0.8
    MARKER_COLOR = _V.MARKER_COLOR


class OsnapSettingsDialog(QDialog):
    """Tick the running snaps. Returns the chosen keys via ``modes()``."""

    def __init__(self, parent, active, enabled: bool = True) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Drafting Settings"))
        self._boxes: dict[str, QCheckBox] = {}

        self.enabled = QCheckBox(tr("Object Snap On (F3)"))
        self.enabled.setChecked(bool(enabled))

        group = QGroupBox(tr("Object Snap modes"))
        grid = QGridLayout(group)
        for index, mode in enumerate(osnap_modes.MODES):
            box = QCheckBox(tr(mode.label))
            box.setIcon(marker_icon(mode.key))
            box.setIconSize(QSize(MARKER_PX, MARKER_PX))
            box.setChecked(mode.key in active)
            if not mode.available:
                box.setChecked(False)
                box.setEnabled(False)
                box.setToolTip(tr(mode.note))
            self._boxes[mode.key] = box
            grid.addWidget(box, index % 7, index // 7)

        select_all = QPushButton(tr("Select All"))
        select_all.clicked.connect(lambda: self._set_all(True))
        clear_all = QPushButton(tr("Clear All"))
        clear_all.clicked.connect(lambda: self._set_all(False))
        side = QVBoxLayout()
        side.addWidget(select_all)
        side.addWidget(clear_all)
        side.addStretch(1)

        middle = QHBoxLayout()
        middle.addWidget(group, 1)
        middle.addLayout(side)

        # Only claims that are true: an invented shortcut in a settings
        # dialog is a bug report waiting to happen.
        hint = QLabel(tr("F3 switches object snap off without losing which "
                         "modes are ticked here."))
        hint.setStyleSheet("color: #9aa0a6;")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.enabled)
        layout.addLayout(middle, 1)
        layout.addWidget(hint)
        layout.addWidget(buttons)

    def _set_all(self, state: bool) -> None:
        for key, box in self._boxes.items():
            if box.isEnabled():
                box.setChecked(state)

    def modes(self) -> set:
        return {key for key, box in self._boxes.items()
                if box.isEnabled() and box.isChecked()}

    def osnap_on(self) -> bool:
        return self.enabled.isChecked()
