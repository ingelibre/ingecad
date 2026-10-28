# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Headless side of DIMJOGGED, DIMBREAK, DIMSPACE and QDIM (issue #39).

The interactive tools live in :mod:`tools.dim_commands`; everything here is
a Command over the document or a pure computation, so a script can call it
and a test can check it without a window.

*Jogged* radius dimensions are stored as a radius DIMENSION whose centre is
the override point and whose text carries the true radius; the jog is drawn
into the dimension's own *D block. Any CAD reads it as a radius dimension
(AutoCAD's AcDbRadialDimensionLarge has no renderer in ezdxf).

*Breaks* are cut into the *D block's lines and remembered as XDATA under
the INGECAD appid, so Remove knows what to undo; a later re-render of the
dimension (a style change, DIMTEDIT) draws it whole again -- AutoCAD's own
rule for manual breaks, and the limit of the automatic ones here.
"""
from __future__ import annotations

import math
from typing import Iterable, Optional

from core import xdata
from core.actions import AddDimensionCommand, rerender_dimension
from core.commands import Command, CompositeCommand

Point = tuple[float, float]

#: AutoCAD's default Break size (Symbols and Arrows tab): 0.125" = 3.75 mm.
DEFAULT_BREAK_SIZE = 3.75
XDATA_BREAK_TAG = "DIMBREAK"


# -- style lookups -------------------------------------------------------------

def _style(document, dim):
    name = None
    if dim is not None:
        name = dim.dxf.get("dimstyle", None)
    name = name or document.doc.header.get("$DIMSTYLE", "Standard")
    if name in document.doc.dimstyles:
        return document.doc.dimstyles.get(name)
    return None


def dim_scale(document, dim) -> float:
    style = _style(document, dim)
    scale = style.dxf.get("dimscale", 1.0) if style is not None else 1.0
    return float(scale) or 1.0


def text_height(document, dim) -> float:
    """The height ``dim``'s text is drawn at, DIMSCALE applied."""
    from core.styles import dim_text_height

    if dim is not None:
        try:
            get = dim.override().get
        except Exception:                      # noqa: BLE001 - the style's
            get = None
    else:
        get = None
    if get is None:
        style = _style(document, dim)
        if style is None:
            return 2.5 * dim_scale(document, dim)
        get = style.dxf.get
    return dim_text_height(document.doc, get) * dim_scale(document, dim)


def measurement_text(dim, value: float) -> str:
    """``value`` written the way ``dim`` writes its measurement: its
    DIMLFAC, DIMRND, DIMDEC, DIMZIN and decimal separator, each from the
    dimension's overrides first and then its style -- what a grip-drag
    preview must show so the number does not jump when the drag lands
    ("48.23" in the preview, "48" on the drawing, in Rafael's seventh
    review). DIMRND 0 is AutoCAD's "no rounding", not ezdxf's "drop the
    decimals"."""
    from ezdxf.render.dim_base import format_text

    try:
        override = dim.override()
        get = override.get
        # the renderer's own answer, so the preview and the drawing agree
        separator = override.get_decimal_separator()
    except Exception:                        # noqa: BLE001 - plain defaults
        def get(_key, default=None):
            return default
        separator = "."
    factor = float(get("dimlfac", 1.0) or 1.0)
    if factor < 0.0:            # paper space only; previews are of the model
        factor = 1.0
    rounding = get("dimrnd", None)
    rounding = float(rounding) if rounding else None
    decimals = get("dimdec", 2)
    return format_text(value * factor, dimrnd=rounding,
                       dimdec=int(decimals) if decimals is not None else 2,
                       dimzin=int(get("dimzin", 8) or 0),
                       dimdsep=separator or ".")


def break_size(document, dim) -> float:
    return DEFAULT_BREAK_SIZE * dim_scale(document, dim)


def dimdli(document, dim) -> float:
    style = _style(document, dim)
    value = style.dxf.get("dimdli", 3.75) if style is not None else 3.75
    return float(value or 3.75) * dim_scale(document, dim)


# -- the *D block's lines --------------------------------------------------------

def _block_lines(document, dim) -> list:
    """The LINE entities of a dimension's block that are not Defpoints."""
    name = dim.dxf.get("geometry", None)
    if not name or name not in document.doc.blocks:
        return []
    return [e for e in document.doc.blocks.get(name)
            if e.dxftype() == "LINE" and e.dxf.layer.lower() != "defpoints"]


def _seg(e) -> tuple[Point, Point]:
    s, w = e.dxf.start, e.dxf.end
    return (s.x, s.y), (w.x, w.y)


def _param(p: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy or 1.0
    return ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2


def _seg_distance(p: Point, a: Point, b: Point) -> float:
    u = max(0.0, min(1.0, _param(p, a, b)))
    return math.dist(p, (a[0] + u * (b[0] - a[0]), a[1] + u * (b[1] - a[1])))


def _crossing(a: Point, b: Point, c: Point, d: Point) -> Optional[float]:
    """Parameter along a->b where it crosses segment c->d, or None."""
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    denom = r[0] * s[1] - r[1] * s[0]
    if abs(denom) < 1e-12:
        return None
    qp = (c[0] - a[0], c[1] - a[1])
    t = (qp[0] * s[1] - qp[1] * s[0]) / denom
    u = (qp[0] * r[1] - qp[1] * r[0]) / denom
    if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
        return min(1.0, max(0.0, t))
    return None


def obstacle_segments(entity, distance: float = 0.05) -> list[tuple[Point, Point]]:
    """A crossing object's outline as segments (curves flattened)."""
    from ezdxf import path as ezpath

    try:
        p = ezpath.make_path(entity)
        pts = [(v.x, v.y) for v in p.flattening(distance)]
    except Exception:            # noqa: BLE001 - not a shape we can cross
        return []
    return list(zip(pts, pts[1:]))


def auto_gaps(document, dim, obstacles: Iterable, size: Optional[float] = None
              ) -> list[tuple[str, float, float]]:
    """(line handle, t0, t1) gaps where the dimension's lines cross the
    obstacles, each ``size`` long (the style's Break size by default)."""
    size = break_size(document, dim) if size is None else size
    segments = []
    for obstacle in obstacles:
        segments.extend(obstacle_segments(obstacle))
    gaps = []
    for line in _block_lines(document, dim):
        a, b = _seg(line)
        length = math.dist(a, b) or 1.0
        half = (size / 2.0) / length
        for c, d in segments:
            t = _crossing(a, b, c, d)
            if t is None:
                continue
            gaps.append((line.dxf.handle, max(0.0, t - half), min(1.0, t + half)))
    return gaps


def manual_gap(document, dim, p1: Point, p2: Point) -> list[tuple[str, float, float]]:
    """One gap between two points, on the dimension line nearest to them."""
    lines = _block_lines(document, dim)
    if not lines:
        return []
    line = min(lines, key=lambda e: _seg_distance(p1, *_seg(e))
               + _seg_distance(p2, *_seg(e)))
    a, b = _seg(line)
    t0, t1 = sorted((_param(p1, a, b), _param(p2, a, b)))
    t0, t1 = max(0.0, t0), min(1.0, t1)
    if t1 - t0 <= 1e-9:
        return []
    return [(line.dxf.handle, t0, t1)]


def _cut(document, dim, gaps) -> None:
    by_handle: dict[str, list[tuple[float, float]]] = {}
    for handle, t0, t1 in gaps:
        by_handle.setdefault(handle, []).append((t0, t1))
    block = document.doc.blocks.get(dim.dxf.geometry)
    db = document.doc.entitydb
    for handle, intervals in by_handle.items():
        line = db.get(handle)
        if line is None or not line.is_alive:
            continue
        a, b = _seg(line)
        intervals.sort()
        pieces, cursor = [], 0.0
        for t0, t1 in intervals:
            if t0 > cursor:
                pieces.append((cursor, t0))
            cursor = max(cursor, t1)
        if cursor < 1.0:
            pieces.append((cursor, 1.0))
        attribs = line.dxfattribs()
        for key in ("handle", "owner", "start", "end"):
            attribs.pop(key, None)
        for t0, t1 in pieces:
            block.add_line((a[0] + t0 * (b[0] - a[0]), a[1] + t0 * (b[1] - a[1])),
                           (a[0] + t1 * (b[0] - a[0]), a[1] + t1 * (b[1] - a[1])),
                           dxfattribs=attribs)
        block.delete_entity(line)


def has_breaks(dim) -> bool:
    if not dim.has_xdata(xdata.APPID):
        return False
    return any(code == 1000 and value == XDATA_BREAK_TAG
               for code, value in dim.get_xdata(xdata.APPID))


def _strip_break_tags(tags):
    return [t for t in tags if not (t[0] == 1000 and t[1] == XDATA_BREAK_TAG)
            and t[0] != 1070]


class DimBreakCommand(Command):
    """DIMBREAK Auto/Manual: cut the given gaps into the dimension's block
    and remember them; undo re-renders the block and restores the XDATA."""

    name = "DIMBREAK"
    needs_regen = False

    @property
    def entities(self) -> list:
        return [self.dim]

    def __init__(self, dim, gaps) -> None:
        self.dim = dim
        self.gaps = list(gaps)
        self._old_xdata = None

    def do(self, document) -> None:
        d = self.dim
        self._old_xdata = (list(d.get_xdata(xdata.APPID))
                           if d.has_xdata(xdata.APPID) else None)
        _cut(document, d, self.gaps)
        xdata.ensure_appid(document.doc)
        tags = _strip_break_tags(self._old_xdata or [])
        tags.append((1000, XDATA_BREAK_TAG))
        tags.append((1070, len(self.gaps)))
        d.discard_xdata(xdata.APPID)
        d.set_xdata(xdata.APPID, tags)
        document.dirty = True

    def undo(self, document) -> None:
        d = self.dim
        d.discard_xdata(xdata.APPID)
        if self._old_xdata is not None:
            d.set_xdata(xdata.APPID, self._old_xdata)
        rerender_dimension(document, d)
        document.dirty = True


class DimBreakRemoveCommand(Command):
    """DIMBREAK Remove: the dimension drawn whole again."""

    name = "DIMBREAK"
    needs_regen = False

    @property
    def entities(self) -> list:
        return [self.dim]

    def __init__(self, dim) -> None:
        self.dim = dim
        self._old_xdata = None
        self._old_name = None

    def do(self, document) -> None:
        d = self.dim
        self._old_xdata = (list(d.get_xdata(xdata.APPID))
                           if d.has_xdata(xdata.APPID) else None)
        d.discard_xdata(xdata.APPID)
        kept = _strip_break_tags(self._old_xdata or [])
        if kept:
            d.set_xdata(xdata.APPID, kept)
        # the broken block survives under its name for undo; the dimension
        # gets a fresh one
        self._old_name = d.dxf.get("geometry", None)
        d.dxf.discard("geometry")
        d.render()
        document.dirty = True

    def undo(self, document) -> None:
        d = self.dim
        d.discard_xdata(xdata.APPID)
        if self._old_xdata is not None:
            d.set_xdata(xdata.APPID, self._old_xdata)
        fresh = d.dxf.get("geometry", None)
        if self._old_name and self._old_name in document.doc.blocks:
            d.dxf.geometry = self._old_name
            if fresh and fresh in document.doc.blocks and fresh != self._old_name:
                document.doc.blocks.delete_block(fresh, safe=False)
        else:
            rerender_dimension(document, d)
        document.dirty = True


# -- DIMJOGGED -------------------------------------------------------------------

def jog_points(o: Point, p: Point, jog: Point, height: float) -> list[Point]:
    """The polyline O -> A -> B -> C -> D -> P of a jogged radius line: a
    Z of ``height`` across the line at the projection of ``jog``."""
    dx, dy = p[0] - o[0], p[1] - o[1]
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    t = (jog[0] - o[0]) * ux + (jog[1] - o[1]) * uy
    t = max(height, min(length - height, t))
    half = height / 2.0

    def at(s: float, offset: float = 0.0) -> Point:
        return (o[0] + ux * s + nx * offset, o[1] + uy * s + ny * offset)

    return [o, at(t - height), at(t - half, half), at(t + half, -half),
            at(t + height), p]


class AddJoggedDimensionCommand(AddDimensionCommand):
    """A radius dimension from a centre override, its line jogged."""

    name = "DIMJOGGED"

    def __init__(self, factory, override: Point, jog: Point) -> None:
        super().__init__(factory)
        self._override = override
        self._jog = jog

    def do(self, document) -> None:
        super().do(document)
        d = self.dim
        block = document.doc.blocks.get(d.dxf.geometry)
        height = text_height(document, d)
        o = self._override
        end = d.dxf.defpoint4                    # the point on the arc
        p = (end.x, end.y)
        # ezdxf drew a plain radius: a short line at the text and a centre
        # mark at the override. A jogged radius has neither: its line runs
        # from the override to the arc, with the Z where the user put it.
        attribs = None
        for line in list(block):
            if line.dxftype() != "LINE" or line.dxf.layer.lower() == "defpoints":
                continue
            if attribs is None:
                attribs = line.dxfattribs()
                for key in ("handle", "owner", "start", "end"):
                    attribs.pop(key, None)
            block.delete_entity(line)
        pts = jog_points(o, p, self._jog, height)
        for s, e in zip(pts, pts[1:]):
            block.add_line(s, e, dxfattribs=attribs or {})


def _format_length(document, value: float) -> str:
    dec = int(document.doc.header.get("$DIMDEC", 2))
    text = f"{value:.{dec}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def dim_jogged(center: Point, radius: float, override: Point, location: Point,
               jog: Point, *, text: str = "<>",
               text_rotation: Optional[float] = None) -> AddJoggedDimensionCommand:
    """DIMJOGGED: the dimension line starts at ``override`` and reaches the
    arc where the ray centre->location meets it; the text reads the TRUE
    radius (the stored radius is the override's distance to that point)."""
    from core.actions import _current_dimstyle, _text_rotation_attribs

    dx, dy = location[0] - center[0], location[1] - center[1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        dx, dy, length = 1.0, 0.0, 1.0
    on_arc = (center[0] + radius * dx / length, center[1] + radius * dy / length)
    fake_radius = math.dist(override, on_arc)

    def factory(msp, document):
        label = text
        if label == "<>":
            label = "R" + _format_length(document, radius)
        elif "<>" in label:
            label = label.replace("<>", _format_length(document, radius), 1)
        return msp.add_radius_dim(
            center=(override[0], override[1]), radius=fake_radius,
            location=on_arc, text=label, dimstyle=_current_dimstyle(document),
            dxfattribs=_text_rotation_attribs(text_rotation))

    return AddJoggedDimensionCommand(factory, override, jog)


# -- DIMSPACE --------------------------------------------------------------------

def is_linear(dim) -> bool:
    return dim.dxftype() == "DIMENSION" and (dim.dxf.dimtype & 15) in (0, 1)


def _axis(dim) -> tuple[Point, Point]:
    """(unit normal to the dimension line, the first extension origin)."""
    p1 = dim.dxf.defpoint2
    p2 = dim.dxf.defpoint3
    if (dim.dxf.dimtype & 15) == 1:
        dx, dy = p2.x - p1.x, p2.y - p1.y
    else:
        a = math.radians(dim.dxf.get("angle", 0.0))
        dx, dy = math.cos(a), math.sin(a)
    length = math.hypot(dx, dy) or 1.0
    return (-dy / length, dx / length), (p1.x, p1.y)


def _offset(dim, normal: Point, origin: Point) -> float:
    d = dim.dxf.defpoint
    return (d.x - origin[0]) * normal[0] + (d.y - origin[1]) * normal[1]


def space_plan(document, base, dims, spacing: Optional[float]
               ) -> list[tuple[object, Point]]:
    """(dimension, new defpoint) for every dimension to move: equal
    ``spacing`` from the base outwards, in their present order. None
    spacing = Auto, twice the base style's text height; 0 lines them up."""
    if not is_linear(base):
        return []
    if spacing is None:
        spacing = 2.0 * text_height(document, base)
    normal, origin = _axis(base)
    base_offset = _offset(base, normal, origin)
    others = [d for d in dims if is_linear(d) and d is not base]
    others.sort(key=lambda d: abs(_offset(d, normal, origin) - base_offset))
    plan = []
    for k, d in enumerate(others, start=1):
        current = _offset(d, normal, origin)
        side = 1.0 if current >= base_offset else -1.0
        target = base_offset + side * k * spacing
        shift = target - current
        p = d.dxf.defpoint
        plan.append((d, (p.x + normal[0] * shift, p.y + normal[1] * shift)))
    return plan


class DimSpaceCommand(Command):
    name = "DIMSPACE"
    needs_regen = False

    def __init__(self, plan) -> None:
        self.plan = list(plan)
        self._old = None

    @property
    def entities(self) -> list:
        return [d for d, _ in self.plan]

    def do(self, document) -> None:
        if self._old is None:
            self._old = [(d, (d.dxf.defpoint.x, d.dxf.defpoint.y))
                         for d, _ in self.plan]
        for d, (x, y) in self.plan:
            d.dxf.defpoint = (x, y, 0.0)
            rerender_dimension(document, d)
        document.dirty = True

    def undo(self, document) -> None:
        for d, (x, y) in self._old or []:
            d.dxf.defpoint = (x, y, 0.0)
            rerender_dimension(document, d)
        document.dirty = True


# -- QDIM --------------------------------------------------------------------------

def feature_points(entities) -> list[Point]:
    """The extension-line origins QDIM takes from the selected geometry."""
    from core import ocs

    pts: list[Point] = []
    for e in entities:
        t = e.dxftype()
        if t == "LINE":
            pts += [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
        elif t == "LWPOLYLINE":
            pts += [(p[0], p[1]) for p in ocs.points_wcs(
                e, [(p[0], p[1]) for p in e.get_points("xy")])]
        elif t == "ARC":
            c, r = ocs.center_wcs(e), e.dxf.radius
            for a in ocs.angles_wcs(e):
                pts.append((c.x + r * math.cos(math.radians(a)),
                            c.y + r * math.sin(math.radians(a))))
        elif t == "CIRCLE":
            c = ocs.center_wcs(e)
            pts.append((c.x, c.y))
    return pts


def _dedupe(values: list[float], tol: float = 1e-6) -> list[float]:
    out: list[float] = []
    for v in sorted(values):
        if not out or abs(v - out[-1]) > tol:
            out.append(v)
    return out


def qdim_axis(points: list[Point], position: Point) -> float:
    """0 (horizontal dimensions) when the position sits above or below the
    geometry, 90 when beside it; the farther side wins in between."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    dy = max(y0 - position[1], position[1] - y1, 0.0)
    dx = max(x0 - position[0], position[0] - x1, 0.0)
    if dy == 0.0 and dx == 0.0:
        return 0.0 if (x1 - x0) >= (y1 - y0) else 90.0
    return 0.0 if dy >= dx else 90.0


def qdim_commands(document, entities, position: Point, mode: str,
                  datum: Optional[Point] = None) -> list:
    """The AddDimensionCommands of one QDIM placement, in order."""
    from core import actions

    mode = mode.upper()
    if mode in ("RADIUS", "DIAMETER"):
        from core import ocs

        out = []
        for e in entities:
            if e.dxftype() not in ("CIRCLE", "ARC"):
                continue
            c = ocs.center_wcs(e)
            make = actions.dim_radius if mode == "RADIUS" else actions.dim_diameter
            out.append(make((c.x, c.y), float(e.dxf.radius), position))
        return out
    points = feature_points(entities)
    if not points or (len(points) < 2 and mode != "ORDINATE"):
        return []
    angle = qdim_axis(points, position)
    horizontal = angle == 0.0
    along = 0 if horizontal else 1
    across = 1 - along
    coords = _dedupe([p[along] for p in points])
    origin_of: dict[float, Point] = {}
    for p in points:
        for c in coords:
            if abs(p[along] - c) <= 1e-6:
                origin_of.setdefault(c, p)
    ys = [p[across] for p in points]
    outward = 1.0 if position[across] >= (min(ys) + max(ys)) / 2.0 else -1.0
    step = dimdli(document, None)

    def location(c_mid: float, level: int) -> Point:
        off = position[across] + outward * step * level
        return (c_mid, off) if horizontal else (off, c_mid)

    def linear(c1: float, c2: float, level: int):
        p1, p2 = origin_of[c1], origin_of[c2]
        return actions.dim_linear(p1, p2, location((c1 + c2) / 2.0, level),
                                  angle=angle)

    out = []
    if mode == "CONTINUOUS":
        for c1, c2 in zip(coords, coords[1:]):
            out.append(linear(c1, c2, 0))
    elif mode == "BASELINE":
        start = coords[0]
        if datum is not None:
            start = min(coords, key=lambda c: abs(c - datum[along]))
        others = [c for c in coords if c != start]
        others.sort(key=lambda c: abs(c - start))
        for level, c in enumerate(others):
            out.append(linear(start, c, level))
    elif mode == "STAGGERED":
        lo, hi, level = 0, len(coords) - 1, 0
        while lo < hi:
            out.append(linear(coords[lo], coords[hi], level))
            lo, hi, level = lo + 1, hi - 1, level + 1
    elif mode == "ORDINATE":
        for c in coords:
            feature = origin_of[c]
            leader_end = ((c, position[across]) if horizontal
                          else (position[across], c))
            out.append(actions.dim_ordinate(feature, leader_end,
                                            dtype="X" if horizontal else "Y"))
    return out


def qdim(document, entities, position: Point, mode: str,
         datum: Optional[Point] = None) -> Optional[CompositeCommand]:
    commands = qdim_commands(document, entities, position, mode, datum)
    if not commands:
        return None
    return CompositeCommand("QDIM", commands)
