# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Help ▸ About IngeCAD names the people whose work is in the program, as
IngeTrazo's does, and AUTHORS says the same."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer


def test_about_rolls_every_contributor_and_authors_lists_them(qapp, monkeypatch):
    from views import about_dialog

    shown = []
    real_exec = about_dialog.AboutDialog.exec

    def fake_exec(dialog):
        # read it before exec(): it is deleted on close; shown, so the
        # roll knows its height
        dialog.show()
        qapp.processEvents()
        start = dialog.credits.offset
        dialog.credits.tick()
        shown.append((dialog.credits._copies[0].text(),
                      dialog.credits.offset != start))
        QTimer.singleShot(0, dialog.accept)
        return real_exec(dialog)

    monkeypatch.setattr(about_dialog.AboutDialog, "exec", fake_exec)
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        win._show_about()
        ((text, rolled),) = shown
        authors = (Path(__file__).resolve().parent.parent / "AUTHORS").read_text(
            encoding="utf-8")
        for name, _role, _link in about_dialog.CONTRIBUTORS:
            assert name in text
            assert name in authors, f"{name} is missing from AUTHORS"
        assert rolled, "the credits do not roll"
    finally:
        win.close()
