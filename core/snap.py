# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Object snaps (osnap) — the AutoCAD drawing "feel".

The engine extracts snappable geometry from the ezdxf modelspace into
NumPy arrays once (lazily, invalidated on edits), so each cursor move is a
vectorized query instead of an entity walk — a cadastre-sized drawing
stays interactive.

Scale notes (1.35 M segment rows on a real cadastre): owners are interned
to int32 ids for vectorized removal/translation, and ``find`` prefilters
segments through a per-row bounds table — one vectorized pass selects the
rows near the cursor and every snap kind works on those candidates only
(the old per-kind full-array passes cost ~130 ms per mouse move).

Supported: END, MID, CEN, QUA, NOD, INT, PER, NEA. Priorities follow
AutoCAD: an endpoint beats a nearby midpoint beats "nearest".

Curves (ELLIPSE, SPLINE, and the arc segments of a polyline) are NOT fed in
as chords. A chord chain would put a false ENDpoint on every flattening
vertex and a false MIDpoint on every chord — dozens of markers that are not
features of the drawing. Instead each type contributes what it really has:

* polyline arc segments become real arcs, so END lands on the vertices, MID
  on the arc's own midpoint and CEN on its centre — before this they were
  treated as straight, and MID sat on the chord, off the drawing;
* an ellipse gives its centre, its quadrants, and its two ends if it is an
  elliptical arc;
* a spline gives its two ends;
* both give a MIDpoint measured ALONG the curve, and feed a separate chord
  table (``_curves``) that only NEA, PER and INT read — the snaps for which
  a fine chord chain is the right approximation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

# Lower = wins when within threshold.
PRIORITY = {"END": 0, "INT": 1, "MID": 2, "CEN": 3, "NOD": 4, "QUA": 5,
            "PER": 6, "NEA": 7}
ALL_KINDS = frozenset(PRIORITY)

# Point targets share one table with a kind column, so a curve can offer an
# end, a midpoint, a centre and four quadrants without four more arrays.
TARGET_KINDS = ("END", "MID", "CEN", "QUA")
_TARGET_CODE = {kind: i for i, kind in enumerate(TARGET_KINDS)}

# Max sagitta of the chord chain, as a fraction of the curve's size. The
# exact snaps (END, MID, CEN, QUA) never come from these chords, so this only
# bounds how far a NEA can sit from the true curve — same divisor the pick
# index uses, so both agree on where a curve is.
CURVE_SAGITTA = 500


@dataclass(frozen=True)
class SnapHit:
    x: float
    y: float
    kind: str


