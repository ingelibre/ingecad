# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""STRETCH, BREAK and JOIN — the geometry, headless and undoable.

Prompts live in ``tools.modify``; this module is the arithmetic and the
Commands, so every one of them is testable without a GUI.

Two rules borrowed from AutoCAD that are easy to get wrong:

* **A stretch is decided vertex by vertex.** What the crossing window
  touched moves; what it did not stays. An object whose defining point is
  inside (a circle's centre, a text's insertion point) moves as a whole,
  because there is nothing in it to stretch.
* **An arc keeps its bulge.** Moving one end of an arc has to produce an
  arc again, and the one AutoCAD produces is the one with the same
  chord-height ratio — the same rule a polyline's arc segments follow.
"""
from __future__ import annotations

import math

from core.actions import ReplaceEntitiesCommand, _restore_entity
from core.commands import Command

Point = tuple[float, float]

# Entities with no vertices to stretch: they move when their defining point
# is caught, and stay put otherwise.
_ANCHOR_ATTR = {
    "CIRCLE": "center",
    "ELLIPSE": "center",
    "INSERT": "insert",
    "TEXT": "insert",
    "ATTDEF": "insert",
    "MTEXT": "insert",
    "POINT": "location",
    "SPLINE": None,          # every control point, or nothing
}


def _inside(point: Point, rects) -> bool:
    for x0, y0, x1, y1 in rects:
        if x0 <= point[0] <= x1 and y0 <= point[1] <= y1:
            return True
    return False


def bulge_of_arc(start_angle: float, end_angle: float) -> float:
    """The bulge (tan of a quarter of the included angle) of a CCW arc."""
    included = math.radians(end_angle - start_angle) % math.tau
    return math.tan(included / 4.0)


def arc_through(start: Point, end: Point, bulge: float):
    """(center, radius, start_angle, end_angle) in degrees, from a bulge."""
    from ezdxf.math import bulge_to_arc

    center, a0, a1, radius = bulge_to_arc(start, end, bulge)
    return ((center.x, center.y), radius,
            math.degrees(a0) % 360.0, math.degrees(a1) % 360.0)


# -- STRETCH -------------------------------------------------------------------

def stretch_points(entity) -> list[Point]:
    """The points a stretch may move, in the order the entity stores them."""
    kind = entity.dxftype()
    if kind == "LINE":
        return [(entity.dxf.start.x, entity.dxf.start.y),
                (entity.dxf.end.x, entity.dxf.end.y)]
    if kind == "LWPOLYLINE":
        return [(p[0], p[1]) for p in entity.get_points("xy")]
    if kind == "POLYLINE":
        return [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
    if kind == "ARC":
        c, r = entity.dxf.center, entity.dxf.radius
        return [(c.x + r * math.cos(math.radians(a)),
                 c.y + r * math.sin(math.radians(a)))
                for a in (entity.dxf.start_angle, entity.dxf.end_angle)]
    attr = _ANCHOR_ATTR.get(kind, "__unknown__")
    if attr:
        try:
            p = entity.dxf.get(attr)
            return [(p.x, p.y)]
        except Exception:
            return []
    return []


def _move_whole(entity, dx: float, dy: float) -> None:
    from ezdxf.math import Matrix44

    entity.transform(Matrix44.translate(dx, dy, 0))


def stretch_entity(entity, rects, dx: float, dy: float) -> bool:
    """Move the caught vertices of one entity. True if anything changed."""
    points = stretch_points(entity)
    if not points:
        return False
    caught = [_inside(p, rects) for p in points]
    if not any(caught):
        return False
    if all(caught):
        _move_whole(entity, dx, dy)
        return True

    kind = entity.dxftype()
    if kind == "LINE":
        if caught[0]:
            s = entity.dxf.start
            entity.dxf.start = (s.x + dx, s.y + dy, s.z)
        if caught[1]:
            e = entity.dxf.end
            entity.dxf.end = (e.x + dx, e.y + dy, e.z)
        return True

    if kind == "LWPOLYLINE":
        moved = []
        for (x, y, sw, ew, bulge), hit in zip(entity.get_points("xyseb"),
                                              caught):
            moved.append((x + dx if hit else x, y + dy if hit else y,
                          sw, ew, bulge))
        entity.set_points(moved, format="xyseb")
        return True

    if kind == "POLYLINE":
        for vertex, hit in zip(entity.vertices, caught):
            if hit:
                loc = vertex.dxf.location
                vertex.dxf.location = (loc.x + dx, loc.y + dy, loc.z)
        return True

    if kind == "ARC":
        # One end caught: rebuild the arc through the moved end, keeping the
        # bulge — the arc AutoCAD leaves behind.
        bulge = bulge_of_arc(entity.dxf.start_angle, entity.dxf.end_angle)
        start, end = points
        if caught[0]:
            start = (start[0] + dx, start[1] + dy)
        if caught[1]:
            end = (end[0] + dx, end[1] + dy)
        center, radius, a0, a1 = arc_through(start, end, bulge)
        entity.dxf.center = (center[0], center[1], entity.dxf.center.z)
        entity.dxf.radius = radius
        entity.dxf.start_angle = a0
        entity.dxf.end_angle = a1
        return True

    _move_whole(entity, dx, dy)
    return True


class StretchCommand(Command):
    """STRETCH over the rectangles the crossing selection covered."""

    name = "STRETCH"

    def __init__(self, entities, rects, dx: float, dy: float) -> None:
        self.entities = list(entities)
        self.rects = [tuple(r) for r in rects]
        self.dx = float(dx)
        self.dy = float(dy)
        self._before: list = []

    def do(self, document) -> None:
        self._before = [e.copy() for e in self.entities]
        for entity in self.entities:
            try:
                stretch_entity(entity, self.rects, self.dx, self.dy)
            except Exception:
                pass          # one odd entity must not abort the command
        document.dirty = True

    def undo(self, document) -> None:
        for entity, snap in zip(self.entities, self._before):
            _restore_entity(entity, snap)
        document.dirty = True


def stretch_entities(entities, rects, dx: float, dy: float) -> StretchCommand:
    return StretchCommand(entities, rects, dx, dy)


# -- BREAK ---------------------------------------------------------------------

def _param_on_line(entity, point: Point) -> float:
    s, e = entity.dxf.start, entity.dxf.end
    dx, dy = e.x - s.x, e.y - s.y
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return 0.0
    return ((point[0] - s.x) * dx + (point[1] - s.y) * dy) / length2


def _point_at(entity, t: float) -> Point:
    s, e = entity.dxf.start, entity.dxf.end
    return (s.x + t * (e.x - s.x), s.y + t * (e.y - s.y))


def _angle_on_circle(center, point: Point) -> float:
    return math.degrees(math.atan2(point[1] - center.y,
                                   point[0] - center.x)) % 360.0


def _sweep(a0: float, a1: float) -> float:
    return (a1 - a0) % 360.0


def break_pieces(entity, first: Point, second: Point):
    """What survives a BREAK, as a list of geometry descriptions.

    Each piece is ``("LINE", p1, p2)`` or ``("ARC", center, radius, a0, a1)``
    or ``("LWPOLYLINE", points_xyseb, closed)``. An empty list means the whole
    object goes; None means this type cannot be broken.
    """
    kind = entity.dxftype()

    if kind == "LINE":
        t1, t2 = _param_on_line(entity, first), _param_on_line(entity, second)
        lo, hi = (t1, t2) if t1 <= t2 else (t2, t1)
        lo, hi = max(0.0, lo), min(1.0, hi)
        pieces = []
        if lo > 1e-12:
            pieces.append(("LINE", _point_at(entity, 0.0), _point_at(entity, lo)))
        if hi < 1.0 - 1e-12:
            pieces.append(("LINE", _point_at(entity, hi), _point_at(entity, 1.0)))
        return pieces

    if kind == "CIRCLE":
        # A broken circle becomes the arc that runs counter-clockwise from
        # the first point to the second (BREAK, p.270).
        c, r = entity.dxf.center, entity.dxf.radius
        a1 = _angle_on_circle(c, first)
        a2 = _angle_on_circle(c, second)
        if abs(_sweep(a2, a1)) < 1e-9:
            return []
        return [("ARC", (c.x, c.y), r, a2, a1)]

    if kind == "ARC":
        c, r = entity.dxf.center, entity.dxf.radius
        a0, a1 = entity.dxf.start_angle % 360.0, entity.dxf.end_angle % 360.0
        p = sorted((_angle_on_circle(c, first), _angle_on_circle(c, second)),
                   key=lambda a: _sweep(a0, a))
        cut_lo, cut_hi = p
        pieces = []
        if _sweep(a0, cut_lo) > 1e-9:
            pieces.append(("ARC", (c.x, c.y), r, a0, cut_lo))
        if _sweep(cut_hi, a1) > 1e-9:
            pieces.append(("ARC", (c.x, c.y), r, cut_hi, a1))
        return pieces

    if kind == "LWPOLYLINE":
        return _break_polyline(entity, first, second)

    return None


def _polyline_position(points, closed: bool, point: Point):
    """(segment index, t within it) of the point nearest to the polyline."""
    best = None
    spans = list(zip(points, points[1:]))
    if closed and len(points) > 2:
        spans.append((points[-1], points[0]))
    for index, (a, b) in enumerate(spans):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length2 = dx * dx + dy * dy
        t = 0.0 if length2 == 0 else max(0.0, min(
            1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length2))
        px, py = a[0] + t * dx, a[1] + t * dy
        distance = math.hypot(point[0] - px, point[1] - py)
        if best is None or distance < best[0]:
            best = (distance, index, t, (px, py))
    return best


def _break_polyline(entity, first: Point, second: Point):
    """Split a polyline at two points, keeping the outer runs.

    Bulges of untouched segments ride along; a segment that is cut has its
    bulge dropped, because half of an arc with the same bulge is a different
    arc and inventing one silently would move the drawing.
    """
    raw = list(entity.get_points("xyseb"))
    points = [(p[0], p[1]) for p in raw]
    closed = bool(entity.closed)
    a = _polyline_position(points, closed, first)
    b = _polyline_position(points, closed, second)
    if a is None or b is None:
        return None
    if (a[1], a[2]) > (b[1], b[2]):
        a, b = b, a
    _da, i1, t1, cut1 = a
    _db, i2, t2, cut2 = b

    def row(x, y, bulge=0.0):
        return (x, y, 0.0, 0.0, bulge)

    head = [row(*p, raw[k][4] if k < i1 else 0.0)
            for k, p in enumerate(points[:i1 + 1])]
    head.append(row(*cut1))
    tail = [row(*cut2, 0.0)]
    tail.extend(row(*p, raw[k][4])
                for k, p in enumerate(points) if k > i2)

    pieces = []
    if len(head) > 1:
        pieces.append(("LWPOLYLINE", head, False))
    if len(tail) > 1:
        pieces.append(("LWPOLYLINE", tail, False))
    return pieces


def _factory_for(piece, template):
    """A callable that adds one piece to a modelspace, styled like the source."""
    attribs = _style_of(template)

    def build(msp):
        kind = piece[0]
        if kind == "LINE":
            return msp.add_line(piece[1], piece[2], dxfattribs=dict(attribs))
        if kind == "ARC":
            _k, center, radius, a0, a1 = piece
            return msp.add_arc(center, radius, a0, a1,
                               dxfattribs=dict(attribs))
        _k, points, closed = piece
        poly = msp.add_lwpolyline(points, format="xyseb",
                                  dxfattribs=dict(attribs))
        poly.closed = closed
        return poly

    return build


def inherit_style(entity, template) -> object:
    """Give ``entity`` the properties of ``template`` and return it.

    TRIM, EXTEND, FILLET and CHAMFER hand back pieces of the objects they
    edited: in AutoCAD those pieces ARE the object, shortened, so they keep
    its layer, colour, linetype, lineweight and the rest. IngeCAD builds new
    entities instead, which means the properties have to be carried across
    by hand — without this they were born on whatever layer happened to be
    current, and a wall trimmed on layer MUROS came back on layer 0.

    XDATA travels too: it is somebody else's data hanging off that object,
    and the conservative round-trip is the promise this project is built on.
    """
    if template is None or entity is None:
        return entity
    for name, value in _style_of(template).items():
        try:
            entity.dxf.set(name, value)
        except Exception:
            pass
    xdata = getattr(template, "xdata", None)
    for appid in list(getattr(xdata, "data", {}) or {}):
        try:
            entity.set_xdata(appid, list(template.get_xdata(appid)))
        except Exception:
            pass
    return entity


def common_style_source(entities):
    """The object new geometry should look like, or None to leave it alone.

    A fillet arc between two objects of the same layer belongs on that
    layer; between two different ones there is no such answer, and the
    current settings decide — which is what AutoCAD does.
    """
    alive = [e for e in entities if e is not None]
    if not alive:
        return None
    first = _style_of(alive[0])
    for other in alive[1:]:
        if _style_of(other) != first:
            return None
    return alive[0]


def _style_of(entity) -> dict:
    keep = ("layer", "color", "linetype", "lineweight", "ltscale",
            "transparency", "true_color")
    attribs = {}
    for name in keep:
        try:
            value = entity.dxf.get(name)
        except Exception:
            continue
        if value is not None:
            attribs[name] = value
    return attribs


def break_entity(entity, first: Point, second: Point):
    """BREAK. Returns a Command, or None when the type cannot be broken."""
    pieces = break_pieces(entity, first, second)
    if pieces is None:
        return None
    return ReplaceEntitiesCommand(
        "BREAK", [entity], [_factory_for(p, entity) for p in pieces])


# -- JOIN ----------------------------------------------------------------------

def _line_ends(entity):
    s, e = entity.dxf.start, entity.dxf.end
    return (s.x, s.y), (e.x, e.y)


def _collinear(a, b, tol: float = 1e-7) -> bool:
    (ax, ay), (bx, by) = a
    (cx, cy), (dx, dy) = b
    v1 = (bx - ax, by - ay)
    v2 = (dx - cx, dy - cy)
    cross = v1[0] * v2[1] - v1[1] * v2[0]
    scale = max(math.hypot(*v1) * math.hypot(*v2), 1e-12)
    if abs(cross) / scale > tol:
        return False
    # Same infinite line, not just parallel.
    offset = (cx - ax, cy - ay)
    cross2 = v1[0] * offset[1] - v1[1] * offset[0]
    return abs(cross2) / max(math.hypot(*v1), 1e-12) <= tol * 1000.0


def join_pieces(entities):
    """The single object a JOIN produces, or None when they cannot join.

    Returns ``(piece, reason)``: ``piece`` as in :func:`break_pieces`, or
    ``(None, reason)`` with a message the prompt can print.
    """
    if len(entities) < 2:
        return None, "need"
    kinds = {e.dxftype() for e in entities}

    if kinds == {"LINE"}:
        ends = [_line_ends(e) for e in entities]
        base = ends[0]
        if not all(_collinear(base, other) for other in ends[1:]):
            # Not one straight line — but lines that touch end to end are a
            # polyline, which is what AutoCAD produces for them.
            return _as_polyline(entities, "collinear")
        points = [p for pair in ends for p in pair]
        direction = (base[1][0] - base[0][0], base[1][1] - base[0][1])
        if math.hypot(*direction) == 0:
            return None, "collinear"
        along = sorted(points,
                       key=lambda p: p[0] * direction[0] + p[1] * direction[1])
        return ("LINE", along[0], along[-1]), ""

    if kinds == {"ARC"}:
        centers = [(e.dxf.center.x, e.dxf.center.y) for e in entities]
        radii = [float(e.dxf.radius) for e in entities]
        if any(math.dist(centers[0], c) > 1e-7 for c in centers[1:]) or \
                any(abs(radii[0] - r) > 1e-7 for r in radii[1:]):
            return _as_polyline(entities, "same circle")
        # Counter-clockwise from the source arc, as AutoCAD does.
        source = entities[0]
        start = source.dxf.start_angle % 360.0
        end = source.dxf.end_angle % 360.0
        for arc in entities[1:]:
            a0 = arc.dxf.start_angle % 360.0
            a1 = arc.dxf.end_angle % 360.0
            if _sweep(start, a0) >= _sweep(start, end):
                end = a1
        return ("ARC", centers[0], radii[0], start, end), ""

    if kinds <= {"LINE", "ARC", "LWPOLYLINE"}:
        return _as_polyline(entities, "contiguous")

    return None, "type"


def _as_polyline(entities, fallback_reason: str):
    """Chain the objects into one polyline, or explain why they will not."""
    if not {e.dxftype() for e in entities} <= {"LINE", "ARC", "LWPOLYLINE"}:
        return None, "type"
    chain = _chain(entities)
    if chain is None:
        return None, fallback_reason
    return ("LWPOLYLINE", chain, False), ""


def _entity_chain_rows(entity):
    """(x, y, bulge) rows an entity contributes to a joined polyline."""
    kind = entity.dxftype()
    if kind == "LINE":
        (x1, y1), (x2, y2) = _line_ends(entity)
        return [(x1, y1, 0.0), (x2, y2, 0.0)]
    if kind == "ARC":
        c, r = entity.dxf.center, entity.dxf.radius
        a0, a1 = entity.dxf.start_angle, entity.dxf.end_angle
        bulge = bulge_of_arc(a0, a1)
        p0 = (c.x + r * math.cos(math.radians(a0)),
              c.y + r * math.sin(math.radians(a0)))
        p1 = (c.x + r * math.cos(math.radians(a1)),
              c.y + r * math.sin(math.radians(a1)))
        return [(p0[0], p0[1], bulge), (p1[0], p1[1], 0.0)]
    rows = [(p[0], p[1], p[4]) for p in entity.get_points("xyseb")]
    return rows


def _chain(entities, tol: float = 1e-6):
    """Order the pieces end to end. None if there is a gap."""
    remaining = [_entity_chain_rows(e) for e in entities]
    chain = remaining.pop(0)
    progress = True
    while remaining and progress:
        progress = False
        for index, rows in enumerate(remaining):
            head = (chain[0][0], chain[0][1])
            tail = (chain[-1][0], chain[-1][1])
            first = (rows[0][0], rows[0][1])
            last = (rows[-1][0], rows[-1][1])
            if math.dist(tail, first) <= tol:
                chain = chain[:-1] + [(chain[-1][0], chain[-1][1], rows[0][2])] \
                    + rows[1:]
            elif math.dist(tail, last) <= tol:
                flipped = _reverse_rows(rows)
                chain = chain[:-1] + [(chain[-1][0], chain[-1][1],
                                       flipped[0][2])] + flipped[1:]
            elif math.dist(head, last) <= tol:
                chain = rows[:-1] + chain
            elif math.dist(head, first) <= tol:
                flipped = _reverse_rows(rows)
                chain = flipped[:-1] + chain
            else:
                continue
            remaining.pop(index)
            progress = True
            break
    if remaining:
        return None
    return [(x, y, 0.0, 0.0, bulge) for x, y, bulge in chain]


def _reverse_rows(rows):
    """Reverse a run of (x, y, bulge): bulges shift and change sign."""
    points = [(x, y) for x, y, _b in rows]
    bulges = [b for _x, _y, b in rows]
    out = []
    for index, (x, y) in enumerate(reversed(points)):
        source = len(points) - index - 2
        bulge = -bulges[source] if source >= 0 else 0.0
        out.append((x, y, bulge))
    return out


def join_entities(entities):
    """JOIN. Returns (Command, "") or (None, reason)."""
    piece, reason = join_pieces(entities)
    if piece is None:
        return None, reason
    return ReplaceEntitiesCommand(
        "JOIN", entities, [_factory_for(piece, entities[0])]), ""


# -- ARRAY ---------------------------------------------------------------------

class ArrayCommand(Command):
    """Copies laid out on a grid or around a centre.

    Plain copies, not AutoCAD's associative array object: an associative
    array is a parametric entity a colleague's AutoCAD would have to
    understand on the way back, and the round trip matters more here than
    the parametrics. Explode an AutoCAD array and this is what is left.
    """

    name = "ARRAY"

    def __init__(self, entities, transforms) -> None:
        self.entities = list(entities)
        self._transforms = list(transforms)
        self.new_entities: list = []

    def do(self, document) -> None:
        msp = document.modelspace()
        self.new_entities = []
        for matrix in self._transforms:
            for source in self.entities:
                copy = source.copy()
                copy.transform(matrix)
                msp.add_entity(copy)
                self.new_entities.append(copy)
        document.dirty = True

    def undo(self, document) -> None:
        msp = document.modelspace()
        for entity in self.new_entities:
            msp.delete_entity(entity)
        self.new_entities = []
        document.dirty = True


def array_rect(entities, rows: int, columns: int,
               row_spacing: float, column_spacing: float) -> ArrayCommand:
    """Rows up and columns to the right from the original (-ARRAY, p.155)."""
    from ezdxf.math import Matrix44

    transforms = []
    for r in range(int(rows)):
        for c in range(int(columns)):
            if r == 0 and c == 0:
                continue          # the original stays where it is
            transforms.append(
                Matrix44.translate(c * column_spacing, r * row_spacing, 0))
    return ArrayCommand(entities, transforms)


def array_polar(entities, center: Point, count: int,
                fill_angle: float = 360.0, rotate: bool = True) -> ArrayCommand:
    """Copies around a centre; positive fill angle turns counter-clockwise."""
    from ezdxf.math import Matrix44

    count = int(count)
    if count < 2:
        return ArrayCommand(entities, [])
    # A full turn puts the last copy on top of the original, so the step
    # divides the whole circle; a partial fan spans it end to end.
    divisor = count if abs(abs(fill_angle) - 360.0) < 1e-9 else count - 1
    step = fill_angle / divisor
    transforms = []
    for index in range(1, count):
        angle = math.radians(step * index)
        about = Matrix44.z_rotate(angle)
        move_back = Matrix44.translate(center[0], center[1], 0)
        move_to_origin = Matrix44.translate(-center[0], -center[1], 0)
        if rotate:
            transforms.append(move_to_origin @ about @ move_back)
        else:
            # Same place, same orientation: rotate the anchor only.
            dx = (center[0] + (0 - center[0]) * math.cos(angle)
                  - (0 - center[1]) * math.sin(angle))
            dy = (center[1] + (0 - center[0]) * math.sin(angle)
                  + (0 - center[1]) * math.cos(angle))
            transforms.append(Matrix44.translate(dx, dy, 0))
    return ArrayCommand(entities, transforms)


# -- MATCHPROP -----------------------------------------------------------------

# What the Property Settings dialog copies by default (MATCHPROP, p.1081).
MATCH_PROPERTIES = ("layer", "color", "linetype", "ltscale", "lineweight",
                    "thickness", "transparency", "true_color")

# What an ABSENT attribute means — AutoCAD copies these as values.
_MATCH_DEFAULTS = {"color": 256, "linetype": "ByLayer", "lineweight": -1,
                   "ltscale": 1.0, "thickness": 0.0}


class MatchPropCommand(Command):
    """Copy the source object's properties onto the destination objects."""

    name = "MATCHPROP"

    def __init__(self, source, targets, properties=MATCH_PROPERTIES) -> None:
        self.source = source
        self.targets = list(targets)
        # the display paths collect touched entities from .entities
        self.entities = self.targets
        self.properties = tuple(properties)
        self._before: list = []
        self._before_xdata: list = []
        # A matched dimension re-renders its anonymous *D block, and the
        # overlay draws that through the same frontend the base scene uses
        # -- so the ordinary surgical path (hide the stale base copy, show
        # the restyled entity) is enough. It used to ask for a full regen
        # here, which on a real plan meant waiting seconds with nothing
        # happening: the user reads that as "it did not select it".
        self.needs_regen = False

    def _dim_pair(self, target) -> bool:
        return (self.source.dxftype() == "DIMENSION"
                and target.dxftype() == "DIMENSION")

    def do(self, document) -> None:
        self._before = [e.copy() for e in self.targets]
        self._before_xdata = [
            list(t.get_xdata("ACAD")) if t.has_xdata("ACAD") else None
            for t in self.targets]
        for target in self.targets:
            for name in self.properties:
                if name in ("true_color", "transparency"):
                    # ABSENCE is a value here: a source without true color
                    # or explicit transparency means ByLayer, and leaving
                    # the destination's old override in place would keep
                    # overriding the ACI we just copied.
                    try:
                        if self.source.dxf.hasattr(name):
                            target.dxf.set(name, self.source.dxf.get(name))
                        else:
                            target.dxf.discard(name)
                    except Exception:
                        pass
                    continue
                # An unset attribute still IS the property: no color attr
                # means ByLayer (256), and AutoCAD copies "ByLayer" itself —
                # the old .get(name) with no default skipped it and a
                # ByBlock destination stayed ByBlock.
                try:
                    value = self.source.dxf.get(name, _MATCH_DEFAULTS.get(name))
                except Exception:
                    continue      # attribute not valid for the source type
                if value is None:
                    continue
                try:
                    target.dxf.set(name, value)
                except Exception:
                    pass          # not every property exists on every type
            _match_style(self.source, target)
            if self._dim_pair(target):
                # The reference's Dimension special property: the style AND
                # its overrides (the DSTYLE xdata), and the block re-renders
                # so the destination actually LOOKS like the source —
                # setting dimstyle alone changed nothing visible.
                try:
                    if self.source.has_xdata("ACAD"):
                        target.set_xdata("ACAD",
                                         list(self.source.get_xdata("ACAD")))
                    else:
                        target.discard_xdata("ACAD")
                except Exception:
                    pass
                _rerender_dimension(document, target)
        document.dirty = True

    def undo(self, document) -> None:
        for target, snap, xdata in zip(self.targets, self._before,
                                       self._before_xdata):
            was_dim = self._dim_pair(target)
            edited_block = target.dxf.get("geometry", None) if was_dim else None
            _restore_entity(target, snap)
            if was_dim:
                try:
                    if xdata is None:
                        target.discard_xdata("ACAD")
                    else:
                        target.set_xdata("ACAD", xdata)
                except Exception:
                    pass
                # the restored 'geometry' points at the block do() dropped:
                # render a fresh one and drop the edited block instead
                target.render()
                from core.actions import _stamp_dim_block_byblock

                _stamp_dim_block_byblock(document, target)
                _drop_block(document, edited_block)
        document.dirty = True


