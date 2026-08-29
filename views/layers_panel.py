# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Layer manager panel (LA), classic AutoCAD-style table.

Columns: current, name, on, freeze, lock, color. Toolbar: new / delete /
set-current. Double-click a row makes it current; the name cell renames.
Every change routes through the layer Commands so undo/redo is exact.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core import layers as layer_ops
from core.i18n import tr

# ACI 1-9 to RGB (the classic AutoCAD standard colors), enough for the
# swatch + picker; higher indices fall back to a neutral grey chip.
ACI_RGB = {
    1: (255, 0, 0), 2: (255, 255, 0), 3: (0, 255, 0), 4: (0, 255, 255),
    5: (0, 0, 255), 6: (255, 0, 255), 7: (255, 255, 255), 8: (128, 128, 128),
    9: (192, 192, 192),
}


# Standard AutoCAD color names for indices 1-9.
ACI_NAMES = {
    1: "Red", 2: "Yellow", 3: "Green", 4: "Cyan", 5: "Blue",
    6: "Magenta", 7: "White", 8: "Gray", 9: "Light gray",
}


def aci_to_qcolor(index: int) -> QColor:
    rgb = ACI_RGB.get(index)
    if rgb is None:
        # the full 255-color ACI palette, ezdxf's table
        from views.color_dialog import aci_qcolor

        return aci_qcolor(index)
    return QColor(*rgb)


def swatch_icon(index: int, size: int = 13):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    from PySide6.QtGui import QPainter, QPen
    p = QPainter(pm)
    p.fillRect(1, 1, size - 2, size - 2, aci_to_qcolor(index))
    p.setPen(QPen(QColor(70, 70, 70)))
    p.drawRect(1, 1, size - 3, size - 3)
    p.end()
    return QIcon(pm)


# Dash patterns for the previews, by the family a standard linetype's name
# starts with. The drawing carries the real definitions; this only has to
# make the list recognisable at a glance, the way AutoCAD's preview does.
_LINETYPE_DASHES = (
    ("CENTER", [9, 3, 3, 3]),
    ("DASHDOT", [8, 3, 1, 3]),
    ("DASHED", [7, 4]),
    ("DIVIDE", [8, 3, 1, 3, 1, 3]),
    ("DOT", [1, 4]),
    ("PHANTOM", [10, 3, 2, 3, 2, 3]),
    ("HIDDEN", [5, 3]),
)


