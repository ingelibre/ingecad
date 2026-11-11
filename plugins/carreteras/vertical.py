# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The vertical alignment (profil en long): grades between vertical
points of intersection (sommets), joined by parabolic curves of radius R
(raccordements paraboliques). Pure: chainage ``s`` and elevation ``z`` in
metres, no document.

At a sommet of chainage s, elevation z, between the grades p1 and p2
(m/m), a curve of radius R starts T before it and ends T after it::

    T = R |p2 - p1| / 2          tangent length
    f = T² / (2 R)               the flèche, sommet to curve
    z(x) = z0 + p1 x ± x² / 2R   x from the start of the curve,
                                 + in a sag (rentrant), - on a crest (saillant)
"""
from __future__ import annotations

import math
from dataclasses import dataclass

Point = tuple[float, float]


@dataclass(frozen=True)
class VerticalCurve:
    number: int
    s: float                     # the sommet
    z: float
    p1: float                    # grade in, m/m
    p2: float                    # grade out
    radius: float                # 0: an angle, no curve

    @property
    def crest(self) -> bool:
        """Saillant: the grade decreases."""
        return self.p2 < self.p1

    @property
    def tangent(self) -> float:
        return self.radius * abs(self.p2 - self.p1) / 2.0

    @property
    def flech(self) -> float:
        t = self.tangent
        return t * t / (2.0 * self.radius) if self.radius > 0 else 0.0

    @property
    def start(self) -> float:
        return self.s - self.tangent

    @property
    def end(self) -> float:
        return self.s + self.tangent

    @property
    def z_start(self) -> float:
        return self.z - self.p1 * self.tangent

    def z_at(self, s: float) -> float:
        x = s - self.start
        sign = -1.0 if self.crest else 1.0
        return self.z_start + self.p1 * x + sign * x * x / (2.0 * self.radius)

    def slope_at(self, s: float) -> float:
        sign = -1.0 if self.crest else 1.0
        return self.p1 + sign * (s - self.start) / self.radius

    @property
    def extremum(self) -> Point | None:
        """The high point of a crest or the low point of a sag, when it
        falls inside the curve (the grades change sign)."""
        if self.radius <= 0 or self.p1 * self.p2 >= 0:
            return None
        s = self.start + abs(self.p1) * self.radius
        return s, self.z_at(s)


class CurveOverlap(ValueError):
    """Two vertical curves need more than the grade between their sommets."""


class VerticalAlignment:
    """Sommets ``(s, z)`` in chainage order, and a radius at each interior
    one (0: a plain angle)."""

    def __init__(self, sommets, radii=None) -> None:
        pts = sorted((float(s), float(z)) for s, z in sommets)
        if len(pts) < 2:
            raise ValueError("a vertical alignment needs at least two points")
        for (s0, _z0), (s1, _z1) in zip(pts, pts[1:]):
            if s1 - s0 < 1e-9:
                raise ValueError(f"two sommets at the same chainage {s0:.3f}")
        self.sommets = pts
        n = len(pts) - 2
        radii = list(radii) if radii is not None else [0.0] * n
        if len(radii) != n:
            raise ValueError(f"{len(radii)} radii for {n} sommets")
        self.radii = [max(0.0, float(r)) for r in radii]
        self._curves = []
        grades = self.slopes()
        for i in range(n):
            s, z = pts[i + 1]
            self._curves.append(VerticalCurve(i + 1, s, z, grades[i], grades[i + 1], self.radii[i]))
        # the curves must fit on their grades
        for i, c in enumerate(self._curves):
            before = pts[i + 1][0] - pts[i][0]
            prev = self._curves[i - 1].tangent if i > 0 else 0.0
            if c.tangent + prev > before + 1e-9:
                raise CurveOverlap(f"S{c.number}: T = {c.tangent:.3f} m, with {prev:.3f} m before it, "
                                   f"> {before:.3f} m of grade")
        if self._curves:
            last = self._curves[-1]
            after = pts[-1][0] - pts[-2][0]
            if last.tangent > after + 1e-9:
                raise CurveOverlap(f"S{last.number}: T = {last.tangent:.3f} m > {after:.3f} m of grade")

    def slopes(self) -> list[float]:
        """Each grade, m/m."""
        return [(z1 - z0) / (s1 - s0) for (s0, z0), (s1, z1) in zip(self.sommets, self.sommets[1:])]

    def curves(self) -> list[VerticalCurve]:
        return list(self._curves)

    @property
    def start(self) -> float:
        return self.sommets[0][0]

    @property
    def end(self) -> float:
        return self.sommets[-1][0]

    def z_at(self, s: float) -> float | None:
        if s < self.start - 1e-9 or s > self.end + 1e-9:
            return None
        for c in self._curves:
            if c.radius > 0 and c.start - 1e-9 <= s <= c.end + 1e-9:
                return c.z_at(s)
        for (s0, z0), (s1, z1) in zip(self.sommets, self.sommets[1:]):
            if s0 - 1e-9 <= s <= s1 + 1e-9:
                return z0 + (s - s0) / (s1 - s0) * (z1 - z0)
        return self.sommets[-1][1]

    def sample(self, step: float = 1.0) -> list[Point]:
        """The line as (s, z) every ``step`` metres, plus every sommet off a
        curve and every curve's ends: what a polyline on the profile draws,
        within s²/8R of the parabola (0.1 mm at 1 m and R = 1000 m)."""
        keys = {self.start, self.end}
        for c in self._curves:
            if c.radius > 0:
                keys |= {c.start, c.end}
                n = max(2, int(math.ceil((c.end - c.start) / step)))
                keys |= {c.start + (c.end - c.start) * k / n for k in range(n + 1)}
            else:
                keys.add(c.s)
        return [(s, self.z_at(s)) for s in sorted(keys)]

    def encode(self) -> list[str]:
        return [f"V;{s:.6f};{z:.6f}" for s, z in self.sommets] + [f"R;{r:.6f}" for r in self.radii]

    @classmethod
    def decode(cls, items) -> "VerticalAlignment":
        pts, radii = [], []
        for text in items:
            parts = str(text).split(";")
            if parts[0] == "V":
                pts.append((float(parts[1]), float(parts[2])))
            elif parts[0] == "R":
                radii.append(float(parts[1]))
        return cls(pts, radii)
