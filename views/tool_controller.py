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
from core import gc_guard
from core import layouts as layout_ops
from core.coords import (CoordinateError, ParsedPoint, is_direct_distance,
                         parse_point)
from core.i18n import tr
from core.select import GeometryIndex, apply_grip_edit, entity_grips
from core.snap import SnapEngine, SnapHit
from render.backend import (_flatten_distance, build_scene_for_entities,
                            curve_quality)
from tools.attributes import ATTRIBUTE_TOOL_CLASSES
from tools.base import Tool, ToolContext
from tools.blocks import BLOCK_TOOL_CLASSES
from tools.cleanup_tools import CLEANUP_TOOL_CLASSES
from tools.dimension import DIM_TOOL_CLASSES
from tools.draw import TOOL_CLASSES
from tools.edit import EDIT_TOOL_CLASSES
from tools.construct import CONSTRUCT_TOOL_CLASSES
from tools.inquiry import INQUIRY_TOOL_CLASSES
from tools.modify import MODIFY_TOOL_CLASSES
from tools.layout_tools import LAYOUT_TOOL_CLASSES
# #38: the everyday commands that were missing, one module each
from tools.align import ALIGN_TOOL_CLASSES
from tools.boundary import BOUNDARY_TOOL_CLASSES
from tools.donut import DONUT_TOOL_CLASSES
from tools.lengthen import LENGTHEN_TOOL_CLASSES
from tools.annoscale import ANNO_TOOL_CLASSES
from tools.scaletext import SCALETEXT_TOOL_CLASSES
from tools.leaders import LEADER_TOOL_CLASSES
from tools.plot_window import PLOT_WINDOW_TOOL_CLASSES   # #52
from tools.dim_commands import DIMCMD_TOOL_CLASSES   # #39
from tools.xrefs import XREF_TOOL_CLASSES
from tools.zoom_window import ZOOM_TOOL_CLASSES   # #80
from tools.ucs_tool import UCS_TOOL_CLASSES         # #91
from views.apertures import GRIP_PX, PICKBOX_DEFAULT, SNAP_PX

# Overlay entities beyond this schedule an idle merge into the base scene
# (the overlay is re-tessellated per edit, so it must not grow unbounded).
MERGE_THRESHOLD = 50
#: An undo or redo touching more objects than this is shown by a background
#: regen, not re-drawn one by one on the GUI thread (see after_history_change).
BIG_EDIT = 2000
#: A drawing with more objects than this in the current space waits for the
#: background warmer instead of building its caches on the GUI thread.
WARM_GUARD = 3000


def _look_only(command) -> bool:
    """A command that changes how objects look, never where they are or
    whether they show: colour, linetype, lineweight (not the layer, which
    may be off or frozen)."""
    return (isinstance(command, actions.SetPropertyCommand)
            and command.prop in ("color", "linetype", "lineweight",
                                 "true_color", "ltscale"))
# MOVE/COPY/PASTE commits at or above this size reuse the ghost tessellation
# as a "stamp" instead of re-tessellating into the overlay (a 3000-entity
# paste re-tessellated ~3.5 s on the UI thread; the stamp costs nothing).
STAMP_MIN = 25
# AutoCAD's GRIPOBJLIMIT (Command Reference p.2339): grips are suppressed
# when the selection holds MORE than this many objects. 0 = never suppress.
GRIPOBJLIMIT_DEFAULT = 100
SETTING_GRIPOBJLIMIT = "selection/gripobjlimit"


def gripobjlimit() -> int:
    """The live GRIPOBJLIMIT (Options > Selection). Saved in the registry,
    as the reference says it is."""
    from core.prefs import int_pref

    return int_pref(SETTING_GRIPOBJLIMIT, GRIPOBJLIMIT_DEFAULT, 0, 32767)


class _CacheWarmer(QThread):
    """Build the snap/pick caches off the UI thread right after a document
    opens — the first click on a cadastre paid a 5-8 s synchronous walk."""

    # document, index, snap, revision, space name, model snap (sheet only)
    done = Signal(object, object, object, int, str, object)

    def __init__(self, document, model_engine: bool = True) -> None:
        super().__init__()
        self.setObjectName("cache-warmer")
        self._document = document
        self._model_engine = model_engine

    def run(self) -> None:
        from core import gc_guard

        with gc_guard.paused():      # never collect Qt garbage off the GUI thread
            self._run()

    def _run(self) -> None:
        revision = self._document.revision
        # Which space these caches describe. NOT derivable from the
        # revision: a Model/Layout switch marks the document dirty WITHOUT
        # bumping it (mark_dirty_no_revision, so the per-tab scene cache
        # survives), so a warmer started on the Model tab would otherwise
        # look fresh after the user has moved to a sheet -- and the sheet
        # would be picked against the model's geometry.
        space = self._document.space_name
        index = GeometryIndex(self._document)
        engine = SnapEngine(self._document)
        # On a sheet the cursor also snaps THROUGH the viewports to the
        # model: that engine is warmed here too, or the first hover over a
        # viewport of a big plan would pay the whole model walk in the GUI.
        model_engine = None
        try:
            index._build()
            engine._build()
            if (self._model_engine and space != "Model"
                    and not getattr(self._document, "edit_block", None)):
                model_engine = SnapEngine(
                    self._document, space=self._document.doc.modelspace())
                model_engine._build()
        except Exception:
            index = engine = model_engine = None   # doc mutated mid-walk
        self.done.emit(self._document, index, engine, revision, space,
                       model_engine)


class _GhostWorker(QThread):
    """Tessellate the drag preview off the UI thread (big selections take
    seconds; Ctrl+V must not freeze). Same GIL/discard rules as RegenWorker."""

    done = Signal(object, object)   # ents list, Scene | None

    def __init__(self, document, ents, flatten: float, canvas=None) -> None:
        super().__init__()
        self.setObjectName("ghost")
        self._document = document
        self._ents = ents
        self._flatten = flatten
        self._canvas = canvas

    def run(self) -> None:
        from core import gc_guard

        with gc_guard.paused():      # never collect Qt garbage off the GUI thread
            self._run()

    def _run(self) -> None:
        try:
            scene = build_scene_for_entities(
                self._document, self._ents, self._flatten, self._canvas)
        except Exception:
            scene = None    # doc mutated mid-read: caller falls back to regen
        self.done.emit(self._ents, scene)

ALL_TOOL_CLASSES = {**TOOL_CLASSES, **EDIT_TOOL_CLASSES, **BLOCK_TOOL_CLASSES,
                    **DIM_TOOL_CLASSES, **LAYOUT_TOOL_CLASSES, **LEADER_TOOL_CLASSES,
                    **CONSTRUCT_TOOL_CLASSES, **INQUIRY_TOOL_CLASSES,
                    **MODIFY_TOOL_CLASSES, **CLEANUP_TOOL_CLASSES,
                    **ATTRIBUTE_TOOL_CLASSES,
                    **LENGTHEN_TOOL_CLASSES, **ALIGN_TOOL_CLASSES,
                    **ANNO_TOOL_CLASSES,
                    **BOUNDARY_TOOL_CLASSES, **DONUT_TOOL_CLASSES,
                    **SCALETEXT_TOOL_CLASSES, **DIMCMD_TOOL_CLASSES,
                    **XREF_TOOL_CLASSES, **PLOT_WINDOW_TOOL_CLASSES,
                    **ZOOM_TOOL_CLASSES, **UCS_TOOL_CLASSES}


#: name -> (owner, windows using it). The registry is process-wide and a
#: process may hold several windows, each activating the same plugin: the
#: second must find its own names already there and count itself in, and
#: a name only leaves when the last window lets go.
_TOOL_OWNERS: dict[str, list] = {}


def register_tool_classes(mapping: dict, owner: str = "plugin") -> None:
    """A plugin's tools join the ONE registry ``start_tool`` reads.

    A name the core owns, or another plugin owns, refuses the whole set: a
    plugin may add commands, never replace LINE.
    """
    clash = sorted(n.upper() for n in mapping
                   if n.upper() in ALL_TOOL_CLASSES
                   and _TOOL_OWNERS.get(n.upper(), ("core",))[0] != owner)
    if clash:
        raise ValueError(f"tool names already registered: {', '.join(clash)}")
    for name, cls in mapping.items():
        key = name.upper()
        if key in _TOOL_OWNERS:
            _TOOL_OWNERS[key][1] += 1
        else:
            ALL_TOOL_CLASSES[key] = cls
            _TOOL_OWNERS[key] = [owner, 1]


def unregister_tool_classes(names, owner: str = "plugin") -> None:
    for name in names:
        key = name.upper()
        record = _TOOL_OWNERS.get(key)
        if record is None or record[0] != owner:
            continue
        record[1] -= 1
        if record[1] <= 0:
            _TOOL_OWNERS.pop(key, None)
            ALL_TOOL_CLASSES.pop(key, None)

# Sentinel first element of _grip_drag while a VIEWPORT grip is hot — the
# paper-space grip flow shares the widget's click-move-click plumbing but
# none of the modelspace snapshot/overlay machinery.
_VP_GRIP = "__viewport__"


def _dim_line_candidates(document):
    """(handle, angle mod 180, x, y) of every linear/aligned dimension.

    The magnet below runs on EVERY mouse move of a dimension-line grip, and
    it used to ``query("DIMENSION")`` the whole modelspace each time -- a
    full walk of the drawing per frame, which is exactly why dragging a
    dimension dragged on a big plan. Nothing but an edit can change the
    answer, and every edit bumps the revision.
    """
    cached = getattr(document, "_dim_align_cache", None)
    if cached is not None and cached[0] == document.revision:
        return cached[1]
    out = []
    for dim in document.modelspace().query("DIMENSION"):
        if (dim.dxf.get("dimtype", 0) & 7) not in (0, 1):
            continue
        defpoint = dim.dxf.get("defpoint", None)
        if defpoint is None:
            continue
        out.append((dim.dxf.get("handle", None),
                    float(dim.dxf.get("angle", 0.0)) % 180.0,
                    defpoint.x, defpoint.y))
    try:
        document._dim_align_cache = (document.revision, out)
    except Exception:
        pass
    return out


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
    handle = entity.dxf.get("handle", None)
    for other, other_angle, x, y in _dim_line_candidates(document):
        if other is handle or abs(other_angle - angle) > 0.01:
            continue
        coord = (x, y)[axis]
        distance = abs((wx, wy)[axis] - coord)
        if distance <= threshold and (best is None or distance < best[0]):
            best = (distance, coord)
    if best is None:
        return wx, wy, None
    snapped = [wx, wy]
    snapped[axis] = best[1]
    return snapped[0], snapped[1], (snapped[0], snapped[1])


def _text_carries_line(dim) -> bool:
    """A linear or aligned dimension whose DIMTMOVE is 0: dragging its text
    moves its dimension line (DIMTMOVE, Command Reference)."""
    if int(dim.dxf.get("dimtype", 0)) & 7 not in (0, 1):
        return False
    try:
        return int(dim.override().get("dimtmove", 0) or 0) == 0
    except Exception:  # noqa: BLE001 -- an odd style: keep the plain move
        return False


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
    from core.dim_commands import measurement_text

    if role == "dim_text":
        return {"text_at": (wx, wy),
                "text": measurement_text(entity, measurement)
                if measurement is not None else ""}
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
            "text": measurement_text(entity, length)}


def _track_label(kind: str) -> str:
    """AutoCAD's tooltip word for a tracking source: the snap mode's name
    (Endpoint, Midpoint...) or Polar for the last point."""
    from core import osnap as osnap_modes
    from core.i18n import tr

    if kind == "polar":
        return tr("Polar")
    label = osnap_modes.label_of(kind)
    return tr(label) if label else kind.capitalize()