class SnapEngine:
    """Snappable-geometry cache over a Document's modelspace."""

    def __init__(self, document) -> None:
        self.document = document
        self._dirty = True
        self._owners: list[str] = []
        self._owner_ids: dict[str, int] = {}
        self._segs = np.empty((0, 4))     # x1 y1 x2 y2
        self._seg_oidx = np.empty(0, dtype=np.int32)
        self._seg_bounds = np.empty((0, 4))
        self._circles = np.empty((0, 3))  # cx cy r (full circles)
        self._circle_oidx = np.empty(0, dtype=np.int32)
        self._arcs = np.empty((0, 5))     # cx cy r a0 a1 (ccw radians)
        self._arc_oidx = np.empty(0, dtype=np.int32)
        self._points = np.empty((0, 2))   # NOD targets
        self._point_oidx = np.empty(0, dtype=np.int32)
        # Chords of ELLIPSE/SPLINE: read by NEA, PER and INT only.
        self._curves = np.empty((0, 4))
        self._curve_oidx = np.empty(0, dtype=np.int32)
        self._curve_bounds = np.empty((0, 4))
        # x y kind_code, for the exact targets a curve owns (see TARGET_KINDS)
        self._targets = np.empty((0, 3))
        self._target_oidx = np.empty(0, dtype=np.int32)

    def invalidate(self) -> None:
        self._dirty = True

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

    # -- extraction -----------------------------------------------------------
    @staticmethod
    def _extract(e, oid, segs, seg_o, circles, circle_o,
                 arcs, arc_o, points, point_o,
                 curves=None, curve_o=None, targets=None, target_o=None) -> None:
        t = e.dxftype()
        try:
            if t == "LINE":
                s, w = e.dxf.start, e.dxf.end
                segs.append((s.x, s.y, w.x, w.y))
                seg_o.append(oid)
            elif t == "LWPOLYLINE":
                vertices = [(v[0], v[1], v[4]) for v in e.get_points("xyseb")]
                SnapEngine._polyline(vertices, bool(e.closed), oid,
                                     segs, seg_o, arcs, arc_o)
            elif t == "POLYLINE":
                if e.get_mode() in ("AcDb2dPolyline", "AcDb3dPolyline"):
                    vertices = [(v.dxf.location.x, v.dxf.location.y,
                                 getattr(v.dxf, "bulge", 0.0) or 0.0)
                                for v in e.vertices]
                    SnapEngine._polyline(vertices, bool(e.is_closed), oid,
                                         segs, seg_o, arcs, arc_o)
            elif t == "CIRCLE":
                c = e.dxf.center
                circles.append((c.x, c.y, e.dxf.radius))
                circle_o.append(oid)
            elif t == "ARC":
                c = e.dxf.center
                a0 = math.radians(e.dxf.start_angle)
                a1 = math.radians(e.dxf.end_angle)
                if a1 <= a0:
                    a1 += math.tau
                arcs.append((c.x, c.y, e.dxf.radius, a0, a1))
                arc_o.append(oid)
            elif t == "POINT":
                l = e.dxf.location
                points.append((l.x, l.y))
                point_o.append(oid)
            elif t == "ELLIPSE" and curves is not None:
                SnapEngine._ellipse(e, oid, curves, curve_o, targets, target_o)
            elif t == "SPLINE" and curves is not None:
                SnapEngine._spline(e, oid, curves, curve_o, targets, target_o)
        except Exception:
            pass  # malformed entity: not snappable, not fatal

    # -- per-type helpers ------------------------------------------------------
    @staticmethod
    def _polyline(vertices, closed: bool, oid, segs, seg_o, arcs, arc_o) -> None:
        """Straight spans become segments, bulged spans become real arcs.

        A bulged span used to go in as its chord, which put MIDpoint off the
        drawing and hid the arc's centre entirely.
        """
        from ezdxf.math import bulge_to_arc

        spans = list(zip(vertices, vertices[1:]))
        if closed and len(vertices) > 2:
            spans.append((vertices[-1], vertices[0]))
        for (x1, y1, bulge), (x2, y2, _b2) in spans:
            if not bulge:
                segs.append((x1, y1, x2, y2))
                seg_o.append(oid)
                continue
            try:
                center, a0, a1, radius = bulge_to_arc((x1, y1), (x2, y2), bulge)
            except Exception:
                segs.append((x1, y1, x2, y2))
                seg_o.append(oid)
                continue
            if a1 <= a0:
                a1 += math.tau
            arcs.append((center.x, center.y, radius, a0, a1))
            arc_o.append(oid)

    @staticmethod
    def _curve_targets(points, oid, targets, target_o) -> None:
        """END at the two ends and MID measured ALONG the curve."""
        if len(points) < 2:
            return
        first, last = points[0], points[-1]
        closed = math.isclose(first[0], last[0], abs_tol=1e-9) and \
            math.isclose(first[1], last[1], abs_tol=1e-9)
        if closed:
            # A closed curve has no ends and no midpoint — AutoCAD offers
            # neither. Its quadrants and centre carry the exact snaps.
            return
        for x, y in (first, last):
            targets.append((x, y, _TARGET_CODE["END"]))
            target_o.append(oid)
        lengths = [0.0]
        for a, b in zip(points, points[1:]):
            lengths.append(lengths[-1] + math.dist(a, b))
        half = lengths[-1] / 2.0
        if half <= 0:
            return
        for i, run in enumerate(lengths[1:], start=1):
            if run >= half:
                a, b = points[i - 1], points[i]
                span = run - lengths[i - 1]
                t = 0.0 if span == 0 else (half - lengths[i - 1]) / span
                targets.append((a[0] + t * (b[0] - a[0]),
                                a[1] + t * (b[1] - a[1]),
                                _TARGET_CODE["MID"]))
                target_o.append(oid)
                return

    @staticmethod
    def _flatten(entity):
        """Chord chain of a curve, at a sagitta that scales with its size."""
        from ezdxf import bbox as ezbbox
        from ezdxf import path as ezpath

        path = ezpath.make_path(entity)
        box = ezbbox.extents([entity], fast=True)
        size = max(box.size.x, box.size.y) if box.has_data else 1.0
        distance = max(abs(size) / CURVE_SAGITTA, 1e-9)
        return [(v.x, v.y) for v in path.flattening(distance)]

    @staticmethod
    def _chords(points, oid, curves, curve_o) -> None:
        for a, b in zip(points, points[1:]):
            curves.append((a[0], a[1], b[0], b[1]))
            curve_o.append(oid)

    @staticmethod
    def _ellipse(e, oid, curves, curve_o, targets, target_o) -> None:
        points = SnapEngine._flatten(e)
        SnapEngine._chords(points, oid, curves, curve_o)
        SnapEngine._curve_targets(points, oid, targets, target_o)
        c = e.dxf.center
        targets.append((c.x, c.y, _TARGET_CODE["CEN"]))
        target_o.append(oid)
        # Quadrants: the four axis extremes, and only those the arc covers.
        major = e.dxf.major_axis
        minor = e.minor_axis
        for sign_major, sign_minor in ((1, 0), (0, 1), (-1, 0), (0, -1)):
            qx = c.x + sign_major * major.x + sign_minor * minor.x
            qy = c.y + sign_major * major.y + sign_minor * minor.y
            if SnapEngine._on_curve((qx, qy), points):
                targets.append((qx, qy, _TARGET_CODE["QUA"]))
                target_o.append(oid)

    @staticmethod
    def _on_curve(point, points, tol_ratio: float = 0.02) -> bool:
        """Is this point on the traced run of the curve? (elliptical arcs)"""
        if len(points) < 2:
            return False
        spread = max(max(p[0] for p in points) - min(p[0] for p in points),
                     max(p[1] for p in points) - min(p[1] for p in points))
        tol = max(spread * tol_ratio, 1e-9)
        px, py = point
        return any(math.dist((px, py), p) <= tol for p in points)

    @staticmethod
    def _spline(e, oid, curves, curve_o, targets, target_o) -> None:
        points = SnapEngine._flatten(e)
        SnapEngine._chords(points, oid, curves, curve_o)
        SnapEngine._curve_targets(points, oid, targets, target_o)

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
        arcs: list = []
        arc_o: list = []
        points: list = []
        point_o: list = []
        curves: list = []
        curve_o: list = []
        targets: list = []
        target_o: list = []
        for e in self.document.modelspace():
            try:
                oid = self._intern(e.dxf.handle)
            except Exception:
                continue
            self._extract(e, oid, segs, seg_o, circles, circle_o,
                          arcs, arc_o, points, point_o,
                          curves, curve_o, targets, target_o)
        self._segs = np.asarray(segs, dtype=np.float64).reshape(-1, 4)
        self._seg_oidx = np.asarray(seg_o, dtype=np.int32)
        self._seg_bounds = self._seg_bounds_of(self._segs)
        self._circles = np.asarray(circles, dtype=np.float64).reshape(-1, 3)
        self._circle_oidx = np.asarray(circle_o, dtype=np.int32)
        self._arcs = np.asarray(arcs, dtype=np.float64).reshape(-1, 5)
        self._arc_oidx = np.asarray(arc_o, dtype=np.int32)
        self._points = np.asarray(points, dtype=np.float64).reshape(-1, 2)
        self._point_oidx = np.asarray(point_o, dtype=np.int32)
        self._curves = np.asarray(curves, dtype=np.float64).reshape(-1, 4)
        self._curve_oidx = np.asarray(curve_o, dtype=np.int32)
        self._curve_bounds = self._seg_bounds_of(self._curves)
        self._targets = np.asarray(targets, dtype=np.float64).reshape(-1, 3)
        self._target_oidx = np.asarray(target_o, dtype=np.int32)
        self._dirty = False

    def add_entities(self, entities) -> None:
        """Append the geometry of freshly added entities to the cache.

        Purely additive edits (LINE segments, paste copies) must not pay a
        full modelspace walk on the next cursor move — on a large drawing
        that rebuild is the per-click lag. No-op while dirty: the pending
        rebuild will pick the entities up anyway.
        """
        if self._dirty:
            return
        segs: list = []
        seg_o: list = []
        circles: list = []
        circle_o: list = []
        arcs: list = []
        arc_o: list = []
        points: list = []
        point_o: list = []
        curves: list = []
        curve_o: list = []
        targets: list = []
        target_o: list = []
        for e in entities:
            try:
                oid = self._intern(e.dxf.handle)
            except Exception:
                continue
            self._extract(e, oid, segs, seg_o, circles, circle_o,
                          arcs, arc_o, points, point_o,
                          curves, curve_o, targets, target_o)
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
                 np.asarray(circles, dtype=np.float64).reshape(-1, 3)])
            self._circle_oidx = np.concatenate(
                [self._circle_oidx, np.asarray(circle_o, dtype=np.int32)])
        if arcs:
            self._arcs = np.vstack(
                [self._arcs, np.asarray(arcs, dtype=np.float64).reshape(-1, 5)])
            self._arc_oidx = np.concatenate(
                [self._arc_oidx, np.asarray(arc_o, dtype=np.int32)])
        if points:
            self._points = np.vstack(
                [self._points,
                 np.asarray(points, dtype=np.float64).reshape(-1, 2)])
            self._point_oidx = np.concatenate(
                [self._point_oidx, np.asarray(point_o, dtype=np.int32)])
        if curves:
            new = np.asarray(curves, dtype=np.float64).reshape(-1, 4)
            self._curves = np.vstack([self._curves, new])
            self._curve_oidx = np.concatenate(
                [self._curve_oidx, np.asarray(curve_o, dtype=np.int32)])
            self._curve_bounds = np.vstack(
                [self._curve_bounds, self._seg_bounds_of(new)])
        if targets:
            self._targets = np.vstack(
                [self._targets,
                 np.asarray(targets, dtype=np.float64).reshape(-1, 3)])
            self._target_oidx = np.concatenate(
                [self._target_oidx, np.asarray(target_o, dtype=np.int32)])

    def translate_handles(self, handles, dx: float, dy: float) -> None:
        """Shift the cached geometry of MOVEd entities in place.

        A pure translation needs no re-extraction at all — O(rows), pure
        NumPy, no ezdxf calls. No-op while dirty.
        """
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
        mask = np.isin(self._curve_oidx, ids)
        if mask.any():
            self._curves[mask] += shift4
            self._curve_bounds[mask] += shift4
        for arr_name, oidx_name in (("_circles", "_circle_oidx"),
                                    ("_arcs", "_arc_oidx"),
                                    ("_points", "_point_oidx"),
                                    ("_targets", "_target_oidx")):
            oidx = getattr(self, oidx_name)
            if not len(oidx):
                continue
            m = np.isin(oidx, ids)
            if m.any():
                arr = getattr(self, arr_name)
                arr[m, 0] += dx
                arr[m, 1] += dy

    def remove_handles(self, handles) -> None:
        """Drop the snap geometry of erased/modified entities (no rebuild).

        Together with ``add_entities`` this lets TRIM/MOVE patch the cache in
        O(touched); the full rebuild walks every LWPOLYLINE in the drawing.
        No-op while dirty.
        """
        if self._dirty:
            return
        ids = self._ids_of(handles)
        if not len(ids):
            return
        keep = ~np.isin(self._seg_oidx, ids)
        if not keep.all():
            self._segs = self._segs[keep]
            self._seg_oidx = self._seg_oidx[keep]
            self._seg_bounds = self._seg_bounds[keep]
        keep = ~np.isin(self._curve_oidx, ids)
        if not keep.all():
            self._curves = self._curves[keep]
            self._curve_oidx = self._curve_oidx[keep]
            self._curve_bounds = self._curve_bounds[keep]
        for arr_name, oidx_name in (("_circles", "_circle_oidx"),
                                    ("_arcs", "_arc_oidx"),
                                    ("_points", "_point_oidx"),
                                    ("_targets", "_target_oidx")):
            oidx = getattr(self, oidx_name)
            if not len(oidx):
                continue
            k = ~np.isin(oidx, ids)
            if not k.all():
                setattr(self, arr_name, getattr(self, arr_name)[k])
                setattr(self, oidx_name, oidx[k])

    # -- query ----------------------------------------------------------------
    def find(
        self,
        cursor: tuple[float, float],
        threshold: float,
        kinds: frozenset[str] = ALL_KINDS,
        from_point: Optional[tuple[float, float]] = None,
    ) -> Optional[SnapHit]:
        """Best snap within ``threshold`` world units of the cursor.

        ``from_point`` anchors PER (perpendicular from the previous point).
        """
        if self._dirty:
            self._build()
        cx, cy = cursor
        best: Optional[tuple[int, float, SnapHit]] = None

        def offer(kind: str, x: float, y: float) -> None:
            nonlocal best
            d = math.hypot(x - cx, y - cy)
            if d > threshold:
                return
            key = (PRIORITY[kind], d)
            if best is None or key < (best[0], best[1]):
                best = (PRIORITY[kind], d, SnapHit(x, y, kind))

        circles, arcs, points = self._circles, self._arcs, self._points

        # ONE bounds pass selects the segments near the cursor; every snap
        # kind below works on those candidates only.
        segs = np.empty((0, 4))
        seg_oids = np.empty(0, dtype=np.int32)
        if len(self._segs):
            b = self._seg_bounds
            near = ((b[:, 0] - threshold <= cx) & (b[:, 2] + threshold >= cx)
                    & (b[:, 1] - threshold <= cy) & (b[:, 3] + threshold >= cy))
            segs = self._segs[near]
            seg_oids = self._seg_oidx[near]
        # Curve chords ride along for NEA/PER/INT, and ONLY those: an END on
        # every chord vertex would be a marker on nothing.
        curves = np.empty((0, 4))
        curve_oids = np.empty(0, dtype=np.int32)
        if len(self._curves):
            b = self._curve_bounds
            near = ((b[:, 0] - threshold <= cx) & (b[:, 2] + threshold >= cx)
                    & (b[:, 1] - threshold <= cy) & (b[:, 3] + threshold >= cy))
            curves = self._curves[near]
            curve_oids = self._curve_oidx[near]
        # Exact targets a curve owns (its ends, its midpoint, a centre, the
        # quadrants), already filtered to the cursor's reach.
        targets = np.empty((0, 3))
        if len(self._targets):
            t = self._targets
            near = ((np.abs(t[:, 0] - cx) <= threshold)
                    & (np.abs(t[:, 1] - cy) <= threshold))
            targets = t[near]

        def offer_targets(kind: str) -> None:
            if not len(targets) or kind not in kinds:
                return
            rows = targets[targets[:, 2] == _TARGET_CODE[kind]]
            if not len(rows):
                return
            d2 = (rows[:, 0] - cx) ** 2 + (rows[:, 1] - cy) ** 2
            i = int(np.argmin(d2))
            offer(kind, float(rows[i, 0]), float(rows[i, 1]))

        if "END" in kinds and len(segs):
            for exy in (segs[:, 0:2], segs[:, 2:4]):
                d2 = (exy[:, 0] - cx) ** 2 + (exy[:, 1] - cy) ** 2
                i = int(np.argmin(d2))
                offer("END", exy[i, 0], exy[i, 1])
        if "END" in kinds and len(arcs):
            for a_idx in (3, 4):
                ex = arcs[:, 0] + arcs[:, 2] * np.cos(arcs[:, a_idx])
                ey = arcs[:, 1] + arcs[:, 2] * np.sin(arcs[:, a_idx])
                d2 = (ex - cx) ** 2 + (ey - cy) ** 2
                i = int(np.argmin(d2))
                offer("END", float(ex[i]), float(ey[i]))
        offer_targets("END")
        if "MID" in kinds and len(segs):
            mx = (segs[:, 0] + segs[:, 2]) / 2.0
            my = (segs[:, 1] + segs[:, 3]) / 2.0
            d2 = (mx - cx) ** 2 + (my - cy) ** 2
            i = int(np.argmin(d2))
            offer("MID", float(mx[i]), float(my[i]))
        offer_targets("MID")
        if "MID" in kinds and len(arcs):
            # An arc's midpoint is on the arc, not on its chord.
            amid = (arcs[:, 3] + arcs[:, 4]) / 2.0
            mx = arcs[:, 0] + arcs[:, 2] * np.cos(amid)
            my = arcs[:, 1] + arcs[:, 2] * np.sin(amid)
            d2 = (mx - cx) ** 2 + (my - cy) ** 2
            i = int(np.argmin(d2))
            offer("MID", float(mx[i]), float(my[i]))
        if "CEN" in kinds:
            for arr in (circles, arcs):
                if len(arr):
                    d2 = (arr[:, 0] - cx) ** 2 + (arr[:, 1] - cy) ** 2
                    i = int(np.argmin(d2))
                    offer("CEN", float(arr[i, 0]), float(arr[i, 1]))
        offer_targets("CEN")
        offer_targets("QUA")
        if "QUA" in kinds:
            # The four compass points of a circle, and of an arc when the
            # sweep actually reaches them. Vectorized per compass point: a
            # Python loop over every circle in the drawing cost 3 ms per
            # mouse move on a plan with a thousand of them.
            for arr, full in ((circles, True), (arcs, False)):
                if not len(arr):
                    continue
                for step in range(4):
                    ang = step * math.pi / 2.0
                    qx = arr[:, 0] + arr[:, 2] * math.cos(ang)
                    qy = arr[:, 1] + arr[:, 2] * math.sin(ang)
                    hits = np.nonzero((np.abs(qx - cx) <= threshold)
                                      & (np.abs(qy - cy) <= threshold))[0]
                    for i in hits:
                        if not full and not _angle_in_sweep(
                                ang, arr[i, 3], arr[i, 4]):
                            continue
                        offer("QUA", float(qx[i]), float(qy[i]))
        if "NOD" in kinds and len(points):
            d2 = (points[:, 0] - cx) ** 2 + (points[:, 1] - cy) ** 2
            i = int(np.argmin(d2))
            offer("NOD", float(points[i, 0]), float(points[i, 1]))

        if len(curves):
            segs = np.vstack([segs, curves]) if len(segs) else curves
            seg_oids = (np.concatenate([seg_oids, curve_oids])
                        if len(seg_oids) else curve_oids)
        near_idx = np.arange(len(segs))[:64]  # dense areas: cap pairwise work
        if "INT" in kinds and len(near_idx) >= 2:
            for j, a in enumerate(near_idx):
                for b_ in near_idx[j + 1:]:
                    # An entity does not intersect itself: two chords of the
                    # same curve meet at every flattening vertex, and that is
                    # a seam of ours, not a feature of the drawing.
                    if len(seg_oids) and seg_oids[a] == seg_oids[b_]:
                        continue
                    hit = _seg_intersection(segs[a], segs[b_])
                    if hit is not None:
                        offer("INT", hit[0], hit[1])
        if "PER" in kinds and from_point is not None and len(near_idx):
            fx, fy = from_point
            for a in near_idx:
                p = _project_on_segment(segs[a], fx, fy)
                if p is not None:
                    offer("PER", p[0], p[1])
        if "NEA" in kinds:
            for a in near_idx:
                p = _closest_on_segment(segs[a], cx, cy)
                offer("NEA", p[0], p[1])
            for arr, full in ((circles, True), (arcs, False)):
                if not len(arr):
                    continue
                # only rims within reach of the cursor
                rim = np.abs(np.hypot(cx - arr[:, 0], cy - arr[:, 1])
                             - arr[:, 2]) <= threshold
                for row in arr[rim]:
                    p = _closest_on_circle(row, cx, cy, full)
                    if p is not None:
                        offer("NEA", p[0], p[1])

        return best[2] if best else None


