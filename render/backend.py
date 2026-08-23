# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""GL vertex backend for ``ezdxf.addons.drawing`` — the "regen" engine.

The ezdxf frontend resolves the hard CAD semantics (block references, MTEXT
layout, linetype dashing, hatch patterns, dimension graphics, OCS) and hands
this backend nothing but resolved 2D primitives with final colors. We collect
them into (layer, color) buckets and pack them into GPU-ready arrays.

Curves are flattened at a fixed world-space tolerance derived from the
drawing size — a "regen", AutoCAD-style. Deep zoom-in past that tolerance
shows facets until a future re-regen at view scale (known trade-off, F1).
"""
from __future__ import annotations

import math
from typing import Iterable, Optional

from ezdxf import bbox
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.backend import Backend, BkPath2d, BkPoints2d
from ezdxf.addons.drawing.config import Configuration
from ezdxf.addons.drawing.properties import BackendProperties
from ezdxf.math import Vec2
from ezdxf.math.triangulation import mapbox_earcut_2d

import logging

from core.document import Document
from render.batches import Bucket, Scene, pack

logger = logging.getLogger(__name__)

# Curve flattening: max sagitta as a fraction of the drawing diagonal.
# 1/20000 keeps a full-drawing circle visually smooth and stays sane on
# kilometre-scale UTM drawings.
FLATTEN_REL = 1.0 / 20000.0
MIN_FLATTEN = 1e-6

# Hatch density cap, AutoCAD MaxHatch style: pattern lines closer than this
# fraction of the flattening distance fall back to ezdxf's solid fill. Keep
# it generous — stipple patterns (AR-CONC, sand) on detail sheets are much
# finer than the sheet-wide flatten distance and must render as patterns
# (pavement-plan lesson: 1/4 turned them all into solid blobs). The timeout
# below, not this cap, is what contains pathological hatches.
HATCH_DENSITY_REL = 1.0 / 64.0
# Backstop for hatches that explode combinatorially: ezdxf aborts the pattern
# after this many seconds and falls back to a solid fill. This is what turned
# a frozen 287 s open (30 s x ~40 hatches) into ~3 s.
HATCHING_TIMEOUT = 5.0


# Layout-tab canvas: the gray "desk" around the white paper sheet (AutoCAD's
# paper background). Slightly lighter than the model-space dark so the two
# spaces read differently at a glance.
PAPER_SURROUND = (0.235, 0.255, 0.275, 1.0)


# Entity types whose fills are text glyphs; they dominate label-heavy plans
# (a cadastre: 43 M of 49 M vertices) and the viewport hides them when they
# would be smaller than a few pixels.
_TEXT_TYPES = frozenset(("TEXT", "MTEXT", "ATTRIB", "ATTDEF"))


class VertexBackend(Backend):
    """Collects frontend primitives into per-(layer, color) buckets."""

    def __init__(self, flatten_distance: float,
                 order_groups: dict[str, int] | None = None) -> None:
        super().__init__()
        self.buckets: dict[tuple, Bucket] = {}
        self._flatten = flatten_distance
        self._order_groups = order_groups or {}
        self._kind = ""
        self._handle = None
        self._group = 0
        # Raster IMAGEs: [{"pixels", "corners" (4 wcs xy), "handle", "group"}]
        self.images: list[dict] = []
        # (kind, owner, group) per open entity. The frontend NESTS these: an
        # INSERT is entered, then each of its sub-entities, up to three deep in
        # real drawings.
        self._open: list[tuple[str, str | None]] = []
        self.background: str | None = None

    def enter_entity(self, entity, properties) -> None:
        super().enter_entity(entity, properties)
        kind = "T" if entity.dxftype() in _TEXT_TYPES else ""
        handle = getattr(entity.dxf, "handle", None)
        # Attribute the primitives to the OUTERMOST entity that has a handle.
        # Block content is drawn from virtual copies whose handle is None, and
        # even when it is not, a block-definition handle is useless here: the
        # selection and the pick index only ever hold the modelspace entity.
        # Without this, every vertex inside a block was unowned, so
        # Viewport.hide_handles could not hide it and an erased block stayed on
        # screen until the next full regen.
        if self._open and self._open[-1][1] is not None:
            handle = self._open[-1][1]
        # The DRAWORDER group follows the same outermost-owner attribution.
        group = (self._open[-1][2] if self._open
                 else self._order_groups.get(handle, 0))
        self._open.append((kind, handle, group))
        self._kind, self._handle, self._group = kind, handle, group

    def exit_entity(self, entity) -> None:
        super().exit_entity(entity)
        if self._open:
            self._open.pop()
        # Restore the enclosing entity's context rather than clearing it: a
        # parent keeps emitting primitives after a child exits, and those used
        # to come out unowned (and untyped, which also mis-keyed their bucket).
        self._kind, self._handle, self._group = (
            self._open[-1] if self._open else ("", None, 0))

    def _bucket(self, properties: BackendProperties) -> Bucket:
        key = (self._group, properties.layer, properties.color,
               properties.lineweight, self._kind)
        bucket = self.buckets.get(key)
        if bucket is None:
            bucket = self.buckets[key] = Bucket(
                properties.layer, properties.color, properties.lineweight,
                self._kind, group=self._group,
            )
        return bucket

    # -- primitives -----------------------------------------------------------
    def draw_point(self, pos: Vec2, properties: BackendProperties) -> None:
        b = self._bucket(properties)
        b.points.extend((pos.x, pos.y))
        b.points_owner.append(self._handle)

    def draw_line(self, start: Vec2, end: Vec2, properties: BackendProperties) -> None:
        b = self._bucket(properties)
        b.lines.extend((start.x, start.y, end.x, end.y))
        b.lines_owner.append(self._handle)

    def draw_solid_lines(
        self, lines: Iterable[tuple[Vec2, Vec2]], properties: BackendProperties
    ) -> None:
        b = self._bucket(properties)
        for start, end in lines:
            b.lines.extend((start.x, start.y, end.x, end.y))
            b.lines_owner.append(self._handle)

    def draw_path(self, path: BkPath2d, properties: BackendProperties) -> None:
        b = self._bucket(properties)
        prev: Vec2 | None = None
        for v in path.flattening(self._flatten):
            if prev is not None:
                b.lines.extend((prev.x, prev.y, v.x, v.y))
                b.lines_owner.append(self._handle)
            prev = v

    def draw_filled_polygon(
        self, points: BkPoints2d, properties: BackendProperties
    ) -> None:
        self._fill(points.vertices(), [], properties)

    def draw_filled_paths(
        self, paths: Iterable[BkPath2d], properties: BackendProperties
    ) -> None:
        # Each path may carry several sub-paths: holes (the "O", hatch
        # islands) but ALSO detached outlines — the tilde of an "ñ", the
        # dot of an "i", a hatch with separate lobes. "Largest ring is the
        # exterior, the rest are holes" silently DROPPED every detached
        # outline (an outside "hole" tessellates to nothing): baño drew as
        # bano. Classify by even-odd nesting instead: a ring inside an even
        # number of others is an exterior, odd makes it a hole of its
        # innermost container.
        # The nesting runs over ALL rings of the CALL, not per path: the
        # paperspace viewport clipper explodes a multi-ring glyph into
        # sibling single-ring paths, and per-path nesting then filled the
        # O's counter solid on every layout tab.
        rings: list[list] = []
        for path in paths:
            for sub in path.sub_paths():
                ring = list(sub.flattening(self._flatten))
                if len(ring) >= 3:
                    rings.append(ring)
        if not rings:
            return
        rings.sort(key=_ring_extent, reverse=True)
        groups: list[tuple[list, list]] = []   # (exterior, holes)
        group_of: dict[int, int] = {}          # ring index -> group index
        for i, ring in enumerate(rings):
            containers = [j for j in range(i)
                          if _point_in_ring(ring[0], rings[j])]
            if len(containers) % 2 == 0:
                group_of[i] = len(groups)
                groups.append((ring, []))
            else:
                # innermost container: the smallest ring holding it
                # (rings are sorted big to small, so the last one).
                owner = containers[-1]
                while owner not in group_of and containers:
                    containers.pop()
                    owner = containers[-1] if containers else 0
                groups[group_of.get(owner, 0)][1].append(ring)
        if self._kind == "T":
            # Legibility metric for the viewport's tiny-text culling: one
            # entry per exterior (a glyph), like the old per-path entry.
            bucket = self._bucket(properties)
            for exterior, _holes in groups:
                ys = [v.y for v in exterior]
                bucket.text_height_sum += max(ys) - min(ys)
                bucket.text_count += 1
        for exterior, holes in groups:
            self._fill(exterior, holes, properties)

    def _fill(
        self,
        exterior: list[Vec2],
        holes: list[list[Vec2]],
        properties: BackendProperties,
    ) -> None:
        if len(exterior) < 3:
            return
        try:
            triangles = mapbox_earcut_2d(exterior, holes or None)
        except (ValueError, ZeroDivisionError):
            return  # degenerate ring: drop the fill, keep going
        bucket = self._bucket(properties)
        for a, b, c in triangles:
            bucket.triangles.extend((a.x, a.y, b.x, b.y, c.x, c.y))
            bucket.triangles_owner.append(self._handle)

    def draw_image(self, image_data, properties: BackendProperties) -> None:
        """Capture the pixels and the world-space quad; GL textures them.

        The transform maps pixel coordinates (top-left origin, y down) to
        WCS. Non-rectangular clip boundaries still show the full quad — the
        clip FRAME is drawn by the frontend either way; pixel-exact clipping
        can come later without touching the format.
        """
        w, h = image_data.image_size()
        if not w or not h:
            return
        m = image_data.transform
        corners = [m.transform((x, y, 0.0))
                   for (x, y) in ((0.0, 0.0), (w, 0.0), (w, h), (0.0, h))]
        self.images.append({
            "pixels": image_data.image,
            "corners": [(c.x, c.y) for c in corners],
            "handle": self._handle,
            "group": self._group,
        })

    # -- lifecycle --------------------------------------------------------------
    def configure(self, config: Configuration) -> None:
        pass

    def set_background(self, color: str) -> None:
        # Captured for paperspace layouts (white paper, like AutoCAD's
        # layout tabs); modelspace keeps the viewport's own dark canvas.
        self.background = color

    def clear(self) -> None:
        self.buckets.clear()

    def finalize(self) -> None:
        pass


def _point_in_ring(point, ring) -> bool:
    """Ray-cast point-in-polygon over a flattened ring (Vec2 list)."""
    x, y = point.x, point.y
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        yi, yj = ring[i].y, ring[j].y
        if (yi > y) != (yj > y):
            xi, xj = ring[i].x, ring[j].x
            if x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
        j = i
    return inside


def _ring_extent(ring: list[Vec2]) -> float:
    xs = [v.x for v in ring]
    ys = [v.y for v in ring]
    return (max(xs) - min(xs)) * (max(ys) - min(ys))


def pick_layout(document: Document):
    """The layout worth showing on open: the saved tab, or a sane fallback.

    ``$TILEMODE`` = 0 means the file was saved with a paperspace tab current;
    AutoCAD reopens there and so do we. Otherwise modelspace — unless it is
    genuinely empty and everything lives in a paper layout (ArchiCAD-published
    sheets, some AutoCAD workflows): AutoCAD opens those showing the layout;
    a blank canvas here would read as a converter bug. Returns (layout, name)
    — name is None for plain modelspace.
    """
    from core.layouts import startup_tab

    saved = startup_tab(document)
    if saved is not None:
        try:
            return document.doc.layouts.get(saved), saved
        except Exception:
            pass
    msp = document.modelspace()
    if len(msp) > 0:
        return msp, None
    best = None
    for layout in document.doc.layouts:
        if layout.name == "Model":
            continue
        if len(layout) > 0 and (best is None or len(layout) > len(best)):
            best = layout
    if best is not None:
        return best, best.name
    return msp, None


def _layout_extents(layout):
    try:
        return bbox.extents(layout, fast=True)
    except Exception:
        # One malformed entity (e.g. a HATCH spline edge with bad knots)
        # aborts the whole-layout pass; retry entity by entity and keep
        # whatever measures cleanly.
        from ezdxf.math import BoundingBox

        total = BoundingBox()
        for entity in layout:
            try:
                one = bbox.extents([entity], fast=True)
            except Exception:
                continue
            if one.has_data:
                total.extend([one.extmin, one.extmax])
        return total


def _header_diagonal(layout) -> Optional[float]:
    """The drawing's own extents, from the header — free, and good enough.

    ``bbox.extents`` walks every entity: 8 s on a 10 847-entity plan, a third
    of a whole regen, spent only to pick how finely curves are flattened. The
    header carries what AutoCAD stored for the same rectangle, and measured
    over real drawings it yields the SAME tolerance (ratios 1.000-1.002).

    Returns None whenever the header cannot be trusted -- absent, infinite,
    degenerate, or carrying the +-1e20 sentinel a never-regenerated drawing
    keeps -- and the caller then pays for the walk.
    """
    doc = getattr(layout, "doc", None)
    if doc is None:
        return None
    paper = getattr(layout, "is_any_paperspace", False)
    lo_key, hi_key = ("$PEXTMIN", "$PEXTMAX") if paper else ("$EXTMIN", "$EXTMAX")
    try:
        lo, hi = doc.header[lo_key], doc.header[hi_key]
        dx, dy = float(hi[0]) - float(lo[0]), float(hi[1]) - float(lo[1])
    except Exception:
        return None
    if not (math.isfinite(dx) and math.isfinite(dy)):
        return None
    diagonal = math.hypot(dx, dy)
    # A drawing that never regenerated keeps 1e20 sentinels, and dx then comes
    # out astronomically wrong (or negative). Neither is a drawing.
    if not (0.0 < diagonal < 1e15):
        return None
    return diagonal


def _flatten_distance(layout) -> float:
    diagonal = _header_diagonal(layout)
    if diagonal is None:
        extents = _layout_extents(layout)
        if not extents.has_data:
            return 0.01
        dx = extents.extmax.x - extents.extmin.x
        dy = extents.extmax.y - extents.extmin.y
        diagonal = (dx * dx + dy * dy) ** 0.5
    return max(diagonal * FLATTEN_REL, MIN_FLATTEN)


class TolerantRenderContext(RenderContext):
    """Property resolution that survives malformed entities.

    resolve_all runs before draw_entity, outside the frontend's per-entity
    guard: a HATCH with pattern_scale 0 (seen after a LibreDWG roundtrip)
    raises ZeroDivisionError there and would blank the whole drawing. Fall
    back to plain defaults for that entity and keep drawing.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # An unsaved drawing has no document_dir, and the frontend refuses
        # to load IMAGE files without one — even when the IMAGEDEF stores an
        # absolute path (pathlib joins absolute onto anything cleanly). Any
        # directory unlocks that case; relative paths resolve on save.
        if self.document_dir is None:
            import pathlib

            self.document_dir = pathlib.Path.cwd()

    def resolve_all(self, entity):
        try:
            return super().resolve_all(entity)
        except Exception as exc:
            handle = getattr(entity.dxf, "handle", None) or "?"
            logger.warning(
                "default properties for %s(#%s): %s",
                entity.dxftype(), handle, exc,
            )
            from ezdxf.addons.drawing.properties import Properties

            return Properties()