def _rerender_dimension(document, dim) -> None:
    from core.actions import _drop_dim_block, _stamp_dim_block_byblock

    old_block = dim.dxf.get("geometry", None)
    dim.render()
    _stamp_dim_block_byblock(document, dim)
    _drop_dim_block(document, old_block)


def _drop_block(document, name) -> None:
    from core.actions import _drop_dim_block

    _drop_dim_block(document, name)


def _match_style(source, target) -> None:
    """The per-type extras AutoCAD copies: text style, dimension style."""
    kinds = {source.dxftype(), target.dxftype()}
    if kinds <= {"TEXT", "MTEXT", "ATTDEF", "ATTRIB"}:
        try:
            target.dxf.style = source.dxf.style
        except Exception:
            pass
        # "changes the text style AND PROPERTIES" (Text special property,
        # p. 1081) — the height crosses TEXT<->MTEXT too, and it must be
        # the EFFECTIVE height: AutoCAD MTEXTs often carry the real height
        # as an inline \H code while char_height holds a residue (0.0019
        # on Marco's plan) — copying the raw attribute shrank the target
        # to that residue.
        height = _effective_text_height(source)
        # The color crosses the same way: the source's EFFECTIVE color
        # lands on the destination's entity, and the destination's own
        # inline color codes are stripped so the new color governs.
        effective = _effective_text_color(source)
        if effective is not None:
            kind, value = effective
            try:
                if kind == "aci":
                    target.dxf.discard("true_color")
                    target.dxf.color = value
                elif kind == "rgb":
                    from ezdxf.colors import rgb2int

                    target.dxf.true_color = rgb2int(value)
                elif kind == "rgb_raw":
                    target.dxf.true_color = value
                if target.dxftype() == "MTEXT":
                    stripped = _strip_mtext_color_codes(target.text)
                    if stripped != target.text:
                        target.text = stripped
            except Exception:
                pass
        if height:
            try:
                if target.dxftype() == "MTEXT":
                    target.dxf.char_height = height
                else:
                    target.dxf.height = height
            except Exception:
                pass
    if source.dxftype() == "DIMENSION" and target.dxftype() == "DIMENSION":
        try:
            target.dxf.dimstyle = source.dxf.dimstyle
        except Exception:
            pass


