# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The in-place MTEXT editor with its Text Formatting toolbar (steps 1+2).

The text is edited on the canvas, at its real position and size, with the
drawing visible behind it, under a compact version of the classic Text
Formatting toolbar (Style, Font, Height, B/I/U/O, Color, Stack,
Justification, OK — the order the AutoCAD toolbar uses; researched in
docs/reference/draw/autocad-bricscad-mtext-editor.md).

Two modes, decided by ``core.mtext_format.parse_runs``:

* **Rich** — the content is fully representable, formatting shows as
  formatting and the toolbar writes real MTEXT codes on commit. Safety is
  by construction: parse_runs only says yes when its own serialization
  parses back identically.
* **Raw** — anything we cannot rebuild exactly (stacked fractions, fields,
  alignment codes…) shows as raw codes, formatting buttons disabled, and
  the content round-trips untouched. Stack lives here: it wraps the
  selection in ``\\S…;`` where codes are literal.

Shared semantics (step 1): Enter = paragraph, Ctrl+Enter / OK / click
outside = commit, Esc asks before discarding, pan/zoom keep the editor
anchored to the text.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeySequence,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
    QTextOption,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFontComboBox,
    QHBoxLayout,
    QMenu,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core import mtext_format
from core.i18n import tr

_FRAME = """
MTextInPlaceEditor { background: transparent; }
QTextEdit {
    background: rgba(30, 33, 38, 205);
    color: #e8e8e8;
    border: 1px solid #6a86a8;
}
QPushButton, QToolButton {
    background: #35424f; color: #e8e8e8; border: 1px solid #4a5a6a;
    padding: 1px 7px; font-size: 11px;
}
QPushButton:hover, QToolButton:hover { background: #3d4c5b; }
QToolButton:checked { background: #4a6e94; }
QComboBox, QDoubleSpinBox {
    background: #2a2e33; color: #e8e8e8; border: 1px solid #4a5a6a;
    font-size: 11px; combobox-popup: 0;
}
"""

MIN_WIDTH_PX = 120
MIN_HEIGHT_PX = 34

# Custom char-format properties: the LOGICAL values the serializer reads,
# stored beside the visual ones so pixel rounding cannot corrupt them.
PROP_ACI = QTextFormat.UserProperty          # int ACI, absent = no code
PROP_HFACTOR = QTextFormat.UserProperty + 1  # float, factor of char_height
PROP_FAMILY = QTextFormat.UserProperty + 2   # str, "" = style's own font

# MText Justification: the nine attachment points, AutoCAD's order/names.
ATTACHMENTS = (
    (1, "Top Left"), (2, "Top Center"), (3, "Top Right"),
    (4, "Middle Left"), (5, "Middle Center"), (6, "Middle Right"),
    (7, "Bottom Left"), (8, "Bottom Center"), (9, "Bottom Right"),
)


def to_editor_text(mtext_content: str) -> str:
    r"""Raw mode: only \P becomes a newline; every other code stays."""
    return mtext_content.replace("\\P", "\n")


def from_editor_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\n", "\\P")


