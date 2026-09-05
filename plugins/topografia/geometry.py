# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Plane geometry of a surveyed polygon: sides, bearings, interior angles,
area, perimeter, and the cuts that subdivide it. Pure functions on
``(x, y)`` tuples in drawing units (metres, east and north); no document.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional

from .points import cad_to_azimuth

Point = tuple[float, float]
_EPS = 1e-9


def polygon_vertices(entity) -> Optional[list[Point]]:
    """The vertices of a closed LWPOLYLINE / 2D POLYLINE, without the
    repeated closing vertex; None for anything else."""
    kind = entity.dxftype()
    if kind == "LWPOLYLINE":
        if not entity.closed:
            return None
        pts = [(float(x), float(y)) for x, y in entity.get_points("xy")]
    elif kind == "POLYLINE":
        if not entity.is_closed or not entity.is_2d_polyline:
            return None
        pts = [(float(v.dxf.location.x), float(v.dxf.location.y))
               for v in entity.vertices]
    else:
        return None
    if len(pts) > 1 and _close(pts[0], pts[-1]):
        pts = pts[:-1]
    return pts if len(pts) >= 3 else None


def _close(a: Point, b: Point) -> bool:
    return abs(a[0] - b[0]) < _EPS and abs(a[1] - b[1]) < _EPS


def signed_area(pts: list[Point]) -> float:
    total = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def area(pts: list[Point]) -> float:
    return abs(signed_area(pts))


def is_clockwise(pts: list[Point]) -> bool:
    return signed_area(pts) < 0


def perimeter(pts: list[Point]) -> float:
    return sum(side.length for side in sides(pts))


def centroid(pts: list[Point]) -> Point:
    a = signed_area(pts)
    if abs(a) < _EPS:
        return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    cx = cy = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        cross = x1 * y2 - x2 * y1
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    return (cx / (6.0 * a), cy / (6.0 * a))


@dataclass(frozen=True)
class Side:
    index: int            # from vertex ``index`` to ``index + 1``
    start: Point
    end: Point
    length: float
    azimuth: float        # from north, clockwise, degrees


def sides(pts: list[Point]) -> list[Side]:
    out = []
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        out.append(Side(i, a, b, math.hypot(dx, dy),
                        cad_to_azimuth(math.degrees(math.atan2(dy, dx)))))
    return out


def interior_angles(pts: list[Point]) -> list[float]:
    """The interior angle at each vertex, in degrees (they sum to
    (n - 2) x 180 for a simple polygon, whichever way it is drawn)."""
    n = len(pts)
    cw = is_clockwise(pts)
    out = []
    for i in range(n):
        v, prev, nxt = pts[i], pts[i - 1], pts[(i + 1) % n]
        to_prev = math.degrees(math.atan2(prev[1] - v[1], prev[0] - v[0]))
        to_next = math.degrees(math.atan2(nxt[1] - v[1], nxt[0] - v[0]))
        angle = (to_next - to_prev) if cw else (to_prev - to_next)
        out.append(angle % 360.0)
    return out


def oriented(pts: list[Point], clockwise: bool) -> list[Point]:
    """The same polygon, starting at the same vertex, in the wanted turn."""
    if is_clockwise(pts) == clockwise:
        return list(pts)
    return [pts[0]] + list(reversed(pts[1:]))


def contains(pts: list[Point], q: Point) -> bool:
    """Ray casting; a point on the boundary counts as inside."""
    x, y = q
    inside = False
    n = len(pts)
    for i in range(n):
        (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % n]
        if _on_segment(q, (x1, y1), (x2, y2)):
            return True
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if xi > x:
                inside = not inside
    return inside


def _on_segment(q: Point, a: Point, b: Point) -> bool:
    cross = (b[0] - a[0]) * (q[1] - a[1]) - (b[1] - a[1]) * (q[0] - a[0])
    if abs(cross) > 1e-7 * max(1.0, math.hypot(b[0] - a[0], b[1] - a[1])):
        return False
    return (min(a[0], b[0]) - _EPS <= q[0] <= max(a[0], b[0]) + _EPS
            and min(a[1], b[1]) - _EPS <= q[1] <= max(a[1], b[1]) + _EPS)


