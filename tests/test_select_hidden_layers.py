# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A click, a window or a crossing only take what is on screen (#97).

A user: "when deleting objects in model space, objects with their layers
turned off might also get deleted". The pick index holds every entity, and
a window over a layer turned off -- or frozen -- took its objects; Delete
then erased what nobody could see. AutoCAD selects only visible objects
that way. The typed ALL is different and stays so: "all objects ... except
those objects on frozen or on locked layers" (SELECT), so a layer that is
merely off is in.
"""
from __future__ import annotations

import pytest

from core import actions


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    window = MainWindow()
    window.resize(1000, 700)
    window.show()
    window.new_document()
    doc = window.document.doc
    for name in ("APAGADA", "CONGELADA"):
        doc.layers.add(name)
    for i, layer in enumerate(("0", "APAGADA", "CONGELADA")):
        window.tools._execute(actions.add_line((0, i * 10), (50, i * 10)))
        doc.modelspace().query("LINE")[-1].dxf.layer = layer
    for line in ("-LAYER", "OFF", "APAGADA", "FREEZE", "CONGELADA", ""):
        window._on_command_submitted(line)
    window.viewport.view.zoom_extents(-10, -10, 60, 30)
    qapp.processEvents()
    yield window
    window.document.dirty = False
    window.close()


def _layers(win, handles):
    db = win.document.doc.entitydb
    return sorted(db[h].dxf.layer for h in handles)


def test_a_window_and_a_crossing_leave_hidden_layers_out(win):
    t = win.tools
    t.on_click(-5, -5)
    t.on_click(55, 25)                      # left to right: window
    assert _layers(win, t.selection) == ["0"]
    t.selection = set()
    t.on_click(55, 25)
    t.on_click(-5, -5)                      # right to left: crossing
    assert _layers(win, t.selection) == ["0"]
    # Delete then erases only what was seen
    win._on_command_submitted("ERASE")
    assert sorted(e.dxf.layer for e in win.document.modelspace()) == [
        "APAGADA", "CONGELADA"]


def test_a_click_on_a_hidden_line_takes_nothing(win):
    t = win.tools
    t.on_click(25, 10)
    t.reset_pick_cycle()
    t.on_click(25, 20)
    assert t.selection == set()


def test_a_crossing_inside_erase_leaves_them_too_and_all_still_takes_off(win):
    win._on_command_submitted("ERASE")
    t = win.tools
    t.on_click(55, 25)
    t.on_click(-5, -5)
    win._on_command_submitted("")
    assert sorted(e.dxf.layer for e in win.document.modelspace()) == [
        "APAGADA", "CONGELADA"]
    win._cmd_undo()
    win._on_command_submitted("ERASE")
    win._on_command_submitted("ALL")
    win._on_command_submitted("")
    assert [e.dxf.layer for e in win.document.modelspace()] == ["CONGELADA"]
