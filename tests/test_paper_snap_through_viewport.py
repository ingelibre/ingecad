# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Snapping from the sheet to what a viewport shows, and measuring it.

A tester: "sin snap al acotar en espacio papel". On the sheet the snap
engine only knew the sheet's own entities (the title block), so a
dimension drawn over a viewport engaged nothing of the plan. AutoCAD snaps
through the window, and its paper-space dimension of model geometry reads
the MODEL's length -- which is the second half, and the one that makes the
first worth anything: a snapped dimension reading 20 mm for a 100-unit
wall is worse than no snap.

Both halves here: the cursor over a viewport snaps to the model geometry
it shows (the hit comes back on paper, marked with the viewport it went
through), and a dimension whose definition points all came through the
same viewport carries DIMLFAC = 1/scale, so it reads the model.
"""
from __future__ import annotations

import time

import pytest

from core import layouts as layout_ops


def _wait_regen(qapp, win, timeout_s=20.0):
    t0 = time.monotonic()
    while win._regen_worker is not None and time.monotonic() - t0 < timeout_s:
        qapp.processEvents()


def _window(qapp):
    """A sheet with a title block text, a viewport at 1:5 showing a model
    line from (5000, 3000) to (5100, 3000) -- paper (150, 100) to
    (170, 100) -- and PSPACE current."""
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    msp = win.document.doc.modelspace()
    msp.add_line((5000, 3000), (5100, 3000))
    psp = win.document.doc.layouts.get("Layout1")
    psp.add_text("PLANO", dxfattribs={"height": 5, "insert": (620, 40)})
    psp.add_line((600, 60), (700, 60))
    vp = psp.add_viewport(center=(150, 100), size=(200, 120),
                          view_center_point=(5000, 3000), view_height=600)
    win._refresh_layout_tabs()
    win.switch_layout("Layout1")
    _wait_regen(qapp, win)
    assert win._active_vp is None, "PSPACE"
    t = win.tools
    t.osnap_on = True
    return win, t, vp


def _dim_text(document, dim) -> str:
    block = document.doc.blocks.get(dim.dxf.geometry)
    for e in block:
        if e.dxftype() in ("MTEXT", "TEXT"):
            return e.text if e.dxftype() == "MTEXT" else e.dxf.text
    return ""


def test_the_cursor_over_a_viewport_snaps_to_the_model_it_shows(qapp):
    win, t, vp = _window(qapp)
    try:
        t.start_tool("LINE")
        t.on_hover(150.4, 100.3, threshold_world=2.0)
        hit = t.snap_hit
        assert hit is not None, "nothing snapped through the window"
        assert (hit.x, hit.y) == pytest.approx((150.0, 100.0))
        assert hit.kind == "END"
        assert hit.via == vp.dxf.handle
        # the midpoint of the model line, 10 paper mm along
        t.on_hover(160.2, 100.1, threshold_world=2.0)
        assert t.snap_hit is not None and t.snap_hit.kind == "MID"
        assert (t.snap_hit.x, t.snap_hit.y) == pytest.approx((160.0, 100.0))
    finally:
        win.close()


def test_the_sheets_own_entities_still_snap_and_win_when_nearer(qapp):
    win, t, vp = _window(qapp)
    try:
        t.start_tool("LINE")
        t.on_hover(600.3, 60.2, threshold_world=2.0)      # the sheet's line
        assert t.snap_hit is not None
        assert (t.snap_hit.x, t.snap_hit.y) == pytest.approx((600.0, 60.0))
        assert t.snap_hit.via is None, "the sheet's own point"
    finally:
        win.close()


def test_outside_every_viewport_nothing_comes_through(qapp):
    win, t, vp = _window(qapp)
    try:
        t.start_tool("LINE")
        # paper (400, 100) would project to model (6250, 3000): no geometry
        # there anyway, but the point is outside the frame, so the model is
        # not even asked
        t._model_snap_engine = None
        t.on_hover(400.0, 100.0, threshold_world=2.0)
        assert t.snap_hit is None
        assert t._model_snap_engine is None, "the model was not consulted"
    finally:
        win.close()


def test_a_dimension_snapped_through_one_viewport_reads_the_model(qapp):
    """The wall is 100 model units and 20 mm on the sheet: the dimension
    on the sheet must say 100."""
    from core.snap import SnapHit

    win, t, vp = _window(qapp)
    try:
        t.start_tool("DIMLINEAR")
        t.on_hover(150.3, 100.2, threshold_world=2.0)
        assert t.snap_hit is not None and t.snap_hit.via == vp.dxf.handle
        t.on_click(150.3, 100.2)
        t.on_hover(170.2, 99.8, threshold_world=2.0)
        assert t.snap_hit is not None and t.snap_hit.via == vp.dxf.handle
        t.on_click(170.2, 99.8)
        t.snap_hit = None
        t.on_click(160.0, 130.0)               # the dimension line, on paper
        psp = win.document.doc.layouts.get("Layout1")
        dims = psp.query("DIMENSION")
        assert len(dims) == 1
        dim = dims[0]
        assert dim.get_measurement() == pytest.approx(20.0), "paper distance"
        assert dim.override().get("dimlfac") == pytest.approx(5.0)
        assert _dim_text(win.document, dim) == "100", (
            "the dimension reads the model, not the sheet")
        # undo and redo keep the factor: it lives in the command
        win.history.undo()
        assert not psp.query("DIMENSION")
        win.history.redo()
        dim = psp.query("DIMENSION")[0]
        assert dim.override().get("dimlfac") == pytest.approx(5.0)
        assert _dim_text(win.document, dim) == "100"
    finally:
        win.close()


def test_a_dimension_with_a_point_of_the_sheets_own_measures_paper(qapp):
    """One end on the plan through the window, the other on the title
    block: that is a paper measurement, and DIMLFAC stays alone."""
    win, t, vp = _window(qapp)
    try:
        t.start_tool("DIMLINEAR")
        t.on_hover(150.3, 100.2, threshold_world=2.0)
        t.on_click(150.3, 100.2)               # through the viewport
        t.on_hover(600.3, 60.2, threshold_world=2.0)
        assert t.snap_hit is not None and t.snap_hit.via is None
        t.on_click(600.3, 60.2)                # the sheet's own line
        t.snap_hit = None
        t.on_click(300.0, 20.0)
        dim = win.document.doc.layouts.get("Layout1").query("DIMENSION")[0]
        assert dim.override().get("dimlfac", None) in (None, 1.0)
        assert _dim_text(win.document, dim) == "450"
    finally:
        win.close()


def test_inside_mspace_the_model_engine_is_not_used(qapp):
    """MSPACE already edits the model through the projection: the snap
    there comes from the current space's own engine, as before."""
    win, t, vp = _window(qapp)
    try:
        win._activate_viewport(vp)
        qapp.processEvents()
        t.start_tool("LINE")
        t._model_snap_engine = None
        t.on_hover(150.4, 100.3, threshold_world=2.0)
        assert t.snap_hit is not None
        assert t.snap_hit.via is None
        assert (t.snap_hit.x, t.snap_hit.y) == pytest.approx((5000.0, 3000.0)), (
            "a MODEL point, as MSPACE answers")
        assert t._model_snap_engine is None
    finally:
        win.close()


def test_the_warmer_builds_the_model_engine_for_a_sheet(qapp):
    """The first hover over a viewport of a big plan must not pay the
    model walk in the GUI: the background warmer builds that engine too
    when the current space is a sheet."""
    from views.tool_controller import _CacheWarmer

    win, t, vp = _window(qapp)
    try:
        t._model_snap_engine = None
        warmer = _CacheWarmer(win.document)
        got = []
        warmer.done.connect(lambda *a: got.append(a))
        warmer._run()
        assert got and got[0][5] is not None, "no model engine for the sheet"
        t._on_caches_warm(*got[0])
        assert t._model_snap_engine is got[0][5]
        # and on the Model tab there is nothing to look through
        win.switch_layout("Model")
        _wait_regen(qapp, win)
        got.clear()
        w2 = _CacheWarmer(win.document)
        w2.done.connect(lambda *a: got.append(a))
        w2._run()
        assert got and got[-1][5] is None
    finally:
        win.close()