class TolerantFrontend(Frontend):
    """Frontend that survives malformed entities.

    Real-world files (and satellite conversions) carry broken geometry —
    e.g. LibreDWG emitting HATCH spline edges with inconsistent knot counts.
    AutoCAD still opens those plans; one bad entity must never blank the
    whole drawing. Failures are skipped, logged, and counted for the UI.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.skipped: list[str] = []

    #: Handles hidden by ISOLATEOBJECTS/HIDEOBJECTS. Display only: the
    #: entity stays in the document, it is simply not drawn.
    hidden_handles: frozenset = frozenset()

    def draw_entity(self, entity, properties) -> None:
        if self.hidden_handles:
            handle = getattr(entity.dxf, "handle", None)
            if handle and handle in self.hidden_handles:
                return
        # ezdxf's draw_entity calls enter_entity BEFORE drawing and
        # exit_entity after; an exception mid-draw skips the exit (for the
        # entity and any open children). Unwind to this depth or the stale
        # frames own every entity drawn afterwards — their vertices become
        # invisible to hide_handles and inherit the wrong kind/group.
        backend = getattr(self.pipeline, "backend", None)
        depth = len(getattr(backend, "_open", ()))
        try:
            super().draw_entity(entity, properties)
        except Exception as exc:
            handle = getattr(entity.dxf, "handle", None) or "?"
            note = f"{entity.dxftype()}(#{handle}): {exc}"
            self.skipped.append(note)
            logger.warning("skipped unrenderable entity %s", note)
            while backend is not None and len(backend._open) > depth:
                backend.exit_entity(entity)


def frontend_config(flatten: float) -> Configuration:
    return Configuration(
        max_flattening_distance=flatten,
        min_hatch_line_distance=flatten * HATCH_DENSITY_REL,
        hatching_timeout=HATCHING_TIMEOUT,
    )


def _declared_extents(document) -> Optional[tuple[float, float, float, float]]:
    """The drawing's own $EXTMIN/$EXTMAX, or None when it is not usable.

    Used by the packer to tell a corrupt coordinate from a far-off detail. On
    every real file checked here these matched ODA File Converter exactly, even
    when individual entities carried garbage.
    """
    try:
        lo = document.doc.header["$EXTMIN"]
        hi = document.doc.header["$EXTMAX"]
    except Exception:
        return None
    try:
        box = (float(lo[0]), float(lo[1]), float(hi[0]), float(hi[1]))
    except Exception:
        return None
    if not all(math.isfinite(v) for v in box):
        return None
    return box


def build_scene_for_entities(document: Document, entities, flatten: float) -> Scene:
    """Pack just ``entities`` (freshly drawn ones) into a small overlay scene.

    Drawing must feel instant on any file size: instead of a full regen per
    added entity, the viewport draws this overlay on top of the base scene
    and merges on the next real regen. ``flatten`` comes from the base scene
    build so curve quality matches.
    """
    from core.isolate import hidden_handles

    backend = VertexBackend(flatten)
    context = TolerantRenderContext(document.doc)
    frontend = TolerantFrontend(context, backend, frontend_config(flatten))
    frontend.hidden_handles = frozenset(hidden_handles(document))
    frontend.draw_entities(entities)
    return pack(backend.buckets, _declared_extents(document))


def _draw_viewport_borders(layout, context, backend) -> None:
    """Synthesize the frame of every floating viewport.

    The ezdxf frontend draws viewport CONTENT (clipped, scaled) but not the
    border AutoCAD shows around it. Drawn through the backend's own entity
    path so the vertices are attributed to the VIEWPORT handle (hide/undo
    work surgically). Mirrors the frontend's _draw_viewports status
    heuristic exactly, so borders and content always agree on which
    viewports exist — including skipping the unreliable "main" viewport
    that represents the paper view itself.
    """
    from ezdxf.math import Vec2

    from core.layouts import visible_viewports

    for vp in visible_viewports(layout):
        try:
            properties = context.resolve_all(vp)
            cx, cy = vp.dxf.center.x, vp.dxf.center.y
            hw, hh = vp.dxf.width / 2.0, vp.dxf.height / 2.0
            corners = [Vec2(cx - hw, cy - hh), Vec2(cx + hw, cy - hh),
                       Vec2(cx + hw, cy + hh), Vec2(cx - hw, cy + hh)]
            backend_props = BackendProperties(
                color=properties.color or "#000000",
                lineweight=properties.lineweight or 0.25,
                layer=properties.layer or "0",
                pen=1,
                handle=vp.dxf.handle,
            )
            backend.enter_entity(vp, properties)
            for a, b in zip(corners, corners[1:] + corners[:1]):
                backend.draw_line(a, b, backend_props)
            backend.exit_entity(vp)
        except Exception:
            continue    # one broken viewport must not blank the sheet


def build_scene(document: Document, layout_name: str | None = None) -> Scene:
    """Run the ezdxf frontend over the drawing and pack the result ("regen").

    ``layout_name`` selects a tab explicitly: "Model" renders modelspace with
    no fallback (the user clicked that tab — an empty canvas is the truth),
    any other name renders that paperspace layout, and None lets
    :func:`pick_layout` choose (file open: saved tab / empty-model fallback).
    """
    if layout_name == "Model":
        layout, layout_name = document.modelspace(), None
    elif layout_name and layout_name in document.doc.layouts:
        layout = document.doc.layouts.get(layout_name)
    else:
        layout, layout_name = pick_layout(document)
    flatten = _flatten_distance(layout)
    from core.draworder import order_groups

    from core.isolate import hidden_handles

    backend = VertexBackend(flatten, order_groups(layout))
    context = TolerantRenderContext(document.doc)
    frontend = TolerantFrontend(context, backend, frontend_config(flatten))
    frontend.hidden_handles = frozenset(hidden_handles(document))
    frontend.draw_layout(layout)
    if layout_name is not None:
        _draw_viewport_borders(layout, context, backend)
    scene = pack(backend.buckets, _declared_extents(document),
                 images=backend.images)
    scene.skipped = list(frontend.skipped)
    scene.layout_name = layout_name
    scene.flatten = flatten
    if layout_name is not None:
        # Layout tab look: gray desk around a white paper sheet (the viewport
        # draws the sheet itself from scene.paper). Entity colors were already
        # resolved by ezdxf against a white background, so ACI 7 reads black.
        from core.layouts import paper_frame

        scene.background = PAPER_SURROUND
        try:
            scene.paper = paper_frame(layout)
        except Exception:
            scene.paper = None   # a broken page setup must not blank the tab
    return scene
