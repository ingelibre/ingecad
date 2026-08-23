# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Glue between prompt/viewport and the drawing tools.

Owns the interactive state AutoCAD users feel with their hands: object
snap (F3), ortho (F8), polar (F10), the rubber-band preview, and the
incremental overlay scene so drawing stays instant on any file size.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
from PySide6.QtCore import QObject, QThread, QTimer, Signal

from core import actions
from core import layouts as layout_ops
from core.coords import CoordinateError, parse_point
from core.i18n import tr
from core.select import GeometryIndex, apply_grip_edit, entity_grips
from core.snap import SnapEngine, SnapHit
from render.backend import _flatten_distance, build_scene_for_entities
from tools.base import Tool, ToolContext
from tools.blocks import BLOCK_TOOL_CLASSES
from tools.dimension import DIM_TOOL_CLASSES
from tools.draw import TOOL_CLASSES
from tools.edit import EDIT_TOOL_CLASSES
from tools.construct import CONSTRUCT_TOOL_CLASSES
from tools.inquiry import INQUIRY_TOOL_CLASSES
from tools.modify import MODIFY_TOOL_CLASSES
from tools.layout_tools import LAYOUT_TOOL_CLASSES

SNAP_PX = 12.0   # aperture in logical pixels
PICK_PX = 8.0    # pick box half-size in logical pixels
# Overlay entities beyond this schedule an idle merge into the base scene
# (the overlay is re-tessellated per edit, so it must not grow unbounded).
MERGE_THRESHOLD = 50
# MOVE/COPY/PASTE commits at or above this size reuse the ghost tessellation
# as a "stamp" instead of re-tessellating into the overlay (a 3000-entity
# paste re-tessellated ~3.5 s on the UI thread; the stamp costs nothing).
STAMP_MIN = 25


class _CacheWarmer(QThread):
    """Build the snap/pick caches off the UI thread right after a document
    opens — the first click on a cadastre paid a 5-8 s synchronous walk."""

    done = Signal(object, object, object, int)  # document, index, snap, rev

    def __init__(self, document) -> None:
        super().__init__()
        self._document = document

    def run(self) -> None:
        revision = self._document.revision
        index = GeometryIndex(self._document)
        engine = SnapEngine(self._document)
        try:
            index._build()
            engine._build()
        except Exception:
            index = engine = None   # doc mutated mid-walk: discard
        self.done.emit(self._document, index, engine, revision)


class _GhostWorker(QThread):
    """Tessellate the drag preview off the UI thread (big selections take
    seconds; Ctrl+V must not freeze). Same GIL/discard rules as RegenWorker."""

    done = Signal(object, object)   # ents list, Scene | None

    def __init__(self, document, ents, flatten: float) -> None:
        super().__init__()
        self._document = document
        self._ents = ents
        self._flatten = flatten

    def run(self) -> None:
        try:
            scene = build_scene_for_entities(
                self._document, self._ents, self._flatten)
        except Exception:
            scene = None    # doc mutated mid-read: caller falls back to regen
        self.done.emit(self._ents, scene)

ALL_TOOL_CLASSES = {**TOOL_CLASSES, **EDIT_TOOL_CLASSES, **BLOCK_TOOL_CLASSES,
                    **DIM_TOOL_CLASSES, **LAYOUT_TOOL_CLASSES,
                    **CONSTRUCT_TOOL_CLASSES, **INQUIRY_TOOL_CLASSES,
                    **MODIFY_TOOL_CLASSES}

# Sentinel first element of _grip_drag while a VIEWPORT grip is hot — the
# paper-space grip flow shares the widget's click-move-click plumbing but
# none of the modelspace snapshot/overlay machinery.
_VP_GRIP = "__viewport__"


def _align_dim_line(document, entity, wx, wy, threshold):
    """Chained-dimension magnet for the LINE grips: near another parallel
    dimension's line, the drag snaps to its offset (the BricsCAD aid
    Marco asked for). Returns (x, y, marker_or_None)."""
    kind = int(entity.dxf.get("dimtype", 0)) & 7
    if kind not in (0, 1) or threshold is None:
        return wx, wy, None
    angle = float(entity.dxf.get("angle", 0.0)) % 180.0
    if angle not in (0.0, 90.0):
        return wx, wy, None
    axis = 1 if angle == 0.0 else 0
    best = None
    for dim in document.modelspace().query("DIMENSION"):
        if dim is entity or (dim.dxf.dimtype & 7) not in (0, 1):
            continue
        if abs((dim.dxf.get("angle", 0.0) % 180.0) - angle) > 0.01:
            continue
        defpoint = dim.dxf.get("defpoint", None)
        if defpoint is None:
            continue
        coord = (defpoint.x, defpoint.y)[axis]
        distance = abs((wx, wy)[axis] - coord)
        if distance <= threshold and (best is None or distance < best[0]):
            best = (distance, coord)
    if best is None:
        return wx, wy, None
    snapped = [wx, wy]
    snapped[axis] = best[1]
    return snapped[0], snapped[1], (snapped[0], snapped[1])


def _dim_grip_preview(entity, role, wx, wy):
    """A live preview frame for a dimension grip drag, or None.

    Linear/aligned dimensions rebuild their frame from the defpoints with
    the dragged one replaced; the text grip ghosts the label at the
    cursor. Rendering nothing while dragging read as "the grip does not
    work" (Marco asked to SEE the line follow the green point).
    """
    import math

    kind = int(entity.dxf.get("dimtype", 0)) & 7
    measurement = None
    try:
        measurement = float(entity.get_measurement())
    except Exception:
        pass
    if role == "dim_text":
        return {"text_at": (wx, wy),
                "text": f"{measurement:.2f}" if measurement is not None else ""}
    if kind not in (0, 1):
        return None
    p1 = entity.dxf.get("defpoint2", None)
    p2 = entity.dxf.get("defpoint3", None)
    loc = entity.dxf.get("defpoint", None)
    if p1 is None or p2 is None or loc is None:
        return None
    p1 = [p1.x, p1.y]
    p2 = [p2.x, p2.y]
    loc = [loc.x, loc.y]
    if role == "dim_defpoint2":
        p1 = [wx, wy]
    elif role == "dim_defpoint3":
        p2 = [wx, wy]
    elif role == "dim_defpoint":
        loc = [wx, wy]
    if kind == 1:      # aligned: the line lies parallel to p1->p2
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        length = math.hypot(dx, dy)
        if length <= 1e-12:
            return None
        ux, uy = dx / length, dy / length
    else:              # linear: the stored angle fixes the direction
        angle = math.radians(float(entity.dxf.get("angle", 0.0)))
        ux, uy = math.cos(angle), math.sin(angle)
        length = abs((p2[0] - p1[0]) * ux + (p2[1] - p1[1]) * uy)
    t1 = (p1[0] - loc[0]) * ux + (p1[1] - loc[1]) * uy
    t2 = (p2[0] - loc[0]) * ux + (p2[1] - loc[1]) * uy
    d1 = (loc[0] + ux * t1, loc[1] + uy * t1)
    d2 = (loc[0] + ux * t2, loc[1] + uy * t2)
    return {"p1": tuple(p1), "p2": tuple(p2), "d1": d1, "d2": d2,
            "text": f"{length:.2f}"}


