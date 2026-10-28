# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Offsetting a polyline — the one a lot boundary needs.

A polyline is a chain of straight spans and circular arcs (its bulges), and
offsetting it is not "move every vertex sideways": each element is offset on
its own, and then consecutive elements are trimmed or extended to where they
now meet. Vertices move a different amount at every corner, by exactly the
amount that keeps the sides parallel.

Arcs go concentric — same centre, radius plus or minus the distance
depending on which way they turn — so a curved frontage stays an arc instead
of turning into a chord chain.

A large offset on a tight shape crosses itself: an arc smaller than the
distance collapses, a short arc is trimmed past its own ends and turns into
a near-full circle, a narrow neck pinches. AutoCAD trims those loops away
and the shape simplifies as it shrinks (#58, Riccardo): the raw offset is
cut wherever it crosses itself, each piece is kept only if every point of
it stays at the full distance from the original, and the survivors are
stitched back into one polyline -- or several, when the offset splits the
shape into islands.
"""
from __future__ import annotations

import math

from core.editmath import (circle_circle_intersections, line_circle_intersections,
                           line_line_intersection)

Point = tuple[float, float]

# Below this an element is a rounding artefact rather than geometry.
_EPS = 1e-9


def elements_of(rows, closed: bool):
    """Split a polyline into its spans: ``("L", p0, p1)`` / ``("A", …)``.

    ``rows`` are the (x, y, start_width, end_width, bulge) tuples ezdxf
    gives for an LWPOLYLINE.
    """
    points = [(float(r[0]), float(r[1])) for r in rows]
    bulges = [float(r[4]) for r in rows]
    spans = list(range(len(points) - 1))
    if closed and len(points) > 2:
        spans.append(len(points) - 1)
    elements = []
    for i in spans:
        p0 = points[i]
        p1 = points[(i + 1) % len(points)]
        bulge = bulges[i]
        if math.dist(p0, p1) <= _EPS:
            continue
        if abs(bulge) <= _EPS:
            elements.append(("L", p0, p1))
        else:
            elements.append(_arc_element(p0, p1, bulge))
    return elements


def _arc_element(p0: Point, p1: Point, bulge: float):
    from ezdxf.math import bulge_to_arc

    center, a0, a1, radius = bulge_to_arc(p0, p1, bulge)
    # bulge_to_arc answers counter-clockwise, start to end, whatever the
    # bulge; a clockwise span (negative bulge) travels the other way, so its
    # start angle is the end one. Here a0 is always the angle of p0: an
    # element runs from a0 to a1, counter-clockwise when ``ccw``.
    if bulge < 0:
        a0, a1 = a1, a0
    return ("A", (center.x, center.y), radius, a0, a1, bulge > 0)


def _normal(p0: Point, p1: Point):
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    length = math.hypot(dx, dy)
    if length <= _EPS:
        return None
    return (-dy / length, dx / length)      # left of travel


def side_sign(elements, pick: Point) -> float:
    """+1 when the pick lies left of the chain, -1 when right.

    Decided on the element nearest the pick, which is the one the user was
    aiming at.
    """
    best = None
    for element in elements:
        if element[0] == "L":
            _k, p0, p1 = element
            t, point = _closest_on_segment(p0, p1, pick)
            distance = math.dist(pick, point)
            normal = _normal(p0, p1)
            if normal is None:
                continue
            sign = 1.0 if ((pick[0] - point[0]) * normal[0]
                           + (pick[1] - point[1]) * normal[1]) >= 0 else -1.0
        else:
            _k, center, radius, a0, a1, ccw = element
            distance = abs(math.dist(pick, center) - radius)
            outward = math.dist(pick, center) >= radius
            # Travelling counter-clockwise the centre is on the left, so
            # outward is right; clockwise it is the other way round.
            sign = (-1.0 if outward else 1.0) if ccw else (1.0 if outward
                                                           else -1.0)
        if best is None or distance < best[0]:
            best = (distance, sign)
    return best[1] if best else 1.0


def _closest_on_segment(p0: Point, p1: Point, point: Point):
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    length2 = dx * dx + dy * dy
    if length2 <= _EPS:
        return 0.0, p0
    t = max(0.0, min(1.0, ((point[0] - p0[0]) * dx
                           + (point[1] - p0[1]) * dy) / length2))
    return t, (p0[0] + t * dx, p0[1] + t * dy)


def offset_element(element, distance: float):
    """One element moved ``distance`` to its left (negative = right)."""
    if element[0] == "L":
        _k, p0, p1 = element
        normal = _normal(p0, p1)
        if normal is None:
            return None
        shift = (normal[0] * distance, normal[1] * distance)
        return ("L", (p0[0] + shift[0], p0[1] + shift[1]),
                (p1[0] + shift[0], p1[1] + shift[1]))
    _k, center, radius, a0, a1, ccw = element
    # Left of travel is toward the centre on a counter-clockwise arc.
    new_radius = radius - distance if ccw else radius + distance
    if new_radius <= _EPS:
        return None                 # the arc collapses through its centre
    return ("A", center, new_radius, a0, a1, ccw)


def _element_endpoints(element):
    if element[0] == "L":
        return element[1], element[2]
    _k, center, radius, a0, a1, _ccw = element
    return (_polar(center, radius, a0), _polar(center, radius, a1))


def _polar(center: Point, radius: float, angle: float) -> Point:
    return (center[0] + radius * math.cos(angle),
            center[1] + radius * math.sin(angle))


def _join_point(first, second, hint: Point):
    """Where two offset elements meet, nearest to the old corner."""
    candidates: list[Point] = []
    if first[0] == "L" and second[0] == "L":
        seg1 = (first[1][0], first[1][1], first[2][0], first[2][1])
        seg2 = (second[1][0], second[1][1], second[2][0], second[2][1])
        hit = line_line_intersection(seg1, seg2, infinite2=True)
        if hit is None:
            # Parallel: the ends already coincide (tangent continuation).
            return _element_endpoints(first)[1]
        # line_line_intersection clamps to seg1; take the infinite crossing.
        candidates.append(_infinite_line_cross(seg1, seg2) or hit[1])
    elif first[0] == "L" and second[0] == "A":
        seg = (first[1][0], first[1][1], first[2][0], first[2][1])
        for t in line_circle_intersections(seg, second[1], second[2]):
            candidates.append((seg[0] + t * (seg[2] - seg[0]),
                               seg[1] + t * (seg[3] - seg[1])))
    elif first[0] == "A" and second[0] == "L":
        seg = (second[1][0], second[1][1], second[2][0], second[2][1])
        for t in line_circle_intersections(seg, first[1], first[2]):
            candidates.append((seg[0] + t * (seg[2] - seg[0]),
                               seg[1] + t * (seg[3] - seg[1])))
    else:
        candidates.extend(circle_circle_intersections(
            first[1], first[2], second[1], second[2]))
    if not candidates:
        return None
    return min(candidates, key=lambda p: math.dist(p, hint))


def _infinite_line_cross(seg1, seg2):
    x1, y1, x2, y2 = seg1
    x3, y3, x4, y4 = seg2
    d1x, d1y = x2 - x1, y2 - y1
    d2x, d2y = x4 - x3, y4 - y3
    denominator = d1x * d2y - d1y * d2x
    if abs(denominator) <= _EPS:
        return None
    t = ((x3 - x1) * d2y - (y3 - y1) * d2x) / denominator
    return (x1 + t * d1x, y1 + t * d1y)


def _retrim(element, start: Point | None, end: Point | None):
    """Move an element's ends to the joins computed for it."""
    if element[0] == "L":
        _k, p0, p1 = element
        return ("L", start or p0, end or p1)
    _k, center, radius, a0, a1, ccw = element
    if start is not None:
        a0 = math.atan2(start[1] - center[1], start[0] - center[0])
    if end is not None:
        a1 = math.atan2(end[1] - center[1], end[0] - center[0])
    return ("A", center, radius, a0, a1, ccw)


def _bulge_of(element) -> float:
    if element[0] == "L":
        return 0.0
    _k, _center, _radius, a0, a1, ccw = element
    sweep = (a1 - a0) % math.tau if ccw else (a0 - a1) % math.tau
    bulge = math.tan(sweep / 4.0)
    return bulge if ccw else -bulge


def _sweep(element) -> float:
    _k, _c, _r, a0, a1, ccw = element
    return (a1 - a0) % math.tau if ccw else (a0 - a1) % math.tau


def _raw_offset(elements, closed: bool, signed: float):
    """Every element offset and trimmed to its neighbours, gaps closed with
    a line -- the raw offset, loops and all."""
    offset = [offset_element(e, signed) for e in elements]
    kept = [(source, moved) for source, moved in zip(elements, offset)
            if moved is not None]
    if not kept:
        return []
    sources = [s for s, _m in kept]
    moved = [m for _m, m in kept]

    # Where consecutive elements now meet. Index i is the join BEFORE
    # element i; the open ends keep their offset positions.
    joins: list[Point | None] = [None] * len(moved)
    pairs = list(range(1, len(moved)))
    if closed and len(moved) > 1:
        pairs.append(0)
    for i in pairs:
        previous = moved[i - 1]
        current = moved[i]
        hint = _element_endpoints(sources[i])[0]
        joins[i] = _join_point(previous, current, hint)

    trimmed = []
    for i, element in enumerate(moved):
        start = joins[i]
        end = joins[(i + 1) % len(moved)] if (i + 1 < len(moved) or closed) \
            else None
        piece = _retrim(element, start, end)
        if piece[0] == "A" and _sweep(piece) > _sweep(element) + math.pi / 2:
            # trimmed past its own ends: what is left is the chord, which
            # the distance test then throws away with the loop it makes
            a, b = _element_endpoints(piece)
            piece = ("L", a, b)
        trimmed.append(piece)

    # no join found (a collapsed arc between two parallel spans): bridge
    chain = []
    count = len(trimmed)
    for i, element in enumerate(trimmed):
        chain.append(element)
        if i + 1 < count or closed:
            end = _element_endpoints(element)[1]
            start = _element_endpoints(trimmed[(i + 1) % count])[0]
            if math.dist(end, start) > 1e-9 * (1.0 + abs(signed)):
                chain.append(("L", end, start))
    return [e for e in chain if _length(e) > _EPS]


# -- one element, by parameter s in [0, 1] -------------------------------------

def _length(element) -> float:
    if element[0] == "L":
        return math.dist(element[1], element[2])
    return element[2] * _sweep(element)


def _point_at(element, s: float) -> Point:
    if element[0] == "L":
        (x0, y0), (x1, y1) = element[1], element[2]
        return (x0 + s * (x1 - x0), y0 + s * (y1 - y0))
    _k, center, radius, a0, _a1, ccw = element
    angle = a0 + (s * _sweep(element) if ccw else -s * _sweep(element))
    return _polar(center, radius, angle)


def _param_on(element, point: Point) -> float | None:
    """``point``'s parameter on the element, or None when it lies off it."""
    if element[0] == "L":
        (x0, y0), (x1, y1) = element[1], element[2]
        dx, dy = x1 - x0, y1 - y0
        length2 = dx * dx + dy * dy
        if length2 <= _EPS:
            return None
        s = ((point[0] - x0) * dx + (point[1] - y0) * dy) / length2
        return s if -1e-9 <= s <= 1 + 1e-9 else None
    _k, center, _radius, a0, _a1, ccw = element
    angle = math.atan2(point[1] - center[1], point[0] - center[0])
    sweep = _sweep(element)
    along = (angle - a0) % math.tau if ccw else (a0 - angle) % math.tau
    if along > sweep + 1e-9:
        if math.tau - along < 1e-9:      # just before the start
            return 0.0
        return None
    return along / sweep if sweep > _EPS else None


def _sub(element, s0: float, s1: float):
    if element[0] == "L":
        return ("L", _point_at(element, s0), _point_at(element, s1))
    _k, center, radius, a0, _a1, ccw = element
    sweep = _sweep(element)
    sign = 1.0 if ccw else -1.0
    return ("A", center, radius, a0 + sign * s0 * sweep, a0 + sign * s1 * sweep, ccw)


def _crossings(e1, e2) -> list[tuple[float, float]]:
    """(s1, s2) where two elements cross."""
    points: list[Point] = []
    if e1[0] == "L" and e2[0] == "L":
        seg1 = (e1[1][0], e1[1][1], e1[2][0], e1[2][1])
        seg2 = (e2[1][0], e2[1][1], e2[2][0], e2[2][1])
        hit = _infinite_line_cross(seg1, seg2)
        if hit is not None:
            points.append(hit)
    elif e1[0] == "A" and e2[0] == "A":
        if math.dist(e1[1], e2[1]) > _EPS or abs(e1[2] - e2[2]) > _EPS:
            points.extend(circle_circle_intersections(e1[1], e1[2], e2[1], e2[2]))
    else:
        line, arc = (e1, e2) if e1[0] == "L" else (e2, e1)
        seg = (line[1][0], line[1][1], line[2][0], line[2][1])
        for t in line_circle_intersections(seg, arc[1], arc[2]):
            points.append((seg[0] + t * (seg[2] - seg[0]),
                           seg[1] + t * (seg[3] - seg[1])))
    found = []
    for point in points:
        s1, s2 = _param_on(e1, point), _param_on(e2, point)
        if s1 is not None and s2 is not None:
            found.append((min(max(s1, 0.0), 1.0), min(max(s2, 0.0), 1.0)))
    return found


def distance_to(point: Point, element) -> float:
    """Shortest distance from ``point`` to one element."""
    if element[0] == "L":
        _t, foot = _closest_on_segment(element[1], element[2], point)
        return math.dist(point, foot)
    if _param_on(element, point) is not None or math.dist(point, element[1]) <= _EPS:
        return abs(math.dist(point, element[1]) - element[2])
    a, b = _element_endpoints(element)
    return min(math.dist(point, a), math.dist(point, b))


def _box(element, grow: float = 0.0):
    """Axis-aligned box around an element (a whole circle for an arc)."""
    if element[0] == "L":
        (x0, y0), (x1, y1) = element[1], element[2]
        return (min(x0, x1) - grow, min(y0, y1) - grow,
                max(x0, x1) + grow, max(y0, y1) + grow)
    (cx, cy), r = element[1], element[2]
    return (cx - r - grow, cy - r - grow, cx + r + grow, cy + r + grow)


class _Grid:
    """Which elements' boxes reach a cell: the pairs and the nearby
    elements are looked up instead of tried against all (#58: a 2000-vertex
    contour took 7 s, every element against every other). An element whose
    box spans too many cells (a big arc) is kept apart and paired with all."""

    _MAX_CELLS = 1024

    def __init__(self, boxes, cell: float) -> None:
        self.cell = cell
        self.count = len(boxes)
        self.cells: dict[tuple[int, int], list[int]] = {}
        self.big: list[int] = []
        for index, (x0, y0, x1, y1) in enumerate(boxes):
            keys = self._keys(x0, y0, x1, y1)
            if keys is None:
                self.big.append(index)
                continue
            for key in keys:
                self.cells.setdefault(key, []).append(index)

    def _keys(self, x0, y0, x1, y1):
        c = self.cell
        i0, i1 = int(math.floor(x0 / c)), int(math.floor(x1 / c))
        j0, j1 = int(math.floor(y0 / c)), int(math.floor(y1 / c))
        if (i1 - i0 + 1) * (j1 - j0 + 1) > self._MAX_CELLS:
            return None
        return [(i, j) for i in range(i0, i1 + 1) for j in range(j0, j1 + 1)]

    def near(self, point) -> list[int]:
        found = self.cells.get((int(math.floor(point[0] / self.cell)),
                                int(math.floor(point[1] / self.cell))), [])
        return found + self.big if self.big else found

    def pairs(self):
        seen = set()
        for members in self.cells.values():
            for a in range(len(members)):
                for b in range(a + 1, len(members)):
                    i, j = members[a], members[b]
                    key = (i, j) if i < j else (j, i)
                    if key not in seen:
                        seen.add(key)
                        yield key
        for i in self.big:
            for j in range(self.count):
                if i == j:
                    continue
                key = (i, j) if i < j else (j, i)
                if key not in seen:
                    seen.add(key)
                    yield key


def _cell_size(boxes, floor: float) -> float:
    sizes = sorted(max(b[2] - b[0], b[3] - b[1]) for b in boxes)
    typical = sizes[len(sizes) // 2] if sizes else 1.0
    return max(typical, floor, 1e-6)


def _clean(raw, closed: bool, original, distance: float):
    """Cut the raw offset where it crosses itself, keep the pieces that stay
    ``distance`` from the original everywhere, stitch them back. Returns a
    list of (elements, closed)."""
    count = len(raw)
    tol = 1e-7 * (1.0 + distance)
    cuts: list[set] = [set() for _ in range(count)]
    raw_boxes = [_box(e) for e in raw]
    grid = _Grid(raw_boxes, _cell_size(raw_boxes, distance))
    for i, j in grid.pairs():
        a, b = raw_boxes[i], raw_boxes[j]
        if a[0] > b[2] + tol or b[0] > a[2] + tol or a[1] > b[3] + tol \
                or b[1] > a[3] + tol:
            continue
        neighbours = j == i + 1 or (closed and i == 0 and j == count - 1)
        for s1, s2 in _crossings(raw[i], raw[j]):
            if neighbours:
                # their shared end is no crossing
                shared = (j == i + 1 and s1 > 1 - 1e-7 and s2 < 1e-7) or \
                    (j != i + 1 and s1 < 1e-7 and s2 > 1 - 1e-7)
                if shared:
                    continue
            cuts[i].add(s1)
            cuts[j].add(s2)

    # the raw chain as sub-elements, each flagged when a crossing ends it
    pieces: list[tuple[object, bool]] = []
    for element, params in zip(raw, cuts):
        inner = sorted(p for p in params if 1e-9 < p < 1 - 1e-9)
        ends_cut = any(p >= 1 - 1e-9 for p in params)
        starts_cut = any(p <= 1e-9 for p in params)
        if starts_cut and pieces:
            last, _flag = pieces[-1]
            pieces[-1] = (last, True)
        bounds = [0.0] + inner + [1.0]
        for k in range(len(bounds) - 1):
            sub = _sub(element, bounds[k], bounds[k + 1])
            if _length(sub) > _EPS:
                pieces.append((sub, k < len(bounds) - 2))
        if ends_cut and pieces:
            last, _flag = pieces[-1]
            pieces[-1] = (last, True)
    if not pieces:
        return []
    if closed and any(cut for _p, cut in pieces):
        first_cut = next(i for i, (_p, cut) in enumerate(pieces) if cut)
        pieces = pieces[first_cut + 1:] + pieces[:first_cut + 1]

    slices, current = [], []
    for element, cut in pieces:
        current.append(element)
        if cut:
            slices.append(current)
            current = []
    if current:
        slices.append(current)

    # the original elements near a point: boxes grown by the distance
    grown = [_box(o, distance) for o in original]
    near_original = _Grid(grown, _cell_size(grown, distance))

    def valid(slice_) -> bool:
        for element in slice_:
            for s in (0.1, 0.3, 0.5, 0.7, 0.9):
                point = _point_at(element, s)
                for k in near_original.near(point):
                    if distance_to(point, original[k]) < distance - tol:
                        return False
        return True

    good = [sl for sl in slices if valid(sl)]
    if not any(cut for _p, cut in pieces):
        return [(good[0], closed)] if good else []

    # stitch: each slice continues with the one that starts where it ends
    joined = []
    remaining = list(good)
    near = tol * 10
    while remaining:
        chain = remaining.pop(0)
        start = _element_endpoints(chain[0])[0]
        grew = True
        while grew:
            end = _element_endpoints(chain[-1])[1]
            if closed and math.dist(start, end) <= near:
                break                         # the loop is back where it began
            grew = False
            for k, other in enumerate(remaining):
                if math.dist(end, _element_endpoints(other[0])[0]) <= near:
                    chain = chain + other
                    remaining.pop(k)
                    grew = True
                    break
        end = _element_endpoints(chain[-1])[1]
        is_loop = math.dist(start, end) <= near
        if closed and not is_loop:
            continue      # a stray piece (a collinear overlap) of a closed shape
        joined.append((chain, closed and is_loop))
    return joined


def _rows_of(chain, closed: bool):
    out_rows = []
    for element in chain:
        start, _end = _element_endpoints(element)
        out_rows.append((start[0], start[1], 0.0, 0.0, _bulge_of(element)))
    if not closed:
        last = _element_endpoints(chain[-1])[1]
        out_rows.append((last[0], last[1], 0.0, 0.0, 0.0))
    return out_rows


def offset_polylines(rows, closed: bool, distance: float, pick: Point):
    """Offset a polyline toward ``pick``: a list of ``(rows, closed)``, one
    per piece that survives -- empty when the shape cannot absorb it, more
    than one when the offset splits it, as AutoCAD's OFFSET does."""
    elements = elements_of(rows, closed)
    if not elements:
        return []
    signed = distance * side_sign(elements, pick)
    raw = _raw_offset(elements, closed, signed)
    if not raw:
        return []
    out = []
    for chain, is_closed in _clean(raw, closed, elements, abs(signed)):
        piece = _rows_of(chain, is_closed)
        if len(piece) >= 2:
            out.append((piece, is_closed))
    # the longest first: what a one-result caller takes
    out.sort(key=lambda r: -sum(math.dist(a[:2], b[:2])
                                for a, b in zip(r[0], r[0][1:])))
    return out


def offset_polyline(rows, closed: bool, distance: float, pick: Point):
    """The main piece of :func:`offset_polylines`, or None."""
    pieces = offset_polylines(rows, closed, distance, pick)
    return pieces[0] if pieces else None
