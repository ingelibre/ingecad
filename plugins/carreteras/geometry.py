# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A road axis as exact geometry: straight tangents and circular arcs,
stationed by their true length. Pure: no document, no Qt.

The axis is an open polyline of ``(x, y, bulge)`` vertices, the way an
LWPOLYLINE stores it. Topography's alignment flattens arcs to a centimetre,
which is enough for a profile; a road's PC and PT stations are read off the
plan to the millimetre, so here an arc's length is ``R·θ`` exactly.

Curve elements (MTC, *Manual de Carreteras: Diseño Geométrico DG-2018*,
simple circular curve)::

    T  = R·tan(Δ/2)            tangent, PI to PC and PI to PT
    Lc = π·R·Δ/180             length of the curve
    E  = R·(1/cos(Δ/2) − 1)    external, PI to the middle of the curve
    M  = R·(1 − cos(Δ/2))      middle ordinate (flecha)
    C  = 2·R·sin(Δ/2)          long chord, PC to PT
"""
from __future__ import annotations

import math
from dataclasses import dataclass

Point = tuple[float, float]
Vertex = tuple[float, float, float]          # x, y, bulge to the next vertex

EPS = 1e-9


# -- segments --------------------------------------------------------------------

@dataclass(frozen=True)
class Segment:
    """One piece of the axis: a straight line (bulge 0) or a circular arc."""

    start: Point
    end: Point
    bulge: float = 0.0

    @property
    def is_arc(self) -> bool:
        return abs(self.bulge) > 1e-12

    @property
    def chord(self) -> float:
        return math.hypot(self.end[0] - self.start[0], self.end[1] - self.start[1])

    @property
    def theta(self) -> float:
        """Signed central angle in radians (positive = counterclockwise)."""
        return 4.0 * math.atan(self.bulge)

    @property
    def radius(self) -> float:
        b = abs(self.bulge)
        return self.chord * (1.0 + b * b) / (4.0 * b) if self.is_arc else math.inf

    @property
    def center(self) -> Point:
        c = self.chord
        ux, uy = (self.end[0] - self.start[0]) / c, (self.end[1] - self.start[1]) / c
        mx, my = (self.start[0] + self.end[0]) / 2.0, (self.start[1] + self.end[1]) / 2.0
        sagitta = abs(self.bulge) * c / 2.0
        d = math.copysign(self.radius - sagitta, self.bulge)
        return (mx - uy * d, my + ux * d)

    @property
    def length(self) -> float:
        return abs(self.theta) * self.radius if self.is_arc else self.chord

    @property
    def start_angle(self) -> float:
        """Direction of travel at the start, degrees CCW from east."""
        chord_angle = math.degrees(math.atan2(self.end[1] - self.start[1],
                                              self.end[0] - self.start[0]))
        return chord_angle - math.degrees(self.theta) / 2.0

    @property
    def end_angle(self) -> float:
        return self.start_angle + math.degrees(self.theta)

    def at(self, t: float) -> tuple[Point, float]:
        """(point, direction in degrees) ``t`` metres from the start."""
        t = max(0.0, min(self.length, t))
        if not self.is_arc:
            c = self.chord
            if c <= 0:
                return self.start, 0.0
            f = t / c
            return ((self.start[0] + f * (self.end[0] - self.start[0]),
                     self.start[1] + f * (self.end[1] - self.start[1])), self.start_angle)
        cx, cy = self.center
        phi = math.copysign(t / self.radius, self.bulge)
        dx, dy = self.start[0] - cx, self.start[1] - cy
        cos_p, sin_p = math.cos(phi), math.sin(phi)
        return ((cx + dx * cos_p - dy * sin_p, cy + dx * sin_p + dy * cos_p),
                self.start_angle + math.degrees(phi))


# -- the axis -------------------------------------------------------------------------

class Alignment:
    """An open chain of segments, stationed from ``start_station``."""

    def __init__(self, vertices, start_station: float = 0.0) -> None:
        verts = [(float(v[0]), float(v[1]), float(v[2]) if len(v) > 2 else 0.0)
                 for v in vertices]
        if len(verts) < 2:
            raise ValueError("an axis needs at least two vertices")
        self.vertices: list[Vertex] = verts
        self.start_station = float(start_station)
        self.segments = [Segment((a[0], a[1]), (b[0], b[1]), a[2])
                         for a, b in zip(verts, verts[1:])
                         if math.hypot(b[0] - a[0], b[1] - a[1]) > EPS]
        if not self.segments:
            raise ValueError("the axis has no length")
        self._runs = []
        run = 0.0
        for seg in self.segments:
            self._runs.append(run)
            run += seg.length
        self.length = run

    @property
    def end_station(self) -> float:
        return self.start_station + self.length

    def reversed(self, start_station: float | None = None) -> "Alignment":
        return Alignment(reverse_vertices(self.vertices),
                         self.start_station if start_station is None else start_station)

    def at(self, s: float) -> tuple[Point, float]:
        """(point, direction) at distance ``s`` from the start of the axis."""
        s = max(0.0, min(self.length, s))
        for seg, run in zip(reversed(self.segments), reversed(self._runs)):
            if s >= run - EPS:
                return seg.at(s - run)
        return self.segments[0].at(0.0)

    def at_station(self, station: float) -> tuple[Point, float]:
        return self.at(station - self.start_station)

    def segment_runs(self):
        """(segment, distance from the start to its first point)."""
        return list(zip(self.segments, self._runs))


def reverse_vertices(vertices) -> list[Vertex]:
    """The same polyline walked the other way: the order flips and every
    arc turns the other way round (its bulge changes sign)."""
    verts = list(vertices)
    out = []
    for i in range(len(verts) - 1, -1, -1):
        bulge = -verts[i - 1][2] if i > 0 else 0.0
        out.append((verts[i][0], verts[i][1], bulge))
    return out


# -- stations ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Tick:
    station: float
    point: Point
    angle: float               # direction of travel, degrees
    regular: bool              # a multiple of the interval (else start / end)
    km: bool = False           # a full kilometre


def station_ticks(alignment: Alignment, interval: float) -> list[Tick]:
    """Every multiple of ``interval`` along the axis, plus its start and its
    end when they fall between them; a multiple of 1000 m is a km tick."""
    if interval <= 0:
        raise ValueError("the station interval must be positive")
    s0, s1 = alignment.start_station, alignment.end_station
    ticks = []
    k = math.ceil((s0 - 1e-6) / interval)
    if abs(k * interval - s0) > 1e-6:
        point, angle = alignment.at(0.0)
        ticks.append(Tick(s0, point, angle, False))
    while k * interval <= s1 + 1e-6:
        station = k * interval
        point, angle = alignment.at_station(station)
        km = abs(station / 1000.0 - round(station / 1000.0)) < 1e-9
        ticks.append(Tick(station, point, angle, True, km))
        k += 1
    if abs(ticks[-1].station - s1) > 1e-6:
        point, angle = alignment.at(alignment.length)
        ticks.append(Tick(s1, point, angle, False))
    return ticks


# -- curve elements ------------------------------------------------------------------------

@dataclass(frozen=True)
class CurveElements:
    delta: float               # deflection, degrees
    radius: float

    @property
    def half(self) -> float:
        return math.radians(self.delta) / 2.0

    @property
    def tangent(self) -> float:
        return self.radius * math.tan(self.half)

    @property
    def length(self) -> float:
        return math.pi * self.radius * self.delta / 180.0

    @property
    def external(self) -> float:
        return self.radius * (1.0 / math.cos(self.half) - 1.0)

    @property
    def middle_ordinate(self) -> float:
        return self.radius * (1.0 - math.cos(self.half))

    @property
    def chord(self) -> float:
        return 2.0 * self.radius * math.sin(self.half)


@dataclass(frozen=True)
class PI:
    """A point of intersection of two tangents, with its curve if any."""

    number: int
    point: Point
    station: float
    curve: CurveElements | None = None
    left: bool = False                    # the axis turns left (Izq.)
    pc: Point | None = None
    pt: Point | None = None
    pc_station: float | None = None
    pt_station: float | None = None
    #: with clothoids: where the circle itself starts and ends (SC, CS);
    #: pc / pt are then the ends of the clothoids (TS, ST)
    sc: Point | None = None
    cs: Point | None = None
    sc_station: float | None = None
    cs_station: float | None = None

    @property
    def spiral(self) -> bool:
        return self.sc is not None


def _deflection(a_in: float, a_out: float) -> float:
    """Signed turn from one direction to the next, degrees, in (-180, 180]."""
    d = (a_out - a_in) % 360.0
    return d - 360.0 if d > 180.0 else d


def points_of_intersection(alignment: Alignment) -> list[PI]:
    """The PIs of the axis in stationing order: one per arc (where its two
    tangents meet) and one per corner between straight pieces. An axis
    with clothoids gives one PI per curve -- clothoid, arc, clothoid."""
    if isinstance(alignment, ElementAlignment) and any(e.is_spiral for e in alignment.elements):
        return _spiral_pis(alignment)
    out: list[PI] = []
    runs = alignment.segment_runs()
    for i, (seg, run) in enumerate(runs):
        if seg.is_arc:
            delta = abs(math.degrees(seg.theta))
            elements = CurveElements(delta, seg.radius)
            rad = math.radians(seg.start_angle)
            t = elements.tangent
            pi = (seg.start[0] + t * math.cos(rad), seg.start[1] + t * math.sin(rad))
            pc_station = alignment.start_station + run
            out.append(PI(len(out) + 1, pi, pc_station + t, elements, seg.bulge > 0,
                          seg.start, seg.end, pc_station, pc_station + seg.length))
        if i + 1 < len(runs):
            nxt = runs[i + 1][0]
            if not seg.is_arc and not nxt.is_arc:
                turn = _deflection(seg.end_angle, nxt.start_angle)
                if abs(turn) > 1e-7:
                    out.append(PI(len(out) + 1, seg.end,
                                  alignment.start_station + run + seg.length,
                                  None, turn > 0))
    return out


class TangentOverlap(ValueError):
    """Two curves need more tangent than the straight between their PIs."""

    def __init__(self, first: int, second: int, needed: float, available: float) -> None:
        where = f"PI-{first}" if first == second else f"PI-{first} and PI-{second}"
        super().__init__(f"{where}: T = {needed:.3f} m > {available:.3f} m")
        self.first, self.second = first, second
        self.needed, self.available = needed, available


def deflections(points) -> list[float]:
    """Signed deflection at each interior vertex of a chain of tangents."""
    out = []
    for a, b, c in zip(points, points[1:], points[2:]):
        a_in = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        a_out = math.degrees(math.atan2(c[1] - b[1], c[0] - b[0]))
        out.append(_deflection(a_in, a_out))
    return out


def fit_curves(points, radii) -> list[Vertex]:
    """The axis through a chain of tangents with a simple circular curve of
    radius ``radii[i]`` at each interior vertex (PI), as (x, y, bulge)
    vertices. A PI where the tangents are aligned, or whose radius is 0,
    keeps its corner. Raises :class:`TangentOverlap` when two curves would
    need more than the tangent between them, and ValueError on a PI that
    turns back on itself."""
    pts = [(float(p[0]), float(p[1])) for p in points]
    if len(pts) < 3:
        raise ValueError("a chain of tangents needs at least three vertices")
    turns = deflections(pts)
    if len(radii) != len(turns):
        raise ValueError(f"{len(radii)} radii for {len(turns)} PIs")
    tangents = []
    for i, (turn, r) in enumerate(zip(turns, radii)):
        if abs(abs(turn) - 180.0) < 1e-7:
            raise ValueError(f"PI-{i + 1} turns back on itself")
        if r < 0:
            raise ValueError(f"PI-{i + 1}: the radius must be positive")
        tangents.append(0.0 if abs(turn) < 1e-7 or r == 0
                        else CurveElements(abs(turn), r).tangent)
    for j in range(len(pts) - 1):
        length = math.hypot(pts[j + 1][0] - pts[j][0], pts[j + 1][1] - pts[j][1])
        before = tangents[j - 1] if j >= 1 else 0.0          # at vertex j
        after = tangents[j] if j < len(tangents) else 0.0     # at vertex j+1
        if before + after > length + 1e-9:
            if j == 0 or j == len(pts) - 2:
                # a curve longer than the first or last tangent: the axis
                # would start or end inside the curve
                which = j + 1 if j == 0 else j
                raise TangentOverlap(which, which, before + after, length)
            raise TangentOverlap(j, j + 1, before + after, length)
    out: list[Vertex] = []

    def push(x: float, y: float, bulge: float) -> None:
        if out and math.hypot(out[-1][0] - x, out[-1][1] - y) < 1e-9:
            out[-1] = (out[-1][0], out[-1][1], bulge)      # PT meets the next PC
        else:
            out.append((x, y, bulge))

    push(pts[0][0], pts[0][1], 0.0)
    for i, (turn, t) in enumerate(zip(turns, tangents)):
        a, b, c = pts[i], pts[i + 1], pts[i + 2]
        if t <= 0.0:
            push(b[0], b[1], 0.0)
            continue
        lin = math.hypot(b[0] - a[0], b[1] - a[1])
        lout = math.hypot(c[0] - b[0], c[1] - b[1])
        pc = (b[0] - (b[0] - a[0]) / lin * t, b[1] - (b[1] - a[1]) / lin * t)
        pt = (b[0] + (c[0] - b[0]) / lout * t, b[1] + (c[1] - b[1]) / lout * t)
        push(pc[0], pc[1], math.copysign(math.tan(math.radians(abs(turn)) / 4.0), turn))
        push(pt[0], pt[1], 0.0)
    push(pts[-1][0], pts[-1][1], 0.0)
    return out


def parse_station(text: str) -> float:
    """``1+250.50``, ``1+250,5`` or plain metres ``1250.5``."""
    raw = text.strip().replace(",", ".")
    if "+" in raw:
        km, _, m = raw.partition("+")
        km_v = float(km) if km.strip() else 0.0
        m_v = float(m)
        if m_v < 0 or km_v < 0:
            raise ValueError(text)
        return km_v * 1000.0 + m_v
    return float(raw)


# =========================================================================================
# Clothoids (raccordements progressifs) -- the French practice: ARP, ICTAAL and ICTAVRU
# introduce a circle by a clothoid, whose curvature grows linearly with its length,
# A^2 = R * L. Every element of such an axis -- straight, arc or clothoid -- is one thing:
# a curve whose signed curvature k varies linearly from k0 to k1 over its length.
# =========================================================================================

def _gauss_nodes(n: int = 8):
    """Gauss-Legendre nodes and weights on [0, 1]."""
    import numpy as np

    x, w = np.polynomial.legendre.leggauss(n)
    return [(float((xi + 1.0) / 2.0), float(wi / 2.0)) for xi, wi in zip(x, w)]


_GAUSS = None


@dataclass(frozen=True)
class Element:
    """A piece of axis of linear curvature: ``k0 == k1 == 0`` is a straight,
    ``k0 == k1 != 0`` an arc, anything else a clothoid. Curvature is signed
    (positive = turning left, counterclockwise); the start point and the
    direction there (degrees CCW from east) place it."""

    start: Point
    start_angle: float
    length: float
    k0: float = 0.0
    k1: float = 0.0

    # -- what it is ------------------------------------------------------------------
    @property
    def is_line(self) -> bool:
        return abs(self.k0) < 1e-15 and abs(self.k1) < 1e-15

    @property
    def is_arc(self) -> bool:
        return not self.is_line and abs(self.k1 - self.k0) < 1e-15

    @property
    def is_spiral(self) -> bool:
        return abs(self.k1 - self.k0) >= 1e-15

    @property
    def kind(self) -> str:
        return "line" if self.is_line else ("arc" if self.is_arc else "clothoid")

    @property
    def radius(self) -> float:
        """The arc's radius; for a clothoid the smaller of its two ends."""
        k = max(abs(self.k0), abs(self.k1))
        return 1.0 / k if k > 0 else math.inf

    @property
    def parameter(self) -> float:
        """A, with A^2 = L / |k1 - k0| (= R * L from a straight)."""
        dk = abs(self.k1 - self.k0)
        return math.sqrt(self.length / dk) if dk > 0 else math.inf

    @property
    def left(self) -> bool:
        return (self.k0 + self.k1) > 0

    @property
    def bulge(self) -> float:
        """What an LWPOLYLINE stores for it: exact for a straight or an arc."""
        if self.is_arc:
            return math.tan(self.k0 * self.length / 4.0)
        return 0.0

    @property
    def theta(self) -> float:
        """Total change of direction, radians, signed."""
        return (self.k0 + self.k1) / 2.0 * self.length

    @property
    def end_angle(self) -> float:
        return self.start_angle + math.degrees(self.theta)

    def heading(self, t: float) -> float:
        """Direction at ``t`` metres, radians."""
        return math.radians(self.start_angle) + self.k0 * t + (self.k1 - self.k0) * t * t / (2.0 * self.length)

    def at(self, t: float) -> tuple[Point, float]:
        """(point, direction in degrees) ``t`` metres from the start."""
        t = max(0.0, min(self.length, t))
        x0, y0 = self.start
        a0 = math.radians(self.start_angle)
        if self.is_line:
            return (x0 + t * math.cos(a0), y0 + t * math.sin(a0)), self.start_angle
        if self.is_arc:
            r = 1.0 / self.k0
            a = a0 + self.k0 * t
            return ((x0 + r * (math.sin(a) - math.sin(a0)),
                     y0 - r * (math.cos(a) - math.cos(a0))), math.degrees(a))
        global _GAUSS
        if _GAUSS is None:
            _GAUSS = _gauss_nodes(8)
        # heading is quadratic in t: Gauss-Legendre on pieces short enough that
        # the error stays far under a micrometre on any road clothoid
        pieces = max(1, int(math.ceil(t / 5.0)))
        h = t / pieces
        x, y = x0, y0
        for p in range(pieces):
            s0 = p * h
            for u, w in _GAUSS:
                ang = self.heading(s0 + u * h)
                x += w * h * math.cos(ang)
                y += w * h * math.sin(ang)
        return (x, y), math.degrees(self.heading(t))

    @property
    def end(self) -> Point:
        return self.at(self.length)[0]

    def reversed(self) -> "Element":
        """The same piece walked the other way."""
        point, angle = self.at(self.length)
        return Element(point, angle + 180.0, self.length, -self.k1, -self.k0)

    def encode(self) -> str:
        """One XDATA string, what the axis keeps to rebuild it exactly."""
        return (f"E;{self.start[0]:.6f};{self.start[1]:.6f};{self.start_angle:.12f};"
                f"{self.length:.6f};{self.k0:.15g};{self.k1:.15g}")

    @classmethod
    def decode(cls, text: str) -> "Element":
        parts = str(text).split(";")
        if len(parts) != 7 or parts[0] != "E":
            raise ValueError(f"not an axis element: {text!r}")
        return cls((float(parts[1]), float(parts[2])), float(parts[3]), float(parts[4]),
                   float(parts[5]), float(parts[6]))

    def polyline(self, sagitta: float = 0.002) -> list[Vertex]:
        """Vertices standing for it in an LWPOLYLINE, without the end
        vertex: one for a straight or an arc (exact), and for a clothoid
        enough chords that none strays more than ``sagitta`` from it."""
        if not self.is_spiral:
            return [(self.start[0], self.start[1], self.bulge)]
        kmax = max(abs(self.k0), abs(self.k1))
        step = math.sqrt(8.0 * sagitta / kmax) if kmax > 0 else self.length
        n = max(2, int(math.ceil(self.length / max(step, 1e-3))))
        out = []
        for i in range(n):
            (x, y), _ = self.at(self.length * i / n)
            out.append((x, y, 0.0))
        return out