def linetype_icon(name: str, document=None, width: int = 58, height: int = 12):
    """A short sample of the linetype, as the AutoCAD combo shows."""
    from PySide6.QtGui import QPainter, QPen

    pm = QPixmap(width, height)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    pen = QPen(QColor(220, 220, 220), 1.3)
    upper = (name or "").upper()
    for prefix, dashes in _LINETYPE_DASHES:
        if upper.startswith(prefix):
            pen.setDashPattern([d for d in dashes])
            break
    p.setPen(pen)
    p.drawLine(2, height // 2, width - 2, height // 2)
    p.end()
    return QIcon(pm)


def lineweight_icon(value: int, width: int = 34, height: int = 12):
    """A line drawn at the weight it names (ByLayer/ByBlock stay hairlines)."""
    from PySide6.QtGui import QPainter, QPen

    pm = QPixmap(width, height)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    # 0.00 mm is a hairline; 2.11 mm is the thickest AutoCAD offers. Five
    # pixels of range is enough to tell them apart in a combo.
    thickness = 1.0 if value < 0 else 1.0 + min(value, 211) / 211.0 * 4.0
    p.setPen(QPen(QColor(220, 220, 220), thickness))
    p.drawLine(2, height // 2, width - 2, height // 2)
    p.end()
    return QIcon(pm)


_PICK_COLOR = -999


def fill_color_combo(combo, include_bylayer: bool = True) -> None:
    """Populate a color combo with swatches (not "Color N" text).

    The last entry opens the Select Color dialog (the full ACI palette);
    the picked color joins the combo as a normal item and the consumer's
    activated/currentIndexChanged flow fires as if it had been listed all
    along — so every color combo in the app gains the palette for free.
    """
    from views.properties_panel import BYLAYER_COLOR
    if include_bylayer:
        combo.addItem(tr("ByLayer"), BYLAYER_COLOR)
        combo.addItem(tr("ByBlock"), 0)
    for aci in sorted(ACI_RGB):
        name = tr(ACI_NAMES[aci]) if aci in ACI_NAMES else str(aci)
        combo.addItem(swatch_icon(aci), name, aci)
    combo.addItem(tr("Select Color..."), _PICK_COLOR)

    state = {"last": 0}

    def on_activated(index: int) -> None:
        if combo.itemData(index) != _PICK_COLOR:
            state["last"] = index
            return
        from views.color_dialog import SelectColorDialog

        dialog = SelectColorDialog(combo.window(),
                                   include_bylayer=include_bylayer)
        if not dialog.exec():
            combo.setCurrentIndex(state["last"])
            return
        aci = dialog.result_aci()
        found = combo.findData(aci)
        if found < 0:
            found = combo.count() - 1     # insert before "Select Color..."
            combo.insertItem(found, swatch_icon(aci), tr("Color {n}", n=aci),
                             aci)
        combo.setCurrentIndex(found)
        combo.activated.emit(found)

    combo.activated.connect(on_activated)


def nearest_aci(color: QColor) -> int:
    best, best_d = 7, 1e18
    for idx, (r, g, b) in ACI_RGB.items():
        d = (r - color.red()) ** 2 + (g - color.green()) ** 2 + (b - color.blue()) ** 2
        if d < best_d:
            best, best_d = idx, d
    return best


COLLAPSED_WIDTH = 22

_PANEL_STYLE = """
LayersPanel { background: #26262a; }
LayersPanel QTableWidget { font-size: 11px; background: #1e1e22;
    alternate-background-color: #232327; }
LayersPanel QHeaderView::section { background: #2d2d31; padding: 1px;
    border: none; font-size: 11px; }
LayersPanel QToolButton { border: none; color: #c8c8c8; padding: 2px 5px;
    font-size: 11px; }
LayersPanel QToolButton:hover { background: #3a3940; }
LayersPanel #sideLabel { color: #b0b0b0; font-weight: bold; }
"""


class LayersPanel(QWidget):
    changed = Signal()   # a layer edit landed: repaint the viewport

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.setObjectName("LayersPanel")
        self.setStyleSheet(_PANEL_STYLE)

        # Columns mirror the Layer Properties Manager (v0.2 subset): Status,
        # Name, On, Freeze, Lock, Color, Linetype, Lineweight, Plot,
        # Description. (Transparency / Plot Style / VP columns: see the
        # audit in docs/reference/layers-and-command-line.md.)
        self.table = QTableWidget(0, 10, self)
        self.table.setHorizontalHeaderItem(0, self._header_item("✓", tr("Status")))
        self.table.setHorizontalHeaderItem(1, self._header_item(tr("Name"), tr("Name")))
        self.table.setHorizontalHeaderItem(2, self._header_item("◍", tr("On/Off")))
        self.table.setHorizontalHeaderItem(3, self._header_item("❄", tr("Freeze")))
        self.table.setHorizontalHeaderItem(4, self._header_item("🔒", tr("Lock")))
        self.table.setHorizontalHeaderItem(5, self._header_item("■", tr("Color")))
        self.table.setHorizontalHeaderItem(6, self._header_item(tr("Linetype"), tr("Linetype")))
        self.table.setHorizontalHeaderItem(7, self._header_item(tr("Lineweight"), tr("Lineweight")))
        self.table.setHorizontalHeaderItem(8, self._header_item("🖶", tr("Plot")))
        self.table.setHorizontalHeaderItem(9, self._header_item(tr("Description"), tr("Description")))
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(20)  # compact rows

        #: Columns the user has resized by hand: their width is theirs.
        self._user_sized: set[int] = set()
        self._auto_sizing = False

        header = self.table.horizontalHeader()
        # Every column that carries a value sizes itself to that value. The
        # widths used to be constants, and they were too small for their own
        # content at EVERY width of the panel -- measured on a real plan:
        # Color got 40 px and needed 43, Linetype 84 of 99, Lineweight 68 of
        # 85 -- so widening the sidebar never revealed them, and what it did
        # instead was squeeze Name and Description down to 24 px.
        # Interactive, NOT ResizeToContents: that mode re-measures the whole
        # column on every setItem while the table fills, which is O(rows^2)
        # -- measured on a real plan of 82 layers, one bulb click froze the
        # UI for 16 s against 103 ms. The content width is computed once per
        # refresh instead, in _size_columns.
        for col in (0, 2, 3, 4, 5, 6, 7, 8):
            header.setSectionResizeMode(col, QHeaderView.Interactive)
        # The two that can take any width: Name keeps whatever the user
        # gives it (and remembers it), Description takes what is left.
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(9, QHeaderView.Stretch)
        self.table.setColumnWidth(1, self._remembered_name_width())
        self.table.setTextElideMode(Qt.ElideRight)
        header.sectionResized.connect(self._remember_name_width_change)
        # AutoCAD's Layer Properties Manager lets you right-click the header
        # and turn columns off; in a sidebar barely 280 px wide that is the
        # difference between scrolling sideways and reading the list.
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self._header_menu)
        self._restore_hidden_columns()

        self.table.cellDoubleClicked.connect(self._on_double_click)
        self.table.cellChanged.connect(self._on_cell_changed)
        self.table.cellClicked.connect(self._on_cell_clicked)

        # Compact icon-buttons instead of wide text buttons.
        new_btn = self._tool_button("＋", tr("New layer"), self._new_layer)
        del_btn = self._tool_button("🗑", tr("Delete layer"), self._delete_layer)
        cur_btn = self._tool_button("✓", tr("Set current"),
                                    self._set_current_selected)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(2, 2, 2, 0)
        buttons.setSpacing(1)
        for b in (new_btn, del_btn, cur_btn):
            buttons.addWidget(b)
        # "Search for layer" — filters the list live, like the manager's box.
        from PySide6.QtWidgets import QLineEdit
        self.search = QLineEdit(self)
        self.search.setPlaceholderText(tr("Search for layer"))
        self.search.setClearButtonEnabled(True)
        self.search.setStyleSheet(
            "QLineEdit { background: #1e1e22; border: 1px solid #3a3940;"
            " color: #d0d0d0; font-size: 11px; padding: 1px 4px; }")
        self.search.textChanged.connect(lambda *_: self.refresh())
        buttons.addWidget(self.search, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        layout.addLayout(buttons)
        layout.addWidget(self.table)

        self._loading = False
        self.refresh()

    def _tool_button(self, text, tip, slot) -> QToolButton:
        btn = QToolButton(self)
        btn.setText(text)
        btn.setToolTip(tip)
        btn.clicked.connect(slot)
        return btn

    @staticmethod
    def _header_item(text: str, tooltip: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setToolTip(tooltip)
        item.setTextAlignment(Qt.AlignCenter)
        return item

    # -- data -----------------------------------------------------------------
    @property
    def document(self):
        return self.window.document

    #: Default width of the Name column, in pixels: a real plan's layer
    #: names ("_R_COLUMNAS_...", "0018 fondo") need about this much.
    NAME_WIDTH = 150

    def _remembered_name_width(self) -> int:
        try:
            width = int(QSettings().value("layers/name_width", self.NAME_WIDTH))
        except (TypeError, ValueError):
            width = self.NAME_WIDTH
        return max(40, width)

    def _remember_name_width_change(self, index: int, _old: int,
                                    new: int) -> None:
        """The user dragged a column edge: keep it.

        Name is kept across sessions; the value columns are remembered for
        the session, so that a width the user chose is not undone by the
        next refresh's content sizing.
        """
        if self._auto_sizing or new <= 0:
            return
        self._user_sized.add(index)
        if index == 1:
            QSettings().setValue("layers/name_width", int(new))

    def _size_columns(self) -> None:
        """Content widths for the value columns, computed ONCE per refresh.

        Columns the user has dragged keep the width they were given.
        """
        self._auto_sizing = True
        try:
            for col in (0, 2, 3, 4, 5, 6, 7, 8):
                if col not in self._user_sized and not self.table.isColumnHidden(col):
                    self.table.resizeColumnToContents(col)
        finally:
            self._auto_sizing = False

    #: Columns the user can hide. Name is not one of them -- a layer list
    #: without names is not a layer list.
    HIDEABLE = (0, 2, 3, 4, 5, 6, 7, 8, 9)

    def _restore_hidden_columns(self) -> None:
        stored = QSettings().value("layers/hidden_columns", "")
        hidden = {int(c) for c in str(stored or "").split(",") if c.strip().isdigit()}
        for col in self.HIDEABLE:
            self.table.setColumnHidden(col, col in hidden)

    def _save_hidden_columns(self) -> None:
        hidden = [str(c) for c in self.HIDEABLE if self.table.isColumnHidden(c)]
        QSettings().setValue("layers/hidden_columns", ",".join(hidden))

    def _header_menu(self, pos) -> None:
        """Right-click on the header: which columns to show, and optimize."""
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        for col in self.HIDEABLE:
            item = self.table.horizontalHeaderItem(col)
            action = menu.addAction(item.toolTip() if item else str(col))
            action.setCheckable(True)
            action.setChecked(not self.table.isColumnHidden(col))
            action.triggered.connect(
                lambda checked, c=col: self._toggle_column(c, checked))
        menu.addSeparator()
        menu.addAction(tr("Optimize all columns"), self._optimize_columns)
        menu.exec(self.table.horizontalHeader().mapToGlobal(pos))

    def _toggle_column(self, col: int, visible: bool) -> None:
        self.table.setColumnHidden(col, not visible)
        self._save_hidden_columns()

    def _optimize_columns(self) -> None:
        """Every column back to the width its content needs, Name included."""
        self.table.resizeColumnToContents(1)
        QSettings().setValue("layers/name_width",
                             int(self.table.columnWidth(1)))

    def refresh(self) -> None:
        if self.document is None:
            self.table.setRowCount(0)
            return
        self._loading = True
        infos = layer_ops.layer_list(self.document)
        needle = self.search.text().strip().lower() if hasattr(self, "search") else ""
        if needle:
            import fnmatch
            pattern = needle if any(c in needle for c in "*?") else f"*{needle}*"
            infos = [i for i in infos
                     if fnmatch.fnmatchcase(i.name.lower(), pattern)]
        self._rows = [i.name for i in infos]
        self.table.setRowCount(len(infos))
        for row, info in enumerate(infos):
            self._fill_row(row, info)
        self._loading = False
        self._size_columns()

    def _fill_row(self, row: int, info: layer_ops.LayerInfo) -> None:
        # Status: current / in use / empty (the manager's official trio).
        status = "✓" if info.is_current else ("▪" if info.in_use else "")
        cur = QTableWidgetItem(status)
        cur.setToolTip(tr("Current layer") if info.is_current
                       else (tr("Layer in use") if info.in_use
                             else tr("Empty layer")))
        cur.setTextAlignment(Qt.AlignCenter)
        cur.setFlags(Qt.ItemIsEnabled)
        self.table.setItem(row, 0, cur)

        name = QTableWidgetItem(info.name)
        if info.name == "0":
            name.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)  # 0 locked-name
        self.table.setItem(row, 1, name)

        for col, on in ((2, info.is_on), (3, not info.is_frozen), (4, not info.is_locked)):
            item = QTableWidgetItem(self._state_glyph(col, on))
            item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row, col, item)

        swatch = QTableWidgetItem(str(info.color))
        swatch.setTextAlignment(Qt.AlignCenter)
        pm = QPixmap(12, 12)
        pm.fill(aci_to_qcolor(info.color))
        swatch.setIcon(QIcon(pm))
        swatch.setToolTip(tr("ACI color {n}", n=info.color))
        swatch.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self.table.setItem(row, 5, swatch)

        lt = QTableWidgetItem(info.linetype)
        lt.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self.table.setItem(row, 6, lt)

        lw = QTableWidgetItem(layer_ops.lineweight_label(info.lineweight))
        lw.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self.table.setItem(row, 7, lw)

        plot = QTableWidgetItem("🖶" if info.plot else "🚫")
        plot.setTextAlignment(Qt.AlignCenter)
        plot.setToolTip(tr("Plot") if info.plot else tr("Do not plot"))
        plot.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self.table.setItem(row, 8, plot)

        descr = QTableWidgetItem(info.description)
        self.table.setItem(row, 9, descr)

    @staticmethod
    def _state_glyph(col: int, active: bool) -> str:
        if col == 2:   # on
            return "💡" if active else "🌑"
        if col == 3:   # thawed (not frozen)
            return "☀" if active else "❄"
        return "🔓" if active else "🔒"   # unlocked

    def _row_layer(self, row: int) -> str:
        rows = getattr(self, "_rows", [])
        if 0 <= row < len(rows):
            return rows[row]
        item = self.table.item(row, 1)
        return item.text() if item else ""

    # -- edits ----------------------------------------------------------------
    def _execute(self, command) -> None:
        self.window.history.execute(command)
        self.window.regen_in_memory()
        self.refresh()
        self.changed.emit()

    def _new_layer(self) -> None:
        if self.document is None:
            self.window.new_document()
        name = layer_ops.unique_layer_name(self.document)
        # The new layer inherits the selected layer's properties (official).
        row = self.table.currentRow()
        base = next((i for i in layer_ops.layer_list(self.document)
                     if row >= 0 and i.name == self._row_layer(row)), None)
        if base is not None:
            self._execute(layer_ops.NewLayerCommand(
                name, color=base.color, linetype=base.linetype,
                lineweight=base.lineweight))
        else:
            self._execute(layer_ops.NewLayerCommand(name))

    def _delete_layer(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        name = self._row_layer(row)
        if name in ("0", "Defpoints"):
            self.window.command_line.echo(
                tr("Layer {name} cannot be deleted.", name=name))
            return
        if name == layer_ops.current_layer_name(self.document):
            self.window.command_line.echo(tr("Cannot delete the current layer."))
            return
        # Referenced layers cannot be deleted — anywhere: every layout and
        # every block definition (official rule).
        if name in layer_ops.layers_in_use(self.document):
            self.window.command_line.echo(tr("Layer {name} is in use.", name=name))
            return
        self._execute(layer_ops.DeleteLayerCommand(name))

    def _set_current_selected(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self._make_current(self._row_layer(row))

    def _make_current(self, name: str) -> None:
        layer_ops.set_current_layer(self.document, name)
        self.refresh()
        self.changed.emit()

    def _on_double_click(self, row: int, col: int) -> None:
        if col != 1:
            self._make_current(self._row_layer(row))

    def _on_cell_clicked(self, row: int, col: int) -> None:
        if self._loading or self.document is None:
            return
        name = self._row_layer(row)
        if col in (2, 3, 4):
            prop = {2: "on", 3: "frozen", 4: "locked"}[col]
            glyph = self.table.item(row, col).text()
            active = glyph in ("💡", "☀", "🔓")
            # toggling: on->off, thawed->frozen, unlocked->locked
            if prop == "on":
                self._execute(layer_ops.LayerPropertyCommand(name, "on", not active))
            elif prop == "frozen":
                self._execute(layer_ops.LayerPropertyCommand(name, "frozen", active))
            else:
                self._execute(layer_ops.LayerPropertyCommand(name, "locked", active))
        elif col == 5:
            info = next((i for i in layer_ops.layer_list(self.document)
                         if i.name == name), None)
            start = aci_to_qcolor(info.color) if info else QColor("white")
            chosen = QColorDialog.getColor(start, self, tr("Layer color"))
            if chosen.isValid():
                self._execute(layer_ops.LayerPropertyCommand(
                    name, "color", nearest_aci(chosen)))
        elif col == 6:
            self._pick_linetype(name)
        elif col == 7:
            self._pick_lineweight(name)
        elif col == 8:
            info = next((i for i in layer_ops.layer_list(self.document)
                         if i.name == name), None)
            if info is not None:
                self._execute(layer_ops.LayerPropertyCommand(
                    name, "plot", not info.plot))

    def _pick_linetype(self, name: str) -> None:
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        for lt in layer_ops.available_linetypes(self.document):
            menu.addAction(lt, lambda lt=lt: self._execute(
                layer_ops.LayerPropertyCommand(name, "linetype", lt)))
        menu.exec(QCursor.pos())

    def _pick_lineweight(self, name: str) -> None:
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        for lw in layer_ops.LINEWEIGHTS:
            menu.addAction(layer_ops.lineweight_label(lw), lambda lw=lw: self._execute(
                layer_ops.LayerPropertyCommand(name, "lineweight", lw)))
        menu.exec(QCursor.pos())

    def _on_cell_changed(self, row: int, col: int) -> None:
        if self._loading or self.document is None:
            return
        name = self._row_layer(row)
        if not name:
            return
        if col == 9:                      # Description (free text, undoable)
            text = self.table.item(row, 9).text()
            self._execute(layer_ops.LayerPropertyCommand(
                name, "description", text))
            return
        if col != 1:
            return
        new_name = self.table.item(row, 1).text().strip()
        names = [i.name for i in layer_ops.layer_list(self.document)]
        if not new_name or new_name == name:
            self.refresh()
            return
        if new_name in names:
            self.window.command_line.echo(
                tr("Layer {name} already exists.", name=new_name))
            self.refresh()
            return
        self._execute(layer_ops.RenameLayerCommand(name, new_name))
