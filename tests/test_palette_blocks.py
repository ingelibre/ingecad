# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Palette's fourth category: the drawing's blocks, ready to insert."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    window = MainWindow()
    window.maybe_save_changes = lambda: True
    window.new_document()
    window.show()
    qapp.processEvents()
    yield window
    window.document.dirty = False
    window.close()


def _define(win, name, radius=5.0):
    """A definition added to the drawing, and the signal every command ends with."""
    block = win.document.doc.blocks.new(name)
    block.add_circle((0, 0), radius)
    block.add_line((-radius, 0), (radius, 0))
    win.tools.changed.emit()


def _names(panel):
    return [panel.list.item(i).data(Qt.UserRole)
            for i in range(panel.list.count())]


def _open_blocks(win, qapp):
    win.toggle_styles_panel()
    panel = win._styles_panel
    panel._cat_btns["BLOCK"].click()
    qapp.processEvents()
    return panel


def _ink(icon, size):
    """Dark pixels of a thumbnail: what was drawn on its light tile."""
    image = icon.pixmap(size).toImage()
    return sum(1 for x in range(image.width()) for y in range(image.height())
               if QColor(image.pixel(x, y)).lightness() < 128)


def test_the_blocks_of_the_drawing_are_listed_with_a_thumbnail(win, qapp):
    _define(win, "DOOR")
    _define(win, "WINDOW")
    panel = _open_blocks(win, qapp)
    assert _names(panel) == ["DOOR", "WINDOW"]
    panel._draw_thumbs(everything=True)
    size = panel.list.iconSize()
    assert _ink(panel.list.item(0).icon(), size) > 50, "an empty thumbnail"


def test_a_block_defined_later_shows_up_without_asking(win, qapp):
    panel = _open_blocks(win, qapp)
    assert _names(panel) == []
    _define(win, "LATE")
    qapp.processEvents()
    assert _names(panel) == ["LATE"]


def test_double_click_inserts_that_block_without_the_dialog(win, qapp):
    _define(win, "DOOR")
    _define(win, "WINDOW")
    panel = _open_blocks(win, qapp)
    asked = []
    win.tools._ask_choice = lambda *a, **k: asked.append(a) or None
    item = panel.list.item(_names(panel).index("WINDOW"))
    panel.list.itemDoubleClicked.emit(item)
    qapp.processEvents()
    assert not asked, "INSERT asked which block"
    assert win.tools.tool is not None and win.tools.tool.name == "INSERT"
    win.tools.tool.on_point((10.0, 20.0))
    inserts = [e for e in win.document.modelspace()
               if e.dxftype() == "INSERT"]
    assert [e.dxf.name for e in inserts] == ["WINDOW"]
    assert tuple(inserts[0].dxf.insert)[:2] == (10.0, 20.0)


def test_a_typed_insert_after_the_palette_asks_again(win, qapp):
    """The palette's pick is spent by the INSERT it started."""
    from tools.blocks import InsertTool

    _define(win, "DOOR")
    panel = _open_blocks(win, qapp)
    win.tools._ask_choice = lambda *a, **k: None   # a modal hangs offscreen
    panel.list.itemDoubleClicked.emit(panel.list.item(0))
    win.tools.cancel()
    assert InsertTool._preset_name is None
