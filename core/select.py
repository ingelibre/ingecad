# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Entity selection: pick box, window (fully inside), crossing (touching).

A GeometryIndex extracts pickable geometry per entity into NumPy arrays
(the same lazy strategy as the snap engine). Exotic entity types fall back
to their bounding box, so everything on screen is selectable even when we
do not understand its exact shape.

Scale notes (a real 92k-entity cadastre = 1.35 M segment rows):
- Owners are interned to int32 ids (``_owners`` list + per-row ``*_oidx``
  arrays), so every ownership test is a vectorized ``np.isin`` instead of a
  Python loop over a million handle strings.
- A per-row segment bounds table prefilters pick() to the rows near the
  cursor; window()/crossing() are fully vectorized (Python only touches the
  handful of ambiguous rows).
- ``version`` bumps on every mutation so per-frame consumers (selection
  highlight, grips) can cache their derived geometry.
"""
from __future__ import annotations

import math
from typing import Iterable, Optional

import numpy as np

from ezdxf import bbox as ezbbox


class GeometryIndex:
    """Per-entity pick geometry over a Document's modelspace."""

    def __init__(self, document) -> None:
        self.document = document
        self._dirty = True
        self.version = 0
        self._owners: list[str] = []            # owner id -> handle
        self._owner_ids: dict[str, int] = {}    # handle -> owner id
        self._segs = np.empty((0, 4))
        self._seg_oidx = np.empty(0, dtype=np.int32)
        self._seg_bounds = np.empty((0, 4))     # min_x min_y max_x max_y
        # cx cy r arc_flag a0 a1 (radians, ccw, a1 > a0; full circle: 0..tau)
        self._circles = np.empty((0, 6))
        self._circle_oidx = np.empty(0, dtype=np.int32)
        self._boxes = np.empty((0, 4))          # min_x min_y max_x max_y
        self._box_oidx = np.empty(0, dtype=np.int32)

    def invalidate(self) -> None:
        self._dirty = True
        self.version += 1

    def entity(self, handle: str):
        return self.document.doc.entitydb.get(handle)

    # -- owner interning -------------------------------------------------------
    def _intern(self, handle: str) -> int:
        oid = self._owner_ids.get(handle)
        if oid is None:
            oid = len(self._owners)
            self._owners.append(handle)
            self._owner_ids[handle] = oid
        return oid

    def _ids_of(self, handles) -> np.ndarray:
        ids = [self._owner_ids[h] for h in handles if h in self._owner_ids]
        return np.asarray(ids, dtype=np.int32)

    # -- extraction -------------------------------------------------------------
    @staticmethod
    def _extract(e, oid, segs, seg_o, circles, circle_o, boxes, box_o) -> None:
        t = e.dxftype()
        try:
            if t == "LINE":
                s, w = e.dxf.start, e.dxf.end
                segs.append((s.x, s.y, w.x, w.y))
                seg_o.append(oid)
            elif t == "LWPOLYLINE":
                pts = e.get_points("xy")
                pairs = list(zip(pts, pts[1:]))
                if e.closed and len(pts) > 2:
                    pairs.append((pts[-1], pts[0]))
                for a, b in pairs:
                    segs.append((a[0], a[1], b[0], b[1]))
                    seg_o.append(oid)
            elif t == "CIRCLE":
                c = e.dxf.center
                circles.append((c.x, c.y, e.dxf.radius, 0.0, 0.0, math.tau))
                circle_o.append(oid)
            elif t == "ARC":
                c = e.dxf.center
                a0 = math.radians(e.dxf.start_angle) % math.tau
                a1 = math.radians(e.dxf.end_angle) % math.tau
                if a1 <= a0:
                    a1 += math.tau
                circles.append((c.x, c.y, e.dxf.radius, 1.0, a0, a1))
                circle_o.append(oid)
            elif t == "POINT":
                l = e.dxf.location
                segs.append((l.x, l.y, l.x, l.y))
                seg_o.append(oid)
            else:
                box = ezbbox.extents([e], fast=True)
                if box.has_data:
                    boxes.append((box.extmin.x, box.extmin.y,
                                  box.extmax.x, box.extmax.y))
                    box_o.append(oid)
        except Exception:
            pass

    @staticmethod
    def _seg_bounds_of(segs: np.ndarray) -> np.ndarray:
        if not len(segs):
            return np.empty((0, 4))
        return np.column_stack((
            np.minimum(segs[:, 0], segs[:, 2]),
            np.minimum(segs[:, 1], segs[:, 3]),
            np.maximum(segs[:, 0], segs[:, 2]),
            np.maximum(segs[:, 1], segs[:, 3]),
        ))

    def _build(self) -> None:
        self._owners = []
        self._owner_ids = {}
        segs: list = []
        seg_o: list = []
        circles: list = []
        circle_o: list = []
        boxes: list = []
        box_o: list = []
        for e in self.document.modelspace():
            try:
                oid = self._intern(e.dxf.handle)
            except Exception:
                continue
            self._extract(e, oid, segs, seg_o, circles, circle_o, boxes, box_o)
        self._segs = np.asarray(segs, dtype=np.float64).reshape(-1, 4)
        self._seg_oidx = np.asarray(seg_o, dtype=np.int32)
        self._seg_bounds = self._seg_bounds_of(self._segs)
        self._circles = np.asarray(circles, dtype=np.float64).reshape(-1, 6)
        self._circle_oidx = np.asarray(circle_o, dtype=np.int32)
        self._boxes = np.asarray(boxes, dtype=np.float64).reshape(-1, 4)
        self._box_oidx = np.asarray(box_o, dtype=np.int32)
        self._dirty = False
        self.version += 1

    # -- incremental maintenance -------------------------------------------------
    def add_entities(self, entities) -> None:
        """Append pick geometry of freshly added entities (no full rebuild).

        Additive edits (drawn segments, paste copies) stay O(new) instead of
        re-walking the whole modelspace. No-op while dirty: the pending
        rebuild includes them anyway.
        """
        if self._dirty:
            return
        segs: list = []
        seg_o: list = []
        circles: list = []
        circle_o: list = []
        boxes: list = []
        box_o: list = []
        for e in entities:
            try:
                oid = self._intern(e.dxf.handle)
            except Exception:
                continue
            self._extract(e, oid, segs, seg_o, circles, circle_o, boxes, box_o)
        if segs:
            new = np.asarray(segs, dtype=np.float64).reshape(-1, 4)
            self._segs = np.vstack([self._segs, new])
            self._seg_oidx = np.concatenate(
                [self._seg_oidx, np.asarray(seg_o, dtype=np.int32)])
            self._seg_bounds = np.vstack(
                [self._seg_bounds, self._seg_bounds_of(new)])
        if circles:
            self._circles = np.vstack(
                [self._circles,
                 np.asarray(circles, dtype=np.float64).reshape(-1, 6)])
            self._circle_oidx = np.concatenate(
                [self._circle_oidx, np.asarray(circle_o, dtype=np.int32)])
        if boxes:
            self._boxes = np.vstack(
                [self._boxes, np.asarray(boxes, dtype=np.float64).reshape(-1, 4)])
            self._box_oidx = np.concatenate(
                [self._box_oidx, np.asarray(box_o, dtype=np.int32)])
        self.version += 1

    def remove_handles(self, handles) -> None:
        """Drop the pick geometry of erased/modified entities (no rebuild).

        Modified entities are re-added via ``add_entities`` right after —
        the full rebuild pays ezdxf bbox extents for every exotic entity in
        the drawing (>1 s on a real 10k-entity plan) and used to freeze the
        first pick after every MOVE/TRIM. No-op while dirty.
        """
        if self._dirty:
            return
        ids = self._ids_of(handles)
        if not len(ids):
            return
        for arr_name, oidx_name, bounds_name in (
                ("_segs", "_seg_oidx", "_seg_bounds"),
                ("_circles", "_circle_oidx", None),
                ("_boxes", "_box_oidx", None)):
            oidx = getattr(self, oidx_name)
            if not len(oidx):
                continue
            keep = ~np.isin(oidx, ids)
            if keep.all():
                continue
            setattr(self, arr_name, getattr(self, arr_name)[keep])
            setattr(self, oidx_name, oidx[keep])
            if bounds_name is not None:
                setattr(self, bounds_name, getattr(self, bounds_name)[keep])
        self.version += 1

    def translate_handles(self, handles, dx: float, dy: float) -> None:
        """Shift the pick geometry of MOVEd entities in place (O(rows),
        pure NumPy — no ezdxf bbox calls). No-op while dirty."""
        if self._dirty:
            return
        ids = self._ids_of(handles)
        if not len(ids):
            return
        shift4 = np.array([dx, dy, dx, dy])
        mask = np.isin(self._seg_oidx, ids)
        if mask.any():
            self._segs[mask] += shift4
            self._seg_bounds[mask] += shift4
        mask = np.isin(self._circle_oidx, ids)
        if mask.any():
            self._circles[mask, 0] += dx
            self._circles[mask, 1] += dy
        mask = np.isin(self._box_oidx, ids)
        if mask.any():
            self._boxes[mask] += shift4
        self.version += 1

    def add_translated(self, pairs, dx: float, dy: float) -> set:
        """Register pasted/copied entities by translating their SOURCE rows.

        ``pairs`` is ``[(src_handle, new_handle)]``. The sources are still in
        the drawing (Ctrl+C copies, it does not consume), so their rows are
        already here — copying + shifting them skips the ezdxf bbox extents
        walk that made a 3000-entity paste pay ~0.7 s. Returns the source
        handles that had NO rows (deleted/changed since): the caller falls
        back to ``add_entities`` for those. No-op while dirty (returns all).
        """
        if self._dirty:
            return {src for src, _new in pairs}
        known = [(s, n) for s, n in pairs if s in self._owner_ids]
        missing = {s for s, _n in pairs if s not in self._owner_ids}
        if not known:
            return missing
        remap = np.full(len(self._owners) + len(known), -1, dtype=np.int32)
        src_ids = np.empty(len(known), dtype=np.int32)
        for i, (s, n) in enumerate(known):
            sid = self._owner_ids[s]
            src_ids[i] = sid
            remap[sid] = self._intern(n)
        shift4 = np.array([dx, dy, dx, dy])
        found_ids: set = set()
        for arr_name, oidx_name, bounds_name, shift in (
                ("_segs", "_seg_oidx", "_seg_bounds", shift4),
                ("_circles", "_circle_oidx", None, None),
                ("_boxes", "_box_oidx", None, shift4)):
            oidx = getattr(self, oidx_name)
            if not len(oidx):
                continue
            mask = np.isin(oidx, src_ids)
            if not mask.any():
                continue
            rows = np.nonzero(mask)[0]
            arr = getattr(self, arr_name)
            block = arr[rows].copy()
            if shift is not None:
                block += shift
            else:  # circles: center only
                block[:, 0] += dx
                block[:, 1] += dy
            setattr(self, arr_name, np.vstack([arr, block]))
            setattr(self, oidx_name,
                    np.concatenate([oidx, remap[oidx[rows]]]))
            if bounds_name is not None:
                bounds = getattr(self, bounds_name)
                setattr(self, bounds_name,
                        np.vstack([bounds, bounds[rows] + shift4]))
            found_ids.update(np.unique(oidx[rows]).tolist())
        self.version += 1
        missing |= {s for s, _n in known
                    if self._owner_ids[s] not in found_ids}
        return missing

    # -- queries --------------------------------------------------------------
    def pick(self, cursor: tuple[float, float], tolerance: float) -> Optional[str]:
        """Handle of the closest entity within ``tolerance`` of the cursor."""
        if self._dirty:
            self._build()
        cx, cy = cursor
        best: Optional[tuple[float, str]] = None

        if len(self._segs):
            # bounds prefilter: exact distances only for rows near the cursor
            b = self._seg_bounds
            cand = np.nonzero(
                (b[:, 0] - tolerance <= cx) & (b[:, 2] + tolerance >= cx)
                & (b[:, 1] - tolerance <= cy) & (b[:, 3] + tolerance >= cy))[0]
            if len(cand):
                d = _dist_point_segments(self._segs[cand], cx, cy)
                i = int(np.argmin(d))
                if d[i] <= tolerance:
                    best = (float(d[i]),
                            self._owners[self._seg_oidx[cand[i]]])
        if len(self._circles):
            c = self._circles
            dc = np.hypot(c[:, 0] - cx, c[:, 1] - cy)
            d = np.abs(dc - c[:, 2])
            # arcs only count when the cursor angle falls inside their sweep
            ang = np.arctan2(cy - c[:, 1], cx - c[:, 0]) % math.tau
            rel = (ang - c[:, 4]) % math.tau
            on_span = (c[:, 3] == 0.0) | (rel <= (c[:, 5] - c[:, 4]))
            d = np.where(on_span, d, np.inf)
            i = int(np.argmin(d))
            if d[i] <= tolerance and (best is None or d[i] < best[0]):
                best = (float(d[i]), self._owners[self._circle_oidx[i]])
        if len(self._boxes) and best is None:
            b = self._boxes
            inside = ((cx >= b[:, 0] - tolerance) & (cx <= b[:, 2] + tolerance)
                      & (cy >= b[:, 1] - tolerance) & (cy <= b[:, 3] + tolerance))
            hits = np.nonzero(inside)[0]
            if len(hits):
                areas = ((b[hits, 2] - b[hits, 0]) * (b[hits, 3] - b[hits, 1]))
                best = (tolerance, self._owners[
                    self._box_oidx[hits[int(np.argmin(areas))]]])
        return best[1] if best else None

    def window(self, rect: tuple[float, float, float, float]) -> list[str]:
        """Entities FULLY inside the rect (left-to-right blue window)."""
        if self._dirty:
            self._build()
        x0, y0, x1, y1 = rect
        n = len(self._owners)
        present = np.zeros(n, dtype=bool)
        bad = np.zeros(n, dtype=bool)
        if len(self._segs):
            b = self._seg_bounds
            ins = ((b[:, 0] >= x0) & (b[:, 2] <= x1)
                   & (b[:, 1] >= y0) & (b[:, 3] <= y1))
            present[self._seg_oidx] = True
            bad[self._seg_oidx[~ins]] = True
        if len(self._circles):
            c = self._circles
            ins = ((c[:, 0] - c[:, 2] >= x0) & (c[:, 0] + c[:, 2] <= x1)
                   & (c[:, 1] - c[:, 2] >= y0) & (c[:, 1] + c[:, 2] <= y1))
            present[self._circle_oidx] = True
            bad[self._circle_oidx[~ins]] = True
        if len(self._boxes):
            b = self._boxes
            ins = ((b[:, 0] >= x0) & (b[:, 2] <= x1)
                   & (b[:, 1] >= y0) & (b[:, 3] <= y1))
            present[self._box_oidx] = True
            bad[self._box_oidx[~ins]] = True
        return [self._owners[i] for i in np.nonzero(present & ~bad)[0]]

    def crossing(self, rect: tuple[float, float, float, float]) -> list[str]:
        """Entities touching the rect (right-to-left green crossing)."""
        if self._dirty:
            self._build()
        x0, y0, x1, y1 = rect
        n = len(self._owners)
        touched = np.zeros(n, dtype=bool)
        if len(self._segs):
            s = self._segs
            b = self._seg_bounds
            overlap = ((b[:, 0] <= x1) & (b[:, 2] >= x0)
                       & (b[:, 1] <= y1) & (b[:, 3] >= y0))
            in1 = ((s[:, 0] >= x0) & (s[:, 0] <= x1)
                   & (s[:, 1] >= y0) & (s[:, 1] <= y1))
            in2 = ((s[:, 2] >= x0) & (s[:, 2] <= x1)
                   & (s[:, 3] >= y0) & (s[:, 3] <= y1))
            touched[self._seg_oidx[overlap & (in1 | in2)]] = True
            # both endpoints outside but bbox overlapping: exact test on the
            # (few) rows that might cross an edge of the rect
            for i in np.nonzero(overlap & ~in1 & ~in2)[0]:
                if _seg_intersects_rect(s[i], x0, y0, x1, y1):
                    touched[self._seg_oidx[i]] = True
        if len(self._circles):
            c = self._circles
            qx = np.clip(c[:, 0], x0, x1)
            qy = np.clip(c[:, 1], y0, y1)
            near = np.hypot(c[:, 0] - qx, c[:, 1] - qy) <= c[:, 2]
            corners_in = np.ones(len(c), dtype=bool)
            for X in (x0, x1):
                for Y in (y0, y1):
                    corners_in &= np.hypot(c[:, 0] - X, c[:, 1] - Y) < c[:, 2]
            center_in = ((c[:, 0] >= x0) & (c[:, 0] <= x1)
                         & (c[:, 1] >= y0) & (c[:, 1] <= y1))
            hit = near & ~(corners_in & ~center_in)
            touched[self._circle_oidx[hit]] = True
        if len(self._boxes):
            b = self._boxes
            hit = ~((b[:, 2] < x0) | (b[:, 0] > x1)
                    | (b[:, 3] < y0) | (b[:, 1] > y1))
            touched[self._box_oidx[hit]] = True
        return sorted(self._owners[i] for i in np.nonzero(touched)[0])

    def bounds_of(self, handles: Iterable[str]):
        """(min_x, min_y, max_x, max_y) of the given entities from the cached
        rows, or None. Ctrl+C needs a base point; ezdxf bbox.extents walks
        INSERT contents recursively (~1.6 s on a 3000-entity selection)."""
        if self._dirty:
            return None
        wanted = set(handles)
        min_x = min_y = np.inf
        max_x = max_y = -np.inf
        segs = self.segments_of(wanted)
        if len(segs):
            min_x = min(min_x, segs[:, (0, 2)].min())
            max_x = max(max_x, segs[:, (0, 2)].max())
            min_y = min(min_y, segs[:, (1, 3)].min())
            max_y = max(max_y, segs[:, (1, 3)].max())
        circles = self.circles_of(wanted)
        if len(circles):
            min_x = min(min_x, (circles[:, 0] - circles[:, 2]).min())
            max_x = max(max_x, (circles[:, 0] + circles[:, 2]).max())
            min_y = min(min_y, (circles[:, 1] - circles[:, 2]).min())
            max_y = max(max_y, (circles[:, 1] + circles[:, 2]).max())
        boxes = self.boxes_of(wanted)
        if len(boxes):
            min_x = min(min_x, boxes[:, 0].min())
            max_x = max(max_x, boxes[:, 2].max())
            min_y = min(min_y, boxes[:, 1].min())
            max_y = max(max_y, boxes[:, 3].max())
        if min_x > max_x:
            return None
        return (float(min_x), float(min_y), float(max_x), float(max_y))

    def segments_of(self, handles: Iterable[str]) -> np.ndarray:
        """Pick segments of the given entities (for highlight drawing)."""
        if self._dirty:
            self._build()
        ids = self._ids_of(handles)
        if not len(ids) or not len(self._seg_oidx):
            return np.empty((0, 4))
        return self._segs[np.isin(self._seg_oidx, ids)]

    def circles_of(self, handles: Iterable[str]) -> np.ndarray:
        if self._dirty:
            self._build()
        ids = self._ids_of(handles)
        if not len(ids) or not len(self._circle_oidx):
            return np.empty((0, 4))
        return self._circles[np.isin(self._circle_oidx, ids)]

    def boxes_of(self, handles: Iterable[str]) -> np.ndarray:
        if self._dirty:
            self._build()
        ids = self._ids_of(handles)
        if not len(ids) or not len(self._box_oidx):
            return np.empty((0, 4))
        return self._boxes[np.isin(self._box_oidx, ids)]


