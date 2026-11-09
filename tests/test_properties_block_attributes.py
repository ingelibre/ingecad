# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Properties panel lists a block reference's attributes, values
editable, as classic CAD's does.

A third-party plugin added the section itself: selecting a title block
showed its name, position and scale but not one of its attribute values.
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QLineEdit, QTreeWidgetItemIterator

from core import attributes as att
from core.i18n import tr


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w.new_document()
    doc = w.document.doc
    block = doc.blocks.new("ROTULO")
    block.add_attdef("PLANO", (0, 0), "A-01", dxfattribs={"height": 2.5})
    block.add_attdef("FECHA", (0, -5), "2026", dxfattribs={"height": 2.5})
    for x, plano in ((0, "A-01"), (100, "A-02")):
        w.tools._execute(att.insert_block_with_attribs(
            "ROTULO", (x, 0), values={"PLANO": plano}))
    yield w
    w.document.dirty = False
    w.close()


def _panel(win, inserts):
    win.tools.select_entities(inserts)
    win.toggle_properties_panel()
    panel = win._properties_panel
    panel.refresh()
    found = {}
    it = QTreeWidgetItemIterator(panel.tree)
    while it.value():
        found[it.value().text(0)] = it.value()
        it += 1
    return panel, found


def _value(insert, tag):
    return next(a.dxf.text for a in insert.attribs if a.dxf.tag == tag)


def test_one_reference_shows_and_edits_its_values(win):
    first, _second = win.document.modelspace().query("INSERT")
    panel, items = _panel(win, [first])
    assert tr("Attributes") in items
    editor = panel.tree.itemWidget(items["PLANO"], 1)
    assert isinstance(editor, QLineEdit) and editor.text() == "A-01"
    assert panel.tree.itemWidget(items["FECHA"], 1).text() == "2026"
    editor.setText("A-07")
    editor.editingFinished.emit()
    assert _value(first, "PLANO") == "A-07"
    win._on_command_submitted("U")
    assert _value(first, "PLANO") == "A-01"


def test_several_references_vary_and_take_one_value(win):
    inserts = list(win.document.modelspace().query("INSERT"))
    panel, items = _panel(win, inserts)
    plano = panel.tree.itemWidget(items["PLANO"], 1)
    assert plano.text() == ""                          # A-01 / A-02: varies
    fecha = panel.tree.itemWidget(items["FECHA"], 1)
    assert fecha.text() == "2026"
    fecha.setText("2027")
    fecha.editingFinished.emit()
    assert [_value(i, "FECHA") for i in inserts] == ["2027", "2027"]
