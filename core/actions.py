# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Headless command dispatch — every prompt keystroke ends up here.

The dispatcher owns the AutoCAD prompt semantics that the UI must not
reimplement: alias resolution, Enter-on-empty repeats the last command,
multi-step prompts (``Z`` then ``E``), Esc cancels. Handlers are plain
callables registered by the application, so the whole flow is testable
without a GUI (the AI-native invariant: every command is a headless
action first).

A handler may return a :class:`Prompt` to ask for more input; the next
submitted line goes to its callback instead of starting a new command.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import math

from core import aliases as aliases_mod
from core.commands import Command
from core.i18n import tr


@dataclass
class Prompt:
    """A continuation: show ``text`` and send the next input line to ``on_input``."""

    text: str
    on_input: Callable[[str], Optional["Prompt"]]


@dataclass
class _Entry:
    handler: Callable[..., Optional[Prompt]]
    phase: int = 0  # 0 = implemented; else "arrives in Phase N"


@dataclass
class Dispatcher:
    """Parses prompt input and routes it to registered command handlers."""

    aliases: dict[str, str] = field(default_factory=aliases_mod.load_aliases)
    echo: Callable[[str], None] = lambda text: None

    def __post_init__(self) -> None:
        self._commands: dict[str, _Entry] = {}
        self._pending: Optional[Prompt] = None
        self.last_command: str = ""

    # -- registration ---------------------------------------------------------
    def register(self, name: str, handler: Callable[..., Optional[Prompt]]) -> None:
        self._commands[name.upper()] = _Entry(handler)

    def register_future(self, name: str, phase: int) -> None:
        """A command in scope but not implemented yet: answer honestly."""
        self._commands[name.upper()] = _Entry(handler=None, phase=phase)

    def known_names(self) -> list[str]:
        """Commands + aliases, for prompt autocompletion."""
        names = set(self._commands)
        names.update(a for a, cmd in self.aliases.items() if cmd in self._commands)
        return sorted(names)

    # -- prompt state ---------------------------------------------------------
    @property
    def pending_prompt(self) -> Optional[str]:
        return self._pending.text if self._pending else None

    def cancel(self) -> None:
        """Esc: abandon any pending multi-step prompt."""
        if self._pending is not None:
            self._pending = None
            self.echo(tr("*Cancel*"))

    # -- input ----------------------------------------------------------------
    def submit(self, raw: str) -> None:
        """One line from the prompt (Enter or Space already stripped)."""
        text = raw.strip()

        if self._pending is not None:
            prompt = self._pending
            self._pending = None
            self._continue(prompt.on_input(text))
            return

        if not text:
            # AutoCAD: Enter on an empty prompt repeats the last command.
            if self.last_command:
                self._run(self.last_command, [])
            return

        tokens = text.split()
        self._run(self.resolve_name(tokens[0]), tokens[1:])

    def resolve_name(self, token: str) -> str:
        """Alias, exact command, or the command a prefix completes to.

        AutoCAD's AutoComplete finishes the name as you type, so ``OFF`` runs
        OFFSET and ``REC`` runs RECTANG without spelling either out. Order
        matters: an ALIAS always wins, or ``L`` would stop meaning LINE the
        day a LAYER-ish command sorted ahead of it. Only then does a prefix
        complete, and among several matches the first alphabetically — the
        one AutoCAD appends, and the one the prompt has been showing inline
        while the user typed.
        """
        name = aliases_mod.resolve(token, self.aliases)
        if name in self._commands:
            return name
        prefix = token.strip().upper()
        if prefix:
            matches = sorted(n for n in self._commands
                             if n.startswith(prefix))
            if matches:
                return matches[0]
        return name

    def _run(self, name: str, args: list[str]) -> None:
        entry = self._commands.get(name)
        if entry is None:
            self.echo(tr('Unknown command "{name}".', name=name))
            return
        self.last_command = name
        if entry.handler is None:
            self.echo(tr("{name}: not available yet (arrives in Phase {phase}).",
                         name=name, phase=entry.phase))
            return
        self._continue(entry.handler(*args) if args else entry.handler())

    def _continue(self, result: Optional[Prompt]) -> None:
        if isinstance(result, Prompt):
            self._pending = result
            self.echo(result.text)


# -- drawing actions (headless, undoable) --------------------------------------
#
# Every mutation is a Command: do() creates the entity in modelspace, undo()
# deletes it. The ezdxf document IS the model — no shadow data structures.

class AddEntityCommand(Command):
    """Create one entity via a factory(msp) -> entity; undo deletes it.

    ``layer`` overrides the usual "new entities land on the current layer"
    rule, for the commands that copy an existing object and are asked to
    keep its layer (OFFSET's Layer > Source, which is AutoCAD's default).
    """

    def __init__(self, name: str, factory, layer: str | None = None) -> None:
        self.name = name
        self._factory = factory
        self.layer = layer
        self.entity = None

    def do(self, document) -> None:
        self.entity = self._factory(document.modelspace())
        # New entities take the CURRENT properties, the ones the Properties
        # bar sets: layer, colour, linetype, lineweight. They default to
        # ByLayer, so a drawing stays layer-driven unless the user overrides
        # it on purpose — and a command that already chose (OFFSET keeping
        # the source's layer) keeps what it chose.
        from core import layers as layer_ops

        wanted = self.layer if self.layer is not None \
            else document.doc.header.get("$CLAYER", "0")
        if wanted in document.doc.layers:
            self.entity.dxf.layer = wanted
        for prop in ("color", "linetype", "lineweight"):
            if self.entity.dxf.hasattr(prop):
                continue          # the factory already said what it wanted
            value = layer_ops.current_property(document, prop)
            if value != layer_ops.CURRENT_DEFAULTS[prop]:
                try:
                    self.entity.dxf.set(prop, value)
                except Exception:
                    pass
        document.dirty = True

    def undo(self, document) -> None:
        if self.entity is not None:
            # Handles destroyed here are recorded so the UI can hide the
            # base-scene copies surgically instead of paying a full regen.
            self.removed_handles = [self.entity.dxf.handle]
            document.modelspace().delete_entity(self.entity)
            self.entity = None
        document.dirty = True


def add_line(p1, p2) -> AddEntityCommand:
    return AddEntityCommand(
        "LINE", lambda msp: msp.add_line((p1[0], p1[1]), (p2[0], p2[1])))


def add_circle(center, radius: float) -> AddEntityCommand:
    return AddEntityCommand(
        "CIRCLE", lambda msp: msp.add_circle((center[0], center[1]), radius))


def circle_from_2p(p1, p2) -> tuple[tuple[float, float], float]:
    center = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
    return center, math.dist(p1, p2) / 2.0


def circle_from_3p(p1, p2, p3) -> tuple[tuple[float, float], float]:
    """Circumcenter/radius; raises ValueError for collinear points."""
    ax, ay = p1
    bx, by = p2
    cx, cy = p3
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        raise ValueError("collinear points")
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay)
          + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx)
          + (cx * cx + cy * cy) * (bx - ax)) / d
    return (ux, uy), math.hypot(ax - ux, ay - uy)


def add_arc_3p(p1, p2, p3) -> AddEntityCommand:
    """Arc from start, a point on the arc, and end (AutoCAD ARC 3P)."""
    center, radius = circle_from_3p(p1, p2, p3)
    a1 = math.degrees(math.atan2(p1[1] - center[1], p1[0] - center[0]))
    a2 = math.degrees(math.atan2(p2[1] - center[1], p2[0] - center[0]))
    a3 = math.degrees(math.atan2(p3[1] - center[1], p3[0] - center[0]))
    # DXF arcs run counterclockwise from start to end; flip when the middle
    # point is not on the ccw sweep.
    if ((a2 - a1) % 360.0) > ((a3 - a1) % 360.0):
        a1, a3 = a3, a1
    return AddEntityCommand(
        "ARC",
        lambda msp: msp.add_arc((center[0], center[1]), radius, a1, a3))


# -- ARC geometry: AutoCAD's 11 methods reduced to (center, radius, a1, a2) ----
#
# DXF arcs always run counterclockwise from start_angle to end_angle; a
# clockwise construction is stored with the angles swapped. Each function
# returns (center, radius, start_deg, end_deg, end_point, ccw) where
# end_point is the USER's end of the drawn arc and ccw is the direction the
# user travelled (for tangent chaining) — not necessarily the entity's
# end_angle side.

def _dir_deg(frm, to) -> float:
    return math.degrees(math.atan2(to[1] - frm[1], to[0] - frm[0]))


def _polar(center, radius: float, angle_deg: float):
    a = math.radians(angle_deg)
    return (center[0] + radius * math.cos(a), center[1] + radius * math.sin(a))


def arc_sca(start, center, angle_deg: float):
    """Start, Center, included Angle. Positive = CCW; negative = CW."""
    radius = math.dist(start, center)
    if radius <= 0.0:
        raise ValueError("zero radius")
    a1 = _dir_deg(center, start)
    end = _polar(center, radius, a1 + angle_deg)
    if angle_deg >= 0.0:
        return center, radius, a1, a1 + angle_deg, end, True
    return center, radius, a1 + angle_deg, a1, end, False


def arc_scl(start, center, chord: float):
    """Start, Center, chord Length. Positive = minor arc CCW; negative =
    major arc CCW (AutoCAD's rule)."""
    radius = math.dist(start, center)
    if radius <= 0.0 or abs(chord) > 2.0 * radius or chord == 0.0:
        raise ValueError("chord does not fit the radius")
    included = math.degrees(2.0 * math.asin(abs(chord) / (2.0 * radius)))
    if chord < 0.0:
        included = 360.0 - included
    a1 = _dir_deg(center, start)
    return (center, radius, a1, a1 + included,
            _polar(center, radius, a1 + included), True)


