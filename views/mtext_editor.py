# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The in-place MTEXT editor — step 1 of the AutoCAD editor clone.

The text is edited on the canvas, at its real position and size, with the
drawing visible behind it. The semantics that make it feel right (researched
in docs/reference/draw/autocad-bricscad-mtext-editor.md):

* **Enter is a paragraph break, never a commit.** The dialog it replaces had
  that exactly backwards.
* Commit with **Ctrl+Enter**, the **OK** button, or a **click outside** the
  editor — the three ways both AutoCAD and BricsCAD close theirs.
* **Esc asks before discarding** when something changed, and just closes
  when nothing did.
* Pan and zoom keep working while the editor is open; it stays anchored to
  the text (a light timer re-derives its geometry from the view).

Step-1 limitations, deliberate and visible rather than guessed at:
inline formatting codes (``\\H``, ``{\\f...}``…) show as raw text — the same
thing AutoCAD does when MTEXTED points at an external editor — so a
colleague's formatted note round-trips unchanged if you don't touch those
parts. Only ``\\P`` is translated (to a real line break and back). Rotated
MTEXT is edited horizontally, which is AutoCAD's own MTEXTFIXED=2 fallback.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QKeySequence, QTextOption
from PySide6.QtWidgets import (
    QApplication,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.i18n import tr

# The editor frame: AutoCAD draws a thin frame around the editing area.
_FRAME = """
MTextInPlaceEditor { background: transparent; }
QTextEdit {
    background: rgba(30, 33, 38, 205);
    color: #e8e8e8;
    border: 1px solid #6a86a8;
}
QPushButton {
    background: #35424f; color: #e8e8e8; border: 1px solid #4a5a6a;
    padding: 1px 10px; font-size: 11px;
}
QPushButton:hover { background: #3d4c5b; }
"""

MIN_WIDTH_PX = 120
MIN_HEIGHT_PX = 34


def to_editor_text(mtext_content: str) -> str:
    r"""MTEXT stream -> editable text: only \P becomes a newline.

    Everything else (inline codes, braces) stays literal, so content we do
    not understand yet survives an edit that does not touch it.
    """
    return mtext_content.replace("\\P", "\n")


def from_editor_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\n", "\\P")


class MTextInPlaceEditor(QWidget):
    """One editing session over the viewport. Commit/cancel via callbacks."""

    def __init__(self, viewport, *, top_left, width_world: float,
                 char_height: float, text: str = "",
                 on_commit: Callable[[str], None],
                 on_cancel: Optional[Callable[[], None]] = None,
                 single_line: bool = False) -> None:
        super().__init__(viewport)
        self._viewport = viewport
        self._top_left = top_left
        self._width_world = float(width_world)
        self._char_height = float(char_height)
        self._on_commit = on_commit
        self._on_cancel = on_cancel or (lambda: None)
        self._single_line = single_line
        self._closed = False

        self.setObjectName("MTextInPlaceEditor")
        self.setStyleSheet(_FRAME)

        self.edit = QTextEdit(self)
        self.edit.setAcceptRichText(False)
        self.edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.edit.setPlainText(to_editor_text(text))
        self._initial = self.edit.toPlainText()
        option = QTextOption()
        option.setWrapMode(QTextOption.NoWrap if single_line
                           else QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.edit.document().setDefaultTextOption(option)
        self.edit.document().setDocumentMargin(2)
        self.edit.textChanged.connect(self._sync_geometry)
        self.edit.installEventFilter(self)

        self.ok = QPushButton(tr("OK"), self)
        self.ok.setToolTip(tr("Save and close (Ctrl+Enter)"))
        self.ok.setFocusPolicy(Qt.NoFocus)
        self.ok.clicked.connect(self.commit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        layout.addWidget(self.ok, alignment=Qt.AlignRight)
        layout.addWidget(self.edit, 1)

        # A click anywhere that is not ours commits, like clicking outside
        # AutoCAD's editor. App-level: the command line and panels count as
        # "outside" too.
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        # Stay anchored to the text through pan/zoom: geometry is a pure
        # function of the view, re-derived on a light timer (30 Hz of a few
        # float ops), which covers every pan/zoom path without hooking them.
        self._anchor_timer = QTimer(self)
        self._anchor_timer.setInterval(33)
        self._anchor_timer.timeout.connect(self._sync_geometry)
        self._anchor_timer.start()

        self._sync_geometry()
        self.show()
        self.edit.setFocus()
        cursor = self.edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.edit.setTextCursor(cursor)

    # -- geometry --------------------------------------------------------------
    def _scale(self) -> float:
        view = self._viewport.view
        return max(float(view.scale), 1e-9)

    def _sync_geometry(self) -> None:
        if self._closed:
            return
        view = self._viewport.view
        scale = self._scale()
        sx, sy = view.world_to_screen(self._top_left[0], self._top_left[1])
        width = max(int(self._width_world * scale), MIN_WIDTH_PX)

        # Text at its drawing size: cap height ≈ char_height, and Qt's
        # pixel size is close enough to cap height for step 1.
        font = QFont(self.edit.font())
        font.setPixelSize(max(int(round(self._char_height * scale)), 6))
        self.edit.setFont(font)

        self.edit.document().setTextWidth(width - 6)
        content = int(self.edit.document().size().height()) + 8
        height = max(content, MIN_HEIGHT_PX)
        button_h = self.ok.sizeHint().height() + 2
        self.setGeometry(int(sx) - 2, int(sy) - button_h - 2,
                         width + 4, height + button_h + 4)

    # -- lifecycle -------------------------------------------------------------
    def _teardown(self) -> None:
        self._closed = True
        self._anchor_timer.stop()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self.hide()
        self.deleteLater()
        self._viewport.setFocus()

    def commit(self) -> None:
        if self._closed:
            return
        text = self.edit.toPlainText()
        self._teardown()
        self._on_commit(from_editor_text(text))

    def cancel(self, ask: bool = True) -> None:
        if self._closed:
            return
        if ask and self.edit.toPlainText() != self._initial:
            # AutoCAD: "Pressing Esc displays a message and allows you to
            # close the editor without saving your changes."
            answer = QMessageBox.question(
                self, tr("Text Editor"),
                tr("Discard the changes to this text?"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        self._teardown()
        self._on_cancel()

    # -- events ----------------------------------------------------------------
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if self._closed:
            return False
        kind = event.type()
        if obj is self.edit and kind == QEvent.KeyPress:
            key = event.key()
            if key in (Qt.Key_Return, Qt.Key_Enter):
                if event.modifiers() & Qt.ControlModifier or self._single_line:
                    self.commit()
                    return True
                return False          # plain Enter: a paragraph break
            if key == Qt.Key_Escape:
                self.cancel()
                return True
            if event.matches(QKeySequence.Cancel):
                self.cancel()
                return True
            return False
        if kind == QEvent.MouseButtonPress and isinstance(obj, QWidget):
            inside = obj is self or self.isAncestorOf(obj)
            if not inside:
                self.commit()
            return False
        return False