def nearest_side(pts: list[Point], q: Point) -> Side:
    """The side closest to ``q``."""
    best, best_d = None, math.inf
    for side in sides(pts):
        d = _point_segment_distance(q, side.start, side.end)
        if d < best_d:
            best, best_d = side, d
    return best


def project_on_boundary(pts: list[Point], q: Point) -> Point:
    side = nearest_side(pts, q)
    return _project(q, side.start, side.end)


def _project(q: Point, a: Point, b: Point) -> Point:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    if length2 < _EPS:
        return a
    t = ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / length2
    t = max(0.0, min(1.0, t))
    return (a[0] + t * dx, a[1] + t * dy)


def _point_segment_distance(q: Point, a: Point, b: Point) -> float:
    p = _project(q, a, b)
    return math.hypot(q[0] - p[0], q[1] - p[1])


# -- cutting -----------------------------------------------------------------------

def clip(pts: list[Point], keep: Callable[[Point], float]) -> list[Point]:
    """Sutherland-Hodgman against the half-plane ``keep(q) >= 0``, where
    ``keep`` is a signed distance (linear along an edge)."""
    out: list[Point] = []
    n = len(pts)
    for i in range(n):
        cur, nxt = pts[i], pts[(i + 1) % n]
        s_cur, s_nxt = keep(cur), keep(nxt)
        if s_cur >= 0:
            out.append(cur)
        if (s_cur >= 0) != (s_nxt >= 0):
            t = s_cur / (s_cur - s_nxt)
            out.append((cur[0] + t * (nxt[0] - cur[0]), cur[1] + t * (nxt[1] - cur[1])))
    return out


def _left_of(p: Point, d: Point) -> Callable[[Point], float]:
    """Signed distance to the directed line through ``p`` along ``d``:
    positive on the left."""
    length = math.hypot(*d) or 1.0
    ux, uy = d[0] / length, d[1] / length

    def s(q: Point) -> float:
        return ux * (q[1] - p[1]) - uy * (q[0] - p[0])
    return s


def split_by_line(pts: list[Point], p: Point, d: Point) -> tuple[list[Point], list[Point]]:
    """(left piece, right piece) of the polygon against the directed line."""
    s = _left_of(p, d)
    return clip(pts, s), clip(pts, lambda q: -s(q))


def line_boundary_hits(pts: list[Point], p: Point, d: Point) -> list[Point]:
    """Where the infinite line meets the boundary, ordered along ``d``."""
    s = _left_of(p, d)
    length = math.hypot(*d) or 1.0
    ux, uy = d[0] / length, d[1] / length
    hits = []
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        sa, sb = s(a), s(b)
        if abs(sa) < _EPS:
            hits.append(a)
        if (sa > 0) != (sb > 0) and abs(sa) >= _EPS and abs(sb) >= _EPS:
            t = sa / (sa - sb)
            hits.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
    hits.sort(key=lambda q: ux * (q[0] - p[0]) + uy * (q[1] - p[1]))
    unique: list[Point] = []
    for q in hits:
        if not unique or not _close(unique[-1], q):
            unique.append(q)
    return unique


@dataclass
class Cut:
    """A straight cut of a polygon: its segment and the two areas."""

    start: Point
    end: Point
    left: list[Point]
    right: list[Point]

    @property
    def area_left(self) -> float:
        return area(self.left) if len(self.left) >= 3 else 0.0

    @property
    def area_right(self) -> float:
        return area(self.right) if len(self.right) >= 3 else 0.0


def _cut(pts: list[Point], p: Point, d: Point) -> Cut:
    left, right = split_by_line(pts, p, d)
    hits = line_boundary_hits(pts, p, d)
    if len(hits) >= 2:
        start, end = hits[0], hits[-1]
    else:
        start = end = p
    return Cut(start, end, left, right)


