# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""File tabs: several drawings open in one window (#71).

AutoCAD keeps every open drawing in the same window, one tab each, above
the drawing area; Open and New add a tab, and the untouched "Drawing1"
gives its place to the first file opened. CLOSE closes the current
drawing, CLOSEALL all of them (Command Reference pp. 335-336), Ctrl+Tab
goes to the next one, and the Window menu lists them.

The window keeps ONE set of widgets -- canvas, command line, panels -- and
each tab is a ``DocumentSession``: the drawing plus everything the window
holds for it (undo and redo, the built scene of each layout, the active
layout, the camera and its zoom-previous stack). Switching stashes the
session going out and restores the one coming in; a tab already drawn
comes back without a regen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QToolButton, QVBoxLayout, QWidget

from core.i18n import tr

@dataclass(eq=False)
class DocumentSession:
    """One open drawing and what the window keeps for it while away."""

    document: object
    #: Tells the automatic saves of two tabs apart (two "Untitled", or two
    #: "plano.dwg" from different folders, would write the same .sv$).
    slot: int = 1
    undo: list = field(default_factory=list)
    redo: list = field(default_factory=list)
    layout_scenes: dict = field(default_factory=dict)
    active_layout: str = "Model"
    regen_ms: dict = field(default_factory=dict)
    layout_cameras: dict = field(default_factory=dict)
    camera: Optional[tuple] = None          # (cx, cy, scale)
    view_stack: list = field(default_factory=list)
    #: an open Block Editor stays open in its own tab, as in AutoCAD
    block_session: object = None
    bedit_return_tab: Optional[str] = None

    def pristine(self) -> bool:
        """AutoCAD's Drawing1 rule: a new drawing nobody touched gives its
        place to the next one opened."""
        doc = self.document
        if doc is None:
            return True
        return (doc.path is None and not doc.dirty and not self.undo
                and not self.redo and len(doc.doc.modelspace()) == 0)


class FileTabBar(QWidget):
    """The strip of drawing tabs above the canvas: name, a close button,
    and "+" for a new drawing at the end -- AutoCAD's File Tabs."""

    STYLE = """
    QWidget#file_tabs { background: #1e1e22; }
    QToolButton { border: 1px solid #3a3a42; border-bottom: none;
        padding: 2px 10px; color: #9a9a9a; font-size: 11px;
        background: #2a2a2e; }
    QToolButton:hover { color: #d0d0d0; }
    QToolButton:checked { color: #f0f0f0; background: #35424f; }
    QToolButton#file_tab_close { padding: 2px 4px; border-left: none; }
    """

    def __init__(self, window) -> None:
        super().__init__(window)
        self.setObjectName("file_tabs")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(self.STYLE)
        self._window = window
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(4, 2, 4, 0)
        self._row.setSpacing(1)
        #: the tab buttons, aligned with the window's sessions
        self.buttons: list[QToolButton] = []
        self.plus: Optional[QToolButton] = None

    def refresh(self, sessions, current) -> None:
        while self._row.count():
            item = self._row.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.buttons = []
        window = self._window
        for session in sessions:
            doc = session.document
            name = doc.name if doc is not None else tr("Untitled")
            button = QToolButton(self)
            button.setText(name)
            path = getattr(doc, "path", None)
            button.setToolTip(str(path) if path else name)
            button.setCheckable(True)
            button.setChecked(session is current)
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(
                lambda _=False, s=session: window.switch_document(s))
            button.setContextMenuPolicy(Qt.CustomContextMenu)
            button.customContextMenuRequested.connect(
                lambda pos, s=session, b=button: window.file_tab_menu(
                    s, b.mapToGlobal(pos)))
            close = QToolButton(self)
            close.setObjectName("file_tab_close")
            close.setText("×")
            close.setToolTip(tr("Close"))
            close.setFocusPolicy(Qt.NoFocus)
            close.clicked.connect(
                lambda _=False, s=session: window.close_document(s))
            self._row.addWidget(button)
            self._row.addWidget(close)
            self.buttons.append(button)
        self.plus = QToolButton(self)
        self.plus.setText("+")
        self.plus.setToolTip(tr("New drawing"))
        self.plus.setFocusPolicy(Qt.NoFocus)
        self.plus.clicked.connect(lambda _=False: window.new_document())
        self._row.addWidget(self.plus)
        self._row.addStretch(1)