def arc_sea(start, end, angle_deg: float):
    """Start, End, included Angle. Positive = CCW; negative = CW."""
    if angle_deg == 0.0 or abs(angle_deg) >= 360.0:
        raise ValueError("angle must be in (-360, 0) or (0, 360)")
    if angle_deg < 0.0:
        # a CW arc start->end is the CCW arc end->start
        center, radius, a1, a2, _e, _ccw = arc_sea(end, start, -angle_deg)
        return center, radius, a1, a2, _polar(center, radius, a1), False
    chord = math.dist(start, end)
    if chord <= 0.0:
        raise ValueError("zero chord")
    half = math.radians(angle_deg) / 2.0
    radius = chord / (2.0 * math.sin(half))
    mid = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
    ux, uy = (end[0] - start[0]) / chord, (end[1] - start[1]) / chord
    left = (-uy, ux)
    d = math.sqrt(max(radius * radius - (chord / 2.0) ** 2, 0.0))
    side = 1.0 if angle_deg < 180.0 else -1.0
    center = (mid[0] + side * d * left[0], mid[1] + side * d * left[1])
    return (center, radius, _dir_deg(center, start), _dir_deg(center, end),
            (end[0], end[1]), True)


def arc_sed(start, end, direction_deg: float):
    """Start, End, start-tangent Direction. Any arc, CW or CCW."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    u = (math.cos(math.radians(direction_deg)),
         math.sin(math.radians(direction_deg)))
    n = (-u[1], u[0])                       # left normal of the tangent
    denom = 2.0 * (dx * n[0] + dy * n[1])
    if abs(denom) < 1e-12:
        raise ValueError("direction is collinear with the chord")
    r_signed = (dx * dx + dy * dy) / denom
    center = (start[0] + r_signed * n[0], start[1] + r_signed * n[1])
    radius = abs(r_signed)
    a_start = _dir_deg(center, start)
    a_end = _dir_deg(center, end)
    if r_signed > 0.0:                      # center left of tangent: CCW
        return center, radius, a_start, a_end, (end[0], end[1]), True
    return center, radius, a_end, a_start, (end[0], end[1]), False


def arc_ser(start, end, radius: float):
    """Start, End, Radius. Positive = minor arc CCW; negative = major arc
    CCW (AutoCAD's rule). Chord must fit the radius."""
    chord = math.dist(start, end)
    if radius == 0.0 or chord <= 0.0 or chord > 2.0 * abs(radius):
        raise ValueError("chord does not fit the radius")
    r = abs(radius)
    mid = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
    ux, uy = (end[0] - start[0]) / chord, (end[1] - start[1]) / chord
    left = (-uy, ux)
    d = math.sqrt(max(r * r - (chord / 2.0) ** 2, 0.0))
    side = 1.0 if radius > 0.0 else -1.0    # minor: center left of the chord
    center = (mid[0] + side * d * left[0], mid[1] + side * d * left[1])
    return (center, r, _dir_deg(center, start), _dir_deg(center, end),
            (end[0], end[1]), True)


def add_arc_geom(geom) -> AddEntityCommand:
    """Command from an arc geometry tuple (see the section comment)."""
    center, radius, a1, a2 = geom[0], geom[1], geom[2], geom[3]
    return AddEntityCommand(
        "ARC", lambda msp: msp.add_arc((center[0], center[1]), radius, a1, a2))


def arc_end_tangent(geom) -> float:
    """Tangent direction (degrees) at the USER end of a drawn arc, following
    the drawing direction — what LINE/ARC Continue chains from."""
    center, end_point, ccw = geom[0], geom[4], geom[5]
    a_end = _dir_deg(center, end_point)
    return a_end + (90.0 if ccw else -90.0)


# -- CIRCLE TTR: radius-r circle tangent to two objects -------------------------
#
# The center of a circle tangent to a LINE lies on one of the two parallels
# at distance r; tangent to a CIRCLE(R), on one of the concentric circles of
# radius R+r or |R-r|. Candidate centers are the intersections of those loci;
# AutoCAD's documented disambiguation picks the candidate whose tangent
# points are closest to the pick points.

def _tangent_loci(obj, r: float) -> list:
    kind = obj[0]
    if kind == "line":
        p1, p2 = obj[1], obj[2]
        ux, uy = p2[0] - p1[0], p2[1] - p1[1]
        length = math.hypot(ux, uy)
        if length < 1e-12:
            raise ValueError("degenerate line")
        n = (-uy / length, ux / length)
        return [("line", (p1[0] + s * r * n[0], p1[1] + s * r * n[1]),
                 (ux / length, uy / length)) for s in (1.0, -1.0)]
    center, big_r = obj[1], obj[2]
    loci = [("circle", center, big_r + r)]
    if abs(big_r - r) > 1e-12:
        loci.append(("circle", center, abs(big_r - r)))
    return loci


def _loci_intersections(a, b) -> list:
    """Intersection points of two loci (lines given as (point, unit))."""
    if a[0] == "circle" and b[0] == "line":
        a, b = b, a
    if a[0] == "line" and b[0] == "line":
        (px, py), (ux, uy) = a[1], a[2]
        (qx, qy), (vx, vy) = b[1], b[2]
        den = ux * vy - uy * vx
        if abs(den) < 1e-12:
            return []
        t = ((qx - px) * vy - (qy - py) * vx) / den
        return [(px + t * ux, py + t * uy)]
    if a[0] == "line":
        (px, py), (ux, uy) = a[1], a[2]
        (cx, cy), r = b[1], b[2]
        t0 = (cx - px) * ux + (cy - py) * uy
        foot = (px + t0 * ux, py + t0 * uy)
        d2 = r * r - ((foot[0] - cx) ** 2 + (foot[1] - cy) ** 2)
        if d2 < -1e-9:
            return []
        h = math.sqrt(max(d2, 0.0))
        return [(foot[0] + s * h * ux, foot[1] + s * h * uy)
                for s in ((1.0, -1.0) if h > 1e-12 else (0.0,))]
    (c1, r1), (c2, r2) = (a[1], a[2]), (b[1], b[2])
    d = math.dist(c1, c2)
    if d < 1e-12 or d > r1 + r2 + 1e-9 or d < abs(r1 - r2) - 1e-9:
        return []
    x = (d * d + r1 * r1 - r2 * r2) / (2.0 * d)
    h2 = r1 * r1 - x * x
    h = math.sqrt(max(h2, 0.0))
    ux, uy = (c2[0] - c1[0]) / d, (c2[1] - c1[1]) / d
    base = (c1[0] + x * ux, c1[1] + x * uy)
    if h < 1e-12:
        return [base]
    return [(base[0] - s * h * uy, base[1] + s * h * ux) for s in (1.0, -1.0)]


def _tangent_point(obj, center) -> tuple[float, float]:
    if obj[0] == "line":
        (px, py), p2 = obj[1], obj[2]
        ux, uy = p2[0] - px, p2[1] - py
        length = math.hypot(ux, uy)
        ux, uy = ux / length, uy / length
        t = (center[0] - px) * ux + (center[1] - py) * uy
        return (px + t * ux, py + t * uy)
    c, big_r = obj[1], obj[2]
    d = math.dist(c, center)
    if d < 1e-12:
        return c
    return (c[0] + (center[0] - c[0]) * big_r / d,
            c[1] + (center[1] - c[1]) * big_r / d)


def ttr_center(obj1, pick1, obj2, pick2, radius: float):
    """CIRCLE Ttr: center of the radius circle tangent to both objects,
    choosing the candidate whose tangent points are closest to the pick
    points (AutoCAD's documented rule). Raises ValueError when no circle
    of that radius fits ("Circle does not exist.")."""
    if radius <= 0.0:
        raise ValueError("radius must be positive")
    best = None
    best_score = None
    for locus1 in _tangent_loci(obj1, radius):
        for locus2 in _tangent_loci(obj2, radius):
            for center in _loci_intersections(locus1, locus2):
                t1 = _tangent_point(obj1, center)
                t2 = _tangent_point(obj2, center)
                score = math.dist(t1, pick1) + math.dist(t2, pick2)
                if best_score is None or score < best_score:
                    best, best_score = center, score
    if best is None:
        raise ValueError("circle does not exist")
    return best


def add_polyline(points, closed: bool = False) -> AddEntityCommand:
    """LWPOLYLINE from plain (x, y) pairs or full (x, y, start_width,
    end_width, bulge) vertices (PLINE arc segments and tapered widths)."""
    if points and len(points[0]) >= 5:
        pts = [tuple(p[:5]) for p in points]
        return AddEntityCommand(
            "PLINE", lambda msp: msp.add_lwpolyline(
                pts, format="xyseb", close=closed))
    pts = [(p[0], p[1]) for p in points]
    return AddEntityCommand(
        "PLINE", lambda msp: msp.add_lwpolyline(pts, close=closed))


def add_spline(fit_points, closed: bool = False) -> AddEntityCommand:
    """SPLINE through fit points (AutoCAD's default Fit method, degree 3).

    Close appends the first point as the last fit point — geometrically
    closed; AutoCAD's tangent-smooth periodic joint is not offered because
    ezdxf has no periodic FIT interpolation to honor it with.
    """
    pts = [tuple(p[:2]) for p in fit_points]
    if closed and pts and pts[-1] != pts[0]:
        pts = pts + [pts[0]]

    return AddEntityCommand(
        "SPLINE", lambda msp: msp.add_spline(fit_points=list(pts)))


def add_polyline_ex(points, closed: bool = False, name: str = "PLINE",
                    dxfattribs: dict | None = None) -> AddEntityCommand:
    """add_polyline with xyseb vertices plus entity attributes (RECTANG's
    Elevation -> elevation, Thickness -> thickness)."""
    pts = [tuple(p[:5]) for p in points]
    attribs = dict(dxfattribs or {})
    # fresh dict per call: ezdxf may consume the attribs, and redo re-runs
    # the factory
    return AddEntityCommand(
        name, lambda msp: msp.add_lwpolyline(
            pts, format="xyseb", close=closed, dxfattribs=dict(attribs)))


def rect_vertices(first, length: float, width: float, *,
                  rotation_deg: float = 0.0, chamfer=(0.0, 0.0),
                  fillet: float = 0.0, pl_width: float = 0.0) -> list:
    """RECTANG's closed ring as xyseb vertices, honoring the sticky corner
    settings: chamfered (8 vertices), filleted (arc corners, bulge
    tan(90°/4)) or square. ``length``/``width`` are signed offsets from
    ``first`` in the rotated frame. Corners that don't fit fall back to a
    square rectangle, like AutoCAD."""
    x0, x1 = (0.0, length) if length >= 0 else (length, 0.0)
    y0, y1 = (0.0, width) if width >= 0 else (width, 0.0)
    w, h = x1 - x0, y1 - y0
    if w <= 0.0 or h <= 0.0:
        raise ValueError("zero-size rectangle")
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]     # CCW ring
    d1, d2 = max(chamfer[0], 0.0), max(chamfer[1], 0.0)
    r = max(fillet, 0.0)
    ring: list[tuple] = []                                  # (x, y, bulge)
    if r > 0.0 and 2.0 * r <= min(w, h) + 1e-12:
        arc_bulge = math.tan(math.radians(90.0) / 4.0)      # CCW quarter turn
        for i, c in enumerate(corners):
            pin = corners[i - 1]
            pout = corners[(i + 1) % 4]
            din = _unit(pin, c)
            dout = _unit(c, pout)
            a = (c[0] - r * din[0], c[1] - r * din[1])
            b = (c[0] + r * dout[0], c[1] + r * dout[1])
            ring.append((a[0], a[1], arc_bulge))            # the corner arc
            ring.append((b[0], b[1], 0.0))                  # then straight on
    elif (d1 > 0.0 or d2 > 0.0) and d1 + d2 <= min(w, h) + 1e-12 \
            and max(d1, d2) * 2.0 <= min(w, h) + 1e-12:
        for i, c in enumerate(corners):
            pin = corners[i - 1]
            pout = corners[(i + 1) % 4]
            din = _unit(pin, c)
            dout = _unit(c, pout)
            a = (c[0] - d1 * din[0], c[1] - d1 * din[1])
            b = (c[0] + d2 * dout[0], c[1] + d2 * dout[1])
            ring.append((a[0], a[1], 0.0))
            ring.append((b[0], b[1], 0.0))
    else:
        ring = [(c[0], c[1], 0.0) for c in corners]
    rot = math.radians(rotation_deg)
    ca, sa = math.cos(rot), math.sin(rot)
    out = []
    for x, y, bulge in ring:
        wx = first[0] + x * ca - y * sa
        wy = first[1] + x * sa + y * ca
        out.append((wx, wy, pl_width, pl_width, bulge))
    return out


