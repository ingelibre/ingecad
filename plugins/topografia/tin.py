# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The triangulated irregular network (TIN): a Delaunay triangulation of
surveyed points, with breaklines, a boundary and a longest-edge filter.

Written here instead of pulling scipy in: the plan's own threshold was
"scipy if it adds under 25 % to the Flatpak", and it adds about 30 %.
Bowyer-Watson insertion, points visited in a grid-snake order so each
walk to the containing triangle is short, a cavity search over the
neighbour graph, and breaklines forced in by edge flips (Sloan 1993).
Coordinates are shifted to the bounding-box centre before any predicate
is evaluated, so UTM millions never meet a squared length. Pure Python +
the standard library; measured at ~20 000 points in a couple of seconds.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Optional

from .geometry import contains as polygon_contains

Point = tuple[float, float]


# -- predicates --------------------------------------------------------------------

def orient(a, b, c) -> float:
    """> 0 when a, b, c turn counter-clockwise."""
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def in_circle(a, b, c, d) -> bool:
    """Is ``d`` strictly inside the circumcircle of the CCW triangle abc?

    A relative tolerance keeps cocircular points (a regular grid, which a
    DEM sample always is) from flipping back and forth: a point on the
    circle is "not inside", consistently.
    """
    adx, ady = a[0] - d[0], a[1] - d[1]
    bdx, bdy = b[0] - d[0], b[1] - d[1]
    cdx, cdy = c[0] - d[0], c[1] - d[1]
    ad = adx * adx + ady * ady
    bd = bdx * bdx + bdy * bdy
    cd = cdx * cdx + cdy * cdy
    det = (adx * (bdy * cd - bd * cdy)
           - ady * (bdx * cd - bd * cdx)
           + ad * (bdx * cdy - bdy * cdx))
    scale = max(ad, bd, cd)
    return det > 1e-10 * scale * scale


def _segments_cross(p1, p2, q1, q2) -> bool:
    """Proper crossing of two segments (no shared endpoints, no touching)."""
    d1, d2 = orient(q1, q2, p1), orient(q1, q2, p2)
    d3, d4 = orient(p1, p2, q1), orient(p1, p2, q2)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) \
        and d1 != 0 and d2 != 0 and d3 != 0 and d4 != 0


# -- the triangulation --------------------------------------------------------------

