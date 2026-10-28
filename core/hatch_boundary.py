# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Boundary detection for HATCH — AutoCAD's "Pick internal point".

Click inside an area and AutoCAD finds the surrounding boundary. The region
is traced from every curve in view by ``core.hatch_trace`` (lines, arcs and
polylines cut at their crossings; the smallest face around the point; what
lies inside it as islands). This module keeps the closed-object rule as the
fallback: the smallest closed object (polyline / circle / ellipse) that
contains the point is the outer boundary, closed objects nested inside it
are islands (holes) — the "Normal" island style.
"""
from __future__ import annotations

import math

from core import ocs

Point = tuple[float, float]


def boundary_polygon(entity, arc_segments: int = 72) -> list[Point] | None:
    """Closed point list for a boundary entity, or None if it isn't closed."""
    t = entity.dxftype()
    if t == "LWPOLYLINE":
        if not entity.closed:
            return None
        return ocs.points_wcs(
            entity, [(p[0], p[1]) for p in entity.get_points("xy")])
    if t == "POLYLINE":
        if not entity.is_closed or entity.get_mode() != "AcDb2dPolyline":
            return None
        return ocs.points_wcs(entity, [(v.dxf.location.x, v.dxf.location.y)
                                       for v in entity.vertices])
    if t == "CIRCLE":
        c, r = ocs.center_wcs(entity), entity.dxf.radius
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


def region_at_point(entities, point: Point, window=None):
    """Return (outer_polygon, [island_polygons]) for the region under ``point``.

    None if nothing encloses the point. The region is traced from every
    curve in the boundary set (``core.hatch_trace``: lines and arcs cut at
    their crossings, the smallest face around the point, whatever lies
    inside it as islands -- AutoCAD's BPOLY). ``window`` = (x0, y0, x1, y1)
    limits that set, like AutoCAD's current viewport. Should the tracer
    find nothing, the closed-object rule below still answers: the smallest
    closed object containing the point, the closed objects nested in it
    as islands.
    """
    from core.hatch_trace import trace_region

    entities = list(entities)
    try:
        traced = trace_region(entities, point, window)
    except Exception:
        traced = None
    if traced is not None:
        return traced
    return _closed_object_region(entities, point)


def _closed_object_region(entities, point: Point):
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


# -- arcs back from the traced chords (BOUNDARY, #83) -------------------------------

def _round_supports(entities):
    """(cx, cy, r, a0, sweep or None for a full circle, sagitta) of every
    circle, arc and curved polyline segment: where a traced loop may run
    along a curve. ``sagitta`` is how far the tracer's chords sit from it
    (core.hatch_trace flattens to the entity's size / CURVE_SAGITTA)."""
    from core.hatch_trace import CURVE_SAGITTA

    out = []
    for e in entities:
        if not e.is_alive:
            continue
        kind = e.dxftype()
        try:
            if kind == "CIRCLE":
                c, r = ocs.center_wcs(e), e.dxf.radius
                out.append((c.x, c.y, r, 0.0, None, 2 * r / CURVE_SAGITTA))
            elif kind == "ARC":
                c, r = ocs.center_wcs(e), e.dxf.radius
                a0, a1 = (math.radians(a) for a in ocs.angles_wcs(e))
                sweep = (a1 - a0) % math.tau or math.tau
                out.append((c.x, c.y, r, a0, sweep, 2 * r / CURVE_SAGITTA))
            elif kind in ("LWPOLYLINE", "POLYLINE"):
                from core import dimassoc

                pts, bulges, closed = dimassoc._polyline_vertices(e)
                if len(pts) < 2:
                    continue
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                size = max(max(xs) - min(xs), max(ys) - min(ys), 1e-9)
                n = len(pts)
                for i in range(n if closed else n - 1):
                    bulge = bulges[i] or 0.0
                    if abs(bulge) < 1e-12:
                        continue
                    cx, cy, r, start, sweep = dimassoc._bulge_arc(
                        pts[i], pts[(i + 1) % n], bulge)
                    a0 = start if sweep > 0 else start + sweep
                    out.append((cx, cy, r, a0 % math.tau, abs(sweep),
                                max(size, 2 * r) / CURVE_SAGITTA))
        except Exception:  # noqa: BLE001 - an odd entity is just not a curve
            continue
    return out


def _edge_support(p, q, supports, tol):
    """The support (cx, cy, r) the chord p->q was flattened from, or None.
    ``supports`` is the array _support_array made (vectorized: a room in a
    dense plan has hundreds of chords and of arcs nearby)."""
    import numpy as np

    if not len(supports):
        return None
    cx, cy, r, a0, sweep, sagitta = supports.T
    # ezdxf flattens arcs through cubic Béziers: the chord vertices sit up
    # to ~3e-4 r off the true circle
    reach = tol + BEZIER_SLACK * r
    mx, my = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
    ok = (np.abs(np.hypot(p[0] - cx, p[1] - cy) - r) <= reach) \
        & (np.abs(np.hypot(q[0] - cx, q[1] - cy) - r) <= reach)
    if not ok.any():
        return None
    inward = r - np.hypot(mx - cx, my - cy)
    ok &= (inward >= -reach) & (inward <= sagitta * 1.05 + reach)
    rel = (np.arctan2(my - cy, mx - cx) - a0) % math.tau
    ok &= np.isnan(sweep) | (rel <= np.nan_to_num(sweep) + 1e-9)
    hits = np.nonzero(ok)[0]
    if not len(hits):
        return None
    k = hits[0]
    return (float(cx[k]), float(cy[k]), float(r[k]))


