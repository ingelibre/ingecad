# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""DRAWORDER (SORTENTSTABLE + canvas groups) and the layer express tools."""
from __future__ import annotations

import pytest

from core.commands import History
from core.document import Document
from core.draworder import DrawOrderCommand, order_groups


def _doc_with_two_solids():
    doc = Document.new()
    msp = doc.modelspace()
    doc.doc.layers.add("ROJA", color=1)
    doc.doc.layers.add("VERDE", color=3)
    s1 = msp.add_solid([(0, 0), (10, 0), (0, 10), (10, 10)],
                       dxfattribs={"layer": "ROJA"})
    s2 = msp.add_solid([(2, 2), (12, 2), (2, 12), (12, 12)],
                       dxfattribs={"layer": "VERDE"})
    return doc, s1, s2


def test_back_writes_a_sort_handle_below_every_natural_one():
    doc, s1, _s2 = _doc_with_two_solids()
    history = History(doc)
    history.execute(DrawOrderCommand([s1], "back"))
    assert order_groups(doc.modelspace()) == {s1.dxf.handle: -1}
    # and it is a REAL SORTENTSTABLE that survives the DXF round trip
    mapping = dict(doc.modelspace().get_redraw_order())
    assert int(mapping[s1.dxf.handle], 16) < int(s1.dxf.handle, 16)


def test_front_goes_above_and_undo_restores():
    doc, _s1, s2 = _doc_with_two_solids()
    history = History(doc)
    history.execute(DrawOrderCommand([s2], "front"))
    assert order_groups(doc.modelspace()) == {s2.dxf.handle: 1}
    history.undo()
    assert order_groups(doc.modelspace()) == {}


def test_the_canvas_honors_the_groups():
    """Back → its bucket packs first (draws under); front → packs last."""
    from render.backend import build_scene

    doc, s1, s2 = _doc_with_two_solids()
    history = History(doc)
    history.execute(DrawOrderCommand([s1], "back"))
    scene = build_scene(doc)
    start_of = {h: r[0][1] for h, r in scene.handle_ranges.items()}
    assert start_of[s1.dxf.handle] < start_of[s2.dxf.handle]
    history.undo()
    history.execute(DrawOrderCommand([s1], "front"))
    scene = build_scene(doc)
    start_of = {h: r[0][1] for h, r in scene.handle_ranges.items()}
    assert start_of[s1.dxf.handle] > start_of[s2.dxf.handle]


# -- layer tools ---------------------------------------------------------------

def _win(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document("mm")
    doc = win.document
    doc.doc.layers.add("MUROS", color=1)
    doc.doc.layers.add("COTAS", color=3)
    doc.doc.layers.add("EJES", color=5)
    return win


def test_layiso_offs_everything_else_and_layuniso_restores(qapp):
    win = _win(qapp)
    try:
        doc = win.document
        entity = doc.modelspace().add_line((0, 0), (1, 1),
                                           dxfattribs={"layer": "MUROS"})
        win.tools.start_tool("LAYISO")
        win.tools.tool.on_selection([entity])
        layers = doc.doc.layers
        assert layers.get("MUROS").is_on()
        assert not layers.get("COTAS").is_on()
        assert not layers.get("EJES").is_on()
        win._cmd_layuniso()
        assert layers.get("COTAS").is_on() and layers.get("EJES").is_on()
    finally:
        win.close()


def test_layoff_turns_off_the_picked_layer_with_undo(qapp):
    win = _win(qapp)
    try:
        doc = win.document
        doc.modelspace().add_line((0, 0), (5, 5), dxfattribs={"layer": "COTAS"})
        win.tools.start_tool("LAYOFF")
        win.tools.tool.on_point((2.5, 2.5))
        assert not doc.doc.layers.get("COTAS").is_on()
        win._cmd_undo()
        assert doc.doc.layers.get("COTAS").is_on()
    finally:
        win.close()


def test_layon_turns_every_layer_on_in_one_step(qapp):
    win = _win(qapp)
    try:
        doc = win.document
        doc.doc.layers.get("COTAS").off()
        doc.doc.layers.get("EJES").off()
        win._cmd_layon()
        assert doc.doc.layers.get("COTAS").is_on()
        assert doc.doc.layers.get("EJES").is_on()
        win._cmd_undo()
        assert not doc.doc.layers.get("COTAS").is_on()
    finally:
        win.close()
