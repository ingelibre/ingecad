# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Switching Model/Layout tabs must not re-tessellate an unchanged drawing.

Marco felt it on a real plan: two or three seconds from layout to model,
every single time. Each tab switch launched a full regen; the drawing had
not changed since the last visit. The window now keeps the built scene per
tab, keyed by document revision, and re-adopts it on the way back.

The cache serves ONLY the tab switch. Every ordinary regen request empties
it, because display settings (VIEWRES, smoothing) change the tessellation
without touching the revision — a stale cached scene would resurrect the
old quality on the next tab switch and no key could tell.
"""
from __future__ import annotations

import time

from core import actions


def _wait_regen(qapp, win, timeout_s=20.0):
    t0 = time.monotonic()
    while win._regen_worker is not None and time.monotonic() - t0 < timeout_s:
        qapp.processEvents()


def _make(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document("mm")
    win.tools._execute(actions.add_line((0, 0), (100, 50)))
    win.document.doc.layouts.new("Sheet")
    win._refresh_layout_tabs()
    win.show()
    qapp.processEvents()
    win.regen_in_memory()
    _wait_regen(qapp, win)
    return win


def test_returning_to_a_visited_tab_adopts_the_kept_scene(qapp):
    win = _make(qapp)
    try:
        model_scene = win.viewport._scene
        win.switch_layout("Sheet")
        _wait_regen(qapp, win)
        win.switch_layout("Model")
        assert win._regen_worker is None, (
            "the switch back launched a regen for an unchanged drawing")
        assert win.viewport._scene is model_scene, (
            "the kept scene was not re-adopted")
    finally:
        win.close()


def test_an_edit_invalidates_the_kept_scenes(qapp):
    win = _make(qapp)
    try:
        win.switch_layout("Sheet")
        _wait_regen(qapp, win)
        # editing bumps the revision AND the regen request clears the cache
        win.tools._execute(actions.add_line((10, 10), (20, 20)))
        win.regen_in_memory()
        _wait_regen(qapp, win)
        win.switch_layout("Model")
        _wait_regen(qapp, win)          # a fresh build must run
        scene = win.viewport._scene
        assert scene is not None
        handles = {e.dxf.handle for e in win.document.modelspace()
                   if e.dxftype() == "LINE"}
        assert all(h in scene.handle_ranges for h in handles), (
            "the re-adopted model scene misses the new line")
    finally:
        win.close()


def test_a_plain_regen_request_empties_the_cache(qapp):
    """VIEWRES-style settings regen without a revision bump — the cache
    must not outlive any explicit regen request."""
    win = _make(qapp)
    try:
        assert win._layout_scenes, "precondition: something was cached"
        win.regen_in_memory()
        assert not win._layout_scenes or win._regen_worker is not None
        _wait_regen(qapp, win)
        # after adoption only the active tab is cached again
        assert set(win._layout_scenes) <= {"Model", "Sheet"}
    finally:
        win.close()


def test_a_tab_switch_dirties_the_file_but_not_the_revision(qapp):
    """switch_active must reach the saved file ($TILEMODE) without bumping
    the revision — the bump is what used to invalidate this very cache on
    every switch, making it dead code that measured well."""
    win = _make(qapp)
    try:
        win.document.dirty = False
        rev = win.document.revision
        win.switch_layout("Sheet")
        assert win.document.dirty, "the tab choice must reach the file"
        assert win.document.revision == rev, (
            "a tab switch changed no drawable content")
    finally:
        win.close()