def element_of_segment(seg: "Segment") -> Element:
    """A bulge segment as an Element (exact)."""
    if seg.is_arc:
        k = math.copysign(1.0 / seg.radius, seg.bulge)
        return Element(seg.start, seg.start_angle, seg.length, k, k)
    return Element(seg.start, seg.start_angle, seg.chord, 0.0, 0.0)


class ElementAlignment(Alignment):
    """An axis made of :class:`Element`s -- the one that can hold clothoids.
    Everything that reads an :class:`Alignment` reads it the same way."""

    def __init__(self, elements, start_station: float = 0.0) -> None:  # noqa: D107
        self.elements = [e for e in elements if e.length > EPS]
        if not self.elements:
            raise ValueError("the axis has no length")
        self.start_station = float(start_station)
        self.segments = self.elements
        self._runs = []
        run = 0.0
        for e in self.elements:
            self._runs.append(run)
            run += e.length
        self.length = run
        self.vertices = elements_polyline(self.elements)

    def reversed(self, start_station: float | None = None) -> "ElementAlignment":
        return ElementAlignment([e.reversed() for e in reversed(self.elements)],
                                self.start_station if start_station is None else start_station)


def elements_polyline(elements, sagitta: float = 0.002) -> list[Vertex]:
    """The LWPOLYLINE that draws the elements: arcs exact, clothoids by chords."""
    out: list[Vertex] = []
    for e in elements:
        out.extend(e.polyline(sagitta))
    end = elements[-1].end
    out.append((end[0], end[1], 0.0))
    return out


