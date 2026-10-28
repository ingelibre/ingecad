# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Geometry for the editing commands: trim, extend, offset, fillet.

Pure 2D math over plain tuples — headless and exhaustively testable,
because TRIM/EXTEND are the highest bar of the editing phase ("se sienten
como AutoCAD").
"""
from __future__ import annotations

import math
from typing import Optional

Point = tuple[float, float]
Seg = tuple[float, float, float, float]

EPS = 1e-9


# -- intersections -------------------------------------------------------------

def line_line_intersection(s1: Seg, s2: Seg, infinite2: bool = False):
    """Intersection of segment s1 (as param t in [0,1]) with s2.

    Returns (t, point) or None. ``infinite2`` treats s2 as an infinite line
    (EXTEND's edge behaves that way in AutoCAD's default Edge=Extend? No —
    default is no-extend; we keep edges finite unless asked).
    """
    x1, y1, x2, y2 = s1
    x3, y3, x4, y4 = s2
    d = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
    if abs(d) < EPS:
        return None
    t = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / d
    u = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / d
    if not infinite2 and not (-EPS <= u <= 1.0 + EPS):
        return None
    return t, (x1 + t * (x2 - x1), y1 + t * (y2 - y1))


#: Tangency tolerance, relative to the size of the numbers involved. A
#: tangent computed by the drawing lands within rounding of the circle
#: (1e-14 in Rafael's drawing), which a strict test reads as "misses" or
#: "crosses twice at the same point" — and TRIM then finds nothing to cut
#: (#14). Relative, because at UTM coordinates (1e7) doubles carry ~1e-9
#: of rounding: 1e-12 of the scale is ~1e-5 there and ~1e-10 near origin.
TANGENT_TOL = 1e-12


def _scale(*values: float) -> float:
    return max(1.0, *(abs(v) for v in values))


def circle_circle_intersections(c1: Point, r1: float,
                                c2: Point, r2: float) -> list[Point]:
    """Intersection points of two circles (0, 1 or 2); a tangency is one."""
    dx, dy = c2[0] - c1[0], c2[1] - c1[1]
    d = math.hypot(dx, dy)
    tol = TANGENT_TOL * _scale(c1[0], c1[1], c2[0], c2[1], r1, r2)
    if d < tol or d > r1 + r2 + tol or d < abs(r1 - r2) - tol:
        return []
    a = (r1 * r1 - r2 * r2 + d * d) / (2.0 * d)
    h = math.sqrt(max(0.0, r1 * r1 - a * a))
    mx = c1[0] + a * dx / d
    my = c1[1] + a * dy / d
    if h <= tol or abs(d - (r1 + r2)) <= tol or abs(d - abs(r1 - r2)) <= tol:
        return [(mx, my)]
    ox, oy = -dy / d * h, dx / d * h
    return [(mx + ox, my + oy), (mx - ox, my - oy)]


def line_circle_intersections(seg: Seg, center: Point, r: float):
    """Params t (may be outside [0,1]) where the segment's line meets circle.

    Measured from the foot of the perpendicular rather than through the
    quadratic's discriminant: at a tangency the discriminant is a difference
    of two large, nearly equal numbers and its sign is noise. A line within
    TANGENT_TOL of the circle touches it once.
    """
    x1, y1, x2, y2 = seg
    dx, dy = x2 - x1, y2 - y1
    a = dx * dx + dy * dy
    if a < EPS:
        return []
    t_foot = ((center[0] - x1) * dx + (center[1] - y1) * dy) / a
    fx = x1 + t_foot * dx - center[0]
    fy = y1 + t_foot * dy - center[1]
    d = math.hypot(fx, fy)
    tol = TANGENT_TOL * _scale(center[0], center[1], r, x1, y1, x2, y2)
    if d > r + tol:
        return []
    if d >= r - tol:
        # Along the line a tangency is ill-conditioned: 1e-14 of radial
        # rounding moves the foot ~1e-7, enough to fall just past the end
        # of a line drawn TO the tangent point. An end that lies on the
        # circle IS that point (a tangent touches once) — use it exactly.
        for t_end, (ex, ey) in ((0.0, (x1, y1)), (1.0, (x2, y2))):
            if abs(math.hypot(ex - center[0], ey - center[1]) - r) <= tol:
                return [t_end]
        return [t_foot]
    half = math.sqrt(r * r - d * d) / math.sqrt(a)
    return [t_foot - half, t_foot + half]


def _unique_angles(angles: list[float], tol: float = 1e-9) -> list[float]:
    """Sorted angles in [0, 2pi) with near-duplicates merged, 0/2pi included."""
    out: list[float] = []
    for angle in sorted(a % math.tau for a in angles):
        if out and angle - out[-1] <= tol:
            continue
        out.append(angle)
    if len(out) > 1 and out[0] + math.tau - out[-1] <= tol:
        out.pop()
    return out


# Edge circles are (center, r) full circles or (center, r, a0, a1) arcs
# (radians ccw, a1 > a0). A crossing only counts if it lies ON the arc.

def _norm_circle(entry):
    if len(entry) == 2:
        return (entry[0], entry[1], 0.0, math.tau)
    return entry


def _on_arc(center: Point, a0: float, a1: float, x: float, y: float) -> bool:
    span = a1 - a0
    if span >= math.tau - EPS:
        return True
    ang = math.atan2(y - center[1], x - center[0]) % math.tau
    rel = (ang - a0) % math.tau
    # a point AT the start angle may come back as 2pi minus a hair
    return rel <= span + 1e-9 or rel >= math.tau - 1e-9


# -- TRIM ----------------------------------------------------------------------

def trim_segment(seg: Seg, cutters: list[Seg],
                 circles: list[tuple[Point, float]],
                 pick_t: float) -> Optional[list[Seg]]:
    """Remove the span of ``seg`` around ``pick_t`` between cutting edges.

    Returns the surviving pieces (0, 1 or 2 segments), or None when no
    cutter crosses the segment (nothing to trim — AutoCAD says so too).
    """
    ts: list[float] = []
    for c in cutters:
        hit = line_line_intersection(seg, c)
        if hit is not None and -EPS < hit[0] < 1.0 + EPS:
            ts.append(min(max(hit[0], 0.0), 1.0))
    for entry in circles:
        center, r, a0, a1 = _norm_circle(entry)
        for t in line_circle_intersections(seg, center, r):
            if -EPS < t < 1.0 + EPS:
                x = seg[0] + t * (seg[2] - seg[0])
                y = seg[1] + t * (seg[3] - seg[1])
                if _on_arc(center, a0, a1, x, y):
                    ts.append(min(max(t, 0.0), 1.0))
    ts = sorted({round(t, 12) for t in ts if EPS < t < 1.0 - EPS})
    if not ts:
        return None
    lo = max((t for t in ts if t <= pick_t), default=0.0)
    hi = min((t for t in ts if t >= pick_t), default=1.0)
    x1, y1, x2, y2 = seg

    def at(t: float) -> Point:
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))

    pieces: list[Seg] = []
    if lo > 0.0:
        p = at(lo)
        pieces.append((x1, y1, p[0], p[1]))
    if hi < 1.0:
        p = at(hi)
        pieces.append((p[0], p[1], x2, y2))
    return pieces


def _circle_crossing_angles(center: Point, r: float, cutters: list[Seg],
                            cutter_circles: list[tuple[Point, float]]):
    angles: list[float] = []
    for cseg in cutters:
        for t in line_circle_intersections(cseg, center, r):
            if -EPS <= t <= 1.0 + EPS:
                x = cseg[0] + t * (cseg[2] - cseg[0])
                y = cseg[1] + t * (cseg[3] - cseg[1])
                angles.append(math.atan2(y - center[1], x - center[0]) % math.tau)
    for entry in cutter_circles:
        c2, r2, a0, a1 = _norm_circle(entry)
        for x, y in circle_circle_intersections(center, r, c2, r2):
            if _on_arc(c2, a0, a1, x, y):
                angles.append(math.atan2(y - center[1], x - center[0]) % math.tau)
    return angles


def circle_crossings(center: Point, r: float, cutters: list[Seg],
                     cutter_circles) -> list[float]:
    """Angles where the circle meets the cutters (segments and circles)."""
    return _circle_crossing_angles(center, r, cutters, cutter_circles or [])


def trim_circle(center: Point, r: float, cutters: list[Seg],
                pick_angle: float,
                cutter_circles: Optional[list[tuple[Point, float]]] = None,
                ) -> Optional[tuple[float, float]]:
    """Trim a full circle at its cutter crossings: the surviving ARC.

    Cutters can be segments AND other circles/arcs (the classic
    two-intersecting-circles trim). Returns (start_angle, end_angle) in
    degrees ccw, or None if fewer than two crossings exist.
    """
    angles = _unique_angles(
        _circle_crossing_angles(center, r, cutters, cutter_circles or []))
    if len(angles) < 2:
        return None
    a = pick_angle % math.tau
    # find the arc span containing the pick, remove it: survivor is the rest
    for i, a0 in enumerate(angles):
        a1 = angles[(i + 1) % len(angles)]
        span = (a1 - a0) % math.tau or math.tau
        if (a - a0) % math.tau <= span:
            return (math.degrees(a1), math.degrees(a0))
    return None


def trim_arc(center: Point, r: float, a_start: float, a_end: float,
             cutters: list[Seg], pick_angle: float,
             cutter_circles: Optional[list[tuple[Point, float]]] = None):
    """Trim an ARC (degrees) around pick_angle. Returns list of (a0, a1)."""
    s = math.radians(a_start) % math.tau
    e = math.radians(a_end) % math.tau
    sweep = (e - s) % math.tau or math.tau
    cuts: list[float] = []
    for ang in _circle_crossing_angles(center, r, cutters, cutter_circles or []):
        rel = (ang - s) % math.tau
        if EPS < rel < sweep - EPS:
            cuts.append(rel)
    cuts = _unique_angles(cuts)
    if not cuts:
        return None
    pick_rel = (pick_angle - s) % math.tau
    lo = max((c for c in cuts if c <= pick_rel), default=0.0)
    hi = min((c for c in cuts if c >= pick_rel), default=sweep)
    out = []
    if lo > 0.0:
        out.append((math.degrees(s), math.degrees(s + lo)))
    if hi < sweep:
        out.append((math.degrees(s + hi), math.degrees(s + sweep)))
    return out


def trim_polyline(points: list[Point], closed: bool, pick_point: Point,
                  cutters: list[Seg],
                  circles: list[tuple[Point, float]]):
    """Trim the picked span of a straight-segment polyline.

    The polyline's OWN other segments also act as cutting edges (AutoCAD
    self-trim: the crossing tails of a sketch trim against the shape).
    Returns a list of vertex chains (0, 1 or 2 polylines) or None when no
    edge crosses the picked segment.
    """
    n = len(points)
    if n < 2:
        return None
    seg_count = n if closed else n - 1
    segs = [(points[i][0], points[i][1],
             points[(i + 1) % n][0], points[(i + 1) % n][1])
            for i in range(seg_count)]

    # picked segment: closest to the pick point
    def dist2(seg: Seg) -> float:
        x1, y1, x2, y2 = seg
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((pick_point[0] - x1) * dx
                                                   + (pick_point[1] - y1) * dy) / L2))
        qx, qy = x1 + t * dx, y1 + t * dy
        return (pick_point[0] - qx) ** 2 + (pick_point[1] - qy) ** 2

    k = min(range(seg_count), key=lambda i: dist2(segs[i]))
    seg_k = segs[k]
    dx, dy = seg_k[2] - seg_k[0], seg_k[3] - seg_k[1]
    L2 = dx * dx + dy * dy
    pick_t = 0.0 if L2 == 0 else max(0.0, min(1.0, (
        (pick_point[0] - seg_k[0]) * dx + (pick_point[1] - seg_k[1]) * dy) / L2))

    all_cutters = list(cutters) + [s for i, s in enumerate(segs) if i != k]
    pieces = trim_segment(seg_k, all_cutters, circles, pick_t)
    if pieces is None:
        return None
    piece1 = next((p for p in pieces
                   if (p[0], p[1]) == (seg_k[0], seg_k[1])), None)
    piece2 = next((p for p in pieces
                   if (p[2], p[3]) == (seg_k[2], seg_k[3])), None)

    chains: list[list[Point]] = []
    if closed:
        # the ring opens at the removed span: one chain from the trim end
        # forward around to the trim start
        idxs = [(k + 1 + i) % n for i in range(n)]
        chain: list[Point] = []
        if piece2 is not None:
            chain.append((piece2[0], piece2[1]))
        chain.extend(points[i] for i in idxs)
        if piece1 is not None:
            chain.append((piece1[2], piece1[3]))
        if len(chain) >= 2:
            chains.append(chain)
    else:
        chain_a: list[Point] = list(points[:k + 1])
        if piece1 is not None:
            chain_a.append((piece1[2], piece1[3]))
        chain_b: list[Point] = []
        if piece2 is not None:
            chain_b.append((piece2[0], piece2[1]))
        chain_b.extend(points[k + 1:])
        for chain in (chain_a, chain_b):
            if len(chain) >= 2:
                chains.append(chain)
    return chains


# -- EXTEND --------------------------------------------------------------------

def extend_segment(seg: Seg, edges: list[Seg],
                   circles: list[tuple[Point, float]],
                   pick_t: float) -> Optional[Seg]:
    """Extend the picked end of ``seg`` to the nearest boundary crossing."""
    forward = pick_t >= 0.5  # extend the end nearest to the pick
    best: Optional[float] = None
    for e in edges:
        hit = line_line_intersection(seg, e)
        if hit is None:
            continue
        t = hit[0]
        if forward and t > 1.0 + EPS:
            best = t if best is None else min(best, t)
        elif not forward and t < -EPS:
            best = t if best is None else max(best, t)
    for entry in circles:
        center, r, a0, a1 = _norm_circle(entry)
        for t in line_circle_intersections(seg, center, r):
            x = seg[0] + t * (seg[2] - seg[0])
            y = seg[1] + t * (seg[3] - seg[1])
            if not _on_arc(center, a0, a1, x, y):
                continue
            if forward and t > 1.0 + EPS:
                best = t if best is None else min(best, t)
            elif not forward and t < -EPS:
                best = t if best is None else max(best, t)
    if best is None:
        return None
    x1, y1, x2, y2 = seg
    px = x1 + best * (x2 - x1)
    py = y1 + best * (y2 - y1)
    return (x1, y1, px, py) if forward else (px, py, x2, y2)


def extend_arc(center: Point, r: float, a_start: float, a_end: float,
               pick_angle: float, edges: list[Seg],
               circles: list) -> Optional[tuple[float, float]]:
    """Extend the end of an ARC (degrees) nearest the pick along its own
    circle to the first boundary crossing; the new (start, end) in degrees,
    or None. The circle meeting a boundary only by touching it counts --
    the tangency tolerance of ``line_circle_intersections`` (issue #14)."""
    s = math.radians(a_start) % math.tau
    e = math.radians(a_end) % math.tau
    sweep = (e - s) % math.tau or math.tau
    if sweep >= math.tau - EPS:
        return None                          # a full circle has no end
    rel = (pick_angle - s) % math.tau
    if rel <= sweep:
        forward = rel > sweep / 2.0          # the end nearest along the arc
    else:                                    # picked off the arc: nearest end
        forward = (rel - sweep) < (math.tau - rel)
    crossings = []
    for ang in _circle_crossing_angles(center, r, edges, circles):
        rel_c = (ang - s) % math.tau
        if sweep + EPS < rel_c < math.tau - EPS:
            crossings.append(rel_c)
    if not crossings:
        return None
    # angles in [0, 360), as AutoCAD writes them: extending past 0° gave a
    # start of -11.5° (found by the release tour)
    if forward:
        start, end = math.degrees(s), math.degrees(s + min(crossings))
    else:
        start = math.degrees(s - (math.tau - max(crossings)))
        end = math.degrees(s + sweep)
    return (start % 360.0, end % 360.0)


def extend_polyline(points: list[Point], closed: bool, pick_point: Point,
                    edges: list[Seg],
                    circles: list[tuple[Point, float]]):
    """Extend the end of an open polyline nearest to the pick.

    The polyline's own other segments also act as boundaries. Returns the
    new vertex list, or None (closed polylines cannot extend; no boundary).
    """
    n = len(points)
    if closed or n < 2:
        return None
    own = [(points[i][0], points[i][1], points[i + 1][0], points[i + 1][1])
           for i in range(n - 1)]
    d_start = math.hypot(pick_point[0] - points[0][0],
                         pick_point[1] - points[0][1])
    d_end = math.hypot(pick_point[0] - points[-1][0],
                       pick_point[1] - points[-1][1])
    if d_end <= d_start:
        seg = (points[-2][0], points[-2][1], points[-1][0], points[-1][1])
        boundaries = edges + own[:-1]
        new = extend_segment(seg, boundaries, circles, 1.0)
        if new is None:
            return None
        return points[:-1] + [(new[2], new[3])]
    seg = (points[1][0], points[1][1], points[0][0], points[0][1])
    boundaries = edges + own[1:]
    new = extend_segment(seg, boundaries, circles, 1.0)
    if new is None:
        return None
    return [(new[2], new[3])] + points[1:]


# -- OFFSET --------------------------------------------------------------------

def offset_line(seg: Seg, distance: float, side_point: Point) -> Seg:
    """Parallel copy of the segment, on the side of ``side_point``."""
    x1, y1, x2, y2 = seg
    dx, dy = x2 - x1, y2 - y1
    L = math.hypot(dx, dy)
    if L < EPS:
        raise ValueError("zero-length line")
    nx, ny = -dy / L, dx / L
    # choose the normal pointing toward the side point
    side = (side_point[0] - x1) * nx + (side_point[1] - y1) * ny
    if side < 0:
        nx, ny = -nx, -ny
    ox, oy = nx * distance, ny * distance
    return (x1 + ox, y1 + oy, x2 + ox, y2 + oy)


def offset_circle_radius(r: float, distance: float,
                         center: Point, side_point: Point) -> Optional[float]:
    """New radius: outward if the side point is outside, inward otherwise."""
    d = math.hypot(side_point[0] - center[0], side_point[1] - center[1])
    new_r = r + distance if d > r else r - distance
    return new_r if new_r > EPS else None


# -- FILLET --------------------------------------------------------------------

def fillet_corner(s1: Seg, s2: Seg) -> Optional[tuple[Seg, Seg]]:
    """Radius-0 fillet: trim/extend both lines to their intersection.

    Keeps each line's far end (the endpoint farther from the corner).
    """
    hit = line_line_intersection(s1, (s2[0], s2[1], s2[2], s2[3]), infinite2=True)
    if hit is None:
        return None
    # also require s2's line to actually reach the corner (infinite both)
    corner = hit[1]

    def keep_far(seg: Seg) -> Seg:
        d_start = math.hypot(seg[0] - corner[0], seg[1] - corner[1])
        d_end = math.hypot(seg[2] - corner[0], seg[3] - corner[1])
        if d_start >= d_end:
            return (seg[0], seg[1], corner[0], corner[1])
        return (corner[0], corner[1], seg[2], seg[3])

    return keep_far(s1), keep_far(s2)


def fillet_arc(s1: Seg, s2: Seg, radius: float):
    """Fillet arc between two lines: (center, r, a0_deg, a1_deg, t1, t2).

    t1/t2 are the tangent points on s1/s2 (the lines get trimmed there).
    Returns None for parallel lines or when the radius does not fit.
    """
    hit = line_line_intersection(s1, s2, infinite2=True)
    if hit is None:
        return None
    corner = hit[1]

    def unit_away(seg: Seg) -> tuple[float, float]:
        # direction from the corner toward the segment's farther endpoint
        d_start = math.hypot(seg[0] - corner[0], seg[1] - corner[1])
        far = (seg[0], seg[1]) if d_start >= math.hypot(
            seg[2] - corner[0], seg[3] - corner[1]) else (seg[2], seg[3])
        vx, vy = far[0] - corner[0], far[1] - corner[1]
        L = math.hypot(vx, vy)
        if L < EPS:
            raise ValueError("degenerate")
        return vx / L, vy / L

    try:
        u1 = unit_away(s1)
        u2 = unit_away(s2)
    except ValueError:
        return None
    cos2a = u1[0] * u2[0] + u1[1] * u2[1]
    angle = math.acos(max(-1.0, min(1.0, cos2a))) / 2.0
    if angle < EPS or abs(angle - math.pi / 2) < EPS:
        return None
    dist_along = radius / math.tan(angle)
    t1 = (corner[0] + u1[0] * dist_along, corner[1] + u1[1] * dist_along)
    t2 = (corner[0] + u2[0] * dist_along, corner[1] + u2[1] * dist_along)
    bx, by = u1[0] + u2[0], u1[1] + u2[1]
    bl = math.hypot(bx, by)
    if bl < EPS:
        return None
    center_dist = radius / math.sin(angle)
    cx = corner[0] + bx / bl * center_dist
    cy = corner[1] + by / bl * center_dist
    a1 = math.degrees(math.atan2(t1[1] - cy, t1[0] - cx))
    a2 = math.degrees(math.atan2(t2[1] - cy, t2[0] - cx))
    # arc sweeps the short way between the tangent points
    if (a2 - a1) % 360.0 > 180.0:
        a1, a2 = a2, a1
    return ((cx, cy), radius, a1, a2, t1, t2)


def sided_fillet(s1: Seg, pick1: Point, s2: Seg, pick2: Point,
                 radius: float):
    """A fillet between two lines that keeps the side of each that was
    picked, as AutoCAD does where the lines cross.

    Returns ``(corner, t1, t2, center, far1, far2, sweep)`` -- the tangent
    points (both the corner for radius 0), the fillet arc's centre (None
    for radius 0), the end of each line that stays, and the arc's included
    angle -- or the reason it cannot be made: "parallel" or "too large".
    The old rule kept each line's end farther from the corner, which on
    crossing lines is often the side NOT picked (GeoCad Yaguarete had to
    patch it).
    """
    hit = line_line_intersection(s1, s2, infinite2=True)
    if hit is None:
        return "parallel"
    corner = hit[1]

    def side(seg: Seg, pick: Point):
        dx, dy = seg[2] - seg[0], seg[3] - seg[1]
        length = math.hypot(dx, dy)
        if length < EPS:
            return None
        ux, uy = dx / length, dy / length
        along = (pick[0] - corner[0]) * ux + (pick[1] - corner[1]) * uy
        if abs(along) < EPS:            # picked on the corner: the far end
            ends = ((seg[0] - corner[0]) * ux + (seg[1] - corner[1]) * uy,
                    (seg[2] - corner[0]) * ux + (seg[3] - corner[1]) * uy)
            along = max(ends, key=abs)
        if along < 0:
            ux, uy = -ux, -uy
        far = max(((seg[0], seg[1]), (seg[2], seg[3])),
                  key=lambda p: (p[0] - corner[0]) * ux + (p[1] - corner[1]) * uy)
        reach = (far[0] - corner[0]) * ux + (far[1] - corner[1]) * uy
        return (ux, uy), far, reach

    a, b = side(s1, pick1), side(s2, pick2)
    if a is None or b is None:
        return "parallel"
    (u1, far1, reach1), (u2, far2, reach2) = a, b
    cos_phi = max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1]))
    phi = math.acos(cos_phi)
    if phi < EPS or abs(phi - math.pi) < EPS:
        return "parallel"
    if radius <= 0.0:
        return corner, corner, corner, None, far1, far2, 0.0
    along = radius / math.tan(phi / 2.0)
    if along >= reach1 - EPS or along >= reach2 - EPS:
        return "too large"
    t1 = (corner[0] + u1[0] * along, corner[1] + u1[1] * along)
    t2 = (corner[0] + u2[0] * along, corner[1] + u2[1] * along)
    bx, by = u1[0] + u2[0], u1[1] + u2[1]
    bl = math.hypot(bx, by)
    centre_at = radius / math.sin(phi / 2.0)
    center = (corner[0] + bx / bl * centre_at, corner[1] + by / bl * centre_at)
    return corner, t1, t2, center, far1, far2, math.pi - phi