def _unit(a, b):
    d = math.dist(a, b)
    return ((b[0] - a[0]) / d, (b[1] - a[1]) / d)


def polygon_ring(center, sides: int, vertex_radius: float,
                 first_vertex_deg: float) -> list:
    """Vertices of a regular polygon, first vertex at the given angle."""
    pts = []
    for i in range(sides):
        a = math.radians(first_vertex_deg + 360.0 * i / sides)
        pts.append((center[0] + vertex_radius * math.cos(a),
                    center[1] + vertex_radius * math.sin(a)))
    return pts


def polygon_from_edge(p1, p2, sides: int) -> list:
    """POLYGON Edge: walk CCW from the first edge (body left of p1->p2)."""
    s = math.dist(p1, p2)
    if s <= 0.0:
        raise ValueError("zero-length edge")
    pts = [tuple(p1), tuple(p2)]
    heading = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    turn = math.tau / sides
    for _ in range(sides - 2):
        heading += turn
        last = pts[-1]
        pts.append((last[0] + s * math.cos(heading),
                    last[1] + s * math.sin(heading)))
    return pts


def add_rectangle(p1, p2) -> AddEntityCommand:
    pts = [(p1[0], p1[1]), (p2[0], p1[1]), (p2[0], p2[1]), (p1[0], p2[1])]
    return AddEntityCommand(
        "RECTANG", lambda msp: msp.add_lwpolyline(pts, close=True))


def polygon_points(center, vertex, sides: int) -> list[tuple[float, float]]:
    """Regular polygon inscribed, one vertex at ``vertex``."""
    r = math.dist(center, vertex)
    a0 = math.atan2(vertex[1] - center[1], vertex[0] - center[0])
    return [
        (center[0] + r * math.cos(a0 + i * math.tau / sides),
         center[1] + r * math.sin(a0 + i * math.tau / sides))
        for i in range(sides)
    ]


def add_polygon(center, vertex, sides: int) -> AddEntityCommand:
    pts = polygon_points(center, vertex, sides)
    return AddEntityCommand(
        "POLYGON", lambda msp: msp.add_lwpolyline(pts, close=True))


# -- editing actions (headless, undoable) --------------------------------------

class TransformCommand(Command):
    """Apply a Matrix44 to entities in place; undo applies the inverse."""

    def __init__(self, name: str, entities, matrix) -> None:
        self.name = name
        self.entities = list(entities)
        self.matrix = matrix

    def do(self, document) -> None:
        for e in self.entities:
            e.transform(self.matrix)
        document.dirty = True

    def undo(self, document) -> None:
        import numpy as np
        from ezdxf.math import Matrix44

        inverse = Matrix44(self.matrix)
        inverse.inverse()
        for e in self.entities:
            e.transform(inverse)
        document.dirty = True


class EraseCommand(Command):
    """Unlink entities from modelspace (keeps them alive for exact undo)."""

    name = "ERASE"

    def __init__(self, entities) -> None:
        self.entities = list(entities)

    def do(self, document) -> None:
        msp = document.modelspace()
        for e in self.entities:
            msp.unlink_entity(e)
        document.dirty = True

    def undo(self, document) -> None:
        msp = document.modelspace()
        for e in self.entities:
            msp.add_entity(e)
        document.dirty = True


class CopyEntitiesCommand(Command):
    """Copy entities transformed by a Matrix44; undo removes the copies."""

    name = "COPY"

    def __init__(self, entities, matrix) -> None:
        self.sources = list(entities)
        self.matrix = matrix
        self.copies = []

    def do(self, document) -> None:
        msp = document.modelspace()
        self.copies = []
        for e in self.sources:
            clone = e.copy()
            clone.transform(self.matrix)
            msp.add_entity(clone)
            self.copies.append(clone)
        document.dirty = True

    def undo(self, document) -> None:
        msp = document.modelspace()
        self.removed_handles = [c.dxf.handle for c in self.copies]
        for clone in self.copies:
            msp.delete_entity(clone)
        self.copies = []
        document.dirty = True


class ReplaceEntitiesCommand(Command):
    """Swap old entities for new ones (TRIM/EXTEND/FILLET results).

    Old entities are unlinked (kept alive), new ones created by factories.
    """

    def __init__(self, name: str, old_entities, factories) -> None:
        self.name = name
        self.old_entities = list(old_entities)
        self._factories = list(factories)
        self.new_entities = []

    def do(self, document) -> None:
        msp = document.modelspace()
        for e in self.old_entities:
            msp.unlink_entity(e)
        self.new_entities = [factory(msp) for factory in self._factories]
        document.dirty = True

    def undo(self, document) -> None:
        msp = document.modelspace()
        self.removed_handles = [e.dxf.handle for e in self.new_entities]
        for e in self.new_entities:
            msp.delete_entity(e)
        self.new_entities = []
        for e in self.old_entities:
            msp.add_entity(e)
        document.dirty = True


# -- blocks (Phase 6) ----------------------------------------------------------

class CreateBlockCommand(Command):
    """BLOCK: define a block from entities and convert them to a reference.

    Matches AutoCAD's default "Convert to block": the selection is packed into
    a new block definition and replaced in place by one INSERT at the base
    point. The block's base point is the picked point, so — inserted at that
    same point — the reference lands exactly over the originals.
    """

    name = "BLOCK"

    def __init__(self, block_name: str, base_point, entities) -> None:
        self.block_name = block_name
        self.base = base_point
        self.sources = list(entities)
        self.insert = None
        self._defined = False

    def do(self, document) -> None:
        doc = document.doc
        msp = document.modelspace()
        if self.block_name not in doc.blocks:
            blk = doc.blocks.new(
                name=self.block_name,
                base_point=(self.base[0], self.base[1]))
            for e in self.sources:
                blk.add_entity(e.copy())
            self._defined = True
        for e in self.sources:
            msp.unlink_entity(e)
        self.insert = msp.add_blockref(
            self.block_name, (self.base[0], self.base[1]))
        document.dirty = True

    def undo(self, document) -> None:
        doc = document.doc
        msp = document.modelspace()
        if self.insert is not None:
            self.removed_handles = [self.insert.dxf.handle]
            msp.delete_entity(self.insert)
            self.insert = None
        for e in self.sources:
            msp.add_entity(e)
        if self._defined and self.block_name in doc.blocks:
            doc.blocks.delete_block(self.block_name, safe=False)
            self._defined = False
        document.dirty = True