_MTEXT_COLOR_CODE = None   # compiled lazily


def _strip_mtext_color_codes(text: str) -> str:
    global _MTEXT_COLOR_CODE
    if _MTEXT_COLOR_CODE is None:
        import re

        _MTEXT_COLOR_CODE = re.compile(r"\\[Cc]\d+;")
    return _MTEXT_COLOR_CODE.sub("", text)


def _effective_text_color(entity):
    """("aci", n) or ("rgb", (r, g, b)) the text DISPLAYS with, or None.

    Like the height, an MTEXT's color often lives in an inline backslash-C (ACI)
    or backslash-c (true color) code — our own editor writes them — while the
    entity attribute stays ByLayer. The first visible run decides.
    """
    if entity.dxftype() == "MTEXT":
        try:
            from ezdxf.tools.text import MTextContext, MTextParser, TokenType

            # seed 256: the parser's default aci is 7, which would read as
            # an explicit color on every uncolored text
            ctx = MTextContext()
            ctx.aci = 256
            for token in MTextParser(entity.text, ctx):
                if token.type == TokenType.WORD:
                    if token.ctx.rgb is not None:
                        return ("rgb", token.ctx.rgb)
                    if token.ctx.aci != 256:
                        return ("aci", int(token.ctx.aci))
                    break
        except Exception:
            pass
    if entity.dxf.hasattr("true_color"):
        return ("rgb_raw", int(entity.dxf.true_color))
    color = int(entity.dxf.get("color", 256))
    return ("aci", color) if color != 256 else None