def sided_chamfer(s1: Seg, pick1: Point, s2: Seg, pick2: Point,
                  d1: float, d2: float):
    """CHAMFER's corner on the picked sides (see sided_fillet): returns
    ``(corner, c1, c2, far1, far2)`` -- the bevel's ends, ``d1`` along the
    first line and ``d2`` along the second, both the corner when the two
    distances are 0 -- or "parallel" / "too large"."""
    base = sided_fillet(s1, pick1, s2, pick2, 0.0)
    if isinstance(base, str):
        return base
    corner, _t1, _t2, _c, far1, far2, _sw = base

    def towards(far, distance):
        length = math.dist(corner, far)
        if distance > length + EPS:
            return None
        if length < EPS:
            return corner
        return (corner[0] + (far[0] - corner[0]) * distance / length,
                corner[1] + (far[1] - corner[1]) * distance / length)

    c1, c2 = towards(far1, d1), towards(far2, d2)
    if c1 is None or c2 is None:
        return "too large"
    return corner, c1, c2, far1, far2


def chamfer_angle_distance(s1: Seg, pick1: Point, s2: Seg, pick2: Point,
                           length: float, angle_deg: float):
    """The second distance of an Angle-method chamfer: the bevel leaves
    the first line ``length`` from the corner at ``angle_deg`` to it.
    None when that line never meets the second."""
    base = sided_fillet(s1, pick1, s2, pick2, 0.0)
    if isinstance(base, str):
        return None
    corner, _t1, _t2, _c, far1, far2, _sw = base
    u1 = (far1[0] - corner[0], far1[1] - corner[1])
    u2 = (far2[0] - corner[0], far2[1] - corner[1])
    phi = math.acos(max(-1.0, min(1.0, (u1[0] * u2[0] + u1[1] * u2[1])
                                  / (math.hypot(*u1) * math.hypot(*u2)))))
    alpha = math.radians(angle_deg)
    if phi + alpha >= math.pi - EPS or alpha <= 0:
        return None
    return length * math.sin(alpha) / math.sin(phi + alpha)