class ToolController(QObject):
    changed = Signal()  # something visual changed: repaint the viewport
    TRACK_DWELL_MS = 300          # pause on a snap point this long to acquire it
    TRACK_MAX = 8                 # acquired points kept, oldest dropped first

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.tool: Optional[Tool] = None
        self.osnap_on = True
        # Which snaps are running (core.osnap keys). The status-bar menu and
        # the Drafting Settings dialog write here.
        from core import osnap as osnap_modes

        self.osnap_modes = set(osnap_modes.from_bits(osnap_modes.DEFAULT_BITS))
        # A one-shot override (typed END/TAN/NONE..., or picked from the
        # Shift+right-click menu): the snaps for the NEXT point only, running
        # modes or not. None = no override; an empty set = no snap at all.
        self.osnap_override: Optional[frozenset] = None
        # The selection filter by type (core.pickfilter): the type names a
        # pick may add, or None when it is off. Kept across drawings, like
        # the status-bar toggles.
        self.pick_filter: Optional[frozenset] = None
        # A point modifier in progress (FROM, M2P): its own points are
        # collected here and ONE point reaches the tool at the end.
        self._modifier: Optional[dict] = None
        self.ortho_on = False
        self.polar_on = False
        self.snap_on = False        # SNAP / F9: the cursor jumps by the grid
        self.shift_held = False     # AutoCAD: Shift held = ortho flipped for the moment
        self.cycling_on = True      # SELECTIONCYCLING (Ctrl+W)
        # OTRACK / F11: object snap tracking. Pausing on an object snap
        # point acquires it (a small +); dashed alignment paths run from
        # every acquired point along the ortho (and polar) angles, and the
        # cursor locks onto a path, or onto two paths' intersection.
        self.otrack_on = False
        self._track_points: list = []            # (x, y, kind) acquired
        self._track_candidate = None
        self._track_tolerance = 1.0
        self.track_hint = None                   # (source, point, label) while locked
        from PySide6.QtCore import QTimer

        self._track_timer = QTimer(self)
        self._track_timer.setSingleShot(True)
        self._track_timer.setInterval(self.TRACK_DWELL_MS)
        self._track_timer.timeout.connect(self.acquire_now)
        # EXT and PAR: tracking snaps. Pausing on the end of a line or arc
        # (EXT) or on a line (PAR, once there is a first point) acquires it;
        # the cursor then locks onto the extension, or onto the parallel
        # through the last point.
        self._ext_sources: list = []
        self._par_dirs: list = []
        self._xp_candidate = None
        self._xp_timer = QTimer(self)
        self._xp_timer.setSingleShot(True)
        self._xp_timer.setInterval(self.TRACK_DWELL_MS)
        self._xp_timer.timeout.connect(self.acquire_tracking_snap)
        # DYN / F12: dynamic input -- the prompt and the live coordinates
        # beside the cursor, and bare coordinates relative after a first point
        self.dyn_on = False
        self.current_prompt = ""
        #: MULTIPLE: the command to start again each time it ends, until Esc
        self.repeat_name: str | None = None
        self.snap_engine: Optional[SnapEngine] = None
        self.snap_hit: Optional[SnapHit] = None
        self._cursor: Optional[tuple[float, float]] = None
        # The overlay's curve tolerance: cached by the _flatten property
        # under (document, space, VIEWRES).
        self._flatten_key = None
        self._flatten_value = 0.01
        self._base_handles: set[str] = set()
        self._clipboard = None   # (list[entity copies], base point) for paste
        self._clipboard_src: list = []   # source handles aligned w/ clipboard
        self._clip_id: Optional[str] = None   # this window's copy on the system clipboard
        self._foreign_clip: Optional[tuple] = None   # (id, (sources, base)) read back
        self._clip_writers: set = set()   # ClipWriter threads in flight
        self._clip_pending: Optional[tuple] = None   # a big copy, not yet out
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
        self._sel_entities_cache = None
        self._warmers: set = set()        # background cache builders
        # Selection state (idle noun set, or the set a tool is acquiring).
        self.index: Optional[GeometryIndex] = None
        self.selection: set[str] = set()
        # typed answers at "Select objects:" (_selection_option)
        self._sel_remove = False          # Remove(R) mode until Add(A)
        self._sel_force: Optional[str] = None   # "W"/"C" for the next window
        self._previous_selection: set[str] = set()   # Previous(P)
        self._sel_history: list[set[str]] = []       # Undo(U)
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
        #: Where the hot grip was grabbed: the base point of the grip edit,
        #: what ORTHO, POLAR and PERpendicular measure from (#60).
        self._grip_base = None
        #: The associative dimensions at the grab (History.dimassoc_state)
        self._grip_dimassoc = None
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
    def attach_document(self, document, flatten: Optional[float] = None,
                        keep_history: bool = False) -> None:
        """Work on ``document`` from now on. ``keep_history``: a drawing tab
        coming back keeps its undo and redo (#71)."""
        self.snap_engine = SnapEngine(document)
        self._model_snap_engine = None
        self._through_vp = {}
        self.lastpoint = (0.0, 0.0)
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
        self._start_warmer(document)
        self.selection = set()
        self._selecting_for = None
        self._window_anchor = None
        self._flatten_key = None
        if flatten:
            # the open path already derived the scene's tolerance: adopt it
            # rather than derive the same number a second time
            self._flatten_key = self._flatten_key_for(document)
            self._flatten_value = flatten
        self._base_handles = set()
        # Entities queued for the overlay belong to the PREVIOUS drawing:
        # left here, File > New drew the last dimensions' lines over the
        # empty canvas (Marco, 2026-09-22), their blocks being unknown to
        # the new document.
        self._pending_render = []
        self.window.history.document = document
        if not keep_history:
            self.window.history.clear()
        self._refresh_overlay()

    def _start_warmer(self, document) -> None:
        # the model engine a sheet snaps through its viewports with is kept
        # across tab switches (see space_changed); only build it when missing
        warmer = _CacheWarmer(document, self._model_snap_engine is None)
        warmer.done.connect(self._on_caches_warm)
        self._warmers.add(warmer)
        gc_guard.start(warmer)

    def caches_warming(self) -> bool:
        """A warmer is still building the snap cache the cursor would need,
        the one in hand is not built yet, and the drawing is big enough for
        building it here to be felt (a small one builds in milliseconds)."""
        return (bool(self._warmers) and self._big_space()
                and (self.snap_engine is None or self.snap_engine._dirty))

    def _big_space(self) -> bool:
        document = self.window.document
        try:
            return document is not None and \
                len(document.current_space()) > WARM_GUARD
        except Exception:  # noqa: BLE001
            return False

    def _on_caches_warm(self, document, index, engine, revision,
                        space, model_engine=None) -> None:
        worker = self.sender()
        if worker in self._warmers:
            worker.wait()   # thread has emitted; joins immediately
            self._warmers.discard(worker)
        if index is None or engine is None:
            return
        if (self.window.document is not document
                or document.revision != revision
                or document.space_name != space):
            return          # edited, reopened, or a different space: stale
        # adopt only what the user has not built already
        if self.index is not None and self.index._dirty:
            self.index = index
            self._highlight_cache = None
            self._grips_cache = None
        if self.snap_engine is not None and self.snap_engine._dirty:
            self.snap_engine = engine
        if model_engine is not None and self._model_snap_engine is None:
            self._model_snap_engine = model_engine
            self._model_engine_revision = revision

    def mark_scene_merged(self) -> None:
        """A full regen just happened: overlay entities now live in the base."""
        self._base_handles = {
            e.dxf.handle
            for c in self._draw_commands()
            for e in self._command_entities(c)
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
        if self.space_vp is not None:
            # An active viewport is for NAVIGATING the model (wheel, pan,
            # ZOOM nXP/E/W, VPLOCK), not for editing it: the pick index and
            # snap engine of a real plan's whole model cost 2 s of GIL on
            # entry and 0.4 s of frozen GUI, for a way of editing nobody
            # uses (Marco, 2026-09-28: "no deberíamos poder editar dentro
            # del viewport"). Drawing happens in the Model tab; the sheet's
            # own commands (MVIEW…) want the paper, so PSPACE first.
            self.window.command_line.echo(
                tr("** {name} is not available inside a viewport — pan, "
                   "zoom and VPLOCK only. PSPACE returns to the sheet; edit "
                   "the drawing in the Model tab. **", name=name))
            return
        if self.window.document is None:
            self.window.new_document()
        if self.tool is not None:
            self.tool.on_cancel()
        if not self.selection:
            self._crossing_rects = []
        ctx = ToolContext(
            execute=self._execute,
            prompt=self._on_prompt,
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
                entities = self._unlocked_for(self.tool, self._selection_entities())
                self._previous_selection = set(self.selection)
                self.tool.on_selection(entities)
            else:
                self._selecting_for = self.tool
                self._sel_remove = False
                self._sel_force = None
                self._sel_history = []
                self.window.command_line.echo_prompt(self.tool.selection_prompt())
        self.changed.emit()

    # -- services for editing tools (ToolContext.services) ---------------------
    def zoom_to_window(self, rect) -> None:
        """ZOOM Window's rectangle, in canvas coordinates (the Model tab or
        a sheet; inside a viewport ZOOM W stays a drag)."""
        x0, y0, x1, y1 = rect
        viewport = self.window.viewport
        viewport.push_view()
        viewport.view.zoom_extents(x0, y0, x1, y1, margin=0.0)
        viewport.update()

    def dimassoc_reference(self, point, hit):
        """The DIMASSOC reference for a dimension point placed with object
        snap ``hit`` (None for a typed point, a point reached through a
        viewport, or a snap no object answers)."""
        from core import dimassoc

        document = self.window.document
        if hit is None or document is None or hit.via is not None \
                or self.index is None:
            return None
        reach = self.px_to_space(3) or 1e-6
        x, y = point
        handles = self.index.crossing((x - reach, y - reach, x + reach, y + reach))
        candidates = [e for h in handles
                      if (e := self.index.entity(h)) is not None and e.is_alive]
        tolerance = max(reach * 1e-3, 1e-9 * max(1.0, abs(x), abs(y)))
        if hit.kind == "INT":
            for i, first in enumerate(candidates):
                for second in candidates[i + 1:]:
                    ref = dimassoc.intersection_reference(first, second)
                    p = dimassoc.where(document.doc, ref, near=(x, y))
                    if p is not None and math.hypot(p[0] - x, p[1] - y) <= tolerance:
                        return ref
            return None
        return dimassoc.reference_at(document, (x, y), hit.kind, candidates,
                                     tolerance)

    def request_selection(self) -> None:
        """A tool asks for objects in the MIDDLE of its flow (WBLOCK: file,
        block name, base point, THEN "Select objects:"). Same phase the
        start of a ``wants_selection`` tool enters."""
        if self.tool is None:
            return
        self._selecting_for = self.tool
        self.window.command_line.echo_prompt(self.tool.selection_prompt())
        self.changed.emit()

    def ask_save_file(self, caption: str, suggested: str, name_filter: str):
        """A save-file dialog for a tool (WBLOCK), through the one door
        every file dialog uses (views/file_dialogs.py)."""
        from views import file_dialogs

        document = self.window.document
        filename, _selected = file_dialogs.get_save_file(
            self.window, caption, suggested, name_filter,
            preferred=document.path if document is not None else None)
        return filename or None

    @property
    def document(self):
        return self.window.document

    def paper_context(self):
        """(document, active layout name) for paper-space tools (MVIEW)."""
        return self.window.document, self.window._active_layout

    def units(self):
        """The drawing's unit settings, for the tools that print numbers."""
        return self.window.display_units()

    def pick_entity(self, point):
        point = self.to_space(*point)
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
        if not self.cycling_on:                  # SELECTIONCYCLING off: the first answer, always
            handles = self._shown(self.index.pick_all(point, tolerance))
            return handles[0] if handles else None
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
        handles = self._shown(self.index.pick_all(point, tolerance))
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
        """Selected handles resolved to live entities. Cached per (index
        version, selection): the properties panel, the properties toolbar
        and the layer control each ask for it on every selection change,
        and on a 5000-object window that was three full walks."""
        if self.index is None:
            return []
        key = (self.index.version, frozenset(self.selection))
        cached = self._sel_entities_cache
        if cached is not None and cached[0] == key:
            return cached[1]
        out = []
        for h in self.selection:
            e = self.index.entity(h)
            if e is not None and e.is_alive:
                out.append(e)
        self._sel_entities_cache = (key, out)
        return out

    def _selectable(self, entities, include_off: bool = False,
                    include_locked: bool = False):
        """The handles of ``entities`` a pick may take: on a layer that is
        on, thawed and unlocked, and not isolated away. ``include_off``:
        the typed ALL, which AutoCAD documents as "except those objects on
        frozen or on locked layers" -- a layer that is off is still in.
        ``include_locked``: what a command's own selection takes, a locked
        layer being refused later, when it would be modified."""
        document = getattr(self.window, "document", None)
        if document is None:
            return []
        layers = document.doc.layers
        hidden = getattr(document, "_isolated_hidden", None) or set()
        refused: dict = {}                    # layer name -> left out?
        handles = []
        for entity in entities:
            handle = entity.dxf.get("handle")
            if not handle or handle in hidden:
                continue
            name = entity.dxf.get("layer", "0")
            out = refused.get(name)
            if out is None:
                layer = layers.get(name) if name in layers else None
                out = refused[name] = layer is not None and (
                    (layer.is_off() and not include_off) or layer.is_frozen()
                    or (layer.is_locked() and not include_locked))
            if not out:
                handles.append(handle)
        return handles

    def _shown(self, handles) -> list:
        """``handles`` the user can see -- on a layer that is on and thawed,
        not isolated away -- in their order. A click, a window or a crossing
        only take what is on screen, as AutoCAD's do; the index holds every
        entity, and a window over a layer turned off took its objects, which
        Delete then erased (#97)."""
        if not handles:
            return []
        db = self.window.document.doc.entitydb
        return self._selectable(
            [e for h in handles if (e := db.get(h)) is not None],
            include_locked=True)

    def _unlocked_for(self, tool, entities) -> list:
        """``entities`` without those on a locked layer when ``tool`` edits
        what it is handed: "Objects on a locked layer cannot be modified"
        (LAYER, Command Reference). A window over a locked layer erased and
        moved its objects as if it were not."""
        document = getattr(self.window, "document", None)
        if document is None or (tool is not None
                                and not getattr(tool, "modifies_selection", True)):
            return entities
        layers = document.doc.layers
        kept = []
        for entity in entities:
            name = entity.dxf.get("layer", "0")
            layer = layers.get(name) if name in layers else None
            if layer is None or not layer.is_locked():
                kept.append(entity)
        locked = len(entities) - len(kept)
        if locked == 1:
            self.window.command_line.echo(tr("1 was on a locked layer."))
        elif locked:
            self.window.command_line.echo(
                tr("{n} were on a locked layer.", n=locked))
        return kept

    def select_all(self) -> int:
        """Ctrl+A: every selectable entity of the current space -- what is
        on a layer that is on, thawed and unlocked, and not isolated away."""
        document = getattr(self.window, "document", None)
        if document is None:
            return 0
        handles = set(self._selectable(document.current_space()))
        self.selection = self._filtered(handles)
        self._highlight_cache = None
        self._grips_cache = None
        self.changed.emit()
        return len(self.selection)

    def clear_selection(self) -> None:
        self.reset_pick_cycle()
        self.selection = set()
        self._window_anchor = None
        self.changed.emit()

    # -- Delete / clipboard (noun-verb: act on the current selection) ----------
    def delete_selection(self) -> bool:
        """Supr/Delete: erase the selected objects (only when idle)."""
        if self.tool is not None:
            return False
        entities = self._selection_entities()
        if not entities:
            return False
        self._execute(actions.EraseCommand(entities))
        self.clear_selection()
        return True

    def copy_selection(self, cut: bool = False, base=None) -> bool:
        """Ctrl+C / Ctrl+X: stash copies of the selection with a base point
        -- the selection's lower-left corner, or the one COPYBASE asked for."""
        entities = self._selection_entities()
        if not entities:
            return False
        # base point from the cached pick rows: ezdxf bbox walks INSERT
        # contents recursively and cost ~1.6 s on a big selection
        bounds = (self.index.bounds_of(self.selection)
                  if self.index is not None else None)
        if base is not None:
            base = (float(base[0]), float(base[1]))
        elif bounds is not None:
            base = (bounds[0], bounds[1])
        else:
            try:
                from ezdxf import bbox
                ext = bbox.extents(entities, fast=True)
                base = (ext.extmin.x, ext.extmin.y)
            except Exception:
                base = (0.0, 0.0)
        self._clipboard = ([e.copy() for e in entities], base)
        # the entities themselves, for a paste into ANOTHER drawing: only
        # entities in their drawing's database carry their resources over
        self._clipboard_originals = list(entities)
        # source handles (aligned with the clipboard) let paste register its
        # copies in the pick index by translating the sources' cached rows
        self._clipboard_src = [e.dxf.handle for e in entities]
        # and on the system clipboard, for the other IngeCAD windows -- each
        # one its own process (#75)
        self._publish_clipboard(entities, base)
        if cut:
            self._execute(actions.EraseCommand(entities))
            self.clear_selection()
        return True

    #: Objects (block contents counted) up to which Ctrl+C puts the copy on
    #: the system clipboard at once; a few hundredths of a second. A bigger
    #: copy waits until the user leaves the window: building it cost 1.3 s
    #: of frozen GUI on a whole 10 000-object plan, and writing it 1.9 s
    #: more of a worker fighting the next ERASE for the GIL (release bench
    #: against v0.6.6). Pasting in this window always uses memory.
    CLIPBOARD_NOW_LIMIT = 600

    def _clip_weight(self, entities) -> int:
        weight = 0
        doc = self.window.document.doc if self.window.document else None
        counts = {}
        for e in entities:
            weight += 1
            if e.dxftype() == "INSERT" and doc is not None:
                name = e.dxf.get("name", "")
                if name not in counts:
                    block = doc.blocks.get(name) if name in doc.blocks else None
                    counts[name] = len(block) if block is not None else 0
                weight += counts[name]
            if weight > self.CLIPBOARD_NOW_LIMIT:
                break
        return weight

    def _publish_clipboard(self, entities, base) -> None:
        from views import clipboard

        self._clip_pending = None
        if self._clip_weight(entities) > self.CLIPBOARD_NOW_LIMIT:
            # a big copy: memory now, the system clipboard when the user
            # goes to another window (_on_application_state)
            self._clip_id = None
            self._clip_pending = (list(entities), base)
            self._watch_application_state()
            return
        self._put_on_system_clipboard(entities, base)

    def _watch_application_state(self) -> None:
        if getattr(self, "_app_state_watched", False):
            return
        from PySide6.QtGui import QGuiApplication

        app = QGuiApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._on_application_state)
            self._app_state_watched = True

    def _on_application_state(self, state) -> None:
        from PySide6.QtCore import Qt

        pending = getattr(self, "_clip_pending", None)
        if pending is None or state != Qt.ApplicationInactive:
            return
        self._clip_pending = None
        entities = [e for e in pending[0] if e.is_alive]
        if entities:
            self._put_on_system_clipboard(entities, pending[1])

    def _put_on_system_clipboard(self, entities, base) -> None:
        from core import gc_guard
        from views import clipboard

        built = clipboard.build(entities, base)
        self._clip_id = built[0] if built is not None else None
        if built is None:
            return
        writer = clipboard.ClipWriter(*built)
        writer.done.connect(self._on_clip_written)
        self._clip_writers.add(writer)
        gc_guard.start(writer)

    def _on_clip_written(self, clip_id, data) -> None:
        from views import clipboard

        worker = self.sender()
        if worker in self._clip_writers:
            worker.wait()   # thread has emitted; joins immediately
            self._clip_writers.discard(worker)
        if data and clip_id == self._clip_id:   # not overtaken by a newer copy
            clipboard.put(clip_id, data)

    def _system_clipboard(self) -> Optional[tuple]:
        """(sources, base) of an IngeCAD copy made in ANOTHER window, read
        from the system clipboard's DXF; None when the latest copy is this
        window's own (pasted from memory) or not IngeCAD's at all."""
        from views import clipboard

        if self._clip_writers or getattr(self, "_clip_pending", None) is not None:
            return None             # this window's copy is the latest: memory
        clip_id = clipboard.current_id()
        if clip_id is None or clip_id == self._clip_id:
            return None
        if self._foreign_clip is not None and self._foreign_clip[0] == clip_id:
            return self._foreign_clip[1]
        data = clipboard.current_dxf()
        try:
            sources, base = clipboard.read_dxf(data) if data else ([], None)
        except Exception:
            sources = []
        if not sources:
            return None
        self._foreign_clip = (clip_id, (sources, base))
        return self._foreign_clip[1]

    def clipboard_data(self):
        other = self._system_clipboard()
        if other is not None:
            return other
        return self._clipboard if self._clipboard else (None, None)

    def clipboard_originals(self) -> list | None:
        other = self._system_clipboard()
        if other is not None:
            # entities of the clipboard drawing: a paste loads them with
            # everything they name
            return list(other[0])
        return getattr(self, "_clipboard_originals", None) if self._clipboard else None

    def paste(self) -> None:
        """Ctrl+V: place the clipboard entities from a picked point."""
        if not self._clipboard and self._system_clipboard() is None:
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
    def open_mtext_editor(self, first, second, char_height: float,
                          commit=None) -> None:
        """MTEXT's two corners placed: edit the new text on the canvas.

        ``commit(content, extras)`` replaces the default (an MTEXT in the
        box) for the tools whose text belongs to another entity -- a leader
        builds its own command from what was typed."""
        from views.mtext_editor import MTextInPlaceEditor

        # the box is square to the UCS (#91): measured there, placed back
        frame = self.current_ucs()
        f_u, s_u = frame.to_ucs(*first), frame.to_ucs(*second)
        top_left = frame.to_world(min(f_u[0], s_u[0]), max(f_u[1], s_u[1]))
        width = abs(s_u[0] - f_u[0])
        document = self.window.document
        style = ""
        if document is not None:
            style = document.doc.header.get("$TEXTSTYLE", "Standard")

        def default_commit(content: str, extras: dict) -> None:
            if content.strip():
                box_second = second
                new_width = extras.get("width")
                if new_width:
                    # The ruler's width arrow moved: keep the left edge, put
                    # the right one where it was dragged to.
                    direction = 1.0 if s_u[0] >= f_u[0] else -1.0
                    box_second = frame.to_world(f_u[0] + direction * new_width,
                                                s_u[1])
                self._execute(actions.add_mtext(
                    first, box_second, content, char_height,
                    style=extras.get("style"),
                    attachment=extras.get("attachment") or 1,
                    line_spacing=extras.get("line_spacing"),
                    bg=extras.get("bg"),
                    columns=extras.get("columns"), frame=frame))
            self.window.viewport.update()

        self._mtext_editor = MTextInPlaceEditor(
            self.window.viewport, top_left=top_left, width_world=width,
            char_height=char_height, text="",
            on_commit=commit if commit is not None else default_commit,
            document=document, style=style, allow_justify=True)

    def edit_hatch(self, entity) -> bool:
        """HATCHEDIT on one hatch: the Hatch dialog, prefilled. True if done.

        "Modifies hatch-specific properties, such as pattern, scale, and
        angle for an existing hatch or fill" (reference p. 896). Its
        boundaries are untouched -- editing those is a different job, and
        AutoCAD keeps it in its own option.
        """
        from views.hatch_dialog import HatchDialog

        if entity is None or not entity.is_alive or entity.dxftype() != "HATCH":
            return False
        document = self.window.document
        if document is None:
            return False
        before = actions.hatch_settings(entity)
        dialog = HatchDialog(self.window, before)
        if not dialog.exec():
            return True             # handled: the user said no
        after = dialog.settings()
        if after == before:
            return True
        snap = actions.SnapshotCommand([entity])
        snap.name = "HATCHEDIT"
        actions.apply_hatch_settings(entity, after)
        snap.commit(document)
        self.window.history.record(snap)
        # its look changed, its geometry did not: redraw that one entity
        # instead of the drawing (the same path a layer's colour takes)
        self.redraw_entities([entity])
        self.window.command_line.echo(
            tr("Hatch pattern {name}.", name=after.get("pattern", "SOLID")))
        return True

    def edit_attributes(self, entity) -> bool:
        """Double-click on a block reference with attributes: the Enhanced
        Attribute Editor (EATTEDIT, p. 715). True if handled."""
        if entity.dxftype() != "INSERT" or not entity.attribs:
            return False
        from tools.attributes import edit_attributes_of
        from tools.base import Tool, ToolContext

        ctx = ToolContext(execute=self._execute, prompt=lambda *_a: None,
                          echo=self.window.command_line.echo,
                          finish=lambda: None, services=self)
        return edit_attributes_of(Tool(ctx), entity)

    def edit_attribute_definition(self, attdef) -> bool:
        """DDEDIT on an attribute definition: the Edit Attribute Definition
        dialog -- tag, prompt, default (p. 523) -- as one undoable step."""
        from views.attribute_dialogs import EditAttDefDialog

        dialog = EditAttDefDialog(self.window, attdef)
        if dialog.exec():
            command = dialog.command()
            if command is not None:
                self._execute(command)
                self.changed.emit()
        return True

    def open_text_editor_for(self, entity) -> bool:
        """Double-click on a text object: edit it in place. True if handled.

        The kinds are DDEDIT's (p. 521): single-line text, multiline text and
        attribute definitions -- plus ATTRIB, which the shortcut menu offers
        alongside them. Everything but MTEXT edits as one line.

        The anchor is the entity's insert point; for MTEXT attachment points
        other than top-left the editor sits close to, not exactly on, the
        text — a step-1 simplification, not a rule.
        """
        from views.mtext_editor import MTextInPlaceEditor

        kind = entity.dxftype()
        if kind not in ("MTEXT", "TEXT", "ATTRIB", "ATTDEF"):
            return False
        if kind == "ATTDEF":
            return self.edit_attribute_definition(entity)
        insert = entity.dxf.insert
        if kind == "MTEXT":
            char_height = float(entity.dxf.char_height or 2.5)
            width = float(entity.dxf.get("width", 0) or 0)
            if width <= 0:
                width = 40.0 * char_height    # unwrapped: a workable box
            text = entity.text
            single = False
            # MTEXT-only: asking a single-line entity for it raises.
            line_spacing = float(
                entity.dxf.get("line_spacing_factor", 1.0) or 1.0)
        else:
            char_height = float(entity.dxf.height or 2.5)
            width = max(len(entity.dxf.text), 8) * char_height
            text = entity.dxf.text
            single = True
            line_spacing = 1.0

        def commit(content: str, extras: dict) -> None:
            if single:
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
            line_spacing=line_spacing)
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
        """(outer_polygon, [island_polygons]) under a Pick-internal-point.

        The boundary set is what the canvas shows, as AutoCAD's default
        (HPBOUND = current viewport): a region is traced from every curve
        in view, lines and arcs included, not only from closed objects.
        """
        from core.hatch_boundary import region_at_point

        if self.window.document is None:
            return None
        return region_at_point(
            list(self.window.document.modelspace()), point,
            window=self._visible_space_rect())

    def _visible_space_rect(self):
        """The canvas in coordinates of the current space, or None headless."""
        viewport = getattr(self.window, "viewport", None)
        view = getattr(viewport, "view", None)
        if view is None or not view.width or not view.height:
            return None
        corners = [view.screen_to_world(0, 0),
                   view.screen_to_world(view.width, view.height)]
        pts = [self.to_space(x, y) for x, y in corners]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))

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

    def pick_drawing_file(self) -> str:
        """INSERT ▸ Browse: AutoCAD's Select Drawing File dialog."""
        from views import file_dialogs

        return file_dialogs.get_open_file(
            self.window, tr("Select Drawing File"),
            tr("Drawings (*.dwg *.dxf);;All files (*)"))

    def _on_prompt(self, text: str) -> None:
        """A tool's prompt: to the command window, and remembered for the
        dynamic-input tooltip beside the cursor."""
        self.current_prompt = text
        self.window.command_line.echo_prompt(text)

    def _finish(self) -> None:
        self.tool = None
        self.snap_hit = None
        self.osnap_override = None
        self._modifier = None
        self.current_prompt = ""
        self._recent_points = []
        self.clear_tracking()
        self._selecting_for = None
        self._window_anchor = None
        self.selection = set()  # command done: highlight goes off
        self._crossing_rects = []
        if self._ghost_on:
            self._ghost_on = False
            self.window.viewport.set_ghost_scene(None)
        self._clear_preview()
        self.changed.emit()
        if self.repeat_name:
            # MULTIPLE: the command ended by itself -- start it again, once
            # this one has fully unwound
            from PySide6.QtCore import QTimer

            QTimer.singleShot(0, self._repeat)

    def _repeat(self) -> None:
        name = self.repeat_name
        if name and self.tool is None:
            self.window.dispatcher.submit(name)

    def cancel(self) -> None:
        self.repeat_name = None          # Esc ends MULTIPLE too
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
            # a LEADER brings the MTEXT it annotates (extra_entities)
            return ToolController._command_entities(command)
        if isinstance(command, actions.AddDimensionCommand):
            # Its graphics live in an anonymous *D block, which the overlay
            # renders through the same frontend the base scene uses -- 1035
            # vertices for a plain DIMLINEAR, measured. Nothing about it needs
            # a full regen.
            # DIMASSOC 0 leaves loose pieces instead of the dimension
            return ([command.dim] if command.dim is not None else []) \
                + list(getattr(command, "_pieces", None) or [])
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
            # (a paste from another drawing: its rows are not in this index)
            if (clip is not None and not command.foreign
                    and len(clip) == len(command.sources)
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
                     actions.CreateBlockCommand, actions.ExplodeCommand,
                     actions.DimGripCommand, actions.DimTextTranslateCommand,
                     actions.DimTextEditCommand)

    @classmethod
    def _patchable(cls, command) -> bool:
        """Is every entity this command touched knowable from the command?

        If so the pick index and the snap engine are patched below instead
        of being thrown away. This ONE predicate now answers for both
        places, because the bug it fixes was the two disagreeing: MATCHPROP
        reaches the display branch through ``.targets`` and got its caches
        patched -- but the invalidation above did not know about
        ``.targets``, so it had already marked them dirty, and a patch on a
        dirty index is a documented no-op. The next pick then paid a full
        rebuild: **2.76 s measured on a 10 084-entity plan**, on every
        destination click after the first, since MATCHPROP keeps painting
        until Enter. Marco reported it as "tarda como 3 segundos".
        """
        return (isinstance(command, cls._KNOWN_MODIFY)
                or getattr(command, "targets", None) is not None)

    @staticmethod
    def _touches_viewport(command) -> bool:
        """True if the command reaches a VIEWPORT entity.

        A viewport's picture is the model re-projected through it: moving,
        scaling or erasing one changes pixels no overlay can predict, so
        these ask for the regen the surgical path would otherwise skip.
        """
        for attr in ("entities", "sources", "old_entities", "targets"):
            group = getattr(command, attr, None)
            if group:
                try:
                    if any(e.dxftype() == "VIEWPORT" for e in group
                           if e is not None and e.is_alive):
                        return True
                except Exception:
                    continue
        entity = getattr(command, "entity", None)
        try:
            return (entity is not None and entity.is_alive
                    and entity.dxftype() == "VIEWPORT")
        except Exception:
            return False

    def _execute(self, command) -> None:
        self._execute_command(command)
        self._show_reacted(command)

    def _show_reacted(self, command) -> None:
        """The associative dimensions a command re-measured (its follow-up,
        core/dimassoc): hide their stale copies and draw them through the
        overlay, the way a dimension grip edit is shown."""
        followup = getattr(command, "dimassoc_followup", None)
        if followup is None:
            return
        dims = [d for d in followup.entities if d.is_alive]
        if not dims:
            return
        handles = [d.dxf.handle for d in dims]
        self._drop_conflicting_stamps(handles)
        self.window.viewport.hide_handles(handles)
        self._base_handles -= set(handles)
        for dim in dims:
            if dim not in self._pending_render:
                self._pending_render.append(dim)
        if self.index is not None:
            self.index.remove_handles(handles)
            self.index.add_entities(dims)
        if self.snap_engine is not None:
            self.snap_engine.remove_handles(handles)
            self.snap_engine.add_entities(dims)
        self._refresh_overlay()

    def _execute_command(self, command) -> None:
        # the drawing changed under the candidates: never cycle stale ones
        self.reset_pick_cycle()
        # asked BEFORE the command runs: an ERASE leaves its entities
        # unlinked and an is_alive test afterwards answers about a ghost
        touched_viewport = self._touches_viewport(command)
        if isinstance(command, actions.AddDimensionCommand) \
                and command.dimlfac is None and command.dimlfac_resolver is None:
            command.dimlfac_resolver = self.trans_spatial_factor
        self.window.history.execute(command)
        skipped = getattr(command, "skipped", None)
        if skipped:
            # Say what did not move rather than let the command look done.
            kinds = sorted({e.dxftype() for e in skipped})
            if kinds == ["VIEWPORT"]:
                self.window.command_line.echo(
                    tr("{count} object(s) unchanged: a viewport has no angle "
                       "to rotate.", count=len(skipped)))
            else:
                self.window.command_line.echo(
                    tr("{count} object(s) unchanged: IngeCAD cannot move or "
                       "copy {kinds}.", count=len(skipped),
                       kinds=", ".join(kinds)))
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
        elif self._patchable(command):
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
        if (getattr(command, "needs_regen", False)
                or touched_viewport):
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
            if (self._patchable(command)
                    and not isinstance(command, (
                        actions.ReplaceEntitiesCommand,
                        actions.CreateBlockCommand,
                        actions.ExplodeCommand))):
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
                if entity.dxftype() == "IMAGE" and self._sync_image_quad(entity):
                    # a MOVEd/ROTATEd image: its pixels are repositioned
                    # surgically, and queuing it would decode its file on
                    # every overlay refresh until the merge. A fresh COPY
                    # has no quad yet — sync fails and it queues normally.
                    continue
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
            # The result is already on screen (hide + overlay). The merge
            # exists only to bound the overlay's growth, so it follows the
            # same rule as the additive path: below the threshold, NOTHING
            # is scheduled. It used to fire after every single edit, and a
            # full re-tessellation of a real plan takes ~3 s -- nominally in
            # a worker, but a pure-Python one holds the GIL, so the UI froze
            # 2.5 s after the edit, right as the user grabbed the next grip.
            # That was the "a veces se queda pegado" Marco reported.
            if (len(self._draw_commands()) + len(self._pending_render)
                    > MERGE_THRESHOLD):
                self._merge_timer.start()

    def _run_deferred_regen(self) -> None:
        self.window.regen_in_memory()

    def _invalidate_geometry(self) -> None:
        if self.snap_engine is not None:
            self.snap_engine.invalidate()
        if self.index is not None:
            self.index.invalidate()
        self._model_snap_engine = None

    def after_history_change(self, command=None) -> None:
        """Called by U/REDO with the command that crossed the boundary.

        Instant feedback, no deferred-regen blank: stale base-scene copies of
        everything the command touched are hidden surgically and the restored
        or current entities ride the overlay; the full regen stays coalesced.
        """
        if command is not None:
            self._show_reacted(command)
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
        touched.extend(getattr(command, "_pieces", None) or [])  # DIMASSOC 0
        for _orig, parts in (getattr(command, "pieces", None) or []):
            touched.extend(parts)
        if len(touched) > BIG_EDIT:
            # Thousands of objects at once (undo of a colour change or an
            # ERASE over the whole plan): re-drawing them through the
            # overlay and re-filing each one in the pick index froze the
            # window 7-8 s on a 10 000-entity sheet. Rebuild everything in
            # the background instead -- the window keeps answering and the
            # result lands with the regen, as when the plan was opened.
            removed = list(getattr(command, "removed_handles", None) or [])
            if removed:
                self.window.viewport.hide_handles(removed)
            self._pending_render = []
            self._refresh_overlay()
            if not _look_only(command):
                # a colour or a layer moves nothing: the pick and snap
                # caches stay valid, and the selection's highlight with them
                self._invalidate_geometry()
                self._start_warmer(self.window.document)
            self.window.regen_in_background()
            return
        # hide stale base copies: entities the undo/redo just destroyed
        # (recorded handles) plus every touched survivor's base-scene copy
        hide = list(getattr(command, "removed_handles", None) or [])
        hide += [e.dxf.handle for e in touched if e.is_alive]
        if hide:
            self.window.viewport.hide_handles(hide)
        # Raster images first, on TOUCHED and not on alive: a snapshot
        # restore leaves the entity momentarily owner-less, and the alive
        # filter below would skip it — the quad then stayed where the drag
        # left it. The quad needs only a live entity; keeping the IMAGE out
        # of the overlay also avoids decoding its file per refresh.
        synced = set()
        for e in touched:
            if (e.is_alive and e.dxftype() == "IMAGE"
                    and self._sync_image_quad(e)):
                synced.add(id(e))
        alive = [e for e in touched
                 if e.is_alive and e.dxf.owner is not None]
        for e in alive:
            if id(e) in synced:
                continue
            if e not in self._pending_render:
                self._pending_render.append(e)
        if any(e.dxftype() == "VIEWPORT" for e in alive):
            # the overlay cannot show a viewport (see _refresh_overlay): the
            # background regen does, as for the edit this undoes. Started
            # once this undo's overlay is built, not before: the two fought
            # over the interpreter and the undo froze 1.2 s instead of 0.5
            # (Iray's sheet, release bench).
            from PySide6.QtCore import QTimer

            QTimer.singleShot(0, self.window.regen_in_memory)
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

    def redraw_entities(self, entities) -> bool:
        """Draw these entities again with their current look, no regen.

        The two steps MATCHPROP already takes -- hide the base scene's copy
        and queue them for the overlay -- so the cost is what changed, not
        the whole drawing. Used when a LAYER's colour, linetype or
        lineweight changes: those entities look different, but their
        geometry, their handles and therefore the pick index and the snap
        engine are untouched.
        """
        alive = [e for e in entities
                 if e.is_alive and e.dxf.owner is not None
                 and e.dxf.get("handle", None)]
        if not alive:
            return False
        handles = [e.dxf.handle for e in alive]
        self._drop_conflicting_stamps(handles)
        self.window.viewport.hide_handles(handles)
        # the base copies are hidden now: lift the no-double-draw exclusion
        # or the overlay would skip them and leave a hole
        self._base_handles -= set(handles)
        for entity in alive:
            if entity not in self._pending_render:
                self._pending_render.append(entity)
        self._refresh_overlay()
        self._merge_timer.start()
        self.changed.emit()
        return True

    def _draw_commands(self):
        return [c for c in self.window.history._undo
                if isinstance(c, actions.AddEntityCommand)]

    @staticmethod
    def _command_entities(command) -> list:
        """What an additive command put in the drawing: its entity and,
        for a LEADER, the MTEXT it annotates (``extra_entities``)."""
        entities = [command.entity] if command.entity is not None else []
        entities += list(getattr(command, "extra_entities", None) or [])
        return entities

    def _refresh_overlay(self) -> None:
        document = self.window.document
        if document is None:
            return
        # owner=None means the entity is unlinked from modelspace (erased,
        # kept alive only for undo) — never draw those in the overlay.
        entities = [
            e for c in self._draw_commands() for e in self._command_entities(c)
            if e.is_alive and e.dxf.owner is not None
            and e.dxf.handle not in self._base_handles
        ]
        entities += [e for e in self._pending_render
                     if e.is_alive and e.dxf.owner is not None
                     and e.dxf.handle not in self._base_handles]
        entities += self.grip_overlay_entities()
        # A VIEWPORT is the model re-projected: drawn here it redrew the
        # whole model through it on the GUI thread (undo of a MOVE on
        # Planos Constructivos' sheet: 5.3 s frozen, found by the release
        # bench once viewports stopped drawing empty). Only the regen shows
        # a viewport; every path that touches one asks for it.
        entities = [e for e in entities if e.dxftype() != "VIEWPORT"]
        scene = (build_scene_for_entities(document, entities, self._flatten,
                                          self.canvas_space())
                 if entities else None)
        self.window.viewport.set_overlay_scene(scene)
        self.changed.emit()

    # -- pointer input ---------------------------------------------------------
    def on_hover(self, wx: float, wy: float,
                 threshold_world: Optional[float] = None) -> None:
        """The cursor moved to this CANVAS point.

        ``threshold_world`` is the snap aperture in canvas units. The app
        never passes one -- SNAP_PX goes through px_to_space -- tests do,
        to stay independent of the window's zoom.
        """
        inside = self.in_active_viewport(wx, wy)
        wx, wy = self.to_space(wx, wy)
        if threshold_world is None:
            threshold_world = self.px_to_space(SNAP_PX)
        else:
            threshold_world = threshold_world / self.space_factor()
        self._cursor = (wx, wy)
        self._pick_tolerance = self.px_to_space(self.pickbox_px())
        self.snap_hit = None
        grip_hot = self._grip_drag is not None
        needs_snap = grip_hot or (
            self.tool is not None and self._selecting_for is None
            and not self.tool.entity_picker)
        if not inside or self.space_vp is not None:
            # over the paper outside the viewport, or inside one: a
            # viewport navigates, it does not snap (see start_tool)
            needs_snap = False
        if needs_snap and self.caches_warming():
            # The caches are being built in the background right after an
            # open. Building them here instead froze the first mouse move
            # on a big plan (135 ms on a 10 000-entity sheet, seconds on a
            # cadastre); snaps come back the moment the warm caches land.
            needs_snap = False
        kinds = self.snap_kinds()
        self.track_hint = None
        if needs_snap and self.snap_engine is not None and kinds:
            self.snap_hit = self._find_snap(
                (wx, wy), threshold_world, kinds, self.anchor_point())
            through = self._snap_through_viewport((wx, wy), threshold_world)
            if through is not None and (
                    self.snap_hit is None
                    or math.hypot(through.x - wx, through.y - wy)
                    < math.hypot(self.snap_hit.x - wx, self.snap_hit.y - wy)):
                self.snap_hit = through
        if needs_snap and self.snap_engine is not None and (
                kinds & {"EXT", "PAR"}):
            self._watch_tracking_snap(wx, wy, threshold_world, kinds)
            if self.snap_hit is None:
                self.snap_hit = self._tracking_snap_hit(wx, wy, threshold_world)
        self._track_tolerance = threshold_world
        self._watch_for_acquisition()
        self._sync_ghost(wx, wy)
        self._sync_preview(wx, wy)

    # -- object snap tracking (OTRACK) ----------------------------------------
    def _watch_for_acquisition(self) -> None:
        """Pausing the cursor on an object snap point acquires it (or lets
        an acquired one go): the dwell timer fires only if the cursor is
        still on the same point."""
        hit = self.snap_hit
        if not self.otrack_on or hit is None:
            self._track_candidate = None
            self._track_timer.stop()
            return
        key = (round(hit.x, 9), round(hit.y, 9))
        if key != self._track_candidate:
            self._track_candidate = key
            self._track_timer.start()

    def acquire_now(self) -> None:
        """The dwell elapsed: acquire the snap point under the cursor, or
        release it if it was acquired already."""
        hit = self.snap_hit
        if not self.otrack_on or hit is None or self._track_candidate is None:
            return
        if (round(hit.x, 9), round(hit.y, 9)) != self._track_candidate:
            return
        for i, (x, y, _kind) in enumerate(self._track_points):
            if abs(x - hit.x) < 1e-9 and abs(y - hit.y) < 1e-9:
                del self._track_points[i]
                self.changed.emit()
                return
        self._track_points.append((hit.x, hit.y, hit.kind))
        del self._track_points[:-self.TRACK_MAX]
        self.changed.emit()

    def track_points(self) -> list:
        """The acquired points, ``(x, y, kind)``, for the overlay: object
        snap tracking's (with OTRACK on) and the ends acquired for EXT."""
        points = list(self._track_points) if self.otrack_on else []
        for source in self._ext_sources:
            end = source[1] if source[0] == "line" else source[3]
            points.append((end[0], end[1], "EXT"))
        return points

    # -- EXT and PAR -----------------------------------------------------------
    def _watch_tracking_snap(self, wx, wy, threshold, kinds) -> None:
        """Start the dwell on an end (EXT) or a line (PAR) under the cursor."""
        candidate = None
        if "EXT" in kinds:
            source = self.snap_engine.extension_source((wx, wy), threshold)
            if source is not None:
                candidate = ("EXT", source)
        if candidate is None and "PAR" in kinds and self.tool is not None \
                and self.tool.last_point is not None:
            direction = self.snap_engine.line_direction((wx, wy), threshold)
            if direction is not None:
                candidate = ("PAR", direction)
        if candidate is None:
            self._xp_candidate = None
            self._xp_timer.stop()
            return
        if candidate != self._xp_candidate:
            self._xp_candidate = candidate
            self._xp_timer.start()

    def acquire_tracking_snap(self) -> None:
        """The dwell elapsed: acquire the end or the direction under the
        cursor -- or let it go if it was acquired already, like OTRACK."""
        candidate = self._xp_candidate
        if candidate is None:
            return
        kind, data = candidate
        pool = self._ext_sources if kind == "EXT" else self._par_dirs
        if kind == "PAR":
            same = [d for d in pool
                    if abs(d[0] * data[1] - d[1] * data[0]) < 1e-9]
        else:
            same = [d for d in pool if d == data]
        for d in same:
            pool.remove(d)
        if not same:
            pool.append(data)
        self.changed.emit()

    def _tracking_snap_hit(self, wx, wy, threshold):
        """The cursor on an acquired extension or parallel: the point on
        it, with AutoCAD's tooltip ("Extension: 5.0000 < 0°")."""
        best = None

        def offer(kind, point, source, along, direction, label):
            nonlocal best
            d = math.hypot(point[0] - wx, point[1] - wy)
            if d <= threshold and (best is None or d < best[0]):
                best = (d, kind, point, source, along, direction, label)

        for src in self._ext_sources:
            if src[0] == "line":
                (ex, ey), (ux, uy) = src[1], src[2]
                along = (wx - ex) * ux + (wy - ey) * uy
                if along > 0:
                    offer("EXT", (ex + along * ux, ey + along * uy), (ex, ey),
                          along, math.atan2(uy, ux), "Extension")
            else:
                (cx, cy), r, end, a0, a1 = src[1], src[2], src[3], src[4], src[5]
                ang = math.atan2(wy - cy, wx - cx)
                rel = (ang - a0) % math.tau
                if rel > (a1 - a0) % math.tau + 1e-12:  # past the arc's ends
                    point = (cx + r * math.cos(ang), cy + r * math.sin(ang))
                    offer("EXT", point, end,
                          math.hypot(point[0] - end[0], point[1] - end[1]),
                          math.atan2(point[1] - end[1], point[0] - end[0]),
                          "Extension")
        anchor = self.tool.last_point if self.tool is not None else None
        if anchor is not None:
            for ux, uy in self._par_dirs:
                along = (wx - anchor[0]) * ux + (wy - anchor[1]) * uy
                point = (anchor[0] + along * ux, anchor[1] + along * uy)
                offer("PAR", point, anchor, abs(along),
                      math.atan2(uy, ux) if along >= 0
                      else math.atan2(-uy, -ux), "Parallel")
        if best is None:
            return None
        _d, kind, point, source, along, direction, label = best
        self.track_hint = (source, point,
                           f"{tr(label)}: {self._length_text(along)} < "
                           f"{math.degrees(direction) % 360:.0f}°")
        return SnapHit(point[0], point[1], kind)

    def _length_text(self, value: float) -> str:
        from core import units as units_mod

        try:
            u = self.units()
            return units_mod.format_length(value, u.lunits, u.luprec)
        except Exception:  # noqa: BLE001
            return f"{value:.4f}"

    def clear_tracking(self) -> None:
        self._ext_sources = []
        self._par_dirs = []
        self._xp_candidate = None
        self._xp_timer.stop()
        self._track_points = []
        self._track_candidate = None
        self._track_timer.stop()
        self.track_hint = None

    def _track_angles(self) -> list:
        """The alignment directions (radians) tracking paths run along:
        orthogonal only, or -- POLARMODE's "track using all polar angle
        settings", with POLAR on -- the polar increment and its additional
        angles (Drafting Settings, Polar Tracking tab)."""
        from core import drafting

        base = self.current_ucs().angle      # the UCS's axes, not the world's
        if self.polar_on and drafting.polar_mode() & drafting.POLAR_OTRACK_ALL:
            return [base + math.radians(a) for a in self._polar_angles()]
        return [base, base + math.pi / 2]

    def _polar_angles(self) -> list:
        """POLARANG's multiples plus POLARADDANG when in use, degrees."""
        from core import drafting

        mode = drafting.polar_mode()
        return drafting.polar_angles(
            drafting.polar_increment(), drafting.polar_additional(),
            bool(mode & drafting.POLAR_ADDITIONAL))

    def _polar_base(self) -> float:
        """Where polar angles are measured from, in world degrees: the UCS's
        X axis (absolute) or the direction of the last segment drawn
        (POLARMODE bit 1) -- the tool's last point and the one before it,
        as this controller saw them go by."""
        from core import drafting

        absolute = self.current_ucs().degrees     # the UCS's X, in the world
        if not (drafting.polar_mode() & drafting.POLAR_RELATIVE):
            return absolute
        points = self._recent_points
        if len(points) >= 2:
            (x0, y0), (x1, y1) = points[-2], points[-1]
            if abs(x1 - x0) > 1e-12 or abs(y1 - y0) > 1e-12:
                return math.degrees(math.atan2(y1 - y0, x1 - x0))
        return absolute

    _recent_points: list = []
    #: AutoCAD's LASTPOINT: the last point entered, in any command. A new
    #: drawing starts it at the origin; it outlives the command it came from.
    lastpoint: tuple = (0.0, 0.0)

    def _note_point(self, point) -> None:
        """A point a tool just took: the trail relative polar angles are
        measured along (cleared when the command ends) and LASTPOINT."""
        self._recent_points = (self._recent_points + [tuple(point)])[-2:]
        self.lastpoint = (float(point[0]), float(point[1]))
        self.osnap_override = None        # a one-shot snap lasts one point

    def snap_kinds(self) -> frozenset:
        """The object snaps the next point uses: a one-shot override if
        there is one (even with OSNAP off), else the running modes."""
        if self.osnap_override is not None:
            return self.osnap_override
        return frozenset(self.osnap_modes) if self.osnap_on else frozenset()

    def set_osnap_override(self, keys, typed: bool = False) -> bool:
        """Use only ``keys`` for the next point (empty: no snap at all).
        False, with the reason echoed, for a mode that is not there yet.

        AutoCAD answers with "of" or "to" as the prompt ("_tan to" when the
        snap came from a menu or a macro, just "to" after typing it)."""
        from core import osnap as osnap_modes

        keys = frozenset(keys)
        for key in keys - osnap_modes.AVAILABLE:
            mode = osnap_modes.BY_KEY.get(key)
            self.window.command_line.echo(
                tr(mode.note) if mode and mode.note else tr("Invalid input."))
            return False
        self.osnap_override = keys
        if keys:
            key = sorted(keys)[0]
            word = osnap_modes.preposition(key)
            self._on_prompt(tr(word) if typed else
                            f"{osnap_modes.command_form(key)} {tr(word)}")
        if self._cursor is not None:
            self._refresh_snap_at_cursor()
        self.changed.emit()
        return True

    def _refresh_snap_at_cursor(self) -> None:
        """Re-run the snap search where the cursor is (in space units)."""
        if self.snap_engine is None or self.tool is None:
            return
        wx, wy = self._cursor
        kinds = self.snap_kinds()
        self.snap_hit = (self._find_snap(
            (wx, wy), self.px_to_space(SNAP_PX), kinds,
            self.tool.last_point) if kinds else None)

    def _find_snap(self, at, threshold, kinds, from_point):
        """The object snap at ``at``: the drawing's, and what the running
        command has drawn but not committed yet (a PLINE's own segments)."""
        drawn = self.tool.drawn_segments() if self.tool is not None else None
        return self.snap_engine.find(at, threshold, kinds=kinds,
                                     from_point=from_point, drawn=drawn)

    def _tracked(self, wx: float, wy: float, anchor, ortho: bool):
        """Where the alignment paths put the cursor: on the nearest path
        within the aperture, or on the intersection of two paths from
        different points when the cursor is near both. None if no path
        is near. The last point counts as a source while ortho or polar
        is on (AutoCAD's polar tracking joins object snap tracking)."""
        tol = self._track_tolerance
        sources = list(self._track_points)
        if anchor is not None and (ortho or self.polar_on):
            sources.append((anchor[0], anchor[1], "polar"))
        if not sources:
            return None
        near = []
        for sx, sy, kind in sources:
            for ang in self._track_angles():
                ux, uy = math.cos(ang), math.sin(ang)
                dx, dy = wx - sx, wy - sy
                along = dx * ux + dy * uy
                px, py = sx + along * ux, sy + along * uy
                dist = math.hypot(wx - px, wy - py)
                if dist <= tol:
                    near.append((dist, (sx, sy, kind), ang, (px, py)))
        if not near:
            return None
        best = None
        for i in range(len(near)):
            for j in range(i + 1, len(near)):
                a, b = near[i], near[j]
                if a[1] is b[1] or a[1][:2] == b[1][:2]:
                    continue
                cross = math.cos(a[2]) * math.sin(b[2]) - math.sin(a[2]) * math.cos(b[2])
                if abs(cross) < 1e-9:
                    continue
                (ax, ay), (bx, by) = a[1][:2], b[1][:2]
                t = ((bx - ax) * math.sin(b[2]) - (by - ay) * math.cos(b[2])) / cross
                ix, iy = ax + t * math.cos(a[2]), ay + t * math.sin(a[2])
                d = math.hypot(wx - ix, wy - iy)
                if d <= 2 * tol and (best is None or d < best[0]):
                    best = (d, a[1], a[2], (ix, iy), b[1], b[2])
        base = self.current_ucs().angle      # labels read in the UCS

        def shown(a):
            return f"{math.degrees(a - base) % 360.0:.0f}"

        if best is not None:
            _d, src, ang, point, other, other_ang = best
            label = (f"{_track_label(src[2])}: <{shown(ang)}°, "
                     f"{_track_label(other[2])}: <{shown(other_ang)}°")
            return point, src, label
        near.sort(key=lambda n: n[0])
        _d, src, ang, point = near[0]
        return point, src, f"{_track_label(src[2])}: <{shown(ang)}°"

    # -- the rendered preview of what the next click creates --------------------
    _preview_key = None

    def _sync_preview(self, wx: float, wy: float) -> None:
        """A dimension being placed is previewed as the dimension the click
        will leave -- rendered through the real style, so the text sits
        where it will sit (Marco: the schematic preview centred the text
        on the line while ISO-25 puts it above). The tool hands over the
        very command the click would run; it is run against the document
        and taken back at once, and the entity's picture is kept."""
        tool = self.tool
        fn = getattr(tool, "preview_command", None) if tool is not None else None
        if fn is None or self.window.document is None:
            self._clear_preview()
            return
        point = self.resolved_point(wx, wy)
        key = (id(tool), round(point[0], 9), round(point[1], 9),
               getattr(tool, "_text", None), getattr(tool, "_text_rotation", None),
               getattr(tool, "_forced_angle", None))
        if key == self._preview_key:
            return
        command = fn(point)
        if command is None:
            self._clear_preview()
            return
        try:
            scene = self._preview_scene_for(command)
        except Exception:
            scene = None
        self._preview_key = key
        self.window.viewport.set_preview_scene(scene)

    def _preview_scene_for(self, command):
        """Create the command's entity, picture it, remove it: no revision
        bump, no dirty flag, no history -- the document is as it was.

        The entity is built in a scratch anonymous block, never in the
        drawing's space: the cache warmer and the background regen walk that
        space from their own threads, and a preview dimension caught there
        for a moment stayed behind -- pickable but invisible in the pick
        index, or visible but unpickable in the regen scene. The revision
        does not change, so both results were adopted as current."""
        from render.backend import build_scene_for_entities

        document = self.window.document
        factory = getattr(command, "_factory", None)
        if factory is None:
            return None
        blocks = document.doc.blocks
        scratch = blocks.new_anonymous_block("U")
        block = None
        try:
            override = factory(scratch, document)
            override.render()
            entity = override.dimension
            block = entity.dxf.get("geometry", None)
            current = document.doc.header.get("$CLAYER", "0")
            if current in document.doc.layers:
                entity.dxf.layer = current
            return build_scene_for_entities(document, [entity], self._flatten,
                                            self.canvas_space())
        finally:
            for name in (block, scratch.name):
                if name and name in blocks:
                    try:
                        blocks.delete_block(name, safe=False)
                    except Exception:
                        pass

    def _preview_now(self) -> None:
        """Rebuild the rendered preview for the current cursor (a tool step
        changed what the next click creates), or drop it."""
        self._preview_key = None
        if self.tool is not None and self._cursor is not None:
            self._sync_preview(*self._cursor)
        else:
            self._clear_preview()

    def _clear_preview(self) -> None:
        # Unconditional: _preview_now forgets the key before rebuilding, so
        # a key check here left the last picture up whenever the new step
        # had nothing to preview. Clearing an absent preview is free.
        self._preview_key = None
        self.window.viewport.set_preview_scene(None)

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
            worker = _GhostWorker(self.window.document, ents, self._flatten,
                                  self.canvas_space())
            worker.done.connect(self._on_ghost_done)
            self._ghost_workers.add(worker)
            gc_guard.start(worker)
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
        if self.space_vp is not None or not self.in_active_viewport(wx, wy):
            return
        wx, wy = self.to_space(wx, wy)
        if self._window_anchor is None:
            self._window_anchor = (wx, wy)
            self.changed.emit()

    def on_click(self, wx: float, wy: float, shift: bool = False) -> None:
        if not self.mspace_route(wx, wy):
            return
        if self.space_vp is not None:
            return      # inside the active viewport a click selects nothing
        wx, wy = self.to_space(wx, wy)
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
                handles = self._shown(self.index.crossing(rect))
                entities = [e for h in handles
                            if (e := self.index.entity(h)) is not None
                            and e.is_alive]
                self.tool.on_target_entities(entities, rect)
                self.changed.emit()
                return
            if not self._shown(self.index.pick_all((wx, wy), self._pick_tolerance)):
                # empty click: anchor a target window instead of "nothing"
                self._window_anchor = (wx, wy)
                self.changed.emit()
                return
        if self._modifier is not None:
            point = self.resolved_point(wx, wy)
            self._note_point(point)
            final = self._modifier_take(point)
            if final is not None:
                self.tool.on_point(final)
            self.changed.emit()
            return
        tangent_pick = getattr(self.tool, "on_tangent_pick", None)
        if (tangent_pick is not None and self.osnap_override
                and "TAN" in self.osnap_override):
            # a point picked with Tangent (CIRCLE 3P, Tan Tan Tan): the tool
            # takes the object under the pick, line, arc or circle
            self.osnap_override = None
            tangent_pick((wx, wy))
            self.changed.emit()
            return
        hit = self.snap_hit
        deferred = getattr(self.tool, "on_deferred_tangent", None)
        if (hit is not None and hit.kind == "DTAN" and hit.circle is not None
                and deferred is not None):
            # a deferred tangent: the tool gets the circle, not a point yet
            self.osnap_override = None
            deferred(hit.circle, (hit.x, hit.y))
            self.changed.emit()
            return
        point = self.resolved_point(wx, wy)
        if not self.tool.entity_picker:
            # LASTPOINT is a point entered at a point prompt; a click that
            # picks an object (TRIM, EXTEND) is not one. It was, and the
            # next direct distance started from a trimmed line's pick.
            self._note_point(point)
        # the object snap this point came from: a dimension ties itself to
        # it (core/dimassoc)
        snapped = self.snap_hit
        self.tool.last_snap = (snapped if snapped is not None
                               and (snapped.x, snapped.y) == tuple(point) else None)
        self.tool.on_point(point)
        self.clear_tracking()          # AutoCAD releases the acquired points with the point
        # The step may have made a preview possible (the second origin of a
        # dimension): build it now, not on the next mouse move -- in between
        # the canvas showed the schematic stand-in, text centred on the line.
        self._preview_now()
        self.changed.emit()

    @property
    def paper_vp(self):
        """The selected VIEWPORT, when the selection is exactly that.

        A layout viewport is an object on the sheet like any other: it is
        picked by its border, window/crossing catch it, Shift removes it.
        What stays special is what its GRIPS do — resize the window, not
        stretch a rectangle — so the rest of the code asks this question
        instead of reading a second, parallel selection.
        """
        if len(self.selection) != 1 or self.index is None:
            return None
        entity = self.index.entity(next(iter(self.selection)))
        if entity is None or not entity.is_alive:
            return None
        return entity if entity.dxftype() == "VIEWPORT" else None

    # -- the current space vs the paper the mouse points at --------------------
    @property
    def space_vp(self):
        """The viewport the current space is reached THROUGH, or None.

        Inside MSPACE every point the canvas hands over is a paper point and
        every point this controller answers with is a model point, so the
        conversion happens once, here, at the door.
        """
        vp = getattr(self.window, "_active_vp", None)
        if vp is None or not getattr(vp, "is_alive", True):
            return None
        return vp

    def mspace_route(self, wx: float, wy: float) -> bool:
        """Should a canvas click at this PAPER point reach the tools?

        On the sheet and in the Model tab: always. Inside MSPACE only when
        it lands in the active viewport -- a click in another one makes that
        viewport current instead, which is what AutoCAD does even in the
        middle of a command, and a click on the bare paper does nothing at
        all, because through the projection it would mean a model point the
        viewport does not show.
        """
        vp = self.space_vp
        if vp is None:
            return True
        x0, y0, x1, y1 = layout_ops.viewport_rect(vp)
        if x0 <= wx <= x1 and y0 <= wy <= y1:
            return True
        layout = self.sheet()
        if layout is not None:
            other = layout_ops.viewport_hit(layout, wx, wy)
            if other is not None and other is not vp:
                self.window._activate_viewport(other)
                return False
        # Bare paper: say once per viewport how to get back out. AutoCAD
        # stays silent here, and a tester who could not find the way out
        # ended up double-clicking around until it happened.
        if not getattr(self, "_mspace_exit_hinted", False):
            self._mspace_exit_hinted = True
            echo = getattr(getattr(self.window, "command_line", None),
                           "echo", None)
            if echo is not None:
                echo(tr("Outside the active viewport. Double-click the "
                        "paper or type PSPACE to return to paper space."))
        return False

    def in_active_viewport(self, wx: float, wy: float) -> bool:
        """Is this PAPER point inside the viewport MSPACE activated?"""
        vp = self.space_vp
        if vp is None:
            return True
        x0, y0, x1, y1 = layout_ops.viewport_rect(vp)
        return x0 <= wx <= x1 and y0 <= wy <= y1

    def canvas_space(self):
        """The space whose CANVAS is on screen, when it is not the one being
        edited: the sheet, while a viewport of it is active. None otherwise,
        which means "the current space draws on its own canvas"."""
        return self.sheet() if self.space_vp is not None else None

    # -- snapping from the sheet to what a viewport shows ----------------------
    _model_snap_engine = None
    #: Paper points (rounded) that were snapped to model geometry, and the
    #: viewport they came through: what tells a paper-space dimension it is
    #: measuring the model.
    _through_vp: dict = {}

    def _snap_through_viewport(self, paper, threshold):
        """A paper-space cursor over a viewport snaps to the model geometry
        that viewport shows (AutoCAD does: a dimension drawn on the sheet
        engages the extremos of the plan through the window). The hit comes
        back as a PAPER point, marked with the viewport it went through.

        Only on the sheet itself: inside MSPACE the current space already is
        the model, and on the Model tab there is no window to look through.
        """
        if self.space_vp is not None:
            return None
        layout = self.sheet()
        if layout is None or self.window.document is None:
            return None
        wx, wy = paper
        for vp in layout_ops.visible_viewports(layout):
            x0, y0, x1, y1 = layout_ops.viewport_rect(vp)
            if not (x0 <= wx <= x1 and y0 <= wy <= y1):
                continue
            model = layout_ops.paper_to_model(vp, wx, wy)
            if model is None:
                continue
            scale = layout_ops.viewport_scale(vp) or 1.0
            engine = self._model_snap_engine
            if engine is None:
                engine = SnapEngine(self.window.document,
                                    space=self.window.document.doc.modelspace())
                self._model_snap_engine = engine
                self._model_engine_revision = self.window.document.revision
            anchor = self.anchor_point()
            if anchor is not None:
                anchor = layout_ops.paper_to_model(vp, *anchor)
            hit = engine.find(model, threshold / scale,
                              kinds=self.snap_kinds(),
                              from_point=anchor)
            if hit is None:
                continue
            back = layout_ops.model_to_paper(vp, hit.x, hit.y)
            if back is None:
                continue
            return SnapHit(back[0], back[1], hit.kind, via=vp.dxf.handle)
        return None

    @staticmethod
    def _point_key(point) -> tuple[float, float]:
        return (round(float(point[0]), 6), round(float(point[1]), 6))

    def _remember_through(self, hit) -> None:
        """A point about to be used came through a viewport: keep that."""
        if hit is None or getattr(hit, "via", None) is None:
            return
        self._through_vp[self._point_key((hit.x, hit.y))] = hit.via
        if len(self._through_vp) > 64:
            for key in list(self._through_vp)[:-64]:
                del self._through_vp[key]

    def trans_spatial_factor(self, points) -> Optional[float]:
        """DIMLFAC for a paper-space dimension whose definition points all
        came through the SAME viewport: model units per paper unit, so the
        dimension reads the model's length and not the sheet's millimetres.
        None when any point is the sheet's own or they mix viewports."""
        if self.space_vp is not None or self.sheet() is None:
            return None
        handles = set()
        for point in points:
            via = self._through_vp.get(self._point_key(point))
            if via is None:
                return None
            handles.add(via)
        if len(handles) != 1:
            return None
        handle = handles.pop()
        try:
            vp = self.window.document.doc.entitydb.get(handle)
        except Exception:
            return None
        if vp is None or not vp.is_alive:
            return None
        scale = layout_ops.viewport_scale(vp)
        return 1.0 / scale if scale else None

    def to_space(self, wx: float, wy: float) -> tuple[float, float]:
        """A canvas (paper) point -> the current space."""
        vp = self.space_vp
        if vp is None:
            return (wx, wy)
        point = layout_ops.paper_to_model(vp, wx, wy)
        return point if point is not None else (wx, wy)

    def space_factor(self) -> float:
        """Paper units per unit of the current space; 1.0 on the sheet.

        Screen distances (the pickbox, the snap radius) arrive in paper
        units and have to shrink or grow by this before they mean anything
        to a model-space index.
        """
        vp = self.space_vp
        if vp is None:
            return 1.0
        view = layout_ops.viewport_view(vp)
        return view[2] if view is not None else 1.0

    def px_to_space(self, px: float) -> float:
        """A screen distance in logical pixels as a distance of the current
        space -- THE conversion (views.apertures says why there is one).

        The view's scale takes pixels to the canvas; inside MSPACE the
        viewport's scale takes the canvas's paper to the model. A headless
        controller with no canvas counts a pixel as a unit.
        """
        view = getattr(getattr(self.window, "viewport", None), "view", None)
        scale = getattr(view, "scale", 0.0) or 0.0
        canvas = px / scale if scale > 0 else px
        return canvas / self.space_factor()

    def pickbox_px(self) -> float:
        """The live PICKBOX, from the canvas's cache -- not from QSettings:
        this runs on every mouse move, and reading a setting per event is
        exactly the per-event work v0.4.2 removed."""
        return getattr(self.window.viewport, "_pickbox_px", PICKBOX_DEFAULT)

    def sheet(self):
        """The layout whose paper the canvas shows, or None on the Model
        tab -- the same answer on the sheet and inside one of its
        viewports."""
        document = self.window.document
        name = getattr(self.window, "_active_layout", "Model")
        if document is None or name == "Model":
            return None
        try:
            return document.doc.layouts.get(name)
        except Exception:
            return None

    def _flatten_key_for(self, document):
        return (id(document), document.space_name, curve_quality())

    @property
    def _flatten(self) -> float:
        """The overlay's curve tolerance for the CURRENT space: the number
        build_scene derives for the base scene, so an arc drawn now matches
        the arcs already on screen.

        Answered here and nowhere else, cached under (document, space,
        VIEWRES). A tab switch, MSPACE, the block editor and a VIEWRES
        change each move the key, so no caller has to remember to recompute
        -- three used to, with three spellings, and inside the block editor
        the answer was the drawing's header instead of the block's extents.
        """
        document = self.window.document
        if document is None:
            return self._flatten_value
        key = self._flatten_key_for(document)
        if key != self._flatten_key:
            self._flatten_value = _flatten_distance(document.current_space())
            self._flatten_key = key
        return self._flatten_value

    def viewport_crossed(self) -> None:
        """A viewport was entered or left (MSPACE/PSPACE).

        Unlike :meth:`space_changed` this builds nothing: inside a viewport
        nothing is picked or snapped, so the model needs no index there, and
        the sheet's own index and snap engine stay valid for the way back.
        Measured on Planos Constructivos: the warmer this used to start took
        2 s of GIL and left the GUI mute for 0.4 s right after the
        double-click. The selection goes, as AutoCAD drops it across spaces.
        """
        self.selection = set()
        self.reset_pick_cycle()
        self._window_anchor = None
        self._crossing_rects = []
        self._highlight_cache = None
        self._grips_cache = None
        self._sel_entities_cache = None
        self._ghost_cache = None
        self.changed.emit()

    def space_changed(self) -> None:
        """The current space changed under us (tab switch, MSPACE/PSPACE).

        Pick index, snap engine and the overlay's curve tolerance each
        describe ONE space, so all three are rebuilt; the selection goes
        because AutoCAD does not carry a selection across spaces either.
        """
        self.selection = set()
        self.reset_pick_cycle()
        self._window_anchor = None
        self._crossing_rects = []
        self._highlight_cache = None
        self._grips_cache = None
        self._sel_entities_cache = None
        # The model engine a sheet snaps through its viewports with walks
        # the whole model in Python (300-600 ms of GIL on a real plan, the
        # GUI mute meanwhile): a tab switch changes no geometry, so it is
        # kept as long as the drawing has not moved since it was built.
        keep = self._model_snap_engine
        revision = getattr(self.window.document, "revision", None)
        self._invalidate_geometry()
        if keep is not None and revision is not None \
                and revision == getattr(self, "_model_engine_revision", None):
            self._model_snap_engine = keep
        # the overlay's curve tolerance follows the space by itself (the
        # space is part of _flatten's cache key); the ghost built at the old
        # one goes
        self._ghost_cache = None
        # and the new space's caches warm in the background, as at open:
        # on a sheet that includes the model engine the cursor snaps
        # through the viewports with (306 ms in the GUI otherwise, on the
        # first hover over a viewport of a 10 000-entity plan)
        if self.window.document is not None:
            self._start_warmer(self.window.document)
        self.changed.emit()

    def _selection_click(self, wx: float, wy: float, shift: bool) -> None:
        if self.index is None:
            if self.window.document is None:
                return
            self.index = GeometryIndex(self.window.document)
        # Remove(R) at "Select objects": every pick takes away, as Shift does
        shift = shift or (self._selecting_for is not None
                          and getattr(self, "_sel_remove", False))
        force = getattr(self, "_sel_force", None)
        if self._selecting_for is not None and self._window_anchor is not None:
            self._sel_history.append(set(self.selection))   # Undo(U) target
        if force is not None and self._window_anchor is None:
            # Window(W) / Crossing(C): the first click is a corner even on
            # an object, as AutoCAD asks "Specify first corner:"
            self._window_anchor = (wx, wy)
            self.window.command_line.echo_prompt(tr("Specify opposite corner:"))
            return
        if self._window_anchor is not None:
            # second corner: apply window (L->R, fully inside) or crossing
            ax, ay = self._window_anchor
            self._window_anchor = None
            rect = (min(ax, wx), min(ay, wy), max(ax, wx), max(ay, wy))
            crossing = wx < ax if force is None else force == "C"
            if force is not None:
                self._sel_force = None
            hits = self._shown(self.index.crossing(rect) if crossing
                               else self.index.window(rect))
            if crossing and not shift:
                self._crossing_rects.append(rect)
            if shift:
                self.selection -= self._with_groups(hits)
            else:
                self.selection |= self._filtered(self._with_groups(hits))
            self._echo_count()
            if force is not None and self._selecting_for is not None:
                self.window.command_line.echo_prompt(self._selection_prompt())
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
        if self._selecting_for is not None:
            self._sel_history.append(set(self.selection))   # Undo(U) target
        if shift:
            self.reset_pick_cycle()
            self.selection -= self._with_groups([handle])
        else:
            if previous is not None and self._cycle is not None \
                    and previous[1] and self._cycle[2] != previous[2]:
                # cycled: swap the previous candidate out instead of adding
                # the second one -- "I meant the other object", not "both".
                self.selection -= self._with_groups([previous[1][previous[2]]])
            self.selection |= self._filtered(self._with_groups([handle]))
        self._echo_count()

    # -- typed answers at "Select objects:" (AutoCAD's SELECT options) ---------
    _SELECT_OPTIONS = {
        "ALL": "ALL", "TODO": "ALL", "L": "L", "LAST": "L",
        "ULTIMO": "L", "ÚLTIMO": "L", "U": "U", "UNDO": "U", "P": "P", "PREVIOUS": "P", "PREVIO": "P",
        "W": "W", "WINDOW": "W", "V": "W", "VENTANA": "W", "C": "C",
        "CROSSING": "C", "CAPTURA": "C", "R": "R", "REMOVE": "R",
        "E": "R", "ELIMINAR": "R", "A": "A", "ADD": "A", "AÑADIR": "A",
    }

    def _selection_prompt(self) -> str:
        if getattr(self, "_sel_remove", False):
            return tr("Remove objects:")
        return self._selecting_for.selection_prompt()

    def _selection_option(self, text: str) -> None:
        """ALL, Last, Previous, Window, Crossing, Remove and Add, typed at a
        Select Objects prompt (SELECT, Command Reference): the English
        letters, and the Spanish names as an extra. Coordinates answer a
        Window/Crossing corner."""
        echo = self.window.command_line.echo
        option = self._SELECT_OPTIONS.get(text.upper().lstrip("_"))
        document = self.window.document
        if option is None and getattr(self, "_sel_force", None) is not None:
            try:
                point = parse_point(text, None)
            except CoordinateError:
                point = None
            if point is not None:
                x, y = self.current_ucs().to_world(point.x, point.y)
                self._selection_click(x, y, False)
                return
        if option is None or document is None:
            echo(tr("*Invalid selection*"))
            echo(tr("Expects a point or Window/Last/Crossing/ALL/Previous/Undo/Add/Remove"))
            self.window.command_line.echo_prompt(self._selection_prompt())
            return
        if option in ("W", "C"):
            self._sel_force = option
            self._window_anchor = None
            self.window.command_line.echo_prompt(tr("Specify first corner:"))
            return
        if option == "U":
            if self._sel_history:
                self.selection = self._sel_history.pop()
                self._highlight_cache = None
                self._grips_cache = None
            else:
                echo(tr("Everything has been undone"))
            self._echo_count()
        elif option == "R":
            self._sel_remove = True
        elif option == "A":
            self._sel_remove = False
        else:
            if option == "ALL":
                found = set(self._selectable(document.current_space(),
                                             include_off=True))
            elif option == "L":
                found = set()
                for entity in reversed(list(document.current_space())):
                    if self._selectable([entity]):
                        found = {entity.dxf.handle}
                        break
            else:                                    # Previous
                db = document.doc.entitydb
                found = {h for h in getattr(self, "_previous_selection", set())
                         if (e := db.get(h)) is not None and e.is_alive}
            echo(tr("{count} found", count=len(found)))
            self._sel_history.append(set(self.selection))
            if getattr(self, "_sel_remove", False):
                self.selection -= found
            else:
                self.selection |= self._filtered(self._with_groups(found))
            self._highlight_cache = None
            self._grips_cache = None
            self._echo_count()
        self.window.command_line.echo_prompt(self._selection_prompt())

    def _filtered(self, handles) -> set:
        """What the selection filter lets in; says how many it kept out,
        so a filter left on never looks like a pick that failed. With no
        command running (pickfirst) objects on a locked layer stay out too:
        Delete, Ctrl+X, grips and the properties panel all act on that set,
        and none of them may change a locked layer."""
        if self._selecting_for is None and self.tool is None:
            document = self.window.document
            if document is not None:
                db = document.doc.entitydb
                entities = [e for h in handles if (e := db.get(h)) is not None]
                handles = {e.dxf.handle
                           for e in self._unlocked_for(None, entities)}
        if self.pick_filter is None:
            return set(handles)
        from core import pickfilter

        handles = set(handles)
        document = self.window.document
        entity_of = (document.doc.entitydb.get if document is not None
                     else (lambda _h: None))
        kept = pickfilter.keep(handles, entity_of, self.pick_filter)
        if len(kept) < len(handles):
            self.window.command_line.echo(
                tr("{n} object(s) left out by the selection filter.",
                   n=len(handles) - len(kept)))
        return kept

    def set_pick_filter(self, allowed) -> None:
        """Switch the filter: a set of type names, or None for off."""
        self.pick_filter = None if allowed is None else frozenset(allowed)
        self.changed.emit()

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
        self._sel_remove = False
        self._sel_force = None
        self._previous_selection = set(self.selection)
        entities = self._unlocked_for(tool, entities)
        # keep the highlight while the command runs (AutoCAD behavior)
        tool.on_selection(entities)
        self.changed.emit()

    def snap_spacing(self):
        """The grid the cursor jumps by in SNAP mode: SNAPUNIT when the
        drawing sets one (AutoCAD's fixed spacing), else the grid on screen
        (adaptive, like BricsCAD's), so what you see is what you get."""
        from core import drafting

        document = getattr(self.window, "document", None)
        if document is not None:
            try:
                fixed = drafting.snap_unit(document.doc)
            except Exception:
                fixed = 0.0
            if fixed > 0:
                return fixed
        viewport = getattr(self.window, "viewport", None)
        spacing = getattr(viewport, "_grid_spacing", None)
        try:
            value = float(spacing()) if callable(spacing) else 0.0
        except Exception:
            value = 0.0
        return value if value > 0 else None

    def resolved_point(self, wx: float, wy: float) -> tuple[float, float]:
        """Object snap wins over grid snap, which wins over ortho/polar --
        AutoCAD's order; Shift held flips ortho for as long as it is held."""
        if self.tool is not None and self.tool.entity_picker:
            return (wx, wy)  # object picking: raw cursor, no snap/ortho
        if self.snap_hit is not None:
            self._remember_through(self.snap_hit)
            return (self.snap_hit.x, self.snap_hit.y)
        self.track_hint = None
        frame = self.current_ucs()
        if self.snap_on:
            step = self.snap_spacing()
            if step:
                # the snap grid is the UCS's, as the grid on screen is
                ux, uy = frame.to_ucs(wx, wy)
                wx, wy = frame.to_world(round(ux / step) * step,
                                        round(uy / step) * step)
        ortho = self.ortho_on != self.shift_held
        if ortho and self.tool is not None and not self.tool.ortho_applies():
            ortho = False
        anchor = self.anchor_point()
        if self.otrack_on and self._track_points:
            tracked = self._tracked(wx, wy, anchor, ortho)
            if tracked is not None:
                point, source, label = tracked
                self.track_hint = ((source[0], source[1]), point, label)
                return point
        if anchor is not None and ortho:
            # along the UCS's X or Y through the anchor
            c, s = math.cos(frame.angle), math.sin(frame.angle)
            dx, dy = wx - anchor[0], wy - anchor[1]
            along_x, along_y = dx * c + dy * s, -dx * s + dy * c
            if abs(along_x) >= abs(along_y):
                return (anchor[0] + along_x * c, anchor[1] + along_x * s)
            return (anchor[0] - along_y * s, anchor[1] + along_y * c)
        if anchor is not None and self.polar_on:
            # Polar tracking, as AutoCAD's: the cursor is caught by an
            # alignment path only when it comes within the aperture of one,
            # and is free everywhere else. Rounding every point to the
            # nearest polar angle -- what this did before -- made a 30°
            # line impossible with POLAR on, and the increment was a 45°
            # nobody could change (a tester wanted 5°).
            from core import drafting

            tol = self._track_tolerance or self.px_to_space(SNAP_PX)
            locked = drafting.polar_lock(anchor, (wx, wy), self._polar_angles(),
                                         tol, self._polar_base())
            if locked is not None:
                point, direction = locked
                shown = round((direction - frame.degrees) % 360.0, 9)
                self.track_hint = ((anchor[0], anchor[1]), point,
                                   f"{_track_label('polar')}: <{shown:g}°")
                return point
        return (wx, wy)

    # -- dynamic input (DYN) -----------------------------------------------------
    def dyn_lines(self) -> list:
        """What the tooltip beside the cursor says: the prompt (while a
        command runs), then what is being typed, or the live coordinates
        -- absolute for a first point, ``distance < angle`` from the last
        point after it, like AutoCAD's pointer input."""
        if not self.dyn_on or self._cursor is None:
            return []
        lines = []
        if self.tool is not None and self.current_prompt:
            lines.append(self.current_prompt.rstrip(":").strip())
        typed = ""
        edit = getattr(getattr(self.window, "command_line", None), "input", None)
        if edit is not None:
            try:
                typed = edit.text().strip()
            except Exception:
                typed = ""
        if typed:
            lines.append(typed)
            return lines
        units = getattr(self.window, "display_units", None)
        units = units() if callable(units) else None
        x, y = self.resolved_point(*self._cursor)
        anchor = self.anchor_point()
        frame = self.current_ucs()
        if anchor is not None:
            d = math.hypot(x - anchor[0], y - anchor[1])
            ang = (math.degrees(math.atan2(y - anchor[1], x - anchor[0]))
                   - frame.degrees) % 360.0
            if units is not None:
                lines.append(f"{units.length(d)} < {units.angle(ang)}")
            else:
                lines.append(f"{d:.4f} < {ang:.0f}")
            return lines
        x, y = frame.to_ucs(x, y)
        if units is not None:
            lines.append(f"{units.length(x)}, {units.length(y)}")
        else:
            lines.append(f"{x:.4f}, {y:.4f}")
        return lines

    # -- prompt input ----------------------------------------------------------
    def on_text(self, text: str) -> bool:
        """Prompt input while a tool is active. True if consumed."""
        if self._selecting_for is not None:
            if not text.strip():
                self.finish_selection()
                return True
            self._selection_option(text.strip())
            self.changed.emit()
            return True
        if self.tool is None:
            return False
        stripped = text.strip()
        if not stripped:
            self.tool.on_enter()
            self.changed.emit()
            return True
        if not self.tool.entity_picker:
            # END, TAN, NONE... at a point prompt: a one-shot object snap,
            # ahead of the command's own options (AutoCAD reads CEN at
            # ARC's "[Center]" prompt as the snap, C as the option).
            from core import osnap as osnap_modes

            override = osnap_modes.override_from_text(stripped)
            if override is not None:
                self.set_osnap_override(override, typed=True)
                return True
            modifier = osnap_modes.modifier_from_text(stripped)
            if modifier is not None:
                self.start_point_modifier(modifier)
                return True
        if self.tool.on_option(stripped):
            self._preview_now()        # a Text/Angle/Horizontal option changes the picture
            self.changed.emit()
            return True
        direction = None
        anchor = self.tool.last_point
        first_point = anchor is None
        offset_from = (self._modifier.get("base")
                       if self._modifier is not None
                       and self._modifier["kind"] == "FROM" else None)
        if offset_from is not None:
            # FROM's <Offset>: relative to the base point just given
            anchor, first_point = offset_from, True
        if first_point:
            # AutoCAD's LASTPOINT: before a command has a point of its own,
            # a direct distance and a relative @ are measured from the last
            # point entered -- (0, 0) in a fresh drawing. That is why "0"
            # and Enter at "Specify first point:" means the origin (a
            # tester: "en AutoCAD escribir 0 + Intro ya significa 0,0"),
            # and "5" five units from it toward the cursor.
            anchor = self.lastpoint
        if self._cursor is not None:
            constrained = self.resolved_point(*self._cursor)
            direction = math.atan2(constrained[1] - anchor[1],
                                   constrained[0] - anchor[0])
            if self.track_hint is not None and offset_from is None \
                    and is_direct_distance(stripped):
                # On an alignment path -- object snap tracking from an
                # acquired point, an extension, polar -- a typed distance is
                # measured from the path's source along it: AutoCAD's "hover
                # the centre, slide right, type 6". It went from the last
                # point instead, toward the cursor, and the centre landed
                # 19 units below (Rafael's seventh review, 06:16-07:02).
                (sx, sy), (px, py), _label = self.track_hint
                if math.hypot(px - sx, py - sy) > 1e-12:
                    anchor = (sx, sy)
                    direction = math.atan2(py - sy, px - sx)
        else:
            # no pointer yet: along the UCS's +X, as AutoCAD
            direction = self.current_ucs().angle
        try:
            # dynamic input's relative default is for the SECOND point on:
            # the first is absolute (DYNPICOORDS), LASTPOINT or not
            # typed in the user's coordinates: anchor and pointer direction
            # go into the UCS, the answer comes back to the world
            frame = self.current_ucs()
            point = parse_point(stripped, frame.to_ucs(*anchor),
                                direction - frame.angle,
                                relative_default=self.dyn_on and not first_point)
            if point is not None and not frame.is_world:
                point = ParsedPoint(*frame.to_world(point.x, point.y))
        except CoordinateError as exc:
            self.window.command_line.echo(tr("Invalid point: {error}",
                                             error=str(exc)))
            return True
        if point is None:
            self.window.command_line.echo(tr("Invalid input."))
            return True
        self._note_point((point.x, point.y))
        # a typed point releases the acquired points, as a picked one does
        self.clear_tracking()
        if self._modifier is not None:
            final = self._modifier_take((point.x, point.y))
            if final is None:
                self.changed.emit()
                return True
            self.tool.on_point(final)
            self.changed.emit()
            return True
        self.tool.last_snap = None       # a typed point is tied to nothing
        self.tool.on_point((point.x, point.y))
        self.changed.emit()
        return True

    # -- point modifiers (FROM, M2P) -------------------------------------------
    def start_point_modifier(self, kind: str) -> None:
        """FROM or M2P at a point prompt (typed, or from the snap menu)."""
        if self.tool is None:
            return
        self._modifier = {"kind": kind}
        self._on_prompt(tr("Base point:") if kind == "FROM"
                        else tr("First point of mid:"))
        self.changed.emit()

    def _modifier_take(self, point):
        """One point for the modifier in progress; the point for the tool
        when it is complete, else None."""
        m = self._modifier
        if m["kind"] == "FROM":
            if "base" not in m:
                m["base"] = point
                self._on_prompt(tr("<Offset>:"))
                return None
            self._modifier = None
            # a typed @offset or distance is measured from the base; a
            # click or an absolute coordinate cancels FROM (Command
            # Reference) and is used as it is
            return point
        if "first" not in m:
            m["first"] = point
            self._on_prompt(tr("Second point of mid:"))
            return None
        self._modifier = None
        a = m["first"]
        return ((a[0] + point[0]) / 2.0, (a[1] + point[1]) / 2.0)

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
        vp = self.paper_vp
        if vp is not None:
            if self.tool is not None or not vp.is_alive:
                return []
            return [(x, y, role, vp.dxf.handle, i)
                    for i, (x, y, role) in enumerate(layout_ops.viewport_grips(vp))]
        if self.tool is not None or not self.selection or self.index is None:
            return []
        limit = gripobjlimit()
        if 0 < limit < len(self.selection):
            # AutoCAD's GRIPOBJLIMIT (p.2339, default 100): past that many
            # objects grips are suppressed ENTIRELY -- not thinned. Ours
            # used to keep the first 200 entities, which on a cadastre is
            # thousands of squares repainted every single frame (measured:
            # 8.8 ms of a 20 ms frame) for a display nobody can use at that
            # size. 0 means "always show", as the variable documents.
            return []
        # per-frame AND per-hover (grip_at): cache per (version, selection)
        key = (self.index.version, frozenset(self.selection))
        cached = self._grips_cache
        if cached is not None and cached[0] == key:
            return cached[1]
        out = []
        for h in sorted(self.selection):
            e = self.index.entity(h)
            if e is None or not e.is_alive:
                continue
            for i, (x, y, role) in enumerate(entity_grips(e)):
                out.append((x, y, role, h, i))
        self._grips_cache = (key, out)
        return out

    def grip_at(self, wx: float, wy: float, tol: Optional[float] = None):
        """The grip under this CANVAS point, within GRIP_PX -- or within
        ``tol`` canvas units, which only tests pass."""
        wx, wy = self.to_space(wx, wy)
        tol = (self.px_to_space(GRIP_PX) if tol is None
               else tol / self.space_factor())
        for x, y, role, h, i in self.grip_points():
            if abs(x - wx) <= tol and abs(y - wy) <= tol:
                return (x, y, role, h, i)
        return None

    def begin_grip_drag(self, grip) -> None:
        from core.actions import SnapshotCommand
        from core.select import entity_grips

        gx, gy, role, handle, index = grip
        if self.paper_vp is not None:
            # viewport grip: only the rubber rectangle moves until the drop
            self._grip_drag = (_VP_GRIP, index, role, None)
            self.window.viewport.vp_drag_rect = layout_ops.viewport_rect(
                self.paper_vp)
            return
        entity = self.index.entity(handle)
        if entity is None:
            return
        snap = SnapshotCommand([entity])   # captures the pre-grab state
        # and the associative dimensions' (core.dimassoc), for the drop
        self._grip_dimassoc = self.window.history.dimassoc_state()
        self._grip_drag = (handle, index, role, snap)
        self._grip_base = (gx, gy)
        # Hide the base-scene copy ONCE (a full-scene re-upload); from here
        # the live entity rides the cheap 1-entity overlay each frame.
        self.window.viewport.hide_handles([handle])
        if entity.dxftype() == "IMAGE":
            # hide_handles hides the frame AND the pixels; the pixels can
            # stay — the drag moves their quad surgically, no regen.
            self.window.viewport.show_image(handle)
        self._refresh_overlay()

    def current_ucs(self):
        """The UCS typed points, the readout, ORTHO, POLAR and the grid
        follow (core/ucs.py): the model's, the world elsewhere."""
        from core import ucs

        return ucs.current(self.window.document)

    def anchor_point(self):
        """The point ORTHO, POLAR, tracking and PERpendicular measure from:
        the command's last point, or -- dragging a hot grip, when no command
        runs -- where the grip was grabbed, as AutoCAD's grip STRETCH/MOVE
        take it. Without it a grip ignored ORTHO (#60)."""
        if self.tool is not None:
            return self.tool.last_point
        drag = self._grip_drag
        if drag is not None and drag[0] != _VP_GRIP:
            return self._grip_base
        return None

    def grip_target(self, wx: float, wy: float) -> tuple[float, float]:
        """Where the hot grip should sit: the same order a command's point
        takes -- object snap, grid snap, ortho, tracking, polar."""
        return self.resolved_point(*self.to_space(wx, wy))

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
            if entity.dxftype() == "IMAGE":
                # the pixels ride along live (6 quad vertices per frame) and
                # the vector overlay is skipped: the frontend cannot draw an
                # IMAGE without DECODING its file, which on a scanned sheet
                # put a 36 MB PIL decode inside every mouse move.
                self._sync_image_quad(entity)
                self.window.viewport.update()
                return
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
            radial = int(entity.dxf.get("dimtype", 0)) & 7 in (3, 4)
            if role == "dim_text" and radial:
                # A radius or diameter is laid out FROM its text: the line
                # turns to follow it and the arrow walks around the circle,
                # as AutoCAD draws it. Moving the number alone left them
                # pointing at nothing (Rafael's sixth review, #67).
                command = actions.DimTextEditCommand(
                    entity, location=(wx, wy), turn=True)
            elif role == "dim_text" and _text_carries_line(entity):
                # DIMTMOVE 0, AutoCAD's default: the line goes with the text
                command = actions.DimTextWithLineCommand(entity, (wx, wy))
            elif role == "dim_text":
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
            self.window.history.record(snap, self._grip_dimassoc)
            self._grip_dimassoc = None
            self._show_reacted(snap)
            # grips/snap see the new shape; both caches are patched, not
            # rebuilt (a full rebuild froze the next pick on big files)
            self._drop_conflicting_stamps([handle])
            if self.snap_engine is not None:
                self.snap_engine.remove_handles([handle])
                self.snap_engine.add_entities([entity])
            if self.index is not None:
                self.index.remove_handles([handle])
                self.index.add_entities([entity])
            if entity.dxftype() == "IMAGE":
                # The pixels are already at their new place (the live quad);
                # the frame catches up at the deferred merge. The entity
                # stays OUT of the vector overlay: drawing an IMAGE through
                # the frontend decodes its file, and pending_render would
                # redo that on every later overlay refresh until the merge.
                self._refresh_overlay()   # drop whatever the grab mounted
                if self._sync_image_quad(entity):
                    self._merge_timer.start()
                else:
                    # no quad to move (file vanished): only a regen is right
                    self.window.regen_in_memory()
                self.changed.emit()
                return
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
            self._merge_timer.start()

    def _sync_image_quad(self, entity) -> bool:
        """Reposition a raster image's pixels surgically; True on success.

        The texture is untouched by a move or resize — only the quad's four
        corners change, computed from the entity's own transform (no pixel
        load, no frontend: pure math per mouse move). False sends the
        caller to a regen, e.g. when the scene holds no quad for it.
        """
        from render.backend import image_corners_wcs

        handle = entity.dxf.handle
        scene = self.window.viewport._scene
        quad = None
        for im in getattr(scene, "images", []) if scene is not None else []:
            if im.handle == handle:
                quad = im
                break
        if quad is None:
            return False
        height, width = quad.pixels.shape[:2]
        corners = image_corners_wcs(entity, (width, height))
        if corners is None:
            return False
        self.window.viewport.update_image_quad(handle, corners)
        self.window.viewport.show_image(handle)
        return True

    def grip_overlay_entities(self):
        if self._grip_drag is None:
            return []
        entity = self.index.entity(self._grip_drag[0])
        if entity is None or not entity.is_alive:
            return []
        if entity.dxftype() == "IMAGE":
            # Never in the vector overlay: rendering an IMAGE decodes its
            # file, and the overlay built at grab time kept the OLD frame
            # on screen until the merge — the live quad is the feedback.
            return []
        return [entity]

    def highlight_geometry(self):
        """(segments, circles, boxes) of the current selection, world coords.

        Called every paint frame: cached per (index version, selection) —
        the isin sweep over a cadastre's 1.35 M rows costs ~40 ms and must
        not run per frame.
        """
        if not self.selection or self.index is None:
            empty = np.empty((0, 4))
            return empty, empty, empty
        key = (self.index.version, frozenset(self.selection))
        cached = self._highlight_cache
        if cached is not None and cached[0] == key:
            return cached[1]
        if self.index._dirty and self._warmers and self._big_space():
            # a warmer is rebuilding the index in the background: building it
            # here too froze the window for seconds on a big selection. Keep
            # the last highlight (or none) until the warm index lands.
            if cached is not None:
                return cached[1]
            empty = np.empty((0, 4))
            return empty, empty, empty
        result = self.index.highlight_of(self.selection)
        self._highlight_cache = (key, result)
        return result
