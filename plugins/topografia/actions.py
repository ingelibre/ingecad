# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Topography, headless: every operation is an undoable Command over the
ezdxf document, and every object it makes is a plain DXF entity.

A survey point is a POINT at (E, N, Z) on ``TOPO-PUNTOS`` with its number
and description in XDATA under the ``INGECAD`` APPID, plus up to three
TEXT labels (number, elevation, description) on their own layers, each
label carrying the handle of its point so renumbering can find it. Any
CAD opens the result; only IngeCAD reads the XDATA back.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.actions import AddEntityCommand
from core.commands import Command, CompositeCommand
from core.layers import NewLayerCommand

from .points import SurveyPoint

APPID = "INGECAD"
POINT_TAG = "TOPO-POINT"
LABEL_TAG = "TOPO-LABEL"

#: (layer, ACI colour) for the point and each label kind.
LAYERS = {
    "point": ("TOPO-PUNTOS", 7),
    "number": ("TOPO-NUMEROS", 2),
    "elevation": ("TOPO-COTAS", 3),
    "description": ("TOPO-DESC", 4),
    "annotation": ("TOPO-ROTULOS", 7),
    "table": ("TOPO-CUADROS", 7),
    "grid": ("TOPO-RETICULA", 8),
    "subdivision": ("TOPO-SUBDIV", 1),
    "tin": ("TOPO-TIN", 8),
}
ALL_LABELS = ("number", "elevation", "description")


@dataclass
class LabelStyle:
    text_height: float = 1.0
    labels: tuple = ALL_LABELS
    decimals: int = 2            # of the elevation label


def ensure_appid(doc) -> None:
    if APPID not in doc.appids:
        doc.appids.add(APPID)


class SetHeaderCommand(Command):
    """One header variable, with exact undo ($PDMODE, $PDSIZE)."""

    name = "header variable"

    def __init__(self, key: str, value) -> None:
        self.key = key
        self.value = value
        self._old = None
        self._had = False

    def do(self, document) -> None:
        header = document.doc.header
        self._had = self.key in header
        self._old = header.get(self.key) if self._had else None
        header[self.key] = self.value
        document.dirty = True

    def undo(self, document) -> None:
        header = document.doc.header
        if self._had:
            header[self.key] = self._old
        else:
            try:
                del header[self.key]
            except KeyError:
                pass
        document.dirty = True


#: AutoCAD's PDMODE 3: an X. A new drawing draws a POINT as one pixel
#: (mode 0), which no surveyor can see on a plan; the first import switches
#: the drawing to X markers sized against the labels, and leaves a drawing
#: that already chose a marker alone.
PDMODE_X = 3


def point_display_commands(document, style: "LabelStyle") -> list[Command]:
    header = document.doc.header
    if int(header.get("$PDMODE", 0)) != 0:
        return []
    return [SetHeaderCommand("$PDMODE", PDMODE_X),
            SetHeaderCommand("$PDSIZE", float(style.text_height) * 0.8)]


def layer_commands(document, kinds=("point",) + ALL_LABELS) -> list[Command]:
    """NewLayerCommands for the topography layers still missing."""
    out = []
    for kind in kinds:
        name, color = LAYERS[kind]
        if name not in document.doc.layers:
            out.append(NewLayerCommand(name, color=color))
    return out


def _point_factory(point: SurveyPoint):
    def make(msp):
        ensure_appid(msp.doc)
        entity = msp.add_point((point.east, point.north, point.z))
        entity.set_xdata(APPID, [(1000, POINT_TAG), (1000, point.name),
                                 (1000, point.desc)])
        return entity
    return make


def _label_factory(point_cmd: AddEntityCommand, kind: str, text: str,
                   offset, style: LabelStyle):
    def make(msp):
        ensure_appid(msp.doc)
        anchor = point_cmd.entity
        loc = anchor.dxf.location
        entity = msp.add_text(text, height=style.text_height)
        entity.set_placement((loc.x + offset[0] * style.text_height,
                              loc.y + offset[1] * style.text_height))
        entity.set_xdata(APPID, [(1000, LABEL_TAG), (1000, kind),
                                 (1005, anchor.dxf.handle)])
        return entity
    return make