def fillet_parallel(s1: Seg, pick1: Point, s2: Seg):
    """FILLET of two parallel lines: ``(new_s2, (center, r, a0, a1))``.

    AutoCAD's rule ("Fillet Parallel Lines"): the radius is temporarily
    half the distance between them, whatever it is set to; the semicircle
    goes at the end of the FIRST line nearest its pick, that line stays as
    it is, and the second is trimmed or extended to meet the arc. Returns
    None when the lines are not parallel or lie on one line.
    """
    dx, dy = s1[2] - s1[0], s1[3] - s1[1]
    ex, ey = s2[2] - s2[0], s2[3] - s2[1]
    l1, l2 = math.hypot(dx, dy), math.hypot(ex, ey)
    if l1 < EPS or l2 < EPS or abs(dx * ey - dy * ex) > 1e-9 * l1 * l2:
        return None
    ux, uy = dx / l1, dy / l1
    # the end of the first line nearest the pick, and the way out past it
    if math.hypot(pick1[0] - s1[2], pick1[1] - s1[3]) <= math.hypot(
            pick1[0] - s1[0], pick1[1] - s1[1]):
        end, ox, oy = (s1[2], s1[3]), ux, uy
    else:
        end, ox, oy = (s1[0], s1[1]), -ux, -uy
    # foot of that end on the second line
    t = (end[0] - s2[0]) * ux + (end[1] - s2[1]) * uy
    foot = (s2[0] + ux * t, s2[1] + uy * t)
    width = math.hypot(foot[0] - end[0], foot[1] - end[1])
    if width < EPS:
        return None
    center = ((end[0] + foot[0]) / 2, (end[1] + foot[1]) / 2)
    r = width / 2
    # keep the second line's end that lies back along the first line
    back = min(((s2[0], s2[1]), (s2[2], s2[3])),
               key=lambda p: (p[0] - foot[0]) * ox + (p[1] - foot[1]) * oy)
    new_s2 = (back[0], back[1], foot[0], foot[1])
    a_end = math.degrees(math.atan2(end[1] - center[1], end[0] - center[0]))
    a_foot = math.degrees(math.atan2(foot[1] - center[1], foot[0] - center[0]))
    a_out = math.degrees(math.atan2(oy, ox))
    # counterclockwise from a0 to a1 must pass through the outward side
    a0, a1 = a_end, a_foot
    if (a_out - a0) % 360.0 > (a1 - a0) % 360.0:
        a0, a1 = a1, a0
    return new_s2, (center, r, a0 % 360.0, a1 % 360.0)


