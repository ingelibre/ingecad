# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""One question, one place.

Marco's ask for this session (CLAUDE.md, 2026-08-29): when the same
question is answered in two places, sooner or later the two answers differ
-- the PICKBOX that drew half of what it caught, the obsolete comment that
lived in two files. Each test here pins the answer the app gives to one
such question THROUGH the path the app really takes (a mouse move, a tab
switch, a command), so that unifying the answer can be measured: the answer
must not move. Where the two answers had already drifted apart, the test
says which one is right and why.
"""
from __future__ import annotations

import math
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _wait_regen(qapp, win, timeout_s=20.0):
    t0 = time.monotonic()
    while win._regen_worker is not None and time.monotonic() - t0 < timeout_s:
        qapp.processEvents()


def _move(win, sx: float, sy: float) -> None:
    """A real mouse move over the canvas, in logical pixels."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    event = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(sx, sy),
                        QPointF(sx, sy), Qt.NoButton, Qt.NoButton,
                        Qt.NoModifier)
    win.viewport.mouseMoveEvent(event)


def _plain_window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document("mm")
    win.viewport.refresh_cursor_prefs()
    qapp.processEvents()
    return win


class _SpyEngine:
    """Stands in for the snap engine and records the aperture it is asked
    to search with -- the only observable of "how far does snap reach"."""

    _dirty = False

    def __init__(self) -> None:
        self.thresholds: list[float] = []

    def find(self, point, threshold, **kwargs):
        self.thresholds.append(threshold)
        return None


# -- what colour is ACI n? -----------------------------------------------------

def test_every_aci_has_exactly_one_swatch_colour(qapp):
    """The layers panel kept its own table of the nine standard colours and
    fell back to the Select Color dialog's resolver for the rest: two
    answers to "what colour is index n". Pinned: for 1-255 it is ezdxf's
    palette; ByLayer, ByBlock and garbage get the neutral grey chip."""
    from ezdxf.colors import aci2rgb
    from PySide6.QtGui import QColor

    from views.color_dialog import aci_qcolor

    for index in list(range(-1, 258)) + [300]:
        if 1 <= index <= 255:
            expected = QColor(*aci2rgb(index))
        else:
            expected = QColor(160, 160, 160)
        assert aci_qcolor(index) == expected, index


def test_the_aci_palette_is_resolved_in_one_module():
    """Structural: ezdxf's palette is consulted, and an RGB table for the
    standard colours is written, in exactly one file of the UI."""
    import re

    resolvers = []
    for folder in ("views", "tools", "core"):
        for path in sorted((ROOT / folder).glob("*.py")):
            text = path.read_text(encoding="utf-8")
            if "aci2rgb" in text or re.search(r"\b1:\s*\(255,\s*0,\s*0\)", text):
                resolvers.append(path.relative_to(ROOT).as_posix())
    assert resolvers == ["views/color_dialog.py"]


# -- how far does the mouse reach? ---------------------------------------------

def test_the_pick_aperture_is_the_pickbox_in_pixels(qapp):
    """PICKBOX is the half-size of the pick aperture, in logical pixels.
    The old formula reached the same number by a detour (snap aperture x
    PICK_PX x box / PICKBOX_PX / SNAP_PX); this pins the number, not the
    detour."""
    win = _plain_window(qapp)
    try:
        vp = win.viewport
        _move(win, 100, 80)
        scale = vp.view.scale
        box = vp._pickbox_px
        assert win.tools._pick_tolerance == pytest.approx(box / scale)

        vp._pickbox_px = box * 3            # what refresh_cursor_prefs sets
        _move(win, 101, 80)
        assert win.tools._pick_tolerance == pytest.approx(3 * box / scale)
    finally:
        win.close()


def test_the_snap_aperture_is_twelve_pixels(qapp):
    win = _plain_window(qapp)
    try:
        spy = _SpyEngine()
        win.tools.snap_engine = spy
        win.tools.start_tool("LINE")
        _move(win, 120, 90)
        assert spy.thresholds, "hovering with LINE active never asked the snap engine"
        assert spy.thresholds[-1] == pytest.approx(12.0 / win.viewport.view.scale)
    finally:
        win.tools.cancel()
        win.close()


def test_a_grip_is_caught_within_seven_pixels_and_not_at_nine(qapp):
    from core import actions

    win = _plain_window(qapp)
    t = win.tools
    try:
        t._execute(actions.add_line((10, 10), (60, 10)))
        t._pick_tolerance = 1.0
        t.on_click(35, 10)
        assert t.selection, "the line did not select"
        sx, sy = win.viewport.view.world_to_screen(60, 10)
        _move(win, sx + 6, sy)
        assert win.viewport._grip_hover is not None
        _move(win, sx + 9, sy)
        assert win.viewport._grip_hover is None
    finally:
        win.document.dirty = False
        win.close()