def as_elements(alignment: Alignment) -> list[Element]:
    if isinstance(alignment, ElementAlignment):
        return list(alignment.elements)
    return [element_of_segment(s) for s in alignment.segments]


# -- the symmetric clothoid - arc - clothoid at a PI ------------------------------------------

@dataclass(frozen=True)
class SpiralCurve:
    """The elements of a curve introduced and left by symmetric clothoids
    of length ``ls`` (``ls == 0``: a simple circle). Angles in degrees."""

    delta: float
    radius: float
    ls: float

    @property
    def theta_s(self) -> float:
        """Direction change along one clothoid, radians: L / 2R."""
        return self.ls / (2.0 * self.radius)

    @property
    def parameter(self) -> float:
        return math.sqrt(self.radius * self.ls) if self.ls > 0 else 0.0

    def _spiral_end(self) -> Point:
        if self.ls <= 0:
            return (0.0, 0.0)
        return Element((0.0, 0.0), 0.0, self.ls, 0.0, 1.0 / self.radius).end

    @property
    def shift(self) -> float:
        """p, the ripage: how far the circle moves inward."""
        xs, ys = self._spiral_end()
        return ys - self.radius * (1.0 - math.cos(self.theta_s)) if self.ls > 0 else 0.0

    @property
    def k(self) -> float:
        xs, _ys = self._spiral_end()
        return xs - self.radius * math.sin(self.theta_s) if self.ls > 0 else 0.0

    @property
    def tangent(self) -> float:
        """From the PI to the start of the first clothoid (and from the end
        of the second back to the PI)."""
        return (self.radius + self.shift) * math.tan(math.radians(self.delta) / 2.0) + self.k

    @property
    def arc_angle(self) -> float:
        """What the circle itself turns, degrees."""
        return self.delta - 2.0 * math.degrees(self.theta_s)

    @property
    def arc_length(self) -> float:
        return math.radians(self.arc_angle) * self.radius

    @property
    def length(self) -> float:
        return 2.0 * self.ls + self.arc_length

    @property
    def external(self) -> float:
        return (self.radius + self.shift) / math.cos(math.radians(self.delta) / 2.0) - self.radius


