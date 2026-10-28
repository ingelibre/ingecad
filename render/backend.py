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
import os
from typing import Iterable, Optional

import numpy as np

from ezdxf import bbox
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.backend import Backend, BkPath2d, BkPoints2d
from ezdxf.addons.drawing.config import Configuration
from ezdxf.addons.drawing.properties import BackendProperties
from ezdxf.math import Vec2
from ezdxf.math.triangulation import mapbox_earcut_2d

import logging

from core.document import Document
from render.batches import THIN_MAX_MM, Bucket, Scene, pack

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


# The canvas colours (model dark, the gray "desk" around the paper sheet,
# the Block Editor's warm tone) live in core.window_colors now — the user
# picks them in the Drawing Window Colors dialog, defaults unchanged.


# Entity types whose fills are text glyphs; they dominate label-heavy plans
# (a cadastre: 43 M of 49 M vertices) and the viewport hides them when they
# would be smaller than a few pixels.
_TEXT_TYPES = frozenset(("TEXT", "MTEXT", "ATTRIB", "ATTDEF"))
#: Infinite by definition: drawn far past the drawing (frontend_config) and
#: left out of its extents (bucket kind "X", batches._world_extents)
_CONSTRUCTION_TYPES = frozenset(("XLINE", "RAY"))
#: How far a construction line reaches, in drawing diagonals (both halves of
#: an XLINE together; a RAY all of it)
CONSTRUCTION_SPAN = 10.0


def _text_size_step(entity) -> int:
    """A text's height as a power of two, for its bucket key.

    Text under 2 px is culled per batch range by the range's AVERAGE glyph
    height, and a layer's texts shared one batch whatever their size: a
    title among a thousand small labels took their average and vanished
    with them (GeoCad's review). Batched by step, the texts of a range are
    within a factor of two of each other."""
    try:
        height = float(entity.dxf.char_height if entity.dxftype() == "MTEXT"
                       else entity.dxf.height)
    except Exception:            # noqa: BLE001 - no height: one step for all
        return 0
    return math.floor(math.log2(height)) if height > 0 else 0


