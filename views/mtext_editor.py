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
# Block-level (paragraph) logical values, in multiples of char_height:
PROP_P_INDENT = QTextFormat.UserProperty + 3   # first line, relative to left
PROP_P_LEFT = QTextFormat.UserProperty + 4
PROP_P_RIGHT = QTextFormat.UserProperty + 5
PROP_P_TABS = QTextFormat.UserProperty + 6     # "4,c8,r12" string form
PROP_P_ALIGN = QTextFormat.UserProperty + 7    # kept only to round-trip

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


class _Ruler(QWidget):
    """The editor's ruler: width arrow, indent sliders, tab stops.

    What each element does is the researched AutoCAD behavior: the TOP
    slider is the first line, the BOTTOM slider the turnover lines, a click
    on the ruler drops a tab of the current type (the button at the left
    end cycles left/center/right), dragging a stop moves it and dragging it
    off the ruler removes it, the arrow at the right end drags the MTEXT
    width and double-clicking it fits the box to the text.

    All values live in multiples of char_height (the MTEXT convention);
    pixels are derived per paint, so zoom costs nothing.
    """

    HEIGHT = 18

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self.editor = editor
        self.setFixedHeight(self.HEIGHT)
        self.setMouseTracking(True)
        # Everything on the ruler is dragged horizontally.
        self.setCursor(Qt.SizeHorCursor)
        self.tab_type = "l"                 # l / c / r, the Tab Selection
        self._drag = None                   # ("first"|"left"|"width"|("tab",i))
        self.setToolTip(tr("Click: add a tab stop. Drag the sliders for the "
                           "indents, the right arrow for the width."))

    # -- unit mapping ----------------------------------------------------------
    def _base(self) -> float:
        return max(self.editor._base_px(), 1)

    def _to_px(self, units: float) -> float:
        return 4 + units * self._base()     # 4 = the text margin offset

    def _to_units(self, px: float) -> float:
        return max((px - 4) / self._base(), 0.0)

    # -- painting --------------------------------------------------------------
    def paintEvent(self, event) -> None:
        from PySide6.QtGui import QPainter, QPen, QPolygonF
        from PySide6.QtCore import QPointF

        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(42, 46, 51))
        height = self.height()
        base = self._base()
        painter.setPen(QPen(QColor(110, 116, 124), 1))
        # Ticks each char_height; long ones at the default stops (4, 8, …).
        units = 0
        while self._to_px(units) < self.width() - 8:
            x = self._to_px(units)
            long = units and units % 4 == 0
            painter.drawLine(QPointF(x, height - (9 if long else 5)),
                             QPointF(x, height - 2))
            units += 1

        props = self.editor.current_props()
        painter.setPen(QPen(QColor(0xE8, 0xC8, 0x60), 1))
        painter.setBrush(QColor(0xE8, 0xC8, 0x60))
        # Tab stops of the current paragraph.
        for stop in props.tab_stops:
            text = str(stop)
            kind, value = ("l", text)
            if text[0] in "cr":
                kind, value = text[0], text[1:]
            x = self._to_px(float(value))
            if kind == "l":
                painter.drawPolyline([QPointF(x, height - 10),
                                      QPointF(x, height - 3),
                                      QPointF(x + 4, height - 3)])
            elif kind == "r":
                painter.drawPolyline([QPointF(x, height - 10),
                                      QPointF(x, height - 3),
                                      QPointF(x - 4, height - 3)])
            else:
                painter.drawLine(QPointF(x, height - 10),
                                 QPointF(x, height - 3))
                painter.drawLine(QPointF(x - 3, height - 3),
                                 QPointF(x + 3, height - 3))
        # First-line slider (top) and left/hanging slider (bottom).
        first_x = self._to_px(props.left + props.indent)
        left_x = self._to_px(props.left)
        painter.setPen(QPen(QColor(0x8F, 0xB8, 0xD8), 1))
        painter.setBrush(QColor(0x8F, 0xB8, 0xD8))
        painter.drawPolygon(QPolygonF([
            QPointF(first_x - 4, 1), QPointF(first_x + 4, 1),
            QPointF(first_x, 7)]))
        painter.drawPolygon(QPolygonF([
            QPointF(left_x, height - 8), QPointF(left_x + 4, height - 2),
            QPointF(left_x - 4, height - 2)]))
        # The width arrow at the right end.
        arrow_x = self.width() - 6
        painter.setPen(QPen(QColor(0xF0, 0xF4, 0xF6), 1))
        painter.setBrush(QColor(0xF0, 0xF4, 0xF6))
        painter.drawPolygon(QPolygonF([
            QPointF(arrow_x - 5, height / 2 - 5),
            QPointF(arrow_x + 1, height / 2),
            QPointF(arrow_x - 5, height / 2 + 5)]))
        # Tab Selection button, far left.
        painter.setPen(QPen(QColor(0xB0, 0xB6, 0xBC), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(1, height // 2 - 6, 11, 12)
        glyph = {"l": "L", "c": "C", "r": "R"}[self.tab_type]
        painter.drawText(3, height // 2 + 4, glyph)
        painter.end()

    # -- interaction -----------------------------------------------------------
    def _hit(self, pos):
        props = self.editor.current_props()
        x, y = pos.x(), pos.y()
        if x <= 13:
            return ("type",)
        if x >= self.width() - 12:
            return ("width",)
        first_x = self._to_px(props.left + props.indent)
        left_x = self._to_px(props.left)
        if abs(x - first_x) <= 5 and y <= 8:
            return ("first",)
        if abs(x - left_x) <= 5 and y >= self.height() - 9:
            return ("left",)
        for index, stop in enumerate(props.tab_stops):
            text = str(stop)
            value = float(text[1:]) if text[0] in "cr" else float(text)
            if abs(x - self._to_px(value)) <= 4:
                return ("tab", index)
        return None

    def mousePressEvent(self, event) -> None:
        hit = self._hit(event.position())
        if hit is None:
            # Click on open ruler: drop a tab of the current type here.
            value = round(self._to_units(event.position().x()), 2)
            stop = value if self.tab_type == "l" else \
                f"{self.tab_type}{value:g}"
            props = self.editor.current_props()
            stops = sorted(
                list(props.tab_stops) + [stop],
                key=lambda t: float(str(t)[1:]) if str(t)[0] in "cr"
                else float(t))
            self.editor.apply_paragraph_props(tab_stops=tuple(stops))
            self._drag = ("tab", stops.index(stop))
            return
        if hit[0] == "type":
            order = "lcr"
            self.tab_type = order[(order.index(self.tab_type) + 1) % 3]
            self.update()
            return
        self._drag = hit

    def mouseMoveEvent(self, event) -> None:
        if self._drag is None:
            return
        value = round(self._to_units(event.position().x()), 2)
        kind = self._drag[0]
        props = self.editor.current_props()
        if kind == "width":
            self.editor.set_width_px(event.position().x() + 8)
        elif kind == "first":
            self.editor.apply_paragraph_props(
                indent=round(value - props.left, 2))
        elif kind == "left":
            self.editor.apply_paragraph_props(left=value)
        elif kind == "tab":
            index = self._drag[1]
            stops = list(props.tab_stops)
            if 0 <= index < len(stops):
                old = str(stops[index])
                prefix = old[0] if old[0] in "cr" else ""
                if event.position().y() > self.height() + 12:
                    stops.pop(index)        # dragged off: remove
                    self._drag = None
                else:
                    stops[index] = f"{prefix}{value:g}" if prefix else value
                self.editor.apply_paragraph_props(tab_stops=tuple(stops))
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        self._drag = None

    def mouseDoubleClickEvent(self, event) -> None:
        if self._hit(event.position()) == ("width",):
            self.editor.fit_width()


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
                 allow_justify: bool = False,
                 line_spacing: float = 1.0) -> None:
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
        self._line_spacing = float(line_spacing) or 1.0
        self._initial_spacing = self._line_spacing
        # ("off") | (aci:int|"canvas", scale) | None = untouched
        self._bg: Optional[tuple] = None
        # (count, height, gutter) | ("off",) | None = untouched
        self._columns: Optional[tuple] = None

        runs = None
        if not single_line:
            runs = mtext_format.parse_runs(text, self._char_height)
        self.rich = runs is not None

        self.setObjectName("MTextInPlaceEditor")
        self.setStyleSheet(_FRAME)
        # The viewport hides the OS pointer (the crosshair IS the cursor in
        # model space) and children inherit that: the toolbar buttons and
        # the ruler were operated with an invisible pointer. The editor is
        # ordinary UI — give it an ordinary arrow; the text area keeps the
        # I-beam QTextEdit sets on its own viewport.
        self.setCursor(Qt.ArrowCursor)

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
        if abs(self._line_spacing - 1.0) > 1e-9:
            self._apply_spacing_visual()
        self._initial = self._current_content()
        self._loading = False

        self.edit.textChanged.connect(self._sync_geometry)
        self.edit.currentCharFormatChanged.connect(self._pull_format)
        self.edit.cursorPositionChanged.connect(
            lambda: self._pull_format(self.edit.currentCharFormat()))

        self.ruler = _Ruler(self)
        if not self.rich or single_line:
            self.ruler.hide()
        self.edit.cursorPositionChanged.connect(self.ruler.update)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        layout.addWidget(self._bar)
        layout.addWidget(self.ruler)
        layout.addWidget(self.edit, 1)

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        self._anchor_timer = QTimer(self)
        self._anchor_timer.setInterval(33)
        self._anchor_timer.timeout.connect(self._sync_geometry)
        self._anchor_timer.start()

        # Twice on purpose: the first pass installs the zoom-derived font,
        # the second measures the caret with that font in place. One pass
        # opened the editor a line short and the anchor timer fixed it a
        # tick later — a caret that starts hidden and pops in.
        self._sync_geometry()
        self._sync_geometry()
        # A hairline caret disappears against the drawing; AutoCAD's editor
        # caret is a solid bar.
        self.edit.setCursorWidth(2)
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

        self.spacing = QToolButton(self._bar)
        self.spacing.setText(f"{self._line_spacing:g}x")
        self.spacing.setToolTip(tr("Line spacing"))
        self.spacing.setFocusPolicy(Qt.NoFocus)
        self.spacing.setPopupMode(QToolButton.InstantPopup)
        spacing_menu = QMenu(self.spacing)
        for factor in (1.0, 1.5, 2.0, 2.5):
            spacing_menu.addAction(
                f"{factor:g}x", lambda f=factor: self._set_line_spacing(f))
        spacing_menu.addAction(tr("Other..."), self._ask_line_spacing)
        self.spacing.setMenu(spacing_menu)
        row.addWidget(self.spacing)

        self.lists = QToolButton(self._bar)
        self.lists.setText(tr("List"))
        self.lists.setToolTip(tr("Bullets and numbering"))
        self.lists.setFocusPolicy(Qt.NoFocus)
        self.lists.setPopupMode(QToolButton.InstantPopup)
        lists_menu = QMenu(self.lists)
        lists_menu.addAction(tr("None"), lambda: self._apply_list(None))
        lists_menu.addAction(tr("Numbered (1. 2. 3.)"),
                             lambda: self._apply_list("number"))
        lists_menu.addAction(tr("Lettered (a. b. c.)"),
                             lambda: self._apply_list("letter"))
        lists_menu.addAction(tr("Bulleted (•)"),
                             lambda: self._apply_list("bullet"))
        self.lists.setMenu(lists_menu)
        row.addWidget(self.lists)

        self.mask = QToolButton(self._bar)
        self.mask.setText(tr("Mask"))
        self.mask.setToolTip(tr("Background mask (opaque behind the text)"))
        self.mask.setFocusPolicy(Qt.NoFocus)
        self.mask.clicked.connect(self._mask_dialog)
        row.addWidget(self.mask)

        self.columns = QToolButton(self._bar)
        self.columns.setText(tr("Columns"))
        self.columns.setToolTip(tr("Static columns"))
        self.columns.setFocusPolicy(Qt.NoFocus)
        self.columns.setPopupMode(QToolButton.InstantPopup)
        columns_menu = QMenu(self.columns)
        columns_menu.addAction(tr("No Columns"),
                               lambda: self._set_columns(None))
        columns_menu.addAction(tr("Static Columns..."), self._columns_dialog)
        self.columns.setMenu(columns_menu)
        row.addWidget(self.columns)

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
                           self.color_combo, self.lists):
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

    # -- paragraph (block) plumbing --------------------------------------------
    def _block_format_for(self, props):
        from PySide6.QtGui import QTextBlockFormat

        fmt = QTextBlockFormat()
        fmt.setProperty(PROP_P_INDENT, float(props.indent))
        fmt.setProperty(PROP_P_LEFT, float(props.left))
        fmt.setProperty(PROP_P_RIGHT, float(props.right))
        fmt.setProperty(PROP_P_TABS,
                        ",".join(str(t) for t in props.tab_stops))
        fmt.setProperty(PROP_P_ALIGN, int(props.align))
        self._apply_block_visuals(fmt, props)
        return fmt

    def _apply_block_visuals(self, fmt, props) -> None:
        """Visual margins/tabs in px from the logical char_height multiples."""
        base = self._base_px()
        fmt.setTextIndent(props.indent * base)
        fmt.setLeftMargin(props.left * base)
        fmt.setRightMargin(props.right * base)
        tabs = []
        for stop in props.tab_stops:
            text = str(stop)
            kind = QTextOption.TabType.LeftTab
            if text.startswith("c"):
                kind = QTextOption.TabType.CenterTab
                text = text[1:]
            elif text.startswith("r"):
                kind = QTextOption.TabType.RightTab
                text = text[1:]
            try:
                position = float(text)
            except ValueError:
                continue
            tabs.append(QTextOption.Tab(position * base, kind))
        fmt.setTabPositions(tabs)

    def _props_of_block(self, block):
        from ezdxf.tools.text import (MTextParagraphAlignment,
                                      ParagraphProperties)

        fmt = block.blockFormat()
        if fmt.property(PROP_P_LEFT) is None \
                and fmt.property(PROP_P_INDENT) is None:
            return ParagraphProperties()
        raw_tabs = fmt.property(PROP_P_TABS) or ""
        tabs = []
        for piece in raw_tabs.split(","):
            piece = piece.strip()
            if not piece:
                continue
            if piece[0] in "cr":
                tabs.append(piece[0] + f"{float(piece[1:]):g}")
            else:
                tabs.append(float(piece))
        return ParagraphProperties(
            indent=float(fmt.property(PROP_P_INDENT) or 0.0),
            left=float(fmt.property(PROP_P_LEFT) or 0.0),
            right=float(fmt.property(PROP_P_RIGHT) or 0.0),
            align=MTextParagraphAlignment(
                int(fmt.property(PROP_P_ALIGN) or 0)),
            tab_stops=tuple(tabs),
        )

    def selected_blocks(self):
        """The blocks the selection covers — the ruler's paragraphs."""
        cursor = self.edit.textCursor()
        document = self.edit.document()
        first = document.findBlock(cursor.selectionStart())
        last = document.findBlock(cursor.selectionEnd())
        blocks = [first]
        while blocks[-1] != last and blocks[-1].isValid():
            blocks.append(blocks[-1].next())
        return [b for b in blocks if b.isValid()]

    def apply_paragraph_props(self, **changes) -> None:
        """The ruler's writes: merge into every selected paragraph."""
        if not self.rich:
            return
        cursor = QTextCursor(self.edit.document())
        cursor.beginEditBlock()
        for block in self.selected_blocks():
            props = self._props_of_block(block)
            props = props._replace(**changes)
            edit_cursor = QTextCursor(block)
            edit_cursor.setBlockFormat(self._block_format_for(props))
        cursor.endEditBlock()
        self._sync_geometry()
        if hasattr(self, "ruler"):
            self.ruler.update()

    def current_props(self):
        block = self.edit.textCursor().block()
        return self._props_of_block(block)

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
            from views.color_dialog import aci_qcolor

            fmt.setProperty(PROP_ACI, int(run.aci))
            fmt.setForeground(aci_qcolor(run.aci))
        elif run.rgb is not None:
            fmt.setForeground(QColor(*run.rgb))
            fmt.setProperty(PROP_ACI, -1)     # marker: keep rgb via brush
        fmt.setProperty(QTextFormat.FontPixelSize,
                        max(int(round(self._base_px() * run.height)), 4))
        return fmt

    def _load_runs(self, paragraphs) -> None:
        cursor = QTextCursor(self.edit.document())
        cursor.beginEditBlock()
        for index, paragraph in enumerate(paragraphs):
            if index:
                cursor.insertBlock()
            cursor.setBlockFormat(self._block_format_for(paragraph.resolved()))
            for run in paragraph.runs:
                cursor.insertText(run.text, self._format_for(run))
        cursor.endEditBlock()

    def _runs_from_document(self):
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
            paragraphs.append(mtext_format.Paragraph(
                runs=line, props=self._props_of_block(block)))
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
        from views.color_dialog import BYLAYER, aci_qcolor

        aci = self.color_combo.itemData(index)
        fmt = QTextCharFormat()
        if aci in (None, BYLAYER):
            fmt.setProperty(PROP_ACI, None)
            fmt.setForeground(QColor("#e8e8e8"))
        else:
            fmt.setProperty(PROP_ACI, int(aci))
            fmt.setForeground(aci_qcolor(int(aci)))
        self.edit.mergeCurrentCharFormat(fmt)
        self.edit.setFocus()

    def _apply_stack(self) -> None:
        """Raw mode: wrap the a/b selection in the \\S code (TRIM p.1224)."""
        cursor = self.edit.textCursor()
        selected = cursor.selectedText()
        if not selected or not any(c in selected for c in "/#^"):
            return
        cursor.insertText("\\S" + selected + ";")

    # -- line spacing ----------------------------------------------------------
    def _set_line_spacing(self, factor: float) -> None:
        self._line_spacing = max(0.25, min(4.0, float(factor)))
        self.spacing.setText(f"{self._line_spacing:g}x")
        self._apply_spacing_visual()

    def _ask_line_spacing(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        value, ok = QInputDialog.getDouble(
            self, tr("Line spacing"), tr("Factor (0.25 to 4):"),
            self._line_spacing, 0.25, 4.0, 2)
        if ok:
            self._set_line_spacing(value)

    def _apply_spacing_visual(self) -> None:
        from PySide6.QtGui import QTextBlockFormat

        cursor = QTextCursor(self.edit.document())
        cursor.select(QTextCursor.SelectionType.Document)
        fmt = QTextBlockFormat()
        fmt.setLineHeight(self._line_spacing * 100.0,
                          QTextBlockFormat.LineHeightTypes
                          .ProportionalHeight.value)
        cursor.mergeBlockFormat(fmt)

    # -- bullets and numbering -------------------------------------------------
    def _apply_list(self, style) -> None:
        """The Lists menu: rewrite the selected paragraphs as items."""
        from core import mtext_lists

        if not self.rich:
            return
        blocks = self.selected_blocks()
        cursor = QTextCursor(self.edit.document())
        cursor.beginEditBlock()
        if style is None:
            for block in blocks:
                self._set_block_marker(block, None)
            self.apply_paragraph_props(indent=0.0, left=0.0, tab_stops=())
        else:
            for index, block in enumerate(blocks, start=1):
                self._set_block_marker(
                    block, mtext_lists.marker_for(style, index))
            self.apply_paragraph_props(
                indent=mtext_lists.LIST_INDENT, left=mtext_lists.LIST_LEFT,
                tab_stops=mtext_lists.LIST_TABS)
        cursor.endEditBlock()

    def _set_block_marker(self, block, marker) -> None:
        """Replace the paragraph's leading marker (or add/remove it).

        Only the prefix is touched, so the item's own runs keep their
        character formats.
        """
        from core import mtext_lists

        found = mtext_lists.detect_marker(block.text())
        cursor = QTextCursor(block)
        prefix_len = 0
        if found is not None:
            prefix_len = len(block.text()) - len(found[2])
        cursor.setPosition(block.position())
        cursor.setPosition(block.position() + prefix_len,
                           QTextCursor.MoveMode.KeepAnchor)
        replacement = (marker + "\t") if marker else ""
        fmt = QTextCharFormat()
        fmt.setProperty(PROP_HFACTOR, 1.0)
        cursor.insertText(replacement, fmt)

    def _list_keys(self, key, modifiers) -> bool:
        """Enter continues a list, an empty item ends it, Tab starts one."""
        from core import mtext_lists

        if not self.rich:
            return False
        cursor = self.edit.textCursor()
        block = cursor.block()
        text = block.text()
        if key in (Qt.Key_Return, Qt.Key_Enter) and not modifiers:
            if mtext_lists.is_empty_item(text):
                # Enter on a bare marker: the list is over.
                self._set_block_marker(block, None)
                self.apply_paragraph_props(indent=0.0, left=0.0,
                                           tab_stops=())
                return True
            marker = mtext_lists.next_marker(text)
            if marker is not None and cursor.atBlockEnd():
                cursor.insertBlock()
                fmt = QTextCharFormat()
                fmt.setProperty(PROP_HFACTOR, 1.0)
                cursor.insertText(marker + "\t", fmt)
                self.edit.setTextCursor(cursor)
                return True
            return False
        if key == Qt.Key_Tab and not modifiers:
            head = text[:cursor.positionInBlock()]
            started = mtext_lists.autolist_style(head)
            if started is not None and head == text:
                style, ordinal = started
                # REPLACE the typed head ("1.", "-", "a.") with the marker:
                # inserting beside it would leave "•\t-" behind.
                replace = QTextCursor(block)
                replace.setPosition(block.position())
                replace.setPosition(block.position() + len(head),
                                    QTextCursor.MoveMode.KeepAnchor)
                fmt = QTextCharFormat()
                fmt.setProperty(PROP_HFACTOR, 1.0)
                replace.insertText(
                    mtext_lists.marker_for(style, ordinal) + "\t", fmt)
                self.apply_paragraph_props(
                    indent=mtext_lists.LIST_INDENT,
                    left=mtext_lists.LIST_LEFT,
                    tab_stops=mtext_lists.LIST_TABS)
                self.edit.setTextCursor(replace)
                return True
        return False

    # -- background mask -------------------------------------------------------
    def _mask_dialog(self) -> None:
        from views.mtext_dialogs import BackgroundMaskDialog

        dialog = BackgroundMaskDialog(self, self._current_bg())
        if dialog.exec():
            self._bg = dialog.result_bg()

    def _current_bg(self):
        if self._bg is not None:
            return self._bg
        return getattr(self, "_initial_bg", ("off",))

    def set_initial_bg(self, bg) -> None:
        self._initial_bg = bg

    # -- columns ---------------------------------------------------------------
    def _set_columns(self, value) -> None:
        self._columns = ("off",) if value is None else value

    def _columns_dialog(self) -> None:
        from views.mtext_dialogs import StaticColumnsDialog

        current = self._columns if self._columns \
            and self._columns[0] != "off" else getattr(
                self, "_initial_columns", None)
        dialog = StaticColumnsDialog(self, current,
                                     char_height=self._char_height,
                                     width=self._width_world)
        if dialog.exec():
            self._columns = dialog.result_columns()

    def set_initial_columns(self, columns) -> None:
        self._initial_columns = columns

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
        # Pixels per unit of the space the text LIVES in: inside a viewport
        # that is the model, drawn on the sheet at the viewport's scale.
        scale = getattr(self._viewport, "_space_scale", None)
        if scale is not None:
            return max(float(scale()), 1e-9)
        return max(float(self._viewport.view.scale), 1e-9)

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
            # Block visuals (margins, tabs) are pixel values too: re-derive
            # them from the stored char_height multiples at the new zoom.
            block_props = self._props_of_block(block)
            block_cursor = QTextCursor(block)
            fmt = block.blockFormat()
            self._apply_block_visuals(fmt, block_props)
            block_cursor.setBlockFormat(fmt)
            block = block.next()
        cursor.endEditBlock()

    def _sync_geometry(self) -> None:
        if self._closed:
            return
        scale = self._scale()
        sx, sy = self._viewport._space_to_screen(self._top_left[0],
                                                 self._top_left[1])
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
        # The floor is ONE REAL LINE at the current zoom, not a fixed pixel
        # count: an empty editor whose text is taller than the fixed floor
        # clipped its own caret. The caret's own rect is the truth — it
        # follows the cursor's char format, which the font metrics do not.
        one_line = max(self.edit.fontMetrics().height(),
                       self.edit.cursorRect().height()) + 12
        height = max(content, one_line, MIN_HEIGHT_PX)
        # Everything stacked ABOVE the text area. Forgetting a row here
        # squeezes the QTextEdit by that many pixels and pushes the caret
        # below its visible area — it types fine and shows nothing.
        chrome = 0
        if not self._single_line:
            chrome += self._bar.sizeHint().height() + 1
            if self.ruler.isVisible():
                chrome += self.ruler.height() + 1
        self.setGeometry(int(sx) - 2, int(sy) - chrome - 2,
                         max(width + 4, self._bar.sizeHint().width() + 4),
                         height + chrome + 4)

    # -- lifecycle -------------------------------------------------------------
    def set_width_px(self, px: float) -> None:
        """The ruler's width arrow: pixels -> world width, live re-wrap."""
        scale = self._scale()
        self._width_world = max(px / scale, 5.0 / scale)
        self._width_changed = True
        self._sync_geometry()

    def fit_width(self) -> None:
        """Double-click on the width arrow: confine the box to the text."""
        ideal = self.edit.document().idealWidth() + 8
        self.set_width_px(ideal)

    def _extras(self) -> dict:
        style = self.style_combo.currentText()
        return {
            "style": style if style != self._initial_style else None,
            "attachment": self._attachment,
            "width": self._width_world if getattr(self, "_width_changed",
                                                  False) else None,
            "line_spacing": self._line_spacing
            if abs(self._line_spacing - self._initial_spacing) > 1e-9
            else None,
            "bg": self._bg,
            "columns": self._columns,
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
            if self._list_keys(key, event.modifiers()):
                return True
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
