# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Where the right sidebar ends.

Qt gives both bottom corners to the BOTTOM dock area by default, so the
command window ran the full width of the frame and cut the sidebar short --
"la barra de comandos ocupa un espacio de la barra lateral derecha".
"""
from __future__ import annotations

from PySide6.QtCore import Qt


def _window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    for _ in range(30):
        qapp.processEvents()
    return win


def test_the_sidebar_runs_to_the_bottom_and_the_command_bar_stops_at_it(qapp):
    win = _window(qapp)
    try:
        side = win._layers_dock.geometry()
        cmd = win._command_dock.geometry()
        assert side.height() > 0 and cmd.width() > 0, "no layout was computed"
        assert side.bottom() >= cmd.bottom(), (
            f"the sidebar stops at {side.bottom()} while the command window "
            f"reaches {cmd.bottom()}")
        assert cmd.right() <= side.left(), (
            "the command window still runs under the sidebar")
        # and the corner that decides it, so a future refactor says why
        assert win.corner(Qt.BottomRightCorner) == Qt.RightDockWidgetArea
    finally:
        win.close()
