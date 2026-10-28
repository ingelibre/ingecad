# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Panning inside a viewport stays live on the sheets colleagues send.

Marco (2026-09-27): "dentro del viewport hago pan para centrar el dibujo y
hay lag". Measured with real mouse events on Planos Constructivos: 60 moves
fired 60 sheet regens, and the live path never engaged. The reason: the
live navigation took any clipping_boundary_handle as "clipped, only the
bake can draw it" -- but on 25 of that sheet's 30 viewports (and on every
viewport of Plaza Yanque and Casa Peregrinos) the handle points at
NOTHING, a dangling reference the conversion leaves behind, and ezdxf
itself falls back to the frame for those. The other five are plain
rectangles, which a scissor clips as well as the frame does.

So :func:`core.layouts.viewport_clip` mirrors ezdxf's rule exactly, and
only a shaped boundary keeps the baked path.
"""
from __future__ import annotations

import pytest
from ezdxf.lldxf import const


def _sheet(win, boundary=None, dangling=False):
    """A sheet with one viewport; optionally a clipping boundary."""
    doc = win.document
    doc.modelspace().add_line((0, 0), (100, 50))
    psp = doc.doc.layouts.get("Layout1")
    vp = psp.add_viewport(center=(100, 70), size=(120, 80),
                          view_center_point=(50, 25), view_height=60)
    if boundary is not None:
        vp.dxf.flags |= const.VSF_NON_RECTANGULAR_CLIPPING
        vp.dxf.clipping_boundary_handle = boundary.dxf.handle
    elif dangling:
        vp.dxf.flags |= const.VSF_NON_RECTANGULAR_CLIPPING
        vp.dxf.clipping_boundary_handle = "FFFFFF"
    return psp, vp


def _drag(win, vp, moves=5):
    """Activate the viewport and pan the model inside it, as a middle-drag
    does; returns how many sheet regens the drag fired."""
    fired = []
    real = win.regen_in_memory
    win.regen_in_memory = lambda *a, **k: fired.append(1) or real(*a, **k)
    win.switch_layout("Layout1")
    win._activate_viewport(vp)
    _warm(win)                     # the user looks for a moment, then drags
    fired.clear()
    for _ in range(moves):
        assert win.vp_view_pan(1.0, 0.5) is True
    return len(fired)


def _warm(win) -> None:
    """Let the live model scene the activation started finish landing."""
    from PySide6.QtWidgets import QApplication

    worker = getattr(win, "_vp_live_worker", None)
    if worker is not None:
        worker.wait()
    for _ in range(5):
        QApplication.processEvents()


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    window = MainWindow()
    window.new_document("mm")
    yield window
    window.document.dirty = False
    window.close()


def test_viewport_clip_mirrors_ezdxf(win):
    from core.layouts import viewport_clip

    psp, vp = _sheet(win)
    assert viewport_clip(vp) is None                                   # no clip
    vp.dxf.clipping_boundary_handle = "FFFFFF"
    assert viewport_clip(vp) is None                                   # flag off: no clip
    vp.dxf.flags |= const.VSF_NON_RECTANGULAR_CLIPPING
    assert viewport_clip(vp) is None                                   # dangling: the frame
    rect = psp.add_lwpolyline([(60, 40), (140, 40), (140, 100), (60, 100)], close=True)
    vp.dxf.clipping_boundary_handle = rect.dxf.handle
    assert viewport_clip(vp) == (60.0, 40.0, 140.0, 100.0)
    shape = psp.add_lwpolyline([(60, 40), (140, 40), (150, 70), (140, 100),
                                (60, 100), (50, 70)], close=True)
    vp.dxf.clipping_boundary_handle = shape.dxf.handle
    assert viewport_clip(vp) is False                                  # a real shape
    bulged = psp.add_lwpolyline([(60, 40, 0, 0, 1), (140, 40), (140, 100), (60, 100)],
                                format="xyseb", close=True)
    vp.dxf.clipping_boundary_handle = bulged.dxf.handle
    assert viewport_clip(vp) is False                                  # arcs: not a rectangle


def test_a_dangling_clip_handle_pans_live_and_fires_no_regen(win):
    _psp, vp = _sheet(win, dangling=True)
    assert _drag(win, vp) == 0
    assert win.viewport._live_vp is not None


def test_a_rectangular_clip_pans_live_scissored_to_the_rectangle(win):
    psp, vp = _sheet(win)
    rect = psp.add_lwpolyline([(60, 40), (140, 40), (140, 100), (60, 100)], close=True)
    vp.dxf.flags |= const.VSF_NON_RECTANGULAR_CLIPPING
    vp.dxf.clipping_boundary_handle = rect.dxf.handle
    assert _drag(win, vp) == 0
    live = win.viewport._live_vp[0]
    assert live["rect"] == (60.0, 40.0, 140.0, 100.0)


def test_a_shaped_clip_keeps_the_baked_path(win):
    psp, vp = _sheet(win)
    shape = psp.add_lwpolyline([(60, 40), (140, 40), (150, 70), (140, 100),
                                (60, 100), (50, 70)], close=True)
    vp.dxf.flags |= const.VSF_NON_RECTANGULAR_CLIPPING
    vp.dxf.clipping_boundary_handle = shape.dxf.handle
    win.switch_layout("Layout1")
    win._activate_viewport(vp)
    assert win._vp_live_draw() is False


def test_a_full_turn_of_twist_is_no_twist(win):
    """Planos Constructivos' title-block viewport: view_twist_angle 720.
    One viewport that cannot go live keeps the whole sheet baked, so this
    one alone made every pan a regen."""
    from core.layouts import viewport_twist

    _psp, vp = _sheet(win, dangling=True)
    vp.dxf.view_twist_angle = 720.0
    assert viewport_twist(vp) == 0.0
    assert _drag(win, vp) == 0
    assert win.viewport._live_vp is not None
    vp.dxf.view_twist_angle = 15.0
    assert viewport_twist(vp) == 15.0


def test_a_twisted_viewport_pans_live_too(win):
    """Planos Constructivos' A-01 has a 60° viewport; one viewport that
    cannot go live keeps the whole sheet on the bake, so every pan tick
    inside ANY of its viewports re-baked the sheet (Marco: "hablo dentro
    del viewport"). The live matrix turns, as model_to_paper does."""
    _psp, vp = _sheet(win, dangling=True)
    vp.dxf.view_twist_angle = 60.0
    assert _drag(win, vp) == 0
    live = win.viewport._live_vp[0]
    assert live["angle"] == pytest.approx(60.0)


def test_dragging_right_after_the_double_click_never_freezes_or_regens(win):
    """The live model used to be built on the first pan tick, on the GUI
    thread: 5.8 s frozen on Planos Constructivos. The activation now starts
    it in the background; a drag meanwhile fires no regen per tick, and the
    display catches up with the cursor the moment the scene lands."""
    from PySide6.QtWidgets import QApplication

    _psp, vp = _sheet(win, dangling=True)
    fired = []
    real = win.regen_in_memory
    win.regen_in_memory = lambda *a, **k: fired.append(1) or real(*a, **k)
    win.switch_layout("Layout1")
    # the drag must still be under way when the scene lands: on a slow CI
    # machine the 700 ms settle timer ended the gesture first
    win._vp_gesture_timer.setInterval(60_000)
    win._activate_viewport(vp)
    worker = win._vp_live_worker
    assert worker is not None and worker.objectName() == "vp-live"
    fired.clear()
    for _ in range(5):                                # dragging already
        assert win.vp_view_pan(1.0, 0.5) is True
    assert fired == []
    worker.wait()
    import time
    deadline = time.monotonic() + 2.0                 # a slow CI delivers late
    while win.viewport._live_vp is None and time.monotonic() < deadline:
        QApplication.processEvents()
    assert win.viewport._live_vp is not None          # caught up, mid-gesture
    assert fired == []


def test_thick_half_world_scales_with_the_scene_s_pixels_per_unit():
    """A 0.5 mm line is 0.5 mm on screen whatever scene it lives in: the
    model shown through a 1:50 viewport spans 50 times fewer pixels per
    unit, so its half width in model units is 50 times larger."""
    from views.viewport import PX_PER_MM, thick_half_world

    paper = thick_half_world(0.5, True, 4.0)                # 4 px per paper mm
    model = thick_half_world(0.5, True, 4.0 * (1 / 50))     # through a 1:50 viewport
    assert paper == pytest.approx(0.5 * PX_PER_MM / 2 / 4.0)
    assert model == pytest.approx(paper * 50)
    assert thick_half_world(0.5, False, 4.0) == pytest.approx(0.5 / 4.0)   # LWT off: a hairline
    assert thick_half_world(0.0, True, 4.0) == pytest.approx(0.5 / 4.0)    # never under a pixel


def test_a_thick_line_inside_a_viewport_is_as_wide_live_as_baked(qapp):
    """Marco's video (2026-09-27): entering a viewport turned every wall
    into a black bar. The live path drew the model's lineweights at the
    paper's pixels per unit, 50x too wide in a 1:50 viewport. Pixels, live
    against baked, at the same view; needs a real GL context."""
    import numpy as np
    from PySide6.QtGui import QGuiApplication, QImage
    from PySide6.QtTest import QTest

    if QGuiApplication.platformName() in ("offscreen", "minimal"):
        pytest.skip("no OpenGL on this platform: the pixels need a real context")
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document("mm")
    win.resize(1000, 700)
    win.show()
    QTest.qWaitForWindowExposed(win, 5000)
    try:
        doc = win.document
        doc.modelspace().add_line((0, 0), (5000, 0), dxfattribs={"lineweight": 100})
        psp = doc.doc.layouts.get("Layout1")
        vp = psp.add_viewport(center=(150, 100), size=(120, 80),
                              view_center_point=(2500, 0), view_height=4000)
        win.viewport.lwt_on = True
        win.switch_layout("Layout1")

        def wait():
            deadline = 60
            import time
            t = time.monotonic()
            while time.monotonic() - t < deadline:
                qapp.processEvents()
                live = getattr(win, "_vp_live_worker", None)
                if (win._regen_worker is None and not win.tools._warmers
                        and not (live is not None and live.isRunning())):
                    break
            for _ in range(5):
                qapp.processEvents()

        shots = {}

        def rows_of_ink(label):
            win.viewport.grabFramebuffer()
            img = win.viewport.grabFramebuffer().convertToFormat(QImage.Format_RGB888)
            shots[label] = img
            a = np.frombuffer(img.constBits(), np.uint8).reshape(
                img.height(), img.bytesPerLine())[:, :img.width() * 3]
            a = a.reshape(img.height(), img.width(), 3).astype(int)
            dark = np.all(a < 80, axis=2)                      # the black line
            # a band around where the line's middle lands on screen, and
            # only the rows near it (the viewport's frame stays outside)
            dpr = img.devicePixelRatio()
            sx, sy = win.viewport.view.world_to_screen(150.0, 100.0)
            cx, cy = int(sx * dpr), int(sy * dpr)
            band = dark[max(0, cy - 40): cy + 40, max(0, cx - 5): cx + 5]
            return int(band.any(axis=1).sum())

        wait()
        win.viewport.zoom_extents()
        wait()
        baked = rows_of_ink("baked")
        assert baked >= 2
        win._activate_viewport(vp)
        wait()
        assert win.vp_view_pan(0.0, 0.0) is True
        wait()
        assert win.viewport._live_vp is not None
        live = rows_of_ink("live")
        if abs(live - baked) > 1:
            import tempfile

            folder = tempfile.mkdtemp(prefix="ingecad-lwt-")
            for label, img in shots.items():
                img.save(f"{folder}/{label}.png")
        assert abs(live - baked) <= 1, f"live {live} rows, baked {baked} (see {folder})"
    finally:
        win.document.dirty = False
        win.close()


def test_outside_the_active_viewport_the_pointer_is_an_arrow(win):
    """AutoCAD: inside MSPACE the crosshair is clipped to the active
    viewport, and over the rest of the sheet the pointer is the ordinary
    arrow. IngeCAD clipped the crosshair but painted nothing else, so the
    pointer vanished on the paper -- Marco: "cuando salgo al papel no hay
    cursor, ¿cómo sé que estoy en el papel?". The arrow is painted into the
    frame; the OS pointer stays blank (it flickers over GL on some setups)."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    _psp, vp = _sheet(win)
    win.switch_layout("Layout1")
    v = win.viewport
    v.zoom_extents()
    shapes = []
    original = v.setCursor
    v.setCursor = lambda c: (shapes.append(c.shape()), original(c))

    def move(paper_xy):
        sx, sy = v.view.world_to_screen(*paper_xy)
        pos = QPointF(sx, sy)
        QApplication.sendEvent(v, QMouseEvent(
            QEvent.MouseMove, pos, v.mapToGlobal(pos), Qt.NoButton, Qt.NoButton,
            Qt.NoModifier))
        QApplication.processEvents()

    move((30, 30))
    assert not v._arrow_pointer                           # paper: the crosshair
    win._activate_viewport(vp)
    _warm(win)
    move((150, 100))                                      # inside the viewport
    assert not v._arrow_pointer
    move((30, 30))                                        # out on the paper
    assert v._arrow_pointer
    move((150, 100))
    assert not v._arrow_pointer
    move((30, 30))
    win._deactivate_viewport()                            # PSPACE: paper again
    assert not v._arrow_pointer
    assert shapes == [] and v.cursor().shape() == Qt.BlankCursor


def test_zoom_extents_inside_a_viewport_shows_the_new_view_at_once(win):
    """Z + E inside a viewport fitted the view and waited for the sheet's
    full regen to show it -- 5.7 s on Planos Constructivos (Marco). The
    fitted view now shows through the live matrix at once, like a pan
    tick, and the regen lands afterwards."""
    _psp, vp = _sheet(win, dangling=True)
    doc = win.document
    doc.modelspace().add_circle((300, 200), 40)          # beyond the fitted view
    win.switch_layout("Layout1")
    win._activate_viewport(vp)
    _warm(win)
    height_before = float(vp.dxf.view_height)
    win._on_command_submitted("Z")
    win._on_command_submitted("E")
    assert float(vp.dxf.view_height) != height_before    # the view was fitted
    live = win.viewport._live_vp
    assert live is not None, "the new view waited for the regen"
    assert live[0]["factor"] == pytest.approx(
        float(vp.dxf.height) / float(vp.dxf.view_height))
    assert win.viewport.space_placement["factor"] == pytest.approx(live[0]["factor"])


def test_navigating_inside_a_viewport_re_bakes_the_sheet_only_on_leaving(win):
    """Every wheel burst inside a viewport re-baked the whole sheet when it
    settled -- a full parallel regen per pause, 12 in a minute of zooming
    on a real sheet (measured), the lag Marco felt. The live matrix already
    shows the exact view, so the bake waits until the viewport is left."""
    _psp, vp = _sheet(win, dangling=True)
    fired = []
    real = win.regen_in_memory
    win.regen_in_memory = lambda *a, **k: fired.append(1) or real(*a, **k)
    win.switch_layout("Layout1")
    win._activate_viewport(vp)
    _warm(win)
    fired.clear()
    for _ in range(3):                                 # three bursts, each settling
        assert win.vp_view_zoom(1.2, (100.0, 70.0)) is True
        win._vp_gesture_commit()                       # what the 700 ms timer does
    assert fired == []
    assert win.viewport._live_vp is not None           # the picture stays up
    assert win._vp_sheet_stale
    win._on_command_submitted("Z")
    win._on_command_submitted("E")
    assert fired == []
    win._deactivate_viewport()                         # PSPACE: now the sheet re-bakes
    assert fired == [1]
    assert not win._vp_sheet_stale


def test_a_twisted_viewport_draws_the_same_live_as_baked(qapp):
    """Pixels: a line through a 60° viewport, baked against live at the
    same view. Needs a real GL context."""
    import numpy as np
    from PySide6.QtGui import QGuiApplication, QImage
    from PySide6.QtTest import QTest

    if QGuiApplication.platformName() in ("offscreen", "minimal"):
        pytest.skip("no OpenGL on this platform: the pixels need a real context")
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document("mm")
    win.resize(1000, 700)
    win.show()
    QTest.qWaitForWindowExposed(win, 5000)
    try:
        doc = win.document
        msp = doc.modelspace()
        msp.add_line((0, 0), (5000, 0))
        msp.add_line((0, 0), (0, 3000))
        msp.add_circle((3000, 1500), 800)
        psp = doc.doc.layouts.get("Layout1")
        vp = psp.add_viewport(center=(150, 100), size=(160, 100),
                              view_center_point=(2500, 1500), view_height=5000)
        vp.dxf.view_twist_angle = 60.0
        win.switch_layout("Layout1")

        def wait():
            import time
            t = time.monotonic()
            while time.monotonic() - t < 60:
                qapp.processEvents()
                live = getattr(win, "_vp_live_worker", None)
                if (win._regen_worker is None and not win.tools._warmers
                        and not (live is not None and live.isRunning())):
                    break
            for _ in range(5):
                qapp.processEvents()

        def ink():
            win.viewport.grabFramebuffer()
            img = win.viewport.grabFramebuffer().convertToFormat(QImage.Format_RGB888)
            a = np.frombuffer(img.constBits(), np.uint8).reshape(
                img.height(), img.bytesPerLine())[:, :img.width() * 3]
            a = a.reshape(img.height(), img.width(), 3).astype(int)
            return np.all(a < 80, axis=2)                  # black on paper

        wait()
        win.viewport.zoom_extents()
        wait()
        baked = ink()
        win._activate_viewport(vp)
        wait()
        assert win.vp_view_pan(0.0, 0.0) is True
        wait()
        assert win.viewport._live_vp is not None
        live = ink()
        # the active-viewport frame is drawn heavier live: compare inside it
        x0, y0 = win.viewport.view.world_to_screen(75, 55)
        x1, y1 = win.viewport.view.world_to_screen(225, 145)
        dpr = live.shape[0] / win.viewport.height()
        sl = (slice(int(y1 * dpr), int(y0 * dpr)), slice(int(x0 * dpr), int(x1 * dpr)))
        b, l = baked[sl], live[sl]
        # not empty: 191 px under the CI's software GL (llvmpipe), ~250 here
        assert b.sum() > 100, "the baked viewport shows the model"
        differing = (b != l).sum()
        assert differing < 0.05 * b.sum(), f"{differing} px differ of {b.sum()} ink"
    finally:
        win.document.dirty = False
        win.close()


def test_an_edit_inside_a_viewport_never_freezes_the_next_pan(win, monkeypatch):
    """After an edit the live model is stale; the next pan tick used to
    rebuild it on the GUI thread (2.4 s frozen on a real sheet). The tick
    now asks for the background build and draws nothing rather than
    waiting; the display catches up when it lands."""
    import threading

    from PySide6.QtWidgets import QApplication

    from render import backend

    _psp, vp = _sheet(win, dangling=True)
    win.switch_layout("Layout1")
    win._activate_viewport(vp)
    _warm(win)
    assert win.vp_view_pan(1.0, 0.5) is True
    assert win.viewport._live_vp is not None
    win._vp_gesture_commit()

    main = threading.main_thread()
    on_gui = []
    real_build = backend.build_scene

    def spy(document, layout_name=None, **kw):
        if kw.get("canvas") is not None and threading.current_thread() is main:
            on_gui.append(1)
        return real_build(document, layout_name, **kw)

    monkeypatch.setattr(backend, "build_scene", spy)
    # the edit's own warm-up is held back: a stale cache with nothing in
    # flight is exactly what the tick must cope with
    asked = []
    real_warm = win._vp_warm_live_scene
    monkeypatch.setattr(win, "_vp_warm_live_scene", lambda: asked.append(1))
    win.invalidate_vp_model_cache()                            # what an edit does
    assert asked == [1] and win._vp_model_cache is None
    assert win.vp_view_pan(1.0, 0.5) is True                   # the next pan
    assert on_gui == [], "the live model was rebuilt on the GUI thread"
    assert asked == [1, 1]                                     # the tick asked for it
    monkeypatch.setattr(win, "_vp_warm_live_scene", real_warm)
    real_warm()
    win._vp_live_worker.wait()
    for _ in range(5):
        QApplication.processEvents()
    assert win.viewport._live_vp is not None                   # caught up
    assert on_gui == []
