# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The startup window: pick a template, or reopen a recent drawing.

Two questions, side by side, the way BricsCAD asks them. On the left the
unit the new drawing will be in — the decision that is cheap now and
expensive later (see ``core.templates``). On the right the drawings you had
open, with the picture of each one, because a plan is recognised by its
shape long before its file name is read.

Thumbnails arrive on a worker thread: a DWG's built-in preview is instant,
but a DXF has to be drawn, which costs seconds on a real plan. The list
shows its entries immediately and the pictures land as they are made.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import recent as recent_mod
from core import templates as templates_mod
from core.i18n import tr
from core.version import __version__
from views import file_dialogs

THUMB_VIEW = QSize(160, 100)

SETTING_SHOW = "startup/show"
SETTING_TEMPLATE = "startup/template"


class _ThumbnailWorker(QThread):
    """Builds thumbnails off the UI thread, one drawing at a time."""

    ready = Signal(str, str)          # drawing path, thumbnail path

    def __init__(self, paths: list[Path]) -> None:
        super().__init__()
        self._paths = list(paths)
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        from formats import thumbnails

        for path in self._paths:
            if self._stop:
                return
            try:
                made = thumbnails.generate(path)
            except Exception:
                made = None           # a broken drawing must not kill startup
            if made and not self._stop:
                self.ready.emit(str(path), str(made))