def _bisect(f: Callable[[float], float], lo: float, hi: float, target: float,
            tol: float = 1e-6, steps: int = 100) -> float:
    """``x`` in [lo, hi] with ``f(x) == target``, for ``f`` monotonic."""
    f_lo, f_hi = f(lo), f(hi)
    rising = f_hi >= f_lo
    for _ in range(steps):
        mid = (lo + hi) / 2.0
        value = f(mid)
        if abs(value - target) <= tol:
            return mid
        if (value < target) == rising:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def cut_parallel_to_side(pts: list[Point], side_index: int, target_area: float) -> Cut:
    """The cut parallel to side ``side_index`` that leaves ``target_area``
    between that side and the cut. The piece next to the side is ``left``.
    """
    side = sides(pts)[side_index]
    d = (side.end[0] - side.start[0], side.end[1] - side.start[1])
    length = math.hypot(*d) or 1.0
    ux, uy = d[0] / length, d[1] / length
    # inward normal: the polygon lies on one side of its own edge
    nx, ny = (-uy, ux) if not is_clockwise(pts) else (uy, -ux)
    depth = max(nx * (q[0] - side.start[0]) + ny * (q[1] - side.start[1]) for q in pts)

    def piece(t: float) -> list[Point]:
        return clip(pts, lambda q: t - (nx * (q[0] - side.start[0]) + ny * (q[1] - side.start[1])))

    total = area(pts)
    wanted = max(0.0, min(total, target_area))
    t = _bisect(lambda t: area(piece(t)) if len(piece(t)) >= 3 else 0.0, 0.0, depth, wanted)
    p = (side.start[0] + nx * t, side.start[1] + ny * t)
    near = piece(t)
    far = clip(pts, lambda q: (nx * (q[0] - side.start[0]) + ny * (q[1] - side.start[1])) - t)
    hits = line_boundary_hits(pts, p, (ux, uy))
    start, end = (hits[0], hits[-1]) if len(hits) >= 2 else (p, p)
    return Cut(start, end, near, far)


def cut_through_point(pts: list[Point], pivot: Point, target_area: float) -> Cut:
    """The cut through ``pivot`` whose LEFT piece (looking along the cut
    from the pivot) has ``target_area``. Scans a full turn for the bracket,
    then bisects; a pivot on the boundary of a convex lot always has one."""
    total = area(pts)
    wanted = max(0.0, min(total, target_area))

    def left_area(theta: float) -> float:
        d = (math.cos(theta), math.sin(theta))
        piece = clip(pts, _left_of(pivot, d))
        return area(piece) if len(piece) >= 3 else 0.0

    samples = 360
    values = [(k * 2 * math.pi / samples, left_area(k * 2 * math.pi / samples))
              for k in range(samples + 1)]
    theta = None
    for (t0, a0), (t1, a1) in zip(values, values[1:]):
        if (a0 - wanted) * (a1 - wanted) <= 0:
            theta = _bisect(left_area, t0, t1, wanted)
            break
    if theta is None:
        theta = min(values, key=lambda tv: abs(tv[1] - wanted))[0]
    d = (math.cos(theta), math.sin(theta))
    cut = _cut(pts, pivot, d)
    hits = line_boundary_hits(pts, pivot, d)
    # the chord that starts at the pivot and crosses the polygon
    others = [q for q in hits if not _close(q, pivot)]
    inside = [q for q in others
              if contains(pts, ((q[0] + pivot[0]) / 2, (q[1] + pivot[1]) / 2))]
    if inside:
        far = max(inside, key=lambda q: math.hypot(q[0] - pivot[0], q[1] - pivot[1]))
        cut.start, cut.end = pivot, far
    return cut


def cut_by_two_points(pts: list[Point], a: Point, b: Point) -> Cut:
    d = (b[0] - a[0], b[1] - a[1])
    return _cut(pts, a, d)


# -- grids -------------------------------------------------------------------------

def grid_values(lo: float, hi: float, spacing: float) -> list[float]:
    """The multiples of ``spacing`` inside [lo, hi]."""
    if spacing <= 0 or hi < lo:
        return []
    first = math.ceil(lo / spacing - 1e-9)
    last = math.floor(hi / spacing + 1e-9)
    return [k * spacing for k in range(first, last + 1)]


def format_area(m2: float, decimals: int = 2) -> str:
    return f"{m2:.{decimals}f} m²"


def format_length(m: float, decimals: int = 2) -> str:
    return f"{m:.{decimals}f} m"
