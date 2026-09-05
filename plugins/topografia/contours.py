# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Contour lines from a TIN, and the slope of its triangles. Pure.

Marching triangles: a level plane cuts each triangle in at most one
segment; the segments of a level are linked into open or closed chains.
The half-open convention (a vertex exactly ON the level counts as below)
keeps every cut consistent, so chains close where they should and two
levels can never cross -- unless smoothing moves them, which is why
smoothing is optional and off by default.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .tin import Tin

Point = tuple[float, float]


def _cross(p, q, level: float) -> Point:
    t = (level - p[2]) / (q[2] - p[2])
    return (p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]))


def contour_segments(tin: Tin, level: float) -> list[tuple[Point, Point]]:
    """One segment per triangle the level plane cuts."""
    out = []
    for a, b, c in tin.triangles:
        pa, pb, pc = tin.points[a], tin.points[b], tin.points[c]
        above = [p[2] > level for p in (pa, pb, pc)]
        n = sum(above)
        if n == 0 or n == 3:
            continue
        hits = []
        for p, q in ((pa, pb), (pb, pc), (pc, pa)):
            if (p[2] > level) != (q[2] > level):
                hits.append(_cross(p, q, level))
        if len(hits) == 2 and (abs(hits[0][0] - hits[1][0]) > 1e-12
                               or abs(hits[0][1] - hits[1][1]) > 1e-12):
            out.append((hits[0], hits[1]))
    return out


def _key(p: Point, tol: float) -> tuple[int, int]:
    return (round(p[0] / tol), round(p[1] / tol))


def link_segments(segments, tol: float = 1e-6) -> list[tuple[list[Point], bool]]:
    """Chains (points, closed) from unordered segments that share endpoints."""
    ends: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for i, (p, q) in enumerate(segments):
        ends.setdefault(_key(p, tol), []).append((i, 0))
        ends.setdefault(_key(q, tol), []).append((i, 1))
    used = [False] * len(segments)
    chains = []

    for i in range(len(segments)):
        if used[i]:
            continue
        used[i] = True
        forward = walk_from(i, 1, segments, ends, used, tol)
        backward = walk_from(i, 0, segments, ends, used, tol)
        points = list(reversed(backward)) + [segments[i][0], segments[i][1]] + forward
        closed = len(points) > 3 and _key(points[0], tol) == _key(points[-1], tol)
        if closed:
            points = points[:-1]
        chains.append((points, closed))
    return chains


def walk_from(i: int, end: int, segments, ends, used, tol) -> list[Point]:
    """Follow the chain that continues from end ``end`` of segment ``i``."""
    out: list[Point] = []
    p = segments[i][end]
    while True:
        nxt = [(j, k) for j, k in ends.get(_key(p, tol), []) if not used[j]]
        if not nxt:
            return out
        j, k = nxt[0]
        used[j] = True
        p = segments[j][1 - k]
        out.append(p)


def contour_levels(z_min: float, z_max: float, interval: float, base: float = 0.0) -> list[float]:
    if interval <= 0 or z_max <= z_min:
        return []
    # strictly inside (z_min, z_max): a level AT the minimum would trace the
    # rim of the surface, vertex to vertex, which is not a contour
    first = math.floor((z_min - base) / interval + 1e-9) + 1
    last = math.ceil((z_max - base) / interval - 1e-9) - 1
    return [base + k * interval for k in range(first, last + 1)]


@dataclass
class Contour:
    level: float
    points: list = field(default_factory=list)
    closed: bool = False
    major: bool = False

    def length(self) -> float:
        pts = self.points + ([self.points[0]] if self.closed else [])
        return sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(pts, pts[1:]))


