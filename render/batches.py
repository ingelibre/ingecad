# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""CPU-side scene data: primitive buckets packed into GPU-ready arrays.

Coordinates arrive in world units as float64 (UTM drawings live near
E=500 000 — architectural principle #3). ``pack`` subtracts the scene origin
(the drawing's center) *in float64* and only then casts to float32, so the
precision loss lands in coordinates that are small by construction. The
viewport adds the origin back when building its matrix.

Vertex formats (colors as normalized uint8 — half the memory of floats):
- standard: [x f32, y f32, rgba u8x4]                     -> 12 bytes
- thick:    [x f32, y f32, nx f32, ny f32, rgba u8x4]     -> 20 bytes

Primitives are reordered by a coarse spatial grid inside each (layer, color,
lineweight, kind) bucket, and draw ranges carry world bounds so the viewport
can cull to the visible rect and skip illegible text (a cadastre's 43 M
glyph vertices are 90 % of the scene but invisible below a few pixels).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

VERTEX_DTYPE = np.dtype([("pos", "<f4", 2), ("rgba", "u1", 4)])          # 12 B
THICK_DTYPE = np.dtype([("pos", "<f4", 2), ("normal", "<f4", 2),
                        ("rgba", "u1", 4)])                              # 20 B

# AutoCAD LWT displays weights up to 0.25 mm as one pixel; above that the
# line grows with the weight. Same split here: thin -> GL_LINES, thick ->
# screen-constant quads expanded in the shader.
THIN_MAX_MM = 0.25

# Spatial grid resolution per axis for view culling.
GRID_DIV = 16


def parse_color(color: str) -> tuple[float, float, float, float]:
    """``#rrggbb`` or ``#rrggbbaa`` (ezdxf backend format) -> RGBA floats."""
    h = color.lstrip("#")
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    a = int(h[6:8], 16) / 255.0 if len(h) >= 8 else 1.0
    return r, g, b, a


def _color_u8(color: str) -> np.ndarray:
    h = color.lstrip("#")
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    a = int(h[6:8], 16) if len(h) >= 8 else 255
    return np.array([r, g, b, a], dtype=np.uint8)


@dataclass
class Bucket:
    """Primitives of one (layer, color, lineweight, kind) group, float64."""

    layer: str
    color: str
    lineweight: float = 0.25                              # mm, resolved
    kind: str = ""                                        # "T" = text glyphs
    # DRAWORDER group: -1 sent to back, +1 brought to front, 0 default. The
    # packer sorts buckets by their dict key, and the backend puts this group
    # FIRST in that key, so back draws under everything and front over.
    group: int = 0
    lines: list[float] = field(default_factory=list)      # x,y per endpoint
    triangles: list[float] = field(default_factory=list)  # x,y per corner
    points: list[float] = field(default_factory=list)     # x,y per point
    # Owner handle per PRIMITIVE (one entry per line/triangle/point). Survives
    # the grid sort and lets pack() build a handle -> vertex-runs map so the
    # viewport can hide an edited entity instantly, without a regen (the
    # surgical-display building block).
    lines_owner: list = field(default_factory=list)
    triangles_owner: list = field(default_factory=list)
    points_owner: list = field(default_factory=list)
    text_height_sum: float = 0.0                          # glyph extents, world
    text_count: int = 0

    @property
    def avg_text_height(self) -> float:
        return self.text_height_sum / self.text_count if self.text_count else 0.0


@dataclass
class DrawRange:
    """A contiguous vertex run inside a packed array."""

    layer: str
    first: int  # vertex index (not byte index)
    count: int
    lineweight: float = 0.25  # mm; drives u_half_world for thick ranges


class Batch:
    """One primitive type packed: interleaved array + culling metadata."""

    def __init__(self, data: np.ndarray, ranges: list[DrawRange],
                 bounds: Optional[np.ndarray] = None,
                 is_text: Optional[np.ndarray] = None,
                 text_height: Optional[np.ndarray] = None) -> None:
        self.data = data                    # structured array
        self.ranges = ranges
        # Parallel arrays for vectorized culling (one row per range):
        n = len(ranges)
        self.firsts = np.fromiter((r.first for r in ranges), np.int64, n)
        self.counts = np.fromiter((r.count for r in ranges), np.int64, n)
        self.bounds = bounds                # (n, 4) world min_x,min_y,max_x,max_y
        self.is_text = is_text              # (n,) bool
        self.text_height = text_height      # (n,) avg glyph height, world units

    @property
    def vertex_count(self) -> int:
        return len(self.data)

    def positions(self) -> np.ndarray:
        """(N, 2) float32 view of the vertex positions (tests, picking)."""
        return self.data["pos"]

    def visible_runs(self, view_rect, px_per_unit: float,
                     min_text_px: float) -> list[tuple[int, int]]:
        """Merged (first, count) vertex runs to draw for this view."""
        if not len(self.ranges):
            return []
        if self.bounds is None:
            return [(0, self.vertex_count)]
        x0, y0, x1, y1 = view_rect
        vis = (
            (self.bounds[:, 0] <= x1) & (self.bounds[:, 2] >= x0)
            & (self.bounds[:, 1] <= y1) & (self.bounds[:, 3] >= y0)
        )
        if self.is_text is not None and min_text_px > 0.0:
            # A zero height means the metric was never fed for that range —
            # an MTEXT's background-mask quad arrives through a path that
            # carries no glyph height. Culling must act only where the
            # metric exists, or the mask vanishes at EVERY zoom while its
            # text draws.
            legible = ((self.text_height <= 0.0)
                       | (self.text_height * px_per_unit >= min_text_px))
            vis &= ~self.is_text | legible
        idx = np.nonzero(vis)[0]
        if len(idx) == 0:
            return []
        firsts = self.firsts[idx]
        counts = self.counts[idx]
        # Merge runs that are contiguous in the buffer into single draws.
        breaks = np.nonzero(firsts[1:] != firsts[:-1] + counts[:-1])[0] + 1
        starts = np.concatenate(([0], breaks))
        ends = np.concatenate((breaks, [len(idx)]))
        return [
            (int(firsts[s]), int(firsts[e - 1] + counts[e - 1] - firsts[s]))
        for s, e in zip(starts, ends)]


def _empty_batch(dtype=VERTEX_DTYPE) -> Batch:
    return Batch(np.empty(0, dtype=dtype), [])


@dataclass
class SceneImage:
    """One raster IMAGE: a textured quad, positioned like everything else
    (float64 corners minus the scene origin, stored float32)."""

    pixels: "np.ndarray"          # (H, W, 4) uint8 RGBA, row 0 = top
    corners: "np.ndarray"         # (4, 2) float32, origin-relative, CCW from
                                  # the image's top-left pixel corner
    handle: str | None = None
    group: int = 0                # DRAWORDER group, like Bucket.group


@dataclass
class Scene:
    """Everything the viewport needs to draw one document."""

    origin: tuple[float, float]                    # float64 world center
    extents: tuple[float, float, float, float]     # world min_x, min_y, max_x, max_y
    lines: Batch                                   # thin lines
    thick: Batch                                   # lineweight quads
    triangles: Batch
    points: Batch
    # Entities the tolerant frontend could not draw ("TYPE(#handle): why").
    skipped: list[str] = field(default_factory=list)
    # Paperspace layout shown instead of an empty modelspace, if any.
    layout_name: Optional[str] = None
    # Canvas color for that layout (RGBA floats); None = viewport default.
    background: Optional[tuple[float, float, float, float]] = None
    # Paper sheet of a paperspace layout, from core.layouts.paper_frame():
    # {"sheet": (x0, y0, x1, y1), "printable": (...) | None} in layout units.
    paper: Optional[dict] = None
    # Flattening distance used for the build (reused by overlay regens).
    flatten: float = 0.01
    # handle -> [(batch_name, first_vertex, count)] for surgical hiding.
    handle_ranges: dict = field(default_factory=dict)
    # Handles currently hidden (edited entities awaiting the next regen).
    hidden: set = field(default_factory=set)
    # Raster IMAGE entities, drawn as textured quads (under the vectors for
    # group <= 0, over them for group > 0 — the DRAWORDER split).
    images: list = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return (
            self.lines.vertex_count == 0
            and self.thick.vertex_count == 0
            and self.triangles.vertex_count == 0
            and self.points.vertex_count == 0
        )


def _grid_cells(prims_xy: np.ndarray, extents, verts_per_prim: int) -> np.ndarray:
    """Cell id per primitive from its first vertex (cheap, good enough)."""
    min_x, min_y, max_x, max_y = extents
    w = max(max_x - min_x, 1e-12)
    h = max(max_y - min_y, 1e-12)
    p0 = prims_xy[::verts_per_prim]
    cx = np.clip(((p0[:, 0] - min_x) / w * GRID_DIV).astype(np.int32), 0, GRID_DIV - 1)
    cy = np.clip(((p0[:, 1] - min_y) / h * GRID_DIV).astype(np.int32), 0, GRID_DIV - 1)
    return cy * GRID_DIV + cx


def _pack_standard(
    buckets: list[Bucket], attr: str, verts_per_prim: int,
    origin: tuple[float, float], extents,
    batch_name: str = "", handle_ranges: Optional[dict] = None,
) -> Batch:
    ox, oy = origin
    chunks: list[np.ndarray] = []
    ranges: list[DrawRange] = []
    bounds: list[np.ndarray] = []
    is_text: list[bool] = []
    text_h: list[float] = []
    first = 0
    for bucket in buckets:
        coords = getattr(bucket, attr)
        if not coords:
            continue
        if attr == "lines" and bucket.lineweight > THIN_MAX_MM:
            continue  # packed as quads by _pack_thick
        xy = np.asarray(coords, dtype=np.float64).reshape(-1, 2)
        n_prims = len(xy) // verts_per_prim
        # Spatial order inside the bucket, so cell ranges are contiguous.
        cells = _grid_cells(xy, extents, verts_per_prim)
        order = np.argsort(cells, kind="stable")
        xy = xy.reshape(n_prims, verts_per_prim, 2)[order]
        cells = cells[order]

        verts = np.empty(n_prims * verts_per_prim, dtype=VERTEX_DTYPE)
        flat = xy.reshape(-1, 2)
        verts["pos"][:, 0] = flat[:, 0] - ox  # float64 math, float32 store
        verts["pos"][:, 1] = flat[:, 1] - oy
        verts["rgba"] = _color_u8(bucket.color)
        chunks.append(verts)

        # Record which vertex runs belong to each entity handle (for the
        # viewport's surgical hide). Owners follow the same grid permutation.
        owners = getattr(bucket, attr + "_owner")
        if owners and handle_ranges is not None:
            owner_arr = np.asarray(owners, dtype=object)[order.tolist()]
            i = 0
            while i < n_prims:
                h = owner_arr[i]
                j = i
                while j < n_prims and owner_arr[j] == h:
                    j += 1
                if h is not None:
                    handle_ranges.setdefault(h, []).append(
                        (batch_name, first + i * verts_per_prim,
                         (j - i) * verts_per_prim))
                i = j

        # One range per occupied cell.
        cell_breaks = np.nonzero(cells[1:] != cells[:-1])[0] + 1
        starts = np.concatenate(([0], cell_breaks))
        ends = np.concatenate((cell_breaks, [n_prims]))
        for s, e in zip(starts, ends):
            block = xy[s:e].reshape(-1, 2)
            ranges.append(DrawRange(
                bucket.layer,
                first + s * verts_per_prim,
                (e - s) * verts_per_prim,
                bucket.lineweight,
            ))
            bounds.append(np.array([
                block[:, 0].min(), block[:, 1].min(),
                block[:, 0].max(), block[:, 1].max(),
            ]))
            is_text.append(bucket.kind == "T")
            text_h.append(bucket.avg_text_height)
        first += n_prims * verts_per_prim
    if not chunks:
        return _empty_batch()
    return Batch(
        np.concatenate(chunks),
        ranges,
        np.vstack(bounds),
        np.asarray(is_text, dtype=bool),
        np.asarray(text_h, dtype=np.float64),
    )


def _pack_thick(
    buckets: list[Bucket], origin: tuple[float, float], extents,
    batch_name: str = "", handle_ranges: Optional[dict] = None,
) -> Batch:
    """Thick line segments -> quads (2 triangles, 6 vertices) per segment.

    Each vertex stores the segment point plus a unit perpendicular; the
    shader expands it by the half lineweight in world units, so thickness
    stays constant in pixels at any zoom (AutoCAD LWT display).

    Records owner runs like :func:`_pack_standard` does. Skipping that was a
    real bug: this batch holds every entity whose lineweight is above
    ``THIN_MAX_MM``, and ``Viewport.hide_handles`` silently ignores a handle it
    cannot find, so erasing left thick strokes on screen until the next regen.
    """
    ox, oy = origin
    chunks: list[np.ndarray] = []
    ranges: list[DrawRange] = []
    bounds: list[np.ndarray] = []
    first = 0
    for bucket in buckets:
        if not bucket.lines or bucket.lineweight <= THIN_MAX_MM:
            continue
        seg = np.asarray(bucket.lines, dtype=np.float64).reshape(-1, 2, 2)
        d = seg[:, 1] - seg[:, 0]
        length = np.hypot(d[:, 0], d[:, 1])
        ok = length > 0.0
        # Owners are per segment, so they take the same two steps the geometry
        # takes: drop the zero-length ones, then the grid permutation.
        owners = bucket.lines_owner
        owner_arr = (np.asarray(owners, dtype=object)[ok]
                     if owners and handle_ranges is not None else None)
        seg, d, length = seg[ok], d[ok], length[ok]
        if len(seg) == 0:
            continue
        cells = _grid_cells(seg.reshape(-1, 2), extents, 2)
        order = np.argsort(cells, kind="stable")
        seg, d, length, cells = seg[order], d[order], length[order], cells[order]
        if owner_arr is not None:
            owner_arr = owner_arr[order]

        normal = np.column_stack((-d[:, 1], d[:, 0])) / length[:, None]
        p0 = seg[:, 0] - (ox, oy)
        p1 = seg[:, 1] - (ox, oy)
        n_seg = len(seg)
        verts = np.empty((n_seg, 6), dtype=THICK_DTYPE)
        # Triangle pair: (p0,+n) (p0,-n) (p1,+n) / (p1,+n) (p0,-n) (p1,-n)
        corners = ((p0, 1), (p0, -1), (p1, 1), (p1, 1), (p0, -1), (p1, -1))
        for i, (p, sign) in enumerate(corners):
            verts["pos"][:, i] = p
            verts["normal"][:, i] = normal * sign
        verts["rgba"] = _color_u8(bucket.color)
        chunks.append(verts.reshape(-1))

        # Six vertices per segment, so a run of k segments is 6k vertices.
        if owner_arr is not None:
            i = 0
            while i < n_seg:
                h = owner_arr[i]
                j = i
                while j < n_seg and owner_arr[j] == h:
                    j += 1
                if h is not None:
                    handle_ranges.setdefault(h, []).append(
                        (batch_name, first + i * 6, (j - i) * 6))
                i = j

        cell_breaks = np.nonzero(cells[1:] != cells[:-1])[0] + 1
        starts = np.concatenate(([0], cell_breaks))
        ends = np.concatenate((cell_breaks, [n_seg]))
        for s, e in zip(starts, ends):
            block = seg[s:e].reshape(-1, 2)
            ranges.append(DrawRange(
                bucket.layer, first + s * 6, (e - s) * 6, bucket.lineweight))
            bounds.append(np.array([
                block[:, 0].min(), block[:, 1].min(),
                block[:, 0].max(), block[:, 1].max(),
            ]))
        first += n_seg * 6
    if not chunks:
        return _empty_batch(THICK_DTYPE)
    return Batch(np.concatenate(chunks), ranges, np.vstack(bounds))


#: Coordinates at or beyond this magnitude cannot be geometry: AutoCAD writes
#: ±1e20 into $EXTMIN/$EXTMAX to mean "no extents recorded", and no physical
#: drawing reaches 1e15 (the Earth in micrometres is 4e13).
_COORD_LIMIT = 1e15

#: How far outside the drawing's own declared extents a vertex may still sit,
#: as a multiple of that box's span. Generous, because $EXTMIN/$EXTMAX can lag
#: behind the geometry — it only has to be tighter than the corruption.
_HINT_MARGIN = 1.0

#: Fraction of vertices the declared box must accept before we believe it.
_HINT_MIN_KEPT = 0.95


def _world_extents(
    buckets: list[Bucket],
    hint: Optional[tuple[float, float, float, float]] = None,
) -> tuple[float, float, float, float]:
    """World bounds, robust against corrupt coordinates.

    One bad vertex used to swallow the drawing. Two real cases:
    PTL-026-COFOPRI-01-OJAMOQ.dwg arrived with LAYOUT extents at 6.7e301 and
    polyline vertices at 8.9e21, PLANTA Y PERFIL SEDAPAR.dwg with vertices at
    7.6e19 and more around 1e9. Raw min/max framed a box astronomically wide,
    Zoom Extents fitted *that*, and thousands of entities collapsed below one
    pixel: a blank canvas holding a complete drawing.

    Neither a magnitude cut nor a statistical one is enough on its own. The
    corruption overlaps plausible values (1e5 in a UTM drawing), and clipping by
    how far a vertex sits from the bulk throws away legitimate far-off details.
    So the drawing's own ``$EXTMIN``/``$EXTMAX`` is the reference when it is
    usable — the CAD application recorded it, and on every real file checked here
    it matched ODA File Converter exactly. Without it, only the impossible
    magnitudes go.

    NaN and inf are always dropped; they poison min/max on contact.
    """
    lo_hi = None
    if hint is not None and all(np.isfinite(hint)):
        hx0, hy0, hx1, hy1 = hint
        if hx1 > hx0 and hy1 > hy0 and max(abs(hx1 - hx0), abs(hy1 - hy0)) < _COORD_LIMIT:
            mx = _HINT_MARGIN * (hx1 - hx0)
            my = _HINT_MARGIN * (hy1 - hy0)
            lo_hi = (hx0 - mx, hy0 - my, hx1 + mx, hy1 + my)

    for use_hint in (lo_hi is not None, False):
        min_x = min_y = np.inf
        max_x = max_y = -np.inf
        kept = total = 0
        for bucket in buckets:
            for coords in (bucket.lines, bucket.triangles, bucket.points):
                if not coords:
                    continue
                xy = np.asarray(coords, dtype=np.float64).reshape(-1, 2)
                keep = np.isfinite(xy).all(axis=1)
                if use_hint:
                    keep &= ((xy[:, 0] >= lo_hi[0]) & (xy[:, 0] <= lo_hi[2])
                             & (xy[:, 1] >= lo_hi[1]) & (xy[:, 1] <= lo_hi[3]))
                else:
                    keep &= (np.abs(xy) < _COORD_LIMIT).all(axis=1)
                total += len(xy)
                n = int(keep.sum())
                if not n:
                    continue
                kept += n
                good = xy[keep]
                min_x = min(min_x, good[:, 0].min())
                min_y = min(min_y, good[:, 1].min())
                max_x = max(max_x, good[:, 0].max())
                max_y = max(max_y, good[:, 1].max())
        # A declared box that rejects a real slice of the drawing is stale or
        # wrong, not a filter: distrust it and fall back to magnitude only.
        if not use_hint or (total and kept >= _HINT_MIN_KEPT * total):
            break

    if min_x > max_x:  # nothing drawable
        return (0.0, 0.0, 0.0, 0.0)
    return (float(min_x), float(min_y), float(max_x), float(max_y))


def pack(buckets: dict[tuple, Bucket],
         extents_hint: Optional[tuple[float, float, float, float]] = None,
         images: Optional[list] = None) -> Scene:
    """Pack backend buckets into a Scene, origin at the drawing's center.

    ``extents_hint`` is the drawing's declared ``$EXTMIN``/``$EXTMAX``, used to
    tell corrupt coordinates from far-off geometry. See :func:`_world_extents`.
    """
    # Stable order: by layer then color, so ranges group per layer for the
    # future visibility toggle. Within each DRAWORDER group: ordinary fills
    # first, then text background masks (kind "TM"), then glyphs (kind "T")
    # LAST. Batching by (layer, color) destroys the file's entity order, and
    # both halves of that order matter on a real sheet: the title block's
    # WIPEOUT (layer "0", paper white) sorted after the labels of layer
    # "-Textos" and erased them, and a leader label's own background mask
    # (white on a sheet) sorted after its black glyphs and erased itself.
    _KIND_RANK = {"": 0, "TM": 1, "T": 2}
    ordered = [buckets[k]
               for k in sorted(buckets,
                               key=lambda k: (k[0],
                                              _KIND_RANK.get(k[-1], 0),
                                              k[1:]))]
    extents = _world_extents(ordered, extents_hint)
    if images:
        # Image corners count as geometry: zoom extents must include them
        # even in a drawing that is nothing but the scanned sheet.
        xs = [c[0] for im in images for c in im["corners"]]
        ys = [c[1] for im in images for c in im["corners"]]
        if not ordered:
            extents = (min(xs), min(ys), max(xs), max(ys))
        else:
            extents = (min(extents[0], *xs), min(extents[1], *ys),
                       max(extents[2], *xs), max(extents[3], *ys))
    origin = ((extents[0] + extents[2]) / 2.0, (extents[1] + extents[3]) / 2.0)
    hr: dict = {}
    scene = Scene(
        origin=origin,
        extents=extents,
        lines=_pack_standard(ordered, "lines", 2, origin, extents, "lines", hr),
        thick=_pack_thick(ordered, origin, extents, "thick", hr),
        triangles=_pack_standard(ordered, "triangles", 3, origin, extents,
                                 "triangles", hr),
        points=_pack_standard(ordered, "points", 1, origin, extents, "points", hr),
    )
    scene.handle_ranges = hr
    for im in images or []:
        corners = np.asarray(im["corners"], dtype=np.float64)
        corners[:, 0] -= origin[0]
        corners[:, 1] -= origin[1]
        scene.images.append(SceneImage(
            pixels=im["pixels"], corners=corners.astype(np.float32),
            handle=im.get("handle"), group=im.get("group", 0)))
    return scene