def central_widget(window, viewport) -> tuple[QWidget, FileTabBar]:
    """The tab strip on top of the canvas, as one central widget."""
    host = QWidget(window)
    column = QVBoxLayout(host)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(0)
    bar = FileTabBar(host)
    bar._window = window
    column.addWidget(bar)
    column.addWidget(viewport, 1)
    return host, bar


class DocumentTabsMixin:
    """MainWindow's side of the file tabs."""

    # -- bookkeeping -------------------------------------------------------------
    def _tabs_init(self) -> None:
        self._sessions: list[DocumentSession] = []
        self._session: Optional[DocumentSession] = None

    def document_sessions(self) -> list:
        return list(self._sessions)

    def current_session(self) -> Optional[DocumentSession]:
        return self._session

    def _stash_session(self) -> None:
        """Keep what the window holds for the drawing going out of view."""
        session = self._session
        if session is None:
            return
        history = self.history
        session.document = self.document
        session.undo, session.redo = history._undo, history._redo
        history._undo, history._redo = [], []
        session.layout_scenes = self._layout_scenes
        session.active_layout = self._active_layout
        session.regen_ms = self._regen_ms
        self._remember_tab_view()
        session.layout_cameras = self._layout_cameras
        view = self.viewport.view
        session.camera = (view.cx, view.cy, view.scale)
        session.view_stack = list(self.viewport._view_stack)
        self._layout_scenes, self._regen_ms = {}, {}
        self._layout_cameras = {}
        session.block_session = self._block_session
        session.bedit_return_tab = getattr(self, "_bedit_return_tab", None)
        self._drop_block_session()      # the window's editor, not the drawing's

    def _tab_for_new_document(self, document) -> None:
        """New or Open: a tab of its own, or the untouched Drawing1's."""
        # A command halfway belongs to the drawing it started in: left
        # running, WBLOCK went on to act on the new one (Rafael's sixth
        # review). Ended here, while the window still holds its drawing.
        tools = getattr(self, "tools", None)
        if tools is not None:
            tools.cancel()
        current = self._session
        if current is not None and current.pristine():
            self._drop_block_session()
            self._autosave_discard()
            current.document = document
            current.undo, current.redo = [], []
            self.history._undo, self.history._redo = [], []
            self._layout_scenes, self._regen_ms = {}, {}
            self._layout_cameras = {}
            return
        self._stash_session()
        taken = {s.slot for s in self._sessions}
        session = DocumentSession(document,
                                  slot=min(set(range(1, len(taken) + 2)) - taken))
        index = (self._sessions.index(current) + 1
                 if current in self._sessions else len(self._sessions))
        self._sessions.insert(index, session)
        self._session = session

    def _session_for_path(self, path) -> Optional[DocumentSession]:
        """The open drawing saved at ``path``, or None."""
        try:
            wanted = Path(path).resolve()
        except OSError:
            return None
        for session in self._sessions:
            document = (self.document if session is self._session
                        else session.document)
            own = getattr(document, "path", None)
            if own is None:
                continue
            try:
                if Path(own).resolve() == wanted:
                    return session
            except OSError:
                continue
        return None

    # -- switching ---------------------------------------------------------------
    def switch_document(self, session) -> bool:
        """Show another open drawing (True once it is in view)."""
        if session is self._session or session not in self._sessions:
            self._refresh_file_tabs()
            return session is self._session
        self.tools.cancel()
        self._deactivate_viewport()
        self._stash_session()
        self._restore_session(session)
        return True

    def _restore_session(self, session) -> None:
        self._session = session
        document = session.document
        self.document = document
        self.history._undo, self.history._redo = session.undo, session.redo
        self._layout_scenes = session.layout_scenes
        self._regen_ms = session.regen_ms
        self._layout_cameras = session.layout_cameras
        self._active_layout = session.active_layout
        self._block_session = session.block_session
        self._bedit_return_tab = session.bedit_return_tab
        session.block_session = None
        self.tools.attach_document(document, keep_history=True)
        viewport = self.viewport
        if session.camera is not None:
            viewport.view.cx, viewport.view.cy, viewport.view.scale = session.camera
        viewport._view_stack = list(session.view_stack)
        cached = self._layout_scenes.get(self._active_layout)
        if cached is not None and cached[0] == document.revision:
            viewport.set_scene(cached[1])
            self.tools.mark_scene_merged()
        else:
            viewport.set_scene(None)
            self._regen_zoom = session.camera is None
            if self._regen_worker is not None:
                self._regen_rerun = True     # the other drawing's regen
            else:
                self._start_regen()
        self._autosave_arm()
        self._refresh_layout_tabs()
        self._update_space_button()
        self.refresh_grid_settings()
        self._refresh_document_panels()
        block = self._block_session
        self._blockedit_toolbar.setVisible(block is not None)
        if block is not None:
            self._blockedit_label.setText(tr("Block: {name}", name=block.name))
            self.setWindowTitle(f"IngeCAD — {document.name} — "
                                + tr("Block Editor: {name}", name=block.name))
        else:
            self.setWindowTitle(f"IngeCAD — {document.name}")
        self._refresh_file_tabs()
        viewport.update()

    def step_document(self, step: int) -> None:
        """Ctrl+Tab / Ctrl+Shift+Tab: the next or previous drawing."""
        if len(self._sessions) < 2 or self._session not in self._sessions:
            return
        index = self._sessions.index(self._session)
        self.switch_document(self._sessions[(index + step) % len(self._sessions)])

    # -- closing -----------------------------------------------------------------
    def close_document(self, session=None) -> bool:
        """CLOSE: the current drawing (or ``session``), asking to save it
        first. The last one closed leaves a new empty drawing, as the
        window always shows one."""
        session = session or self._session
        if session not in self._sessions:
            return False
        if session is not self._session and not self.switch_document(session):
            return False
        if not self.maybe_save_changes():
            return False
        self._autosave_discard()
        index = self._sessions.index(session)
        self._sessions.remove(session)
        self._session = None
        self.history._undo, self.history._redo = [], []
        if not self._sessions:
            self.new_document()
            return True
        self._restore_session(self._sessions[min(index, len(self._sessions) - 1)])
        return True

    def close_all_documents(self) -> bool:
        """CLOSEALL: every drawing, each asked about in turn; Cancel stops."""
        for session in list(self._sessions):
            if not self.close_document(session):
                return False
        return True

    def close_others(self, keep) -> bool:
        for session in [s for s in self._sessions if s is not keep]:
            if not self.close_document(session):
                return False
        return True

    def maybe_save_all(self) -> bool:
        """Leaving the window: each modified drawing asks, as AutoCAD's
        QUIT does; the one in view first, then the others."""
        if not self.maybe_save_changes():
            return False
        for session in list(self._sessions):
            if session is self._session or not session.document.dirty:
                continue
            if not self.switch_document(session) or not self.maybe_save_changes():
                return False
        return True

    # -- the strip and the menus -------------------------------------------------
    def _refresh_file_tabs(self) -> None:
        bar = getattr(self, "_file_tabs", None)
        if bar is not None:
            bar.refresh(self._sessions, self._session)
        self._refresh_window_menu()

    def _refresh_window_menu(self) -> None:
        menu = getattr(self, "_window_documents_menu", None)
        if menu is None:
            return
        from PySide6.QtGui import QAction

        for action in getattr(self, "_window_document_actions", []):
            menu.removeAction(action)
            action.deleteLater()
        self._window_document_actions = []
        for number, session in enumerate(self._sessions, 1):
            doc = session.document
            label = f"&{number} {doc.name}" if number < 10 else doc.name
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(session is self._session)
            action.triggered.connect(
                lambda _=False, s=session: self.switch_document(s))
            menu.addAction(action)
            self._window_document_actions.append(action)

    def file_tab_menu(self, session, global_pos) -> None:
        """Right-click on a drawing tab: AutoCAD's file tab menu."""
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        menu.addAction(tr("New"), self.new_document)
        menu.addAction(tr("Open..."), self._open_dialog)
        menu.addAction(tr("Save"),
                       lambda: self.switch_document(session) and self.save_document())
        menu.addSeparator()
        menu.addAction(tr("Close"), lambda: self.close_document(session))
        menu.addAction(tr("Close All"), self.close_all_documents)
        others = menu.addAction(tr("Close All Other Drawings"),
                                lambda: self.close_others(session))
        others.setEnabled(len(self._sessions) > 1)
        path = getattr(session.document, "path", None)
        if path is not None:
            menu.addSeparator()
            menu.addAction(tr("Copy Full File Path"),
                           lambda: self._copy_path(path))
            menu.addAction(tr("Open File Location"),
                           lambda: self._open_location(path))
        menu.exec(global_pos)

    @staticmethod
    def _copy_path(path) -> None:
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.clipboard().setText(str(path))

    @staticmethod
    def _open_location(path) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