def _image_quad_corners(image_data) -> Optional[list]:
    """The image's WCS quad, WITHOUT touching the pixels.

    One home for the corner math: the full build and the surgical
    move/resize both call this, so they cannot drift apart. Accessing
    ``image_data.image`` is what loads the file from disk — a live grip
    drag must not pay that per mouse move on a scanned sheet.
    """
    w, h = image_data.image_size()
    if not w or not h:
        return None
    m = image_data.transform
    return [(c.x, c.y) for c in
            (m.transform((x, y, 0.0))
             for (x, y) in ((0.0, 0.0), (w, 0.0), (w, h), (0.0, h)))]


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
        self._size = 0
        # Raster IMAGEs: [{"pixels", "corners" (4 wcs xy), "handle", "group"}]
        self.images: list[dict] = []
        # (kind, owner, group, size step) per open entity. The frontend NESTS
        # these: an INSERT is entered, then each of its sub-entities, up to
        # three deep in real drawings.
        self._open: list[tuple] = []
        self.background: str | None = None

    def enter_entity(self, entity, properties) -> None:
        super().enter_entity(entity, properties)
        dxftype = entity.dxftype()
        kind = ("T" if dxftype in _TEXT_TYPES
                else "X" if dxftype in _CONSTRUCTION_TYPES else "")
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
        size = _text_size_step(entity) if kind == "T" else 0
        self._open.append((kind, handle, group, size))
        self._kind, self._handle, self._group, self._size = (
            kind, handle, group, size)

    def exit_entity(self, entity) -> None:
        super().exit_entity(entity)
        if self._open:
            self._open.pop()
        # Restore the enclosing entity's context rather than clearing it: a
        # parent keeps emitting primitives after a child exits, and those used
        # to come out unowned (and untyped, which also mis-keyed their bucket).
        self._kind, self._handle, self._group, self._size = (
            self._open[-1] if self._open else ("", None, 0, 0))

    def _bucket(self, properties: BackendProperties) -> Bucket:
        key = (self._group, properties.layer, properties.color,
               properties.lineweight, self._size, self._kind)
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
        if start.x == end.x and start.y == end.y and b.lineweight <= THIN_MAX_MM:
            self._dot(b, start)
            return
        b.lines.extend((start.x, start.y, end.x, end.y))
        b.lines_owner.append(self._handle)

    def draw_solid_lines(
        self, lines: Iterable[tuple[Vec2, Vec2]], properties: BackendProperties
    ) -> None:
        b = self._bucket(properties)
        thin = b.lineweight <= THIN_MAX_MM
        for start, end in lines:
            if thin and start.x == end.x and start.y == end.y:
                self._dot(b, start)
                continue
            b.lines.extend((start.x, start.y, end.x, end.y))
            b.lines_owner.append(self._handle)

    def _dot(self, b: Bucket, at: Vec2) -> None:
        """The 0.0 dash of a linetype -- DASHDOT's, CENTER's, PHANTOM's dot
        -- arrives as a zero-length line, which GL rasterizes as nothing:
        the dots were missing (#87, Rafael). A thin one is a one-pixel
        point, as AutoCAD shows it; a thick one stays a segment and the
        packer squares it to the pen's width (batches._pack_thick)."""
        b.points.extend((at.x, at.y))
        b.points_owner.append(self._handle)

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
        if self._kind == "T":
            # Inside a text entity this call is the BACKGROUND MASK (the
            # glyphs arrive through draw_filled_paths). It must paint under
            # the glyphs, but batching splits them into sibling buckets
            # keyed by colour, and the pack order between siblings is
            # alphabetical: on a sheet the window-colour mask is paper
            # white, "#ffffff" sorts after the black glyphs, and every
            # masked label erased its own text. (The model tab survived by
            # luck: its mask colour "#212830" happens to sort first.)
            # A kind of its own lets pack() slot masks between the ordinary
            # fills and the glyphs.
            self._fill_as(points.vertices(), [], properties, "TM")
            return
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
        # One bounding box per ring, computed once. It pays twice: the sort
        # below used to rebuild two coordinate lists per comparison, and the
        # containment test that follows is O(rings^2) -- 387 543 ray casts on
        # a real plan. A ring cannot contain a point outside its box, so the
        # box rejects almost all of those pairs before any ray is cast. Exact:
        # box containment is a necessary condition, never a sufficient one --
        # a concave ring still needs the ray, and there is a test for that.
        boxes = [_ring_box(ring) for ring in rings]
        order = sorted(range(len(rings)), key=lambda i: _box_extent(boxes[i]),
                       reverse=True)
        rings = [rings[i] for i in order]
        boxes = [boxes[i] for i in order]
        groups: list[tuple[list, list]] = []   # (exterior, holes)
        group_of: dict[int, int] = {}          # ring index -> group index
        for i, ring in enumerate(rings):
            px, py = ring[0].x, ring[0].y
            containers = [
                j for j in range(i)
                if boxes[j][0] <= px <= boxes[j][2]
                and boxes[j][1] <= py <= boxes[j][3]
                and _point_in_ring(ring[0], rings[j])]
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

    def _fill_as(
        self,
        exterior: list[Vec2],
        holes: list[list[Vec2]],
        properties: BackendProperties,
        kind: str,
    ) -> None:
        """``_fill`` into a bucket of ``kind`` instead of the entity's."""
        keep = self._kind
        self._kind = kind
        try:
            self._fill(exterior, holes, properties)
        finally:
            self._kind = keep

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
        corners = _image_quad_corners(image_data)
        if corners is None:
            return
        self.images.append({
            "pixels": image_data.image,
            "corners": corners,
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

    # -- block instancing (#29) --------------------------------------------------
    def begin_capture(self) -> tuple:
        """Record what is drawn from now on apart from the scene: a block's
        content, drawn once at the origin. Returns what end_capture needs."""
        saved = (self.buckets, self.images)
        self.buckets, self.images = {}, []
        return saved

    def end_capture(self, saved) -> Optional[list]:
        """The recording -- [(bucket key, template bucket, lines, triangles,
        points as (n, 2) arrays)] -- or None when it cannot be replayed
        (it drew a raster image). The scene's own buckets come back."""
        import numpy as np

        buckets, images = self.buckets, self.images
        self.buckets, self.images = saved
        if images:
            return None
        recording = []
        for key, b in buckets.items():
            arrays = tuple(np.asarray(v, dtype=np.float64).reshape(-1, 2)
                           for v in (b.lines, b.triangles, b.points))
            recording.append((key, b, *arrays))
        return recording

    def replay(self, recording, cos_a: float, sin_a: float,
               dx: float, dy: float) -> None:
        """A recording rotated by (cos_a, sin_a) and moved by (dx, dy), owned
        by the entity being drawn -- one block reference, without ezdxf."""
        handle = self._handle
        for key, template, lines, triangles, points in recording:
            bucket = self.buckets.get(key)
            if bucket is None:
                bucket = self.buckets[key] = Bucket(
                    template.layer, template.color, template.lineweight,
                    template.kind, group=template.group)
            for xy, coords, owners, per in (
                    (lines, bucket.lines, bucket.lines_owner, 2),
                    (triangles, bucket.triangles, bucket.triangles_owner, 3),
                    (points, bucket.points, bucket.points_owner, 1)):
                if not len(xy):
                    continue
                x, y = xy[:, 0], xy[:, 1]
                moved = np.empty_like(xy)
                moved[:, 0] = x * cos_a - y * sin_a + dx
                moved[:, 1] = x * sin_a + y * cos_a + dy
                coords.extend(moved.ravel().tolist())
                owners.extend([handle] * (len(xy) // per))
            bucket.text_height_sum += template.text_height_sum
            bucket.text_count += template.text_count


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


def _ring_box(ring: list[Vec2]) -> tuple[float, float, float, float]:
    """(min_x, min_y, max_x, max_y) of a flattened ring, in one pass."""
    xs = [v.x for v in ring]
    ys = [v.y for v in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _box_extent(box) -> float:
    return (box[2] - box[0]) * (box[3] - box[1])


def _ring_extent(ring: list[Vec2]) -> float:
    return _box_extent(_ring_box(ring))


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
    msp = document.doc.modelspace()
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
    keeps -- or does not describe this layout at all: a block definition is
    not the drawing. The caller then pays for the walk.
    """
    doc = getattr(layout, "doc", None)
    if doc is None or getattr(layout, "is_block_layout", False):
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


#: AutoCAD's VIEWRES (p. 2049) -- "the greater the number of vectors, the
#: smoother the appearance of the circle or arc". Its own default is 1000,
#: and its own warning is that raising it may slow the regen down.
VIEWRES_DEFAULT = 1000
VIEWRES_MIN = 1
VIEWRES_MAX = 20000
SETTING_VIEWRES = "display/viewres"


def viewres() -> int:
    """The current VIEWRES, from Options > Display or the VIEWRES command."""
    from core.prefs import int_pref

    return int_pref(SETTING_VIEWRES, VIEWRES_DEFAULT, VIEWRES_MIN, VIEWRES_MAX)


def curve_quality() -> float:
    """Multiplier on the flattening tolerance, derived from VIEWRES.

    Higher VIEWRES = smaller tolerance = finer curves. Measured on two real
    plans, going four times finer costs +0.6% vertices and no measurable
    regen time, because a civil drawing is overwhelmingly straight lines --
    but a drawing that IS mostly curves would pay, which is why AutoCAD
    warns about it too and why it stays a setting rather than a new default.
    """
    return max(0.05, min(20.0, VIEWRES_DEFAULT / float(viewres())))


def _flatten_distance(layout) -> float:
    diagonal = _header_diagonal(layout)
    if diagonal is None:
        extents = _layout_extents(layout)
        if not extents.has_data:
            return 0.01
        dx = extents.extmax.x - extents.extmin.x
        dy = extents.extmax.y - extents.extmin.y
        diagonal = math.hypot(dx, dy)
    return max(diagonal * FLATTEN_REL * curve_quality(), MIN_FLATTEN)


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

    def set_current_layout(self, layout, ctb: str = ""):
        super().set_current_layout(layout, ctb)
        if layout.name == "Model":
            # The user's canvas colour, where ezdxf resolves against it:
            # ACI 7 flips to black over a light background, and the text
            # background masks fill with the canvas colour. Both come from
            # current_layout_properties, so a white model canvas is wrong
            # everywhere unless the choice lands HERE. Sheets keep ezdxf's
            # paper-white properties: their viewports already resolve
            # against paper.
            from core import window_colors

            self.current_layout_properties.set_colors(
                window_colors.background("model"))

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


#: How much bigger than the viewport's own rectangle the cull window is. A
#: lineweight is drawn in paper millimetres, so geometry whose centreline sits
#: just outside can still bleed in; 5% of the view is far more than any
#: lineweight and costs almost nothing when 94% is being skipped.
VIEWPORT_CULL_MARGIN = 0.05


def _viewport_model_rect(vp) -> Optional[tuple[float, float, float, float]]:
    """The model rectangle a VIEWPORT shows, grown by a safety margin.

    Returns None -- meaning "cull nothing" -- for anything this cannot state
    conservatively: a missing or degenerate view, or a non-finite number.
    A twisted viewport gets the rectangle that circumscribes its rotated
    view, which is larger than what it shows and therefore still safe.
    """
    from core.layouts import view_centre_wcs

    try:
        height = float(vp.dxf.view_height)
        width_paper = float(vp.dxf.width)
        height_paper = float(vp.dxf.height)
        # The WCS point at the viewport's centre -- NOT group 12/22 raw,
        # which is relative to the view target and turned by the twist: a
        # viewport with a UTM target read raw put the rectangle near the
        # origin and culled the whole model, so the sheet drew it EMPTY
        # (Plaza Yanque's Layout1, Marco 2026-09-27; v0.6.4 too).
        cx, cy = view_centre_wcs(vp)
    except Exception:
        return None
    if not (math.isfinite(height) and height > 0.0):
        return None
    if not (math.isfinite(cx) and math.isfinite(cy)):
        return None
    aspect = (width_paper / height_paper
              if height_paper > 0.0 and math.isfinite(width_paper) else 1.0)
    if not (math.isfinite(aspect) and aspect > 0.0):
        aspect = 1.0
    width = height * aspect
    try:
        twist = float(vp.dxf.get("view_twist_angle", 0.0) or 0.0)
    except Exception:
        twist = 0.0
    if twist:
        # circumscribe the rotated view: never smaller than what is shown
        angle = math.radians(twist)
        cos_a, sin_a = abs(math.cos(angle)), abs(math.sin(angle))
        width, height = (width * cos_a + height * sin_a,
                         width * sin_a + height * cos_a)
    margin_x = width * VIEWPORT_CULL_MARGIN
    margin_y = height * VIEWPORT_CULL_MARGIN
    return (cx - width / 2 - margin_x, cy - height / 2 - margin_y,
            cx + width / 2 + margin_x, cy + height / 2 + margin_y)


def _rect_covers_model(rect, vp) -> bool:
    """True when ``rect`` already contains the whole drawing.

    Read from the header, so it costs nothing. Unknown or unusable extents
    answer False: culling then proceeds, which is never wrong, only slower.
    """
    doc = getattr(vp, "doc", None)
    if doc is None:
        return False
    try:
        lo, hi = doc.header["$EXTMIN"], doc.header["$EXTMAX"]
        x0, y0 = float(lo[0]), float(lo[1])
        x1, y1 = float(hi[0]), float(hi[1])
    except Exception:
        return False
    if not all(math.isfinite(v) for v in (x0, y0, x1, y1)):
        return False
    if x1 < x0 or y1 < y0 or (x1 - x0) > 1e15:
        return False        # the sentinel of a never-regenerated drawing
    return (rect[0] <= x0 and rect[1] <= y0
            and rect[2] >= x1 and rect[3] >= y1)


_DIMENSION_TYPES = frozenset(("DIMENSION", "ARC_DIMENSION"))


#: not inside a layout pass (see TolerantFrontend._anno_scale)
_UNSET = object()


_UNSEEN = object()


def viewport_ltscale_factor(vp) -> float:
    """What a viewport multiplies the drawing's linetype scale by so its
    dashes come out on the sheet the way AutoCAD draws them.

    AutoCAD: with PSLTSCALE=1 (the default, the Linetype Manager's "Use
    paper space units for scaling") a dash measures pattern x LTSCALE ON
    PAPER in every viewport, whatever its scale; with 0 it measures that in
    model units, so pattern x LTSCALE x scale on paper.

    ezdxf applies the pattern to the geometry already in PAPER coordinates
    (its linetype stage runs after the viewport's transform and clip) and
    then multiplies it by 1/scale -- so a 1:2 viewport drew dashes twice too
    long on the sheet and a 1:50 one fifty times. The factor returned here
    is applied on top of that to land on AutoCAD's result: ``scale`` for
    PSLTSCALE=1, ``scale**2`` for 0, 1.0 when the scale is unknown.
    """
    doc = getattr(vp, "doc", None)
    if doc is None:
        return 1.0
    try:
        scale = float(vp.get_scale())
        paper_units = int(doc.header.get("$PSLTSCALE", 1))
    except Exception:                       # noqa: BLE001 - leave it as is
        return 1.0
    if not (scale > 0.0) or scale != scale:
        return 1.0
    scale = max(scale, 0.0001)              # ezdxf's own 1:10000 clamp
    return scale if paper_units else scale * scale


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
        #: Model rectangle the viewport currently being drawn shows, or None
        #: outside a viewport pass. See :meth:`draw_viewport`.
        self._vp_rect: Optional[tuple[float, float, float, float]] = None
        #: entity id -> model bounding box, computed once for the whole build
        self._vp_boxes: dict[int, Optional[tuple]] = {}
        # MULTILEADER: draw the real content, never the baked proxy picture
        # (white-box masks). See draw_mleader_entity.
        self._dispatch["MULTILEADER"] = self.draw_mleader_entity
        self._dispatch["MLEADER"] = self.draw_mleader_entity
        # ATTDISP ($ATTMODE): OFF hides every attribute, ON shows the
        # Invisible ones too; ezdxf alone only knows the entity's own flag.
        self._attmode = 1
        self.push_property_override_function(self._attmode_override)

    def _attmode_override(self, entity, properties) -> None:
        if entity.dxftype() in ("ATTRIB", "ATTDEF"):
            from core.attributes import attribute_visible

            properties.is_visible = attribute_visible(entity, self._attmode)

    def _draw_constant_attdefs(self, insert, properties) -> None:
        """A Constant attribute has no ATTRIB: the reference shows the
        definition itself, placed by the reference's matrix (AutoCAD). ezdxf
        skips ATTDEFs when it explodes a block, so they are drawn here, owned
        by the reference like its attributes."""
        if insert.dxftype() != "INSERT":
            return
        block = insert.block()
        if block is None:
            return
        consts = [a for a in block.attdefs() if a.is_const]
        if not consts:
            return
        try:
            from ezdxf.entities.attrib import copy_attrib_as_text

            matrix = insert.matrix44()
            copies = []
            for attdef in consts:
                # as TEXT: ezdxf draws an ATTDEF with its TAG (what a block
                # definition shows), the reference shows the VALUE
                copy = copy_attrib_as_text(attdef)
                copy.transform(matrix)
                copies.append(copy)
        except Exception as exc:              # noqa: BLE001 - a bad matrix
            logger.warning("constant attributes of #%s: %s",
                           insert.dxf.get("handle", "?"), exc)
            return
        self.ctx.push_state(properties)
        try:
            self.draw_entities(copies)
        finally:
            self.ctx.pop_state()

    #: Handles hidden by ISOLATEOBJECTS/HIDEOBJECTS. Display only: the
    #: entity stays in the document, it is simply not drawn.
    hidden_handles: frozenset = frozenset()

    #: A parallel sheet build (render.parallel): the model entities this
    #: worker draws in every viewport, or None to draw them all ...
    _model_share: Optional[frozenset] = None
    #: ... and whether it also draws the sheet's own entities (one worker does)
    _draws_paper: bool = True
    #: Inside a viewport pass -- drawing the model through a viewport
    _in_viewport: bool = False

    #: Annotation scale of the space being drawn (core.annotative): model
    #: space's CANNOSCALE, a viewport's own scale, or None on the sheet
    #: itself. _UNSET outside a layout pass (overlays): the entity's space
    #: decides.
    _anno_scale = _UNSET
    #: ANNOALLVISIBLE of that space
    _anno_show_all: bool = True
    #: ANNOALLVISIBLE of the sheet whose viewports are being drawn
    _anno_sheet_show_all: bool = True

    def draw_layout(self, layout, *args, **kwargs):
        """Draw a space at its annotation scale (see core.annotative)."""
        from core import annotative

        saved = (self._anno_scale, self._anno_show_all,
                 self._anno_sheet_show_all)
        from core.attributes import attmode

        self._attmode = attmode(layout.doc)
        if layout.is_modelspace:
            self._anno_scale = annotative.current_scale(layout.doc)
            self._anno_show_all = annotative.all_visible(layout)
        else:
            # objects drawn on the sheet itself show at their own size
            self._anno_scale = None
            self._anno_sheet_show_all = annotative.all_visible(layout)
        try:
            return super().draw_layout(layout, *args, **kwargs)
        finally:
            (self._anno_scale, self._anno_show_all,
             self._anno_sheet_show_all) = saved

    def draw_viewport(self, vp) -> None:
        """Draw one viewport, skipping the model it does not show.

        A sheet redraws the whole model once per viewport: on a real plan
        with ten of them that was 4 264 ms of a 4 742 ms rebuild, every pass
        costing the same because nothing cached. Yet each viewport shows
        between 0.5% and 18% of the model -- **94% of that work was on
        entities no viewport displays**, fully processed and then clipped
        away.

        So each pass now skips entities whose bounding box misses the
        rectangle this viewport shows. Exact by construction: what falls
        outside the rectangle is what the clipper was going to discard. The
        rectangle is grown by a margin, the boxes are the conservative
        ``fast=True`` ones (a curve's control polygon contains the curve),
        an entity whose box cannot be computed is never skipped, and a
        twisted viewport gets the circumscribed rectangle -- every doubt
        resolves towards drawing.
        """
        previous = self._vp_rect
        rect = _viewport_model_rect(vp)
        if rect is not None and _rect_covers_model(rect, vp):
            # This viewport shows the whole drawing, so nothing can be
            # skipped -- and measuring every entity to learn that is pure
            # loss. A one-viewport sheet is exactly this case.
            rect = None
        self._vp_rect = rect
        from core import annotative

        saved = (self._anno_scale, self._anno_show_all)
        # A viewport's annotation scale is its own property, NOT its zoom
        # (they differ on 457 of 707 real viewports); without one it shows
        # annotations at model space's scale.
        self._anno_scale = (annotative.viewport_scale(vp)
                            or annotative.current_scale(vp.doc))
        self._anno_show_all = self._anno_sheet_show_all
        inside = self._in_viewport
        self._in_viewport = True
        # Linetypes in a viewport the way AutoCAD scales them (PSLTSCALE;
        # see viewport_ltscale_factor). The viewport's render context is
        # copied from this one, so set it here and put it back after.
        saved_ltscale = self.ctx.linetype_scale
        self.ctx.linetype_scale = saved_ltscale * viewport_ltscale_factor(vp)
        try:
            super().draw_viewport(vp)
        finally:
            self._vp_rect = previous
            self._anno_scale, self._anno_show_all = saved
            self._in_viewport = inside
            self.ctx.linetype_scale = saved_ltscale

    def _skip_share_check(self, entity) -> bool:
        """Only a drawing's own top-level entities are shared out: the
        content of a block, a dimension or a leader is drawn by whoever
        draws its owner (virtual copies carry no handle). An entity that
        cannot even say its handle counts as one: it is drawn."""
        try:
            return not entity.dxf.handle
        except Exception:                     # noqa: BLE001 - draw it
            return True

    def _outside_viewport(self, entity) -> bool:
        rect = self._vp_rect
        if rect is None:
            return False
        if self._skip_share_check(entity):
            # A virtual copy -- the content of a block -- is never culled:
            # its owner was measured already, and the box cache is keyed by
            # id(), which Python hands to the NEXT temporary copy once this
            # one is freed. A later copy then inherited a stranger's box and
            # vanished from the sheet at random (a window block drew 8 of
            # its 28 line vertices in 1 regen out of 5).
            return False
        key = id(entity)
        box = self._vp_boxes.get(key, False)
        if box is False:
            try:
                found = bbox.extents([entity], fast=True)
                box = ((found.extmin.x, found.extmin.y,
                        found.extmax.x, found.extmax.y)
                       if found.has_data else None)
            except Exception:
                box = None
            self._vp_boxes[key] = box
        if box is None:
            return False        # unmeasurable: always draw
        x0, y0, x1, y1 = rect
        return box[2] < x0 or box[0] > x1 or box[3] < y0 or box[1] > y1

    #: The host Document, when the caller has one: xref paths resolve
    #: against its folder and its UNLOADed names are honoured.
    _host_document = None
    #: id(referenced drawing) -> its own RenderContext (layers, styles)
    _xref_contexts: Optional[dict] = None

    def _draw_xref(self, insert, properties) -> None:
        """An INSERT of an external reference draws the referenced
        drawing's modelspace, placed by the insert (core.xrefs, #33). The
        block is empty in this file, so ezdxf would draw nothing.

        Each referenced entity resolves its properties in ITS drawing's
        context (layers, linetypes, ByBlock through the insert), on the
        canvas of the space being drawn (paper white or the model's dark),
        and the host's ``xref|layer`` layer can still switch it off, as
        AutoCAD lets a host freeze an xref's layer.
        """
        from core import xrefs

        host = self._host_document
        if host is None:
            host = getattr(insert.doc, "_ingecad_document", None)
        if host is None:
            return
        xdoc = xrefs.referenced_for_insert(host, insert)
        if xdoc is None:
            return                          # unloaded or not found: nothing
        if self._xref_contexts is None:
            self._xref_contexts = {}
        ctx = self._xref_contexts.get(id(xdoc))
        if ctx is None:
            ctx = TolerantRenderContext(xdoc.doc)
            self._xref_contexts[id(xdoc)] = ctx
        # the referenced entities land on THIS canvas
        ctx.current_layout_properties = self.ctx.current_layout_properties
        host_layers = self.ctx.layers
        prefix = insert.dxf.name + "|"
        ctx.push_state(properties)
        try:
            for copy in xrefs.virtual_entities(insert, host):
                try:
                    host_layer = host_layers.get((prefix + copy.dxf.layer).lower())
                    if host_layer is not None and not host_layer.is_visible:
                        continue
                    props = ctx.resolve_all(copy)
                    if not props.is_visible:
                        continue
                    self.draw_entity(copy, props)
                except Exception as exc:      # noqa: BLE001 - one bad entity
                    self.skipped.append(
                        f"{copy.dxftype()} in xref {insert.dxf.name}: {exc}")
        finally:
            ctx.pop_state()

    def draw_mleader_entity(self, entity, properties) -> None:
        """Draw a MULTILEADER from its real content, not its proxy graphic.

        ezdxf lists MULTILEADER among the proxy-graphic-only entities, so
        whenever the entity carries a proxy graphic it replays the picture
        the SAVING program baked into the file. That picture hard-codes the
        text background mask in the saving machine's window colour — a white
        HATCH on every plan a colleague saved over a white canvas — and the
        label text in colours that white swallows. Marco's fence plan: every
        leader was a blank white box.

        The native render engine resolves the actual MTEXT instead, with the
        mask as ``bg_fill = 3`` (window colour), which the drawing add-on
        correctly declines to fill. The proxy graphic stays as the fallback
        for the day the engine cannot digest a broken leader.
        """
        from ezdxf.render import mleader as _mleader

        try:
            children = list(
                _mleader.virtual_entities(entity, proxy_graphic=False))
        except Exception as exc:
            logger.warning("MULTILEADER #%s native render failed (%s); "
                           "falling back to its proxy graphic",
                           getattr(entity.dxf, "handle", "?"), exc)
            children = []
        if not children:
            if entity.proxy_graphic:
                self.draw_proxy_graphic(entity.proxy_graphic, entity.doc)
            return
        self.draw_entities(children)

    def _annotation_scale_for(self, entity):
        scale = self._anno_scale
        if scale is not _UNSET:
            return scale
        # an overlay pass: model space objects show at CANNOSCALE
        from core import annotative

        doc = entity.doc
        try:
            in_model = entity.dxf.owner == doc.modelspace().block_record_handle
        except Exception:
            return None
        return annotative.current_scale(doc) if in_model else None

    #: Recordings of block content for this build, or None when block
    #: references are drawn one by one (see draw_composite_entity).
    _block_cache: Optional[dict] = None

    def draw_composite_entity(self, entity, properties) -> None:
        """A block reference drawn from a recording of its block (#29).

        ezdxf explodes a block again for every reference to it -- a door
        placed 80 times is tessellated 80 times. Within one build, the
        block's content is drawn ONCE at the origin, unrotated, with this
        reference's scale and resolved properties (ByBlock and layer-0
        content take the reference's colour and layer), and every
        reference that shares them replays it rotated and moved: the same
        primitives, owned by the reference, so picking and hiding work as
        before. Its attributes are drawn afterwards as ezdxf draws them.

        Only in a plain model build: a sheet clips through its viewports in
        ezdxf's pipeline, which a replay would bypass. MINSERT, a clipped
        reference, a tilted extrusion and a block holding an image go the
        usual way.
        """
        if entity.dxftype() == "INSERT":
            from core import xrefs

            if xrefs.is_xref_insert(entity):
                # an external reference: its content lives in another
                # file, not in a recording of this one (see _draw_xref)
                self._draw_xref(entity, properties)
                return
        cache = self._block_cache
        key = self._instance_key(entity, properties) if cache is not None else None
        if key is None:
            super().draw_composite_entity(entity, properties)
            self._draw_constant_attdefs(entity, properties)
            return
        backend = self.pipeline.backend
        recording = cache.get(key, _UNSEEN)
        if recording is _UNSEEN:
            recording = cache[key] = self._record_block(entity, properties, backend)
        if recording is None:
            super().draw_composite_entity(entity, properties)
            self._draw_constant_attdefs(entity, properties)
            return
        angle = math.radians(entity.dxf.get("rotation", 0.0))
        at = entity.dxf.insert
        backend.replay(recording, math.cos(angle), math.sin(angle), at.x, at.y)
        if entity.attribs:
            self.ctx.push_state(properties)
            try:
                self.draw_entities(entity.attribs)
            finally:
                self.ctx.pop_state()
        self._draw_constant_attdefs(entity, properties)

    def _instance_key(self, entity, properties):
        """What a recording depends on, or None when this reference cannot
        be replayed."""
        if entity.dxftype() != "INSERT" or entity.mcount > 1:
            return None
        extrusion = entity.dxf.get("extrusion", None)
        if extrusion is not None and not (abs(extrusion[0]) < 1e-12
                                          and abs(extrusion[1]) < 1e-12
                                          and extrusion[2] > 0):
            return None
        if entity.has_extension_dict:
            from ezdxf import xclip

            clip = xclip.XClip(entity)
            if clip.has_clipping_path and clip.is_clipping_enabled:
                return None
        backend = self.pipeline.backend
        if not hasattr(backend, "replay"):
            return None
        props = tuple(sorted((k, tuple(v) if isinstance(v, (list, tuple)) else v)
                             for k, v in vars(properties).items()
                             if isinstance(v, (str, int, float, bool, list, tuple))))
        dxf = entity.dxf
        return (dxf.name, dxf.get("xscale", 1.0), dxf.get("yscale", 1.0),
                dxf.get("zscale", 1.0), props, backend._group, backend._kind,
                self._anno_scale, self._anno_show_all)

    def _record_block(self, entity, properties, backend):
        """Draw the block's content once, at the origin and unrotated."""
        proto = entity.copy()
        proto.dxf.insert = (0.0, 0.0, 0.0)
        proto.dxf.rotation = 0.0
        saved = backend.begin_capture()
        self.ctx.push_state(properties)
        try:
            self.draw_entities(
                proto.virtual_entities(skipped_entity_callback=self.skip_entity))
        except Exception as exc:              # noqa: BLE001 - draw it the usual way
            logger.warning("block %s not recorded: %s", entity.dxf.name, exc)
            backend.end_capture(saved)
            return None
        finally:
            self.ctx.pop_state()
        return backend.end_capture(saved)

    def draw_entity(self, entity, properties) -> None:
        share = self._model_share
        if share is not None and not self._skip_share_check(entity):
            if self._in_viewport:
                if entity.dxf.handle not in share:
                    return
            elif not self._draws_paper and entity.dxftype() != "VIEWPORT":
                return
        substituted = False
        if entity.dxf.hasattr("handle"):
            from core import annotative

            scale = self._annotation_scale_for(entity)
            if scale is not None:
                rep = annotative.representation_for(
                    entity, scale, self._anno_show_all)
                if rep is annotative.HIDDEN:
                    return
                if rep is not None:
                    try:
                        virtual = annotative.virtual_representation(
                            entity, rep)
                    except Exception as exc:
                        logger.warning("annotative #%s: %s",
                                       entity.dxf.handle, exc)
                        virtual = None
                    if virtual is not None:
                        entity, substituted = virtual, True
        # a substituted representation lies elsewhere than the box cached
        # for the object: never cull it
        if (not substituted and self._vp_rect is not None
                and self._outside_viewport(entity)):
            return
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
        # A dimension's *D block is a block reference in all but name:
        # AutoCAD resolves its ByBlock strokes (ISO-25's default for lines,
        # arrows and text) and its layer-0 content against the DIMENSION
        # itself, which is how a dimension moved to a red layer turns red.
        # ezdxf pushes that context for INSERT only; without it every
        # ByBlock stroke resolved to the canvas default -- white on any
        # layer, whatever the dimension's own colour said.
        as_block = entity.dxftype() in _DIMENSION_TYPES
        if as_block:
            self.ctx.push_state(properties)
        try:
            super().draw_entity(entity, properties)
        except Exception as exc:
            handle = getattr(entity.dxf, "handle", None) or "?"
            note = f"{entity.dxftype()}(#{handle}): {exc}"
            self.skipped.append(note)
            logger.warning("skipped unrenderable entity %s", note)
            while backend is not None and len(backend._open) > depth:
                backend.exit_entity(entity)
        finally:
            if as_block:
                self.ctx.pop_state()


def point_size(document) -> Optional[float]:
    """The size POINT symbols are drawn at, in drawing units; None leaves
    ezdxf to read a positive $PDSIZE itself.

    $PDSIZE 0 or negative is AutoCAD's size relative to the screen: 0 is 5 %
    of the view height, -N is N %. ezdxf cannot do it (it falls back to 1
    unit, #69: points all but invisible). As in AutoCAD the view is the one
    of the last regeneration: the window hands its height over as
    ``document.point_view_height`` before each regen.
    """
    if document is None:
        return None
    try:
        value = float(document.doc.header.get("$PDSIZE", 0.0))
    except (TypeError, ValueError):
        value = 0.0
    if value > 0:
        return None
    height = getattr(document, "point_view_height", None)
    if not height or height <= 0:
        # no view yet (the regen of an opening file): the saved one
        try:
            height = float(document.doc.viewports.get("*Active")[0].dxf.height)
        except Exception:                  # noqa: BLE001 - no saved view
            return None
        if not height > 0:
            return None
    percent = 5.0 if value == 0 else -value
    return height * percent / 100.0


def min_dash_length(tolerance: float, document=None) -> float:
    """ezdxf's shortest dash, in its own terms (it multiplies by $LTSCALE).

    ezdxf stretches every dash, gap and dot to 0.1 drawing units: in a
    drawing in metres that is 10 cm, so HIDDEN and DASHDOT at the small
    linetype scale such a drawing needs came out identical and dotless, on
    screen and in the PDF (a YouTuber's staircase plan, drawn in metres).
    The floor follows the drawing's own tolerance instead -- never coarser
    than ezdxf's 0.1, so a big plan in millimetres draws as before."""
    ltscale = 1.0
    if document is not None:
        try:
            ltscale = float(document.doc.header.get("$LTSCALE", 1.0)) or 1.0
        except Exception:  # noqa: BLE001 -- a broken header: plain 1
            ltscale = 1.0
    return min(max(tolerance, 1e-9) / abs(ltscale), 0.1)


def construction_length(flatten: float) -> float:
    """What ezdxf draws an XLINE (and a RAY) as: CONSTRUCTION_SPAN drawing
    diagonals, read back from the flattening tolerance the regen derived
    from that diagonal. ezdxf's own 20 units made them look like short
    lines (#98: "se ven de tamaño finito"); far longer would cost float32
    precision near the drawing and dashes by the million on a dashed axis."""
    return max(flatten / FLATTEN_REL * CONSTRUCTION_SPAN, 20.0)


def frontend_config(flatten: float, document=None) -> Configuration:
    config = Configuration(
        max_flattening_distance=flatten,
        min_hatch_line_distance=flatten * HATCH_DENSITY_REL,
        hatching_timeout=HATCHING_TIMEOUT,
        min_dash_length=min_dash_length(flatten, document),
        infinite_line_length=construction_length(flatten),
    )
    size = point_size(document)
    return config if size is None else config.with_changes(pdsize=size)


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


def build_scene_for_entities(document: Document, entities, flatten: float,
                             canvas=None) -> Scene:
    """Pack just ``entities`` (freshly drawn ones) into a small overlay scene.

    Drawing must feel instant on any file size: instead of a full regen per
    added entity, the viewport draws this overlay on top of the base scene
    and merges on the next real regen. ``flatten`` comes from the base scene
    build so curve quality matches.

    ``canvas`` is the space whose canvas the overlay lands on, when that is
    not the space being edited: inside a viewport (MSPACE) the entities are
    the MODEL's but they are drawn on the white sheet, and an ACI 7 line
    resolved against the model's dark background would be white on white.
    """
    from core.isolate import hidden_handles

    # The overlay never draws raster quads (pack() below is not handed the
    # images), so loading their pixels here was pure waste — and during a
    # live image grip drag this runs per mouse move, which on a scanned
    # sheet re-read 36 MB from disk 30 times per second.
    backend = _CornersOnlyBackend(flatten)
    context = TolerantRenderContext(document.doc)
    _apply_space_colors(context, document, canvas)
    frontend = TolerantFrontend(context, backend, frontend_config(flatten, document))
    frontend._host_document = document       # xref paths resolve from here
    frontend.hidden_handles = frozenset(hidden_handles(document))
    frontend.draw_entities(entities)
    return pack(backend.buckets, _declared_extents(document))


def _apply_space_colors(context, document, canvas=None) -> None:
    """Resolve colours against the canvas the overlay will land on.

    ``draw_entities`` never calls ``set_current_layout``, so the context
    keeps ezdxf's dark modelspace defaults — and on a white sheet that
    paints a freshly drawn ACI 7 line **white on white**. The overlay must
    answer the same question the base scene answered: which space is this?

    Which is why ``canvas`` exists: inside a viewport the space being edited
    (the model) and the canvas it is drawn on (the sheet) are not the same
    one, and it is the CANVAS that decides the colour.
    """
    from core import window_colors

    space = canvas if canvas is not None else document.current_space()
    try:
        if getattr(space, "is_any_paperspace", False):
            context.set_current_layout(space)      # ezdxf's paper white
        elif getattr(document, "edit_block", None):
            context.current_layout_properties.set_colors(
                window_colors.background("block_editor"))
        else:
            context.current_layout_properties.set_colors(
                window_colors.background("model"))
    except Exception:
        pass    # a colour is never worth losing the overlay over


class _CornersOnlyBackend(VertexBackend):
    """VertexBackend that captures the image quad without keeping pixels."""

    def draw_image(self, image_data, properties) -> None:
        corners = _image_quad_corners(image_data)
        if corners is not None:
            self.images.append({"corners": corners,
                                "handle": self._handle,
                                "group": self._group})


def image_corners_wcs(entity, pixel_size) -> Optional[list]:
    """The 4 WCS corners a regen would give this IMAGE, without the regen.

    Pure math over the entity's own transform — the drawing add-on builds
    its quad from ``image.get_wcs_transform()`` over the pixel rectangle,
    which is exactly what this computes. The pixels are never touched, and
    neither is the frontend: profiling showed ``draw_image_entity`` loads
    and converts the file with PIL before any backend runs, which put a
    36 MB decode inside every mouse move of a live image drag.

    ``pixel_size`` is (width, height) of the ACTUAL loaded raster — the
    caller has it in the scene's quad — because the file's real size wins
    over the declared one in the full build too.
    """
    w, h = pixel_size
    if not w or not h:
        return None
    try:
        m = entity.get_wcs_transform()
    except Exception:
        return None
    return [(c.x, c.y) for c in
            (m.transform((x, y, 0.0))
             for (x, y) in ((0.0, 0.0), (w, 0.0), (w, h), (0.0, h)))]


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


def build_scene(document: Document, layout_name: str | None = None, *,
                canvas=None) -> Scene:
    """Run the ezdxf frontend over the drawing and pack the result ("regen").

    ``layout_name`` selects a tab explicitly: "Model" renders modelspace with
    no fallback (the user clicked that tab — an empty canvas is the truth),
    any other name renders that paperspace layout, and None lets
    :func:`pick_layout` choose (file open: saved tab / empty-model fallback).

    ``canvas`` is a paperspace layout when the MODEL is being tessellated to
    be shown through that sheet's viewports (live navigation): colours then
    resolve against the paper, as they do in the sheet's own bake. Without
    it the model resolves against the dark model canvas and every ACI 7
    entity comes out white -- invisible on the white sheet, which on a
    plan drawn all in "color 7" is the whole drawing vanishing the moment
    a pan starts inside a viewport.
    """
    if getattr(document, "edit_block", None) and layout_name in (None, "Model"):
        return _build_block_scene(document)
    if layout_name == "Model":
        layout, layout_name = document.doc.modelspace(), None
    elif layout_name and layout_name in document.doc.layouts:
        layout = document.doc.layouts.get(layout_name)
    else:
        layout, layout_name = pick_layout(document)
    flatten = _flatten_distance(layout)
    from core.draworder import order_groups

    from core.isolate import hidden_handles

    groups = order_groups(layout)
    hidden = frozenset(hidden_handles(document))
    # external references: read the referenced drawings NOW, in this
    # process, so forked workers inherit them instead of each reading the
    # files (core.xrefs, #33)
    from core import xrefs as _xrefs

    _xrefs.preload(document)
    # block references replay a recording of their block: the model only
    # (through a sheet's viewports too: the recording keys on the resolved
    # colours, which then are the paper's)
    instancing = (layout_name is None and layout.is_modelspace
                  and os.environ.get("INGECAD_NO_INSTANCING", "") not in ("1", "true"))

    def make_frontend():
        # one recipe for the serial regen and for each parallel worker
        backend = VertexBackend(flatten, groups)
        context = TolerantRenderContext(document.doc)
        frontend = TolerantFrontend(context, backend, frontend_config(flatten, document))
        frontend._host_document = document   # xref paths resolve from here
        frontend.hidden_handles = hidden
        if instancing:
            frontend._block_cache = {}
        return frontend, backend

    parallel = None
    if layout_name is None and layout.is_modelspace:
        from render import parallel as _parallel

        properties = None
        if canvas is not None:
            from ezdxf.addons.drawing.properties import LayoutProperties

            properties = LayoutProperties.from_layout(canvas)
        parallel = _parallel.draw_parallel(make_frontend, layout,
                                           layout_properties=properties)
    elif layout_name is not None:
        from render import parallel as _parallel

        parallel = _parallel.draw_sheet_parallel(make_frontend, layout)
    if parallel is not None:
        backend, skipped = parallel
        if layout_name is not None:
            # the context the serial draw leaves behind: the sheet current,
            # so a border in colour 7 resolves against the paper
            context = TolerantRenderContext(document.doc)
            context.set_current_layout(layout)
            _draw_viewport_borders(layout, context, backend)
    else:
        frontend, backend = make_frontend()
        if canvas is not None and layout_name is None:
            from ezdxf.addons.drawing.properties import LayoutProperties

            # what ezdxf's own draw_viewport does for the model inside a sheet
            frontend.draw_layout(
                layout, layout_properties=LayoutProperties.from_layout(canvas))
        else:
            frontend.draw_layout(layout)
        if layout_name is not None:
            _draw_viewport_borders(layout, frontend.ctx, backend)
        skipped = frontend.skipped
    scene = pack(backend.buckets, _declared_extents(document),
                 images=backend.images)
    scene.skipped = list(skipped)
    scene.layout_name = layout_name
    scene.flatten = flatten
    if layout_name is None:
        from core import window_colors

        scene.background = window_colors.rgba("model")
    if layout_name is not None:
        # Layout tab look: gray desk around a white paper sheet (the viewport
        # draws the sheet itself from scene.paper). Entity colors were already
        # resolved by ezdxf against a white background, so ACI 7 reads black.
        from core.layouts import paper_frame

        from core import window_colors

        scene.background = window_colors.rgba("sheet")
        try:
            scene.paper = paper_frame(layout)
        except Exception:
            scene.paper = None   # a broken page setup must not blank the tab
    return scene


def _build_block_scene(document: Document) -> Scene:
    """The Block Editor's canvas: the definition alone, base point at origin.

    ``document.modelspace()`` already answers with the block's layout during
    a session, so this differs from a model regen in only three honest ways:
    the flattening tolerance comes from the block's own extents (the header
    describes the drawing, not the block), the declared extents are not used
    for the same reason, and the background says "you are in the editor".
    The axes icon the viewport always draws marks the base point for free,
    because a definition's base point IS its origin.
    """
    from core.draworder import order_groups
    from core.isolate import hidden_handles

    block = document.modelspace()
    flatten = _flatten_distance(block)     # its own extents, never the header
    from core import window_colors

    backend = VertexBackend(flatten, order_groups(block))
    context = TolerantRenderContext(document.doc)
    # draw_entities never calls set_current_layout, so the editor's canvas
    # colour is applied to the resolution properties directly — same reason
    # as the Model override above (ACI 7 flip, text masks).
    context.current_layout_properties.set_colors(
        window_colors.background("block_editor"))
    frontend = TolerantFrontend(context, backend, frontend_config(flatten, document))
    frontend.hidden_handles = frozenset(hidden_handles(document))
    frontend.draw_entities(block)
    scene = pack(backend.buckets, None, images=backend.images)
    scene.skipped = list(frontend.skipped)
    scene.flatten = flatten
    scene.background = window_colors.rgba("block_editor")
    return scene
