# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""2D drafting viewport: dark model space, AutoCAD-style crosshair, pan/zoom.

Uses PySide6's bundled QOpenGL* helper classes — no external GL bindings.

Wayland requires every frame to be drawn explicitly: ``paintGL`` always calls
``glClear`` first, and re-establishes all relevant GL state each frame because
the QPainter overlay (crosshair, UCS icon) contaminates it between frames.
Both gotchas were hard-won in IngeTrazo — do not "simplify" them away.

Navigation (AutoCAD-like):
- Middle-button drag: pan
- Wheel: zoom in/out at the cursor
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

import numpy as np
from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QMatrix4x4,
    QOpenGLFunctions,
    QPainter,
    QPen,
    QPolygonF,
)
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLVertexArrayObject,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QRubberBand

from core.paths import app_root
from render.batches import THICK_DTYPE, VERTEX_DTYPE, Batch, Scene
from render.view import ViewTransform2D

# OpenGL constants — kept as literals so we don't depend on PyOpenGL.
GL_FLOAT = 0x1406
GL_UNSIGNED_BYTE = 0x1401

GRIP_PICK_PX = 7.0  # grip hit aperture, logical pixels
SNAP_PX_HOVER = 12.0  # osnap aperture while a hot grip follows the cursor
GL_POINTS = 0x0000
GL_LINES = 0x0001
GL_TRIANGLES = 0x0004
GL_COLOR_BUFFER_BIT = 0x00004000
GL_DEPTH_TEST = 0x0B71
GL_SCISSOR_TEST = 0x0C11
GL_BLEND = 0x0BE2
GL_SRC_ALPHA = 0x0302
GL_ONE_MINUS_SRC_ALPHA = 0x0303

SHADER_DIR = app_root() / "resources" / "shaders"

# Classic dark model space (near-black, slightly blue like AutoCAD's default).
BACKGROUND = (0.129, 0.149, 0.169)
AXIS_LEN = 1.0e6  # world units; clipped by GL, cheap to keep "infinite"
CROSSHAIR_COLOR = QColor(215, 215, 215, 210)        # over the dark canvas
CROSSHAIR_COLOR_LIGHT = QColor(40, 40, 40, 210)     # over paper-white layouts
PICKBOX_PX = 8

#: AutoCAD's CURSORSIZE (p. 2202): crosshair length as a percentage of the
#: screen, 1-100, where 100 means full-screen arms. AutoCAD ships 5; IngeCAD
#: ships 100 because that is what it has always drawn -- changing the default
#: would shrink every existing user's cursor without being asked.
SETTING_CURSORSIZE = "display/cursorsize"
CURSORSIZE_DEFAULT = 100
#: Crosshair colour. Empty means "follow the background", which is what the
#: canvas did before there was a choice: light over dark, dark over paper.
SETTING_CROSSHAIR_COLOR = "display/crosshair_color"
#: AutoCAD's PICKBOX (p. 2452): the selection target, in pixels. It drives
#: the drawn box AND the aperture that actually picks, which is the point --
#: they used to be set independently, so the box on screen was half the size
#: of what it caught.
SETTING_PICKBOX = "selection/pickbox"


def _int_pref(key: str, default: int, low: int, high: int) -> int:
    try:
        from PySide6.QtCore import QSettings

        value = int(QSettings().value(key, default))
    except (TypeError, ValueError, Exception):
        return default
    return value if low <= value <= high else default


def cursorsize() -> int:
    return _int_pref(SETTING_CURSORSIZE, CURSORSIZE_DEFAULT, 1, 100)


def pickbox() -> int:
    return _int_pref(SETTING_PICKBOX, PICKBOX_PX, 1, 50)


def crosshair_color():
    """The chosen colour, or None to follow the background."""
    try:
        from PySide6.QtCore import QSettings

        name = str(QSettings().value(SETTING_CROSSHAIR_COLOR, "") or "")
    except Exception:
        return None
    if not name:
        return None
    color = QColor(name)
    return color if color.isValid() else None
# Lineweight display: mm of paper -> logical pixels (96 dpi reference,
# AutoCAD LWT look). 0.5 mm ~ 2 px, 1.0 mm ~ 4 px.
PX_PER_MM = 96.0 / 25.4
# Text glyphs smaller than this on screen are illegible: skip their ranges
# (they reappear instantly on zoom-in — the data stays on the GPU).
MIN_TEXT_PX = 2.0


# Paper sheet colors (layout tabs): white paper on the gray desk, soft drop
# shadow, and the dashed printable-area margin AutoCAD draws inside it.
PAPER_SHEET_RGBA = (255, 255, 255, 255)
PAPER_SHADOW_RGBA = (0, 0, 0, 70)
PAPER_BORDER_RGBA = (70, 74, 80, 255)
PAPER_MARGIN_RGBA = (150, 154, 158, 255)


def _paper_vertices(paper: dict, origin: tuple[float, float]) -> tuple:
    """(triangles, lines) vertex arrays for the paper sheet of a layout.

    World coordinates minus the scene origin, same convention as packed
    batches, so the viewport reuses the scene MVP. Pure NumPy — testable
    without a GL context.
    """
    ox, oy = origin
    x0, y0, x1, y1 = paper["sheet"]
    x0, y0, x1, y1 = x0 - ox, y0 - oy, x1 - ox, y1 - oy
    w, h = x1 - x0, y1 - y0
    d = 0.015 * max(w, h)                      # shadow offset, world units

    def quad(ax, ay, bx, by, rgba):
        v = np.zeros(6, dtype=VERTEX_DTYPE)
        v["pos"] = [(ax, ay), (bx, ay), (bx, by),
                    (ax, ay), (bx, by), (ax, by)]
        v["rgba"] = rgba
        return v

    tris = np.concatenate((
        quad(x0 + d, y0 - d, x1 + d, y1 - d, PAPER_SHADOW_RGBA),
        quad(x0, y0, x1, y1, PAPER_SHEET_RGBA),
    ))

    segments: list[tuple[float, float, float, float, tuple]] = [
        (x0, y0, x1, y0, PAPER_BORDER_RGBA),
        (x1, y0, x1, y1, PAPER_BORDER_RGBA),
        (x1, y1, x0, y1, PAPER_BORDER_RGBA),
        (x0, y1, x0, y0, PAPER_BORDER_RGBA),
    ]
    printable = paper.get("printable")
    if printable is not None:
        px0, py0, px1, py1 = (printable[0] - ox, printable[1] - oy,
                              printable[2] - ox, printable[3] - oy)
        dash = max(w, h) / 90.0                # scales with the sheet
        gap = dash * 0.6
        for ax, ay, bx, by in ((px0, py0, px1, py0), (px1, py0, px1, py1),
                               (px1, py1, px0, py1), (px0, py1, px0, py0)):
            length = float(np.hypot(bx - ax, by - ay))
            if length <= 0.0:
                continue
            ux, uy = (bx - ax) / length, (by - ay) / length
            t = 0.0
            while t < length:
                e = min(t + dash, length)
                segments.append((ax + ux * t, ay + uy * t,
                                 ax + ux * e, ay + uy * e, PAPER_MARGIN_RGBA))
                t = e + gap

    lines = np.zeros(2 * len(segments), dtype=VERTEX_DTYPE)
    for i, (ax, ay, bx, by, rgba) in enumerate(segments):
        lines["pos"][2 * i] = (ax, ay)
        lines["pos"][2 * i + 1] = (bx, by)
        lines["rgba"][2 * i] = lines["rgba"][2 * i + 1] = rgba
    return tris, lines


def _axes_vertices() -> np.ndarray:
    """X and Y world axes through the origin in the standard vertex format."""
    data = np.zeros(4, dtype=VERTEX_DTYPE)
    data["pos"] = [(-AXIS_LEN, 0.0), (AXIS_LEN, 0.0),
                   (0.0, -AXIS_LEN), (0.0, AXIS_LEN)]
    data["rgba"][0] = data["rgba"][1] = (122, 46, 46, 255)   # muted red X
    data["rgba"][2] = data["rgba"][3] = (41, 107, 46, 255)   # muted green Y
    return data