def tangent_points_from(circle, point: Point) -> list[Point]:
    """Where the tangent lines from ``point`` touch ``circle`` (cx, cy, r):
    two points, or none from inside it."""
    cx, cy, r = circle
    dx, dy = point[0] - cx, point[1] - cy
    d = math.hypot(dx, dy)
    if d <= r + EPS:
        return []
    base = math.atan2(dy, dx)
    spread = math.acos(r / d)
    return [(cx + r * math.cos(base + s * spread),
             cy + r * math.sin(base + s * spread)) for s in (1.0, -1.0)]


def common_tangents(c1, c2) -> list[tuple[Point, Point]]:
    """The lines tangent to two circles, as their two touch points: up to
    four (two outer, two crossing between them)."""
    x1, y1, r1 = c1
    x2, y2, r2 = c2
    dx, dy = x2 - x1, y2 - y1
    d = math.hypot(dx, dy)
    if d < EPS:
        return []
    ux, uy = dx / d, dy / d
    out = []
    for k in (1.0, -1.0):              # 1: outer tangents, -1: crossing
        c = (r1 - k * r2) / d
        if c * c > 1.0:
            continue
        h = math.sqrt(max(0.0, 1.0 - c * c))
        for s in (1.0, -1.0):
            nx, ny = ux * c - s * h * uy, uy * c + s * h * ux
            out.append(((x1 + r1 * nx, y1 + r1 * ny),
                        (x2 + k * r2 * nx, y2 + k * r2 * ny)))
    return out