class MTextInPlaceEditor(QWidget):
    """One editing session over the viewport. Commit/cancel via callbacks.

    ``on_commit(content, extras)`` — extras carries entity-level choices:
    ``{"style": name | None, "attachment": int | None}``.
    """

    def __init__(self, viewport, *, top_left, width_world: float,
                 char_height: float, text: str = "",
                 on_commit: Callable[[str, dict], None],
                 on_cancel: Optional[Callable[[], None]] = None,
                 single_line: bool = False,
                 document=None, style: str = "",
                 allow_justify: bool = False) -> None:
        super().__init__(viewport)
        self._viewport = viewport
        self._top_left = top_left
        self._width_world = float(width_world)
        self._char_height = float(char_height) or 1.0
        self._on_commit = on_commit
        self._on_cancel = on_cancel or (lambda: None)
        self._single_line = single_line
        self._closed = False
        self._loading = True
        self._last_scale = 0.0
        self._attachment: Optional[int] = None

        runs = None
        if not single_line:
            runs = mtext_format.parse_runs(text, self._char_height)
        self.rich = runs is not None

        self.setObjectName("MTextInPlaceEditor")
        self.setStyleSheet(_FRAME)

        self.edit = QTextEdit(self)
        self.edit.setAcceptRichText(False)
        self.edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        option = QTextOption()
        option.setWrapMode(QTextOption.NoWrap if single_line
                           else QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.edit.document().setDefaultTextOption(option)
        self.edit.document().setDocumentMargin(2)
        self.edit.installEventFilter(self)

        self._build_toolbar(document, style, allow_justify)

        if self.rich:
            self._load_runs(runs)
        else:
            self.edit.setPlainText(to_editor_text(text))
        self._initial = self._current_content()
        self._loading = False

        self.edit.textChanged.connect(self._sync_geometry)
        self.edit.currentCharFormatChanged.connect(self._pull_format)
        self.edit.cursorPositionChanged.connect(
            lambda: self._pull_format(self.edit.currentCharFormat()))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        layout.addWidget(self._bar)
        layout.addWidget(self.edit, 1)

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        self._anchor_timer = QTimer(self)
        self._anchor_timer.setInterval(33)
        self._anchor_timer.timeout.connect(self._sync_geometry)
        self._anchor_timer.start()

        self._sync_geometry()
        self.show()
        self.edit.setFocus()
        cursor = self.edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.edit.setTextCursor(cursor)

    # -- toolbar ---------------------------------------------------------------
    def _build_toolbar(self, document, style: str, allow_justify: bool) -> None:
        from views.layers_panel import fill_color_combo

        self._bar = QWidget(self)
        row = QHBoxLayout(self._bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)

        def tool(label, tip, checkable=True):
            button = QToolButton(self._bar)
            button.setText(label)
            button.setToolTip(tip)
            button.setCheckable(checkable)
            button.setFocusPolicy(Qt.NoFocus)
            row.addWidget(button)
            return button

        # Style — applied to the whole object, like AutoCAD's Style control.
        self.style_combo = QComboBox(self._bar)
        self.style_combo.setFocusPolicy(Qt.NoFocus)
        self.style_combo.setToolTip(tr("Text style (applies to the whole text)"))
        names = []
        if document is not None:
            try:
                names = [s.dxf.name for s in document.doc.styles]
            except Exception:
                names = []
        self.style_combo.addItems(names or ["Standard"])
        if style:
            index = self.style_combo.findText(style)
            if index >= 0:
                self.style_combo.setCurrentIndex(index)
        self._initial_style = self.style_combo.currentText()
        row.addWidget(self.style_combo)

        self.font_combo = QFontComboBox(self._bar)
        self.font_combo.setFocusPolicy(Qt.NoFocus)
        self.font_combo.setMaximumWidth(130)
        self.font_combo.setToolTip(tr("Font for the selected characters"))
        self.font_combo.setCurrentText("")
        self.font_combo.currentTextChanged.connect(self._apply_font)
        row.addWidget(self.font_combo)

        self.height_spin = QDoubleSpinBox(self._bar)
        self.height_spin.setFocusPolicy(Qt.ClickFocus)
        self.height_spin.setDecimals(4)
        self.height_spin.setRange(0.0001, 1e6)
        self.height_spin.setValue(self._char_height)
        self.height_spin.setToolTip(tr("Text height (drawing units)"))
        self.height_spin.editingFinished.connect(self._apply_height)
        row.addWidget(self.height_spin)

        self.bold = tool("N", tr("Bold (TrueType fonts)"))
        self.italic = tool("K", tr("Italic (TrueType fonts)"))
        self.under = tool("S", tr("Underline"))
        self.over = tool("O", tr("Overline"))
        self.bold.toggled.connect(lambda on: self._merge(bold=on))
        self.italic.toggled.connect(lambda on: self._merge(italic=on))
        self.under.toggled.connect(lambda on: self._merge(underline=on))
        self.over.toggled.connect(lambda on: self._merge(overline=on))
        font = self.bold.font()
        font.setBold(True)
        self.bold.setFont(font)

        self.color_combo = QComboBox(self._bar)
        self.color_combo.setFocusPolicy(Qt.NoFocus)
        self.color_combo.setMaximumWidth(96)
        self.color_combo.setToolTip(tr("Color of the selected characters"))
        fill_color_combo(self.color_combo)
        self.color_combo.activated.connect(self._apply_color)
        row.addWidget(self.color_combo)

        self.stack = tool("a/b", tr("Stack the selection (a/b, a#b, a^b)"),
                          checkable=False)
        self.stack.clicked.connect(self._apply_stack)

        self.justify = QToolButton(self._bar)
        self.justify.setText(tr("Justify"))
        self.justify.setFocusPolicy(Qt.NoFocus)
        self.justify.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.justify)
        for value, label in ATTACHMENTS:
            menu.addAction(tr(label),
                           lambda v=value: self._set_attachment(v))
        self.justify.setMenu(menu)
        row.addWidget(self.justify)

        row.addStretch(1)
        self.ok = QPushButton(tr("OK"), self._bar)
        self.ok.setToolTip(tr("Save and close (Ctrl+Enter)"))
        self.ok.setFocusPolicy(Qt.NoFocus)
        self.ok.clicked.connect(self.commit)
        row.addWidget(self.ok)

        if not self.rich:
            reason = tr("This text carries formatting the editor cannot "
                        "show yet — it is edited as codes so nothing is "
                        "lost.")
            for widget in (self.font_combo, self.height_spin, self.bold,
                           self.italic, self.under, self.over,
                           self.color_combo):
                widget.setEnabled(False)
                widget.setToolTip(reason)
        else:
            self.stack.setEnabled(False)
            self.stack.setToolTip(
                tr("Stacking writes \\S codes — available when the text is "
                   "edited as codes."))
        if not allow_justify:
            self.justify.setEnabled(False)
            self.justify.setToolTip(
                tr("Justification of an existing text keeps its insertion "
                   "point — not supported yet."))
        if self._single_line:
            self._bar.hide()

    # -- rich-mode plumbing ----------------------------------------------------
    def _base_px(self) -> int:
        return max(int(round(self._char_height * self._scale())), 6)

    def _format_for(self, run: mtext_format.Run) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Bold if run.bold else QFont.Normal)
        fmt.setFontItalic(run.italic)
        fmt.setFontUnderline(run.underline)
        fmt.setFontOverline(run.overline)
        fmt.setFontStrikeOut(run.strike)
        fmt.setProperty(PROP_HFACTOR, float(run.height))
        fmt.setProperty(PROP_FAMILY, run.font or "")
        if run.font:
            fmt.setFontFamilies([run.font])
        if run.aci is not None:
            from views.layers_panel import aci_to_qcolor

            fmt.setProperty(PROP_ACI, int(run.aci))
            fmt.setForeground(aci_to_qcolor(run.aci))
        elif run.rgb is not None:
            fmt.setForeground(QColor(*run.rgb))
            fmt.setProperty(PROP_ACI, -1)     # marker: keep rgb via brush
        fmt.setProperty(QTextFormat.FontPixelSize,
                        max(int(round(self._base_px() * run.height)), 4))
        return fmt

    def _load_runs(self, paragraphs) -> None:
        cursor = QTextCursor(self.edit.document())
        cursor.beginEditBlock()
        for index, line in enumerate(paragraphs):
            if index:
                cursor.insertBlock()
            for run in line:
                cursor.insertText(run.text, self._format_for(run))
        cursor.endEditBlock()

    def _runs_from_document(self):
        from views.layers_panel import ACI_RGB

        paragraphs = []
        block = self.edit.document().begin()
        while block.isValid():
            line = []
            it = block.begin()
            while not it.atEnd():
                fragment = it.fragment()
                if fragment.isValid():
                    fmt = fragment.charFormat()
                    aci = fmt.property(PROP_ACI)
                    rgb = None
                    if aci == -1:
                        colour = fmt.foreground().color()
                        rgb = (colour.red(), colour.green(), colour.blue())
                        aci = None
                    factor = fmt.property(PROP_HFACTOR)
                    family = fmt.property(PROP_FAMILY) or None
                    line.append(mtext_format.Run(
                        text=fragment.text(),
                        bold=fmt.fontWeight() >= QFont.DemiBold,
                        italic=fmt.fontItalic(),
                        underline=fmt.fontUnderline(),
                        overline=fmt.fontOverline(),
                        strike=fmt.fontStrikeOut(),
                        aci=int(aci) if aci is not None else None,
                        rgb=rgb,
                        height=float(factor) if factor else 1.0,
                        font=family,
                    ))
                it += 1
            paragraphs.append(line)
            block = block.next()
        return paragraphs

    def _current_content(self) -> str:
        if self.rich:
            return mtext_format.serialize(self._runs_from_document())
        return from_editor_text(self.edit.toPlainText())

    # -- formatting actions ----------------------------------------------------
    def _merge(self, **what) -> None:
        if self._loading or not self.rich:
            return
        fmt = QTextCharFormat()
        if "bold" in what:
            fmt.setFontWeight(QFont.Bold if what["bold"] else QFont.Normal)
        if "italic" in what:
            fmt.setFontItalic(what["italic"])
        if "underline" in what:
            fmt.setFontUnderline(what["underline"])
        if "overline" in what:
            fmt.setFontOverline(what["overline"])
        self.edit.mergeCurrentCharFormat(fmt)
        self.edit.setFocus()

    def _apply_font(self, family: str) -> None:
        if self._loading or not self.rich or not family:
            return
        fmt = QTextCharFormat()
        fmt.setFontFamilies([family])
        fmt.setProperty(PROP_FAMILY, family)
        self.edit.mergeCurrentCharFormat(fmt)
        self.edit.setFocus()

    def _apply_height(self) -> None:
        if self._loading or not self.rich:
            return
        factor = max(self.height_spin.value() / self._char_height, 1e-6)
        fmt = QTextCharFormat()
        fmt.setProperty(PROP_HFACTOR, float(factor))
        # Only the size: a full setFont() would drag the base family along
        # and silently reset every run the merge touches.
        fmt.setProperty(QTextFormat.FontPixelSize,
                        max(int(round(self._base_px() * factor)), 4))
        self.edit.mergeCurrentCharFormat(fmt)
        self.edit.setFocus()

    def _apply_color(self, index: int) -> None:
        if self._loading or not self.rich:
            return
        from views.layers_panel import aci_to_qcolor
        from views.properties_panel import BYLAYER_COLOR

        aci = self.color_combo.itemData(index)
        fmt = QTextCharFormat()
        if aci in (None, BYLAYER_COLOR):
            fmt.setProperty(PROP_ACI, None)
            fmt.setForeground(QColor("#e8e8e8"))
        else:
            fmt.setProperty(PROP_ACI, int(aci))
            fmt.setForeground(aci_to_qcolor(int(aci)))
        self.edit.mergeCurrentCharFormat(fmt)
        self.edit.setFocus()

    def _apply_stack(self) -> None:
        """Raw mode: wrap the a/b selection in the \\S code (TRIM p.1224)."""
        cursor = self.edit.textCursor()
        selected = cursor.selectedText()
        if not selected or not any(c in selected for c in "/#^"):
            return
        cursor.insertText("\\S" + selected + ";")

    def _set_attachment(self, value: int) -> None:
        self._attachment = value
        for number, label in ATTACHMENTS:
            if number == value:
                self.justify.setText(tr(label))

    def _pull_format(self, fmt) -> None:
        """Cursor moved: the toolbar shows the format under it."""
        if self._loading or not self.rich:
            return
        self._loading = True
        try:
            self.bold.setChecked(fmt.fontWeight() >= QFont.DemiBold)
            self.italic.setChecked(fmt.fontItalic())
            self.under.setChecked(fmt.fontUnderline())
            self.over.setChecked(fmt.fontOverline())
            factor = fmt.property(PROP_HFACTOR) or 1.0
            self.height_spin.setValue(self._char_height * float(factor))
        finally:
            self._loading = False

    # -- geometry --------------------------------------------------------------
    def _scale(self) -> float:
        view = self._viewport.view
        return max(float(view.scale), 1e-9)

    def _rescale_rich_text(self) -> None:
        """Zoom changed: every run's pixel size follows its stored factor."""
        document = self.edit.document()
        cursor = QTextCursor(document)
        block = document.begin()
        base = self._base_px()
        cursor.beginEditBlock()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                fragment = it.fragment()
                if fragment.isValid():
                    fmt = fragment.charFormat()
                    factor = float(fmt.property(PROP_HFACTOR) or 1.0)
                    wanted = max(int(round(base * factor)), 4)
                    if fmt.font().pixelSize() != wanted:
                        cursor.setPosition(fragment.position())
                        cursor.setPosition(fragment.position()
                                           + fragment.length(),
                                           QTextCursor.MoveMode.KeepAnchor)
                        patch = QTextCharFormat()
                        patch.setProperty(QTextFormat.FontPixelSize, wanted)
                        cursor.mergeCharFormat(patch)
                it += 1
            block = block.next()
        cursor.endEditBlock()

    def _sync_geometry(self) -> None:
        if self._closed:
            return
        view = self._viewport.view
        scale = self._scale()
        sx, sy = view.world_to_screen(self._top_left[0], self._top_left[1])
        width = max(int(self._width_world * scale), MIN_WIDTH_PX)

        if abs(scale - self._last_scale) / scale > 0.01:
            self._last_scale = scale
            font = QFont(self.edit.font())
            font.setPixelSize(self._base_px())
            self.edit.setFont(font)
            if self.rich and not self._loading:
                was = self._loading
                self._loading = True
                try:
                    self._rescale_rich_text()
                finally:
                    self._loading = was

        self.edit.document().setTextWidth(width - 6)
        content = int(self.edit.document().size().height()) + 8
        height = max(content, MIN_HEIGHT_PX)
        bar_height = 0 if self._single_line else \
            self._bar.sizeHint().height() + 2
        self.setGeometry(int(sx) - 2, int(sy) - bar_height - 2,
                         max(width + 4, self._bar.sizeHint().width() + 4),
                         height + bar_height + 4)

    # -- lifecycle -------------------------------------------------------------
    def _extras(self) -> dict:
        style = self.style_combo.currentText()
        return {
            "style": style if style != self._initial_style else None,
            "attachment": self._attachment,
        }

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
        content = self._current_content()
        extras = self._extras()
        self._teardown()
        self._on_commit(content, extras)

    def cancel(self, ask: bool = True) -> None:
        if self._closed:
            return
        if ask and self._current_content() != self._initial:
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
                if event.modifiers() & Qt.ShiftModifier:
                    # Qt would insert U+2028 here; a run must never carry a
                    # line separator, so make it a real paragraph.
                    self.edit.textCursor().insertBlock()
                    return True
                return False
            if key == Qt.Key_Escape:
                self.cancel()
                return True
            if event.matches(QKeySequence.Bold):
                self.bold.toggle()
                return True
            if event.matches(QKeySequence.Italic):
                self.italic.toggle()
                return True
            if event.matches(QKeySequence.Underline):
                self.under.toggle()
                return True
            return False
        if kind == QEvent.MouseButtonPress and isinstance(obj, QWidget):
            inside = obj is self or self.isAncestorOf(obj)
            if not inside:
                popup = QApplication.activePopupWidget()
                if popup is not None:       # a combo's list is "inside"
                    return False
                self.commit()
            return False
        return False
