# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Object snaps reach the geometry inside a block insert, as in AutoCAD.

Only the insertion point snapped: a door's jamb, a column's corner, a
title block's frame were out of reach. GeoCad Yaguarete (Fernando
Bellocchio's plugin) had to patch it in. Every hit belongs to the INSERT,
the object the drawing can select.
"""
from __future__ import annotations

import math

import ezdxf
import pytest

from core import actions
from core.commands import History
from core.document import Document
from core.snap import SnapEngine


def _drawing():
    doc = ezdxf.new("R2018")
    block = doc.blocks.new("PIEZA", base_point=(1, 1))
    block.add_line((1, 1), (11, 1))                     # 10 long from base
    block.add_circle((6, 4), 2)
    block.add_arc((1, 1), 3, 0, 90)                     # (4,1) .. (1,4)
    inner = doc.blocks.new("TORNILLO")
    inner.add_circle((0, 0), 0.5)
    block.add_blockref("TORNILLO", (11, 6))
    return Document(doc), doc.modelspace()


def _find(engine, x, y, kind):
    hit = engine.find((x, y), 0.3, kinds=frozenset({kind}))
    return None if hit is None else (round(hit.x, 6), round(hit.y, 6))


def test_endpoints_centres_and_nested_blocks_of_an_insert():
    document, msp = _drawing()
    msp.add_blockref("PIEZA", (100, 50),
                           dxfattribs={"rotation": 90, "xscale": 2, "yscale": 2})
    engine = SnapEngine(document)
    # the line (1,1)-(11,1) from the base: x2, turned 90 -> (100,50)-(100,70)
    assert _find(engine, 100.1, 69.9, "END") == (100, 70)
    # the circle centre (6,4): offset (5,3) x2 turned -> (-6, 10)
    assert _find(engine, 94.1, 60.1, "CEN") == (94, 60)
    # the nested bolt (11,6): offset (10,5) x2 turned -> (-10, 20)
    assert _find(engine, 90.1, 70.1, "CEN") == (90, 70)
    # its own insertion point still snaps
    assert _find(engine, 100.1, 50.1, "INS") == (100, 50)


def test_a_mirrored_insert_keeps_its_arcs():
    document, msp = _drawing()
    msp.add_blockref("PIEZA", (0, 0), dxfattribs={"xscale": -1})
    engine = SnapEngine(document)
    # the arc (1,1) r3 0..90 mirrored in x: from (-3,0) to (0,3) around (0,0)
    assert _find(engine, -3.1, 0.1, "END") == (-3, 0)
    assert _find(engine, 0.1, 3.1, "END") == (0, 3)
    mid = engine.find((-2.2, 2.2), 0.4, kinds=frozenset({"MID"}))
    s = 3 / math.sqrt(2)
    assert mid is not None and (mid.x, mid.y) == pytest.approx((-s, s))


def test_a_stretched_insert_still_snaps_through_its_copies():
    document, msp = _drawing()
    msp.add_blockref("PIEZA", (0, 0), dxfattribs={"xscale": 2, "yscale": 1})
    engine = SnapEngine(document)
    assert _find(engine, 20.1, 0.1, "END") == (20, 0)


def test_a_redefined_block_snaps_with_its_new_geometry():
    document, msp = _drawing()
    msp.add_blockref("PIEZA", (0, 0))
    engine = SnapEngine(document)
    assert _find(engine, 10.1, 0.1, "END") == (10, 0)
    history = History(document)
    source = ezdxf.new("R2018")
    source.modelspace().add_line((0, 0), (0, 30))
    history.execute(actions.RedefineBlockFromFileCommand(
        "PIEZA", Document(source)))
    engine.invalidate()
    assert _find(engine, 10.1, 0.1, "END") is None, "old definition cached"
    # the new definition: base (0,0) now -> line (0,0)-(0,30) at the insert
    assert _find(engine, 0.1, 29.9, "END") == (0, 30)
    history.undo()
    engine.invalidate()
    assert _find(engine, 10.1, 0.1, "END") == (10, 0)


def test_the_drawing_snaps_inside_a_block_from_the_canvas(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        win.new_document()
        t = win.tools
        win.document.doc.blocks.new("MARCO").add_line((0, 0), (40, 0))
        t._execute(actions.insert_block("MARCO", (10, 10)))
        t.osnap_on = True
        t.osnap_modes = {"END"}
        win.dispatcher.submit("LINE")
        t.on_hover(49.9, 10.1, threshold_world=0.5)
        assert t.snap_hit is not None and t.snap_hit.kind == "END"
        assert (t.snap_hit.x, t.snap_hit.y) == pytest.approx((50.0, 10.0))
        t.cancel()
    finally:
        win.document.dirty = False
        win.close()