class StartupDialog(QDialog):
    """Returns what to do: ``('new', key)``, ``('open', path)`` or None."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("IngeCAD"))
        self.setMinimumSize(760, 420)
        self._choice = None
        self._worker: _ThumbnailWorker | None = None

        heading = QLabel(f"IngeCAD {__version__}")
        heading.setStyleSheet("font-size: 20px; font-weight: 600;")
        subtitle = QLabel(tr("Start a drawing, or pick up where you left off."))
        subtitle.setStyleSheet("color: #9aa0a6;")

        # -- templates --------------------------------------------------------
        self.templates = QListWidget()
        self.templates.setAlternatingRowColors(True)
        # Two lines per entry, so the description has to wrap rather than
        # run off behind a horizontal scrollbar.
        self.templates.setWordWrap(True)
        self.templates.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.templates.setMinimumWidth(300)
        for template in templates_mod.BUILTIN_TEMPLATES:
            item = QListWidgetItem(
                f"{tr(template.name)}\n{tr(template.description)}")
            item.setData(Qt.UserRole, template.key)
            self.templates.addItem(item)
        self.templates.itemDoubleClicked.connect(self._start_template)

        browse = QPushButton(tr("Use another drawing as a template..."))
        browse.clicked.connect(self._browse_template)

        left = QVBoxLayout()
        left.addWidget(_section(tr("New drawing")))
        left.addWidget(self.templates, 1)
        left.addWidget(browse)

        # -- recent -----------------------------------------------------------
        self.recent = QListWidget()
        self.recent.setViewMode(QListWidget.IconMode)
        self.recent.setIconSize(THUMB_VIEW)
        self.recent.setGridSize(QSize(THUMB_VIEW.width() + 30,
                                      THUMB_VIEW.height() + 46))
        self.recent.setResizeMode(QListWidget.Adjust)
        self.recent.setMovement(QListWidget.Static)
        self.recent.setWordWrap(True)
        self.recent.itemDoubleClicked.connect(self._open_recent)

        open_button = QPushButton(tr("Open a drawing..."))
        open_button.clicked.connect(self._open_dialog)

        right = QVBoxLayout()
        right.addWidget(_section(tr("Recent drawings")))
        right.addWidget(self.recent, 1)
        right.addWidget(open_button)

        columns = QHBoxLayout()
        columns.addLayout(left, 3)
        columns.addLayout(right, 4)

        self.show_again = QCheckBox(tr("Show this window at startup"))
        self.show_again.setChecked(True)
        start = QPushButton(tr("Start drawing"))
        start.setDefault(True)
        start.clicked.connect(self._start_selected)
        bottom = QHBoxLayout()
        bottom.addWidget(self.show_again)
        bottom.addStretch(1)
        bottom.addWidget(start)

        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addWidget(subtitle)
        layout.addLayout(columns, 1)
        layout.addLayout(bottom)

        self._load_settings()
        self._fill_recent()

    # -- results ---------------------------------------------------------------
    def choice(self):
        return self._choice

    def selected_template(self) -> str:
        item = self.templates.currentItem()
        return item.data(Qt.UserRole) if item else templates_mod.DEFAULT_TEMPLATE

    # -- population ------------------------------------------------------------
    def _fill_recent(self) -> None:
        from formats import thumbnails

        paths = recent_mod.load()
        self.recent.clear()
        if not paths:
            empty = QListWidgetItem(tr("Nothing here yet."))
            empty.setFlags(Qt.NoItemFlags)
            self.recent.addItem(empty)
            return
        missing = []
        for path in paths:
            item = QListWidgetItem(path.name)
            item.setData(Qt.UserRole, str(path))
            item.setToolTip(str(path))
            cached = thumbnails.cached(path)
            if cached:
                item.setIcon(QIcon(str(cached)))
            else:
                item.setIcon(_placeholder_icon())
                missing.append(path)
            self.recent.addItem(item)
        if missing:
            self._worker = _ThumbnailWorker(missing)
            self._worker.ready.connect(self._thumbnail_ready)
            self._worker.start()

    def _thumbnail_ready(self, drawing: str, thumb: str) -> None:
        for row in range(self.recent.count()):
            item = self.recent.item(row)
            if item.data(Qt.UserRole) == drawing:
                item.setIcon(QIcon(thumb))
                return

    # -- actions ---------------------------------------------------------------
    def _start_template(self, item) -> None:
        self._choice = ("new", item.data(Qt.UserRole))
        self._save_settings()
        self.accept()

    def _start_selected(self) -> None:
        current = self.recent.currentItem()
        if current is not None and current.data(Qt.UserRole):
            self._open_recent(current)
            return
        self._choice = ("new", self.selected_template())
        self._save_settings()
        self.accept()

    def _open_recent(self, item) -> None:
        path = item.data(Qt.UserRole)
        if not path:
            return
        self._choice = ("open", Path(path))
        self._save_settings()
        self.accept()

    def _open_dialog(self) -> None:
        filename = file_dialogs.get_open_file(
            self, tr("Open Drawing"),
            tr("Drawings (*.dwg *.dxf);;All files (*)"))
        if filename:
            self._choice = ("open", Path(filename))
            self._save_settings()
            self.accept()

    def _browse_template(self) -> None:
        filename = file_dialogs.get_open_file(
            self, tr("Use another drawing as a template..."),
            tr("Drawings (*.dwg *.dxf);;All files (*)"))
        if filename:
            self._choice = ("template", Path(filename))
            self._save_settings()
            self.accept()

    # -- persistence -----------------------------------------------------------
    def _load_settings(self) -> None:
        from PySide6.QtCore import QSettings

        settings = QSettings()
        self.show_again.setChecked(
            str(settings.value(SETTING_SHOW, "true")).lower() != "false")
        wanted = str(settings.value(SETTING_TEMPLATE,
                                    templates_mod.DEFAULT_TEMPLATE))
        for row in range(self.templates.count()):
            if self.templates.item(row).data(Qt.UserRole) == wanted:
                self.templates.setCurrentRow(row)
                return
        self.templates.setCurrentRow(0)

    def _save_settings(self) -> None:
        from PySide6.QtCore import QSettings

        settings = QSettings()
        settings.setValue(SETTING_SHOW, self.show_again.isChecked())
        if self._choice and self._choice[0] == "new":
            settings.setValue(SETTING_TEMPLATE, self._choice[1])

    def closeEvent(self, event) -> None:
        if self._worker is not None:
            self._worker.stop()
            self._worker.wait(2000)
        super().closeEvent(event)

    def reject(self) -> None:
        self._save_settings()
        super().reject()


def _section(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("font-weight: 600; color: #cfd3d7;")
    return label


def _placeholder_icon() -> QIcon:
    """A blank sheet, shown while the real picture is being made."""
    from PySide6.QtGui import QColor, QPainter, QPen

    pixmap = QPixmap(THUMB_VIEW)
    pixmap.fill(QColor(30, 33, 38))
    painter = QPainter(pixmap)
    painter.setPen(QPen(QColor(70, 74, 80), 1))
    painter.drawRect(8, 8, THUMB_VIEW.width() - 17, THUMB_VIEW.height() - 17)
    painter.end()
    return QIcon(pixmap)


def should_show() -> bool:
    from PySide6.QtCore import QSettings

    return str(QSettings().value(SETTING_SHOW, "true")).lower() != "false"