def _dist_point_segments(segs: np.ndarray, px: float, py: float) -> np.ndarray:
    dx = segs[:, 2] - segs[:, 0]
    dy = segs[:, 3] - segs[:, 1]
    L2 = dx * dx + dy * dy
    L2s = np.where(L2 == 0.0, 1.0, L2)
    t = ((px - segs[:, 0]) * dx + (py - segs[:, 1]) * dy) / L2s
    t = np.clip(np.where(L2 == 0.0, 0.0, t), 0.0, 1.0)
    qx = segs[:, 0] + t * dx
    qy = segs[:, 1] + t * dy
    return np.hypot(px - qx, py - qy)


def _seg_intersects_rect(s, x0, y0, x1, y1) -> bool:
    if max(s[0], s[2]) < x0 or min(s[0], s[2]) > x1:
        return False
    if max(s[1], s[3]) < y0 or min(s[1], s[3]) > y1:
        return False
    # endpoint inside?
    for px, py in ((s[0], s[1]), (s[2], s[3])):
        if x0 <= px <= x1 and y0 <= py <= y1:
            return True
    # crosses any rect edge?
    edges = ((x0, y0, x1, y0), (x1, y0, x1, y1),
             (x1, y1, x0, y1), (x0, y1, x0, y0))
    for e in edges:
        if _segments_cross(s, e):
            return True
    return False