_OFFSETS = {"number": (0.3, 0.3), "elevation": (0.3, -1.3),
            "description": (0.3, -2.9)}


def label_text(point: SurveyPoint, kind: str, style: LabelStyle) -> str:
    if kind == "number":
        return point.name
    if kind == "elevation":
        return f"{point.z:.{style.decimals}f}"
    return point.desc


def point_commands(point: SurveyPoint, style: LabelStyle) -> list[Command]:
    """The POINT and its labels, as commands in the order they must run."""
    point_cmd = AddEntityCommand("TOPO-POINT", _point_factory(point),
                                 layer=LAYERS["point"][0])
    out: list[Command] = [point_cmd]
    for kind in style.labels:
        text = label_text(point, kind, style)
        if not text:
            continue
        out.append(AddEntityCommand(
            "TOPO-LABEL", _label_factory(point_cmd, kind, text, _OFFSETS[kind], style),
            layer=LAYERS[kind][0]))
    return out


def import_points(document, points, style: LabelStyle | None = None) -> CompositeCommand:
    """All the points, their labels and any missing layer as ONE undo step."""
    style = style or LabelStyle()
    commands = layer_commands(document) + point_display_commands(document, style)
    for point in points:
        commands.extend(point_commands(point, style))
    return CompositeCommand("import points", commands)


def add_point(document, point: SurveyPoint, style: LabelStyle | None = None) -> CompositeCommand:
    """One surveyed point, drawn by hand (PBY)."""
    style = style or LabelStyle()
    return CompositeCommand("survey point",
                            layer_commands(document)
                            + point_display_commands(document, style)
                            + point_commands(point, style))


# -- reading back ----------------------------------------------------------------

def _xdata(entity):
    try:
        return [value for _code, value in entity.get_xdata(APPID)]
    except Exception:
        return None


def is_survey_point(entity) -> bool:
    if entity.dxftype() != "POINT":
        return False
    data = _xdata(entity)
    return bool(data) and data[0] == POINT_TAG


def survey_point(entity) -> SurveyPoint:
    """The point an entity stands for; a bare POINT has no name."""
    loc = entity.dxf.location
    data = _xdata(entity) or []
    name = str(data[1]) if len(data) > 1 and data[0] == POINT_TAG else ""
    desc = str(data[2]) if len(data) > 2 and data[0] == POINT_TAG else ""
    return SurveyPoint(name, loc.x, loc.y, loc.z, desc)


def survey_points(document, entities=None) -> list[SurveyPoint]:
    """The survey points among ``entities`` (or in the current space), in
    drawing order. Bare POINTs count too, numbered by position."""
    source = entities if entities is not None else document.current_space()
    out = []
    for entity in source:
        if entity.dxftype() != "POINT":
            continue
        point = survey_point(entity)
        if not point.name:
            point.name = str(len(out) + 1)
        out.append(point)
    return out


def find_point(document, name: str):
    """The POINT entity numbered ``name``, or None."""
    wanted = name.strip().upper()
    for entity in document.current_space():
        if is_survey_point(entity) and survey_point(entity).name.upper() == wanted:
            return entity
    return None


def next_number(document) -> str:
    """One past the highest numeric point name in the current space."""
    highest = 0
    for entity in document.current_space():
        if is_survey_point(entity):
            name = survey_point(entity).name
            if name.isdigit():
                highest = max(highest, int(name))
    return str(highest + 1)


def labels_of(document, point_entity) -> dict:
    """{kind: TEXT} of the labels hanging from ``point_entity``."""
    handle = point_entity.dxf.handle
    out = {}
    for entity in document.current_space():
        if entity.dxftype() != "TEXT":
            continue
        data = _xdata(entity)
        if data and data[0] == LABEL_TAG and len(data) > 2 and data[2] == handle:
            out[str(data[1])] = entity
    return out


