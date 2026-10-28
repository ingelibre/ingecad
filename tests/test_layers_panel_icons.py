# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Layers panel's states are painted icons, not font glyphs (#100).

On Ubuntu without a desktop the on/off, freeze and lock columns were empty
boxes: they were emoji, and the fonts that carry them come with a desktop.
The click read the state back from that very glyph. Now each cell holds a
painted icon and keeps its state as data.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def panel(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    doc = win.document.doc
    doc.layers.add("EJES")
    if win._layers_panel is None:
        win.toggle_layers_panel()
    panel = win._layers_panel
    panel.refresh()
    yield panel
    win.document.dirty = False
    win.close()


def test_no_state_is_a_glyph_and_each_pair_differs(panel):
    row = panel._rows.index("EJES")
    for col in (2, 3, 4, 8):
        item = panel.table.item(row, col)
        assert item.text() == "", col
        assert not item.icon().isNull(), col
    for col in (2, 3, 4, 8):
        header = panel.table.horizontalHeaderItem(col)
        assert header.text() == "" and not header.icon().isNull(), col
    from views.icons import layer_state_icon

    for kind in ("on", "thaw", "lock", "plot"):
        a = layer_state_icon(kind, True).pixmap(24, 24).toImage()
        b = layer_state_icon(kind, False).pixmap(24, 24).toImage()
        assert a != b, kind


def test_clicks_toggle_by_the_kept_state(panel):
    doc = panel.document.doc
    layer = doc.layers.get("EJES")
    for col, is_set in ((2, lambda: not layer.is_on()),
                        (3, layer.is_frozen),
                        (4, layer.is_locked)):
        row = panel._rows.index("EJES")
        panel.table.cellClicked.emit(row, col)
        assert is_set(), col
        row = panel._rows.index("EJES")
        panel.table.cellClicked.emit(row, col)
        assert not is_set(), col