def trim_line_to(seg: Seg, point: Point, pick: Point) -> Seg:
    """FILLET's cut of a line at ``point`` (on its infinite line): keep the
    part on the pick's side, extending the line when the point is past
    its end."""
    ends = ((seg[0], seg[1]), (seg[2], seg[3]))
    toward = (pick[0] - point[0], pick[1] - point[1])

    def along(p):
        return (p[0] - point[0]) * toward[0] + (p[1] - point[1]) * toward[1]

    kept = max(ends, key=along)
    return (kept[0], kept[1], point[0], point[1])


def trim_arc_to(center: Point, a0: float, a1: float, point: Point,
                pick: Point) -> tuple[float, float]:
    """FILLET's cut of an arc (ccw ``a0``..``a1``, degrees) at ``point`` on
    its circle: ``(new_a0, new_a1)``. Inside the arc, keep the piece the
    pick is on; outside, extend the nearer end to the point."""
    at = math.degrees(math.atan2(point[1] - center[1], point[0] - center[0]))
    span = (a1 - a0) % 360.0 or 360.0
    if (at - a0) % 360.0 <= span:
        picked = math.degrees(math.atan2(pick[1] - center[1],
                                         pick[0] - center[0]))
        if (picked - a0) % 360.0 <= (at - a0) % 360.0:
            return a0, at % 360.0
        return at % 360.0, a1
    # past an end: grow the end the point is nearer to
    if (a0 - at) % 360.0 <= (at - a1) % 360.0:
        return at % 360.0, a1
    return a0, at % 360.0