def create_block(block_name, base_point, entities) -> CreateBlockCommand:
    return CreateBlockCommand(block_name, base_point, entities)


def insert_block(name, point, xscale=1.0, yscale=None,
                 rotation=0.0) -> AddEntityCommand:
    ys = xscale if yscale is None else yscale
    return AddEntityCommand(
        "INSERT",
        lambda msp: msp.add_blockref(
            name, (point[0], point[1]),
            dxfattribs={"xscale": xscale, "yscale": ys, "rotation": rotation}))


class ExplodeCommand(Command):
    """EXPLODE: replace INSERT/POLYLINE with their component entities.

    Component entities come from ``virtual_entities`` (already placed in world
    coordinates); the originals are unlinked (kept alive for exact undo).
    """

    name = "EXPLODE"

    def __init__(self, entities) -> None:
        self.sources = list(entities)
        self.pieces: list = []

    def do(self, document) -> None:
        msp = document.modelspace()
        self.pieces = []
        for e in self.sources:
            if e.dxftype() not in ("INSERT", "LWPOLYLINE", "POLYLINE"):
                continue
            parts = []
            for v in e.virtual_entities():
                msp.add_entity(v)
                parts.append(v)
            msp.unlink_entity(e)
            self.pieces.append((e, parts))
        document.dirty = True

    def undo(self, document) -> None:
        msp = document.modelspace()
        self.removed_handles = [v.dxf.handle
                                for _o, parts in self.pieces for v in parts]
        for original, parts in self.pieces:
            for v in parts:
                msp.delete_entity(v)
            msp.add_entity(original)
        self.pieces = []
        document.dirty = True


def explode_entities(entities) -> ExplodeCommand:
    return ExplodeCommand(entities)


# -- hatch (Phase 6) -----------------------------------------------------------

def _std_patterns():
    """The 172 predefined ACAD/ISO hatch patterns, loaded once."""
    global _STD_PATTERNS
    try:
        return _STD_PATTERNS
    except NameError:
        from ezdxf.tools import pattern as _pat
        _STD_PATTERNS = _pat.load()
        return _STD_PATTERNS


def hatch_pattern_names() -> list:
    """Sorted predefined pattern names (for the hatch style picker)."""
    return sorted(_std_patterns().keys())


def _add_boundary(hatch, item, flags: int) -> None:
    """Add one boundary path: an ezdxf entity (closed) or a point list."""
    if isinstance(item, (list, tuple)) and item and isinstance(item[0], (list, tuple)):
        pts = [(p[0], p[1]) for p in item]
        hatch.paths.add_polyline_path(pts, is_closed=True, flags=flags)
        return
    t = item.dxftype()
    if t == "LWPOLYLINE":
        pts = [(p[0], p[1], p[2]) for p in item.get_points("xyb")]
        hatch.paths.add_polyline_path(pts, is_closed=True, flags=flags)
    elif t == "CIRCLE":
        c = item.dxf.center
        path = hatch.paths.add_edge_path(flags=flags)
        path.add_arc((c.x, c.y), item.dxf.radius, 0, 360)
    elif t == "ELLIPSE":
        c = item.dxf.center
        maj = item.dxf.major_axis
        path = hatch.paths.add_edge_path(flags=flags)
        path.add_ellipse((c.x, c.y), (maj.x, maj.y), item.dxf.ratio, 0, 360)
    else:
        from core.hatch_boundary import boundary_polygon

        poly = boundary_polygon(item)
        if poly:
            hatch.paths.add_polyline_path(poly, is_closed=True, flags=flags)


#: -HATCH island styles (DXF group 75): what happens inside the outer loop.
HATCH_STYLE_NORMAL = 0     # alternate fill at nested islands
HATCH_STYLE_OUTER = 1      # hatch only the outermost level
HATCH_STYLE_IGNORE = 2     # hatch straight through internal objects


def user_pattern_definition(angle_deg: float, spacing: float,
                            double: bool) -> list:
    """-HATCH "User defined": continuous parallel lines at ``angle`` with
    ``spacing`` between them; ``double`` adds a second set at 90 degrees."""
    def line(a):
        rad = math.radians(a)
        offset = (-spacing * math.sin(rad), spacing * math.cos(rad))
        return [a, (0.0, 0.0), offset, []]

    lines = [line(angle_deg)]
    if double:
        lines.append(line(angle_deg + 90.0))
    return lines


def add_hatch(boundaries, pattern="SOLID", scale=1.0, angle=0.0,
              color=256, islands=None, style=HATCH_STYLE_NORMAL,
              user_def=None) -> AddEntityCommand:
    """SOLID, a predefined pattern (ANSI31…) or a user-defined one inside
    closed boundaries.

    ``boundaries`` and ``islands`` are ezdxf entities or point lists.
    ``style`` is the AutoCAD island style (Normal/Outer/Ignore): Ignore
    drops the islands entirely; the style is also recorded in the entity
    (group 75) for round-trip. ``user_def`` = (angle, spacing, double)
    builds -HATCH's "User defined" pattern. ``color`` is an ACI; 256 =
    ByLayer (AutoCAD's default for a new hatch).
    """
    from ezdxf.lldxf.const import (
        BOUNDARY_PATH_EXTERNAL, BOUNDARY_PATH_OUTERMOST)

    name = str(pattern).upper()
    aci = 7 if color in (256, 0) else color

    def factory(msp):
        h = msp.add_hatch(color=aci)
        if user_def is not None:
            u_angle, u_spacing, u_double = user_def
            h.set_pattern_fill(
                "U", color=aci, scale=1.0, angle=0.0,
                definition=user_pattern_definition(u_angle, u_spacing,
                                                   bool(u_double)))
            h.dxf.pattern_type = 0    # user-defined
            h.dxf.pattern_double = 1 if u_double else 0
        elif name == "SOLID":
            h.set_solid_fill(color=aci)
        else:
            defn = _std_patterns().get(name)
            h.set_pattern_fill(name, color=aci, angle=angle, scale=scale,
                               definition=defn)
        for b in boundaries:
            _add_boundary(h, b, BOUNDARY_PATH_EXTERNAL)
        if style != HATCH_STYLE_IGNORE:
            for isl in (islands or ()):
                _add_boundary(h, isl, BOUNDARY_PATH_OUTERMOST)
        # last: ezdxf's fill/path helpers overwrite hatch_style on the way
        h.dxf.hatch_style = int(style)
        h.dxf.color = color   # keep ByLayer sentinel when requested
        return h
    return AddEntityCommand("HATCH", factory)


# -- dimensions (create) -------------------------------------------------------

class AddDimensionCommand(Command):
    """Create a dimension: the factory builds it, ``render()`` draws the
    graphics into an anonymous *D block. Undo removes the dimension and that
    block; the current dimension style ($DIMSTYLE) is used at render time.
    """

    name = "DIMENSION"

    def __init__(self, factory) -> None:
        self._factory = factory
        self.dim = None
        self._block_name = None

    def do(self, document) -> None:
        override = self._factory(document.modelspace(), document)
        override.render()
        self.dim = override.dimension
        self._block_name = self.dim.dxf.get("geometry", None)
        current = document.doc.header.get("$CLAYER", "0")
        if current in document.doc.layers:
            self.dim.dxf.layer = current
        # AFTER the layer lands: the stamp dresses the block in the
        # dimension's layer.
        _stamp_dim_block_byblock(document, self.dim)
        document.dirty = True

    def undo(self, document) -> None:
        msp = document.modelspace()
        block = self._block_name
        if self.dim is not None and self.dim.is_alive:
            # DIMTEDIT re-renders into a fresh *D block: trust the entity's
            # current geometry attribute over the name captured at creation.
            block = self.dim.dxf.get("geometry", block)
            self.removed_handles = [self.dim.dxf.handle]
            msp.delete_entity(self.dim)
        if block and block in document.doc.blocks:
            try:
                document.doc.blocks.delete_block(block, safe=False)
            except Exception:
                pass
        self.dim = None
        document.dirty = True


def _current_dimstyle(document) -> str:
    name = document.doc.header.get("$DIMSTYLE", "Standard")
    return name if name in document.doc.dimstyles else "Standard"


def linear_dim_angle(p1, p2, location) -> float:
    """DIMLINEAR's automatic horizontal/vertical choice.

    AutoCAD never auto-picks a zero measurement: origins sharing an X give
    the vertical dimension wherever the cursor goes (the old midpoint rule
    picked "horizontal" on a slightly diagonal drag and produced a
    collapsed dimension reading 0). Diagonal origins follow the side the
    cursor leaves the points' box on; inside the box, the closer axis.
    ONE source of truth: the tool's preview and the created entity must
    never disagree (they used to hold separate copies of the rule).
    """
    x1, x2 = sorted((p1[0], p2[0]))
    y1, y2 = sorted((p1[1], p2[1]))
    span = max(x2 - x1, y2 - y1, 1e-12)
    if (x2 - x1) < span * 1e-9:
        return 90.0
    if (y2 - y1) < span * 1e-9:
        return 0.0
    beyond_x = max(x1 - location[0], location[0] - x2, 0.0)
    beyond_y = max(y1 - location[1], location[1] - y2, 0.0)
    if beyond_x > beyond_y:
        return 90.0
    if beyond_y > beyond_x:
        return 0.0
    mid = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
    horizontal = abs(location[1] - mid[1]) >= abs(location[0] - mid[0])
    return 0.0 if horizontal else 90.0