class SpiralTooLong(ValueError):
    """The two clothoids turn more than the PI does."""


def fit_spiral_curves(points, radii, spirals) -> list[Element]:
    """The axis through a chain of tangents, each PI turned by a circle of
    ``radii[i]`` between two symmetric clothoids of length ``spirals[i]``
    (0: a plain circle; radius 0: the corner is kept). Raises
    :class:`TangentOverlap` like :func:`fit_curves`, and
    :class:`SpiralTooLong` when 2 L / 2R exceeds the deflection."""
    pts = [(float(p[0]), float(p[1])) for p in points]
    if len(pts) < 3:
        raise ValueError("a chain of tangents needs at least three vertices")
    turns = deflections(pts)
    if not (len(radii) == len(spirals) == len(turns)):
        raise ValueError(f"{len(radii)} radii and {len(spirals)} clothoids for {len(turns)} PIs")
    curves: list[SpiralCurve | None] = []
    tangents = []
    for i, (turn, r, ls) in enumerate(zip(turns, radii, spirals)):
        if abs(abs(turn) - 180.0) < 1e-7:
            raise ValueError(f"PI-{i + 1} turns back on itself")
        if r < 0 or ls < 0:
            raise ValueError(f"PI-{i + 1}: radius and clothoid length must be positive")
        if abs(turn) < 1e-7 or r == 0:
            curves.append(None)
            tangents.append(0.0)
            continue
        curve = SpiralCurve(abs(turn), r, ls)
        if curve.arc_angle < -1e-9:
            raise SpiralTooLong(f"PI-{i + 1}: two clothoids of {ls:g} m turn "
                                f"{2 * math.degrees(curve.theta_s):.4f}° > {abs(turn):.4f}°")
        curves.append(curve)
        tangents.append(curve.tangent)
    for j in range(len(pts) - 1):
        length = math.hypot(pts[j + 1][0] - pts[j][0], pts[j + 1][1] - pts[j][1])
        before = tangents[j - 1] if j >= 1 else 0.0
        after = tangents[j] if j < len(tangents) else 0.0
        if before + after > length + 1e-9:
            if j == 0 or j == len(pts) - 2:
                which = j + 1 if j == 0 else j
                raise TangentOverlap(which, which, before + after, length)
            raise TangentOverlap(j, j + 1, before + after, length)

    elements: list[Element] = []
    cursor = pts[0]

    def straight_to(point):
        nonlocal cursor
        d = math.hypot(point[0] - cursor[0], point[1] - cursor[1])
        if d > 1e-9:
            ang = math.degrees(math.atan2(point[1] - cursor[1], point[0] - cursor[0]))
            elements.append(Element(cursor, ang, d))
        cursor = point

    for i, curve in enumerate(curves):
        a, b, c = pts[i], pts[i + 1], pts[i + 2]
        if curve is None:
            straight_to(b)
            continue
        lin = math.hypot(b[0] - a[0], b[1] - a[1])
        t = curve.tangent
        ts = (b[0] - (b[0] - a[0]) / lin * t, b[1] - (b[1] - a[1]) / lin * t)
        straight_to(ts)
        sign = 1.0 if turns[i] > 0 else -1.0
        k = sign / curve.radius
        ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        if curve.ls > 0:
            e = Element(cursor, ang, curve.ls, 0.0, k)
            elements.append(e)
            cursor, ang = e.at(e.length)
        if curve.arc_length > 1e-9:
            e = Element(cursor, ang, curve.arc_length, k, k)
            elements.append(e)
            cursor, ang = e.at(e.length)
        if curve.ls > 0:
            e = Element(cursor, ang, curve.ls, k, 0.0)
            elements.append(e)
            cursor, ang = e.at(e.length)
        # land exactly on the outgoing tangent: the numeric clothoid is
        # within micrometres, and the next straight starts from here
        lout = math.hypot(c[0] - b[0], c[1] - b[1])
        cursor = (b[0] + (c[0] - b[0]) / lout * t, b[1] + (c[1] - b[1]) / lout * t)
    straight_to(pts[-1])
    return elements