def arc_between(center: Point, p: Point, q: Point) -> tuple[float, float]:
    """The ccw angles of the shorter arc of a circle from ``p`` to ``q``."""
    a = math.degrees(math.atan2(p[1] - center[1], p[0] - center[0]))
    b = math.degrees(math.atan2(q[1] - center[1], q[0] - center[0]))
    if (b - a) % 360.0 > 180.0:
        a, b = b, a
    return a % 360.0, b % 360.0


def fillet_polyline(rows, closed: bool, radius: float):
    """FILLET Polyline: ``(new_rows, filleted, too_short)``.

    ``rows`` are xyseb vertices. Every vertex where two straight segments
    meet gets an arc of ``radius`` (a new vertex pair, the first carrying
    the bulge); a corner whose segments are too short for it is counted and
    left alone, as AutoCAD reports "n were too short".
    """
    rows = [tuple(r) for r in rows]
    n = len(rows)
    if n < 3 or radius <= 0:
        return rows, 0, 0
    corners = range(n) if closed else range(1, n - 1)
    lengths = []
    for i in range(n if closed else n - 1):
        a, b = rows[i], rows[(i + 1) % n]
        lengths.append(math.hypot(b[0] - a[0], b[1] - a[1]))
    # length already taken from each segment's start and end by its corners
    used_start = [0.0] * len(lengths)
    used_end = [0.0] * len(lengths)
    cuts = {}                          # vertex index -> (t_in, t_out, bulge)
    filleted = too_short = 0
    for i in corners:
        prev, nxt = (i - 1) % n, (i + 1) % n
        if rows[prev][4] or rows[i][4]:
            continue                   # an arc on either side: not two lines
        a, b, c = rows[prev], rows[i], rows[nxt]
        result = fillet_arc((a[0], a[1], b[0], b[1]),
                            (b[0], b[1], c[0], c[1]), radius)
        if result is None:
            continue                   # straight on: nothing to round
        center, _r, _a0, _a1, t1, t2 = result
        d_in = math.hypot(t1[0] - b[0], t1[1] - b[1])
        d_out = math.hypot(t2[0] - b[0], t2[1] - b[1])
        seg_in, seg_out = prev % len(lengths), i % len(lengths)
        if (d_in + used_start[seg_in] > lengths[seg_in] + EPS
                or d_out + used_end[seg_out] > lengths[seg_out] + EPS):
            too_short += 1
            continue
        used_end[seg_in] = d_in
        used_start[seg_out] = d_out
        v1 = (t1[0] - center[0], t1[1] - center[1])
        v2 = (t2[0] - center[0], t2[1] - center[1])
        sweep = math.atan2(v1[0] * v2[1] - v1[1] * v2[0],
                           v1[0] * v2[0] + v1[1] * v2[1])
        cuts[i] = (t1, t2, math.tan(sweep / 4.0))
        filleted += 1
    out = []
    for i, row in enumerate(rows):
        if i in cuts:
            t1, t2, bulge = cuts[i]
            out.append((t1[0], t1[1], row[2], row[3], bulge))
            out.append((t2[0], t2[1], row[2], row[3], 0.0))
        else:
            out.append(row)
    return out, filleted, too_short


