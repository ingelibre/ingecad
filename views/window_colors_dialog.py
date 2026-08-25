# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""AutoCAD's Drawing Window Colors dialog (Options ▸ Display ▸ Colors...).

Same shape as the original: a context list, an interface-element list, a
colour drop-down whose last entry opens the full picker, a live preview,
and the four restore buttons — element, context, all contexts, and the
classic colours (black model space).

Contexts: 2D model space, Sheet / layout, Block editor. Elements: Uniform
background per context, plus Crosshairs — which edits the same setting the
Display tab already exposes, exactly as AutoCAD keeps its crosshair colour
in this dialog.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import window_colors
from core.i18n import tr

#: For a BACKGROUND, the drop-down offers AutoCAD's own canvas tones — the
#: ones that look right to work on — not the pure index colours:
#: 33,40,48 is the modern model-space charcoal, 254,252,240 the cream
#: AutoCAD uses for its Block Editor (the cream colleagues ask for).
_BACKGROUND_TONES = [
    ("Dark gray (AutoCAD)", "#212830"),
    ("Cream (AutoCAD)", "#FEFCF0"),
    ("White", "#FFFFFF"),
    ("Black", "#000000"),
]

#: The crosshair keeps AutoCAD's colour list: the seven index colours plus
#: the two monochromes.
_NAMED = [
    ("Red", "#FF0000"), ("Yellow", "#FFFF00"), ("Green", "#00FF00"),
    ("Cyan", "#00FFFF"), ("Blue", "#0000FF"), ("Magenta", "#FF00FF"),
    ("White", "#FFFFFF"), ("Black", "#000000"),
]

_CONTEXTS = [("model", "2D model space"),
             ("sheet", "Sheet / layout"),
             ("block_editor", "Block editor")]
_ELEMENTS = [("background", "Uniform background"),
             ("crosshairs", "Crosshairs")]

#: The Display tab's crosshair setting ("" = automatic contrast).
_CROSSHAIR_KEY = "display/crosshair_color"


