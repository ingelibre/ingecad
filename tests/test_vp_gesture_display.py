# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Panning inside a viewport must never leave it empty.

A tester: "al panear dentro de una ventana desaparece el dibujo". Measured
on a synthetic sheet: a pan tick goes live (the sheet's baked copy of the
model is hidden, a matrix draws the model at the new view); 700 ms later
the gesture committed, dropped the live matrix -- and asked nobody for the
regen its comment promised. Hidden copy, no live picture, no regen coming:
264 visible vertices before the pan, 8 (the viewport border) after the
commit, still 8 three seconds later. The picture only came back with the
next edit or tab switch.

The rule now: the live matrix stays up until the fresh sheet lands, and
the commit is what asks for that sheet. Measured the same way: 8 visible
vertices with the live matrix on during the regen, 264 once it lands.

These tests read the scene the canvas draws (vertex alphas, live matrix,
regen in flight) rather than pixels, because the offscreen platform has no
GL framebuffer; the pixel version was run by hand under xcb.
"""
from __future__ import annotations

import time


def _wait_regen(qapp, win, timeout_s=30.0):
    t0 = time.monotonic()
    while win._regen_worker is not None and time.monotonic() - t0 < timeout_s:
        qapp.processEvents()
        time.sleep(0.005)


def _visible_vertices(win) -> int:
    """Vertices of the sheet scene with a non-zero alpha: what is drawn."""
    scene = win.viewport._scene
    total = 0
    for name in ("lines", "thick", "triangles", "points"):
        batch = getattr(scene, name, None)
        if batch is not None and len(batch.data):
            total += int((batch.data["rgba"][:, 3] > 0).sum())
    return total


def _window_in_mspace(qapp):
    """A sheet with one plain viewport on a circle, MSPACE active, the
    sheet scene built and adopted."""
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    win.document.modelspace().add_circle((10, 5), 3)
    psp = win.document.doc.layouts.get("Layout1")
    vp = psp.add_viewport(center=(100, 100), size=(80, 60),
                          view_center_point=(10, 5), view_height=20)
    win.switch_layout("Layout1")
    _wait_regen(qapp, win)
    win._activate_viewport(vp)
    _wait_regen(qapp, win)
    assert win.viewport._live_vp is None
    assert _visible_vertices(win) > 8, "the sheet shows the circle"
    return win, vp


def test_the_picture_survives_the_gesture_commit(qapp):
    win, vp = _window_in_mspace(qapp)
    try:
        baseline = _visible_vertices(win)
        assert win.vp_view_pan(5.0, 2.0)
        assert win.viewport._live_vp is not None, "the tick went live"
        assert _visible_vertices(win) < baseline, "baked copy hidden"

        win._vp_gesture_commit()
        # The moment the tester saw the blank: no live matrix, hidden copy,
        # nothing in flight. Now the live picture stays up while the fresh
        # sheet is built.
        assert win.viewport._live_vp is not None, (
            "the live matrix was dropped before the fresh sheet landed")
        assert win._regen_worker is not None, "the commit asked for the regen"

        _wait_regen(qapp, win)
        assert win.viewport._live_vp is None, "the fresh sheet retired it"
        assert _visible_vertices(win) == baseline, (
            "the fresh sheet shows the model again")
    finally:
        win.close()


def test_a_gesture_that_ends_where_it_started_needs_no_regen(qapp):
    win, vp = _window_in_mspace(qapp)
    try:
        baseline = _visible_vertices(win)
        scene = win.viewport._scene
        assert win.vp_view_pan(5.0, 2.0)
        assert win.vp_view_pan(-5.0, -2.0)      # back to the start
        win._vp_gesture_commit()
        assert win.viewport._live_vp is None
        assert win._regen_worker is None, "nothing changed: no rebuild"
        assert win.viewport._scene is scene
        assert _visible_vertices(win) == baseline, (
            "the hidden copy came back surgically")
    finally:
        win.close()


def test_a_new_burst_during_the_regen_keeps_the_live_picture(qapp):
    """Pause 700 ms, pan again while the previous commit's regen is still
    running: the fresh sheet must not show its copy of the model under the
    live one, and the second commit retires the live matrix in the end."""
    win, vp = _window_in_mspace(qapp)
    try:
        baseline = _visible_vertices(win)
        assert win.vp_view_pan(5.0, 2.0)
        win._vp_gesture_commit()
        assert win._regen_worker is not None
        # the next burst starts before that regen lands
        assert win.vp_view_pan(3.0, 1.0)
        assert win._vp_gesture is not None
        _wait_regen(qapp, win)
        assert win.viewport._live_vp is not None, "still mid-gesture"
        assert _visible_vertices(win) < baseline, (
            "the fresh sheet's copy of the model is hidden under the live one")
        win._vp_gesture_commit()
        _wait_regen(qapp, win)
        assert win.viewport._live_vp is None
        assert _visible_vertices(win) == baseline
    finally:
        win.close()


def test_leaving_the_viewport_mid_gesture_does_not_blank_it(qapp):
    """PSPACE (or a double-click on the paper) right after a pan: the
    commit it triggers keeps the picture up until the sheet is rebuilt."""
    win, vp = _window_in_mspace(qapp)
    try:
        baseline = _visible_vertices(win)
        assert win.vp_view_pan(5.0, 2.0)
        win._deactivate_viewport()
        assert win._active_vp is None
        if win._regen_worker is not None:
            assert win.viewport._live_vp is not None, (
                "blank until the regen lands")
        _wait_regen(qapp, win)
        assert win.viewport._live_vp is None
        assert _visible_vertices(win) == baseline
    finally:
        win.close()


def test_a_sheet_that_cannot_go_live_is_not_charged_the_model_build(
        qapp, monkeypatch):
    """One clipped or twisted viewport keeps the whole sheet on the bake
    path. Finding that out used to cost the model tessellation first --
    5.3 s, synchronous, on the first tick of every gesture on a real plan
    whose viewports are all clipped."""
    win, vp = _window_in_mspace(qapp)
    try:
        monkeypatch.setattr(win, "_vp_placement", lambda v: None)
        built = []
        monkeypatch.setattr(win, "_vp_model_scene",
                            lambda: built.append(1) or None)
        assert win.vp_view_pan(5.0, 2.0)
        assert not built, "the model scene was built for nothing"
        assert win.viewport._live_vp is None
        win._vp_gesture_commit()
        _wait_regen(qapp, win)
    finally:
        win.close()


def test_the_live_model_tessellation_is_coloured_for_the_sheet(qapp):
    """The second half of the same report, found by looking at the pixels:
    the live matrix drew nothing visible. The model was tessellated for the
    model canvas -- ACI 7 white -- and drawn on the white paper. On a plan
    drawn all in "color 7", the whole drawing vanished the moment a pan
    began. Measured after the fix: the live picture and the sheet's bake
    differ in 11 pixels of 1 151 880."""
    import numpy as np

    from render.backend import build_scene

    win, vp = _window_in_mspace(qapp)
    try:
        sheet = win.document.doc.layouts.get("Layout1")
        for_model_tab = build_scene(win.document, "Model")
        for_sheet = build_scene(win.document, "Model", canvas=sheet)
        white = np.unique(for_model_tab.lines.data["rgba"][:, :3], axis=0)
        black = np.unique(for_sheet.lines.data["rgba"][:, :3], axis=0)
        assert white.tolist() == [[255, 255, 255]], "control: the model tab"
        assert black.tolist() == [[0, 0, 0]], "ACI 7 resolved against paper"
        live = win._vp_model_scene()
        assert np.unique(live.lines.data["rgba"][:, :3], axis=0).tolist() \
            == [[0, 0, 0]], "the live path uses the sheet's colours"
    finally:
        win.close()