def chamfer_polyline(rows, closed: bool, d1: float, d2: float):
    """CHAMFER Polyline: ``(new_rows, chamfered, too_short)`` -- every
    vertex where two straight segments meet is bevelled, ``d1`` back along
    the segment coming in and ``d2`` along the one going out ("Chamfers
    become new segments of the polyline"; segments too short are left and
    counted, CHAMFER p. 315)."""
    rows = [tuple(r) for r in rows]
    n = len(rows)
    if n < 3 or (d1 <= 0 and d2 <= 0):
        return rows, 0, 0
    corners = range(n) if closed else range(1, n - 1)
    lengths = [math.dist(rows[i][:2], rows[(i + 1) % n][:2])
               for i in range(n if closed else n - 1)]
    used_start = [0.0] * len(lengths)
    used_end = [0.0] * len(lengths)
    cuts = {}
    done = too_short = 0
    for i in corners:
        prev, nxt = (i - 1) % n, (i + 1) % n
        if rows[prev][4] or rows[i][4]:
            continue                   # an arc on either side: not two lines
        a, b, c = rows[prev][:2], rows[i][:2], rows[nxt][:2]
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if abs(cross) < EPS:
            continue                   # straight on: no corner
        seg_in, seg_out = prev % len(lengths), i % len(lengths)
        if (d1 + used_start[seg_in] > lengths[seg_in] + EPS
                or d2 + used_end[seg_out] > lengths[seg_out] + EPS):
            too_short += 1
            continue
        used_end[seg_in] = d1
        used_start[seg_out] = d2

        def at(p, q, distance):
            length = math.dist(p, q)
            return (p[0] + (q[0] - p[0]) * distance / length,
                    p[1] + (q[1] - p[1]) * distance / length)
        cuts[i] = (at(b, a, d1), at(b, c, d2))
        done += 1
    out = []
    for i, row in enumerate(rows):
        if i in cuts:
            c1, c2 = cuts[i]
            out.append((c1[0], c1[1], row[2], row[3], 0.0))
            out.append((c2[0], c2[1], row[2], row[3], 0.0))
        else:
            out.append(row)
    return out, done, too_short