def dim_linear(p1, p2, location, *, angle: float | None = None,
               text: str = "<>", text_rotation: float | None = None,
               dimstyle: str | None = None) -> AddDimensionCommand:
    """DIMLINEAR: horizontal/vertical chosen by the dimension-line pick, or a
    forced angle (Horizontal=0 / Vertical=90 / Rotated=any). ``text`` follows
    AutoCAD's Text option: "<>" is the measurement, " " suppresses it, any
    other string replaces it (an embedded "<>" is substituted by ezdxf).
    ``text_rotation`` is the Angle option (absolute text angle)."""
    if angle is None:
        angle = linear_dim_angle(p1, p2, location)

    def factory(msp, document):
        return msp.add_linear_dim(
            base=(location[0], location[1]),
            p1=(p1[0], p1[1]), p2=(p2[0], p2[1]),
            angle=angle, text=text, text_rotation=text_rotation,
            dimstyle=_chained_dimstyle(dimstyle, document))
    return AddDimensionCommand(factory)


def _chained_dimstyle(dimstyle: str | None, document) -> str:
    """DIMCONTINUE/DIMBASELINE inherit the base dimension's style."""
    if dimstyle and dimstyle in document.doc.dimstyles:
        return dimstyle
    return _current_dimstyle(document)


def _text_rotation_attribs(text_rotation: float | None) -> dict:
    # ezdxf's renderer reads the user text angle straight from the DIMENSION
    # entity (group 53); only add_linear_dim exposes it as a keyword.
    if text_rotation is None:
        return {}
    return {"text_rotation": float(text_rotation)}


def dim_aligned(p1, p2, location, *, text: str = "<>",
                text_rotation: float | None = None,
                dimstyle: str | None = None) -> AddDimensionCommand:
    """DIMALIGNED: dimension parallel to p1->p2, offset to the picked side."""
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length      # unit normal
    distance = (location[0] - p1[0]) * nx + (location[1] - p1[1]) * ny

    def factory(msp, document):
        return msp.add_aligned_dim(
            p1=(p1[0], p1[1]), p2=(p2[0], p2[1]),
            distance=distance, text=text,
            dimstyle=_chained_dimstyle(dimstyle, document),
            dxfattribs=_text_rotation_attribs(text_rotation))
    return AddDimensionCommand(factory)


def dim_radius(center, radius: float, location, *, text: str = "<>",
               text_rotation: float | None = None) -> AddDimensionCommand:
    angle = math.degrees(math.atan2(location[1] - center[1],
                                    location[0] - center[0]))

    def factory(msp, document):
        return msp.add_radius_dim(
            center=(center[0], center[1]), radius=radius, angle=angle,
            text=text, dimstyle=_current_dimstyle(document),
            dxfattribs=_text_rotation_attribs(text_rotation))
    return AddDimensionCommand(factory)


def dim_diameter(center, radius: float, location, *, text: str = "<>",
                 text_rotation: float | None = None) -> AddDimensionCommand:
    angle = math.degrees(math.atan2(location[1] - center[1],
                                    location[0] - center[0]))

    def factory(msp, document):
        return msp.add_diameter_dim(
            center=(center[0], center[1]), radius=radius, angle=angle,
            text=text, dimstyle=_current_dimstyle(document),
            dxfattribs=_text_rotation_attribs(text_rotation))
    return AddDimensionCommand(factory)


def _dim_block_shared(document, name: str) -> bool:
    """Is the anonymous *D block still referenced by any dimension?"""
    for e in document.doc.entitydb.values():
        if e.is_alive and e.dxftype() in ("DIMENSION", "ARC_DIMENSION") \
                and e.dxf.get("geometry", None) == name:
            return True
    return False


def _stamp_dim_block_byblock(document, dim) -> None:
    """Make a freshly rendered *D block wear the dimension's own dress.

    Real AutoCAD files (casa bueno's autopsy) write the block geometry on
    the DIMENSION'S LAYER with ByLayer color — a dim on layer Cota draws
    Cota's magenta. ezdxf's renderer leaves entities on layer 0 with no
    color, which resolved white on our canvas after every re-render.
    Entities the style explicitly colored (dimclrd/e/t as real ACIs) and
    the Defpoints markers stay untouched.
    """
    name = dim.dxf.get("geometry", None)
    if not name or name not in document.doc.blocks:
        return
    dim_layer = dim.dxf.get("layer", "0")
    for entity in document.doc.blocks.get(name):
        if entity.dxf.get("color", 256) == 256 \
                and entity.dxf.get("layer", "0") == "0":
            entity.dxf.layer = dim_layer   # ByLayer now means the dim's layer


def translate_dim_text(document, dim, dx: float, dy: float) -> bool:
    """Slide the text entities inside the dimension's block by (dx, dy).

    Used by the text grip: a pure translation keeps every other stroke of
    the block EXACTLY as its author's CAD rendered it — re-rendering a
    foreign dimension would replace AutoCAD's block with our
    approximation. Returns False when there is no block to edit.
    """
    name = dim.dxf.get("geometry", None)
    if not name or name not in document.doc.blocks:
        return False
    moved = False
    for entity in document.doc.blocks.get(name):
        if entity.dxftype() in ("MTEXT", "TEXT"):
            entity.translate(dx, dy, 0)
            moved = True
    if not moved:
        return False
    mid = dim.dxf.get("text_midpoint", None)
    if mid is not None:
        dim.dxf.text_midpoint = (mid.x + dx, mid.y + dy, mid.z)
    # AutoCAD's "user positioned text" flag: its own re-render respects
    # the moved spot instead of snapping the text back.
    dim.dxf.dimtype = dim.dxf.dimtype | 128
    return True


class DimTextTranslateCommand(Command):
    """The text grip: exact-fidelity text move, no block swap."""

    name = "GRIP"
    needs_regen = True

    def __init__(self, dim, target) -> None:
        self.dim = dim
        self.target = (float(target[0]), float(target[1]))
        self._delta: tuple[float, float] | None = None

    def do(self, document) -> None:
        mid = self.dim.dxf.get("text_midpoint", None)
        if self._delta is None:
            if mid is None:
                self._delta = (0.0, 0.0)
            else:
                self._delta = (self.target[0] - mid.x, self.target[1] - mid.y)
        translate_dim_text(document, self.dim, *self._delta)
        document.dirty = True

    def undo(self, document) -> None:
        dx, dy = self._delta or (0.0, 0.0)
        translate_dim_text(document, self.dim, -dx, -dy)
        document.dirty = True


def _drop_dim_block(document, name) -> None:
    if name and name in document.doc.blocks \
            and not _dim_block_shared(document, name):
        try:
            document.doc.blocks.delete_block(name, safe=False)
        except Exception:
            pass


class DimGripCommand(Command):
    """A grip moved one of a dimension's definition points.

    Setting the attr re-measures (extension origins) or relocates the
    dimension line (defpoint); render() rebuilds the *D block and the old
    one is dropped, so the document never keeps stale blocks. Undo
    restores every non-geometry attr and re-renders again.
    """

    name = "GRIP"
    needs_regen = True

    def __init__(self, dim, attr: str, point) -> None:
        self.dim = dim
        self.attr = attr
        self.point = (float(point[0]), float(point[1]))
        self._before: dict | None = None

    def do(self, document) -> None:
        d = self.dim
        if self._before is None:
            self._before = {
                k: v for k, v in d.dxf.all_existing_dxf_attribs().items()
                if k not in ("geometry", "handle")}
        old_block = d.dxf.get("geometry", None)
        # Preserve the text rotation the author's CAD chose: this file's
        # style says outside text lies horizontal (dimtoh), which ezdxf's
        # renderer does not reproduce — without this the label flipped to
        # line-aligned on every grip edit.
        if not d.dxf.hasattr("text_rotation") and old_block \
                and old_block in document.doc.blocks:
            for e in document.doc.blocks.get(old_block):
                if e.dxftype() in ("MTEXT", "TEXT"):
                    d.dxf.text_rotation = float(e.dxf.get("rotation", 0.0))
                    break
        setattr(d.dxf, self.attr, (self.point[0], self.point[1], 0.0))
        d.render()
        _stamp_dim_block_byblock(document, d)
        _drop_dim_block(document, old_block)
        document.dirty = True

    def undo(self, document) -> None:
        d = self.dim
        edited_block = d.dxf.get("geometry", None)
        for key in list(d.dxf.all_existing_dxf_attribs()):
            if key not in (self._before or {}) \
                    and key not in ("geometry", "handle"):
                d.dxf.discard(key)
        for key, value in (self._before or {}).items():
            d.dxf.set(key, value)
        d.render()
        _drop_dim_block(document, edited_block)
        document.dirty = True