def _segments_cross(s1, s2) -> bool:
    x1, y1, x2, y2 = s1
    x3, y3, x4, y4 = s2
    d = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
    if abs(d) < 1e-15:
        return False
    t = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / d
    u = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / d
    return 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0


def _circle_intersects_rect(c, x0, y0, x1, y1) -> bool:
    cx, cy, r = c[0], c[1], c[2]
    # closest point of rect to center within r AND rect not fully inside circle
    qx = min(max(cx, x0), x1)
    qy = min(max(cy, y0), y1)
    if math.hypot(cx - qx, cy - qy) > r:
        return False
    # if all four corners are inside the circle, the circle does not touch
    # the rect boundary (rect fully inside circle: crossing should still
    # select it? AutoCAD: crossing selects if the curve crosses the window
    # OR is inside; a rect inside the circle does not touch the curve).
    corners_in = all(math.hypot(cx - X, cy - Y) < r
                     for X in (x0, x1) for Y in (y0, y1))
    center_in = x0 <= cx <= x1 and y0 <= cy <= y1
    if corners_in and not center_in:
        return False
    return True


def entity_grips(entity) -> list[tuple[float, float, str]]:
    """Grip points of an entity: (x, y, role).

    Roles drive editing: 'end'/'mid'/'vertex' move that point, 'center'
    moves the whole entity, 'radius'/'quadrant' resize. Mirrors AutoCAD's
    grip set for the supported types.
    """
    import math

    t = entity.dxftype()
    grips: list[tuple[float, float, str]] = []
    if t == "LINE":
        s, e = entity.dxf.start, entity.dxf.end
        grips.append((s.x, s.y, "end"))
        grips.append(((s.x + e.x) / 2, (s.y + e.y) / 2, "mid"))
        grips.append((e.x, e.y, "end"))
    elif t == "LWPOLYLINE":
        pts = entity.get_points("xy")
        for x, y in pts:
            grips.append((x, y, "vertex"))
        pairs = list(zip(pts, pts[1:]))
        if entity.closed and len(pts) > 2:
            pairs.append((pts[-1], pts[0]))
        for a, b in pairs:
            grips.append(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, "mid"))
    elif t == "CIRCLE":
        c, r = entity.dxf.center, entity.dxf.radius
        grips.append((c.x, c.y, "center"))
        for ang in (0, 90, 180, 270):
            grips.append((c.x + r * math.cos(math.radians(ang)),
                          c.y + r * math.sin(math.radians(ang)), "quadrant"))
    elif t == "ARC":
        c, r = entity.dxf.center, entity.dxf.radius
        grips.append((c.x, c.y, "center"))
        for a in (entity.dxf.start_angle, entity.dxf.end_angle):
            grips.append((c.x + r * math.cos(math.radians(a)),
                          c.y + r * math.sin(math.radians(a)), "end"))
        mid = math.radians((entity.dxf.start_angle + entity.dxf.end_angle) / 2)
        grips.append((c.x + r * math.cos(mid), c.y + r * math.sin(mid), "mid"))
    elif t == "POINT":
        l = entity.dxf.location
        grips.append((l.x, l.y, "center"))
    return grips