# -- curves read back from an axis of elements ----------------------------------------------

@dataclass(frozen=True)
class CurveGroup:
    """One curve of an axis between two straights: its elements and what a
    table says of it."""

    number: int
    elements: tuple
    first_run: float               # distance from the axis start to its first element
    pi: Point
    delta: float                   # degrees
    left: bool

    @property
    def radius(self) -> float:
        return min(e.radius for e in self.elements)

    @property
    def spiral_in(self) -> Element | None:
        e = self.elements[0]
        return e if e.is_spiral else None

    @property
    def spiral_out(self) -> Element | None:
        e = self.elements[-1]
        return e if e.is_spiral and len(self.elements) > 1 else None

    @property
    def length(self) -> float:
        return sum(e.length for e in self.elements)


def _line_intersection(p, a_deg, q, b_deg) -> Point | None:
    ax, ay = math.cos(math.radians(a_deg)), math.sin(math.radians(a_deg))
    bx, by = math.cos(math.radians(b_deg)), math.sin(math.radians(b_deg))
    den = ax * by - ay * bx
    if abs(den) < 1e-12:
        return None
    t = ((q[0] - p[0]) * by - (q[1] - p[1]) * bx) / den
    return (p[0] + t * ax, p[1] + t * ay)


def curve_groups(alignment: Alignment) -> list[CurveGroup]:
    """Every run of curved elements between straights, as one curve."""
    elements = as_elements(alignment)
    out: list[CurveGroup] = []
    run = 0.0
    i = 0
    while i < len(elements):
        if elements[i].is_line:
            run += elements[i].length
            i += 1
            continue
        j, start_run = i, run
        group = []
        while j < len(elements) and not elements[j].is_line:
            group.append(elements[j])
            run += elements[j].length
            j += 1
        first, last = group[0], group[-1]
        delta = _deflection(first.start_angle, last.end_angle)
        pi = _line_intersection(first.start, first.start_angle, last.end, last.end_angle) or first.start
        out.append(CurveGroup(len(out) + 1, tuple(group), start_run, pi, abs(delta), delta > 0))
        i = j
    return out


