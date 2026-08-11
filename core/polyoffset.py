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

What this does NOT do: clean up the self-intersections a large offset makes
on a tight concavity. AutoCAD trims those loops away. Offsets that big on
that shape are rare in a plan and the missing cleanup is visible rather than
silent, so it is left as a known limit rather than half-guessed.
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
    # bulge_to_arc gives the sweep counter-clockwise for a positive bulge.
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


def offset_polyline(rows, closed: bool, distance: float, pick: Point):
    """Offset a polyline toward ``pick``.

    Returns ``(rows, closed)`` for the new polyline, or None when nothing
    survives (an offset larger than the shape can absorb).
    """
    elements = elements_of(rows, closed)
    if not elements:
        return None
    signed = distance * side_sign(elements, pick)
    offset = [offset_element(e, signed) for e in elements]
    kept = [(source, moved) for source, moved in zip(elements, offset)
            if moved is not None]
    if not kept:
        return None
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
        trimmed.append(_retrim(element, start, end))

    out_rows = []
    for element in trimmed:
        start, _end = _element_endpoints(element)
        out_rows.append((start[0], start[1], 0.0, 0.0, _bulge_of(element)))
    if not closed:
        last = _element_endpoints(trimmed[-1])[1]
        out_rows.append((last[0], last[1], 0.0, 0.0, 0.0))
    if len(out_rows) < 2:
        return None
    return out_rows, closed