def _effective_text_height(entity) -> float | None:
    """The height the text DISPLAYS at.

    TEXT: the height attribute. MTEXT: char_height unless the content's
    first visible run overrides it with an inline backslash-H code (absolute or
    relative) — the parser resolves either form.
    """
    if entity.dxftype() != "MTEXT":
        return entity.dxf.get("height", None)
    base = float(entity.dxf.get("char_height", 0.0)) or None
    try:
        from ezdxf.tools.text import MTextContext, MTextParser, TokenType

        ctx = MTextContext()
        if base:
            ctx.cap_height = base
        for token in MTextParser(entity.text, ctx):
            if token.type == TokenType.WORD:
                return float(token.ctx.cap_height) or base
    except Exception:
        pass
    return base


def match_properties(source, targets, properties=MATCH_PROPERTIES):
    return MatchPropCommand(source, targets, properties)


# -- PEDIT ---------------------------------------------------------------------

class PolylineEditCommand(Command):
    """One PEDIT operation, with snapshot undo."""

    name = "PEDIT"

    def __init__(self, entity, operation: str, value=None) -> None:
        self.entity = entity
        self.operation = operation
        self.value = value
        self._before = None

    def do(self, document) -> None:
        self._before = self.entity.copy()
        apply_pedit(self.entity, self.operation, self.value)
        document.dirty = True

    def undo(self, document) -> None:
        _restore_entity(self.entity, self._before)
        document.dirty = True