def contours(tin: Tin, interval: float, major_every: int = 5,
             base: float = 0.0) -> list[Contour]:
    """Every contour of the surface at ``interval``; every ``major_every``-th
    level is major. Levels equal to a vertex elevation are handled by the
    half-open convention, never by nudging the data."""
    st = tin.stats()
    out = []
    for level in contour_levels(st["z_min"], st["z_max"], interval, base):
        k = round((level - base) / interval)
        major = major_every > 0 and k % major_every == 0
        for points, closed in link_segments(contour_segments(tin, level)):
            if len(points) >= 2:
                out.append(Contour(level, points, closed, major))
    return out


def smooth(points: list[Point], closed: bool, passes: int = 1) -> list[Point]:
    """Chaikin's corner cutting: each pass replaces every corner by two
    points at a quarter and three quarters of its edges."""
    pts = list(points)
    for _ in range(max(0, passes)):
        if len(pts) < 3:
            break
        out = []
        pairs = list(zip(pts, pts[1:] + ([pts[0]] if closed else [])))
        for p, q in pairs:
            out.append((0.75 * p[0] + 0.25 * q[0], 0.75 * p[1] + 0.25 * q[1]))
            out.append((0.25 * p[0] + 0.75 * q[0], 0.25 * p[1] + 0.75 * q[1]))
        if not closed:
            out = [pts[0]] + out + [pts[-1]]
        pts = out
    return pts


def positions_along(points: list[Point], closed: bool, spacing: float) -> list[tuple[float, float, float]]:
    """(x, y, angle°) every ``spacing`` along the chain, starting half a
    spacing in; a chain shorter than a spacing gets one at its middle."""
    pts = list(points) + ([points[0]] if closed else [])
    lengths = [math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(pts, pts[1:])]
    total = sum(lengths)
    if total <= 0:
        return []
    if total < spacing:
        targets = [total / 2.0]
    else:
        targets = []
        s = spacing / 2.0
        while s < total - 1e-9:
            targets.append(s)
            s += spacing
    out = []
    for target in targets:
        run = 0.0
        for (p, q), length in zip(zip(pts, pts[1:]), lengths):
            if run + length >= target and length > 0:
                t = (target - run) / length
                x, y = p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])
                out.append((x, y, math.degrees(math.atan2(q[1] - p[1], q[0] - p[0]))))
                break
            run += length
    return out


def nearest_on_chain(points: list[Point], closed: bool, q: Point) -> tuple[float, float, float]:
    """The point of the chain closest to ``q``, with the chain's angle there."""
    pts = list(points) + ([points[0]] if closed else [])
    best, best_d = None, math.inf
    for p, r in zip(pts, pts[1:]):
        dx, dy = r[0] - p[0], r[1] - p[1]
        length2 = dx * dx + dy * dy
        t = 0.0 if length2 < 1e-18 else max(0.0, min(1.0, ((q[0] - p[0]) * dx + (q[1] - p[1]) * dy) / length2))
        x, y = p[0] + t * dx, p[1] + t * dy
        d = math.hypot(q[0] - x, q[1] - y)
        if d < best_d:
            best_d, best = d, (x, y, math.degrees(math.atan2(dy, dx)))
    return best


# -- slopes ------------------------------------------------------------------------------

def triangle_slope(tin: Tin, t) -> float:
    """Slope of the triangle's plane, in percent."""
    a, b, c = (tin.points[i] for i in t)
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    if abs(nz) < 1e-12:
        return math.inf
    return math.hypot(nx / nz, ny / nz) * 100.0


def slope_class(slope: float, breaks) -> int:
    """How many breaks the slope reaches: 0 = below the first break. A
    slope a rounding hair under a break counts as reaching it (a 10 %
    plane came out 9.999999 % on 80 of 400 facets)."""
    return sum(1 for b in breaks if slope >= b - 1e-9)


def slope_label(index: int, breaks) -> str:
    breaks = list(breaks)
    if index == 0:
        return f"< {breaks[0]:g} %"
    if index >= len(breaks):
        return f"> {breaks[-1]:g} %"
    return f"{breaks[index - 1]:g} - {breaks[index]:g} %"
