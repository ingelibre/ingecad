# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Grading: a platform over the ground, its side slopes to daylight, the
design surface they make, and the exact volume between two surfaces.

The daylight line is found the way a grading crew stakes it: from points
along the platform's edge, march outward along the normal with the slope
(cut up, fill down, benches if asked) until the design meets the ground.
The volume between two TINs is exact: every design triangle is clipped
against every ground triangle it overlaps, the difference of two planes
is a plane, and its integral over a convex piece is area x value at the
centroid, split at the zero line into fill and cut.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional

from .geometry import Point, clip, oriented, signed_area
from .tin import Tin, build_tin, orient


# -- the platform's plane ----------------------------------------------------------------

def platform_plane(origin: Point, z0: float, slope_pct: float = 0.0,
                   azimuth: float = 0.0) -> Callable[[float, float], float]:
    """z(x, y) of a platform at ``z0`` on ``origin``, falling ``slope_pct``
    along ``azimuth`` (from north, clockwise); 0 makes it flat."""
    rad = math.radians(90.0 - azimuth)
    gx, gy = -slope_pct / 100.0 * math.cos(rad), -slope_pct / 100.0 * math.sin(rad)

    def z(x: float, y: float) -> float:
        return z0 + gx * (x - origin[0]) + gy * (y - origin[1])
    return z


# -- side slopes ---------------------------------------------------------------------------

@dataclass
class SlopeSpec:
    cut_hv: float = 1.0           # horizontal per vertical, going up
    fill_hv: float = 1.5          # going down
    bench_height: float = 0.0     # a bench every this much rise (0 = none)
    bench_width: float = 0.0


def slope_rise(distance: float, hv: float, spec: SlopeSpec) -> float:
    """Vertical change after ``distance`` outward on a slope of ``hv``,
    benches included (flat stretches every ``bench_height`` of rise)."""
    hv = max(hv, 1e-9)
    if spec.bench_height <= 0 or spec.bench_width <= 0:
        return distance / hv
    run_per_lift = spec.bench_height * hv
    period = run_per_lift + spec.bench_width
    lifts, rest = divmod(distance, period)
    return lifts * spec.bench_height + min(rest, run_per_lift) / hv


@dataclass
class DaylightPoint:
    x: float
    y: float
    z: float
    distance: float               # from the platform edge
    cut: bool                     # the ground was above the platform here
    edge_x: float
    edge_y: float
    edge_z: float


def _march(tin: Tin, edge: Point, z_edge: float, normal: Point, spec: SlopeSpec,
           step: float, max_distance: float) -> Optional[DaylightPoint]:
    zg0 = tin.z_at(*edge)
    if zg0 is None:
        return None
    cut = zg0 > z_edge
    hv = spec.cut_hv if cut else spec.fill_hv
    sign = 1.0 if cut else -1.0
    last_d, last_diff = 0.0, zg0 - z_edge
    if abs(last_diff) < 1e-9:
        return DaylightPoint(edge[0], edge[1], z_edge, 0.0, cut, edge[0], edge[1], z_edge)
    d = step
    while d <= max_distance + 1e-9:
        x, y = edge[0] + normal[0] * d, edge[1] + normal[1] * d
        zg = tin.z_at(x, y)
        if zg is None:
            return None
        zd = z_edge + sign * slope_rise(d, hv, spec)
        diff = zg - zd
        if diff == 0 or (diff > 0) != (last_diff > 0):
            t = last_diff / (last_diff - diff)
            dd = last_d + t * (d - last_d)
            xx, yy = edge[0] + normal[0] * dd, edge[1] + normal[1] * dd
            zz = z_edge + sign * slope_rise(dd, hv, spec)
            return DaylightPoint(xx, yy, zz, dd, cut, edge[0], edge[1], z_edge)
        last_d, last_diff = d, diff
        d += step
    return None


def edge_samples(polygon: list[Point], sample: float) -> list[tuple[Point, Point, int]]:
    """(point, outward normal, side index) every ``sample`` metres around
    the polygon, corners included, walking it counter-clockwise."""
    pts = oriented(polygon, clockwise=False)
    out = []
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length < 1e-9:
            continue
        ux, uy = dx / length, dy / length
        normal = (uy, -ux)                                        # outward for CCW
        prev = pts[i - 1]
        px, py = a[0] - prev[0], a[1] - prev[1]
        pl = math.hypot(px, py) or 1.0
        # the corner: the bisector of the two outward normals
        n_prev = (py / pl, -px / pl)
        bis = (normal[0] + n_prev[0], normal[1] + n_prev[1])
        bl = math.hypot(*bis)
        corner_normal = (bis[0] / bl, bis[1] / bl) if bl > 1e-9 else normal
        out.append((a, corner_normal, i))
        k = 1
        while k * sample < length - 1e-9:
            out.append(((a[0] + ux * k * sample, a[1] + uy * k * sample), normal, i))
            k += 1
    return out


def daylight_line(tin: Tin, polygon: list[Point], z_of: Callable[[float, float], float],
                  spec: SlopeSpec, sample: float = 1.0, step: float = 0.25,
                  max_distance: float = 100.0) -> list[Optional[DaylightPoint]]:
    """One daylight point per edge sample, in order around the platform;
    None where the slope never met the ground within ``max_distance``."""
    out = []
    for point, normal, _side in edge_samples(polygon, sample):
        out.append(_march(tin, point, z_of(*point), normal, spec, step, max_distance))
    return out


def hachures(daylight: list[Optional[DaylightPoint]], every: int = 1) -> list[tuple[Point, Point]]:
    """The slope lines a plan shows between the platform edge and the
    daylight: a long one then a short one (half way), alternating."""
    out = []
    for k, dp in enumerate(daylight[::every]):
        if dp is None or dp.distance <= 0:
            continue
        a = (dp.edge_x, dp.edge_y)
        b = (dp.x, dp.y)
        if k % 2 == 0:
            out.append((a, b))
        else:
            out.append((a, ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)))
    return out