def _support_array(supports):
    import numpy as np

    rows = [(cx, cy, r, a0, np.nan if sweep is None else sweep, sag)
            for cx, cy, r, a0, sweep, sag in supports]
    return np.asarray(rows, dtype=float).reshape(-1, 6)


#: How far ezdxf's Bézier flattening of an arc may stray from it, per radius.
BEZIER_SLACK = 5e-4


def _line_circle_near(a, b, circle, near):
    """Where the line through a, b meets the circle, nearest to ``near``."""
    cx, cy, r = circle
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return None
    ux, uy = dx / length, dy / length
    t0 = (cx - a[0]) * ux + (cy - a[1]) * uy
    fx, fy = a[0] + t0 * ux, a[1] + t0 * uy
    h2 = r * r - ((cx - fx) ** 2 + (cy - fy) ** 2)
    if h2 < -(BEZIER_SLACK * r) ** 2 * 4:
        return None
    h = math.sqrt(max(h2, 0.0))
    roots = [(fx - h * ux, fy - h * uy), (fx + h * ux, fy + h * uy)]
    return min(roots, key=lambda p: math.hypot(p[0] - near[0], p[1] - near[1]))


def _circle_circle_near(c1, c2, near):
    dx, dy = c2[0] - c1[0], c2[1] - c1[1]
    d = math.hypot(dx, dy)
    r1, r2 = c1[2], c2[2]
    if d == 0:
        return None
    m = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h = math.sqrt(max(r1 * r1 - m * m, 0.0))
    mx, my = c1[0] + m * dx / d, c1[1] + m * dy / d
    roots = [(mx + h * dy / d, my - h * dx / d), (mx - h * dy / d, my + h * dx / d)]
    return min(roots, key=lambda p: math.hypot(p[0] - near[0], p[1] - near[1]))


def _exact_junctions(loop, edge):
    """Move every vertex where a curve meets something onto both exactly:
    the tracer's cut points sit on chords, a hair inside the circle."""
    n = len(loop)
    out = list(loop)
    for i in range(n):
        before, after = edge[i - 1], edge[i]
        if before is None and after is None:
            continue
        if before is not None and after is not None:
            if before == after:
                continue
            p = _circle_circle_near(before, after, loop[i])
        else:
            circle = before if before is not None else after
            far = loop[(i + 1) % n] if after is None else loop[i - 1]
            p = _line_circle_near(loop[i], far, circle, loop[i])
        if p is not None and math.hypot(p[0] - loop[i][0], p[1] - loop[i][1]) \
                <= 4 * BEZIER_SLACK * max(c[2] for c in (before, after) if c):
            out[i] = p
    return out


def loop_with_bulges(loop: list[Point], entities, tol: float | None = None):
    """A traced loop as (x, y, bulge) vertices: the runs of chords that came
    from one circle become one curved segment, as AutoCAD's BOUNDARY makes
    them. Straight runs stay as they are."""
    n = len(loop)
    if n < 3:
        return [(x, y, 0.0) for x, y in loop]
    if tol is None:
        xs, ys = [p[0] for p in loop], [p[1] for p in loop]
        tol = max(max(xs) - min(xs), max(ys) - min(ys), 1e-6) * 1e-7
    supports = _support_array(_round_supports(entities))
    if not len(supports):
        return [(x, y, 0.0) for x, y in loop]
    edge = [_edge_support(loop[i], loop[(i + 1) % n], supports, tol)
            for i in range(n)]
    loop = _exact_junctions(loop, edge)

    def same(a, b):
        return a is not None and b is not None and all(
            abs(u - v) <= tol + 1e-9 * abs(u) for u, v in zip(a, b))

    # start the walk where a run begins, so no run wraps past index 0
    start = 0
    if all(same(edge[i], edge[0]) for i in range(n)):
        start = 0
    else:
        for i in range(n):
            if not same(edge[i], edge[i - 1]):
                start = i
                break
    order = [(start + k) % n for k in range(n)]
    out = []
    k = 0
    while k < n:
        i = order[k]
        support = edge[i]
        if support is None:
            out.append((loop[i][0], loop[i][1], 0.0))
            k += 1
            continue
        run = [i]
        while k + len(run) < n and same(edge[order[k + len(run)]], support):
            run.append(order[k + len(run)])
        cx, cy, _r = support
        sweep = 0.0
        for j in run:
            a, b = loop[j], loop[(j + 1) % n]
            da = math.atan2(b[1] - cy, b[0] - cx) - math.atan2(a[1] - cy, a[0] - cx)
            sweep += (da + math.pi) % math.tau - math.pi
        # the exact sweep between the run's (exact) ends, on the side the
        # chords went
        a, b = loop[run[0]], loop[(run[-1] + 1) % n]
        exact = math.atan2(b[1] - cy, b[0] - cx) - math.atan2(a[1] - cy, a[0] - cx)
        sweep += (exact - sweep + math.pi) % math.tau - math.pi
        if len(run) == n:
            # the whole loop on one circle: two exact half circles (one
            # bulge spans less than 360°), turning the way the chords did
            r = support[2]
            angle = math.atan2(loop[0][1] - cy, loop[0][0] - cx)
            turn = 1.0 if sweep > 0 else -1.0
            return [(cx + r * math.cos(angle), cy + r * math.sin(angle), turn),
                    (cx - r * math.cos(angle), cy - r * math.sin(angle), turn)]
        p0 = loop[i]
        out.append((p0[0], p0[1], math.tan(sweep / 4.0)))
        k += len(run)
    return out
