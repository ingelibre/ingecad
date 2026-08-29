# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Layers panel's columns: readable, and cheap to keep readable.

Two bugs live here, and they pull in opposite directions:

* the column widths were constants smaller than their own content, so
  Color, Linetype and Lineweight were cut at EVERY width of the panel and
  widening the sidebar never revealed them;
* the obvious cure -- QHeaderView.ResizeToContents -- re-measures the whole
  column on every ``setItem`` while the table fills, which is O(rows^2):
  measured on a real plan of 82 layers, one click on a layer's bulb froze
  the UI for 16 s against 103 ms before.

So the widths are computed once per refresh, and both facts are asserted.
"""
from __future__ import annotations

import time

import ezdxf
import pytest
from PySide6.QtWidgets import QHeaderView

from core.document import Document

VALUE_COLUMNS = (0, 2, 3, 4, 5, 6, 7, 8)


def _document(layers: int = 60) -> Document:
    doc = ezdxf.new("R2018", setup=True)
    msp = doc.modelspace()
    for i in range(layers):
        name = f"CAPA-CON-NOMBRE-LARGO-{i:03d}"
        layer = doc.layers.add(name)
        layer.dxf.linetype = "DASHED" if i % 2 else "Continuous"
        layer.dxf.lineweight = 35 if i % 3 else 13
        layer.description = f"descripcion larga de la capa numero {i}"
        msp.add_line((0, i), (10, i), dxfattribs={"layer": name})
    return Document(doc)


def _panel(qapp, document):
    from PySide6.QtWidgets import QWidget

    from views.layers_panel import LayersPanel

    window = QWidget()          # stands in for the MainWindow: the panel
    window.document = document  # only reads the document to fill the table
    panel = LayersPanel(window)
    # Shown and sized: an unshown table skips the layout work that made the
    # regression cost 13 s, so an offscreen panel would measure the wrong
    # case entirely.
    panel.resize(320, 700)
    panel.show()
    panel.refresh()
    qapp.processEvents()
    return panel


def test_every_value_column_shows_its_content(qapp):
    """The original complaint: 'algunas columnas no se ven bien'."""
    panel = _panel(qapp, _document())
    header = panel.table.horizontalHeader()
    for col in VALUE_COLUMNS:
        need = max(panel.table.sizeHintForColumn(col),
                   header.sectionSizeHint(col))
        assert header.sectionSize(col) >= need, (
            f"column {col} shows {header.sectionSize(col)} px of {need}")


def test_no_column_is_left_in_resize_to_contents(qapp):
    """The mode is the trap: Qt re-measures the column on every setItem.

    Asserted structurally because the cost only shows on a real plan, and a
    stopwatch in a test is a flake waiting to happen.
    """
    panel = _panel(qapp, _document())
    header = panel.table.horizontalHeader()
    for col in range(panel.table.columnCount()):
        assert header.sectionResizeMode(col) != QHeaderView.ResizeToContents, (
            f"column {col} is back on ResizeToContents")


def test_a_refresh_of_a_long_layer_list_stays_cheap(qapp):
    """The cost only exists inside the real window.

    A bare panel refreshes a 200-layer list in well under a second in EITHER
    mode -- measured -- because an orphan table skips the layout pass that
    the dock, the toolbars and the GL viewport make expensive. In a
    MainWindow the same list takes 107 ms one way and 79 SECONDS the other,
    so this is the only harness that can catch the regression.
    """
    from views.main_window import MainWindow

    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    try:
        win.new_document()
        doc = win.document.doc
        msp = doc.modelspace()
        for i in range(150):
            name = f"CAPA-CON-NOMBRE-LARGO-{i:03d}"
            doc.layers.add(name).description = f"descripcion de la capa {i}"
            msp.add_line((0, i), (10, i), dxfattribs={"layer": name})
        panel = win._layers_panel
        panel.refresh()
        qapp.processEvents()

        t0 = time.perf_counter()
        panel.refresh()
        qapp.processEvents()
        elapsed = (time.perf_counter() - t0) * 1000
        assert elapsed < 3000, (
            f"refreshing 150 layers took {elapsed:.0f} ms -- the O(rows^2) "
            f"column sizing is back")
    finally:
        win.close()


def test_a_width_the_user_chose_survives_the_next_refresh(qapp):
    """Content sizing must not undo a column the user dragged."""
    panel = _panel(qapp, _document())
    panel.table.setColumnWidth(6, 200)          # as a drag would
    panel._remember_name_width_change(6, 99, 200)
    panel.refresh()
    qapp.processEvents()
    assert panel.table.columnWidth(6) == 200

    # ... and a column the user never touched still follows its content
    panel.table.setColumnWidth(7, 5)
    panel.refresh()
    qapp.processEvents()
    assert panel.table.columnWidth(7) > 5


def test_columns_can_be_hidden_from_the_header_menu(qapp):
    """AutoCAD's way out of a narrow palette; the choice is remembered."""
    panel = _panel(qapp, _document())
    panel._toggle_column(9, False)
    assert panel.table.isColumnHidden(9)
    panel._restore_hidden_columns()
    assert panel.table.isColumnHidden(9), "the hidden column was not stored"
    panel._toggle_column(9, True)
    assert not panel.table.isColumnHidden(9)
    assert 1 not in panel.HIDEABLE, "Name must not be hideable"
