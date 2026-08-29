# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Turning a layer off shows up at once, without rebuilding the scene.

Marco, on a plan of 88 000 entities: "quiero apagar una capa, aprieto el
foquito, demora una eternidad; en AutoCAD es instantaneo". Half of that was
the panel (see test_layers_panel_columns.py); the other half was this: the
drawing only agreed with the click after a full regen, 7.7 s later.

The geometry is already on the GPU, so the answer is the surgical display
the eraser has used since v0.1.3 -- zero the alpha of that layer's vertices.
What it cannot reach is geometry drawn through an INSERT, which belongs to
the INSERT's handle, so a layer that also lives inside a block still asks
for the rebuild.
"""
from __future__ import annotations

import ezdxf
import pytest

from core import layers as layer_ops


def _doc_with_a_block_layer():
    doc = ezdxf.new("R2018", setup=True)
    doc.layers.add("SUELTA")
    doc.layers.add("DENTRO-DE-BLOQUE")
    block = doc.blocks.new("PIEZA")
    block.add_line((0, 0), (1, 1), dxfattribs={"layer": "DENTRO-DE-BLOQUE"})
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "SUELTA"})
    msp.add_blockref("PIEZA", (5, 5))
    return doc


def test_a_layer_inside_a_block_is_known_to_need_the_rebuild():
    from core.document import Document

    document = Document(_doc_with_a_block_layer())
    inside = layer_ops.layers_inside_blocks(document)
    assert "DENTRO-DE-BLOQUE" in inside
    assert "SUELTA" not in inside, (
        "a layer used only in the modelspace does not need the rebuild")
    # the layout's own blocks are not block content
    assert not any(n.lower().startswith("*") for n in inside)


def test_the_scan_is_cached_until_the_drawing_changes():
    from core.document import Document

    document = Document(_doc_with_a_block_layer())
    first = layer_ops.layers_inside_blocks(document)
    assert layer_ops.layers_inside_blocks(document) is first
    document.doc.blocks.get("PIEZA").add_line(
        (0, 0), (2, 2), dxfattribs={"layer": "NUEVA"})
    document.revision += 1                      # as any edit does
    assert "NUEVA" in layer_ops.layers_inside_blocks(document)


# -- through the window --------------------------------------------------------

def _window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.resize(900, 700)
    win.show()
    win.new_document()
    doc = win.document.doc
    doc.layers.add("SUELTA")
    doc.layers.add("DENTRO-DE-BLOQUE")
    block = doc.blocks.new("PIEZA")
    block.add_line((0, 0), (1, 1), dxfattribs={"layer": "DENTRO-DE-BLOQUE"})
    msp = doc.modelspace()
    for i in range(20):
        msp.add_line((0, i), (10, i), dxfattribs={"layer": "SUELTA"})
    msp.add_blockref("PIEZA", (5, 5))
    win.regen_in_memory()
    deadline = 0
    while win._regen_worker is not None and deadline < 2000:
        qapp.processEvents()
        deadline += 1
    qapp.processEvents()
    return win


def _hidden_vertices(win) -> int:
    scene = win.viewport._scene
    if scene is None:
        return 0
    return int(sum(int((getattr(scene, b).data["rgba"][:, 3] == 0).sum())
                   for b in ("triangles", "lines", "points")))


def test_hiding_a_plain_layer_needs_no_regen_and_is_visible_at_once(qapp):
    win = _window(qapp)
    try:
        assert win.viewport._scene is not None, "no scene to hide in"
        before = _hidden_vertices(win)
        assert win.apply_layer_visibility("SUELTA", False) is True, (
            "a layer that lives only in the modelspace asked for a regen")
        after = _hidden_vertices(win)
        assert after > before, "nothing was hidden"

        # and back on, exactly
        assert win.apply_layer_visibility("SUELTA", True) is True
        assert _hidden_vertices(win) == before
    finally:
        win.close()


def test_a_layer_inside_a_block_still_asks_for_the_regen(qapp):
    win = _window(qapp)
    try:
        # It is hidden surgically all the same -- the INSERT's own copy is
        # what the rebuild is for -- but the answer is "regenerate too".
        assert win.apply_layer_visibility("DENTRO-DE-BLOQUE", False) is False
    finally:
        win.close()


def test_turning_a_layer_back_on_after_a_rebuild_asks_for_the_regen(qapp):
    """The scene no longer carries the vertices: only a regen can bring
    them back, and saying True there would leave the drawing wrong."""
    win = _window(qapp)
    try:
        assert win.apply_layer_visibility("SUELTA", False) is True
        win.viewport._hidden_rgba.clear()      # what a rebuild leaves behind
        assert win.apply_layer_visibility("SUELTA", True) is False
    finally:
        win.close()


def test_changing_a_layers_look_redraws_that_layer_only(qapp):
    """Colour, linetype and lineweight change how the layer LOOKS: its own
    entities are re-tessellated and swapped in, the drawing is not."""
    win = _window(qapp)
    try:
        drawn = win._drawn_entities_of_layer("SUELTA")
        assert drawn, "nothing of the layer is on screen to redraw"
        assert win.apply_layer_appearance("SUELTA") is True
        queued = {e.dxf.handle for e in win.tools._pending_render}
        assert {e.dxf.handle for e in drawn} <= queued, (
            "the layer's entities were not queued for the overlay")

        # inside a block it cannot be done surgically: that geometry belongs
        # to the INSERT's handle
        assert win.apply_layer_appearance("DENTRO-DE-BLOQUE") is False
    finally:
        win.close()


def test_the_panel_only_regenerates_when_it_has_to(qapp):
    """The wiring, end to end: the bulb and a colour take the fast paths,
    a new layer -- which changes what the drawing contains -- does not."""
    win = _window(qapp)
    try:
        panel = win._layers_panel
        panel.refresh()
        qapp.processEvents()
        row = next(r for r in range(panel.table.rowCount())
                   if panel._row_layer(r) == "SUELTA")
        calls = []
        win.regen_in_memory = lambda *a, **k: calls.append("regen")

        panel._on_cell_clicked(row, 2)          # the bulb
        assert not calls, "turning a layer off still regenerated"
        assert win.document.doc.layers.get("SUELTA").is_on() is False

        panel._on_cell_clicked(row, 2)          # and on again
        panel._execute(layer_ops.LayerPropertyCommand("SUELTA", "color", 3),
                       appearance="SUELTA")
        assert not calls, "a colour change rebuilt the whole drawing"
        assert abs(win.document.doc.layers.get("SUELTA").dxf.color) == 3

        panel._execute(layer_ops.NewLayerCommand("OTRA"))
        assert calls == ["regen"], "a new layer must reach the scene"
    finally:
        win.close()