class _Preview(QWidget):
    """A little canvas: background, grid corner, one ACI-7 line, crosshair."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(220, 140)
        self.background = QColor("#212630")
        self.crosshair = None            # None = automatic

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        p = QPainter(self)
        rect = self.rect()
        p.fillRect(rect, self.background)
        light = self.background.lightnessF() > 0.5
        grid = QColor("#BDBDBD") if light else QColor("#48505C")
        p.setPen(QPen(grid, 1))
        for x in range(rect.left() + 20, rect.right(), 24):
            p.drawLine(x, rect.top(), x, rect.bottom())
        for y in range(rect.top() + 20, rect.bottom(), 24):
            p.drawLine(rect.left(), y, rect.right(), y)
        # an ACI-7 entity: black over light, white over dark (the flip)
        p.setPen(QPen(QColor("#000000") if light else QColor("#FFFFFF"), 2))
        p.drawLine(rect.left() + 18, rect.bottom() - 24,
                   rect.right() - 30, rect.top() + 26)
        p.drawEllipse(rect.center(), 22, 22)
        # the crosshair, automatic or chosen
        color = self.crosshair
        if color is None:
            color = QColor("#111111") if light else QColor("#DDDDDD")
        p.setPen(QPen(color, 1))
        cx, cy = rect.center().x() + 34, rect.center().y() + 18
        p.drawLine(cx - 26, cy, cx + 26, cy)
        p.drawLine(cx, cy - 26, cx, cy + 26)
        p.end()


class WindowColorsDialog(QDialog):
    """Edits core.window_colors + the crosshair colour; applies on OK."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Drawing Window Colors"))
        self.setMinimumWidth(560)
        #: pending edits, applied on OK: {("ctx","background"|"crosshairs"): "#..."|""}
        self._edits: dict = {}

        root = QVBoxLayout(self)
        lists = QHBoxLayout()

        left = QVBoxLayout()
        left.addWidget(QLabel(tr("Context:")))
        self.contexts = QListWidget(self)
        for key, label in _CONTEXTS:
            self.contexts.addItem(tr(label))
        self.contexts.setCurrentRow(0)
        left.addWidget(self.contexts)
        lists.addLayout(left, 2)

        mid = QVBoxLayout()
        mid.addWidget(QLabel(tr("Interface element:")))
        self.elements = QListWidget(self)
        for key, label in _ELEMENTS:
            self.elements.addItem(tr(label))
        self.elements.setCurrentRow(0)
        mid.addWidget(self.elements)
        lists.addLayout(mid, 2)

        right = QVBoxLayout()
        right.addWidget(QLabel(tr("Color:")))
        self.color = QComboBox(self)
        self._rebuild_color_combo("#212630")
        right.addWidget(self.color)
        right.addWidget(QLabel(tr("Preview:")))
        self.preview = _Preview(self)
        right.addWidget(self.preview, 1)
        lists.addLayout(right, 3)
        root.addLayout(lists)

        row = QHBoxLayout()
        self.btn_element = QPushButton(tr("Restore current element"), self)
        self.btn_context = QPushButton(tr("Restore current context"), self)
        self.btn_all = QPushButton(tr("Restore all contexts"), self)
        self.btn_classic = QPushButton(tr("Restore classic colors"), self)
        for b in (self.btn_element, self.btn_context, self.btn_all,
                  self.btn_classic):
            row.addWidget(b)
        root.addLayout(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.contexts.currentRowChanged.connect(self._sync_from_settings)
        self.elements.currentRowChanged.connect(self._sync_from_settings)
        self.color.activated.connect(self._color_chosen)
        self.btn_element.clicked.connect(self._restore_element)
        self.btn_context.clicked.connect(self._restore_context)
        self.btn_all.clicked.connect(self._restore_all)
        self.btn_classic.clicked.connect(self._restore_classic)
        self._sync_from_settings()

    # -- current selection ---------------------------------------------------
    def _context_key(self) -> str:
        return _CONTEXTS[max(0, self.contexts.currentRow())][0]

    def _element_key(self) -> str:
        return _ELEMENTS[max(0, self.elements.currentRow())][0]

    def _current_value(self) -> str:
        """The pending or stored colour of the selection ("" = automatic)."""
        key = (self._context_key(), self._element_key())
        if key in self._edits:
            return self._edits[key]
        if key[1] == "crosshairs":
            return str(QSettings().value(_CROSSHAIR_KEY, "") or "")
        return window_colors.background(key[0])

    # -- widgets -------------------------------------------------------------
    @staticmethod
    def _swatch_icon(hexv: str) -> QIcon:
        pix = QPixmap(14, 14)
        pix.fill(QColor(hexv))
        painter = QPainter(pix)
        painter.setPen(QPen(QColor(90, 90, 90), 1))
        painter.drawRect(0, 0, 13, 13)
        painter.end()
        return QIcon(pix)

    def _rebuild_color_combo(self, value: str) -> None:
        self.color.blockSignals(True)
        self.color.clear()
        crosshairs = self._element_key() == "crosshairs" if self.elements \
            .currentItem() is not None else False
        if crosshairs:
            self.color.addItem(tr("Automatic"), "")
        palette = _NAMED if crosshairs else _BACKGROUND_TONES
        for name, hexv in palette:
            self.color.addItem(self._swatch_icon(hexv), tr(name), hexv)
        self.color.addItem(tr("Select Color..."), None)
        idx = self.color.findData(value)
        if idx < 0:
            self.color.insertItem(0, self._swatch_icon(value),
                                  value.upper(), value)
            idx = 0
        self.color.setCurrentIndex(idx)
        self.color.blockSignals(False)

    def _sync_from_settings(self, *_a) -> None:
        self._rebuild_color_combo(self._current_value())
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        ctx = self._context_key()
        bg = self._edits.get((ctx, "background"),
                             window_colors.background(ctx))
        cross = self._edits.get(
            (ctx, "crosshairs"),
            str(QSettings().value(_CROSSHAIR_KEY, "") or ""))
        self.preview.background = QColor(bg)
        self.preview.crosshair = QColor(cross) if cross else None
        self.preview.update()

    def _color_chosen(self, index: int) -> None:
        data = self.color.itemData(index)
        if data is None:                       # Select Color...
            # AutoCAD opens its own Select Color palette here (the 255-index
            # grid) — so does IngeCAD: the same dialog layers and entities
            # already use, without ByLayer/ByBlock, which mean nothing for
            # a window background.
            from views.color_dialog import SelectColorDialog, aci_qcolor

            dialog = SelectColorDialog(self, include_bylayer=False)
            if dialog.exec() != SelectColorDialog.Accepted:
                self._rebuild_color_combo(self._current_value())
                return
            data = aci_qcolor(dialog.result_aci()).name().upper()
        self._edits[(self._context_key(), self._element_key())] = data
        self._rebuild_color_combo(data)
        self._refresh_preview()

    # -- restores ------------------------------------------------------------
    def _restore_element(self) -> None:
        ctx, elem = self._context_key(), self._element_key()
        self._edits[(ctx, elem)] = ("" if elem == "crosshairs"
                                    else window_colors.DEFAULTS[ctx])
        self._sync_from_settings()

    def _restore_context(self) -> None:
        ctx = self._context_key()
        self._edits[(ctx, "background")] = window_colors.DEFAULTS[ctx]
        self._edits[(ctx, "crosshairs")] = ""
        self._sync_from_settings()

    def _restore_all(self) -> None:
        for ctx, _label in _CONTEXTS:
            self._edits[(ctx, "background")] = window_colors.DEFAULTS[ctx]
        self._edits[(self._context_key(), "crosshairs")] = ""
        self._sync_from_settings()

    def _restore_classic(self) -> None:
        for ctx, _label in _CONTEXTS:
            self._edits[(ctx, "background")] = window_colors.CLASSIC[ctx]
        self._sync_from_settings()

    # -- apply ---------------------------------------------------------------
    def accept(self) -> None:  # noqa: N802 - Qt override
        settings = QSettings()
        for (ctx, elem), value in self._edits.items():
            if elem == "crosshairs":
                settings.setValue(_CROSSHAIR_KEY, value)
            else:
                window_colors.set_background(ctx, value)
        super().accept()

    def changed_backgrounds(self) -> bool:
        """Did any background change? (the caller must regen then)."""
        return any(elem == "background" for (_c, elem) in self._edits)
