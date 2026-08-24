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


# The canvas colours (model dark, the gray "desk" around the paper sheet,
# the Block Editor's warm tone) live in core.window_colors now — the user
# picks them in the Drawing Window Colors dialog, defaults unchanged.


# Entity types whose fills are text glyphs; they dominate label-heavy plans
# (a cadastre: 43 M of 49 M vertices) and the viewport hides them when they
# would be smaller than a few pixels.
_TEXT_TYPES = frozenset(("TEXT", "MTEXT", "ATTRIB", "ATTDEF"))


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


#: AutoCAD's VIEWRES (p. 2049) -- "the greater the number of vectors, the
#: smoother the appearance of the circle or arc". Its own default is 1000,
#: and its own warning is that raising it may slow the regen down.
VIEWRES_DEFAULT = 1000
VIEWRES_MIN = 1
VIEWRES_MAX = 20000
SETTING_VIEWRES = "display/viewres"


def viewres() -> int:
    """The current VIEWRES, from Options > Display or the VIEWRES command."""
    try:
        from PySide6.QtCore import QSettings

        value = int(QSettings().value(SETTING_VIEWRES, VIEWRES_DEFAULT))
    except (TypeError, ValueError, Exception):
        return VIEWRES_DEFAULT
    return value if VIEWRES_MIN <= value <= VIEWRES_MAX else VIEWRES_DEFAULT


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
        diagonal = (dx * dx + dy * dy) ** 0.5
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
    try:
        centre = vp.dxf.view_center_point
        height = float(vp.dxf.view_height)
        width_paper = float(vp.dxf.width)
        height_paper = float(vp.dxf.height)
        cx, cy = float(centre[0]), float(centre[1])
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

    #: Handles hidden by ISOLATEOBJECTS/HIDEOBJECTS. Display only: the
    #: entity stays in the document, it is simply not drawn.
    hidden_handles: frozenset = frozenset()

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
        try:
            super().draw_viewport(vp)
        finally:
            self._vp_rect = previous

    def _outside_viewport(self, entity) -> bool:
        rect = self._vp_rect
        if rect is None:
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

    def draw_entity(self, entity, properties) -> None:
        if self._vp_rect is not None and self._outside_viewport(entity):
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

    # The overlay never draws raster quads (pack() below is not handed the
    # images), so loading their pixels here was pure waste — and during a
    # live image grip drag this runs per mouse move, which on a scanned
    # sheet re-read 36 MB from disk 30 times per second.
    backend = _CornersOnlyBackend(flatten)
    context = TolerantRenderContext(document.doc)
    frontend = TolerantFrontend(context, backend, frontend_config(flatten))
    frontend.hidden_handles = frozenset(hidden_handles(document))
    frontend.draw_entities(entities)
    return pack(backend.buckets, _declared_extents(document))


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


def build_scene(document: Document, layout_name: str | None = None) -> Scene:
    """Run the ezdxf frontend over the drawing and pack the result ("regen").

    ``layout_name`` selects a tab explicitly: "Model" renders modelspace with
    no fallback (the user clicked that tab — an empty canvas is the truth),
    any other name renders that paperspace layout, and None lets
    :func:`pick_layout` choose (file open: saved tab / empty-model fallback).
    """
    if getattr(document, "edit_block", None) and layout_name in (None, "Model"):
        return _build_block_scene(document)
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
    extents = _layout_extents(block)
    if extents.has_data:
        dx = extents.extmax.x - extents.extmin.x
        dy = extents.extmax.y - extents.extmin.y
        flatten = max(math.hypot(dx, dy) * FLATTEN_REL * curve_quality(),
                      MIN_FLATTEN)
    else:
        flatten = 0.01                     # a brand-new, still-empty block
    from core import window_colors

    backend = VertexBackend(flatten, order_groups(block))
    context = TolerantRenderContext(document.doc)
    # draw_entities never calls set_current_layout, so the editor's canvas
    # colour is applied to the resolution properties directly — same reason
    # as the Model override above (ACI 7 flip, text masks).
    context.current_layout_properties.set_colors(
        window_colors.background("block_editor"))
    frontend = TolerantFrontend(context, backend, frontend_config(flatten))
    frontend.hidden_handles = frozenset(hidden_handles(document))
    frontend.draw_entities(block)
    scene = pack(backend.buckets, None, images=backend.images)
    scene.skipped = list(frontend.skipped)
    scene.flatten = flatten
    scene.background = window_colors.rgba("block_editor")
    return scene