class Delaunay:
    """Incremental Delaunay triangulation of 2D points (indices into ``pts``).

    Triangles are index triples, counter-clockwise; ``nbr[t][i]`` is the
    triangle across the edge opposite vertex ``i`` of ``t`` (that edge is
    ``(tri[t][i+1], tri[t][i+2])``), or -1 on the outside.
    """

    def __init__(self, points: list[Point]) -> None:
        n = len(points)
        if n < 3:
            raise ValueError("a triangulation needs at least three points")
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
        size = max(max(xs) - min(xs), max(ys) - min(ys), 1e-9)
        self.shift = (cx, cy)
        self.pts: list[Point] = [(x - cx, y - cy) for x, y in points]
        # the super triangle, far enough that it never shapes the hull
        big = size * 1000.0
        self.pts += [(-big, -big), (big, -big), (0.0, big)]
        self.n = n
        self.tri: list[list[int]] = [[n, n + 1, n + 2]]
        self.nbr: list[list[int]] = [[-1, -1, -1]]
        self.alive: list[bool] = [True]
        self._last = 0
        for index in self._insertion_order():
            self._insert(index)

    # -- construction --------------------------------------------------------------
    def _insertion_order(self) -> list[int]:
        """A grid snake: consecutive points are near each other, so the
        walk from the last triangle is a few steps, not a few hundred."""
        n = self.n
        if n <= 64:
            return list(range(n))
        cells = max(1, int(math.sqrt(n / 4.0)))
        xs = [p[0] for p in self.pts[:n]]
        ys = [p[1] for p in self.pts[:n]]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        w = (x1 - x0) or 1.0
        h = (y1 - y0) or 1.0

        def key(i: int):
            row = min(cells - 1, int((self.pts[i][1] - y0) / h * cells))
            col = min(cells - 1, int((self.pts[i][0] - x0) / w * cells))
            return (row, col if row % 2 == 0 else cells - 1 - col, self.pts[i][0])
        return sorted(range(n), key=key)

    def _locate(self, p: Point) -> int:
        """The alive triangle containing ``p``, by walking from the last."""
        t = self._last
        if not self.alive[t]:
            t = next(i for i in range(len(self.tri) - 1, -1, -1) if self.alive[i])
        pts = self.pts
        for _ in range(len(self.tri) + 8):
            a, b, c = self.tri[t]
            pa, pb, pc = pts[a], pts[b], pts[c]
            if orient(pb, pc, p) < 0:
                nxt = self.nbr[t][0]
            elif orient(pc, pa, p) < 0:
                nxt = self.nbr[t][1]
            elif orient(pa, pb, p) < 0:
                nxt = self.nbr[t][2]
            else:
                return t
            if nxt < 0:
                break
            t = nxt
        # degenerate walk (should not happen inside the super triangle)
        for i in range(len(self.tri)):
            if self.alive[i] and self._inside(i, p):
                return i
        raise RuntimeError("point outside the triangulation")

    def _circle_holds(self, t: int, p: Point) -> bool:
        """Does triangle ``t``'s circumcircle hold ``p``?

        A triangle with one super-triangle vertex is treated as if that
        vertex were at infinity: its "circle" is the half-plane beyond its
        real edge. With a finite super triangle a very obtuse hull triangle
        has a circumcircle wide enough to reach the fake vertex, and the
        hull comes out one triangle short (measured: 2977 of 2980).
        """
        a, b, c = self.tri[t]
        n = self.n
        fake = (a >= n) + (b >= n) + (c >= n)
        if fake == 0:
            return in_circle(self.pts[a], self.pts[b], self.pts[c], p)
        if fake == 1:
            # rotate so the fake vertex is first: the real edge is (b, c)
            if b >= n:
                a, b, c = b, c, a
            elif c >= n:
                a, b, c = c, a, b
            return orient(self.pts[b], self.pts[c], p) > 0
        return in_circle(self.pts[a], self.pts[b], self.pts[c], p)

    def _inside(self, t: int, p: Point) -> bool:
        a, b, c = (self.pts[i] for i in self.tri[t])
        return orient(a, b, p) >= 0 and orient(b, c, p) >= 0 and orient(c, a, p) >= 0

    def _insert(self, ip: int) -> None:
        p = self.pts[ip]
        start = self._locate(p)
        # the cavity: every triangle whose circumcircle holds p
        cavity: set[int] = set()
        stack = [start]
        while stack:
            t = stack.pop()
            if t in cavity or t < 0 or not self.alive[t]:
                continue
            if t == start or self._circle_holds(t, p):
                cavity.add(t)
                stack.extend(self.nbr[t])
        # its boundary: edges whose other side is not in the cavity
        boundary: list[tuple[int, int, int]] = []          # (b, c, outer)
        for t in cavity:
            tri, nbr = self.tri[t], self.nbr[t]
            for i in range(3):
                outer = nbr[i]
                if outer not in cavity:
                    boundary.append((tri[(i + 1) % 3], tri[(i + 2) % 3], outer))
        for t in cavity:
            self.alive[t] = False
        pending: dict[tuple[int, int], tuple[int, int]] = {}
        first_new = len(self.tri)
        for b, c, outer in boundary:
            t = len(self.tri)
            self.tri.append([ip, b, c])
            self.nbr.append([outer, -1, -1])
            self.alive.append(True)
            if outer >= 0:
                # the slot of ``outer`` whose opposite edge IS (b, c): an
                # outer triangle may touch the cavity along two edges, and
                # "the first slot pointing into the cavity" picks the wrong one
                ot = self.tri[outer]
                on = self.nbr[outer]
                for i in range(3):
                    if ot[i] != b and ot[i] != c:
                        on[i] = t
                        break
            # edge opposite b is (c, ip); opposite c is (ip, b)
            for i, (x, y) in ((1, (c, ip)), (2, (ip, b))):
                key = (x, y) if x < y else (y, x)
                other = pending.pop(key, None)
                if other is None:
                    pending[key] = (t, i)
                else:
                    t2, i2 = other
                    self.nbr[t][i] = t2
                    self.nbr[t2][i2] = t
        self._last = first_new

    # -- results -------------------------------------------------------------------
    def triangles(self) -> list[tuple[int, int, int]]:
        """CCW index triples of the real points (super-triangle gone)."""
        n = self.n
        return [tuple(t) for t, ok in zip(self.tri, self.alive)
                if ok and t[0] < n and t[1] < n and t[2] < n]

    # -- breaklines: Sloan's edge flipping ----------------------------------------------
    def _edge_map(self) -> dict[tuple[int, int], list[int]]:
        out: dict[tuple[int, int], list[int]] = {}
        for t, ok in enumerate(self.alive):
            if not ok:
                continue
            a, b, c = self.tri[t]
            for x, y in ((a, b), (b, c), (c, a)):
                out.setdefault((x, y) if x < y else (y, x), []).append(t)
        return out

    def _flip(self, t1: int, t2: int) -> tuple[int, int, int, int]:
        """Replace the edge shared by t1 and t2 with the other diagonal.

        Returns ``(a, d, b, c)``: the new edge a-d, and the old edge b-c in
        t1's own counter-clockwise order -- the caller's edge map needs
        THAT order to know which owners changed, and a sorted key does not
        carry it (the first version updated the wrong pair and a later
        flip found two "neighbours" that were not).
        """
        tri1, tri2 = self.tri[t1], self.tri[t2]
        i1 = next(i for i in range(3) if self.nbr[t1][i] == t2)
        i2 = next(i for i in range(3) if self.nbr[t2][i] == t1)
        a = tri1[i1]                                  # apex of t1
        b, c = tri1[(i1 + 1) % 3], tri1[(i1 + 2) % 3]  # shared edge, CCW in t1
        d = tri2[i2]                                  # apex of t2; t2 = (d, c, b)
        n1, n2 = self.nbr[t1], self.nbr[t2]
        across_ca = n1[(i1 + 1) % 3]                  # opposite b in t1
        across_ab = n1[(i1 + 2) % 3]                  # opposite c in t1
        across_bd = n2[(i2 + 1) % 3]                  # opposite c in t2
        across_dc = n2[(i2 + 2) % 3]                  # opposite b in t2
        self.tri[t1] = [a, b, d]                      # opposite a: (b,d); b: (d,a); d: (a,b)
        self.nbr[t1] = [across_bd, t2, across_ab]
        self.tri[t2] = [a, d, c]                      # opposite a: (d,c); d: (c,a); c: (a,d)
        self.nbr[t2] = [across_dc, across_ca, t1]
        self._point(across_bd, (b, d), t1)            # used to point at t2
        self._point(across_ca, (c, a), t2)            # used to point at t1
        return (a, d, b, c)

    def _point(self, t: int, edge: tuple[int, int], to: int) -> None:
        """Make triangle ``t``'s slot across ``edge`` point at ``to``."""
        if t < 0:
            return
        tri = self.tri[t]
        for i in range(3):
            if tri[i] != edge[0] and tri[i] != edge[1]:
                self.nbr[t][i] = to
                return

    @staticmethod
    def _key(x: int, y: int) -> tuple[int, int]:
        return (x, y) if x < y else (y, x)

    def constrain(self, u: int, v: int, max_flips: int = 100000) -> bool:
        """Force the segment u-v to be an edge (Sloan 1993). True when it is."""
        if u == v:
            return True
        pu, pv = self.pts[u], self.pts[v]
        edges = self._edge_map()
        key = self._key(u, v)
        if key in edges:
            return True
        queue = [e for e in edges
                 if u not in e and v not in e and len(edges[e]) == 2
                 and _segments_cross(pu, pv, self.pts[e[0]], self.pts[e[1]])]
        flips = 0
        while queue and flips < max_flips:
            e = queue.pop(0)
            ts = edges.get(e)
            if ts is None or len(ts) != 2:
                continue
            t1, t2 = ts
            a = next(x for x in self.tri[t1] if x not in e)
            d = next(x for x in self.tri[t2] if x not in e)
            flips += 1
            if not _segments_cross(self.pts[a], self.pts[d], self.pts[e[0]], self.pts[e[1]]):
                queue.append(e)                       # not convex yet: later
                continue
            a, d, b, c = self._flip(t1, t2)
            new_edge = (a, d)
            # the map, exactly: (b,c) gone, (a,d) new, two edges change owner
            del edges[e]
            edges[self._key(*new_edge)] = [t1, t2]
            for ek, old, now in ((self._key(b, d), t2, t1), (self._key(c, a), t1, t2)):
                lst = edges.get(ek)
                if lst is not None:
                    edges[ek] = [now if t == old else t for t in lst]
            # keep every edge's owners consistent with the new triangles
            for ek in (self._key(a, b), self._key(d, c)):
                lst = edges.get(ek)
                if lst is not None:
                    edges[ek] = [t for t in lst if set(ek) <= set(self.tri[t])]
            nk = self._key(*new_edge)
            if nk != key and u not in nk and v not in nk and \
                    _segments_cross(pu, pv, self.pts[nk[0]], self.pts[nk[1]]):
                queue.append(nk)
        return key in self._edge_map()