def apply_grip_edit(entity, grip_index: int, role: str, new_point):
    """Move the grip at ``grip_index`` to ``new_point``, editing the entity
    in place. Returns True on success (undo is handled by the caller through
    a snapshot Command)."""
    import math

    t = entity.dxftype()
    nx, ny = new_point
    if t == "LINE":
        if role == "mid":               # move whole line
            s, e = entity.dxf.start, entity.dxf.end
            dx = nx - (s.x + e.x) / 2
            dy = ny - (s.y + e.y) / 2
            entity.dxf.start = (s.x + dx, s.y + dy, 0)
            entity.dxf.end = (e.x + dx, e.y + dy, 0)
        elif grip_index == 0:
            entity.dxf.start = (nx, ny, 0)
        else:
            entity.dxf.end = (nx, ny, 0)
        return True
    if t == "LWPOLYLINE":
        pts = entity.get_points("xyseb")
        n = len(pts)
        if role == "vertex" and grip_index < n:
            p = list(pts[grip_index])
            p[0], p[1] = nx, ny
            pts[grip_index] = tuple(p)
            entity.set_points(pts, format="xyseb")
            return True
        if role == "mid":
            # AutoCAD/BricsCAD: the midpoint (triangle) grip MOVES the whole
            # segment — it translates both its endpoints by the drag delta,
            # keeping the segment straight; adjacent segments stretch to
            # follow. No vertex is inserted.
            seg = grip_index - n
            a, b = seg, (seg + 1) % n if entity.closed else seg + 1
            if b >= len(pts):
                return False
            mid_x = (pts[a][0] + pts[b][0]) / 2.0
            mid_y = (pts[a][1] + pts[b][1]) / 2.0
            dx, dy = nx - mid_x, ny - mid_y
            for idx in (a, b):
                p = list(pts[idx])
                p[0] += dx
                p[1] += dy
                pts[idx] = tuple(p)
            entity.set_points(pts, format="xyseb")
            return True
        return False
    if t == "CIRCLE":
        if role == "center":
            entity.dxf.center = (nx, ny, 0)
        else:                            # quadrant: new radius
            c = entity.dxf.center
            entity.dxf.radius = max(1e-9, math.hypot(nx - c.x, ny - c.y))
        return True
    if t == "ARC":
        c = entity.dxf.center
        if role == "center":
            entity.dxf.center = (nx, ny, 0)
        elif role == "mid":              # new radius, angles kept
            entity.dxf.radius = max(1e-9, math.hypot(nx - c.x, ny - c.y))
        else:                            # end grip: move that angle
            ang = math.degrees(math.atan2(ny - c.y, nx - c.x))
            if grip_index == 1:
                entity.dxf.start_angle = ang
            else:
                entity.dxf.end_angle = ang
        return True
    if t == "POINT":
        entity.dxf.location = (nx, ny, 0)
        return True
    return False
