# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""IngeCAD main window — classic pre-ribbon layout.

Menu bar + (from Phase 3) dockable toolbars, command line at the bottom, and a
status bar with coordinate readout and mode toggles. The ribbon does not exist
and will never exist here.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import QLabel, QMainWindow

from core import i18n
from core.i18n import tr
from core.version import __version__
from views.viewport import Viewport


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"IngeCAD — {tr('Untitled')}")
        self.resize(1280, 800)

        self.viewport = Viewport(self)
        self.setCentralWidget(self.viewport)

        self._build_menus()
        self._build_status_bar()
        self.viewport.cursorMoved.connect(self._on_cursor_moved)

    # -- chrome ---------------------------------------------------------------
    def _build_menus(self) -> None:
        menu_bar = self.menuBar()
        menu_bar.clear()

        file_menu = menu_bar.addMenu(tr("File"))
        quit_act = QAction(tr("Quit"), self)
        quit_act.setShortcut(QKeySequence.Quit)
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        view_menu = menu_bar.addMenu(tr("View"))
        extents_act = QAction(tr("Zoom Extents"), self)
        extents_act.triggered.connect(self.viewport.zoom_extents)
        view_menu.addAction(extents_act)

        tools_menu = menu_bar.addMenu(tr("Tools"))
        lang_menu = tools_menu.addMenu(tr("Language"))
        lang_group = QActionGroup(self)
        # Each language is listed in its own name — recognizable no matter
        # which language is currently active.
        for code, native_name in (("en", "English"), ("es", "Español")):
            act = QAction(native_name, self)
            act.setCheckable(True)
            act.setChecked(i18n.current_language() == code)
            act.triggered.connect(lambda _=False, c=code: self._set_language(c))
            lang_group.addAction(act)
            lang_menu.addAction(act)

    def _set_language(self, code: str) -> None:
        """Switch the UI language, persist it, and retranslate live."""
        if code == i18n.current_language():
            return
        QSettings().setValue("language", code)
        i18n.set_language(code)
        self._retranslate()

    def _retranslate(self) -> None:
        self.setWindowTitle(f"IngeCAD — {tr('Untitled')}")
        self._build_menus()

    def _build_status_bar(self) -> None:
        # Coordinate readout, bottom-left — the classic AutoCAD tracker.
        self._coords_label = QLabel("0.0000, 0.0000")
        self._coords_label.setMinimumWidth(220)
        self.statusBar().addWidget(self._coords_label)
        self.statusBar().addPermanentWidget(QLabel(f"IngeCAD {__version__}"))

    def _on_cursor_moved(self, wx: float, wy: float) -> None:
        self._coords_label.setText(f"{wx:.4f}, {wy:.4f}")

    # -- documents (entry point wired now; import lands in Phase 1/2) ---------
    def open_path(self, path: Path) -> None:
        """OS file associations and argv[1] land here."""
        self.statusBar().showMessage(
            tr("Cannot open {name} yet — file import lands in Phase 1", name=path.name),
            5000,
        )