# -- the surface --------------------------------------------------------------------------

@dataclass
class Tin:
    """Points with elevation and the CCW triangles over them."""

    points: list[tuple[float, float, float]]
    triangles: list[tuple[int, int, int]] = field(default_factory=list)
    name: str = "TERRENO"

    def edges(self) -> set[tuple[int, int]]:
        out = set()
        for a, b, c in self.triangles:
            for x, y in ((a, b), (b, c), (c, a)):
                out.add((x, y) if x < y else (y, x))
        return out

    def triangle_points(self, t):
        return tuple(self.points[i] for i in t)

    def z_at(self, x: float, y: float) -> Optional[float]:
        """Elevation of the surface at (x, y), or None outside it."""
        for a, b, c in self.triangles:
            pa, pb, pc = self.points[a], self.points[b], self.points[c]
            d1, d2, d3 = orient(pa, pb, (x, y)), orient(pb, pc, (x, y)), orient(pc, pa, (x, y))
            if d1 >= -1e-9 and d2 >= -1e-9 and d3 >= -1e-9:
                total = orient(pa, pb, pc)
                if abs(total) < 1e-12:
                    continue
                wa, wb, wc = d2 / total, d3 / total, d1 / total
                return wa * pa[2] + wb * pb[2] + wc * pc[2]
        return None

    def stats(self) -> dict:
        zs = [p[2] for p in self.points]
        area2d = area3d = 0.0
        longest = 0.0
        for a, b, c in self.triangles:
            pa, pb, pc = self.points[a], self.points[b], self.points[c]
            area2d += abs(orient(pa, pb, pc)) / 2.0
            ux, uy, uz = pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]
            vx, vy, vz = pc[0] - pa[0], pc[1] - pa[1], pc[2] - pa[2]
            cx, cy, cz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
            area3d += math.sqrt(cx * cx + cy * cy + cz * cz) / 2.0
            for p, q in ((pa, pb), (pb, pc), (pc, pa)):
                longest = max(longest, math.hypot(q[0] - p[0], q[1] - p[1]))
        counts: dict[tuple[int, int], int] = {}
        for a, b, c in self.triangles:
            for x, y in ((a, b), (b, c), (c, a)):
                k = (x, y) if x < y else (y, x)
                counts[k] = counts.get(k, 0) + 1
        return {
            "points": len(self.points), "triangles": len(self.triangles),
            "edges": len(counts), "boundary_edges": sum(1 for v in counts.values() if v == 1),
            "bad_edges": sum(1 for v in counts.values() if v > 2),
            "z_min": min(zs) if zs else 0.0, "z_max": max(zs) if zs else 0.0,
            "area_2d": area2d, "area_3d": area3d, "longest_edge": longest,
        }