class RenumberCommand(Command):
    """Give the points new numbers (``start``, ``start+step``...) in the
    order given, rewriting their XDATA and their number labels; undo puts
    the old numbers back."""

    name = "renumber points"

    def __init__(self, entities, start: int, step: int = 1) -> None:
        self.handles = [e.dxf.handle for e in entities]
        self.start = start
        self.step = step
        self._old: dict[str, str] = {}

    def _apply(self, document, names: dict[str, str]) -> None:
        space = document.current_space()
        for entity in space:
            if entity.dxf.handle not in names or not is_survey_point(entity):
                continue
            point = survey_point(entity)
            entity.set_xdata(APPID, [(1000, POINT_TAG), (1000, names[entity.dxf.handle]),
                                     (1000, point.desc)])
            label = labels_of(document, entity).get("number")
            if label is not None:
                label.dxf.text = names[entity.dxf.handle]
        document.dirty = True

    def do(self, document) -> None:
        by_handle = {e.dxf.handle: e for e in document.current_space()
                     if e.dxf.handle in self.handles}
        new = {}
        number = self.start
        for handle in self.handles:
            entity = by_handle.get(handle)
            if entity is None or not is_survey_point(entity):
                continue
            self._old.setdefault(handle, survey_point(entity).name)
            new[handle] = str(number)
            number += self.step
        self._apply(document, new)

    def undo(self, document) -> None:
        self._apply(document, dict(self._old))


def renumber(entities, start: int, step: int = 1) -> RenumberCommand:
    return RenumberCommand(entities, start, step)


# ======================================================================
# T2: annotation, the construction chart, areas, subdivision, UTM grid
# ======================================================================

import math as _math

from core import tables as _tables
from core.actions import EraseCommand, add_polyline
from core.i18n import tr as _tr

from . import geometry
from .points import format_bearing, format_dms

ANNOT_TAG = "TOPO-ANNOT"


@dataclass
class AnnotationStyle:
    text_height: float = 1.0
    mode: str = "both"           # "bearing" | "distance" | "both"
    azimuth: bool = False        # azimuth 123.4567° instead of N 45°30' E
    decimals: int = 2
    prefix: str = ""
    suffix: str = ""


def readable_rotation(angle_deg: float) -> float:
    """The rotation a label along a line takes so it never reads upside
    down: AutoCAD's rule, (-90, 90]."""
    a = angle_deg % 360.0
    if 90.0 < a <= 270.0:
        a -= 180.0
    return ((a + 180.0) % 360.0) - 180.0


def _text_factory(text: str, pos, height: float, rotation: float = 0.0,
                  align: str = "MIDDLE_CENTER", link: str | None = None,
                  tag: str = ANNOT_TAG):
    def make(msp):
        from ezdxf.enums import TextEntityAlignment

        ensure_appid(msp.doc)
        entity = msp.add_text(text, height=height, dxfattribs={"rotation": rotation})
        entity.set_placement((pos[0], pos[1]),
                             align=getattr(TextEntityAlignment, align))
        if link is not None:
            entity.set_xdata(APPID, [(1000, tag), (1005, link)])
        return entity
    return make


def bearing_text(azimuth: float, style: AnnotationStyle) -> str:
    return f"{azimuth:.4f}°" if style.azimuth else format_bearing(azimuth)