class DimTextEditCommand(Command):
    """DIMTEDIT: reposition the text of an existing dimension and re-render
    its geometry block. Exactly one operation per invocation: a new text
    location, a horizontal alignment (left/center/right), Home (back to the
    style's default position) or a text angle. Undo restores the snapshot
    and re-renders, so the document never keeps stale *D blocks."""

    name = "DIMTEDIT"
    needs_regen = True

    def __init__(self, dim, *, location=None, halign: str | None = None,
                 home: bool = False, angle: float | None = None) -> None:
        self.dim = dim
        self.location = location
        self.halign = halign
        self.home = home
        self.angle = angle
        self._snapshot = None

    def do(self, document) -> None:
        d = self.dim
        if self._snapshot is None:
            self._snapshot = (
                d.dxf.dimtype,
                d.dxf.get("text_midpoint", None),
                d.dxf.get("text_rotation", None),
                list(d.get_xdata("ACAD")) if d.has_xdata("ACAD") else None)
        old_block = d.dxf.get("geometry", None)
        if self.location is not None:
            override = d.override()
            override.set_location(
                (self.location[0], self.location[1]),
                leader=False, relative=False)
            override.render()
        elif self.halign is not None:
            override = d.override()
            override.set_text_align(halign=self.halign)
            override.render()
        elif self.home:
            d.dxf.dimtype = d.dxf.dimtype & ~128    # drop user text position
            d.dxf.discard("text_midpoint")
            d.render()
        elif self.angle is not None:
            d.dxf.text_rotation = float(self.angle)
            d.render()
        _drop_dim_block(document, old_block)
        document.dirty = True

    def undo(self, document) -> None:
        d = self.dim
        dimtype, midpoint, text_rotation, xdata = self._snapshot
        edited_block = d.dxf.get("geometry", None)
        d.dxf.dimtype = dimtype
        if midpoint is None:
            d.dxf.discard("text_midpoint")
        else:
            d.dxf.text_midpoint = midpoint
        if text_rotation is None:
            d.dxf.discard("text_rotation")
        else:
            d.dxf.text_rotation = text_rotation
        d.discard_xdata("ACAD")
        if xdata is not None:
            d.set_xdata("ACAD", xdata)
        d.render()
        _drop_dim_block(document, edited_block)
        document.dirty = True


def dim_text_edit(dim, **kwargs) -> DimTextEditCommand:
    return DimTextEditCommand(dim, **kwargs)


# -- angular / arc-length / ordinate / center mark (v0.2 wave C) ---------------

def _ccw_contains(a_from: float, a_to: float, a: float) -> bool:
    """Is angle ``a`` inside the CCW sweep a_from -> a_to (radians)?"""
    two_pi = 2.0 * math.pi
    return (a - a_from) % two_pi <= (a_to - a_from) % two_pi


def angular_points(vertex, p1, p2, region):
    """Order (p1, p2) so the CCW angle from p1 to p2 contains ``region`` —
    AutoCAD's rule: the location (or Quadrant) pick chooses WHICH of the two
    possible angles is dimensioned."""
    a1 = math.atan2(p1[1] - vertex[1], p1[0] - vertex[0])
    a2 = math.atan2(p2[1] - vertex[1], p2[0] - vertex[0])
    ar = math.atan2(region[1] - vertex[1], region[0] - vertex[0])
    if _ccw_contains(a1, a2, ar):
        return p1, p2
    return p2, p1


def angular_measurement(vertex, p1, p2) -> float:
    """CCW sweep p1 -> p2 around vertex, in degrees."""
    a1 = math.atan2(p1[1] - vertex[1], p1[0] - vertex[0])
    a2 = math.atan2(p2[1] - vertex[1], p2[0] - vertex[0])
    return math.degrees((a2 - a1) % (2.0 * math.pi))


def line_intersection(l1, l2):
    """Intersection of two infinite lines ((p, q) tuples), or None."""
    (x1, y1), (x2, y2) = l1
    (x3, y3), (x4, y4) = l2
    d1 = (x2 - x1, y2 - y1)
    d2 = (x4 - x3, y4 - y3)
    denom = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(denom) < 1e-12:
        return None
    t = ((x3 - x1) * d2[1] - (y3 - y1) * d2[0]) / denom
    return (x1 + t * d1[0], y1 + t * d1[1])


def angular_from_lines(l1, l2, region):
    """(vertex, p1, p2) for DIMANGULAR between two lines, or None if
    parallel. Of the four regions the two lines form, the one containing
    ``region`` is dimensioned (official behavior); p1/p2 lie on the
    bounding rays at the region-pick's distance."""
    vertex = line_intersection(l1, l2)
    if vertex is None:
        return None
    radius = math.dist(region, vertex) or 1.0
    ang1 = math.atan2(l1[1][1] - l1[0][1], l1[1][0] - l1[0][0])
    ang2 = math.atan2(l2[1][1] - l2[0][1], l2[1][0] - l2[0][0])
    ar = math.atan2(region[1] - vertex[1], region[0] - vertex[0])
    for a in (ang1, ang1 + math.pi):
        for b in (ang2, ang2 + math.pi):
            lo, hi = (a, b) if _ccw_contains(a, b, ar) else (b, a)
            if not _ccw_contains(lo, hi, ar):
                continue
            if (hi - lo) % (2.0 * math.pi) <= math.pi + 1e-9:
                return (vertex,
                        (vertex[0] + radius * math.cos(lo),
                         vertex[1] + radius * math.sin(lo)),
                        (vertex[0] + radius * math.cos(hi),
                         vertex[1] + radius * math.sin(hi)))
    return None


def dim_angular(vertex, p1, p2, location, *, region=None, text: str = "<>",
                text_rotation: float | None = None) -> AddDimensionCommand:
    """DIMANGULAR: the CCW angle p1 -> p2 around ``vertex``. When ``region``
    is given (the location or the Quadrant pick), the points are reordered so
    the dimensioned angle is the one containing it; None keeps the order
    (the arc path always dimensions the arc's own included angle)."""
    if region is not None:
        p1, p2 = angular_points(vertex, p1, p2, region)
    q1, q2 = p1, p2

    def factory(msp, document):
        return msp.add_angular_dim_3p(
            base=(location[0], location[1]), center=(vertex[0], vertex[1]),
            p1=(q1[0], q1[1]), p2=(q2[0], q2[1]),
            text=text, text_rotation=text_rotation,
            dimstyle=_current_dimstyle(document))
    return AddDimensionCommand(factory)


def dim_arc(center, radius: float, start_angle: float, end_angle: float,
            location, *, text: str = "<>",
            text_rotation: float | None = None) -> AddDimensionCommand:
    """DIMARC: arc-length dimension (angles in degrees, CCW start->end).
    The dimension arc sits at the location pick's distance from the arc."""
    distance = max(math.dist(location, center) - radius, 0.1 * radius)

    def factory(msp, document):
        return msp.add_arc_dim_cra(
            center=(center[0], center[1]), radius=radius,
            start_angle=start_angle, end_angle=end_angle, distance=distance,
            text=text, text_rotation=text_rotation,
            dimstyle=_current_dimstyle(document))
    return AddDimensionCommand(factory)


def clamp_angle_to_arc(pick, center, start_angle: float,
                       end_angle: float) -> float:
    """The pick's angle (degrees) clamped into the arc's CCW sweep — the
    Partial option accepts points anywhere and uses the nearest arc point."""
    two_pi = 360.0
    a = math.degrees(math.atan2(pick[1] - center[1], pick[0] - center[0]))
    sweep = (end_angle - start_angle) % two_pi or two_pi
    rel = (a - start_angle) % two_pi
    if rel <= sweep:
        return start_angle + rel
    # outside: clamp to the nearer endpoint
    past_end = rel - sweep
    before_start = two_pi - rel
    return end_angle if past_end <= before_start else start_angle


def dim_ordinate(feature, leader_end, *, dtype: str | None = None,
                 text: str = "<>",
                 text_rotation: float | None = None) -> AddDimensionCommand:
    """DIMORDINATE: X or Y datum from the UCS origin. Auto choice (official
    convention): a mostly-vertical leader writes the X datum, a mostly-
    horizontal one the Y datum. ``dtype`` = "X"/"Y" forces it."""
    dx, dy = leader_end[0] - feature[0], leader_end[1] - feature[1]
    if dtype is None:
        dtype = "X" if abs(dy) >= abs(dx) else "Y"

    def factory(msp, document):
        fn = msp.add_ordinate_x_dim if dtype == "X" else msp.add_ordinate_y_dim
        return fn(feature_location=(feature[0], feature[1]), offset=(dx, dy),
                  text=text, dimstyle=_current_dimstyle(document),
                  dxfattribs=_text_rotation_attribs(text_rotation))
    return AddDimensionCommand(factory)


def center_mark(entity):
    """DIMCENTER: center mark / center lines for an arc or circle, per the
    current style's DIMCEN (0 = nothing -> None, >0 = mark of that size,
    <0 = mark plus center lines extending |DIMCEN| outside — the exact
    geometry AutoCAD and ezdxf's radius renderer draw). Plain LINEs."""
    from core.commands import CompositeCommand

    doc = entity.doc
    name = doc.header.get("$DIMSTYLE", "Standard")
    size = 2.5
    if name in doc.dimstyles:
        size = doc.dimstyles.get(name).dxf.get("dimcen", 2.5)
    if not size:
        return None
    s = abs(size)
    c = entity.dxf.center
    cx, cy, r = c.x, c.y, float(entity.dxf.radius)
    lines = [((cx - s, cy), (cx + s, cy)), ((cx, cy - s), (cx, cy + s))]
    if size < 0 and r + s >= 2.0 * s:
        far = r + s
        lines += [((cx + 2 * s, cy), (cx + far, cy)),
                  ((cx - 2 * s, cy), (cx - far, cy)),
                  ((cx, cy + 2 * s), (cx, cy + far)),
                  ((cx, cy - 2 * s), (cx, cy - far))]
    return CompositeCommand("DIMCENTER", [add_line(a, b) for a, b in lines])


