# SPDX-License-Identifier: GPL-3.0-or-later
"""End-to-end: after an erase, is the geometry actually gone from the buffers?"""
import time

import ezdxf
import numpy as np

BATCHES = ("lines", "thick", "triangles", "points")


def _wait_regen(qapp, win, timeout_s=20.0):
    t0 = time.monotonic()
    while (win._regen_worker is not None or win.viewport._scene is None) \
            and time.monotonic() - t0 < timeout_s:
        qapp.processEvents()
    assert win.viewport._scene is not None, "regen never landed"


def _visible_alpha(viewport):
    """Total alpha still non-zero across every scene batch."""
    scene = viewport._scene
    return sum(int((getattr(scene, b).data["rgba"][:, 3] != 0).sum())
               for b in BATCHES if getattr(scene, b).vertex_count)


def test_erase_hides_blocks_thick_lines_and_hatches(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    doc = win.document.doc

    # The three things that were unhideable: block content, thick strokes and
    # hatch fills inside a block.
    blk = doc.blocks.new("MUEBLE")
    for i in range(8):
        blk.add_line((float(i), 0.0), (float(i), 4.0))
    h = blk.add_hatch(color=2)
    h.paths.add_polyline_path([(0, 0), (8, 0), (8, 4), (0, 4)], is_closed=True)

    msp = win.document.modelspace()
    msp.add_blockref("MUEBLE", (0.0, 0.0))
    msp.add_line((0.0, 10.0), (20.0, 10.0), dxfattribs={"lineweight": 50})
    msp.add_line((0.0, 12.0), (20.0, 12.0), dxfattribs={"lineweight": 13})

    # Prime both caches: they build lazily on the first query.
    win.tools.snap_engine.find((0.0, 0.0), 1.0)
    win.tools.index.pick((0.0, 0.0), 1.0)

    win.regen_in_memory()
    _wait_regen(qapp, win)
    before = _visible_alpha(win.viewport)
    assert before > 0

    t = win.tools
    t.selection = set(t.index.crossing((-5.0, -5.0, 30.0, 20.0)))
    assert len(t.selection) == 3, f"expected the 3 modelspace entities, got {t.selection}"
    assert t.delete_selection()

    # Model side: nothing left in modelspace.
    assert len(list(win.document.modelspace())) == 0
    # Display side: no visible vertex may survive the erase.
    after = _visible_alpha(win.viewport)
    assert after == 0, f"{after} of {before} vertices still visible after ERASE"
    win.close()


def test_cut_leaves_nothing_of_the_original(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    doc = win.document.doc
    blk = doc.blocks.new("BLK")
    for i in range(6):
        blk.add_line((float(i), 0.0), (float(i), 3.0))
    msp = win.document.modelspace()
    msp.add_blockref("BLK", (0.0, 0.0))
    msp.add_line((0.0, 8.0), (10.0, 8.0), dxfattribs={"lineweight": 70})

    # Prime both caches: they build lazily on the first query.
    win.tools.snap_engine.find((0.0, 0.0), 1.0)
    win.tools.index.pick((0.0, 0.0), 1.0)

    win.regen_in_memory()
    _wait_regen(qapp, win)
    assert _visible_alpha(win.viewport) > 0

    t = win.tools
    t.selection = set(t.index.crossing((-2.0, -2.0, 15.0, 12.0)))
    assert t.copy_selection(cut=True)
    assert _visible_alpha(win.viewport) == 0, "the cut original is still on screen"
    win.close()
