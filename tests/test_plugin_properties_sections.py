# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A plugin adds its own sections to the Properties panel
(properties_sections and core.plugins.Row; level 2).

A third-party plugin replaced the panel's schema to add a section of its
own data and rows that apply object by object (an operation such as
``*2`` on each object's own height), and wrote the rows one object at a
time through the panel's internals.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QLineEdit, QTreeWidgetItemIterator

from core import actions
from core.plugins import LoadedPlugin, PluginSpec, Row

PLUGIN = "ejemplo_propiedades"


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w.new_document()
    yield w
    w.plugins.deactivate(PLUGIN)
    w.plugins.loaded.pop(PLUGIN, None)
    w.document.dirty = False
    w.close()


def _times(entity, text):
    """``*2`` multiplies the object's own radius; a number sets it."""
    text = text.replace(",", ".").strip()
    radius = entity.dxf.radius
    entity.dxf.radius = (radius * float(text[1:]) if text.startswith("*")
                         else float(text))


def _sections(ctx, entities):
    if {e.dxftype() for e in entities} != {"CIRCLE"}:
        return []
    return [("Survey", [Row("Radius by", "str", lambda e: e.dxf.radius,
                            apply_each=_times)])]


def _activate(win, hook):
    spec = PluginSpec(id=PLUGIN, name="Props", properties_sections=hook)
    win.plugins.loaded[spec.id] = LoadedPlugin(spec.id, Path("."), False,
                                               spec=spec)
    assert win.plugins.activate(spec.id)


def _two_circles(win):
    win.tools._execute(actions.add_circle((0, 0), 2))
    win.tools._execute(actions.add_circle((10, 0), 3))
    circles = list(win.document.modelspace().query("CIRCLE"))
    win.tools.select_entities(circles)
    return circles


def _panel(win):
    win.toggle_properties_panel()
    panel = win._properties_panel
    panel.refresh()
    return panel


def _items(panel):
    found = {}
    it = QTreeWidgetItemIterator(panel.tree)
    while it.value():
        found[it.value().text(0)] = it.value()
        it += 1
    return found


def test_the_section_shows_and_applies_object_by_object(win):
    _activate(win, _sections)
    first, second = _two_circles(win)
    panel = _panel(win)
    items = _items(panel)
    assert "Survey" in items
    editor = panel.tree.itemWidget(items["Radius by"], 1)
    assert isinstance(editor, QLineEdit)
    assert editor.text() == ""                # 2 and 3: *varies*
    editor.setText("*2")
    editor.editingFinished.emit()
    assert (first.dxf.radius, second.dxf.radius) == (4, 6)
    win._on_command_submitted("U")
    assert (first.dxf.radius, second.dxf.radius) == (2, 3)


def test_deactivated_its_section_is_gone(win):
    _activate(win, _sections)
    _two_circles(win)
    win.plugins.deactivate(PLUGIN)
    assert "Survey" not in _items(_panel(win))


def test_a_broken_section_leaves_the_panel_whole(win):
    def broken(ctx, entities):
        raise RuntimeError("boom")

    _activate(win, broken)
    _two_circles(win)
    items = _items(_panel(win))
    assert "Survey" not in items and len(items) > 3
    assert "Props: RuntimeError: boom" in \
        win.command_line.history.toPlainText()