class PasteCommand(Command):
    """Paste clipboard entities, translated so the base point lands on the
    target. Each paste makes fresh copies, so the clipboard stays reusable."""

    name = "PASTE"

    def __init__(self, sources, dx: float, dy: float) -> None:
        self.sources = list(sources)
        self.dx = dx
        self.dy = dy
        self.copies: list = []

    def do(self, document) -> None:
        from ezdxf.math import Matrix44

        msp = document.modelspace()
        m = Matrix44.translate(self.dx, self.dy, 0.0)
        self.copies = []
        for e in self.sources:
            clone = e.copy()
            clone.transform(m)
            msp.add_entity(clone)
            self.copies.append(clone)
        document.dirty = True

    def undo(self, document) -> None:
        msp = document.modelspace()
        self.removed_handles = [c.dxf.handle for c in self.copies]
        for clone in self.copies:
            msp.delete_entity(clone)
        self.copies = []
        document.dirty = True


def move_entities(entities, dx: float, dy: float) -> TransformCommand:
    from ezdxf.math import Matrix44

    return TransformCommand("MOVE", entities, Matrix44.translate(dx, dy, 0.0))


def rotate_entities(entities, base, angle_deg: float) -> TransformCommand:
    import math as _math

    from ezdxf.math import Matrix44

    m = (Matrix44.translate(-base[0], -base[1], 0.0)
         @ Matrix44.z_rotate(_math.radians(angle_deg))
         @ Matrix44.translate(base[0], base[1], 0.0))
    return TransformCommand("ROTATE", entities, m)


def scale_entities(entities, base, factor: float) -> TransformCommand:
    from ezdxf.math import Matrix44

    m = (Matrix44.translate(-base[0], -base[1], 0.0)
         @ Matrix44.scale(factor, factor, factor)
         @ Matrix44.translate(base[0], base[1], 0.0))
    return TransformCommand("SCALE", entities, m)


def _mirror_matrix(p1, p2):
    import math as _math

    from ezdxf.math import Matrix44

    ang = _math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    return (Matrix44.translate(-p1[0], -p1[1], 0.0)
            @ Matrix44.z_rotate(-ang)
            @ Matrix44.scale(1.0, -1.0, 1.0)
            @ Matrix44.z_rotate(ang)
            @ Matrix44.translate(p1[0], p1[1], 0.0))


def mirror_entities(entities, p1, p2, keep_source: bool = True) -> Command:
    m = _mirror_matrix(p1, p2)
    if keep_source:
        cmd = CopyEntitiesCommand(entities, m)
        cmd.name = "MIRROR"
        return cmd
    return TransformCommand("MIRROR", entities, m)


def copy_entities(entities, dx: float, dy: float) -> CopyEntitiesCommand:
    from ezdxf.math import Matrix44

    return CopyEntitiesCommand(entities, Matrix44.translate(dx, dy, 0.0))


def attach_image(path: str, size_px: tuple[int, int],
                 insert, scale: float) -> AddEntityCommand:
    """IMAGEATTACH: an IMAGE entity referencing ``path`` (never embedded).

    AutoCAD's base size with no resolution info: one drawing unit per
    pixel, times the scale factor. The IMAGEDEF object is created by the
    factory; undo removes the entity and leaves the def, which is inert.
    """
    width, height = size_px

    def factory(msp):
        image_def = msp.doc.add_image_def(filename=str(path),
                                          size_in_pixel=(width, height))
        return msp.add_image(image_def, insert=insert,
                             size_in_units=(width * scale, height * scale))

    command = AddEntityCommand("IMAGEATTACH", factory)
    # The incremental-display overlay only tessellates vectors: it would
    # show the frame and never the pixels, and below the merge threshold
    # no regen is ever scheduled — the image simply never appeared. Like
    # a dimension's block, an image needs the real regen.
    command.needs_regen = True
    return command


class SnapshotCommand(Command):
    """Undo via full DXF-tag snapshots of the edited entities.

    Grip edits mutate entities in place through many small setters; capturing
    a before/after tag copy is the simplest exact-undo route (the entity keeps
    its handle, so the round-trip stays conservative).
    """

    name = "GRIP"

    def __init__(self, entities) -> None:
        self.entities = list(entities)
        self._before = [e.copy() for e in entities]
        self._after = None

    def commit(self, document) -> None:
        """Call after the in-place edit; captures the 'after' state."""
        self._after = [e.copy() for e in self.entities]
        document.dirty = True

    def do(self, document) -> None:
        if self._after is None:
            return  # first application already happened in place
        for e, snap in zip(self.entities, self._after):
            _restore_entity(e, snap)
        document.dirty = True

    def undo(self, document) -> None:
        for e, snap in zip(self.entities, self._before):
            _restore_entity(e, snap)
        document.dirty = True


def _restore_entity(entity, snapshot) -> None:
    """Copy snapshot's DXF attributes back onto entity (keeps its handle)."""
    wanted = snapshot.dxf.all_existing_dxf_attribs()
    # Attributes the edit ADDED have no entry in the snapshot; copying alone
    # would leave them behind (setting style on an entity that used the
    # default survived its own undo this way).
    for key in list(entity.dxf.all_existing_dxf_attribs()):
        if key not in wanted and key != "handle":
            entity.dxf.discard(key)
    for key, value in wanted.items():
        if key == "handle":
            continue
        entity.dxf.set(key, value)
    if entity.dxftype() == "LWPOLYLINE":
        entity.set_points(snapshot.get_points("xyseb"), format="xyseb")
    elif entity.dxftype() == "MTEXT":
        # The content lives in the entity's text stream, not in a DXF
        # attribute — without this, undoing an MTEXT edit restored the
        # position and silently kept the new words. The column layout is
        # object state too, not a DXF attribute.
        entity.text = snapshot.text
        entity._columns = snapshot._columns


def apply_in_place(history, entities, mutate) -> None:
    """Run an in-place mutation on ``entities`` with exact snapshot undo.

    For edits that ezdxf performs through many small setters (a Vec3 component,
    text contents) a before/after tag snapshot is the simplest reversible route
    — same mechanism the grip drag uses. Records straight onto the history so
    the change joins the normal undo stack.
    """
    snap = SnapshotCommand(entities)
    mutate()
    snap.commit(history.document)
    history._undo.append(snap)
    history._redo.clear()


class SetPropertyCommand(Command):
    """Set a DXF property (layer/color/linetype/lineweight) on entities.

    Color/linetype/lineweight take AutoCAD's ByLayer sentinels: color 256 =
    ByLayer, linetype "ByLayer", lineweight -1 = ByLayer. Undo restores each
    entity's previous value individually.
    """

    name = "properties"

    def __init__(self, entities, prop: str, value) -> None:
        self.entities = list(entities)
        self.prop = prop
        self.value = value
        self._old = []

    def do(self, document) -> None:
        self._old = []
        for e in self.entities:
            self._old.append(e.dxf.get(self.prop, None))
            e.dxf.set(self.prop, self.value)
        document.dirty = True

    def undo(self, document) -> None:
        for e, old in zip(self.entities, self._old):
            if old is None:
                e.dxf.discard(self.prop)
            else:
                e.dxf.set(self.prop, old)
        document.dirty = True


def add_ellipse(center, major_axis, ratio: float,
                start_param: float = 0.0,
                end_param: float = math.tau) -> AddEntityCommand:
    """major_axis: vector from center to the major-axis endpoint. ratio =
    minor/major in (0, 1]. Non-default params make an elliptical arc."""
    return AddEntityCommand(
        "ELLIPSE",
        lambda msp: msp.add_ellipse((center[0], center[1]),
                                    major_axis=(major_axis[0], major_axis[1]),
                                    ratio=ratio, start_param=start_param,
                                    end_param=end_param))


def _ellipse_normalize(center, first_axis, other_dist: float):
    """The FIRST axis may be the minor one (official ELLIPSE rule): when the
    other half-axis is longer, the axes swap — never clamp the ratio."""
    first_len = math.hypot(*first_axis)
    if first_len <= 1e-12:
        return center, first_axis, 1.0
    if other_dist <= first_len:
        return center, first_axis, other_dist / first_len
    # perpendicular (CCW) axis becomes the major one
    scale = other_dist / first_len
    major = (-first_axis[1] * scale, first_axis[0] * scale)
    return center, major, first_len / other_dist


def ellipse_from_axis(p1, p2, other_dist: float):
    """Axis endpoints p1,p2 + distance to the other axis -> (center, major, ratio)."""
    center = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
    first = ((p2[0] - p1[0]) / 2.0, (p2[1] - p1[1]) / 2.0)
    return _ellipse_normalize(center, first, other_dist)


def ellipse_from_center(center, axis_end, other_dist: float):
    """Center + first-axis endpoint + distance to the other axis."""
    first = (axis_end[0] - center[0], axis_end[1] - center[1])
    return _ellipse_normalize(center, first, other_dist)


def ellipse_param_from_angle(ratio: float, angle_deg: float) -> float:
    """True angle from the center (relative to the major axis) -> the DXF
    parametric angle t of p(t) = c + a·cos(t) + b·sin(t)."""
    a = math.radians(angle_deg)
    return math.atan2(math.sin(a), max(ratio, 1e-12) * math.cos(a)) % math.tau


def add_point(pos) -> AddEntityCommand:
    return AddEntityCommand(
        "POINT", lambda msp: msp.add_point((pos[0], pos[1])))