class ToolController(QObject):
    changed = Signal()  # something visual changed: repaint the viewport

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.tool: Optional[Tool] = None
        self.osnap_on = True
        # Which snaps are running (core.osnap keys). The status-bar menu and
        # the Drafting Settings dialog write here.
        from core import osnap as osnap_modes

        self.osnap_modes = set(osnap_modes.from_bits(osnap_modes.DEFAULT_BITS))
        self.ortho_on = False
        self.polar_on = False
        self.snap_engine: Optional[SnapEngine] = None
        self.snap_hit: Optional[SnapHit] = None
        self._cursor: Optional[tuple[float, float]] = None
        self._flatten = 0.01
        self._base_handles: set[str] = set()
        self._clipboard = None   # (list[entity copies], base point) for paste
        self._clipboard_src: list = []   # source handles aligned w/ clipboard
        self._ghost_on = False   # a drag ghost (MOVE/COPY/PASTE) is showing
        # Ghost tessellation is expensive on big selections: cache it per
        # entity-list identity and build it OFF the UI thread.
        self._ghost_cache: Optional[tuple] = None    # (ents list, Scene)
        self._ghost_workers: set = set()             # live tessellators
        self._ghost_wanted: Optional[list] = None
        # Stamped commits (big MOVE/COPY/PASTE): id(command) -> record.
        self._stamp_records: dict = {}
        self._pending_stamps: list = []   # record keys awaiting ghost scene
        # Per-frame caches keyed on (index.version, selection).
        self._highlight_cache = None
        self._grips_cache = None
        self._warmers: set = set()        # background cache builders
        # Selection state (idle noun set, or the set a tool is acquiring).
        self.index: Optional[GeometryIndex] = None
        self.selection: set[str] = set()
        # Paper space has its own tiny selection: the one picked VIEWPORT
        # entity (border click). Model selection machinery never sees it.
        self.paper_vp = None
        self._selecting_for: Optional[Tool] = None
        # Rectangles a crossing selection covered, for the one command that
        # cares WHERE the selection touched: STRETCH.
        self._crossing_rects: list = []
        self._window_anchor: Optional[tuple[float, float]] = None
        self._pick_tolerance = 1.0  # world units, refreshed on hover
        # Edits render instantly via the overlay; the expensive base-scene
        # regen is coalesced so a burst of trims pays it once.
        self._pending_render: list = []
        # Grip drag state: (handle, grip_index, role, SnapshotCommand).
        self._grip_drag = None
        self._regen_timer = QTimer(self)
        self._regen_timer.setSingleShot(True)
        self._regen_timer.setInterval(400)
        self._regen_timer.timeout.connect(self._run_deferred_regen)
        # Additive edits (draw/paste/copy) never NEED a regen — they ride the
        # overlay — but the overlay is re-tessellated per edit, so merge it
        # into the base scene after a longer quiet pause to bound its growth.
        self._merge_timer = QTimer(self)
        self._merge_timer.setSingleShot(True)
        self._merge_timer.setInterval(2500)
        self._merge_timer.timeout.connect(self._run_deferred_regen)

    # -- document lifecycle ----------------------------------------------------
    def attach_document(self, document, flatten: Optional[float] = None) -> None:
        self.snap_engine = SnapEngine(document)
        self.index = GeometryIndex(document)
        self._ghost_cache = None
        self._ghost_wanted = None
        self._stamp_records = {}
        self._pending_stamps = []
        self._highlight_cache = None
        self._grips_cache = None
        self.window.viewport.clear_stamps()
        # warm the caches in the background so the FIRST pick/hover on a big
        # drawing does not pay the full modelspace walk synchronously
        warmer = _CacheWarmer(document)
        warmer.done.connect(self._on_caches_warm)
        self._warmers.add(warmer)
        warmer.start()
        self.selection = set()
        self._selecting_for = None
        self._window_anchor = None
        self._flatten = flatten if flatten else _flatten_distance(
            document.modelspace())
        self._base_handles = set()
        self.window.history.document = document
        self.window.history.clear()
        self._refresh_overlay()

    def _on_caches_warm(self, document, index, engine, revision) -> None:
        worker = self.sender()
        if worker in self._warmers:
            worker.wait()   # thread has emitted; joins immediately
            self._warmers.discard(worker)
        if index is None or engine is None:
            return
        if (self.window.document is not document
                or document.revision != revision):
            return          # the user edited or opened another file: stale
        # adopt only what the user has not built already
        if self.index is not None and self.index._dirty:
            self.index = index
            self._highlight_cache = None
            self._grips_cache = None
        if self.snap_engine is not None and self.snap_engine._dirty:
            self.snap_engine = engine

    def mark_scene_merged(self) -> None:
        """A full regen just happened: overlay entities now live in the base."""
        self._base_handles = {
            c.entity.dxf.handle
            for c in self._draw_commands()
            if c.entity is not None
        }
        self._pending_render = []
        # stamped placements are part of the fresh base scene now
        self._stamp_records = {}
        self._pending_stamps = []
        self.window.viewport.clear_stamps()
        self._refresh_overlay()

    # -- toggles ---------------------------------------------------------------
    def toggle(self, which: str) -> bool:
        value = not getattr(self, f"{which}_on")
        setattr(self, f"{which}_on", value)
        self.changed.emit()
        return value

    # -- tool lifecycle --------------------------------------------------------
    def active(self) -> bool:
        return self.tool is not None

    def start_tool(self, name: str) -> None:
        self.reset_pick_cycle()   # a new command starts picking fresh
        in_paper = getattr(self.window, "_active_layout", "Model") != "Model"
        if name in LAYOUT_TOOL_CLASSES and not in_paper:
            # AutoCAD: "** Command not allowed in Model Tab **"
            self.window.command_line.echo(
                tr("** {name} is not allowed in the Model tab — switch to a "
                   "layout. **", name=name))
            return
        if in_paper and name not in LAYOUT_TOOL_CLASSES:
            # Model-space editing from a layout tab arrives with MSPACE.
            self.window.command_line.echo(
                tr("Drawing on the sheet itself is not available yet — "
                   "MSPACE to draw inside a viewport, or use the Model tab."))
            return
        if self.window.document is None:
            self.window.new_document()
        if self.tool is not None:
            self.tool.on_cancel()
        if not self.selection:
            self._crossing_rects = []
        ctx = ToolContext(
            execute=self._execute,
            prompt=self.window.command_line.echo,
            echo=self.window.command_line.echo,
            finish=self._finish,
            services=self,
            ask_text=self._ask_text,
            ask_choice=self._ask_choice,
            ask_hatch=self._ask_hatch,
            undo_last=self.window._cmd_undo,
        )
        self.tool = ALL_TOOL_CLASSES[name](ctx)
        self.tool.start()
        if self.tool is not None and self.tool.wants_selection:
            if self.selection:
                # noun-verb: the preselected set feeds the command directly.
                # The highlight STAYS while the command runs (AutoCAD keeps
                # the cutting edges lit during TRIM to guide the picks);
                # _finish clears it.
                entities = self._selection_entities()
                self.tool.on_selection(entities)
            else:
                self._selecting_for = self.tool
                self.window.command_line.echo(self.tool.selection_prompt())
        self.changed.emit()

    # -- services for editing tools (ToolContext.services) ---------------------
    def paper_context(self):
        """(document, active layout name) for paper-space tools (MVIEW)."""
        return self.window.document, self.window._active_layout

    def units(self):
        """The drawing's unit settings, for the tools that print numbers."""
        return self.window.display_units()

    def pick_entity(self, point):
        if self.index is None:
            return None
        handle = self.pick_cycling(point)
        return self.index.entity(handle) if handle else None

    # -- selection cycling -----------------------------------------------------
    #: (point, candidate handles, index into them) of the click being cycled.
    _cycle = None

    def reset_pick_cycle(self) -> None:
        """Forget the cycle: the next click starts from the nearest again."""
        self._cycle = None

    def pick_cycling(self, point) -> Optional[str]:
        """The handle this click selects, advancing on a repeated click.

        On a dense plan things sit on top of each other -- a dimension and
        the number somebody typed beside it -- and a click always answered
        with the same one, so the other was unreachable. Clicking the same
        spot again now offers the next candidate, which is what AutoCAD's
        selection cycling does (SELECTIONCYCLING, p. 2505) without the list
        dialog its value 2 shows.

        The first answer is unchanged: ``pick_all`` orders candidates exactly
        as ``pick`` chose its winner, so cycling only ever reaches what a
        single click was already skipping.
        """
        if self.index is None:
            return None
        tolerance = self._pick_tolerance
        cycle = self._cycle
        if cycle is not None:
            (px, py), handles, position = cycle
            near = abs(point[0] - px) <= tolerance and abs(point[1] - py) <= tolerance
            handles = [h for h in handles
                       if (e := self.index.entity(h)) is not None and e.is_alive]
            if near and len(handles) > 1:
                position = (position + 1) % len(handles)
                self._cycle = ((px, py), handles, position)
                self._echo_cycle(handles, position)
                return handles[position]
        handles = self.index.pick_all(point, tolerance)
        if not handles:
            self._cycle = None
            return None
        self._cycle = (point, handles, 0)
        return handles[0]

    def _echo_cycle(self, handles, position) -> None:
        entity = self.index.entity(handles[position])
        kind = entity.dxftype() if entity is not None else "?"
        self.window.command_line.echo(
            tr("Cycling: {n} of {total} ({kind}) — click again for the next.",
               n=position + 1, total=len(handles), kind=kind))

    def edges_geometry(self, handles=None, exclude=None, near=None):
        """(segments, circles) for TRIM/EXTEND edge math.

        ``near`` is a world bbox: cutters that cannot touch it are filtered
        out vectorized — a trim pick pays for LOCAL edges, not the whole
        drawing (TRIM cutters must intersect the target by definition).
        """
        if self.index is None:
            return [], []
        if self.index._dirty:
            self.index._build()
        seg_arr = self.index._segs
        circ_arr = self.index._circles
        smask = np.ones(len(seg_arr), dtype=bool)
        cmask = np.ones(len(circ_arr), dtype=bool)
        if handles is not None:
            wanted = set(handles)
            wanted.discard(exclude)
            ids = self.index._ids_of(wanted)
            smask &= np.isin(self.index._seg_oidx, ids)
            cmask &= np.isin(self.index._circle_oidx, ids)
        elif exclude is not None:
            ex = self.index._owner_ids.get(exclude)
            if ex is not None:
                smask &= self.index._seg_oidx != ex
                cmask &= self.index._circle_oidx != ex
        if near is not None and len(seg_arr):
            x0, y0, x1, y1 = near
            smask &= ((np.minimum(seg_arr[:, 0], seg_arr[:, 2]) <= x1)
                      & (np.maximum(seg_arr[:, 0], seg_arr[:, 2]) >= x0)
                      & (np.minimum(seg_arr[:, 1], seg_arr[:, 3]) <= y1)
                      & (np.maximum(seg_arr[:, 1], seg_arr[:, 3]) >= y0))
        if near is not None and len(circ_arr):
            x0, y0, x1, y1 = near
            cmask &= ((circ_arr[:, 0] - circ_arr[:, 2] <= x1)
                      & (circ_arr[:, 0] + circ_arr[:, 2] >= x0)
                      & (circ_arr[:, 1] - circ_arr[:, 2] <= y1)
                      & (circ_arr[:, 1] + circ_arr[:, 2] >= y0))
        segs = [tuple(s) for s in seg_arr[smask]]
        # (center, r, a0, a1): arcs cut/bound only along their real sweep
        circles = [((c[0], c[1]), c[2], c[4], c[5]) for c in circ_arr[cmask]]
        return segs, circles

    def _selection_entities(self) -> list:
        out = []
        for h in self.selection:
            e = self.index.entity(h) if self.index else None
            if e is not None and e.is_alive:
                out.append(e)
        return out

    def clear_selection(self) -> None:
        self.reset_pick_cycle()
        self.selection = set()
        self.paper_vp = None
        self._window_anchor = None
        self.changed.emit()

    # -- Delete / clipboard (noun-verb: act on the current selection) ----------
    def delete_selection(self) -> bool:
        """Supr/Delete: erase the selected objects (only when idle)."""
        if self.tool is not None:
            return False
        if self._paper_select_mode():
            vp = self.paper_vp
            if vp is None or not vp.is_alive:
                return False
            self.paper_vp = None
            # hide the border instantly (its vertices are owned by the vp
            # handle); the content refreshes with the regen
            self.window.viewport.hide_handles([vp.dxf.handle])
            self._execute(layout_ops.RemoveViewportCommand(
                vp, self.window._active_layout))
            self.changed.emit()
            return True
        entities = self._selection_entities()
        if not entities:
            return False
        self._execute(actions.EraseCommand(entities))
        self.clear_selection()
        return True

    def copy_selection(self, cut: bool = False) -> bool:
        """Ctrl+C / Ctrl+X: stash copies of the selection with a base point."""
        entities = self._selection_entities()
        if not entities:
            return False
        # base point from the cached pick rows: ezdxf bbox walks INSERT
        # contents recursively and cost ~1.6 s on a big selection
        bounds = (self.index.bounds_of(self.selection)
                  if self.index is not None else None)
        if bounds is not None:
            base = (bounds[0], bounds[1])
        else:
            try:
                from ezdxf import bbox
                ext = bbox.extents(entities, fast=True)
                base = (ext.extmin.x, ext.extmin.y)
            except Exception:
                base = (0.0, 0.0)
        self._clipboard = ([e.copy() for e in entities], base)
        # source handles (aligned with the clipboard) let paste register its
        # copies in the pick index by translating the sources' cached rows
        self._clipboard_src = [e.dxf.handle for e in entities]
        if cut:
            self._execute(actions.EraseCommand(entities))
            self.clear_selection()
        return True

    def clipboard_data(self):
        return self._clipboard if self._clipboard else (None, None)

    def paste(self) -> None:
        """Ctrl+V: place the clipboard entities from a picked point."""
        if not self._clipboard:
            self.window.command_line.echo(tr("Clipboard is empty."))
            return
        self.start_tool("PASTECLIP")

    # -- in-place text typing (DTEXT) -----------------------------------------
    def text_capturing(self) -> bool:
        return self.tool is not None and getattr(self.tool, "typing", False)

    def text_char(self, ch: str) -> None:
        if self.text_capturing():
            self.tool.on_char(ch)
            self.changed.emit()

    def text_backspace(self) -> None:
        if self.text_capturing():
            self.tool.on_backspace()
            self.changed.emit()

    def text_newline(self) -> None:
        if self.text_capturing():
            self.tool.on_enter()
            self.changed.emit()

    def text_finish(self) -> None:
        if self.text_capturing():
            self.tool.finish_typing()
            self.changed.emit()

    def live_text(self):
        tool = self.tool
        return tool.live_text() if tool is not None and hasattr(tool, "live_text") \
            else None

    # -- the in-place MTEXT editor ---------------------------------------------
    def open_mtext_editor(self, first, second, char_height: float) -> None:
        """MTEXT's two corners placed: edit the new text on the canvas."""
        from views.mtext_editor import MTextInPlaceEditor

        top_left = (min(first[0], second[0]), max(first[1], second[1]))
        width = abs(second[0] - first[0])
        document = self.window.document
        style = ""
        if document is not None:
            style = document.doc.header.get("$TEXTSTYLE", "Standard")

        def commit(content: str, extras: dict) -> None:
            if content.strip():
                box_second = second
                new_width = extras.get("width")
                if new_width:
                    # The ruler's width arrow moved: keep the left edge, put
                    # the right one where it was dragged to.
                    direction = 1.0 if second[0] >= first[0] else -1.0
                    box_second = (first[0] + direction * new_width, second[1])
                self._execute(actions.add_mtext(
                    first, box_second, content, char_height,
                    style=extras.get("style"),
                    attachment=extras.get("attachment") or 1,
                    line_spacing=extras.get("line_spacing"),
                    bg=extras.get("bg"),
                    columns=extras.get("columns")))
            self.window.viewport.update()

        self._mtext_editor = MTextInPlaceEditor(
            self.window.viewport, top_left=top_left, width_world=width,
            char_height=char_height, text="", on_commit=commit,
            document=document, style=style, allow_justify=True)

    def open_text_editor_for(self, entity) -> bool:
        """Double-click on a TEXT/MTEXT: edit it in place. True if handled.

        The anchor is the entity's insert point; for MTEXT attachment points
        other than top-left the editor sits close to, not exactly on, the
        text — a step-1 simplification, not a rule.
        """
        from views.mtext_editor import MTextInPlaceEditor

        kind = entity.dxftype()
        if kind not in ("MTEXT", "TEXT"):
            return False
        insert = entity.dxf.insert
        if kind == "MTEXT":
            char_height = float(entity.dxf.char_height or 2.5)
            width = float(entity.dxf.get("width", 0) or 0)
            if width <= 0:
                width = 40.0 * char_height    # unwrapped: a workable box
            text = entity.text
            single = False
        else:
            char_height = float(entity.dxf.height or 2.5)
            width = max(len(entity.dxf.text), 8) * char_height
            text = entity.dxf.text
            single = True

        def commit(content: str, extras: dict) -> None:
            if kind == "TEXT":
                new = content.replace("\\P", " ")
            else:
                new = content
            new_style = extras.get("style")
            new_width = extras.get("width")
            new_spacing = extras.get("line_spacing")
            new_bg = extras.get("bg")
            new_columns = extras.get("columns")
            if new == text and not new_style and not new_width \
                    and not new_spacing and new_bg is None \
                    and new_columns is None:
                return                        # untouched: not an edit

            def mutate() -> None:
                if kind == "MTEXT":
                    entity.text = new
                    if new_width:
                        entity.dxf.width = float(new_width)
                    if new_spacing:
                        entity.dxf.line_spacing_factor = float(new_spacing)
                        entity.dxf.line_spacing_style = 1
                    actions.apply_mtext_bg(entity, new_bg)
                    actions.apply_mtext_columns(entity, new_columns)
                else:
                    entity.dxf.text = new
                if new_style:
                    entity.dxf.style = new_style
            actions.apply_in_place(self.window.history, [entity], mutate)
            self.window.regen_in_memory()
            self.window.viewport.update()

        self._mtext_editor = MTextInPlaceEditor(
            self.window.viewport,
            top_left=(insert.x, insert.y),
            width_world=width, char_height=char_height, text=text,
            on_commit=commit, single_line=single,
            document=self.window.document,
            style=str(entity.dxf.get("style", "Standard")),
            line_spacing=float(entity.dxf.get("line_spacing_factor", 1.0)
                               or 1.0))
        if kind == "MTEXT":
            fill = int(entity.dxf.get("bg_fill", 0) or 0)
            if fill & 1:
                colour = "canvas" if (fill & 3) == 3 else \
                    int(entity.dxf.get("bg_fill_color", 7) or 7)
                self._mtext_editor.set_initial_bg(
                    (colour, float(entity.dxf.get("box_fill_scale", 1.5))))
            if entity.has_columns:
                cols = entity.columns
                self._mtext_editor.set_initial_columns(
                    (cols.count, cols.defined_height or cols.total_height,
                     cols.gutter_width))
        return True

    def _ask_text(self, prompt: str, default: str = "") -> Optional[str]:
        from PySide6.QtWidgets import QInputDialog

        text, ok = QInputDialog.getMultiLineText(
            self.window, prompt, prompt, default)
        return text if ok else None

    def _ask_choice(self, prompt: str, items: list, default: str = "") -> Optional[str]:
        from PySide6.QtWidgets import QInputDialog

        start = items.index(default) if default in items else 0
        text, ok = QInputDialog.getItem(
            self.window, prompt, prompt, list(items), start, editable=False)
        return text if ok else None

    def _ask_hatch(self, settings: dict) -> Optional[dict]:
        from views.hatch_dialog import HatchDialog

        dlg = HatchDialog(self.window, settings)
        if dlg.exec():
            return dlg.settings()
        return None

    def hatch_region_at(self, point):
        """(outer_polygon, [island_polygons]) under a Pick-internal-point."""
        from core.hatch_boundary import region_at_point

        if self.window.document is None:
            return None
        return region_at_point(
            list(self.window.document.modelspace()), point)

    def block_names(self) -> list:
        """User block definitions (not *Model_Space/*Paper_Space/anonymous).

        Inside the Block Editor, a block that contains the edited one --
        directly or through nesting -- is left out: inserting it would make
        the definition contain itself, which AutoCAD refuses with "Block
        references itself" and ezdxf would happily write as an infinite
        recursion.
        """
        from core.blockedit import would_recurse

        document = self.window.document
        if document is None:
            return []
        editing = document.edit_block
        return sorted(
            b.name for b in document.doc.blocks
            if not b.name.startswith("*")
            and not would_recurse(document, b.name, editing))

    def _finish(self) -> None:
        self.tool = None
        self.snap_hit = None
        self._selecting_for = None
        self._window_anchor = None
        self.selection = set()  # command done: highlight goes off
        self._crossing_rects = []
        if self._ghost_on:
            self._ghost_on = False
            self.window.viewport.set_ghost_scene(None)
        self.changed.emit()

    def cancel(self) -> None:
        self.reset_pick_cycle()
        if self._grip_drag is not None and self._grip_drag[0] == _VP_GRIP:
            # Esc mid-drag of a viewport grip: nothing was mutated yet
            # (the drag only moves the rubber rectangle) — just drop it.
            self._grip_drag = None
            self.window.viewport.vp_drag_rect = None
            self.changed.emit()
            return
        if self._grip_drag is not None:
            # Esc mid-grip: revert the entity to its pre-drag snapshot. Its
            # base-scene copy was hidden at grab time, so ride the overlay
            # for instant feedback while the async regen rebuilds the base.
            handle, _i, _r, snap = self._grip_drag
            self._grip_drag = None
            snap.undo(self.window.document)
            self._invalidate_geometry()
            self._pending_render.extend(
                e for e in snap.entities
                if e.is_alive and e.dxf.owner is not None
                and e not in self._pending_render)
            self._refresh_overlay()
            self.window.regen_in_memory()
            return
        if self.tool is not None:
            tool = self.tool
            self.tool = None  # avoid re-entry via ctx.finish
            tool.on_cancel()
            self._finish()
        elif self.selection or self._window_anchor or self.paper_vp is not None:
            self.clear_selection()

    # -- command execution and incremental render ------------------------------
    @staticmethod
    def _added_entities(command):
        """New entities of a purely-additive command, else None.

        Additive commands (draw, paste, copy, mirror-keep-source) touch
        nothing that already exists, so the snap/pick caches can grow
        incrementally and the base scene needs no urgent regen.
        """
        if isinstance(command, actions.AddEntityCommand):
            return [command.entity] if command.entity is not None else []
        if isinstance(command, actions.AddDimensionCommand):
            # Its graphics live in an anonymous *D block, which the overlay
            # renders through the same frontend the base scene uses -- 1035
            # vertices for a plain DIMLINEAR, measured. Nothing about it needs
            # a full regen.
            return [command.dim] if command.dim is not None else []
        if isinstance(command, (actions.PasteCommand,
                                actions.CopyEntitiesCommand)):
            return list(command.copies)
        return None

    @staticmethod
    def _pure_translation(matrix):
        """(dx, dy) if the Matrix44 is a pure 2D translation, else None."""
        v = list(matrix)
        ident = (1.0, 0.0, 0.0, 0.0,
                 0.0, 1.0, 0.0, 0.0,
                 0.0, 0.0, 1.0, 0.0)
        if (all(abs(v[i] - ident[i]) <= 1e-12 for i in range(12))
                and abs(v[14]) <= 1e-12):
            return (v[12], v[13])
        return None

    def _stamp_setup(self, command, size_check):
        """((dx, dy), ghost list) when this commit can reuse the ghost.

        Stampable: a translation-only MOVE/COPY/PASTE of a big set whose
        source entities are exactly the active tool's ghost list — then the
        already-tessellated (or in-flight) ghost scene drawn at the drop
        offset replaces the overlay re-tessellation entirely.
        """
        if len(size_check) < STAMP_MIN:
            return None
        if isinstance(command, actions.PasteCommand):
            offset, srcs = (command.dx, command.dy), command.sources
        elif isinstance(command, (actions.CopyEntitiesCommand,
                                  actions.TransformCommand)):
            offset = self._pure_translation(command.matrix)
            srcs = getattr(command, "sources", None) or command.entities
        else:
            return None
        if offset is None:
            return None
        tool = self.tool
        ghost = getattr(tool, "ghost_entities", None) if tool is not None else None
        if (ghost is None or len(ghost) != len(srcs)
                or any(a is not b for a, b in zip(ghost, srcs))):
            return None
        return offset, ghost

    def _commit_stamp(self, command, stamp, hidden) -> None:
        (dx, dy), ghost_ents = stamp
        key = id(command)
        rec = {"command": command, "ents": ghost_ents, "dx": dx, "dy": dy,
               "scene": None, "hidden": list(hidden or [])}
        rec["shown"] = rec["hidden"] or [
            c.dxf.handle for c in getattr(command, "copies", None) or []]
        self._stamp_records[key] = rec
        if self._ghost_cache is not None and self._ghost_cache[0] is ghost_ents:
            rec["scene"] = self._ghost_cache[1]
            self.window.viewport.add_stamp(key, rec["scene"], dx, dy)
        else:
            # ghost still tessellating: the stamp appears when it lands
            self._pending_stamps.append(key)
        self._merge_timer.start()

    def _index_register_added(self, command, added) -> None:
        """Pick-index registration for new entities, translating the source
        rows when they are known (paste/copy) — no per-entity ezdxf bbox."""
        src = None
        offset = None
        if isinstance(command, actions.PasteCommand):
            # PasteCommand copies the source list — compare element-wise
            clip = self._clipboard[0] if self._clipboard else None
            if (clip is not None and len(clip) == len(command.sources)
                    and len(self._clipboard_src) == len(added)
                    and all(a is b for a, b in zip(clip, command.sources))):
                src, offset = self._clipboard_src, (command.dx, command.dy)
        elif isinstance(command, actions.CopyEntitiesCommand):
            offset = self._pure_translation(command.matrix)
            if offset is not None:
                src = [e.dxf.handle for e in command.sources]
        if src is not None and len(src) == len(added):
            pairs = list(zip(src, (c.dxf.handle for c in added)))
            missing = self.index.add_translated(pairs, *offset)
            if missing:
                self.index.add_entities(
                    [c for s, c in zip(src, added) if s in missing])
        else:
            self.index.add_entities(added)

    def _drop_conflicting_stamps(self, handles) -> None:
        """An edit touched entities shown by a stamp: retire that stamp and
        let the survivors ride the overlay (stamps must never show stale
        geometry). The commands stay undoable through the generic path."""
        if not self._stamp_records or not handles:
            return
        touched = set(handles)
        for key, rec in list(self._stamp_records.items()):
            if touched.isdisjoint(rec["shown"]):
                continue
            self.window.viewport.remove_stamp(key)
            if key in self._pending_stamps:
                self._pending_stamps.remove(key)
            del self._stamp_records[key]
            cmd = rec["command"]
            ents = (getattr(cmd, "entities", None) if rec["hidden"]
                    else getattr(cmd, "copies", None)) or []
            self._pending_render.extend(
                e for e in ents
                if e.is_alive and e.dxf.owner is not None
                and e not in self._pending_render)

    # Commands whose touched entities are fully known, so the pick index can
    # be patched (remove + re-add) instead of rebuilt from scratch.
    grip_dim_preview = None
    grip_align_marker = None

    _KNOWN_MODIFY = (actions.EraseCommand, actions.TransformCommand,
                     actions.SetPropertyCommand, actions.ReplaceEntitiesCommand,
                     actions.CreateBlockCommand, actions.ExplodeCommand)

    def _execute(self, command) -> None:
        # the drawing changed under the candidates: never cycle stale ones
        self.reset_pick_cycle()
        self.window.history.execute(command)
        # Any real edit invalidates the model tessellation the layout tab
        # keeps for live viewport navigation.
        invalidate = getattr(self.window, "invalidate_vp_model_cache", None)
        if invalidate is not None:
            invalidate()
        added = self._added_entities(command)
        if added is not None:
            # Appending beats invalidating: a full cache rebuild walks the
            # whole modelspace in Python on the NEXT mouse move — that walk
            # was the per-click lag while drawing on a large file.
            if self.snap_engine is not None:
                self.snap_engine.add_entities(added)
            if self.index is not None:
                self._index_register_added(command, added)
        elif isinstance(command, self._KNOWN_MODIFY):
            pass  # both caches are patched in the display branch below,
                  # where the touched entity sets are known
        else:
            self._invalidate_geometry()
        if (isinstance(command, actions.ReplaceEntitiesCommand)
                and self.selection):
            # a trimmed edge keeps its highlight through its survivors
            olds = {e.dxf.handle for e in command.old_entities}
            if olds & self.selection:
                self.selection = (self.selection - olds) | {
                    e.dxf.handle for e in command.new_entities}
        if self.selection and self.index is not None:
            # prune handles whose entities were erased or replaced
            self.selection = {
                h for h in self.selection
                if (e := self.index.entity(h)) is not None and e.is_alive
            }
        if getattr(command, "needs_regen", False):
            # A viewport's content is the model re-projected: the overlay
            # cannot show that, so only a regen is right.
            self.window.regen_in_memory()
        elif added is not None:
            # Additive: show through the overlay, no hide, no urgent regen —
            # paste used to schedule a full regen whose GIL-heavy rebuild
            # made the NEXT paste stutter on big files.
            stamp = self._stamp_setup(command, added)
            if stamp is not None:
                # big paste/copy: the ghost tessellation IS the result —
                # draw it as a stamp at the drop offset, zero re-tessellation
                self._commit_stamp(command, stamp, hidden=None)
            else:
                if not isinstance(command, actions.AddEntityCommand):
                    # drawn entities reach the overlay via _draw_commands()
                    self._pending_render.extend(added)
                self._refresh_overlay()
            if (not isinstance(command, actions.AddDimensionCommand)
                    and any(e.dxftype() == "DIMENSION" for e in added)):
                # A PASTED dimension may arrive without its *D block, so only
                # a regen renders it right. One this app just created carries
                # the block render() produced, and the overlay draws it.
                self._regen_timer.start()
            elif stamp is not None or (
                    len(self._draw_commands()) + len(self._pending_render)
                    > MERGE_THRESHOLD):
                # overlay/stamps got heavy: fold them into the base scene
                # after a quiet pause. Below the threshold no regen is ever
                # scheduled — a couple of pastes on a big file must not
                # queue a multi-second background rebuild.
                self._merge_timer.start()
        else:
            if isinstance(command, actions.TransformCommand):
                stamp = self._stamp_setup(command, command.entities)
                if stamp is not None:
                    # big MOVE: hide the base copies and draw the ghost
                    # tessellation at the destination — no overlay rebuild
                    handles = [e.dxf.handle for e in command.entities]
                    had = len(self._stamp_records)
                    self._drop_conflicting_stamps(handles)
                    if len(self._stamp_records) != had:
                        # a re-move: the new stamp shows these entities, so
                        # they must not ALSO ride the overlay
                        hs = set(handles)
                        self._pending_render = [
                            e for e in self._pending_render
                            if not (e.is_alive and e.dxf.handle in hs)]
                        self._refresh_overlay()
                    self.window.viewport.hide_handles(handles)
                    (dx, dy), _ents = stamp
                    if self.index is not None:
                        self.index.translate_handles(handles, dx, dy)
                    if self.snap_engine is not None:
                        self.snap_engine.translate_handles(handles, dx, dy)
                    self._commit_stamp(command, stamp, hidden=handles)
                    return
            # hide the OLD geometry instantly (surgical, no regen) and show
            # the results NOW through the overlay; the full regen is deferred
            old_handles = []
            if isinstance(command, (actions.EraseCommand,
                                    actions.TransformCommand,
                                    actions.SetPropertyCommand)) \
                    or getattr(command, "targets", None) is not None:
                # property edits too (MATCHPROP included): hide the stale-look
                # base copy and show the restyled entity via the overlay
                old_handles = [e.dxf.handle for e in command.entities]
            elif isinstance(command, actions.ReplaceEntitiesCommand):
                old_handles = [e.dxf.handle for e in command.old_entities]
            elif isinstance(command, (actions.CreateBlockCommand,
                                      actions.ExplodeCommand)):
                old_handles = [e.dxf.handle for e in command.sources]
            if old_handles:
                self._drop_conflicting_stamps(old_handles)
                self.window.viewport.hide_handles(old_handles)
                # hidden base copies re-show through the overlay: lift the
                # no-double-draw exclusion for them (same lag as the grips)
                self._base_handles -= set(old_handles)
            new_ents = []
            if isinstance(command, actions.CreateBlockCommand) and command.insert:
                new_ents = [command.insert]
            elif isinstance(command, actions.ExplodeCommand):
                for _orig, parts in command.pieces:
                    new_ents.extend(parts)
            elif isinstance(command, actions.EraseCommand):
                pass   # nothing new to show — the hide above IS the result
            else:
                for attr in ("new_entities", "copies", "entities"):
                    extra = getattr(command, attr, None)
                    if extra:
                        new_ents = list(extra)
                        break
            # Dedupe: MATCHPROP onto an entity already riding the overlay
            # (a dimension drawn seconds ago) would otherwise queue it twice
            # and tessellate it twice on every refresh.
            for entity in new_ents:
                if entity not in self._pending_render:
                    self._pending_render.append(entity)
            alive = [e for e in new_ents if e.is_alive]
            # patch both caches: O(touched) instead of a full rebuild
            # (all calls no-op if the cache was invalidated above)
            shift = (self._pure_translation(command.matrix)
                     if isinstance(command, actions.TransformCommand) else None)
            if shift is not None:
                # MOVE: shifting rows in place skips re-extraction entirely
                if self.index is not None:
                    self.index.translate_handles(old_handles, *shift)
                if self.snap_engine is not None:
                    self.snap_engine.translate_handles(old_handles, *shift)
            else:
                if self.index is not None:
                    self.index.remove_handles(old_handles)
                    self.index.add_entities(alive)
                if self.snap_engine is not None:
                    self.snap_engine.remove_handles(old_handles)
                    self.snap_engine.add_entities(alive)
            self._refresh_overlay()
            # the result is already on screen (hide + overlay); reconcile on
            # the IDLE timer — the old 400 ms regen landed exactly when the
            # user made the NEXT trim/move and its GIL churn read as lag
            self._merge_timer.start()

    def _run_deferred_regen(self) -> None:
        self.window.regen_in_memory()

    def _invalidate_geometry(self) -> None:
        if self.snap_engine is not None:
            self.snap_engine.invalidate()
        if self.index is not None:
            self.index.invalidate()

    def after_history_change(self, command=None) -> None:
        """Called by U/REDO with the command that crossed the boundary.

        Instant feedback, no deferred-regen blank: stale base-scene copies of
        everything the command touched are hidden surgically and the restored
        or current entities ride the overlay; the full regen stays coalesced.
        """
        if command is None or getattr(command, "needs_regen", False):
            # unknown scope: only a regen is right;
            # hide what the undo just destroyed so it vanishes NOW (the regen
            # runs in the background and lands later)
            self._invalidate_geometry()
            removed = getattr(command, "removed_handles", None)
            if removed:
                self.window.viewport.hide_handles(removed)
            self.window.regen_in_memory()
            return
        rec = self._stamp_records.get(id(command))
        if rec is not None:
            self._history_toggle_stamp(command, rec)
            return
        touched = []
        for attr in ("entities", "old_entities", "new_entities", "copies",
                     "sources"):
            touched.extend(getattr(command, attr, None) or [])
        if getattr(command, "insert", None) is not None:
            touched.append(command.insert)
        if getattr(command, "entity", None) is not None:
            touched.append(command.entity)
        if getattr(command, "dim", None) is not None:
            touched.append(command.dim)   # AddDimensionCommand, one entity
        for _orig, parts in (getattr(command, "pieces", None) or []):
            touched.extend(parts)
        # hide stale base copies: entities the undo/redo just destroyed
        # (recorded handles) plus every touched survivor's base-scene copy
        hide = list(getattr(command, "removed_handles", None) or [])
        hide += [e.dxf.handle for e in touched if e.is_alive]
        if hide:
            self.window.viewport.hide_handles(hide)
        alive = [e for e in touched
                 if e.is_alive and e.dxf.owner is not None]
        for e in alive:
            if e not in self._pending_render:
                self._pending_render.append(e)
        patchable = self._KNOWN_MODIFY + (
            actions.AddEntityCommand, actions.PasteCommand,
            actions.CopyEntitiesCommand, actions.SnapshotCommand)
        if isinstance(command, patchable):
            # undo/redo of the everyday commands: patch the caches with the
            # restored state instead of a full modelspace rebuild (U is
            # hammered constantly — it must not re-freeze the next pick)
            if self.index is not None:
                self.index.remove_handles(hide)
                self.index.add_entities(alive)
            if self.snap_engine is not None:
                self.snap_engine.remove_handles(hide)
                self.snap_engine.add_entities(alive)
            self._refresh_overlay()
            self._merge_timer.start()
        else:
            self._invalidate_geometry()
            self._refresh_overlay()
            self._regen_timer.start()

    def _history_toggle_stamp(self, command, rec) -> None:
        """Undo/redo of a stamped MOVE/COPY/PASTE: flip the stamp instead of
        re-tessellating anything. Stamp showing -> this is the undo."""
        key = id(command)
        vp = self.window.viewport
        was_on = vp.remove_stamp(key)
        if not was_on and key in self._pending_stamps:
            self._pending_stamps.remove(key)
            was_on = True
        dx, dy = rec["dx"], rec["dy"]
        if was_on:                       # UNDO
            if rec["hidden"]:            # MOVE: base copies are valid again
                vp.unhide_handles(rec["hidden"])
                if self.index is not None:
                    self.index.translate_handles(rec["hidden"], -dx, -dy)
                if self.snap_engine is not None:
                    self.snap_engine.translate_handles(rec["hidden"], -dx, -dy)
            else:                        # PASTE/COPY: the copies are gone
                dead = list(getattr(command, "removed_handles", None) or [])
                if self.index is not None:
                    self.index.remove_handles(dead)
                if self.snap_engine is not None:
                    self.snap_engine.remove_handles(dead)
        else:                            # REDO
            if rec["hidden"]:
                vp.hide_handles(rec["hidden"])
                if self.index is not None:
                    self.index.translate_handles(rec["hidden"], dx, dy)
                if self.snap_engine is not None:
                    self.snap_engine.translate_handles(rec["hidden"], dx, dy)
            else:
                copies = list(getattr(command, "copies", None) or [])
                if self.snap_engine is not None:
                    self.snap_engine.add_entities(copies)
                if self.index is not None:
                    self._index_register_added(command, copies)
                rec["shown"] = [c.dxf.handle for c in copies]
            if (rec["scene"] is None and self._ghost_cache is not None
                    and self._ghost_cache[0] is rec["ents"]):
                rec["scene"] = self._ghost_cache[1]
            if rec["scene"] is not None:
                vp.add_stamp(key, rec["scene"], dx, dy)
            else:
                self._pending_stamps.append(key)
        self._merge_timer.start()
        self.changed.emit()

    def _draw_commands(self):
        return [c for c in self.window.history._undo
                if isinstance(c, actions.AddEntityCommand)]

    def _refresh_overlay(self) -> None:
        document = self.window.document
        if document is None:
            return
        # owner=None means the entity is unlinked from modelspace (erased,
        # kept alive only for undo) — never draw those in the overlay.
        entities = [
            c.entity for c in self._draw_commands()
            if c.entity is not None and c.entity.dxf.owner is not None
            and c.entity.dxf.handle not in self._base_handles
        ]
        entities += [e for e in self._pending_render
                     if e.is_alive and e.dxf.owner is not None
                     and e.dxf.handle not in self._base_handles]
        entities += self.grip_overlay_entities()
        scene = (build_scene_for_entities(document, entities, self._flatten)
                 if entities else None)
        self.window.viewport.set_overlay_scene(scene)
        self.changed.emit()

    # -- pointer input ---------------------------------------------------------
    def on_hover(self, wx: float, wy: float, threshold_world: float) -> None:
        self._cursor = (wx, wy)
        self._pick_tolerance = threshold_world * (PICK_PX / SNAP_PX)
        self.snap_hit = None
        grip_hot = self._grip_drag is not None
        needs_snap = grip_hot or (
            self.tool is not None and self._selecting_for is None
            and not self.tool.entity_picker)
        if getattr(self.window, "_active_layout", "Model") != "Model":
            # The snap engine indexes MODEL geometry; its points are model
            # coordinates and mean nothing on a paper-space sheet.
            needs_snap = False
        if needs_snap and self.osnap_on and self.snap_engine is not None \
                and self.osnap_modes:
            self.snap_hit = self.snap_engine.find(
                (wx, wy), threshold_world,
                kinds=frozenset(self.osnap_modes),
                from_point=self.tool.last_point if self.tool else None,
            )
        self._sync_ghost(wx, wy)

    def _sync_ghost(self, wx: float, wy: float) -> None:
        """MOVE/COPY/PASTE drag preview: the tool exposes ghost_entities +
        ghost_base; the scene builds ONCE (in the background, cached per
        entity list) and each hover only updates the translation uniform —
        the drag stays fluid on any selection size."""
        tool = self.tool
        ents = getattr(tool, "ghost_entities", None) if tool is not None else None
        base = getattr(tool, "ghost_base", None) if tool is not None else None
        if not ents or base is None:
            if self._ghost_on:
                self._ghost_on = False
                self.window.viewport.set_ghost_scene(None)
            return
        if not self._ghost_on:
            scene = self._ghost_scene_for(ents)
            if scene is None:
                return   # tessellating in the background; pops in when ready
            self.window.viewport.set_ghost_scene(scene)
            self._ghost_on = True
        rx, ry = self.resolved_point(wx, wy)
        placement = None
        getter = getattr(tool, "ghost_placement", None)
        if getter is not None:
            placement = getter((rx, ry))
        if placement is None:
            self.window.viewport.set_ghost_offset(rx - base[0], ry - base[1])
        else:
            angle, factor = placement
            self.window.viewport.set_ghost_placement(base, angle, factor)

    def _ghost_scene_for(self, ents):
        """Cached ghost scene, or None while a worker tessellates it."""
        if self._ghost_cache is not None and self._ghost_cache[0] is ents:
            return self._ghost_cache[1]
        if self._ghost_wanted is not ents:
            self._ghost_wanted = ents
            worker = _GhostWorker(self.window.document, ents, self._flatten)
            worker.done.connect(self._on_ghost_done)
            self._ghost_workers.add(worker)
            worker.start()
        return None

    def _on_ghost_done(self, ents, scene) -> None:
        worker = self.sender()
        if worker in self._ghost_workers:
            worker.wait()   # thread has emitted; joins immediately
            self._ghost_workers.discard(worker)
        if scene is not None:
            if self._ghost_wanted is ents:
                self._ghost_cache = (ents, scene)
            tool = self.tool
            if (not self._ghost_on and tool is not None
                    and getattr(tool, "ghost_entities", None) is ents):
                self.window.viewport.set_ghost_scene(scene)
                self._ghost_on = True
                base = getattr(tool, "ghost_base", None)
                if base is not None and self._cursor is not None:
                    rx, ry = self.resolved_point(*self._cursor)
                    self.window.viewport.set_ghost_offset(
                        rx - base[0], ry - base[1])
        # commits that happened before the tessellation landed
        for key in list(self._pending_stamps):
            rec = self._stamp_records.get(key)
            if rec is None:
                self._pending_stamps.remove(key)
                continue
            if rec["ents"] is not ents:
                continue
            self._pending_stamps.remove(key)
            if scene is not None:
                rec["scene"] = scene
                self.window.viewport.add_stamp(key, scene, rec["dx"], rec["dy"])
            else:
                # tessellation failed: let a background regen reconcile
                del self._stamp_records[key]
                self._regen_timer.start()
        self.changed.emit()

    def in_selection_mode(self) -> bool:
        return self.tool is None or self._selecting_for is not None

    def wants_drag_rect(self) -> bool:
        """Left press should defer to release (drag = window rectangle)."""
        return (self.in_selection_mode()
                or (self.tool is not None and self.tool.accepts_target_windows))

    def start_window(self, wx: float, wy: float) -> None:
        """Anchor a selection window (drag start). Idempotent during a drag."""
        if self._window_anchor is None:
            self._window_anchor = (wx, wy)
            self.changed.emit()

    def on_click(self, wx: float, wy: float, shift: bool = False) -> None:
        if self.in_selection_mode():
            self._selection_click(wx, wy, shift)
            self.changed.emit()
            return
        if self.tool is None:
            return
        self.tool.shift = shift
        if self.tool.accepts_target_windows and self.index is not None:
            if self._window_anchor is not None:
                # complete a target rectangle (drag or click-click). AutoCAD
                # quick-mode TRIM/EXTEND treats BOTH directions as crossing:
                # whatever the rect touches is a target.
                ax, ay = self._window_anchor
                self._window_anchor = None
                rect = (min(ax, wx), min(ay, wy), max(ax, wx), max(ay, wy))
                handles = self.index.crossing(rect)
                entities = [e for h in handles
                            if (e := self.index.entity(h)) is not None
                            and e.is_alive]
                self.tool.on_target_entities(entities, rect)
                self.changed.emit()
                return
            if self.index.pick((wx, wy), self._pick_tolerance) is None:
                # empty click: anchor a target window instead of "nothing"
                self._window_anchor = (wx, wy)
                self.changed.emit()
                return
        self.tool.on_point(self.resolved_point(wx, wy))
        self.changed.emit()

    def _paper_select_mode(self) -> bool:
        """Paper-space selection is live: layout tab, not inside MSPACE."""
        return (getattr(self.window, "_active_layout", "Model") != "Model"
                and getattr(self.window, "_active_vp", None) is None
                and self.window.document is not None)

    def _selection_click(self, wx: float, wy: float, shift: bool) -> None:
        if self._paper_select_mode():
            # Paper space: the only selectable entity (v0.1) is a viewport,
            # picked by its border like AutoCAD. No selection windows here.
            self._window_anchor = None
            layout = self.window.document.doc.layouts.get(
                self.window._active_layout)
            vp = layout_ops.viewport_border_hit(
                layout, wx, wy, self._pick_tolerance)
            self.paper_vp = vp
            if vp is not None:
                self.window.command_line.echo(tr("{count} selected.", count=1))
            return
        if self.index is None:
            if self.window.document is None:
                return
            self.index = GeometryIndex(self.window.document)
        if self._window_anchor is not None:
            # second corner: apply window (L->R, fully inside) or crossing
            ax, ay = self._window_anchor
            self._window_anchor = None
            rect = (min(ax, wx), min(ay, wy), max(ax, wx), max(ay, wy))
            crossing = wx < ax
            hits = self.index.crossing(rect) if crossing else self.index.window(rect)
            if crossing and not shift:
                self._crossing_rects.append(rect)
            if shift:
                self.selection -= self._with_groups(hits)
            else:
                self.selection |= self._with_groups(hits)
            self._echo_count()
            return
        previous = self._cycle
        if shift:
            # Shift removes from the selection; cycling under it would take
            # away something the user never pointed at. Reset BEFORE picking,
            # or this very click already advances to the next candidate.
            self.reset_pick_cycle()
            previous = None
        handle = self.pick_cycling((wx, wy))
        if handle is None:
            self._window_anchor = (wx, wy)
            return
        if shift:
            self.reset_pick_cycle()
            self.selection -= self._with_groups([handle])
        else:
            if previous is not None and self._cycle is not None \
                    and previous[1] and self._cycle[2] != previous[2]:
                # cycled: swap the previous candidate out instead of adding
                # the second one -- "I meant the other object", not "both".
                self.selection -= self._with_groups([previous[1][previous[2]]])
            self.selection |= self._with_groups([handle])
        self._echo_count()

    def _with_groups(self, handles) -> set:
        """Picking one member of a selectable group takes the whole group —
        the behaviour that makes GROUP worth having (p. 861), switched off
        wholesale by PICKSTYLE 0."""
        from core.groups import expand

        document = self.window.document
        if document is None:
            return set(handles)
        return expand(document, handles)

    def _echo_count(self) -> None:
        if self.selection:
            self.window.command_line.echo(
                tr("{count} selected.", count=len(self.selection)))

    def cursor_mode(self) -> str:
        """What the cursor should be right now, AutoCAD's three states.

        ``"idle"``   crosshair with the pick box, nothing running;
        ``"pick"``   pick box alone, at a Select Objects prompt or while a
                     command picks an object (TRIM's targets, FILLET's lines);
        ``"point"``  crosshair alone, while a command asks for a point.

        The pickbox "appears in editing commands" at the Select Objects
        prompt (PICKBOX, p.2451) — and AutoCAD drops the crosshair there,
        which is the difference a hand notices.
        """
        if self._selecting_for is not None:
            return "pick"
        if self.tool is None:
            return "idle"
        return "pick" if self.tool.entity_picker else "point"

    def crossing_rects(self):
        """The crossing rectangles of the selection a tool is about to get."""
        return list(self._crossing_rects)

    def selection_rect(self):
        """(rect, crossing?) while a window pick is in progress."""
        if self._window_anchor is None or self._cursor is None:
            return None
        ax, ay = self._window_anchor
        wx, wy = self._cursor
        rect = (min(ax, wx), min(ay, wy), max(ax, wx), max(ay, wy))
        return rect, wx < ax

    def finish_selection(self) -> None:
        """Enter during a tool's 'Select objects' phase."""
        tool = self._selecting_for
        if tool is None:
            return
        self._selecting_for = None
        entities = self._selection_entities()
        self._window_anchor = None
        # keep the highlight while the command runs (AutoCAD behavior)
        tool.on_selection(entities)
        self.changed.emit()

    def resolved_point(self, wx: float, wy: float) -> tuple[float, float]:
        """Snap wins over ortho/polar, AutoCAD-style."""
        if self.tool is not None and self.tool.entity_picker:
            return (wx, wy)  # object picking: raw cursor, no snap/ortho
        if self.snap_hit is not None:
            return (self.snap_hit.x, self.snap_hit.y)
        anchor = self.tool.last_point if self.tool else None
        if anchor is not None and (self.ortho_on or self.polar_on):
            dx, dy = wx - anchor[0], wy - anchor[1]
            if self.polar_on and not self.ortho_on:
                ang = math.atan2(dy, dx)
                step = math.radians(45.0)
                ang = round(ang / step) * step
                d = math.hypot(dx, dy)
                return (anchor[0] + d * math.cos(ang),
                        anchor[1] + d * math.sin(ang))
            if abs(dx) >= abs(dy):
                return (wx, anchor[1])
            return (anchor[0], wy)
        return (wx, wy)

    # -- prompt input ----------------------------------------------------------
    def on_text(self, text: str) -> bool:
        """Prompt input while a tool is active. True if consumed."""
        if self._selecting_for is not None:
            if not text.strip():
                self.finish_selection()
                return True
            self.window.command_line.echo(self._selecting_for.selection_prompt())
            return True
        if self.tool is None:
            return False
        stripped = text.strip()
        if not stripped:
            self.tool.on_enter()
            self.changed.emit()
            return True
        if self.tool.on_option(stripped):
            self.changed.emit()
            return True
        direction = None
        anchor = self.tool.last_point
        if anchor is not None and self._cursor is not None:
            constrained = self.resolved_point(*self._cursor)
            direction = math.atan2(constrained[1] - anchor[1],
                                   constrained[0] - anchor[0])
        try:
            point = parse_point(stripped, anchor, direction)
        except CoordinateError as exc:
            self.window.command_line.echo(tr("Invalid point: {error}",
                                             error=str(exc)))
            return True
        if point is None:
            self.window.command_line.echo(tr("Invalid input."))
            return True
        self.tool.on_point((point.x, point.y))
        self.changed.emit()
        return True

    # -- viewport painting hooks ----------------------------------------------
    def preview_segments(self):
        if self.tool is None or self._cursor is None:
            return []
        return self.tool.preview_segments(self.resolved_point(*self._cursor))

    def preview_dimension(self):
        """Rich dimension preview (frame + measurement) for the dim tools."""
        if self.tool is None or self._cursor is None:
            return None
        fn = getattr(self.tool, "preview_dimension", None)
        if fn is None:
            return None
        return fn(self.resolved_point(*self._cursor))

    # -- grips (selected-entity editing points) --------------------------------
    def grip_points(self):
        """[(x, y, role, handle, index)] for the current idle selection."""
        # While a grip is hot, hide the rest (AutoCAD/BricsCAD show only the
        # moving grip); this also avoids flashing the new grips of a just-
        # inserted vertex before the user drops it.
        if self._grip_drag is not None:
            return []
        if self._paper_select_mode():
            vp = self.paper_vp
            if self.tool is not None or vp is None or not vp.is_alive:
                return []
            return [(x, y, role, vp.dxf.handle, i)
                    for i, (x, y, role) in enumerate(layout_ops.viewport_grips(vp))]
        if self.tool is not None or not self.selection or self.index is None:
            return []
        # per-frame AND per-hover (grip_at): cache per (version, selection)
        key = (self.index.version, frozenset(self.selection))
        cached = self._grips_cache
        if cached is not None and cached[0] == key:
            return cached[1]
        out = []
        for h in sorted(self.selection)[:200]:  # cap: grips get noisy past that
            e = self.index.entity(h)
            if e is None or not e.is_alive:
                continue
            for i, (x, y, role) in enumerate(entity_grips(e)):
                out.append((x, y, role, h, i))
        self._grips_cache = (key, out)
        return out

    def grip_at(self, wx: float, wy: float, tol: float):
        for x, y, role, h, i in self.grip_points():
            if abs(x - wx) <= tol and abs(y - wy) <= tol:
                return (x, y, role, h, i)
        return None

    def begin_grip_drag(self, grip) -> None:
        from core.actions import SnapshotCommand
        from core.select import entity_grips

        gx, gy, role, handle, index = grip
        if self._paper_select_mode() and self.paper_vp is not None:
            # viewport grip: only the rubber rectangle moves until the drop
            self._grip_drag = (_VP_GRIP, index, role, None)
            self.window.viewport.vp_drag_rect = layout_ops.viewport_rect(
                self.paper_vp)
            return
        entity = self.index.entity(handle)
        if entity is None:
            return
        snap = SnapshotCommand([entity])   # captures the pre-grab state
        if entity.dxftype() == "IMAGE":
            # Undo/redo of an image grip must regen: the overlay cannot
            # move pixels, only the frame.
            snap.needs_regen = True
        self._grip_drag = (handle, index, role, snap)
        # Hide the base-scene copy ONCE (a full-scene re-upload); from here
        # the live entity rides the cheap 1-entity overlay each frame.
        self.window.viewport.hide_handles([handle])
        self._refresh_overlay()

    def grip_target(self, wx: float, wy: float) -> tuple[float, float]:
        """Where the hot grip should sit: snap wins, then ortho/polar."""
        if self.snap_hit is not None:
            return (self.snap_hit.x, self.snap_hit.y)
        return (wx, wy)

    def update_grip_drag(self, wx: float, wy: float) -> None:
        if self._grip_drag is None:
            return
        if self._grip_drag[0] == _VP_GRIP:
            _m, index, role, _ = self._grip_drag
            if self.paper_vp is not None and self.paper_vp.is_alive:
                self.window.viewport.vp_drag_rect = layout_ops.viewport_drag_rect(
                    self.paper_vp, index, role, (wx, wy))
                self.window.viewport.update()
            return
        handle, index, role, _snap = self._grip_drag
        entity = self.index.entity(handle)
        if entity is not None:
            if role.startswith("dim_"):
                # A dimension only re-renders at the drop (a render per
                # mouse move would churn one *D block per frame) — but the
                # drag shows a live dimension preview instead of nothing.
                self.grip_align_marker = None
                if role == "dim_defpoint":
                    wx, wy, marker = _align_dim_line(
                        self.window.document, entity, wx, wy,
                        12.0 / self.window.viewport.view.scale
                        if self.window.viewport.view.scale else None)
                    self.grip_align_marker = marker
                self.grip_dim_preview = _dim_grip_preview(entity, role,
                                                          wx, wy)
                self.window.viewport.update()
                return
            apply_grip_edit(entity, index, role, (wx, wy))
            # per frame: rebuild only the dragged entity's overlay — no
            # index rebuild, no whole-scene re-upload
            self._refresh_overlay()

    def finish_grip_drag(self, wx: float, wy: float) -> None:
        if self._grip_drag is None:
            return
        if self._grip_drag[0] == _VP_GRIP:
            _m, index, role, _ = self._grip_drag
            self._grip_drag = None
            self.window.viewport.vp_drag_rect = None
            vp = self.paper_vp
            if vp is not None and vp.is_alive:
                command = layout_ops.viewport_grip_command(
                    vp, index, role, (wx, wy))
                if command is not None:
                    self._execute(command)   # needs_regen shows the result
            self.changed.emit()
            return
        handle, index, role, snap = self._grip_drag
        self._grip_drag = None
        entity = self.index.entity(handle)
        self.grip_dim_preview = None
        self.grip_align_marker = None
        if entity is not None and role.startswith("dim_"):
            if role == "dim_defpoint":
                # the drop honors the same magnet the drag showed
                wx, wy, _marker = _align_dim_line(
                    self.window.document, entity, wx, wy,
                    12.0 / self.window.viewport.view.scale
                    if self.window.viewport.view.scale else None)
            # Route through the dedicated command: it re-renders the block
            # and drops the old one, which the generic snapshot cannot undo.
            self.window.viewport.unhide_handles([handle])
            if role == "dim_text":
                # Pure translation: a foreign dimension keeps its author's
                # block stroke for stroke (DIMTEDIT still offers the full
                # re-rendering options when asked for them).
                command = actions.DimTextTranslateCommand(entity, (wx, wy))
            else:
                command = actions.DimGripCommand(
                    entity, role[len("dim_"):], (wx, wy))
            self._execute(command)
            self.changed.emit()
            return
        if entity is not None:
            apply_grip_edit(entity, index, role, (wx, wy))
            snap.commit(self.window.document)
            self.window.history._undo.append(snap)
            self.window.history._redo.clear()
            # grips/snap see the new shape; both caches are patched, not
            # rebuilt (a full rebuild froze the next pick on big files)
            self._drop_conflicting_stamps([handle])
            if self.snap_engine is not None:
                self.snap_engine.remove_handles([handle])
                self.snap_engine.add_entities([entity])
            if self.index is not None:
                self.index.remove_handles([handle])
                self.index.add_entities([entity])
            # The base copy is hidden since the grab and the grip overlay
            # empties on release: without this the entity VANISHED until
            # the deferred merge regen (seconds on a big file).
            if entity not in self._pending_render:
                self._pending_render.append(entity)
            # An entity DRAWN this session sits in _base_handles and the
            # overlay excludes those (no double-draw with the base) — but
            # its base copy is hidden now, so the exclusion would blank it:
            # a just-created MTEXT lagged on every grip move while a text
            # from the opened file moved instantly.
            self._base_handles.discard(handle)
            self._refresh_overlay()
            if entity.dxftype() == "IMAGE":
                # The overlay shows only the frame; the pixels need the
                # real regen to land at their new size.
                self.window.regen_in_memory()
            else:
                self._merge_timer.start()

    def grip_overlay_entities(self):
        if self._grip_drag is None:
            return []
        entity = self.index.entity(self._grip_drag[0])
        return [entity] if entity is not None and entity.is_alive else []

    def highlight_geometry(self):
        """(segments, circles, boxes) of the current selection, world coords.

        Called every paint frame: cached per (index version, selection) —
        the isin sweep over a cadastre's 1.35 M rows costs ~40 ms and must
        not run per frame.
        """
        if self._paper_select_mode():
            empty = np.empty((0, 4))
            vp = self.paper_vp
            if vp is None or not vp.is_alive:
                return empty, empty, empty
            return empty, empty, np.array([layout_ops.viewport_rect(vp)])
        if not self.selection or self.index is None:
            empty = np.empty((0, 4))
            return empty, empty, empty
        key = (self.index.version, frozenset(self.selection))
        cached = self._highlight_cache
        if cached is not None and cached[0] == key:
            return cached[1]
        result = (self.index.segments_of(self.selection),
                  self.index.circles_of(self.selection),
                  self.index.boxes_of(self.selection))
        self._highlight_cache = (key, result)
        return result