def design_surface(polygon: list[Point], z_of: Callable[[float, float], float],
                   daylight: list[Optional[DaylightPoint]], name: str = "PLATAFORMA") -> Tin:
    """The platform and its slopes as a TIN: platform vertices at design
    elevation, daylight points at ground elevation, both loops as
    breaklines, clipped to the daylight loop."""
    plat = [(x, y, z_of(x, y)) for x, y in oriented(polygon, clockwise=False)]
    day = [(d.x, d.y, d.z) for d in daylight if d is not None]
    points = plat + day
    breaklines = [plat + [plat[0]]]
    if len(day) >= 3:
        breaklines.append(day + [day[0]])
    boundary = [(p[0], p[1]) for p in day] if len(day) >= 3 else [(p[0], p[1]) for p in plat]
    return build_tin(points, breaklines, boundary=boundary, name=name)


# -- the volume between two surfaces --------------------------------------------------------

def _plane(pa, pb, pc):
    """z = a x + b y + c through three points."""
    d = orient(pa, pb, pc)
    if abs(d) < 1e-12:
        return None
    a = ((pb[2] - pa[2]) * (pc[1] - pa[1]) - (pc[2] - pa[2]) * (pb[1] - pa[1])) / d
    b = ((pc[2] - pa[2]) * (pb[0] - pa[0]) - (pb[2] - pa[2]) * (pc[0] - pa[0])) / d
    c = pa[2] - a * pa[0] - b * pa[1]
    return a, b, c


def _bbox(tri):
    xs = [p[0] for p in tri]
    ys = [p[1] for p in tri]
    return min(xs), min(ys), max(xs), max(ys)


def _clip_convex(subject: list[Point], clipper: list[Point]) -> list[Point]:
    """Subject polygon clipped by a convex CCW clipper (Sutherland-Hodgman)."""
    out = list(subject)
    n = len(clipper)
    for i in range(n):
        a, b = clipper[i], clipper[(i + 1) % n]
        if len(out) < 3:
            return []
        out = clip(out, lambda q, a=a, b=b: orient(a, b, q))
    return out


def _integrate(poly: list[Point], da: float, db: float, dc: float) -> tuple[float, float]:
    """(fill, cut) of the linear difference d = da x + db y + dc over the
    convex polygon: positive d is fill (design above ground)."""
    if len(poly) < 3:
        return 0.0, 0.0
    pos = clip(poly, lambda q: da * q[0] + db * q[1] + dc)
    neg = clip(poly, lambda q: -(da * q[0] + db * q[1] + dc))
    fill = cut = 0.0
    for piece, sign in ((pos, 1.0), (neg, -1.0)):
        if len(piece) < 3:
            continue
        area = abs(signed_area(piece))
        if area < 1e-14:
            continue
        cx, cy = _centroid(piece)          # of the polygon, not of its vertices
        value = sign * (da * cx + db * cy + dc)
        if sign > 0:
            fill += area * value
        else:
            cut += area * value
    return fill, cut


def _centroid(poly: list[Point]) -> Point:
    a = signed_area(poly)
    if abs(a) < 1e-14:
        return (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))
    cx = cy = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        cross = x1 * y2 - x2 * y1
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    return (cx / (6.0 * a), cy / (6.0 * a))


def volume_between(ground: Tin, design: Tin) -> tuple[float, float]:
    """(cut, fill) between the surfaces over the design's footprint:
    exact for two TINs, by overlaying their triangles."""
    # Work in local coordinates: with UTM millions a plane's constant term
    # is z minus a gradient times 8 000 000, and the difference of two such
    # constants keeps a few digits of a volume that needs many (measured:
    # 1 918 m³ of fill on a pad that has 13).
    if not design.points:
        return 0.0, 0.0
    ox = min(p[0] for p in design.points)
    oy = min(p[1] for p in design.points)

    def local(p):
        return (p[0] - ox, p[1] - oy, p[2])

    ground_tris = []
    for t in ground.triangles:
        tri = [local(ground.points[i]) for i in t]
        if orient(tri[0], tri[1], tri[2]) < 0:
            tri = [tri[0], tri[2], tri[1]]
        plane = _plane(*tri)
        if plane is not None:
            ground_tris.append((tri, _bbox(tri), plane))
    cut = fill = 0.0
    for t in design.triangles:
        tri = [local(design.points[i]) for i in t]
        if orient(tri[0], tri[1], tri[2]) < 0:
            tri = [tri[0], tri[2], tri[1]]
        dplane = _plane(*tri)
        if dplane is None:
            continue
        x0, y0, x1, y1 = _bbox(tri)
        flat = [(p[0], p[1]) for p in tri]
        for gtri, (gx0, gy0, gx1, gy1), gplane in ground_tris:
            if gx0 > x1 or gx1 < x0 or gy0 > y1 or gy1 < y0:
                continue
            piece = _clip_convex(flat, [(p[0], p[1]) for p in gtri])
            if len(piece) < 3:
                continue
            da, db, dc = (dplane[0] - gplane[0], dplane[1] - gplane[1], dplane[2] - gplane[2])
            f, c = _integrate(piece, da, db, dc)
            fill += f
            cut += c
    # clipping leaves crumbs of 1e-12 either side of zero; a report must
    # never say "-0.0"
    return max(cut, 0.0), max(fill, 0.0)


def footprint_area(tin: Tin) -> float:
    return sum(abs(orient(*(tin.points[i] for i in t))) / 2.0 for t in tin.triangles)