def _angle_in_sweep(angle: float, a0: float, a1: float) -> bool:
    """Is this compass angle inside the arc's counter-clockwise sweep?"""
    rel = (angle - a0) % math.tau
    return rel <= (a1 - a0) + 1e-12


def _closest_on_segment(seg, px, py):
    x1, y1, x2, y2 = seg
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
    return (x1 + t * dx, y1 + t * dy)


def _project_on_segment(seg, px, py):
    """Foot of the perpendicular, only when it lands inside the segment."""
    x1, y1, x2, y2 = seg
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return None
    t = ((px - x1) * dx + (py - y1) * dy) / L2
    if t < 0.0 or t > 1.0:
        return None
    return (x1 + t * dx, y1 + t * dy)


def _closest_on_circle(row, px, py, full: bool):
    cx, cy, r = row[0], row[1], row[2]
    d = math.hypot(px - cx, py - cy)
    if d == 0:
        return None
    ang = math.atan2(py - cy, px - cx)
    if not full:
        a0, a1 = row[3], row[4]
        a = ang % math.tau
        if a < a0:
            a += math.tau
        if a > a1:
            return None
    return (cx + r * math.cos(ang), cy + r * math.sin(ang))


def _seg_intersection(s1, s2):
    """Intersection point of two segments, or None."""
    x1, y1, x2, y2 = s1
    x3, y3, x4, y4 = s2
    d = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
    if abs(d) < 1e-12:
        return None
    t = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / d
    u = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / d
    if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    return None
