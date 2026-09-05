# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""An alignment (an axis drawn as a polyline) as chainage: stations every
N metres plus every vertex, each with its point and its normal. Pure.

Chainage is horizontal length along the axis, written the Peruvian way,
``0+020.00`` (kilometres + metres).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

Point = tuple[float, float]


@dataclass(frozen=True)
class Station:
    s: float                 # chainage, metres from the start
    x: float
    y: float
    angle: float             # tangent direction, degrees CCW from east
    vertex: bool = False     # a vertex of the axis, not a regular station

    @property
    def normal(self) -> Point:
        """Unit vector to the LEFT of the axis (the negative offset side)."""
        rad = math.radians(self.angle)
        return (-math.sin(rad), math.cos(rad))

    def offset_point(self, offset: float) -> Point:
        """The point ``offset`` metres to the right (+) or left (-)."""
        nx, ny = self.normal
        return (self.x - nx * offset, self.y - ny * offset)


def format_station(s: float, decimals: int = 2) -> str:
    km, m = divmod(round(s, decimals), 1000.0)
    return f"{int(km)}+{m:0{4 + decimals}.{decimals}f}"


def polyline_length(points: list[Point]) -> float:
    return sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(points, points[1:]))


def point_at(points: list[Point], s: float) -> Station:
    """The station ``s`` along the polyline (clamped to its ends)."""
    if len(points) < 2:
        raise ValueError("an alignment needs at least two points")
    run = 0.0
    for p, q in zip(points, points[1:]):
        length = math.hypot(q[0] - p[0], q[1] - p[1])
        if length <= 0:
            continue
        if run + length >= s - 1e-9:
            t = max(0.0, min(1.0, (s - run) / length))
            return Station(s, p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]),
                           math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])))
        run += length
    p, q = points[-2], points[-1]
    return Station(run, q[0], q[1], math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])))


def stations(points: list[Point], step: float, start: float = 0.0) -> list[Station]:
    """Every ``step`` from ``start``, plus every vertex and the end, in
    chainage order without duplicates."""
    total = polyline_length(points)
    if step <= 0:
        raise ValueError("the station step must be positive")
    wanted: dict[float, bool] = {}
    s = start
    while s <= total + 1e-9:
        wanted[round(s, 6)] = False
        s += step
    run = 0.0
    for p, q in zip(points, points[1:]):
        wanted[round(run, 6)] = True
        run += math.hypot(q[0] - p[0], q[1] - p[1])
    wanted[round(total, 6)] = True
    out = []
    for key in sorted(wanted):
        st = point_at(points, key)
        out.append(Station(key, st.x, st.y, st.angle, wanted[key]))
    return out


def station_of(points: list[Point], q: Point) -> float:
    """The chainage of the point of the axis nearest to ``q``."""
    best, best_d, run = 0.0, math.inf, 0.0
    for p, r in zip(points, points[1:]):
        dx, dy = r[0] - p[0], r[1] - p[1]
        length2 = dx * dx + dy * dy
        length = math.sqrt(length2)
        t = 0.0 if length2 < 1e-18 else max(0.0, min(1.0, ((q[0] - p[0]) * dx + (q[1] - p[1]) * dy) / length2))
        x, y = p[0] + t * dx, p[1] + t * dy
        d = math.hypot(q[0] - x, q[1] - y)
        if d < best_d:
            best_d, best = d, run + t * length
        run += length
    return best