# -- construction lines (XLINE / RAY) ------------------------------------------

def add_xline(point, direction_deg: float) -> AddEntityCommand:
    """Infinite construction line through ``point`` at ``direction_deg``."""
    rad = math.radians(direction_deg)
    unit = (math.cos(rad), math.sin(rad))
    return AddEntityCommand(
        "XLINE", lambda msp: msp.add_xline((point[0], point[1], 0.0),
                                           (unit[0], unit[1], 0.0)))


def add_ray(point, direction_deg: float) -> AddEntityCommand:
    """Semi-infinite RAY from ``point`` toward ``direction_deg``."""
    rad = math.radians(direction_deg)
    unit = (math.cos(rad), math.sin(rad))
    return AddEntityCommand(
        "RAY", lambda msp: msp.add_ray((point[0], point[1], 0.0),
                                       (unit[0], unit[1], 0.0)))


# -- DIVIDE / MEASURE: arc-length sampling along an entity ----------------------

def _entity_polyline(entity):
    """(points, closed) — the entity flattened to a fine 2D polyline."""
    from ezdxf import path as ezpath

    p = ezpath.make_path(entity)
    # tolerance relative to size so splines and arcs sample smoothly
    box_pts = list(p.flattening(1.0))
    if len(box_pts) < 2:
        raise ValueError("degenerate entity")
    xs = [v.x for v in box_pts]
    ys = [v.y for v in box_pts]
    diag = math.hypot(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    pts = [(v.x, v.y) for v in p.flattening(diag / 4000.0)]
    return pts, p.is_closed


def _resample(points, positions):
    """[(x, y, tangent_deg)] at the given arc-length positions."""
    lengths = [0.0]
    for a, b in zip(points, points[1:]):
        lengths.append(lengths[-1] + math.dist(a, b))
    total = lengths[-1]
    out = []
    seg = 1
    for s in positions:
        s = min(max(s, 0.0), total)
        while seg < len(lengths) - 1 and lengths[seg] < s:
            seg += 1
        a, b = points[seg - 1], points[seg]
        span = lengths[seg] - lengths[seg - 1] or 1.0
        t = (s - lengths[seg - 1]) / span
        out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t,
                    math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))))
    return out


def divide_samples(entity, segments: int):
    """DIVIDE: sample points along the entity — (n-1) for open objects,
    n for closed ones (no point coincides with an endpoint)."""
    if not 2 <= segments <= 32767:
        raise ValueError("between 2 and 32767 segments")
    points, closed = _entity_polyline(entity)
    total = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
    if total <= 0.0:
        raise ValueError("zero-length entity")
    if closed:
        positions = [total * i / segments for i in range(segments)]
    else:
        positions = [total * i / segments for i in range(1, segments)]
    return _resample(points, positions)


def measure_samples(entity, step: float, pick):
    """MEASURE: points every ``step`` starting at the end nearest ``pick``;
    the remainder stays at the far end (AutoCAD)."""
    if step <= 0.0:
        raise ValueError("segment length must be positive")
    points, closed = _entity_polyline(entity)
    if not closed and pick is not None:
        if math.dist(pick, points[-1]) < math.dist(pick, points[0]):
            points = points[::-1]
    total = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
    if total <= 0.0:
        raise ValueError("zero-length entity")
    positions = []
    s = step
    while s < total - 1e-9:
        positions.append(s)
        s += step
    return _resample(points, positions)


# -- REVCLOUD -------------------------------------------------------------------

def _loop_is_ccw(points) -> bool:
    area = 0.0
    for a, b in zip(points, points[1:] + points[:1]):
        area += a[0] * b[1] - b[0] * a[1]
    return area > 0.0


def revcloud_vertices(loop, arc_chord: float, reverse: bool = False,
                      calligraphy: bool = False) -> list:
    """A revision cloud as closed xyseb vertices: the loop resampled at the
    chord length, every chord bulged OUTWARD (~110 degrees); Reverse flips
    the convexity; Calligraphy tapers each arc's width."""
    if arc_chord <= 0.0:
        raise ValueError("arc length must be positive")
    pts = [(p[0], p[1]) for p in loop]
    if len(pts) < 3:
        raise ValueError("need at least 3 points")
    if math.dist(pts[0], pts[-1]) > 1e-9:
        pts.append(pts[0])
    total = sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
    count = max(int(round(total / arc_chord)), 3)
    samples = _resample(pts, [total * i / count for i in range(count)])
    ring = [(x, y) for x, y, _t in samples]
    outward_sign = -1.0 if _loop_is_ccw(ring) else 1.0   # right of travel
    if reverse:
        outward_sign = -outward_sign
    bulge = outward_sign * math.tan(math.radians(110.0) / 4.0)
    ew = arc_chord * 0.18 if calligraphy else 0.0
    return [(x, y, 0.0, ew, bulge) for x, y in ring]


def _current_text_style(msp) -> str:
    """The document's current text style ($TEXTSTYLE), AutoCAD-style."""
    name = msp.doc.header.get("$TEXTSTYLE", "Standard")
    return name if name in msp.doc.styles else "Standard"


def add_text(pos, text: str, height: float, rotation: float = 0.0,
             align: str = "LEFT", p2=None,
             style: str | None = None) -> AddEntityCommand:
    """TEXT with an AutoCAD justification (TextEntityAlignment name).
    ALIGNED/FIT take ``p2`` as the second baseline point."""
    def make(msp):
        from ezdxf.enums import TextEntityAlignment

        chosen = style if style and style in msp.doc.styles \
            else _current_text_style(msp)
        entity = msp.add_text(
            text, height=height,
            dxfattribs={"rotation": rotation, "style": chosen})
        anchor = getattr(TextEntityAlignment, align, TextEntityAlignment.LEFT)
        if align in ("ALIGNED", "FIT") and p2 is not None:
            entity.set_placement((pos[0], pos[1]), (p2[0], p2[1]),
                                 align=anchor)
        elif align == "LEFT":
            entity.set_placement((pos[0], pos[1]))
        else:
            entity.set_placement((pos[0], pos[1]), align=anchor)
        return entity
    return AddEntityCommand("TEXT", make)


def apply_mtext_bg(entity, bg) -> None:
    """("off",) removes the mask; (aci | "canvas", scale) sets it."""
    if bg is None:
        return
    if bg[0] == "off":
        entity.set_bg_color(None)
    else:
        colour, scale = bg
        entity.set_bg_color("canvas" if colour == "canvas" else int(colour),
                            scale=float(scale))


def apply_mtext_columns(entity, columns) -> None:
    """("off",) clears the layout; (count, height, gutter) sets static ones."""
    if columns is None:
        return
    if columns[0] == "off":
        entity._columns = None
        return
    from ezdxf.entities.mtext import MTextColumns

    count, height, gutter = columns
    count = int(count)
    # The user's box width is the TOTAL width, as in AutoCAD's Column
    # Settings; each column gets its share after the gutters.
    total = float(entity.dxf.width or 10.0)
    column_width = max((total - (count - 1) * float(gutter)) / count,
                       total / (count * 4.0))
    entity.setup_columns(
        MTextColumns.new_static_columns(
            count, column_width, float(gutter), float(height)),
        linked=False)


def add_mtext(p1, p2, text: str, char_height: float,
              style: str | None = None,
              attachment: int = 1,
              line_spacing: float | None = None,
              bg=None, columns=None) -> AddEntityCommand:
    """MTEXT in the box the two corners define.

    ``attachment`` is the MText Justification (1..9, TL..BR): the insert
    point is the matching point OF THE BOX, which is how AutoCAD keeps the
    text inside the rectangle the user dragged whatever the justification.
    """
    width = abs(p2[0] - p1[0])
    x0, x1 = min(p1[0], p2[0]), max(p1[0], p2[0])
    y0, y1 = min(p1[1], p2[1]), max(p1[1], p2[1])
    column = (attachment - 1) % 3          # 0 left, 1 center, 2 right
    row = (attachment - 1) // 3            # 0 top, 1 middle, 2 bottom
    insert = ((x0, (x0 + x1) / 2.0, x1)[column],
              (y1, (y0 + y1) / 2.0, y0)[row])

    def make(msp):
        attribs = {"char_height": char_height,
                   "width": width,
                   "style": style or _current_text_style(msp)}
        if line_spacing and abs(line_spacing - 1.0) > 1e-9:
            # Group 44 + style 1 ("At least"), AutoCAD's own default style.
            attribs["line_spacing_factor"] = float(line_spacing)
            attribs["line_spacing_style"] = 1
        m = msp.add_mtext(text, dxfattribs=attribs)
        m.set_location(insert, attachment_point=attachment)
        apply_mtext_bg(m, bg)
        apply_mtext_columns(m, columns)
        return m
    return AddEntityCommand("MTEXT", make)


def add_arc_sce(start, center, end) -> AddEntityCommand:
    """Arc by Start, Center, End (AutoCAD's second arc method).

    Radius from center->start; ccw from start angle to end angle (the end
    point sets the direction; its distance is ignored, AutoCAD does the same).
    """
    radius = math.hypot(start[0] - center[0], start[1] - center[1])
    a_start = math.degrees(math.atan2(start[1] - center[1], start[0] - center[0]))
    a_end = math.degrees(math.atan2(end[1] - center[1], end[0] - center[0]))
    return AddEntityCommand(
        "ARC", lambda msp: msp.add_arc((center[0], center[1]), radius,
                                       a_start, a_end))