def _dedupe(points, tol: float = 1e-6):
    """Distinct XY positions (the first Z wins), and the index each input
    point maps to -- a station often shoots the same corner twice."""
    out, index = [], []
    seen: dict[tuple[int, int], int] = {}
    for p in points:
        key = (round(p[0] / tol), round(p[1] / tol))
        i = seen.get(key)
        if i is None:
            i = len(out)
            seen[key] = i
            out.append((float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0))
        index.append(i)
    return out, index


def build_tin(points, breaklines: Iterable = (), boundary: Optional[list[Point]] = None,
              max_edge: Optional[float] = None, name: str = "TERRENO") -> Tin:
    """Delaunay over ``points`` (x, y[, z]); ``breaklines`` are polylines
    whose vertices join the point set and whose segments become edges;
    ``boundary`` drops triangles whose centre falls outside it; ``max_edge``
    drops the long slivers along the hull that a survey never means."""
    raw = [tuple(p) for p in points]
    constraints: list[tuple[int, int]] = []
    for line in breaklines:
        verts = [tuple(v) for v in line]
        start = len(raw)
        raw.extend((v[0], v[1], v[2] if len(v) > 2 else 0.0) for v in verts)
        for k in range(len(verts) - 1):
            constraints.append((start + k, start + k + 1))
    pts3, index = _dedupe(raw)
    tri = Delaunay([(p[0], p[1]) for p in pts3])
    for u, v in constraints:
        tri.constrain(index[u], index[v])
    triangles = tri.triangles()
    if boundary is not None:
        triangles = [t for t in triangles if polygon_contains(boundary, _centre(pts3, t))]
    if max_edge is not None and max_edge > 0:
        triangles = [t for t in triangles if _longest(pts3, t) <= max_edge]
    return Tin(pts3, triangles, name)


def _centre(pts, t) -> Point:
    return (sum(pts[i][0] for i in t) / 3.0, sum(pts[i][1] for i in t) / 3.0)


def _longest(pts, t) -> float:
    a, b, c = (pts[i] for i in t)
    return max(math.hypot(b[0] - a[0], b[1] - a[1]), math.hypot(c[0] - b[0], c[1] - b[1]),
               math.hypot(a[0] - c[0], a[1] - c[1]))


def convex_hull(points: list[Point]) -> list[Point]:
    """Andrew's monotone chain, for the tests' Euler count."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def half(seq):
        out: list[Point] = []
        for p in seq:
            while len(out) >= 2 and orient(out[-2], out[-1], p) <= 0:
                out.pop()
            out.append(p)
        return out
    lower, upper = half(pts), half(reversed(pts))
    return lower[:-1] + upper[:-1]
