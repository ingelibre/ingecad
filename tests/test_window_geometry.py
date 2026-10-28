# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The window comes back as it was closed (#72, Rafael): IngeCAD always
reopened at 1280 x 800, where IngeTrazo remembers its size."""
from __future__ import annotations

from PySide6.QtCore import QSettings


def test_the_next_session_opens_at_the_size_the_last_one_closed(qapp):
    from views.main_window import SETTING_WINDOW_GEOMETRY, MainWindow

    QSettings().remove(SETTING_WINDOW_GEOMETRY)
    first = MainWindow()
    first.new_document()
    first.resize(700, 520)       # inside the offscreen 800 x 600 screen
    first.show()
    qapp.processEvents()
    # what the window really took: on Windows its minimum width is ~800
    closed_at = (first.width(), first.height())
    first.document.dirty = False
    first.close()
    qapp.processEvents()

    fresh = MainWindow()                     # a test window keeps the default
    assert (fresh.width(), fresh.height()) == (1280, 800)
    fresh.close()

    again = MainWindow()                     # what main.py does at start-up
    assert again.restore_window_geometry()
    again.show()
    qapp.processEvents()
    try:
        assert (again.width(), again.height()) == closed_at
    finally:
        again.close()
        QSettings().remove(SETTING_WINDOW_GEOMETRY)


def test_main_restores_the_geometry_before_showing(monkeypatch):
    # the start-up path itself calls it, before show()
    import inspect

    import main

    source = inspect.getsource(main.main)
    restore = source.index("restore_window_geometry()")
    assert restore < source.index("window.show()")