def segment_annotation_commands(a, b, style: AnnotationStyle,
                                link: str | None = None) -> list[Command]:
    """Distance above the segment, bearing below, both readable."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = _math.hypot(dx, dy)
    if length < 1e-9:
        return []
    angle = _math.degrees(_math.atan2(dy, dx))
    rotation = readable_rotation(angle)
    rad = _math.radians(rotation)
    up = (-_math.sin(rad), _math.cos(rad))          # "above" for the reader
    mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
    gap = 0.9 * style.text_height
    out: list[Command] = []
    if style.mode in ("distance", "both"):
        text = f"{style.prefix}{length:.{style.decimals}f}{style.suffix}"
        out.append(AddEntityCommand("TOPO-ANNOT", _text_factory(
            text, (mid[0] + up[0] * gap, mid[1] + up[1] * gap),
            style.text_height, rotation, link=link), layer=LAYERS["annotation"][0]))
    if style.mode in ("bearing", "both"):
        azimuth = geometry.cad_to_azimuth(angle)
        out.append(AddEntityCommand("TOPO-ANNOT", _text_factory(
            bearing_text(azimuth, style), (mid[0] - up[0] * gap, mid[1] - up[1] * gap),
            style.text_height, rotation, link=link), layer=LAYERS["annotation"][0]))
    return out


def arc_annotation_commands(arc, style: AnnotationStyle,
                            link: str | None = None) -> list[Command]:
    """L, R, delta and chord of an ARC, outside its middle."""
    c = arc.dxf.center
    r = float(arc.dxf.radius)
    a0, a1 = float(arc.dxf.start_angle), float(arc.dxf.end_angle)
    while a1 <= a0:
        a1 += 360.0
    delta = a1 - a0
    mid_angle = _math.radians((a0 + a1) / 2.0)
    length = _math.radians(delta) * r
    chord = 2.0 * r * _math.sin(_math.radians(delta) / 2.0)
    text = (f"L={length:.{style.decimals}f}  R={r:.{style.decimals}f}  "
            f"D={format_dms(delta)}  C={chord:.{style.decimals}f}")
    gap = 1.2 * style.text_height
    pos = (c.x + (r + gap) * _math.cos(mid_angle), c.y + (r + gap) * _math.sin(mid_angle))
    rotation = readable_rotation(_math.degrees(mid_angle) + 90.0)
    return [AddEntityCommand("TOPO-ANNOT", _text_factory(
        text, pos, style.text_height, rotation, link=link),
        layer=LAYERS["annotation"][0])]


def _segments_of(entity):
    """(kind, payload) per straight segment / arc of a LINE, ARC or polyline."""
    kind = entity.dxftype()
    if kind == "LINE":
        s, e = entity.dxf.start, entity.dxf.end
        yield "segment", ((s.x, s.y), (e.x, e.y))
    elif kind == "ARC":
        yield "arc", entity
    elif kind in ("LWPOLYLINE", "POLYLINE"):
        for part in entity.virtual_entities():
            if part.dxftype() == "LINE":
                s, e = part.dxf.start, part.dxf.end
                yield "segment", ((s.x, s.y), (e.x, e.y))
            elif part.dxftype() == "ARC":
                yield "arc", part


def annotate(document, entities, style: AnnotationStyle | None = None) -> CompositeCommand:
    """Bearing and distance on every straight segment, arc data on every
    arc, of the lines, arcs and polylines given -- one undo step."""
    style = style or AnnotationStyle()
    commands = layer_commands(document, ("annotation",))
    for entity in entities:
        link = entity.dxf.handle
        for kind, payload in _segments_of(entity):
            if kind == "segment":
                commands.extend(segment_annotation_commands(payload[0], payload[1], style, link))
            else:
                commands.extend(arc_annotation_commands(payload, style, link))
    return CompositeCommand("annotate", commands)


# -- the construction chart ----------------------------------------------------------

@dataclass
class ChartStyle:
    text_height: float = 1.0
    clockwise: bool | None = True    # None = as drawn
    azimuth: bool = False
    decimals: int = 2
    label_vertices: bool = True
    vertex_prefix: str = "V"


@dataclass
class PolygonData:
    vertices: list
    rows: list
    area: float
    perimeter: float


def polygon_data(entity_or_points, style: ChartStyle | None = None) -> PolygonData:
    """Vertex by vertex: name, side, distance, bearing, interior angle,
    east, north -- what every coordinate chart lists."""
    style = style or ChartStyle()
    pts = entity_or_points if isinstance(entity_or_points, list) \
        else geometry.polygon_vertices(entity_or_points)
    if pts is None:
        raise ValueError("not a closed polygon")
    if style.clockwise is not None:
        pts = geometry.oriented(pts, style.clockwise)
    angles = geometry.interior_angles(pts)
    rows = []
    n = len(pts)
    for side in geometry.sides(pts):
        i, j = side.index, (side.index + 1) % n
        name, nxt = f"{style.vertex_prefix}{i + 1}", f"{style.vertex_prefix}{j + 1}"
        rows.append([
            name, f"{name}-{nxt}",
            f"{side.length:.{style.decimals}f}",
            bearing_text(side.azimuth, AnnotationStyle(azimuth=style.azimuth)),
            format_dms(angles[i]),
            f"{side.start[0]:.{style.decimals}f}",
            f"{side.start[1]:.{style.decimals}f}",
        ])
    return PolygonData(pts, rows, geometry.area(pts), geometry.perimeter(pts))


def chart_headers(style: ChartStyle) -> list[str]:
    return [_tr("VERTEX"), _tr("SIDE"), _tr("DISTANCE"),
            _tr("AZIMUTH") if style.azimuth else _tr("BEARING"),
            _tr("INTERIOR ANGLE"), _tr("EAST"), _tr("NORTH")]


def chart_widths(style: ChartStyle) -> list[float]:
    h = style.text_height
    return [w * h for w in (7.0, 9.0, 10.0, 13.0, 12.0, 12.0, 13.0)]


def construction_table(document, entity, insert, style: ChartStyle | None = None) -> CompositeCommand:
    """The construction chart of a closed polygon, as a table of lines and
    text at ``insert`` (top-left), plus the vertex labels on the drawing."""
    style = style or ChartStyle()
    data = polygon_data(entity, style)
    rows = list(data.rows)
    rows.append(["", _tr("AREA"), geometry.format_area(data.area, style.decimals), "", "", "", ""])
    rows.append(["", _tr("PERIMETER"), geometry.format_length(data.perimeter, style.decimals),
                 "", "", "", ""])
    h = style.text_height
    table = _tables.insert_table(
        insert, cols=7, col_width=10.0 * h, data_rows=len(rows), row_height=2.0 * h,
        text_height=h, title=_tr("CONSTRUCTION CHART"), headers=chart_headers(style),
        data=rows, col_widths=chart_widths(style))
    commands = layer_commands(document, ("table", "annotation"))
    for command in table.commands:
        command.layer = LAYERS["table"][0]
    commands.extend(table.commands)
    if style.label_vertices:
        cx, cy = geometry.centroid(data.vertices)
        for i, (x, y) in enumerate(data.vertices):
            # a little outward from the centroid, so the label clears the corner
            dx, dy = x - cx, y - cy
            d = _math.hypot(dx, dy) or 1.0
            pos = (x + dx / d * 1.2 * h, y + dy / d * 1.2 * h)
            commands.append(AddEntityCommand("TOPO-ANNOT", _text_factory(
                f"{style.vertex_prefix}{i + 1}", pos, h, link=entity.dxf.handle),
                layer=LAYERS["annotation"][0]))
    return CompositeCommand("construction chart", commands)


# -- areas -------------------------------------------------------------------------------

def area_of(entity) -> float | None:
    """The area an entity encloses: closed polylines and circles."""
    if entity.dxftype() == "CIRCLE":
        return _math.pi * float(entity.dxf.radius) ** 2
    pts = geometry.polygon_vertices(entity)
    if pts is None:
        return None
    if entity.dxftype() == "LWPOLYLINE" and any(abs(b) > 1e-12 for b in
                                                (p[4] for p in entity.get_points())):
        # arcs in the boundary: measure the flattened outline
        flat = [(v.x, v.y) for v in entity.flattening(0.01)]
        if flat and geometry._close(flat[0], flat[-1]):
            flat = flat[:-1]
        return geometry.area(flat)
    return geometry.area(pts)


def area_label(document, point, text: str, text_height: float) -> CompositeCommand:
    return CompositeCommand("area label", layer_commands(document, ("annotation",)) + [
        AddEntityCommand("TOPO-ANNOT", _text_factory(text, point, text_height),
                         layer=LAYERS["annotation"][0])])


# -- subdivision ---------------------------------------------------------------------------

def subdivide(document, entity, cut: geometry.Cut, split: bool = False) -> CompositeCommand:
    """Draw the cut line; with ``split``, replace the polygon by its two
    pieces (same layer), the original kept for undo."""
    commands = layer_commands(document, ("subdivision",))
    a, b = cut.start, cut.end
    commands.append(AddEntityCommand(
        "TOPO-SUBDIV", lambda msp: msp.add_line((a[0], a[1]), (b[0], b[1])),
        layer=LAYERS["subdivision"][0]))
    if split:
        layer = entity.dxf.layer
        commands.append(EraseCommand([entity]))
        for piece in (cut.left, cut.right):
            if len(piece) >= 3:
                command = add_polyline(piece, closed=True)
                command.layer = layer
                commands.append(command)
    return CompositeCommand("subdivide", commands)


# -- UTM grid -------------------------------------------------------------------------------

def utm_grid(document, x0: float, y0: float, x1: float, y1: float, spacing: float,
             text_height: float = 1.0, crosses: bool = True) -> CompositeCommand:
    """Crosses (or full lines) at every multiple of ``spacing`` inside the
    rectangle, with E/N labels along the bottom and left borders."""
    x0, x1 = min(x0, x1), max(x0, x1)
    y0, y1 = min(y0, y1), max(y0, y1)
    xs, ys = geometry.grid_values(x0, x1, spacing), geometry.grid_values(y0, y1, spacing)
    layer = LAYERS["grid"][0]
    commands = layer_commands(document, ("grid",))

    def line(a, b):
        commands.append(AddEntityCommand(
            "TOPO-GRID", lambda msp, a=a, b=b: msp.add_line(a, b), layer=layer))

    arm = spacing * 0.08
    if crosses:
        for x in xs:
            for y in ys:
                line((x - arm, y), (x + arm, y))
                line((x, y - arm), (x, y + arm))
    else:
        for x in xs:
            line((x, y0), (x, y1))
        for y in ys:
            line((x0, y), (x1, y))
    h = text_height
    for x in xs:
        label = "E " + f"{x:,.0f}".replace(",", " ")
        commands.append(AddEntityCommand("TOPO-GRID", _text_factory(
            label, (x, y0 - 1.5 * h), h, 90.0, align="MIDDLE_RIGHT", tag="TOPO-GRID"),
            layer=layer))
    for y in ys:
        label = "N " + f"{y:,.0f}".replace(",", " ")
        commands.append(AddEntityCommand("TOPO-GRID", _text_factory(
            label, (x0 - 1.5 * h, y), h, 0.0, align="MIDDLE_RIGHT", tag="TOPO-GRID"),
            layer=layer))
    return CompositeCommand("utm grid", commands)


# ======================================================================
# T3: the surface -- a TIN of 3DFACEs, read back, edited, checked
# ======================================================================

from . import tin as _tin

TIN_TAG = "TOPO-TIN"


def _face_factory(pa, pb, pc, name: str):
    def make(msp):
        ensure_appid(msp.doc)
        entity = msp.add_3dface([pa, pb, pc, pc])
        entity.set_xdata(APPID, [(1000, TIN_TAG), (1000, name)])
        return entity
    return make


def _vertex_xyz(v):
    return (float(v[0]), float(v[1]), float(v[2]) if len(v) > 2 else 0.0)


def surface_inputs(entities):
    """(points, breaklines) among the entities: POINTs are points, lines
    and polylines are breaklines (their vertices join the surface)."""
    points, breaklines = [], []
    for entity in entities:
        kind = entity.dxftype()
        if kind == "POINT":
            loc = entity.dxf.location
            points.append((loc.x, loc.y, loc.z))
        elif kind == "LINE":
            s, e = entity.dxf.start, entity.dxf.end
            breaklines.append([(s.x, s.y, s.z), (e.x, e.y, e.z)])
        elif kind == "LWPOLYLINE":
            z = float(entity.dxf.elevation)
            verts = [(x, y, z) for x, y in entity.get_points("xy")]
            if entity.closed and verts:
                verts.append(verts[0])
            breaklines.append(verts)
        elif kind == "POLYLINE":
            verts = [(v.dxf.location.x, v.dxf.location.y, v.dxf.location.z)
                     for v in entity.vertices]
            if entity.is_closed and verts:
                verts.append(verts[0])
            breaklines.append(verts)
    return points, breaklines


def build_surface(document, tin: _tin.Tin) -> CompositeCommand:
    """Every triangle of ``tin`` as a 3DFACE on TOPO-TIN, one undo step."""
    commands = layer_commands(document, ("tin",))
    for a, b, c in tin.triangles:
        commands.append(AddEntityCommand(
            "TOPO-TIN", _face_factory(tin.points[a], tin.points[b], tin.points[c], tin.name),
            layer=LAYERS["tin"][0]))
    return CompositeCommand("triangulate", commands)


def is_face(entity, name: str | None = None) -> bool:
    if entity.dxftype() != "3DFACE":
        return False
    data = _xdata(entity)
    if not data or data[0] != TIN_TAG:
        return False
    return name is None or (len(data) > 1 and str(data[1]) == name)


def surface_faces(document, name: str | None = None) -> list:
    return [e for e in document.current_space() if is_face(e, name)]


def surface_names(document) -> list[str]:
    names = []
    for entity in document.current_space():
        if is_face(entity):
            data = _xdata(entity)
            label = str(data[1]) if len(data) > 1 else ""
            if label not in names:
                names.append(label)
    return names


def face_points(face) -> tuple:
    """The three corners (x, y, z), counter-clockwise."""
    d = face.dxf
    pts = [(d.vtx0.x, d.vtx0.y, d.vtx0.z), (d.vtx1.x, d.vtx1.y, d.vtx1.z),
           (d.vtx2.x, d.vtx2.y, d.vtx2.z)]
    if _tin.orient(pts[0], pts[1], pts[2]) < 0:
        pts = [pts[0], pts[2], pts[1]]
    return tuple(pts)


def read_surface(document, name: str | None = None, faces=None) -> _tin.Tin:
    """The surface the 3DFACEs describe, vertices shared by position."""
    faces = surface_faces(document, name) if faces is None else faces
    raw = []
    for face in faces:
        raw.extend(face_points(face))
    pts, index = _tin._dedupe(raw)
    triangles = [(index[3 * i], index[3 * i + 1], index[3 * i + 2]) for i in range(len(faces))]
    label = name
    if label is None and faces:
        data = _xdata(faces[0])
        label = str(data[1]) if data and len(data) > 1 else "TERRENO"
    return _tin.Tin(pts, triangles, label or "TERRENO")


def face_name(face) -> str:
    data = _xdata(face)
    return str(data[1]) if data and len(data) > 1 else "TERRENO"


def face_at(faces, point):
    """The face whose 2D triangle holds ``point``, or None."""
    for face in faces:
        a, b, c = face_points(face)
        if (_tin.orient(a, b, point) >= -1e-9 and _tin.orient(b, c, point) >= -1e-9
                and _tin.orient(c, a, point) >= -1e-9):
            return face
    return None


def _same_xy(p, q) -> bool:
    return abs(p[0] - q[0]) < 1e-6 and abs(p[1] - q[1]) < 1e-6


def nearest_edge(faces, point):
    """(face_a, face_b, edge) for the shared edge closest to ``point``; None
    when the closest edge belongs to a single face (the boundary)."""
    best = None
    best_d = _math.inf
    for face in faces:
        pts = face_points(face)
        for i in range(3):
            a, b = pts[i], pts[(i + 1) % 3]
            d = geometry._point_segment_distance(point, a, b)
            if d < best_d:
                best_d, best = d, (face, (a, b))
    if best is None:
        return None
    face, (a, b) = best
    for other in faces:
        if other is face:
            continue
        pts = other.face_points if False else face_points(other)
        if sum(1 for q in pts if _same_xy(q, a) or _same_xy(q, b)) == 2:
            return face, other, (a, b)
    return None


def flip_edge(document, face_a, face_b) -> CompositeCommand | None:
    """The two faces sharing an edge, re-cut along the other diagonal."""
    pa, pb = face_points(face_a), face_points(face_b)
    shared = [q for q in pa if any(_same_xy(q, r) for r in pb)]
    if len(shared) != 2:
        return None
    apex_a = next(q for q in pa if not any(_same_xy(q, r) for r in shared))
    apex_b = next(q for q in pb if not any(_same_xy(q, r) for r in shared))
    b, c = shared
    if not _tin._segments_cross(apex_a, apex_b, b, c):
        return None                                   # the quad is not convex
    name = face_name(face_a)
    t1 = (apex_a, b, apex_b) if _tin.orient(apex_a, b, apex_b) > 0 else (apex_a, apex_b, b)
    t2 = (apex_a, apex_b, c) if _tin.orient(apex_a, apex_b, c) > 0 else (apex_a, c, apex_b)
    return CompositeCommand("flip edge", [
        EraseCommand([face_a, face_b]),
        AddEntityCommand("TOPO-TIN", _face_factory(*t1, name), layer=face_a.dxf.layer),
        AddEntityCommand("TOPO-TIN", _face_factory(*t2, name), layer=face_a.dxf.layer),
    ])


def delete_faces(faces) -> CompositeCommand:
    return CompositeCommand("delete triangles", [EraseCommand(list(faces))])


def insert_point(document, faces, point) -> CompositeCommand | None:
    """Bowyer-Watson on the drawn surface: the faces whose circumcircle
    holds the point go, the fan around the point comes in."""
    p = _vertex_xyz(point)
    cavity = []
    for face in faces:
        a, b, c = face_points(face)
        if _tin.in_circle(a, b, c, p) or face_at([face], p) is face:
            cavity.append(face)
    if not cavity:
        return None
    name = face_name(cavity[0])
    layer = cavity[0].dxf.layer
    counts: dict = {}
    for face in cavity:
        pts = face_points(face)
        for i in range(3):
            a, b = pts[i], pts[(i + 1) % 3]
            key = (round(a[0], 6), round(a[1], 6), round(b[0], 6), round(b[1], 6))
            rev = (key[2], key[3], key[0], key[1])
            if rev in counts:
                counts.pop(rev)                       # interior edge: both sides in the cavity
            else:
                counts[key] = (a, b)
    commands = [EraseCommand(cavity)]
    for a, b in counts.values():
        if _tin.orient(a, b, p) > 0:
            tri = (a, b, p)
        else:
            tri = (b, a, p)
        commands.append(AddEntityCommand("TOPO-TIN", _face_factory(*tri, name), layer=layer))
    return CompositeCommand("insert point", commands)


def clip_surface(faces, polygon, keep_inside: bool = True) -> CompositeCommand:
    gone = []
    for face in faces:
        a, b, c = face_points(face)
        centre = ((a[0] + b[0] + c[0]) / 3.0, (a[1] + b[1] + c[1]) / 3.0)
        inside = geometry.contains(polygon, centre)
        if inside != keep_inside:
            gone.append(face)
    return CompositeCommand("clip surface", [EraseCommand(gone)] if gone else [])


def surface_report(tin: _tin.Tin) -> str:
    st = tin.stats()
    return _tr("{name}: {t} triangles, {p} points, {e} edges ({b} on the border), "
               "Z {zmin:.2f} to {zmax:.2f}, area 2D {a2:.2f} m², 3D {a3:.2f} m²",
               name=tin.name, t=st["triangles"], p=st["points"], e=st["edges"],
               b=st["boundary_edges"], zmin=st["z_min"], zmax=st["z_max"],
               a2=st["area_2d"], a3=st["area_3d"])