def _sheet_window(qapp):
    """A sheet with a viewport at 1:5 showing a model line (the fixture of
    test_mspace_editing): paper (150, 100) is the centre of the frame."""
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    msp = win.document.doc.modelspace()
    msp.add_line((5000, 3000), (5100, 3000))
    psp = win.document.doc.layouts.get("Layout1")
    psp.add_text("PLANO", dxfattribs={"height": 5, "insert": (620, 40)})
    vp = psp.add_viewport(center=(150, 100), size=(200, 120),
                          view_center_point=(5000, 3000), view_height=600)
    win._refresh_layout_tabs()
    qapp.processEvents()
    win.switch_layout("Layout1")
    _wait_regen(qapp, win)
    win._activate_viewport(vp)
    qapp.processEvents()
    return win, win.tools, vp


def test_inside_mspace_every_aperture_shrinks_by_the_viewport_scale(qapp):
    """Screen distances are paper millimetres; through a 1:5 viewport they
    are five times more model units. The pickbox and the snap aperture
    already knew (the MSPACE session put the conversion at the door). The
    dimension magnet measured its own twelve pixels and forgot the
    viewport: one of the three answers was wrong, which is the whole point
    of asking once."""
    from core import layouts as layout_ops

    win, t, vp = _sheet_window(qapp)
    try:
        factor = layout_ops.viewport_scale(vp)
        assert factor == pytest.approx(0.2)
        sx, sy = win.viewport.view.world_to_screen(150, 100)
        scale = win.viewport.view.scale

        _move(win, sx, sy)
        assert t._pick_tolerance == pytest.approx(
            win.viewport._pickbox_px / scale / factor)

        spy = _SpyEngine()
        t.snap_engine = spy
        t.start_tool("LINE")
        _move(win, sx + 1, sy)
        assert spy.thresholds[-1] == pytest.approx(12.0 / scale / factor)

        t.cancel()
        t.start_tool("DIMLINEAR")
        assert t.tool is not None
        assert t.tool._align_threshold() == pytest.approx(12.0 / scale / factor)
    finally:
        t.cancel()
        win.document.dirty = False
        win.close()


# -- how finely are curves flattened right now? --------------------------------

def test_the_overlay_flattens_curves_like_the_scene_in_every_space(qapp):
    """The base scene and the overlay must tessellate a curve at the same
    distance, or an arc drawn now would not match the arcs on screen. The
    controller recomputed its copy at three moments with three spellings;
    the block editor's scene used a fourth formula (the block's own
    extents), and the controller's copy in that space read the DRAWING's
    header instead -- coarser by orders of magnitude on any saved plan."""
    from PySide6.QtCore import QSettings

    from render.backend import (FLATTEN_REL, SETTING_VIEWRES,
                                _flatten_distance)

    settings = QSettings()
    saved = settings.value(SETTING_VIEWRES, None)
    win = _plain_window(qapp)
    t = win.tools
    try:
        doc = win.document
        header = doc.doc.header
        header["$EXTMIN"], header["$EXTMAX"] = (0, 0, 0), (100000, 100000, 0)
        header["$PEXTMIN"], header["$PEXTMAX"] = (0, 0, 0), (420, 297, 0)

        t.space_changed()
        model = math.hypot(100000, 100000) * FLATTEN_REL
        assert t._flatten == pytest.approx(model)
        assert t._flatten == pytest.approx(_flatten_distance(doc.current_space()))

        win.switch_layout("Layout1")
        _wait_regen(qapp, win)
        sheet = math.hypot(420, 297) * FLATTEN_REL
        assert t._flatten == pytest.approx(sheet)
        assert sheet != pytest.approx(model)        # the space really changed it

        settings.setValue(SETTING_VIEWRES, 4000)   # four times finer
        win.refresh_curve_tolerance()
        _wait_regen(qapp, win)
        assert t._flatten == pytest.approx(sheet / 4)

        settings.remove(SETTING_VIEWRES)
        win.switch_layout("Model")
        _wait_regen(qapp, win)
        chair = doc.doc.blocks.new("SILLA")
        chair.add_line((0, 0), (10, 0))
        doc.doc.modelspace().add_blockref("SILLA", (50, 50))
        win.dispatcher.submit("BEDIT SILLA")
        _wait_regen(qapp, win)
        assert doc.edit_block == "SILLA"
        # the scene of the block editor: the block's own extents, never the
        # drawing's header -- a 10-unit chair is not a 100 km plan
        assert t._flatten == pytest.approx(10.0 * FLATTEN_REL)
        win._end_block_session(save=True)
    finally:
        settings.remove(SETTING_VIEWRES) if saved is None else \
            settings.setValue(SETTING_VIEWRES, saved)
        win.document.dirty = False
        win.close()


# -- which space is current? ---------------------------------------------------

def test_the_activated_viewport_is_read_in_two_places_only():
    """The document owns "which space is current" (current_space); the
    window owns the tab and the MSPACE viewport, and tells the document.
    Outside the window the viewport entity is read in exactly two places:
    the controller's door (space_vp) and the canvas's wheel/pan routing.
    A third reader is a second answer waiting to drift."""
    readers: dict[str, int] = {}
    for folder in ("views", "tools", "core", "render"):
        for path in sorted((ROOT / folder).glob("*.py")):
            if path.name == "main_window.py":
                continue
            count = path.read_text(encoding="utf-8").count("_active_vp")
            if count:
                readers[path.relative_to(ROOT).as_posix()] = count
    assert readers == {"views/tool_controller.py": 1, "views/viewport.py": 1}
