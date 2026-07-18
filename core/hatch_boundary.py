# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Boundary detection for HATCH — AutoCAD's "Pick internal point".

Click inside an area and AutoCAD finds the surrounding boundary. We resolve
the common, robust case: the smallest closed object (polyline / circle /
ellipse) that contains the point becomes the outer boundary, and any closed
objects nested inside it become islands (holes) — exactly the "Normal" island
style. Boundaries built from unclosed crossing fragments are out of scope for
now (AutoCAD needs gap tolerance there too).
"""
from __future__ import annotations

import math

Point = tuple[float, float]


def boundary_polygon(entity, arc_segments: int = 72) -> list[Point] | None:
    """Closed point list for a boundary entity, or None if it isn't closed."""
    t = entity.dxftype()
    if t == "LWPOLYLINE":
        if not entity.closed:
            return None
        return [(p[0], p[1]) for p in entity.get_points("xy")]
    if t == "POLYLINE":
        if not entity.is_closed or entity.get_mode() != "AcDb2dPolyline":
            return None
        return [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
    if t == "CIRCLE":
        c, r = entity.dxf.center, entity.dxf.radius
        return [(c.x + r * math.cos(2 * math.pi * i / arc_segments),
                 c.y + r * math.sin(2 * math.pi * i / arc_segments))
                for i in range(arc_segments)]
    if t == "ELLIPSE":
        c = entity.dxf.center
        maj = entity.dxf.major_axis
        big = math.hypot(maj.x, maj.y)
        small = big * entity.dxf.ratio
        rot = math.atan2(maj.y, maj.x)
        pts = []
        for i in range(arc_segments):
            a = 2 * math.pi * i / arc_segments
            x, y = big * math.cos(a), small * math.sin(a)
            pts.append((c.x + x * math.cos(rot) - y * math.sin(rot),
                        c.y + x * math.sin(rot) + y * math.cos(rot)))
        return pts
    return None


def polygon_area(poly: list[Point]) -> float:
    a = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def point_in_polygon(poly: list[Point], pt: Point) -> bool:
    x, y = pt
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            xc = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < xc:
                inside = not inside
        j = i
    return inside


def region_at_point(entities, point: Point):
    """Return (outer_polygon, [island_polygons]) for the region under ``point``.

    None if no closed boundary contains the point. The outer boundary is the
    smallest closed object containing the point; islands are the closed
    objects nested inside it (which the point is NOT inside).
    """
    containing = []
    polys = []
    for e in entities:
        poly = boundary_polygon(e)
        if poly is None or len(poly) < 3:
            continue
        area = polygon_area(poly)
        polys.append((e, poly, area))
        if point_in_polygon(poly, point):
            containing.append((e, poly, area))
    if not containing:
        return None
    outer_e, outer_poly, outer_area = min(containing, key=lambda c: c[2])
    islands = []
    for e, poly, area in polys:
        if e is outer_e or area >= outer_area:
            continue
        cx = sum(p[0] for p in poly) / len(poly)
        cy = sum(p[1] for p in poly) / len(poly)
        if point_in_polygon(outer_poly, (cx, cy)) \
                and not point_in_polygon(poly, point):
            islands.append(poly)
    return outer_poly, islands
