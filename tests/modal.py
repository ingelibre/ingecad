# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Drive exec()'d dialogs from a test, the way a user's clicks arrive."""
from __future__ import annotations

import time


def drive_modal(cls, action, errors, timeout=5.0):
    """Wait for the modal dialog of class ``cls`` and run ``action`` on it.

    The dialogs are exec()'d, so the test cannot hold them: it polls from the
    event loop the modal itself spins. A failing ``action`` is kept in
    ``errors`` and its dialog rejected, so a regression fails the test
    instead of leaving a modal that hangs it.
    """
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    started = time.monotonic()

    def poll():
        modal = QApplication.activeModalWidget()
        if isinstance(modal, cls):
            try:
                action(modal)
            except BaseException as exc:      # noqa: BLE001 -- re-raised by the test
                errors.append(exc)
                if modal.isVisible():
                    modal.reject()
        elif time.monotonic() - started < timeout:
            QTimer.singleShot(20, poll)

    QTimer.singleShot(0, poll)
