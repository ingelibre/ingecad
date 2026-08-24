# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Moving or resizing a raster image must not re-tessellate the drawing.

Marco: dragging a corner grip of an inserted image took seconds to take
effect. Measured: the drop forced a full regen — 9.4 s on a real plan —
while the texture never changes on a move/resize; only the four corners of
its quad do. The surgical path rewrites those 6 vertices: the drop fell to
~80 ms and the pixels follow the mouse live at ~0.04 ms per move.

The other half of the stall: drawing an IMAGE through the ezdxf frontend
DECODES its file (PIL), so the vector overlay must never carry one — a
scanned sheet put a 36 MB decode inside every mouse move.
"""
from __future__ import annotations

import time

import numpy as np
import pytest

from core import actions


def _wait_regen(qapp, win, timeout_s=30.0):
    t0 = time.monotonic()
    while win._regen_worker is not None and time.monotonic() - t0 < timeout_s:
        qapp.processEvents()


def _win_with_image(qapp, tmp_path):
    from PIL import Image as PILImage
    from views.main_window import MainWindow

    png = tmp_path / "photo.png"
    PILImage.fromarray(
        (np.random.rand(64, 96, 3) * 255).astype(np.uint8)).save(png)
    win = MainWindow()
    win.new_document("mm")
    doc = win.document.doc
    image_def = doc.add_image_def(filename=str(png), size_in_pixel=(96, 64))
    win.document.modelspace().add_image(
        image_def=image_def, insert=(10.0, 20.0), size_in_units=(9.6, 6.4))
    win.document.dirty = True
    win.show()
    qapp.processEvents()
    win.regen_in_memory()
    _wait_regen(qapp, win)
    return win


def _quad(win, handle):
    scene = win.viewport._scene
    im = next(i for i in scene.images if i.handle == handle)
    ox, oy = scene.origin
    return [(float(c[0]) + ox, float(c[1]) + oy) for c in im.corners]


def test_corners_match_the_full_build(tmp_path):
    """The surgical math and the regen must agree to the last float."""
    import ezdxf
    from PIL import Image as PILImage

    from core.document import Document
    from render.backend import build_scene, image_corners_wcs

    png = tmp_path / "photo.png"
    PILImage.fromarray(
        (np.random.rand(64, 96, 3) * 255).astype(np.uint8)).save(png)
    doc = ezdxf.new("R2018", setup=True)
    image_def = doc.add_image_def(filename=str(png),
                                  size_in_pixel=(96, 64))
    img = doc.modelspace().add_image(
        image_def=image_def, insert=(10.0, 20.0), size_in_units=(9.6, 6.4))
    surgical = image_corners_wcs(img, (96, 64))
    scene = build_scene(Document(doc))
    built = next(i for i in scene.images if i.handle == img.dxf.handle)
    ox, oy = scene.origin
    full = [(float(c[0]) + ox, float(c[1]) + oy) for c in built.corners]
    err = max(max(abs(a - c), abs(b - d))
              for (a, b), (c, d) in zip(surgical, full))
    assert err < 1e-4, f"surgical corners drifted from the build: {err}"


def test_grip_drop_is_surgical(qapp, tmp_path):
    win = _win_with_image(qapp, tmp_path)
    try:
        img = next(e for e in win.document.modelspace()
                   if e.dxftype() == "IMAGE")
        h = img.dxf.handle
        from core.select import entity_grips
        g = entity_grips(img)[0]
        win.tools.selection = {h}
        before = _quad(win, h)
        win.tools.begin_grip_drag((g[0], g[1], g[2], h, 0))
        assert h not in win.viewport._hidden_images, (
            "the pixels must stay visible during the drag")
        win.tools.update_grip_drag(g[0] + 1.0, g[1] + 1.0)
        win.tools.finish_grip_drag(g[0] + 1.0, g[1] + 1.0)
        assert win._regen_worker is None, (
            "an image grip drop launched a full regen again")
        after = _quad(win, h)
        assert after != before, "the quad did not move"
        assert not win.tools._pending_render, (
            "the IMAGE was queued into the overlay — that decodes its "
            "file on every refresh")
    finally:
        win.close()


def test_undo_of_an_image_grip_is_surgical_and_exact(qapp, tmp_path):
    win = _win_with_image(qapp, tmp_path)
    try:
        img = next(e for e in win.document.modelspace()
                   if e.dxftype() == "IMAGE")
        h = img.dxf.handle
        from core.select import entity_grips
        g = entity_grips(img)[0]
        win.tools.selection = {h}
        before = _quad(win, h)
        win.tools.begin_grip_drag((g[0], g[1], g[2], h, 0))
        win.tools.finish_grip_drag(g[0] + 1.0, g[1] + 1.0)
        win._cmd_undo()
        assert win._regen_worker is None, "undo forced a regen"
        assert _quad(win, h) == pytest.approx(before), (
            "undo did not put the quad back")
    finally:
        win.close()


def test_move_command_is_surgical(qapp, tmp_path):
    win = _win_with_image(qapp, tmp_path)
    try:
        img = next(e for e in win.document.modelspace()
                   if e.dxftype() == "IMAGE")
        h = img.dxf.handle
        before = _quad(win, h)
        win.tools._execute(actions.move_entities([img], 2.0, 3.0))
        assert win._regen_worker is None, "MOVE of an image forced a regen"
        after = _quad(win, h)
        assert after[0][0] == pytest.approx(before[0][0] + 2.0)
        assert after[0][1] == pytest.approx(before[0][1] + 3.0)
        assert h not in win.viewport._hidden_images, (
            "the moved image is invisible until the merge")
    finally:
        win.close()


def test_image_never_rides_the_grip_overlay(qapp, tmp_path):
    """The overlay mounted at grab time kept the OLD frame on screen for
    seconds after the drop (Marco saw the stale border linger). An IMAGE
    must never be in the vector overlay: the live quad is the feedback."""
    win = _win_with_image(qapp, tmp_path)
    try:
        img = next(e for e in win.document.modelspace()
                   if e.dxftype() == "IMAGE")
        h = img.dxf.handle
        from core.select import entity_grips
        g = entity_grips(img)[0]
        win.tools.selection = {h}
        win.tools.begin_grip_drag((g[0], g[1], g[2], h, 0))
        assert win.tools.grip_overlay_entities() == [], (
            "the grab mounted the image's stale frame into the overlay")
        win.tools.finish_grip_drag(g[0] + 1.0, g[1] + 1.0)
        scene = win.viewport._overlay_scene
        assert scene is None or scene.is_empty, (
            "the drop left a stale overlay on screen")
    finally:
        win.close()
