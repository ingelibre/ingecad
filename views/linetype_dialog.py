# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""AutoCAD's linetype dialogs: the Linetype Manager, Select Linetype, and
Load or Reload Linetypes.

The Linetype Manager lists what a drawing has loaded in three columns,
**Linetype / Appearance / Description** (reference p. 1045), and the
Appearance column is a *drawn sample* of the pattern: it is how a drafter
tells CENTER from PHANTOM without reading. The Load button brings in
definitions from the standard library, because a drawing can only use the
linetypes loaded into it.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core import linetypes as lt_ops
from core.i18n import tr, tr_context

SAMPLE_W = 150
SAMPLE_H = 16
#: Pixels per drawing unit in a sample. Chosen so the classic quarter-inch
#: family (HIDDEN 0.375 units) reads as dashes and CENTER (2.0) shows about
#: three periods, the way the manager's list looks in AutoCAD.
UNIT_PX = 26.0


def pattern_pixmap(pattern, width: int = SAMPLE_W, height: int = SAMPLE_H,
                   color: QColor | None = None) -> QPixmap:
    """The Appearance column: the dash pattern drawn as a line.

    ``pattern`` is a LIN definition's dashes -- positive is a dash, negative
    a gap, 0.0 a dot -- in drawing units. The swatch is drawn at a FIXED
    number of pixels per drawing unit, so CENTER, CENTER2 and CENTERX2 look
    like what they are: the same shape at half, one and twice the size.
    Normalising each pattern to the swatch instead -- the obvious way --
    draws all three identically, which is exactly the difference the
    Appearance column exists to show. A pattern too long for one period at
    that scale (the ISO ones run to 30 units) is shrunk to fit one.
    """
    pen_color = color or QColor(235, 235, 235)
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, False)
    painter.setPen(QPen(pen_color, 1.4))
    y = height / 2.0
    dashes = [d for d in pattern if d is not None]
    total = sum(abs(d) for d in dashes)
    if not dashes or total <= 0.0:
        painter.drawLine(2, int(y), width - 2, int(y))   # CONTINUOUS
        painter.end()
        return pixmap
    usable = width - 4
    unit = UNIT_PX
    if total * unit > usable:
        unit = usable / total      # one full period, for the long ISO ones
    x = 2.0
    while x < width - 2:
        for dash in dashes:
            length = abs(dash) * unit
            if dash > 0:
                painter.drawLine(int(x), int(y), int(min(x + length, width - 2)),
                                 int(y))
            elif dash == 0:
                painter.drawPoint(int(x), int(y))
                length = max(length, 1.5)
            x += length
            if x >= width - 2:
                break
    painter.end()
    return pixmap


def _shown(document, name: str) -> str:
    """A loaded linetype's description as the interface shows it."""
    return lt_ops.shown_description(lt_ops.description_of(document, name))