class Viewport(QOpenGLWidget):
    """Model-space canvas. Owns the view transform; documents plug in at F1."""

    cursorMoved = Signal(float, float)  # world coordinates under the cursor

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.view = ViewTransform2D(width=self.width(), height=self.height())
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        # The crosshair *is* the cursor in model space, AutoCAD-style.
        self.setCursor(Qt.BlankCursor)
        self._cursor: Optional[QPointF] = None
        self._panning = False
        self._pan_last_screen = None
        # MSPACE navigation: the model tessellated once, drawn through the
        # active viewport with nothing but a matrix change per frame.
        self._live_vp = None
        self._last_pos = QPointF()
        self._gl: Optional[QOpenGLFunctions] = None
        self._program: Optional[QOpenGLShaderProgram] = None
        self._scene: Optional[Scene] = None
        self._scene_dirty = False
        # Per-primitive GPU buffers: name -> (vao, vbo, vertex_count)
        self._scene_bufs: dict[str, tuple] = {}
        # Raster IMAGEs: [(texture, vao, vbo, group, handle)] per scene.
        self._image_bufs: list[tuple] = []
        self._hidden_images: set = set()
        # Paper sheet of a layout tab (shadow + white sheet + margin dashes),
        # drawn under the geometry. Rebuilt with the scene buffers.
        self._paper_bufs: dict[str, tuple] = {}
        # Vertex runs whose rgba was zeroed (surgical hide): flushed to the
        # existing VBOs with partial writes — never a full scene re-upload.
        self._pending_hide: list[tuple[str, int, int]] = []
        self._view_stack: list[tuple[float, float, float]] = []
        self._zoom_window = False
        self._rubber: Optional[QRubberBand] = None
        self._rubber_origin = QPointF()
        self._overlay_scene: Optional[Scene] = None
        self._overlay_dirty = False
        self._overlay_bufs: dict[str, tuple] = {}
        # Ghost preview (MOVE/COPY/PASTE drag): tessellated ONCE, then only a
        # per-frame translation in the MVP — no rebuild while the mouse moves.
        self._ghost_scene: Optional[Scene] = None
        self._ghost_dirty = False
        self._ghost_bufs: dict[str, tuple] = {}
        self._ghost_offset = (0.0, 0.0)
        # A ghost can also turn or grow about a base point (ROTATE, SCALE).
        self._ghost_base: Optional[tuple[float, float]] = None
        self._ghost_angle = 0.0
        self._ghost_factor = 1.0
        # Stamps: committed MOVE/COPY/PASTE results drawn as the ghost scene
        # at fixed offsets — the pasted geometry costs ZERO re-tessellation
        # until the idle merge folds it into the base scene. One group per
        # scene, many offsets per group (repeated pastes share the buffers).
        self._stamps: list[dict] = []       # {scene, bufs|None, offsets:{key:(dx,dy)}}
        self._retired_stamp_bufs: list[dict] = []   # freed on next paintGL
        # Saved alpha bytes of hidden entities, so undo can un-hide them.
        self._hidden_rgba: dict = {}
        self._sel_press = None  # pending left press in selection mode
        self._hl_lines_cache = None  # (segs, view state, [QLineF])
        # Cursor preferences, read once instead of per frame (the crosshair
        # is drawn on every single paint).
        self._cursorsize = CURSORSIZE_DEFAULT
        self._crosshair_color = None
        self._pickbox_px = PICKBOX_PX
        self.refresh_cursor_prefs()
        self._grip_hover = None  # grip under the cursor, if any
        self._pan_mode = False   # interactive PAN command (open-hand cursor)
        # Status-bar drafting aids: GRID (F7) draws the reference grid under
        # the drawing; LWT toggles on-screen lineweight display.
        self.grid_on = False
        self.lwt_on = True
        self._grid_buf = None    # (vao, vbo, count, key) — rebuilt on view change
        # Interactive tool hook (ToolController): hover/click/preview/markers.
        self.tool_delegate = None
        # MSPACE-active viewport rect (paper world coords) — drawn with the
        # heavy border AutoCAD gives the active viewport. None = paper space.
        self.active_vp_rect = None
        # The projection of the activated viewport, or None on the sheet and
        # in the Model tab. Set by the MainWindow; every overlay this widget
        # draws for the TOOL layer goes through it, because inside a
        # viewport the tools speak model coordinates and the canvas paper.
        self.space_placement = None
        # Rubber rectangle while a selected viewport's grip follows the
        # cursor (move/resize preview). Set by the ToolController.
        self.vp_drag_rect = None

    # -- document hooks -------------------------------------------------------
    def set_scene(self, scene: Optional[Scene]) -> None:
        """Adopt a packed scene; the GL upload happens on the next frame."""
        self._scene = scene
        self._scene_dirty = True
        self._hidden_rgba = {}   # saved alphas referenced the old scene
        self._hidden_images = set()
        self.update()

    # -- stamps (committed ghost geometry, zero re-tessellation) --------------
    def add_stamp(self, key, scene: Scene, dx: float, dy: float) -> None:
        for group in self._stamps:
            if group["scene"] is scene:
                group["offsets"][key] = (dx, dy)
                self.update()
                return
        self._stamps.append(
            {"scene": scene, "bufs": None, "offsets": {key: (dx, dy)}})
        self.update()

    def remove_stamp(self, key) -> bool:
        """Drop one stamped placement. True if it was showing (undo probe)."""
        for group in self._stamps:
            if key in group["offsets"]:
                del group["offsets"][key]
                if not group["offsets"]:
                    self._stamps.remove(group)
                    if group["bufs"]:
                        self._retired_stamp_bufs.append(group["bufs"])
                self.update()
                return True
        return False

    def clear_stamps(self) -> None:
        for group in self._stamps:
            if group["bufs"]:
                self._retired_stamp_bufs.append(group["bufs"])
        self._stamps.clear()
        self.update()

    # -- interactive PAN command (open/closed hand, AutoCAD-style) ------------
    def start_pan_mode(self) -> None:
        self._pan_mode = True
        self._cursor = None            # hide the crosshair; show the hand
        self.setCursor(Qt.OpenHandCursor)
        self.update()

    def stop_pan_mode(self) -> None:
        if not self._pan_mode:
            return
        self._pan_mode = False
        self._panning = False
        self.setCursor(Qt.BlankCursor)
        # PAN ends where the hand was, so that is where the crosshair goes —
        # not back to wherever it was before the command started.
        last = getattr(self, "_pan_last_screen", None)
        if last is not None:
            self._cursor = last
            if self.tool_delegate is not None:
                wx, wy = self.view.screen_to_world(last.x(), last.y())
                self.cursorMoved.emit(wx, wy)
        self.update()

    def set_overlay_scene(self, scene: Optional[Scene]) -> None:
        """Freshly drawn entities, rendered on top of the base scene."""
        self._overlay_scene = scene
        self._overlay_dirty = True
        self.update()

    def set_ghost_scene(self, scene: Optional[Scene]) -> None:
        """The dragged geometry preview; drawn dimmed at the ghost offset."""
        self._ghost_scene = scene
        self._ghost_dirty = True
        self._ghost_offset = (0.0, 0.0)
        self._ghost_base = None
        self._ghost_angle = 0.0
        self._ghost_factor = 1.0
        self.update()

    def set_ghost_offset(self, dx: float, dy: float) -> None:
        """Move the ghost: only the MVP translation changes — free per frame."""
        self._ghost_offset = (dx, dy)
        self._ghost_base = None
        self._ghost_angle = 0.0
        self._ghost_factor = 1.0

    def set_ghost_placement(self, base, angle: float = 0.0,
                            factor: float = 1.0,
                            offset: tuple[float, float] = (0.0, 0.0)) -> None:
        """Turn and/or grow the ghost about ``base`` (world coordinates).

        Same buffers, same cost as a drag: the whole placement rides in the
        MVP, so a ROTATE preview on a 90k-entity selection is as cheap as a
        MOVE preview.
        """
        self._ghost_base = base
        self._ghost_angle = float(angle)
        self._ghost_factor = float(factor)
        self._ghost_offset = offset
        self.update()

    def set_live_viewport(self, live) -> None:
        """Draw the sheet's viewports from a model scene, live.

        ``live`` is a list of ``{"scene", "rect", "base", "factor",
        "offset"}`` — one per viewport, all sharing the one tessellation —
        or None. Panning or zooming inside a floating viewport then costs a
        matrix per viewport instead of a re-tessellation of the whole sheet,
        whose baked copy of that content is hidden while this is on.
        """
        self._live_vp = live
        self._live_vp_dirty = True
        self.update()

    def hide_handles(self, handles) -> None:
        """Make edited entities vanish instantly (alpha 0), no regen.

        The next full regen rebuilds the base scene without them; until then
        this hides their vertices in the existing buffers — a few KB of GPU
        update instead of seconds of regen (surgical display).
        """
        if self._scene is None:
            return
        for image in getattr(self._scene, "images", []):
            if image.handle is not None and image.handle in set(handles):
                self._hidden_images.add(image.handle)
        if not self._scene.handle_ranges:
            return
        touched = False
        for h in handles:
            ranges = self._scene.handle_ranges.get(h, ())
            if not ranges:
                continue
            if h not in self._hidden_rgba:
                # save the alpha bytes so undo can un-hide surgically
                self._hidden_rgba[h] = [
                    (bn, first, count,
                     getattr(self._scene, bn).data["rgba"][
                         first:first + count, 3].copy())
                    for bn, first, count in ranges
                ]
            for batch_name, first, count in ranges:
                getattr(self._scene, batch_name).data["rgba"][
                    first:first + count, 3] = 0
                self._pending_hide.append((batch_name, first, count))
                touched = True
        if touched:
            if not self._scene_bufs:
                # nothing uploaded yet: the full upload will carry the zeros
                self._scene_dirty = True
            elif len(self._pending_hide) > 4096:
                # mass erase: one full re-upload beats thousands of writes
                self._pending_hide.clear()
                self._scene_dirty = True
            self.update()

    def unhide_handles(self, handles) -> None:
        """Restore entities hidden by ``hide_handles`` (undo of a stamped
        MOVE): the base-scene copy at the original position is still valid."""
        touched = False
        for h in handles:
            if h in self._hidden_images:
                self._hidden_images.discard(h)
                touched = True
            saved = self._hidden_rgba.pop(h, None)
            if not saved:
                continue
            for batch_name, first, count, alpha in saved:
                getattr(self._scene, batch_name).data["rgba"][
                    first:first + count, 3] = alpha
                self._pending_hide.append((batch_name, first, count))
                touched = True
        if touched:
            if not self._scene_bufs:
                self._scene_dirty = True
            elif len(self._pending_hide) > 4096:
                self._pending_hide.clear()
                self._scene_dirty = True
            self.update()

    # -- view stack (ZOOM Previous) -------------------------------------------
    def push_view(self) -> None:
        self._view_stack.append((self.view.cx, self.view.cy, self.view.scale))
        del self._view_stack[:-32]  # bounded, AutoCAD-style

    def zoom_previous(self) -> bool:
        if not self._view_stack:
            return False
        self.view.cx, self.view.cy, self.view.scale = self._view_stack.pop()
        self.update()
        return True

    def start_zoom_window(self) -> None:
        """Next left-drag on the canvas picks the zoom window."""
        self._zoom_window = True
        self.setCursor(Qt.CrossCursor)

    def scene_bounds(self) -> tuple[float, float, float, float]:
        """World bounds to fit on Zoom Extents.

        On a layout tab the paper sheet counts as content: Zoom Extents on an
        empty layout frames the sheet (AutoCAD behavior), and geometry that
        hangs off the paper widens the frame. Without a document (or with an
        empty one) a human-scale frame around the origin keeps the canvas
        navigable.
        """
        boxes = []
        if self._scene is not None:
            if not self._scene.is_empty:
                min_x, min_y, max_x, max_y = self._scene.extents
                if max_x > min_x or max_y > min_y:
                    boxes.append((min_x, min_y, max_x, max_y))
            if self._scene.paper is not None:
                boxes.append(self._scene.paper["sheet"])
        if boxes:
            return (min(b[0] for b in boxes), min(b[1] for b in boxes),
                    max(b[2] for b in boxes), max(b[3] for b in boxes))
        return (-50.0, -50.0, 50.0, 50.0)

    def zoom_extents(self) -> None:
        self.push_view()
        self.view.zoom_extents(*self.scene_bounds())
        self.update()

    # -- GL lifecycle ---------------------------------------------------------
    def initializeGL(self) -> None:
        self._gl = QOpenGLFunctions(self.context())
        self._gl.initializeOpenGLFunctions()
        self._gl.glClearColor(*BACKGROUND, 1.0)

        self._program = self._compile_program("line.vert", "line.frag")
        self._loc_mvp = self._program.uniformLocation("u_mvp")
        self._thick_program = self._compile_program("thick.vert", "line.frag")
        self._loc_thick_mvp = self._thick_program.uniformLocation("u_mvp")
        self._loc_half_world = self._thick_program.uniformLocation("u_half_world")
        self._image_program = self._compile_program("image.vert", "image.frag")
        self._loc_image_mvp = self._image_program.uniformLocation("u_mvp")

        data = _axes_vertices()
        self._axes_vao, self._axes_vbo, self._axes_count = self._make_vao(data)
        # GL objects live in Python attributes, so without this their C++
        # destructors run whenever the GC gets to them -- typically at window
        # destruction or interpreter exit, with no current context. That was
        # a double free ("821 passed ... Aborted (core dumped)" on CI: every
        # test green, then a crash destroying the leftover windows). Qt's
        # documented pattern: release everything while the context is still
        # alive, from its own aboutToBeDestroyed.
        self.context().aboutToBeDestroyed.connect(self._release_gl)
        # A scene set before the context existed uploads on the first frame.
        if self._scene is not None:
            self._scene_dirty = True

    def _make_vao(self, data: np.ndarray) -> tuple:
        """Upload standard-format vertices (12 B: pos f32x2 + rgba u8x4)."""
        loc_pos = self._program.attributeLocation("a_pos")
        loc_color = self._program.attributeLocation("a_color")
        vao = QOpenGLVertexArrayObject(self)
        vao.create()
        vao.bind()
        vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        vbo.create()
        vbo.bind()
        raw = data.tobytes()
        vbo.allocate(raw, len(raw))
        stride = VERTEX_DTYPE.itemsize
        self._program.bind()
        self._program.enableAttributeArray(loc_pos)
        self._program.setAttributeBuffer(loc_pos, GL_FLOAT, 0, 2, stride)
        self._program.enableAttributeArray(loc_color)
        # Qt normalizes integer attribute types: u8 255 -> 1.0 in the vec4.
        self._program.setAttributeBuffer(loc_color, GL_UNSIGNED_BYTE, 8, 4, stride)
        self._program.release()
        vao.release()
        vbo.release()
        return vao, vbo, len(data)

    def _make_thick_vao(self, data: np.ndarray) -> tuple:
        """Upload thick-format vertices (20 B: pos + normal f32x2 + rgba u8x4)."""
        prog = self._thick_program
        loc_pos = prog.attributeLocation("a_pos")
        loc_normal = prog.attributeLocation("a_normal")
        loc_color = prog.attributeLocation("a_color")
        vao = QOpenGLVertexArrayObject(self)
        vao.create()
        vao.bind()
        vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        vbo.create()
        vbo.bind()
        raw = data.tobytes()
        vbo.allocate(raw, len(raw))
        stride = THICK_DTYPE.itemsize
        prog.bind()
        prog.enableAttributeArray(loc_pos)
        prog.setAttributeBuffer(loc_pos, GL_FLOAT, 0, 2, stride)
        prog.enableAttributeArray(loc_normal)
        prog.setAttributeBuffer(loc_normal, GL_FLOAT, 8, 2, stride)
        prog.enableAttributeArray(loc_color)
        prog.setAttributeBuffer(loc_color, GL_UNSIGNED_BYTE, 16, 4, stride)
        prog.release()
        vao.release()
        vbo.release()
        return vao, vbo, len(data)

    def _release_gl(self) -> None:
        """Destroy every GL object while the context can still say goodbye."""
        self.makeCurrent()
        try:
            holders = [self._scene_bufs, self._paper_bufs,
                       self._overlay_bufs, self._ghost_bufs]
            for bufs in holders:
                for vao, vbo, *_ in bufs.values():
                    vbo.destroy()
                    vao.destroy()
                bufs.clear()
            for tex, vao, vbo, _group, _handle in self._image_bufs:
                tex.destroy()
                vbo.destroy()
                vao.destroy()
            self._image_bufs.clear()
            for group in self._stamps:
                for vao, vbo, *_ in (group.get("bufs") or {}).values():
                    vbo.destroy()
                    vao.destroy()
                group["bufs"] = None
            for bufs in self._retired_stamp_bufs:
                for vao, vbo, *_ in bufs.values():
                    vbo.destroy()
                    vao.destroy()
            self._retired_stamp_bufs.clear()
            if getattr(self, "_axes_vbo", None) is not None:
                self._axes_vbo.destroy()
                self._axes_vao.destroy()
                self._axes_vbo = self._axes_vao = None
        finally:
            self.doneCurrent()

    def _upload_scene(self) -> None:
        """(Re)build the scene buffers. Requires a current GL context."""
        for vao, vbo, _count in self._scene_bufs.values():
            vbo.destroy()
            vao.destroy()
        self._scene_bufs.clear()
        for vao, vbo, _count in self._paper_bufs.values():
            vbo.destroy()
            vao.destroy()
        self._paper_bufs.clear()
        for tex, vao, vbo, _group, _handle in self._image_bufs:
            tex.destroy()
            vbo.destroy()
            vao.destroy()
        self._image_bufs.clear()
        self._scene_dirty = False
        self._pending_hide.clear()  # a full upload carries any zeroed rgba
        if self._scene is None:
            return
        for image in getattr(self._scene, "images", []):
            self._image_bufs.append(self._make_image_buf(image))
        if self._scene.paper is not None:
            tris, lines = _paper_vertices(self._scene.paper, self._scene.origin)
            self._paper_bufs["triangles"] = self._make_vao(tris)
            if len(lines):
                self._paper_bufs["lines"] = self._make_vao(lines)
        batches: dict[str, Batch] = {
            "triangles": self._scene.triangles,
            "lines": self._scene.lines,
            "points": self._scene.points,
        }
        for name, batch in batches.items():
            if batch.vertex_count:
                self._scene_bufs[name] = self._make_vao(batch.data)
        if self._scene.thick.vertex_count:
            self._scene_bufs["thick"] = self._make_thick_vao(self._scene.thick.data)

    def _flush_hidden_ranges(self) -> None:
        """Partial VBO writes for surgically hidden entities.

        Re-uploading the whole scene on every hide froze big drawings for a
        beat on each MOVE/ERASE/grip grab; the hidden runs are a few KB.
        """
        pending, self._pending_hide = self._pending_hide, []
        if self._scene is None:
            return
        for batch_name, first, count in pending:
            buf = self._scene_bufs.get(batch_name)
            if buf is None:
                continue
            _vao, vbo, _n = buf
            data = getattr(self._scene, batch_name).data
            raw = data[first:first + count].tobytes()
            vbo.bind()
            vbo.write(first * data.dtype.itemsize, raw, len(raw))
            vbo.release()

    def _make_image_buf(self, image) -> tuple:
        """Texture + quad VBO for one raster IMAGE (pos f32x2 + uv f32x2)."""
        from PySide6.QtOpenGL import QOpenGLTexture

        pixels = np.ascontiguousarray(image.pixels)
        height, width = pixels.shape[:2]
        tex = QOpenGLTexture(QOpenGLTexture.Target2D)
        tex.create()
        tex.setSize(width, height)
        tex.setFormat(QOpenGLTexture.RGBA8_UNorm)
        tex.allocateStorage()
        tex.setData(QOpenGLTexture.RGBA, QOpenGLTexture.UInt8,
                    pixels.tobytes())
        tex.setMinMagFilters(QOpenGLTexture.LinearMipMapLinear,
                             QOpenGLTexture.Linear)
        tex.setWrapMode(QOpenGLTexture.ClampToEdge)
        tex.generateMipMaps()

        # The wcs transform maps pixel (0,0) to where the picture's BOTTOM
        # row belongs (ezdxf's own PyQt backend flips the array before
        # applying it). The texture is uploaded unflipped — row 0 = the
        # picture's top — so v runs 1 at pixel y=0 and 0 at pixel y=h.
        c = image.corners
        quad = np.array([
            [c[0][0], c[0][1], 0.0, 1.0],
            [c[1][0], c[1][1], 1.0, 1.0],
            [c[2][0], c[2][1], 1.0, 0.0],
            [c[0][0], c[0][1], 0.0, 1.0],
            [c[2][0], c[2][1], 1.0, 0.0],
            [c[3][0], c[3][1], 0.0, 0.0],
        ], dtype=np.float32)
        vao = QOpenGLVertexArrayObject(self)
        vao.create()
        vao.bind()
        vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        vbo.create()
        vbo.bind()
        raw = quad.tobytes()
        vbo.allocate(raw, len(raw))
        prog = self._image_program
        prog.bind()
        prog.enableAttributeArray(0)
        prog.setAttributeBuffer(0, GL_FLOAT, 0, 2, 16)
        prog.enableAttributeArray(1)
        prog.setAttributeBuffer(1, GL_FLOAT, 8, 2, 16)
        prog.release()
        vao.release()
        vbo.release()
        return (tex, vao, vbo, image.group, image.handle)

    def show_image(self, handle) -> None:
        """Un-hide one raster quad (hide_handles hides frame AND pixels)."""
        self._hidden_images.discard(handle)
        self.update()

    def update_image_quad(self, handle, corners_wcs) -> None:
        """Move/resize one raster IMAGE without a regen.

        The texture never changes when an image is dragged or resized —
        only the four corners of its quad do. Rewriting those 6 vertices
        replaces what used to be a full re-tessellation of the drawing
        (9.4 s on a real plan for one grip drop).
        """
        if self._scene is None:
            return
        ox, oy = self._scene.origin
        c = np.array([(x - ox, y - oy) for x, y in corners_wcs],
                     dtype=np.float32)
        for image in getattr(self._scene, "images", []):
            if image.handle == handle:
                image.corners = c      # survives a later full re-upload
                break
        else:
            return
        quad = np.array([
            [c[0][0], c[0][1], 0.0, 1.0],
            [c[1][0], c[1][1], 1.0, 1.0],
            [c[2][0], c[2][1], 1.0, 0.0],
            [c[0][0], c[0][1], 0.0, 1.0],
            [c[2][0], c[2][1], 1.0, 0.0],
            [c[3][0], c[3][1], 0.0, 0.0],
        ], dtype=np.float32)
        for _tex, _vao, vbo, _group, h in self._image_bufs:
            if h == handle:
                self.makeCurrent()
                vbo.bind()
                raw = quad.tobytes()
                vbo.write(0, raw, len(raw))
                vbo.release()
                self.doneCurrent()
                break
        self.update()

    def _draw_images(self, gl, mvp, front: bool) -> None:
        """The raster quads: group <= 0 under the vectors, > 0 over them."""
        if not self._image_bufs:
            return
        prog = self._image_program
        prog.bind()
        prog.setUniformValue(self._loc_image_mvp, mvp)
        for tex, vao, _vbo, group, handle in self._image_bufs:
            if (group > 0) != front or handle in self._hidden_images:
                continue
            tex.bind(0)
            prog.setUniformValue("u_tex", 0)
            vao.bind()
            gl.glDrawArrays(GL_TRIANGLES, 0, 6)
            vao.release()
            tex.release(0)
        prog.release()

    def _compile_program(self, vert: str, frag: str) -> QOpenGLShaderProgram:
        prog = QOpenGLShaderProgram(self)
        prog.addShaderFromSourceFile(QOpenGLShader.Vertex, str(SHADER_DIR / vert))
        prog.addShaderFromSourceFile(QOpenGLShader.Fragment, str(SHADER_DIR / frag))
        if not prog.link():
            raise RuntimeError(f"shader link failed: {prog.log()}")
        return prog

    def resizeEvent(self, event) -> None:
        # Tracked here and not in resizeGL: resizeEvent always fires, even on
        # platforms without a GL context (CI's offscreen runner), keeping the
        # view transform testable headless.
        super().resizeEvent(event)
        self.view.width = max(self.width(), 1)
        self.view.height = max(self.height(), 1)

    def _mvp(self, ox: float = 0.0, oy: float = 0.0,
             space: bool = False) -> QMatrix4x4:
        """World -> clip for vertices stored relative to origin (ox, oy).

        The subtraction (view center - vertex origin) happens here in float64;
        both operands are large (UTM), the difference is small, and only the
        small number reaches the float32 matrix.

        ``space=True`` means the vertices are in the CURRENT space, which
        inside an activated viewport is the model: the viewport's projection
        is inserted between them and the view. The sheet's own scene never
        passes it, which is why this is a flag and not the default.
        """
        kx, ky, cx, cy = self.view.ndc_factors()
        m = QMatrix4x4()
        m.scale(kx, ky, 1.0)
        place = self.space_placement if space else None
        if place:
            self._space_chain(m, cx, cy, ox, oy)
            return m
        m.translate(-(cx - ox), -(cy - oy), 0.0)
        return m

    def _space_chain(self, m: QMatrix4x4, cx: float, cy: float,
                     ox: float, oy: float) -> None:
        """Append "project the current space onto the paper" to ``m``.

        Every large subtraction is done here in float64 -- the view centre
        against the viewport's paper position, and the vertex origin against
        the view centre of the model -- so the float32 matrix only ever sees
        small numbers. A UTM drawing seen through a viewport is exactly the
        case where the naive chain loses millimetres.
        """
        place = self.space_placement
        bx, by = place["base"]
        offx, offy = place["offset"]
        f = place["factor"]
        angle = place.get("angle", 0.0) or 0.0
        m.translate(-(cx - bx - offx), -(cy - by - offy), 0.0)
        if angle:
            m.rotate(angle, 0.0, 0.0, 1.0)
        m.scale(f, f, 1.0)
        m.translate(ox - bx, oy - by, 0.0)

    def space_scissor(self, gl) -> bool:
        """Clip GL drawing to the active viewport's frame. True when set."""
        place = self.space_placement
        if not place:
            return False
        x0, y0, x1, y1 = place["rect"]
        sx0, sy0 = self.view.world_to_screen(x0, y1)
        sx1, sy1 = self.view.world_to_screen(x1, y0)
        dpr = self.devicePixelRatioF()
        px, py = int(sx0 * dpr), int(sy0 * dpr)
        pw, ph = int((sx1 - sx0) * dpr), int((sy1 - sy0) * dpr)
        if pw <= 0 or ph <= 0:
            return False
        gl.glEnable(GL_SCISSOR_TEST)
        gl.glScissor(px, int(self.height() * dpr) - py - ph, pw, ph)
        return True

    def _mvp_about(self, ox: float, oy: float, base, angle: float,
                   factor: float, dx: float = 0.0, dy: float = 0.0,
                   space: bool = False):
        """World -> clip with the ghost turned/grown about ``base``.

        A stored vertex v sits at ``v + origin``; the placement sends it to
        ``R*(v + origin - base)*f + base + offset``, which is exactly the
        chain of translations below (QMatrix4x4 post-multiplies, so it reads
        outermost first).
        """
        kx, ky, cx, cy = self.view.ndc_factors()
        bx, by = base
        m = QMatrix4x4()
        m.scale(kx, ky, 1.0)
        if space and self.space_placement:
            # the placement lands the *base* point, then the ghost turns
            # and grows about it as usual
            self._space_chain(m, cx, cy, bx + dx, by + dy)
        else:
            m.translate(-(cx - bx - dx), -(cy - by - dy), 0.0)
        if angle:
            m.rotate(angle, 0.0, 0.0, 1.0)
        if factor != 1.0:
            m.scale(factor, factor, 1.0)
        m.translate(ox - bx, oy - by, 0.0)
        return m

    def paintGL(self) -> None:
        gl = self._gl
        # Re-establish state every frame: the QPainter overlay below disables
        # GL state behind our back and Wayland shows stale memory otherwise.
        gl.glDisable(GL_DEPTH_TEST)
        gl.glEnable(GL_BLEND)
        gl.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        if self._scene is not None and self._scene.background is not None:
            gl.glClearColor(*self._scene.background)
        else:
            gl.glClearColor(*BACKGROUND, 1.0)
        gl.glClear(GL_COLOR_BUFFER_BIT)

        if self._retired_stamp_bufs:
            for bufs in self._retired_stamp_bufs:
                for vao, vbo, _count in bufs.values():
                    vbo.destroy()
                    vao.destroy()
            self._retired_stamp_bufs.clear()
        if self._scene_dirty:
            self._upload_scene()
        elif self._pending_hide:
            self._flush_hidden_ranges()
        if self._overlay_dirty:
            self._upload_overlay()
        if self._ghost_dirty:
            self._upload_ghost()

        self._program.bind()

        on_paper = self._scene is not None and self._scene.paper is not None
        if on_paper and self._paper_bufs:
            # The sheet goes under everything: shadow + white paper, then the
            # border and the dashed printable margin.
            self._program.setUniformValue(self._loc_mvp,
                                          self._mvp(*self._scene.origin))
            for name, mode in (("triangles", GL_TRIANGLES), ("lines", GL_LINES)):
                buf = self._paper_bufs.get(name)
                if buf is None:
                    continue
                vao, _vbo, count = buf
                vao.bind()
                gl.glDrawArrays(mode, 0, count)
                vao.release()

        if self.grid_on:
            self._draw_grid(gl)

        if not on_paper:
            # World axes are a model-space reference; on a layout tab they
            # would just streak across the sheet.
            self._program.setUniformValue(self._loc_mvp, self._mvp())
            self._axes_vao.bind()
            gl.glDrawArrays(GL_LINES, 0, self._axes_count)
            self._axes_vao.release()

        if self._scene is not None and self._scene_bufs:
            scene_mvp = self._mvp(*self._scene.origin)
            view_rect = self._view_world_rect()
            self._program.release()
            self._draw_images(gl, scene_mvp, front=False)
            self._program.bind()
            self._program.setUniformValue(self._loc_mvp, scene_mvp)
            # Fills first, then lines and points on top of them.
            for name, mode in (("triangles", GL_TRIANGLES),
                               ("lines", GL_LINES),
                               ("points", GL_POINTS)):
                buf = self._scene_bufs.get(name)
                if buf is None:
                    continue
                vao, _vbo, _count = buf
                batch: Batch = getattr(self._scene, name)
                vao.bind()
                for first, count in batch.visible_runs(
                        view_rect, self.view.scale, MIN_TEXT_PX):
                    gl.glDrawArrays(mode, first, count)
                vao.release()
            self._program.release()
            self._draw_thick(gl, scene_mvp, view_rect,
                             self._scene_bufs.get("thick"), self._scene.thick)
            self._draw_images(gl, scene_mvp, front=True)
        else:
            self._program.release()

        if self._live_vp is not None:
            self._draw_live_viewport(gl)

        if self._stamps:
            # Everything below draws the CURRENT space: inside a viewport
            # that is the model, so it goes through the projection and is
            # clipped to the viewport's frame like the content it joins.
            scissored = self.space_scissor(gl)
            self._program.bind()
            for group in self._stamps:
                if group["bufs"] is None:
                    group["bufs"] = {}
                    for name in ("triangles", "lines", "points"):
                        batch: Batch = getattr(group["scene"], name)
                        if batch.vertex_count:
                            group["bufs"][name] = self._make_vao(batch.data)
                    if group["scene"].thick.vertex_count:
                        group["bufs"]["thick"] = self._make_thick_vao(
                            group["scene"].thick.data)
                ox, oy = group["scene"].origin
                for dx, dy in group["offsets"].values():
                    self._program.bind()
                    self._program.setUniformValue(
                        self._loc_mvp, self._mvp(ox + dx, oy + dy, space=True))
                    for name, mode in (("triangles", GL_TRIANGLES),
                                       ("lines", GL_LINES),
                                       ("points", GL_POINTS)):
                        buf = group["bufs"].get(name)
                        if buf is None:
                            continue
                        vao, _vbo, count = buf
                        vao.bind()
                        gl.glDrawArrays(mode, 0, count)
                        vao.release()
                    self._program.release()
                    self._draw_thick(gl, self._mvp(ox + dx, oy + dy,
                                                    space=True), None,
                                     group["bufs"].get("thick"),
                                     group["scene"].thick)
            self._program.release()
            if scissored:
                gl.glDisable(GL_SCISSOR_TEST)

        if self._overlay_scene is not None and self._overlay_bufs:
            scissored = self.space_scissor(gl)
            overlay_mvp = self._mvp(*self._overlay_scene.origin, space=True)
            self._program.bind()
            self._program.setUniformValue(self._loc_mvp, overlay_mvp)
            for name, mode in (("triangles", GL_TRIANGLES),
                               ("lines", GL_LINES),
                               ("points", GL_POINTS)):
                buf = self._overlay_bufs.get(name)
                if buf is None:
                    continue
                vao, _vbo, count = buf
                vao.bind()
                gl.glDrawArrays(mode, 0, count)
                vao.release()
            self._program.release()
            self._draw_thick(gl, overlay_mvp, None,
                             self._overlay_bufs.get("thick"),
                             self._overlay_scene.thick)
            if scissored:
                gl.glDisable(GL_SCISSOR_TEST)

        if self._ghost_scene is not None and self._ghost_bufs:
            # The ghost translates by shifting the vertex origin in the MVP:
            # same buffers every frame, only this uniform changes.
            ox, oy = self._ghost_scene.origin
            dx, dy = self._ghost_offset
            scissored = self.space_scissor(gl)
            if self._ghost_base is None:
                ghost_mvp = self._mvp(ox + dx, oy + dy, space=True)
            else:
                ghost_mvp = self._mvp_about(ox, oy, self._ghost_base,
                                            self._ghost_angle,
                                            self._ghost_factor, dx, dy,
                                            space=True)
            self._program.bind()
            self._program.setUniformValue(self._loc_mvp, ghost_mvp)
            for name, mode in (("triangles", GL_TRIANGLES),
                               ("lines", GL_LINES),
                               ("points", GL_POINTS)):
                buf = self._ghost_bufs.get(name)
                if buf is None:
                    continue
                vao, _vbo, count = buf
                vao.bind()
                gl.glDrawArrays(mode, 0, count)
                vao.release()
            self._program.release()
            self._draw_thick(gl, ghost_mvp, None,
                             self._ghost_bufs.get("thick"),
                             self._ghost_scene.thick)
            if scissored:
                gl.glDisable(GL_SCISSOR_TEST)

        self._paint_overlay()

    def _draw_live_viewport(self, gl) -> None:
        """The active viewport's model content, scissored to its frame.

        Everything about the placement rides in the matrix — the same trick
        the drag ghost uses — so a pan tick is a uniform update instead of a
        200 ms rebuild of the sheet.
        """
        placements = self._live_vp
        if not placements:
            return
        scene = placements[0]["scene"]
        if getattr(self, "_live_vp_dirty", False) or not getattr(
                self, "_live_vp_bufs", None):
            for vao, vbo, _c in (getattr(self, "_live_vp_bufs", None) or {}).values():
                vbo.destroy()
                vao.destroy()
            self._live_vp_bufs = {}
            for name in ("triangles", "lines", "points"):
                batch = getattr(scene, name)
                if batch.vertex_count:
                    self._live_vp_bufs[name] = self._make_vao(batch.data)
            if scene.thick.vertex_count:
                self._live_vp_bufs["thick"] = self._make_thick_vao(
                    scene.thick.data)
            self._live_vp_dirty = False
        if not self._live_vp_bufs:
            return

        gl.glEnable(GL_SCISSOR_TEST)
        for live in placements:
            self._draw_one_live_viewport(gl, live, scene)
        gl.glDisable(GL_SCISSOR_TEST)

    def _draw_one_live_viewport(self, gl, live, scene) -> None:
        # Clip to the viewport's frame, in device pixels with y flipped —
        # GL counts scissor rows from the bottom.
        x0, y0, x1, y1 = live["rect"]
        sx0, sy0 = self.view.world_to_screen(x0, y1)
        sx1, sy1 = self.view.world_to_screen(x1, y0)
        dpr = self.devicePixelRatioF()
        px, py = int(sx0 * dpr), int(sy0 * dpr)
        pw, ph = int((sx1 - sx0) * dpr), int((sy1 - sy0) * dpr)
        if pw <= 0 or ph <= 0:
            return
        gl.glScissor(px, int(self.height() * dpr) - py - ph, pw, ph)
        ox, oy = scene.origin
        mvp = self._mvp_about(ox, oy, live["base"], 0.0, live["factor"],
                              live["offset"][0], live["offset"][1])
        self._program.bind()
        self._program.setUniformValue(self._loc_mvp, mvp)
        for name, mode in (("triangles", GL_TRIANGLES), ("lines", GL_LINES),
                           ("points", GL_POINTS)):
            buf = self._live_vp_bufs.get(name)
            if buf is None:
                continue
            vao, _vbo, count = buf
            vao.bind()
            gl.glDrawArrays(mode, 0, count)
            vao.release()
        self._program.release()
        self._draw_thick(gl, mvp, None, self._live_vp_bufs.get("thick"),
                         scene.thick)

    def _upload_overlay(self) -> None:
        for vao, vbo, _count in self._overlay_bufs.values():
            vbo.destroy()
            vao.destroy()
        self._overlay_bufs.clear()
        self._overlay_dirty = False
        if self._overlay_scene is None:
            return
        for name in ("triangles", "lines", "points"):
            batch: Batch = getattr(self._overlay_scene, name)
            if batch.vertex_count:
                self._overlay_bufs[name] = self._make_vao(batch.data)
        # Thick quads too: an entity on a heavyweight layer (0.8 mm columns)
        # otherwise vanishes between the edit and the deferred regen.
        if self._overlay_scene.thick.vertex_count:
            self._overlay_bufs["thick"] = self._make_thick_vao(
                self._overlay_scene.thick.data)

    def _upload_ghost(self) -> None:
        for vao, vbo, _count in self._ghost_bufs.values():
            vbo.destroy()
            vao.destroy()
        self._ghost_bufs.clear()
        self._ghost_dirty = False
        if self._ghost_scene is None:
            return
        for name in ("triangles", "lines", "points"):
            batch: Batch = getattr(self._ghost_scene, name)
            if batch.vertex_count:
                data = batch.data.copy()
                # dim so the ghost reads as a preview, not committed geometry
                data["rgba"][:, 3] = (data["rgba"][:, 3] * 0.55).astype("u1")
                self._ghost_bufs[name] = self._make_vao(data)
        if self._ghost_scene.thick.vertex_count:
            data = self._ghost_scene.thick.data.copy()
            data["rgba"][:, 3] = (data["rgba"][:, 3] * 0.55).astype("u1")
            self._ghost_bufs["thick"] = self._make_thick_vao(data)

    # Grid colors: faint minor lines, slightly brighter every 5th (major).
    GRID_MINOR = (52, 58, 66, 255)
    GRID_MAJOR = (72, 80, 92, 255)
    #: over a light canvas (white/cream model background) the dark-canvas
    #: grays vanish; AutoCAD's grid stays visible on white too.
    GRID_MINOR_LIGHT = (214, 214, 214, 255)
    GRID_MAJOR_LIGHT = (189, 189, 189, 255)

    def _grid_spacing(self) -> float:
        """Adaptive 1-2-5 spacing that keeps cells ~25-90 px on screen."""
        import math
        raw = 35.0 / max(self.view.scale, 1e-12)
        exp = math.floor(math.log10(raw)) if raw > 0 else 0
        for m in (1.0, 2.0, 5.0, 10.0):
            s = m * 10.0 ** exp
            if s * self.view.scale >= 25.0:
                return s
        return 10.0 ** (exp + 1)

    def _draw_grid(self, gl) -> None:
        """Reference grid under the drawing (GRID / F7), BricsCAD-style lines.

        A tiny VBO (a few hundred vertices) keyed on the snapped view rect:
        static under zoom-stable panning, rebuilt only when the visible cell
        range changes — never per frame while idle.
        """
        x0, y0, x1, y1 = self._view_world_rect()
        s = self._grid_spacing()
        i0, i1 = int(np.floor(x0 / s)), int(np.ceil(x1 / s))
        j0, j1 = int(np.floor(y0 / s)), int(np.ceil(y1 / s))
        light = self._light_background()
        key = (s, i0, i1, j0, j1, light)
        if self._grid_buf is None or self._grid_buf[3] != key:
            if self._grid_buf is not None:
                self._grid_buf[0].destroy()
                self._grid_buf[1].destroy()
            # origin at the rect centre keeps float32 coordinates small (UTM)
            ox, oy = (i0 + i1) / 2.0 * s, (j0 + j1) / 2.0 * s
            # endpoints snapped to the cell range too, so the buffer is fully
            # determined by `key` (stable while panning within the same cells)
            gy0, gy1 = j0 * s - oy, j1 * s - oy
            gx0, gx1 = i0 * s - ox, i1 * s - ox
            major = self.GRID_MAJOR_LIGHT if light else self.GRID_MAJOR
            minor = self.GRID_MINOR_LIGHT if light else self.GRID_MINOR
            verts = []
            for i in range(i0, i1 + 1):
                color = major if i % 5 == 0 else minor
                verts.append((i * s - ox, gy0, color))
                verts.append((i * s - ox, gy1, color))
            for j in range(j0, j1 + 1):
                color = major if j % 5 == 0 else minor
                verts.append((gx0, j * s - oy, color))
                verts.append((gx1, j * s - oy, color))
            data = np.zeros(len(verts), dtype=VERTEX_DTYPE)
            for k, (px, py, color) in enumerate(verts):
                data["pos"][k] = (px, py)
                data["rgba"][k] = color
            vao, vbo, count = self._make_vao(data)
            self._grid_origin = (ox, oy)
            self._grid_buf = (vao, vbo, count, key)
        vao, _vbo, count, _key = self._grid_buf
        self._program.setUniformValue(self._loc_mvp,
                                      self._mvp(*self._grid_origin))
        vao.bind()
        gl.glDrawArrays(GL_LINES, 0, count)
        vao.release()

    def _view_world_rect(self) -> tuple[float, float, float, float]:
        x0, y1 = self.view.screen_to_world(0.0, 0.0)          # top-left
        x1, y0 = self.view.screen_to_world(self.width(), self.height())
        return (x0, y0, x1, y1)

    def _draw_thick(self, gl, mvp: QMatrix4x4, view_rect, buf, batch) -> None:
        """Thick lineweight quads: one draw per visible weight range.

        ``view_rect`` of None skips culling — the overlay/ghost/stamp scenes
        are small and their bounds are not view-aligned once offset.
        """
        if buf is None:
            return
        vao, _vbo, _count = buf
        prog = self._thick_program
        prog.bind()
        prog.setUniformValue(self._loc_thick_mvp, mvp)
        vao.bind()
        # No run merging here: u_half_world changes per lineweight.
        for i, rng in enumerate(batch.ranges):
            if view_rect is not None and batch.bounds is not None:
                x0, y0, x1, y1 = view_rect
                bx0, by0, bx1, by1 = batch.bounds[i]
                if bx0 > x1 or bx1 < x0 or by0 > y1 or by1 < y0:
                    continue
            # LWT off: draw thick entities as hairlines (AutoCAD's LWT toggle)
            px = max(1.0, rng.lineweight * PX_PER_MM) if self.lwt_on else 1.0
            half_world = (px / 2.0) / self.view.scale
            prog.setUniformValue1f(self._loc_half_world, half_world)
            gl.glDrawArrays(GL_TRIANGLES, rng.first, rng.count)
        vao.release()
        prog.release()

    # -- the current space vs the paper the canvas draws ----------------------
    def space_affine(self):
        """(a, b, c, d, tx, ty): a CURRENT-SPACE point -> paper coordinates.

        ``px = a*x + b*y + tx``, ``py = c*x + d*y + ty``. The identity on the
        sheet and in the Model tab, the viewport's projection inside MSPACE.
        """
        place = self.space_placement
        if not place:
            return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        f = place["factor"]
        bx, by = place["base"]
        ox, oy = place["offset"]
        angle = math.radians(place.get("angle", 0.0) or 0.0)
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        a, b = f * cos_a, -f * sin_a
        c, d = f * sin_a, f * cos_a
        # scale/turn about base, then shift: p = R*f*(x - base) + base + off
        return (a, b, c, d,
                bx + ox - (a * bx + b * by),
                by + oy - (c * bx + d * by))

    def _space_to_screen(self, x: float, y: float):
        """A point of the current space -> pixels, through the projection."""
        if self.space_placement:
            a, b, c, d, tx, ty = self.space_affine()
            x, y = a * x + b * y + tx, c * x + d * y + ty
        return self.view.world_to_screen(x, y)

    def _space_scale(self) -> float:
        """Pixels per unit of the CURRENT space (a model unit is smaller on
        the sheet by the viewport's scale)."""
        if self.space_placement:
            return self.view.scale * self.space_placement["factor"]
        return self.view.scale

    # -- overlay (QPainter, logical pixels) -----------------------------------
    def _paint_overlay(self) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.active_vp_rect is not None:
            # MSPACE: the active viewport gets AutoCAD's heavy border.
            x0, y0, x1, y1 = self.active_vp_rect
            sx0, sy0 = self.view.world_to_screen(x0, y1)   # top-left
            sx1, sy1 = self.view.world_to_screen(x1, y0)
            p.setPen(QPen(QColor(20, 20, 20), 3))
            p.drawRect(sx0, sy0, sx1 - sx0, sy1 - sy0)
        if self.vp_drag_rect is not None:
            # move/resize preview of the selected viewport (grip drag)
            x0, y0, x1, y1 = self.vp_drag_rect
            sx0, sy0 = self.view.world_to_screen(x0, y1)
            sx1, sy1 = self.view.world_to_screen(x1, y0)
            p.setPen(QPen(self.HIGHLIGHT_COLOR, 1, Qt.DashLine))
            p.drawRect(sx0, sy0, sx1 - sx0, sy1 - sy0)
        self._draw_ucs_icon(p)
        if self.tool_delegate is not None:
            self._draw_selection(p)
            self._draw_grips(p)
            if self.tool_delegate.active():
                self._draw_tool_preview(p)
            grip_marker = getattr(self.tool_delegate,
                                  "grip_align_marker", None)
            if grip_marker is not None:
                mx, my = self._space_to_screen(*grip_marker)
                half = self.MARKER_SIZE / 2.0
                p.save()
                p.setPen(QPen(QColor(80, 220, 80), 2))
                p.drawRect(mx - half, my - half, 2 * half, 2 * half)
                p.restore()
            grip_dim = getattr(self.tool_delegate, "grip_dim_preview", None)
            if grip_dim is not None:
                color = (QColor(90, 90, 90) if self._light_background()
                         else QColor(200, 200, 200))
                p.setPen(QPen(color, 1, Qt.DashLine))
                if "text_at" in grip_dim:
                    tx, ty = self._space_to_screen(*grip_dim["text_at"])
                    p.setPen(QPen(color))
                    p.drawText(QPointF(tx, ty), grip_dim["text"])
                else:
                    self._draw_dim_preview(p, grip_dim, color)
            self._draw_live_text(p)
        if self._cursor is not None and not self._panning:
            self._draw_crosshair(p, self._cursor, self._cursor_mode())
        p.end()

    # AutoSnap marker glyphs (classic yellow), drawn in logical pixels.
    MARKER_COLOR = QColor(255, 220, 0)
    MARKER_SIZE = 10
    # Selection visuals (AutoCAD colors): dashed highlight, blue window,
    # green crossing.
    HIGHLIGHT_COLOR = QColor(60, 170, 255)
    WINDOW_FILL = QColor(70, 130, 255, 50)
    WINDOW_BORDER = QColor(90, 140, 255)
    CROSSING_FILL = QColor(80, 220, 110, 50)
    CROSSING_BORDER = QColor(90, 220, 120)

    GRIP_COLOR = QColor(0, 170, 90)          # classic AutoCAD grip blue-green
    GRIP_HOVER = QColor(255, 90, 90)
    GRIP_SIZE = 8

    def _draw_grips(self, p: QPainter) -> None:
        grips = self.tool_delegate.grip_points()
        if not grips:
            return
        s = self.GRIP_SIZE / 2.0
        hovered = self._grip_hover
        # Off-screen grips cost as much to draw as visible ones and show
        # nothing: a polyline of 800 vertices seen through a window that
        # holds twenty of them used to paint all 800 every frame.
        w, h_px = float(self.width()), float(self.height())
        squares, others = [], []
        hot = None
        for x, y, role, handle, i in grips:
            sx, sy = self._space_to_screen(x, y)
            if sx < -s or sy < -s or sx > w + s or sy > h_px + s:
                continue
            if hovered is not None and hovered[3] == handle and hovered[4] == i:
                hot = (sx, sy, role)
                continue
            if role in ("mid", "center"):
                others.append((sx, sy, role))
            else:
                squares.append(QRectF(sx - s, sy - s, 2 * s, 2 * s))
        # One pen and one brush for the whole batch: the old code set both
        # per grip, which is 2 Qt state changes per square and was the
        # single most expensive thing in the frame.
        p.setPen(QPen(self.GRIP_COLOR, 1))
        p.setBrush(self.GRIP_COLOR)
        if squares:
            p.drawRects(squares)                       # square: vertices/ends
        for sx, sy, role in others:
            if role == "mid":                          # triangle: add/stretch
                p.drawPolygon([QPointF(sx, sy - s), QPointF(sx - s, sy + s),
                               QPointF(sx + s, sy + s)])
            else:
                p.drawEllipse(QPointF(sx, sy), s, s)   # round: move whole
        if hot is not None:
            sx, sy, role = hot
            p.setPen(QPen(self.GRIP_HOVER, 1))
            p.setBrush(self.GRIP_HOVER)
            if role == "mid":
                p.drawPolygon([QPointF(sx, sy - s), QPointF(sx - s, sy + s),
                               QPointF(sx + s, sy + s)])
            elif role == "center":
                p.drawEllipse(QPointF(sx, sy), s, s)
            else:
                p.drawRect(sx - s, sy - s, 2 * s, 2 * s)
        p.setBrush(Qt.NoBrush)

    def _draw_live_text(self, p: QPainter) -> None:
        info = self.tool_delegate.live_text()
        if info is None:
            return
        from PySide6.QtGui import QFont

        pos, buffer, height, rotation = info
        sx, sy = self._space_to_screen(pos[0], pos[1])
        px = max(6.0, height * self._space_scale())  # world height -> pixels
        p.save()
        p.translate(sx, sy)
        p.rotate(-rotation)                        # world CCW -> screen
        font = QFont()
        font.setPixelSize(int(px))
        p.setFont(font)
        p.setPen(QPen(QColor(230, 230, 230)))
        text = buffer if buffer else ""
        fm = p.fontMetrics()
        p.drawText(QPointF(0, 0), text)            # baseline at the pick point
        caret_x = fm.horizontalAdvance(text)
        p.setPen(QPen(QColor(255, 200, 0), 1))     # blinking-less caret bar
        p.drawLine(QPointF(caret_x + 1, -px * 0.75), QPointF(caret_x + 1, px * 0.15))
        p.restore()

    def _visible_lines(self, segs, cap: int) -> list:
        """World segments -> QLineF, transformed in one numpy pass and
        clipped to the widget. Returns at most ``cap`` visible lines."""
        if not len(segs):
            return []
        v = self.view
        # While the view is still -- dragging a selection window, hovering a
        # grip, typing at the prompt -- the same lines are rebuilt every
        # frame. Keyed by the array IDENTITY (holding the reference keeps it
        # alive, so a rebuilt selection can never alias a freed one).
        xf = self.space_affine()
        state = (v.cx, v.cy, v.scale, v.width, v.height, cap, xf)
        cached = self._hl_lines_cache
        if cached is not None and cached[0] is segs and cached[1] == state:
            return cached[2]
        a = np.asarray(segs, dtype=float)
        if xf != (1.0, 0.0, 0.0, 1.0, 0.0, 0.0):
            # inside a viewport the segments are model coordinates: project
            # them onto the paper in the same numpy pass
            m11, m12, m21, m22, tx, ty = xf
            a = np.column_stack((
                m11 * a[:, 0] + m12 * a[:, 1] + tx,
                m21 * a[:, 0] + m22 * a[:, 1] + ty,
                m11 * a[:, 2] + m12 * a[:, 3] + tx,
                m21 * a[:, 2] + m22 * a[:, 3] + ty))
        sx = (a[:, 0] - v.cx) * v.scale + v.width / 2.0
        sy = v.height / 2.0 - (a[:, 1] - v.cy) * v.scale
        ex = (a[:, 2] - v.cx) * v.scale + v.width / 2.0
        ey = v.height / 2.0 - (a[:, 3] - v.cy) * v.scale
        w, h = float(self.width()), float(self.height())
        keep = ~((np.maximum(sx, ex) < 0) | (np.minimum(sx, ex) > w)
                 | (np.maximum(sy, ey) < 0) | (np.minimum(sy, ey) > h))
        idx = np.flatnonzero(keep)[:cap]
        lines = [QLineF(x1, y1, x2, y2) for x1, y1, x2, y2
                 in zip(sx[idx], sy[idx], ex[idx], ey[idx])] if len(idx) else []
        self._hl_lines_cache = (segs, state, lines)
        return lines

    def _draw_selection(self, p: QPainter) -> None:
        delegate = self.tool_delegate
        segs, circles, boxes = delegate.highlight_geometry()
        if len(segs) or len(circles) or len(boxes):
            # Solid, like BricsCAD's selected look: the dashed overlay read
            # as clutter on a real plan ("ensucia el dibujo").
            p.setPen(QPen(self.HIGHLIGHT_COLOR, 2))
            # Whole-array world->screen and a screen-rect cull: highlighting
            # a cadastre used to walk 4000 segments in Python EVERY frame,
            # most of them off-screen. The cap now bounds what is actually
            # visible, so zooming in shows a complete highlight instead of
            # the first 4000 segments of the selection.
            lines = self._visible_lines(segs, 4000)
            if lines:
                p.drawLines(lines)
            import math as _math

            for c in circles[:1000]:
                x, y = self._space_to_screen(c[0], c[1])
                r = c[2] * self._space_scale()
                if x + r < 0 or y + r < 0 or x - r > self.width() \
                        or y - r > self.height():
                    continue
                if len(c) >= 6 and c[3] != 0.0:
                    # highlight the ARC's real sweep, not its full circle
                    a0 = _math.degrees(c[4])
                    span = _math.degrees(c[5] - c[4])
                    p.drawArc(int(x - r), int(y - r), int(2 * r), int(2 * r),
                              int(a0 * 16), int(span * 16))
                else:
                    p.drawEllipse(QPointF(x, y), r, r)
            rects = []
            for b in boxes[:1000]:
                x1, y1 = self._space_to_screen(b[0], b[3])
                x2, y2 = self._space_to_screen(b[2], b[1])
                if x2 < 0 or y2 < 0 or x1 > self.width() or y1 > self.height():
                    continue
                rects.append(QRectF(x1, y1, x2 - x1, y2 - y1))
            if rects:
                p.drawRects(rects)
        rect_info = delegate.selection_rect()
        if rect_info is not None:
            (x0, y0, x1, y1), crossing = rect_info
            sx1, sy1 = self._space_to_screen(x0, y1)
            sx2, sy2 = self._space_to_screen(x1, y0)
            fill = self.CROSSING_FILL if crossing else self.WINDOW_FILL
            border = self.CROSSING_BORDER if crossing else self.WINDOW_BORDER
            p.fillRect(sx1, sy1, sx2 - sx1, sy2 - sy1, fill)
            p.setPen(QPen(border, 1, Qt.DashLine if crossing else Qt.SolidLine))
            p.drawRect(sx1, sy1, sx2 - sx1, sy2 - sy1)

    def _draw_tool_preview(self, p: QPainter) -> None:
        delegate = self.tool_delegate
        preview_color = (QColor(90, 90, 90) if self._light_background()
                        else QColor(200, 200, 200))
        pen = QPen(preview_color, 1, Qt.DashLine)
        p.setPen(pen)
        dim = delegate.preview_dimension()
        if dim is not None:
            self._draw_dim_preview(p, dim, preview_color)
            marker = getattr(delegate.tool, "align_marker", None)
            if marker is not None:
                # AutoCAD's chained-dimension aid: the green square where
                # the new line locked onto an existing dimension's line.
                mx, my = self._space_to_screen(*marker)
                half = self.MARKER_SIZE / 2.0
                p.save()
                p.setPen(QPen(QColor(80, 220, 80), 2))
                p.drawRect(mx - half, my - half, 2 * half, 2 * half)
                p.restore()
        else:
            for (ax, ay), (bx, by) in delegate.preview_segments():
                x1, y1 = self._space_to_screen(ax, ay)
                x2, y2 = self._space_to_screen(bx, by)
                p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        hit = delegate.snap_hit
        if hit is not None:
            sx, sy = self._space_to_screen(hit.x, hit.y)
            self._draw_snap_marker(p, hit.kind, sx, sy)

    def _draw_dim_preview(self, p: QPainter, dim: dict, color: QColor) -> None:
        """A real-looking dimension preview: extension + dimension lines,
        arrowheads, and the live measurement — floats with the cursor."""
        import math

        s = self._space_to_screen
        p1 = QPointF(*s(*dim["p1"]))
        p2 = QPointF(*s(*dim["p2"]))
        d1 = QPointF(*s(*dim["d1"]))
        d2 = QPointF(*s(*dim["d2"]))
        solid = QPen(color, 1)
        thin = QPen(color, 1, Qt.DashLine)
        # extension lines (dashed), dimension line (solid)
        p.setPen(thin)
        p.drawLine(p1, d1)
        p.drawLine(p2, d2)
        p.setPen(solid)
        p.drawLine(d1, d2)
        # arrowheads pointing outward along the dimension line
        ang = math.atan2(d2.y() - d1.y(), d2.x() - d1.x())
        self._arrow_head(p, d1, ang, color)
        self._arrow_head(p, d2, ang + math.pi, color)
        # measurement text, upright, centred above the dimension line
        mid = QPointF((d1.x() + d2.x()) / 2, (d1.y() + d2.y()) / 2)
        p.save()
        p.setPen(QPen(color))
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(dim["text"])
        p.drawText(QPointF(mid.x() - w / 2, mid.y() - 4), dim["text"])
        p.restore()

    def _arrow_head(self, p: QPainter, tip: QPointF, angle: float,
                    color: QColor) -> None:
        import math
        size = 9.0
        a1 = angle + math.radians(20)     # base corners open inward
        a2 = angle - math.radians(20)
        poly = QPolygonF([
            tip,
            QPointF(tip.x() + size * math.cos(a1), tip.y() + size * math.sin(a1)),
            QPointF(tip.x() + size * math.cos(a2), tip.y() + size * math.sin(a2)),
        ])
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawPolygon(poly)
        p.restore()

    def _draw_snap_marker(self, p: QPainter, kind: str, x: float, y: float) -> None:
        s = self.MARKER_SIZE / 2.0
        p.setPen(QPen(self.MARKER_COLOR, 2))
        if kind == "END":       # square
            p.drawRect(x - s, y - s, 2 * s, 2 * s)
        elif kind == "MID":     # triangle
            p.drawPolygon([QPointF(x, y - s), QPointF(x - s, y + s),
                           QPointF(x + s, y + s)])
        elif kind == "CEN":     # circle
            p.drawEllipse(QPointF(x, y), s, s)
        elif kind == "NOD":     # circle with X
            p.drawEllipse(QPointF(x, y), s, s)
            p.drawLine(QPointF(x - s, y - s), QPointF(x + s, y + s))
            p.drawLine(QPointF(x - s, y + s), QPointF(x + s, y - s))
        elif kind == "INS":     # two offset squares
            p.drawRect(x - s, y - s, 1.6 * s, 1.6 * s)
            p.drawRect(x - 0.4 * s, y - 0.4 * s, 1.6 * s, 1.6 * s)
        elif kind == "GCE":     # square with its centre marked
            p.drawRect(x - s, y - s, 2 * s, 2 * s)
            p.drawPoint(QPointF(x, y))
            p.drawEllipse(QPointF(x, y), 1.2, 1.2)
        elif kind == "TAN":     # circle with its tangent across the top
            p.drawEllipse(QPointF(x, y + 1), s - 1, s - 1)
            p.drawLine(QPointF(x - s, y - s), QPointF(x + s, y - s))
        elif kind == "QUA":     # diamond
            p.drawPolygon([QPointF(x, y - s), QPointF(x + s, y),
                           QPointF(x, y + s), QPointF(x - s, y)])
        elif kind == "INT":     # X
            p.drawLine(QPointF(x - s, y - s), QPointF(x + s, y + s))
            p.drawLine(QPointF(x - s, y + s), QPointF(x + s, y - s))
        elif kind == "PER":     # right-angle symbol
            p.drawLine(QPointF(x - s, y - s), QPointF(x - s, y + s))
            p.drawLine(QPointF(x - s, y + s), QPointF(x + s, y + s))
            p.drawLine(QPointF(x - s, y), QPointF(x, y))
            p.drawLine(QPointF(x, y), QPointF(x, y + s))
        else:                   # NEA: bowtie
            p.drawPolygon([QPointF(x - s, y - s), QPointF(x + s, y + s),
                           QPointF(x + s, y - s), QPointF(x - s, y + s)])

    def _draw_ucs_icon(self, p: QPainter) -> None:
        """Classic UCS icon: red X / green Y arrows at the world origin.

        When the origin is outside the view, the icon anchors to the lower-left
        corner (AutoCAD's off-origin behavior).
        """
        ox, oy = self.view.world_to_screen(0.0, 0.0)
        margin = 40
        if not (-margin < ox < self.width() + margin and -margin < oy < self.height() + margin):
            ox, oy = 60.0, self.height() - 60.0
        size = 48
        x_pen = QPen(QColor(205, 82, 82), 2)
        y_pen = QPen(QColor(96, 190, 96), 2)
        p.setPen(x_pen)
        p.drawLine(QPointF(ox, oy), QPointF(ox + size, oy))
        p.drawLine(QPointF(ox + size, oy), QPointF(ox + size - 8, oy - 4))
        p.drawLine(QPointF(ox + size, oy), QPointF(ox + size - 8, oy + 4))
        p.drawText(QPointF(ox + size + 6, oy + 4), "X")
        p.setPen(y_pen)
        p.drawLine(QPointF(ox, oy), QPointF(ox, oy - size))
        p.drawLine(QPointF(ox, oy - size), QPointF(ox - 4, oy - size + 8))
        p.drawLine(QPointF(ox, oy - size), QPointF(ox + 4, oy - size + 8))
        p.drawText(QPointF(ox - 4, oy - size - 6), "Y")

    def _light_background(self) -> bool:
        if self._scene is None:
            return False
        if self._scene.paper is not None:
            # Layout tab: the white sheet dominates the view — dark crosshair
            # and previews, like AutoCAD's black crosshair over paper.
            return True
        if self._scene.background is None:
            return False
        r, g, b, _a = self._scene.background
        return (0.2126 * r + 0.7152 * g + 0.0722 * b) > 0.5

    def _cursor_mode(self) -> str:
        delegate = self.tool_delegate
        getter = getattr(delegate, "cursor_mode", None) if delegate else None
        try:
            return getter() if getter else "idle"
        except Exception:
            return "idle"

    def refresh_cursor_prefs(self) -> None:
        """Re-read CURSORSIZE, the crosshair colour and PICKBOX."""
        self._cursorsize = cursorsize()
        self._crosshair_color = crosshair_color()
        self._pickbox_px = pickbox()
        self.update()

    def _draw_crosshair(self, p: QPainter, pos: QPointF,
                        mode: str = "idle") -> None:
        """The cursor, in AutoCAD's three states (see cursor_mode).

        A command that is choosing objects shows the pick box ALONE: the
        crosshair is for aiming at a coordinate, and there is no coordinate
        being asked for. Keeping it there is the giveaway that a CAD program
        was written by someone who never watched a drafter work.
        """
        color = self._crosshair_color
        if color is None:
            color = (CROSSHAIR_COLOR_LIGHT if self._light_background()
                     else CROSSHAIR_COLOR)
        clipped = False
        if self.active_vp_rect is not None:
            # "the crosshairs are clipped to the current viewport" — the
            # cue that says which viewport an edit will land in.
            x0, y0, x1, y1 = self.active_vp_rect
            sx0, sy0 = self.view.world_to_screen(x0, y1)
            sx1, sy1 = self.view.world_to_screen(x1, y0)
            p.save()
            p.setClipRect(QRectF(sx0, sy0, sx1 - sx0, sy1 - sy0))
            clipped = True
        p.setPen(QPen(color, 1))
        x, y = pos.x(), pos.y()
        box = self._pickbox_px
        half = box / 2
        if mode != "pick":
            # CURSORSIZE: "the size of the crosshairs as a percentage of the
            # screen size... when set to 100, the crosshairs are full-screen"
            # (p.2202). The percentage is of the SHORTER side, so 100 reaches
            # every edge and a square cursor stays square.
            pct = self._cursorsize
            if pct >= 100:
                p.drawLine(QPointF(0, y), QPointF(self.width(), y))
                p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
            else:
                arm = min(self.width(), self.height()) * pct / 200.0
                p.drawLine(QPointF(x - arm, y), QPointF(x + arm, y))
                p.drawLine(QPointF(x, y - arm), QPointF(x, y + arm))
        if mode != "point":
            p.drawRect(x - half, y - half, box, box)
        if clipped:
            p.restore()

    # -- input -----------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if self._pan_mode:
            if event.button() == Qt.LeftButton:
                self._panning = True   # grab: closed hand, pan follows cursor
                self._last_pos = event.position()
                self.setCursor(Qt.ClosedHandCursor)
                return
            if event.button() == Qt.RightButton:
                self.stop_pan_mode()   # right-click ends PAN, like AutoCAD
                return
        if event.button() == Qt.RightButton and self.tool_delegate is not None:
            window = getattr(self.tool_delegate, "window", None)
            if self._zoom_window:
                self._zoom_window = False        # right-click cancels the pick
                self.setCursor(Qt.BlankCursor)
                if self._rubber is not None:
                    self._rubber.hide()
            elif self.tool_delegate._grip_drag is not None:
                self.tool_delegate.cancel()      # drop the hot grip
            elif window is not None and hasattr(window, "on_canvas_right_click"):
                # AutoCAD: Enter during a command, context menu when idle.
                window.on_canvas_right_click(event.globalPosition().toPoint())
            self.update()
            return
        if self._zoom_window and event.button() == Qt.LeftButton:
            self._rubber_origin = event.position()
            if self._rubber is None:
                self._rubber = QRubberBand(QRubberBand.Rectangle, self)
            self._rubber.setGeometry(int(self._rubber_origin.x()),
                                     int(self._rubber_origin.y()), 0, 0)
            self._rubber.show()
            return
        if event.button() == Qt.MiddleButton:
            self._panning = True
            self._last_pos = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            self.update()
            return
        if event.button() == Qt.LeftButton and self.tool_delegate is not None:
            pos = event.position()
            wx, wy = self.view.screen_to_world(pos.x(), pos.y())
            shift = bool(event.modifiers() & Qt.ShiftModifier)
            if self.tool_delegate.in_selection_mode():
                if self.tool_delegate._grip_drag is not None:
                    # a grip is already "hot": this click drops it here
                    # (snap-resolved, like the live follow)
                    tx, ty = self.tool_delegate.grip_target(wx, wy)
                    self.tool_delegate.finish_grip_drag(tx, ty)
                    self.update()
                    return
                grip = self.tool_delegate.grip_at(
                    wx, wy, GRIP_PICK_PX / self.view.scale)
                if grip is not None:
                    # click to grab; the point then follows the cursor freely
                    self.tool_delegate.begin_grip_drag(grip)
                    self.update()
                    return
            if self.tool_delegate.wants_drag_rect():
                # defer to release: a drag becomes a window, a click a pick
                self._sel_press = (pos, (wx, wy), shift)
                return
            self.tool_delegate.on_click(wx, wy, shift)
            self.update()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._pan_mode and event.button() == Qt.LeftButton:
            self._panning = False           # release: back to open hand
            self._pan_last_screen = event.position()
            self.setCursor(Qt.OpenHandCursor)
            return
        if self._zoom_window and event.button() == Qt.LeftButton:
            self._zoom_window = False
            self.setCursor(Qt.BlankCursor)
            if self._rubber is not None:
                self._rubber.hide()
            pos = event.position()
            x0, y0 = self._rubber_origin.x(), self._rubber_origin.y()
            if abs(pos.x() - x0) > 4 and abs(pos.y() - y0) > 4:
                wx0, wy0 = self.view.screen_to_world(x0, y0)
                wx1, wy1 = self.view.screen_to_world(pos.x(), pos.y())
                window = self._mspace_window()
                if window is not None and window.vp_zoom_window(
                        min(wx0, wx1), min(wy0, wy1),
                        max(wx0, wx1), max(wy0, wy1)):
                    # inside a viewport the window zooms THAT view, like the
                    # wheel does, not the sheet the frame sits on
                    self.update()
                    return
                self.push_view()
                self.view.zoom_extents(min(wx0, wx1), min(wy0, wy1),
                                       max(wx0, wx1), max(wy0, wy1), margin=0.0)
            self.update()
            return
        if event.button() == Qt.MiddleButton and self._panning:
            self._panning = False
            # the crosshair comes back exactly under the pointer, not where
            # the last move event happened to land
            self._cursor = event.position()
            self.setCursor(Qt.BlankCursor)
            if self.tool_delegate is not None:
                wx, wy = self.view.screen_to_world(self._cursor.x(),
                                                   self._cursor.y())
                self.cursorMoved.emit(wx, wy)
            self.update()
            return
        if (event.button() == Qt.LeftButton and self._sel_press is not None
                and self.tool_delegate is not None):
            press_pos, press_world, shift = self._sel_press
            self._sel_press = None
            pos = event.position()
            dragged = (abs(pos.x() - press_pos.x()) > 4
                       or abs(pos.y() - press_pos.y()) > 4)
            if dragged:
                # drag-window: anchor at press, complete at release
                self.tool_delegate.start_window(*press_world)
                wx, wy = self.view.screen_to_world(pos.x(), pos.y())
                self.tool_delegate.on_click(wx, wy, shift)
            else:
                self.tool_delegate.on_click(*press_world, shift)
            self.update()
            return
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        # Self-healing: if the button that started a pan was released where
        # we could not see it (over the floating MTEXT editor, another
        # widget, outside the window), the release never arrives and the
        # drag would stick to the cursor forever — Esc included, since it
        # goes to the editor. No button down = no pan.
        if self._panning and not (event.buttons()
                                  & (Qt.MiddleButton | Qt.LeftButton)):
            self._panning = False
        if self._pan_mode:
            if self._panning:
                delta = pos - self._last_pos
                self._last_pos = pos
                self._pan_by(delta)
            # The hand hides the crosshair, but PAN ends where the hand is:
            # remember the position so it comes back under the pointer.
            self._pan_last_screen = pos
            wx, wy = self.view.screen_to_world(pos.x(), pos.y())
            self.cursorMoved.emit(wx, wy)
            self.update()
            return   # open hand otherwise: no crosshair, no hover
        if self._zoom_window and self._rubber is not None and self._rubber.isVisible():
            x0, y0 = self._rubber_origin.x(), self._rubber_origin.y()
            self._rubber.setGeometry(int(min(x0, pos.x())), int(min(y0, pos.y())),
                                     int(abs(pos.x() - x0)), int(abs(pos.y() - y0)))
            return
        if (self.tool_delegate is not None
                and self.tool_delegate._grip_drag is not None):
            # grip is hot: it follows the cursor with NO button held
            # (AutoCAD click-move-click), snapping like a drawing point
            self._cursor = pos
            wx, wy = self.view.screen_to_world(pos.x(), pos.y())
            self.tool_delegate.on_hover(wx, wy, SNAP_PX_HOVER / self.view.scale)
            self.tool_delegate.update_grip_drag(*self.tool_delegate.grip_target(wx, wy))
            self.cursorMoved.emit(wx, wy)
            self.update()
            return
        if self._panning:
            delta = pos - self._last_pos
            self._last_pos = pos
            self._pan_by(delta)
            # The crosshair is not drawn while panning, but its position has
            # to keep up: without this it reappears on release wherever the
            # drag STARTED, and the coordinate readout lies for as long as
            # the pan lasts.
            self._cursor = pos
            wx, wy = self.view.screen_to_world(pos.x(), pos.y())
            self.cursorMoved.emit(wx, wy)
        else:
            self._cursor = pos
            wx, wy = self.view.screen_to_world(pos.x(), pos.y())
            if self.tool_delegate is not None:
                self._grip_hover = self.tool_delegate.grip_at(
                    wx, wy, GRIP_PICK_PX / self.view.scale)
                from views.tool_controller import SNAP_PX

                if (self._sel_press is not None
                        and (abs(pos.x() - self._sel_press[0].x()) > 4
                             or abs(pos.y() - self._sel_press[0].y()) > 4)):
                    # live drag-window rectangle while the button is held
                    self.tool_delegate.start_window(*self._sel_press[1])
                self.tool_delegate.on_hover(wx, wy, SNAP_PX / self.view.scale)
            self.cursorMoved.emit(wx, wy)
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:
        # AutoCAD: double-click enters/leaves a viewport on a layout tab.
        if event.button() == Qt.LeftButton and self.tool_delegate is not None:
            window = getattr(self.tool_delegate, "window", None)
            if window is not None and hasattr(window, "on_canvas_double_click"):
                pos = event.position()
                wx, wy = self.view.screen_to_world(pos.x(), pos.y())
                window.on_canvas_double_click(wx, wy)
                return
        super().mouseDoubleClickEvent(event)

    def _mspace_window(self):
        """The MainWindow iff MSPACE is active (wheel/pan go to the vp)."""
        window = getattr(self.tool_delegate, "window", None) \
            if self.tool_delegate is not None else None
        if window is not None and getattr(window, "_active_vp", None) is not None:
            return window
        return None

    def _pan_by(self, delta) -> None:
        """Middle/PAN drag: pans the paper — or the model inside the
        active viewport when MSPACE is on (AutoCAD)."""
        window = self._mspace_window()
        if window is not None and window.vp_view_pan(
                delta.x() / self.view.scale, -delta.y() / self.view.scale):
            return
        # no active viewport, or its display is locked: pan the paper
        self.view.pan_pixels(delta.x(), delta.y())

    def wheelEvent(self, event) -> None:
        notches = event.angleDelta().y() / 120.0
        if notches:
            pos = event.position()
            window = self._mspace_window()
            if window is not None:
                # MSPACE: the wheel zooms the MODEL in the viewport,
                # anchored at the cursor, exactly like the paper wheel —
                # unless the display is locked, then the paper zooms.
                wx, wy = self.view.screen_to_world(pos.x(), pos.y())
                if window.vp_view_zoom(1.2 ** notches, (wx, wy)):
                    return
            self.view.zoom_at(pos.x(), pos.y(), 1.2 ** notches)
            self.update()

    def leaveEvent(self, event) -> None:
        self._cursor = None
        self.update()
        super().leaveEvent(event)