def _spiral_pis(alignment: "ElementAlignment") -> list[PI]:
    out: list[PI] = []
    groups = {g.first_run: g for g in curve_groups(alignment)}
    elements = alignment.elements
    run = 0.0
    i = 0
    s0 = alignment.start_station
    while i < len(elements):
        e = elements[i]
        if e.is_line:
            nxt = elements[i + 1] if i + 1 < len(elements) else None
            if nxt is not None and nxt.is_line:
                turn = _deflection(e.end_angle, nxt.start_angle)
                if abs(turn) > 1e-7:
                    out.append(PI(len(out) + 1, e.end, s0 + run + e.length, None, turn > 0))
            run += e.length
            i += 1
            continue
        g = groups[run]
        start = g.elements[0].start
        end = g.elements[-1].end
        ls = g.spiral_in.length if g.spiral_in else 0.0
        curve = SpiralCurve(g.delta, g.radius, ls) if ls > 0 else CurveElements(g.delta, g.radius)
        pc_station = s0 + run
        sc = cs = None
        sc_station = cs_station = None
        if ls > 0:
            sc = g.elements[0].end
            sc_station = pc_station + ls
            last = g.spiral_out
            cs = last.start if last is not None else end
            cs_station = pc_station + g.length - (last.length if last is not None else 0.0)
        t_in = math.hypot(g.pi[0] - start[0], g.pi[1] - start[1])
        out.append(PI(len(out) + 1, g.pi, pc_station + t_in, curve, g.left, start, end,
                      pc_station, pc_station + g.length, sc, cs, sc_station, cs_station))
        run += g.length
        i += len(g.elements)
    return out