class SelectLinetypeDialog(QDialog):
    """The loaded linetypes, with their samples. ``result_name()`` answers."""

    def __init__(self, parent, document, current: str | None = None,
                 include_bylayer: bool = False, history=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Select Linetype"))
        self.document = document
        # The undo history Load runs its command on. Passed in, not found by
        # walking up to the parent's window: the Layers panel keeps the main
        # window in an attribute named ``window``, which shadows
        # QWidget.window(), so the walk raised a TypeError inside the slot --
        # swallowed by Qt -- and Load never loaded anything (0.4.7 to 0.6.6).
        self._history = history
        self._name = current
        self._include_bylayer = include_bylayer

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("Loaded linetypes")))
        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(
            [tr("Linetype"), tr("Appearance"), tr("Description")])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setIconSize(QSize(SAMPLE_W, SAMPLE_H))
        self.table.verticalHeader().setDefaultSectionSize(SAMPLE_H + 6)
        self.table.doubleClicked.connect(self._accept_row)
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        load = QPushButton(tr("Load..."), self)
        load.setToolTip(tr("Load linetype definitions into this drawing"))
        load.clicked.connect(self._load)
        buttons.addWidget(load)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
                               parent=self)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)
        self.resize(520, 420)
        self._fill()

    # -- contents --------------------------------------------------------------
    def _rows(self) -> list[str]:
        names = lt_ops.loaded_names(self.document)
        if self._include_bylayer:
            names = ["ByLayer", "ByBlock"] + names
        return names

    def _fill(self) -> None:
        names = self._rows()
        self.table.setRowCount(len(names))
        for row, name in enumerate(names):
            item = QTableWidgetItem(name)
            self.table.setItem(row, 0, item)
            sample = QTableWidgetItem()
            if name.lower() in ("bylayer", "byblock"):
                sample.setText("—")
            else:
                sample.setIcon(QIcon(pattern_pixmap(
                    lt_ops.pattern_of(self.document, name))))
            self.table.setItem(row, 1, sample)
            self.table.setItem(row, 2, QTableWidgetItem(
                _shown(self.document, name)))
            if self._name and name.lower() == self._name.lower():
                self.table.selectRow(row)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.resizeColumnToContents(0)
        self.table.setColumnWidth(1, SAMPLE_W + 12)
        if self.table.currentRow() < 0 and names:
            self.table.selectRow(0)

    def _accept_row(self, *_args) -> None:
        self.accept()

    def _load(self) -> None:
        execute = self._history.execute if self._history is not None else None
        names = run_load(self, self.document, execute)
        if names:
            self._name = names[0]
            self._fill()

    def result_name(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.text() if item else None


def sample_dashes(pattern) -> list[float]:
    """The dashes to draw a sample from: a complex LIN pattern's numbers,
    leaving out what is in brackets (its text or shape)."""
    if not isinstance(pattern, str):
        return list(pattern)
    import re

    body = re.sub(r"\[[^\]]*\]", "", pattern)
    if body[:2].upper() == "A,":
        body = body[2:]
    values = []
    for part in body.split(","):
        try:
            values.append(float(part))
        except ValueError:
            continue
    return values


def run_load(parent, document, execute=None) -> list[str]:
    """The Load button, wherever it is pressed: the Load or Reload dialog,
    AutoCAD's "already loaded -- reload it?" for each loaded one picked, then
    one undoable command. Returns the names that were loaded or reloaded."""
    dialog = LoadLinetypesDialog(parent, document)
    if not dialog.exec():
        return []
    names = dialog.result_names()
    if not names:
        return []
    loaded = {n.upper() for n in lt_ops.loaded_names(document)}
    reload = [n for n in names if n.upper() in loaded
              and dialog.ask_reload(n)]
    wanted = [n for n in names if n.upper() not in loaded or n in reload]
    if not wanted:
        return []
    command = lt_ops.LoadLinetypesCommand(wanted, catalog=dialog.catalog,
                                          reload=reload)
    if execute is not None:
        execute(command)
    else:
        command.do(document)
    return wanted


class LoadLinetypesDialog(QDialog):
    """Load or Reload Linetypes (reference p. 1046): the File button and
    name, and the Available Linetypes list with Select All / Clear All on
    its right-click menu. The list is the WHOLE library, loaded ones too --
    picking one of those is a reload, which AutoCAD confirms first.

    The standard library is :mod:`core.linetypes`; the File button reads any
    LIN file, AutoCAD's own included.
    """

    def __init__(self, parent, document) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Load or Reload Linetypes"))
        self.document = document
        self.catalog = None                   # None: the standard library
        self.source_path = None

        layout = QVBoxLayout(self)
        file_row = QHBoxLayout()
        self.file_button = QPushButton(tr("File..."), self)
        self.file_button.clicked.connect(self._pick_file)
        file_row.addWidget(self.file_button)
        # the standard library is a real LIN file too (as acad.lin is)
        standard = lt_ops.standard_lin_file(document)
        self.file_name = QLineEdit(standard.name, self)
        self.file_name.setToolTip(str(standard))
        self.file_name.setReadOnly(True)
        file_row.addWidget(self.file_name, 1)
        layout.addLayout(file_row)

        layout.addWidget(QLabel(tr("Available linetypes")))
        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(
            [tr("Linetype"), tr("Appearance"), tr("Description")])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setIconSize(QSize(SAMPLE_W, SAMPLE_H))
        self.table.verticalHeader().setDefaultSectionSize(SAMPLE_H + 6)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.doubleClicked.connect(lambda *_a: self.accept())
        layout.addWidget(self.table)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
                               parent=self)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)
        self.resize(560, 480)
        self._fill()

    def _entries(self) -> dict:
        return self.catalog if self.catalog is not None \
            else lt_ops.library(self.document)

    def _fill(self) -> None:
        entries = self._entries()
        names = [n for n in entries if n.upper() not in lt_ops.RESERVED]
        names.sort()
        self.table.setRowCount(len(names))
        for row, name in enumerate(names):
            description, pattern = entries[name]
            self.table.setItem(row, 0, QTableWidgetItem(name))
            sample = QTableWidgetItem()
            sample.setIcon(QIcon(pattern_pixmap(sample_dashes(pattern))))
            self.table.setItem(row, 1, sample)
            self.table.setItem(row, 2, QTableWidgetItem(
                lt_ops.shown_description(description)))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        # ACAD_ISO02W100 is 14 characters: size the name column to the names
        # it holds instead of cutting them, once, after the rows are in.
        self.table.resizeColumnToContents(0)
        self.table.setColumnWidth(1, SAMPLE_W + 12)

    def load_file(self, path) -> bool:
        """Read a LIN file into the list. False (and the list unchanged)
        when it holds no definition this reader understands."""
        try:
            entries = lt_ops.read_lin_file(path)
        except OSError:
            entries = {}
        if not entries:
            return False
        from pathlib import Path

        self.catalog = entries
        self.source_path = str(path)
        self.file_name.setText(Path(path).name)
        self.file_name.setToolTip(str(path))
        self._fill()
        return True

    def _pick_file(self) -> None:
        from views.file_dialogs import get_open_file

        path = get_open_file(self, tr("Select Linetype File"),
                             tr("Linetype files (*.lin)") + ";;"
                             + tr("All files (*)"),
                             select_file=self.source_path
                             or lt_ops.standard_lin_file(self.document))
        if path and not self.load_file(path):
            QMessageBox.warning(self, tr("Load or Reload Linetypes"),
                                tr("No linetype definitions found in {name}.",
                                   name=path))

    def _context_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addAction(tr("Select all"), self.table.selectAll)
        menu.addAction(tr("Clear all"), self.table.clearSelection)
        menu.exec(self.table.viewport().mapToGlobal(pos))
        menu.deleteLater()

    def ask_reload(self, name: str) -> bool:
        """AutoCAD's 'Linetype X is already loaded. Reload it?'"""
        answer = QMessageBox.question(
            self, tr("Reload Linetype"),
            tr("Linetype {name} is already loaded. Reload it?", name=name),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        return answer == QMessageBox.Yes

    def result_names(self) -> list[str]:
        rows = {index.row() for index in self.table.selectedIndexes()}
        return [self.table.item(row, 0).text() for row in sorted(rows)]


#: The manager's three filters (reference p. 1044), in AutoCAD's order.
FILTERS = ("Show all linetypes", "Show all used linetypes",
           "Show all Xref dependent linetypes")


class LinetypeManagerDialog(QDialog):
    """AutoCAD's Linetype Manager (LINETYPE, reference pp. 1043-1046).

    Load and Delete act at once, each its own undo step, as the list shows
    the drawing's linetypes. Everything else -- Current, a rename, the
    description and the three scales -- waits for OK and lands as one undo
    step; Cancel leaves the drawing as it was.
    """

    def __init__(self, parent, document, execute) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Linetype Manager"))
        self.document = document
        self._execute = execute
        header = document.doc.header
        self._current = str(header.get("$CELTYPE", "ByLayer"))
        self._renames: dict[str, str] = {}          # original -> new name
        self._descriptions: dict[str, str] = {}     # original -> description
        self._loading = False

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        filters = QGroupBox(tr("Linetype filters"), self)
        filter_row = QHBoxLayout(filters)
        self.filter = QComboBox(filters)
        for key in FILTERS:
            self.filter.addItem(tr(key), key)
        self.filter.currentIndexChanged.connect(self._fill)
        filter_row.addWidget(self.filter, 1)
        self.invert = QCheckBox(tr("Invert filter"), filters)
        self.invert.toggled.connect(self._fill)
        filter_row.addWidget(self.invert)
        top.addWidget(filters, 1)

        buttons = QVBoxLayout()
        self.load_button = QPushButton(tr("Load..."), self)
        self.load_button.clicked.connect(self._load)
        self.delete_button = QPushButton(tr_context("Linetype manager|Delete"), self)
        self.delete_button.clicked.connect(self._delete)
        self.current_button = QPushButton(tr("Current"), self)
        self.current_button.clicked.connect(self._set_current)
        self.details_button = QPushButton(tr("Show details"), self)
        self.details_button.clicked.connect(self._toggle_details)
        grid = QHBoxLayout()
        grid.addWidget(self.load_button)
        grid.addWidget(self.delete_button)
        buttons.addLayout(grid)
        grid2 = QHBoxLayout()
        grid2.addWidget(self.current_button)
        grid2.addWidget(self.details_button)
        buttons.addLayout(grid2)
        top.addLayout(buttons)
        layout.addLayout(top)

        self.current_label = QLabel(self)
        layout.addWidget(self.current_label)

        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(
            [tr("Linetype"), tr("Appearance"), tr("Description")])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setIconSize(QSize(SAMPLE_W, SAMPLE_H))
        self.table.verticalHeader().setDefaultSectionSize(SAMPLE_H + 6)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.itemSelectionChanged.connect(self._on_selection)
        layout.addWidget(self.table, 1)

        # -- Details ------------------------------------------------------------
        self.details = QGroupBox(tr("Details"), self)
        form = QFormLayout(self.details)
        self.name_edit = QLineEdit(self.details)
        self.name_edit.editingFinished.connect(self._commit_name)
        form.addRow(tr("Name:"), self.name_edit)
        self.description_edit = QLineEdit(self.details)
        self.description_edit.editingFinished.connect(self._commit_description)
        form.addRow(tr("Description:"), self.description_edit)
        self.paper_units = QCheckBox(
            tr("Use paper space units for scaling"), self.details)
        self.paper_units.setChecked(bool(int(header.get("$PSLTSCALE", 1))))
        form.addRow(self.paper_units)
        self.global_scale = QLineEdit(
            f"{float(header.get('$LTSCALE', 1.0)):.4f}", self.details)
        form.addRow(tr("Global scale factor:"), self.global_scale)
        self.object_scale = QLineEdit(
            f"{float(header.get('$CELTSCALE', 1.0)):.4f}", self.details)
        self.object_scale.textEdited.connect(self._object_scale_typed)
        form.addRow(tr("Current object scale:"), self.object_scale)
        self.pen_width = QComboBox(self.details)
        for width in lt_ops.ISO_PEN_WIDTHS:
            self.pen_width.addItem(f"{width:.2f} mm", width)
        self.pen_width.activated.connect(self._pen_width_picked)
        form.addRow(tr("ISO pen width:"), self.pen_width)
        layout.addWidget(self.details)
        self.details.setVisible(False)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
                               parent=self)
        box.accepted.connect(self._ok)
        box.rejected.connect(self.reject)
        layout.addWidget(box)
        self.resize(640, 460)
        self._sync_pen_width()
        self._fill()

    # -- the list ---------------------------------------------------------------
    def _display(self, name: str) -> str:
        return self._renames.get(name, name)

    def _rows(self) -> list[str]:
        names = lt_ops.loaded_names(self.document)
        key = self.filter.currentData()
        if key == "Show all used linetypes":
            from core.cleanup import used_linetypes

            used = used_linetypes(self.document.doc)
            keep = [n for n in names if n.upper() in used]
        elif key == "Show all Xref dependent linetypes":
            keep = [n for n in names if lt_ops.is_xref_dependent(n)]
        else:
            keep = list(names)
        if self.invert.isChecked():
            keep = [n for n in names if n not in keep]
        if key == "Show all linetypes" and not self.invert.isChecked():
            keep = ["ByLayer", "ByBlock"] + keep
        return keep

    def _fill(self, *_args) -> None:
        self._loading = True
        selected = set(self.selected_names())
        names = self._rows()
        self.table.setRowCount(len(names))
        for row, name in enumerate(names):
            item = QTableWidgetItem(self._label(name))
            item.setData(Qt.UserRole, name)
            self.table.setItem(row, 0, item)
            sample = QTableWidgetItem()
            if name.lower() not in ("bylayer", "byblock"):
                sample.setIcon(QIcon(pattern_pixmap(
                    lt_ops.pattern_of(self.document, name))))
            self.table.setItem(row, 1, sample)
            self.table.setItem(row, 2, QTableWidgetItem(
                self._descriptions.get(name, _shown(self.document, name))))
            if name in selected:
                self.table.selectRow(row)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.resizeColumnToContents(0)
        self.table.setColumnWidth(1, SAMPLE_W + 12)
        self._loading = False
        self.current_label.setText(
            tr("Current linetype: {name}", name=self._label(self._current)))
        self._on_selection()

    def _label(self, name: str) -> str:
        if name.lower() == "bylayer":
            return tr("ByLayer")
        if name.lower() == "byblock":
            return tr("ByBlock")
        return self._display(name)

    def selected_names(self) -> list[str]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        out = []
        for row in rows:
            item = self.table.item(row, 0)
            if item is not None:
                out.append(item.data(Qt.UserRole))
        return out

    def select(self, name: str) -> None:
        """Make ``name`` the one selected row. Through the selection model:
        ``selectRow`` in extended mode leaves the current row unselected
        when it is asked to select it again."""
        from PySide6.QtCore import QItemSelectionModel

        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.UserRole).upper() == name.upper():
                index = self.table.model().index(row, 0)
                self.table.selectionModel().setCurrentIndex(
                    index, QItemSelectionModel.ClearAndSelect
                    | QItemSelectionModel.Rows)
                return

    def _on_selection(self) -> None:
        if self._loading:
            return
        names = self.selected_names()
        one = names[0] if len(names) == 1 else None
        self.current_button.setEnabled(one is not None)
        self.delete_button.setEnabled(bool(names))
        editable = one is not None and one.upper() not in lt_ops.RESERVED \
            and not lt_ops.is_xref_dependent(one)
        self.name_edit.setText(self._label(one) if one else "")
        self.name_edit.setEnabled(editable)
        self.description_edit.setText(
            self._descriptions.get(one, _shown(self.document, one))
            if one and one.lower() not in ("bylayer", "byblock") else "")
        self.description_edit.setEnabled(
            one is not None and one.lower() not in ("bylayer", "byblock",
                                                     "continuous"))
        self.pen_width.setEnabled(bool(one) and one.upper().startswith("ACAD_ISO"))

    def _context_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addAction(tr("Select all"), self.table.selectAll)
        menu.addAction(tr("Clear all"), self.table.clearSelection)
        menu.exec(self.table.viewport().mapToGlobal(pos))
        menu.deleteLater()

    # -- buttons ------------------------------------------------------------------
    def _load(self) -> None:
        names = run_load(self, self.document, self._execute)
        if names:
            self.filter.setCurrentIndex(0)
            self.invert.setChecked(False)
            self._fill()
            self.table.clearSelection()
            self.select(names[0])

    def _delete(self) -> None:
        names = self.selected_names()
        unused = {n.upper() for n in lt_ops.unused_names(self.document)}
        removable = [n for n in names if n.upper() in unused]
        refused = [n for n in names if n not in removable]
        if refused:
            self.warn(tr("The selected linetype(s) cannot be deleted: "
                         "BYLAYER, BYBLOCK, CONTINUOUS, the current linetype, "
                         "xref-dependent linetypes and linetypes in use."))
        if not removable:
            return
        from core.cleanup import PurgeCommand

        command = PurgeCommand({"ltypes": removable})
        command.name = "LINETYPE Delete"
        self._execute(command)
        for n in removable:
            self._renames.pop(n, None)
            self._descriptions.pop(n, None)
        self._fill()

    def warn(self, text: str) -> None:
        QMessageBox.warning(self, tr("Linetype Manager"), text)

    def _set_current(self) -> None:
        names = self.selected_names()
        if len(names) == 1:
            self._current = names[0]
            self.current_label.setText(
                tr("Current linetype: {name}", name=self._label(self._current)))

    def _toggle_details(self) -> None:
        """Show or hide Details. Like AutoCAD, the window grows by the
        section's height instead of squeezing the list to make room."""
        shown = self.details.isHidden()
        extra = self.details.sizeHint().height() + \
            self.layout().spacing()
        self.details.setVisible(shown)
        self.details_button.setText(tr("Hide details") if shown
                                    else tr("Show details"))
        self.resize(self.width(), max(self.minimumSizeHint().height(),
                                      self.height() + (extra if shown
                                                       else -extra)))

    # -- details ------------------------------------------------------------------
    def _commit_name(self) -> None:
        names = self.selected_names()
        if len(names) != 1:
            return
        original = names[0]
        new = self.name_edit.text().strip()
        if new == self._display(original):
            return
        others = {self._display(n).upper() for n in lt_ops.loaded_names(
            self.document) if n != original}
        reason = lt_ops.RenameLinetypeCommand.check(self.document, original, new)
        if reason is None and new.upper() in others:
            reason = "Linetype {name} already exists."
        if reason is not None:
            self.warn(tr(reason, name=new if "exists" in reason else original))
            self.name_edit.setText(self._display(original))
            return
        if new == original:
            self._renames.pop(original, None)
        else:
            self._renames[original] = new
        self._fill()

    def _commit_description(self) -> None:
        names = self.selected_names()
        if len(names) != 1:
            return
        name = names[0]
        text = self.description_edit.text()
        if text != _shown(self.document, name):
            self._descriptions[name] = text
        else:
            self._descriptions.pop(name, None)
        self._fill()

    def _object_scale_typed(self, _text: str) -> None:
        self._sync_pen_width()

    def _pen_width_picked(self, index: int) -> None:
        width = self.pen_width.itemData(index)
        self.object_scale.setText(f"{float(width):.4f}")

    def _sync_pen_width(self) -> None:
        try:
            value = float(self.object_scale.text().replace(",", "."))
        except ValueError:
            return
        found = self.pen_width.findData(round(value, 2))
        if found >= 0:
            self.pen_width.setCurrentIndex(found)

    @staticmethod
    def _number(text: str) -> float | None:
        try:
            value = float(text.replace(",", "."))
        except ValueError:
            return None
        return value if value > 0 else None

    def changes(self):
        """The commands OK will run, or None when a scale is not a positive
        number (the dialog then says so and stays open)."""
        from core.attributes import SetHeaderCommand

        header = self.document.doc.header
        global_scale = self._number(self.global_scale.text())
        object_scale = self._number(self.object_scale.text())
        if global_scale is None or object_scale is None:
            return None
        commands = []
        for original, new in self._renames.items():
            commands.append(lt_ops.RenameLinetypeCommand(original, new))
        for name, text in self._descriptions.items():
            commands.append(lt_ops.LinetypeDescriptionCommand(
                self._renames.get(name, name), text))
        current = self._renames.get(self._current, self._current)
        if current != str(header.get("$CELTYPE", "ByLayer")):
            commands.append(SetHeaderCommand("$CELTYPE", current, "CELTYPE"))
        if abs(global_scale - float(header.get("$LTSCALE", 1.0))) > 1e-12:
            commands.append(SetHeaderCommand("$LTSCALE", global_scale, "LTSCALE"))
        if abs(object_scale - float(header.get("$CELTSCALE", 1.0))) > 1e-12:
            commands.append(SetHeaderCommand("$CELTSCALE", object_scale,
                                             "CELTSCALE"))
        paper = 1 if self.paper_units.isChecked() else 0
        if paper != int(header.get("$PSLTSCALE", 1)):
            commands.append(SetHeaderCommand("$PSLTSCALE", paper, "PSLTSCALE"))
        return commands

    def _ok(self) -> None:
        self._commit_name()
        self._commit_description()
        commands = self.changes()
        if commands is None:
            self.warn(tr("Value must be positive."))
            return
        if commands:
            from core.commands import CompositeCommand

            self._execute(CompositeCommand("LINETYPE", commands))
        self.accept()