def apply_pedit(entity, operation: str, value=None) -> None:
    if operation == "close":
        entity.closed = True
    elif operation == "open":
        entity.closed = False
    elif operation == "width":
        rows = [(x, y, float(value), float(value), b)
                for x, y, _sw, _ew, b in entity.get_points("xyseb")]
        entity.set_points(rows, format="xyseb")
    elif operation == "reverse":
        rows = _reverse_rows([(x, y, b)
                              for x, y, _sw, _ew, b in
                              entity.get_points("xyseb")])
        entity.set_points([(x, y, 0.0, 0.0, b) for x, y, b in rows],
                          format="xyseb")


def polyline_edit(entity, operation: str, value=None) -> PolylineEditCommand:
    return PolylineEditCommand(entity, operation, value)


def to_polyline(entity):
    """PEDIT on a line or arc: convert it, so it can be edited and joined."""
    kind = entity.dxftype()
    if kind == "LWPOLYLINE":
        return None
    if kind not in ("LINE", "ARC"):
        return None
    rows = _entity_chain_rows(entity)
    piece = ("LWPOLYLINE", [(x, y, 0.0, 0.0, b) for x, y, b in rows], False)
    return ReplaceEntitiesCommand("PEDIT", [entity], [_factory_for(piece, entity)])
