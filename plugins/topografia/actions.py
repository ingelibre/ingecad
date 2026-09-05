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
    "contour_minor": ("TOPO-CN-FINA", 32),      # dark orange, brown on paper
    "contour_major": ("TOPO-CN-GRUESA", 30),    # orange; the TIN stays grey
    "contour_label": ("TOPO-CN-TEXTO", 7),
    "slopes": ("TOPO-PENDIENTES", 7),
    "profile": ("TOPO-PERFIL", 3),
    "profile_grid": ("TOPO-PERFIL-GRILLA", 8),
    "profile_text": ("TOPO-PERFIL-TEXTO", 7),
    "grade": ("TOPO-RASANTE", 1),
    "sections": ("TOPO-SECCIONES", 3),
    "sections_grid": ("TOPO-SECCIONES-GRILLA", 8),
    "earthworks": ("TOPO-VOLUMENES", 7),
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
        from ezdxf import path as _path

        flat = [(v.x, v.y) for v in _path.make_path(entity).flattening(0.01)]
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


# ======================================================================
# T4: contour lines, their labels, slope zones
# ======================================================================

from . import contours as _contours

CONTOUR_TAG = "TOPO-CONTOUR"
SLOPES_TAG = "TOPO-SLOPES"
SLOPE_COLORS = (3, 2, 30, 1, 6, 5, 4)     # green, yellow, orange, red, magenta...


def _contour_factory(contour: _contours.Contour, name: str):
    def make(msp):
        ensure_appid(msp.doc)
        entity = msp.add_lwpolyline(contour.points, close=contour.closed,
                                    dxfattribs={"elevation": float(contour.level)})
        entity.set_xdata(APPID, [(1000, CONTOUR_TAG), (1000, name), (1040, float(contour.level))])
        return entity
    return make


def draw_contours(document, tin: _tin.Tin, interval: float, major_every: int = 5,
                  smoothing: int = 0, base: float = 0.0) -> CompositeCommand:
    """Every contour as an LWPOLYLINE at its elevation, minor and major on
    their own layers; ``smoothing`` is the number of Chaikin passes."""
    commands = layer_commands(document, ("contour_minor", "contour_major"))
    for contour in _contours.contours(tin, interval, major_every, base):
        if smoothing > 0:
            contour = _contours.Contour(contour.level,
                                        _contours.smooth(contour.points, contour.closed, smoothing),
                                        contour.closed, contour.major)
        layer = LAYERS["contour_major" if contour.major else "contour_minor"][0]
        commands.append(AddEntityCommand("TOPO-CONTOUR", _contour_factory(contour, tin.name),
                                         layer=layer))
    return CompositeCommand("contours", commands)


def is_contour(entity) -> bool:
    if entity.dxftype() != "LWPOLYLINE":
        return False
    data = _xdata(entity)
    return bool(data) and data[0] == CONTOUR_TAG


def contour_entities(document, name: str | None = None) -> list:
    out = []
    for entity in document.current_space():
        if is_contour(entity):
            data = _xdata(entity)
            if name is None or (len(data) > 1 and str(data[1]) == name):
                out.append(entity)
    return out


def contour_level(entity) -> float:
    data = _xdata(entity) or []
    if len(data) > 2:
        try:
            return float(data[2])
        except (TypeError, ValueError):
            pass
    return float(entity.dxf.elevation)


def contour_chain(entity):
    return [(float(x), float(y)) for x, y in entity.get_points("xy")], bool(entity.closed)


def _contour_label_factory(text: str, pos, height: float, rotation: float, link: str | None):
    def make(msp):
        ensure_appid(msp.doc)
        entity = msp.add_mtext(text, dxfattribs={
            "char_height": height, "rotation": rotation,
            "width": max(len(text), 1) * height * 1.1})
        entity.set_location((pos[0], pos[1]), attachment_point=5)     # middle centre
        entity.set_bg_color("canvas", scale=1.15)                       # hides the curve under it
        if link is not None:
            entity.set_xdata(APPID, [(1000, "TOPO-CONTOUR-LABEL"), (1005, link)])
        return entity
    return make


def label_contours(document, entities, text_height: float = 1.0, spacing: float | None = 50.0,
                   at=None, decimals: int = 0) -> CompositeCommand:
    """Elevation labels on the contours: every ``spacing`` along each, or
    at the point of the chain nearest to ``at``. Readable, masked."""
    commands = layer_commands(document, ("contour_label",))
    for entity in entities:
        points, closed = contour_chain(entity)
        if len(points) < 2:
            continue
        level = contour_level(entity)
        text = f"{level:.{decimals}f}"
        if at is not None:
            spots = [_contours.nearest_on_chain(points, closed, at)]
        else:
            spots = _contours.positions_along(points, closed, spacing or 50.0)
        for x, y, angle in spots:
            commands.append(AddEntityCommand("TOPO-CONTOUR-LABEL", _contour_label_factory(
                text, (x, y), text_height, readable_rotation(angle), entity.dxf.handle),
                layer=LAYERS["contour_label"][0]))
    return CompositeCommand("contour labels", commands)


def slope_report(tin: _tin.Tin, breaks=(5.0, 10.0, 20.0, 30.0)) -> list[tuple[str, float, int]]:
    """(label, area 2D, triangles) per class, first class first."""
    breaks = [float(b) for b in breaks]
    rows = [[_contours.slope_label(i, breaks), 0.0, 0] for i in range(len(breaks) + 1)]
    for t in tin.triangles:
        i = _contours.slope_class(_contours.triangle_slope(tin, t), breaks)
        a, b, c = (tin.points[k] for k in t)
        rows[i][1] += abs(_tin.orient(a, b, c)) / 2.0
        rows[i][2] += 1
    return [tuple(r) for r in rows]


def slope_zones(document, tin: _tin.Tin, breaks=(5.0, 10.0, 20.0, 30.0),
                legend_at=None, text_height: float = 1.0) -> CompositeCommand:
    """One solid HATCH per slope class (all its triangles as paths) and,
    at ``legend_at``, a legend of swatches and ranges."""
    breaks = [float(b) for b in breaks]
    classes: dict[int, list] = {}
    for t in tin.triangles:
        i = _contours.slope_class(_contours.triangle_slope(tin, t), breaks)
        classes.setdefault(i, []).append([(tin.points[k][0], tin.points[k][1]) for k in t])
    commands = layer_commands(document, ("slopes",))
    layer = LAYERS["slopes"][0]
    for i in sorted(classes):
        aci = SLOPE_COLORS[i % len(SLOPE_COLORS)]

        def make(msp, tris=classes[i], aci=aci, label=_contours.slope_label(i, breaks)):
            from ezdxf.lldxf.const import BOUNDARY_PATH_EXTERNAL

            ensure_appid(msp.doc)
            h = msp.add_hatch(color=aci)
            h.set_solid_fill(color=aci)
            for tri in tris:
                h.paths.add_polyline_path(tri, is_closed=True, flags=BOUNDARY_PATH_EXTERNAL)
            h.set_xdata(APPID, [(1000, SLOPES_TAG), (1000, tin.name), (1000, label)])
            return h
        commands.append(AddEntityCommand("TOPO-SLOPES", make, layer=layer))
    if legend_at is not None:
        x0, y0 = legend_at
        h = text_height
        report = slope_report(tin, breaks)
        for row, (label, area, count) in enumerate(report):
            if count == 0:
                continue
            y = y0 - row * 2.0 * h
            aci = SLOPE_COLORS[row % len(SLOPE_COLORS)]

            def swatch(msp, x=x0, y=y, aci=aci):
                return msp.add_solid([(x, y), (x + 1.5 * h, y), (x, y - 1.2 * h), (x + 1.5 * h, y - 1.2 * h)],
                                     dxfattribs={"color": aci})
            commands.append(AddEntityCommand("TOPO-SLOPES", swatch, layer=layer))
            commands.append(AddEntityCommand("TOPO-SLOPES", _text_factory(
                f"{label}   {geometry.format_area(area)}", (x0 + 2.0 * h, y - 0.6 * h), h,
                align="MIDDLE_LEFT", tag=SLOPES_TAG), layer=layer))
    return CompositeCommand("slope zones", commands)


# ======================================================================
# T5: profile, grade line, cross sections, earthworks
# ======================================================================

from . import alignment as _alignment
from . import profile as _profile

PROFILE_TAG = "TOPO-PROFILE"
GRADE_TAG = "TOPO-GRADE"
SECTION_TAG = "TOPO-SECTION"


def axis_points(entity) -> list:
    """The axis as a flat polyline (arcs flattened to 1 cm)."""
    kind = entity.dxftype()
    if kind == "LINE":
        s, e = entity.dxf.start, entity.dxf.end
        return [(s.x, s.y), (e.x, e.y)]
    if kind in ("LWPOLYLINE", "POLYLINE"):
        from ezdxf import path as _path

        return [(v.x, v.y) for v in _path.make_path(entity).flattening(0.01)]
    raise ValueError("the axis must be a line or a polyline")


@dataclass
class ProfileFrame:
    """Where a profile drawing sits and how it maps chainage and elevation
    to drawing coordinates."""

    name: str
    x0: float                 # bottom-left of the grid (above the bands)
    y0: float
    hscale: float = 1.0       # drawing units per metre of chainage
    vscale: float = 10.0      # drawing units per metre of elevation
    datum: float = 0.0
    band_height: float = 0.0  # height of the label bands under the grid
    axis_handle: str = ""
    step: float = 20.0

    def to_drawing(self, s: float, z: float) -> tuple[float, float]:
        return (self.x0 + s * self.hscale, self.y0 + (z - self.datum) * self.vscale)

    def to_chainage(self, x: float, y: float) -> tuple[float, float]:
        return ((x - self.x0) / self.hscale, self.datum + (y - self.y0) / self.vscale)

    def xdata(self) -> list:
        return [(1000, PROFILE_TAG), (1000, self.name), (1040, self.x0), (1040, self.y0),
                (1040, self.hscale), (1040, self.vscale), (1040, self.datum),
                (1040, self.band_height), (1005, self.axis_handle or "0"), (1040, self.step)]

    @classmethod
    def from_entity(cls, entity):
        data = _xdata(entity) or []
        if not data or data[0] != PROFILE_TAG or len(data) < 10:
            return None
        return cls(str(data[1]), float(data[2]), float(data[3]), float(data[4]), float(data[5]),
                   float(data[6]), float(data[7]), str(data[8]), float(data[9]))


def is_profile(entity) -> bool:
    return entity.dxftype() == "LWPOLYLINE" and ProfileFrame.from_entity(entity) is not None


def profile_entities(document) -> list:
    return [e for e in document.current_space() if is_profile(e)]


def _line_cmd(a, b, layer: str, tag: str = PROFILE_TAG) -> Command:
    def make(msp):
        ensure_appid(msp.doc)
        entity = msp.add_line((a[0], a[1]), (b[0], b[1]))
        entity.set_xdata(APPID, [(1000, tag)])
        return entity
    return AddEntityCommand("TOPO-PROFILE", make, layer=layer)


def _text_cmd(text, pos, height, layer, rotation=0.0, align="MIDDLE_CENTER", tag=PROFILE_TAG) -> Command:
    return AddEntityCommand("TOPO-PROFILE", _text_factory(text, pos, height, rotation, align, tag=tag),
                            layer=layer)


def draw_profile(document, tin: _tin.Tin, axis_entity, insert, step: float = 20.0,
                 hscale: float = 1.0, vscale: float = 10.0, text_height: float = 1.0,
                 name: str = "EJE", grade: list | None = None) -> CompositeCommand:
    """The longitudinal profile of the axis over the surface, as a grid
    with the station and elevation bands under it and the ground line on
    top; ``grade`` (s, z) adds the design line and its band."""
    axis = axis_points(axis_entity)
    points = _profile.ground_profile(tin, axis, step)
    zs = [p.z for p in points if p.z is not None]
    if grade:
        zs += [z for _s, z in grade]
    if not zs:
        raise ValueError("the axis does not cross the surface")
    h = text_height
    interval = 1.0 if (max(zs) - min(zs)) >= 3.0 else 0.5
    datum = _math.floor(min(zs) / interval) * interval - interval
    top = _math.ceil(max(zs) / interval) * interval + interval
    bands = 2 + (1 if grade else 0)
    band_h = 3.5 * h
    frame = ProfileFrame(name, insert[0] + 8.0 * h, insert[1] + bands * band_h, hscale, vscale,
                         datum, bands * band_h, axis_entity.dxf.handle, step)
    grid, text = LAYERS["profile_grid"][0], LAYERS["profile_text"][0]
    commands = layer_commands(document, ("profile", "profile_grid", "profile_text"))
    length = _alignment.polyline_length(axis)
    x_end = frame.to_drawing(length, datum)[0]
    y_top = frame.to_drawing(0.0, top)[1]
    # the grid: elevation lines with their labels, station lines
    level = datum
    while level <= top + 1e-9:
        y = frame.to_drawing(0.0, level)[1]
        commands.append(_line_cmd((frame.x0, y), (x_end, y), grid))
        commands.append(_text_cmd(f"{level:.2f}", (frame.x0 - 0.8 * h, y), h, text,
                                  align="MIDDLE_RIGHT"))
        level += interval
    bottom = insert[1]
    for pt in points:
        x = frame.to_drawing(pt.s, datum)[0]
        commands.append(_line_cmd((x, bottom), (x, y_top), grid))
        commands.append(_text_cmd(_alignment.format_station(pt.s), (x, bottom + 0.5 * band_h),
                                  h, text, rotation=90.0))
        if pt.z is not None:
            commands.append(_text_cmd(f"{pt.z:.2f}", (x, bottom + 1.5 * band_h), h, text,
                                      rotation=90.0))
        if grade:
            zd = _profile.grade_at(grade, pt.s)
            if zd is not None:
                commands.append(_text_cmd(f"{zd:.2f}", (x, bottom + 2.5 * band_h), h, text,
                                          rotation=90.0))
    # band frame and titles
    for k in range(bands + 1):
        y = bottom + k * band_h
        commands.append(_line_cmd((insert[0], y), (x_end, y), grid))
    commands.append(_line_cmd((insert[0], bottom), (insert[0], y_top), grid))
    commands.append(_line_cmd((frame.x0, bottom), (frame.x0, y_top), grid))
    commands.append(_line_cmd((x_end, bottom), (x_end, y_top), grid))
    titles = [_tr("STATION"), _tr("GROUND")] + ([_tr("GRADE")] if grade else [])
    for k, title in enumerate(titles):
        commands.append(_text_cmd(title, (insert[0] + 0.5 * h, bottom + (k + 0.5) * band_h),
                                  h * 0.8, text, align="MIDDLE_LEFT"))
    commands.append(_text_cmd(
        _tr("PROFILE {name}   H 1:{h:g}   V 1:{v:g}", name=name, h=1000.0 / hscale, v=1000.0 / vscale),
        (frame.x0, y_top + 2.0 * h), 1.4 * h, text, align="MIDDLE_LEFT"))
    # the ground line carries the frame
    ground = [frame.to_drawing(pt.s, pt.z) for pt in points if pt.z is not None]

    def make_ground(msp):
        ensure_appid(msp.doc)
        entity = msp.add_lwpolyline(ground)
        entity.set_xdata(APPID, frame.xdata())
        return entity
    commands.append(AddEntityCommand("TOPO-PROFILE", make_ground, layer=LAYERS["profile"][0]))
    if grade:
        line = [frame.to_drawing(s_, z_) for s_, z_ in grade]
        commands.extend(layer_commands(document, ("grade",)))
        commands.append(AddEntityCommand("TOPO-PROFILE", lambda msp, pts=line: msp.add_lwpolyline(pts),
                                         layer=LAYERS["grade"][0]))
    return CompositeCommand("profile", commands)


def profile_csv(tin: _tin.Tin, axis_entity, step: float, grade: list | None = None) -> str:
    axis = axis_points(axis_entity)
    lines = ["station,ground_z,design_z,cut,fill"]
    for pt in _profile.ground_profile(tin, axis, step):
        zd = _profile.grade_at(grade, pt.s) if grade else None
        zg = "" if pt.z is None else f"{pt.z:.3f}"
        zd_txt = "" if zd is None else f"{zd:.3f}"
        diff = "" if (zd is None or pt.z is None) else f"{max(pt.z - zd, 0):.3f},{max(zd - pt.z, 0):.3f}"
        lines.append(f"{pt.s:.2f},{zg},{zd_txt},{diff if diff else ','}")
    return "\n".join(lines) + "\n"


# -- the grade line -------------------------------------------------------------------------

class TagEntityCommand(Command):
    """Move an entity to a layer and give it XDATA, undoably."""

    name = "tag entity"

    def __init__(self, entity, layer: str, xdata: list) -> None:
        self.entity = entity
        self.layer = layer
        self.xdata = xdata
        self._old_layer = None
        self._old_xdata = None

    def do(self, document) -> None:
        ensure_appid(document.doc)
        self._old_layer = self.entity.dxf.layer
        try:
            self._old_xdata = list(self.entity.get_xdata(APPID))
        except Exception:
            self._old_xdata = None
        if self.layer in document.doc.layers:
            self.entity.dxf.layer = self.layer
        self.entity.set_xdata(APPID, self.xdata)
        document.dirty = True

    def undo(self, document) -> None:
        self.entity.dxf.layer = self._old_layer
        if self._old_xdata is None:
            self.entity.discard_xdata(APPID)
        else:
            self.entity.set_xdata(APPID, self._old_xdata)
        document.dirty = True


def frame_of(document, entity) -> tuple | None:
    """(profile anchor, frame) of the profile the entity lies in."""
    pts = axis_points(entity) if entity.dxftype() in ("LINE", "LWPOLYLINE", "POLYLINE") else []
    if not pts:
        return None
    cx = sum(p[0] for p in pts) / len(pts)
    for anchor in profile_entities(document):
        frame = ProfileFrame.from_entity(anchor)
        xs = [v.x for v in anchor.vertices_in_wcs()]
        if xs and min(xs) - 1e-6 <= cx <= max(xs) + 1e-6:
            return anchor, frame
    return None


def is_grade(entity) -> bool:
    data = _xdata(entity)
    return bool(data) and data[0] == GRADE_TAG


def grade_of(entity, frame: ProfileFrame) -> list:
    """The design line as (s, z), in chainage order."""
    pts = [frame.to_chainage(x, y) for x, y in axis_points(entity)]
    return sorted(pts, key=lambda p: p[0])


def grade_profile_anchor(document, entity):
    data = _xdata(entity) or []
    handle = str(data[1]) if len(data) > 1 else ""
    for anchor in profile_entities(document):
        if anchor.dxf.handle == handle:
            return anchor
    return None


def register_grade(document, entity, anchor, frame: ProfileFrame,
                   text_height: float = 1.0) -> CompositeCommand:
    """Adopt a polyline drawn on the profile as its design line: layer,
    tag, a slope label on each segment and the elevation at each vertex."""
    grade = grade_of(entity, frame)
    commands = layer_commands(document, ("grade", "profile_text"))
    commands.append(TagEntityCommand(entity, LAYERS["grade"][0],
                                     [(1000, GRADE_TAG), (1005, anchor.dxf.handle)]))
    h = text_height
    text = LAYERS["profile_text"][0]
    for (s0, z0), (s1, z1), slope in zip(grade, grade[1:], _profile.grade_slopes(grade)):
        a, b = frame.to_drawing(s0, z0), frame.to_drawing(s1, z1)
        mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0 + 1.2 * h)
        angle = _math.degrees(_math.atan2(b[1] - a[1], b[0] - a[0]))
        commands.append(_text_cmd(f"{slope:+.2f} %", mid, h, text, readable_rotation(angle),
                                  tag=GRADE_TAG))
    for s_, z_ in grade:
        x, y = frame.to_drawing(s_, z_)
        commands.append(_text_cmd(f"{_alignment.format_station(s_)}  {z_:.2f}",
                                  (x, y - 1.6 * h), 0.8 * h, text, tag=GRADE_TAG))
    return CompositeCommand("grade line", commands)


# -- cross sections -----------------------------------------------------------------------

def draw_sections(document, tin: _tin.Tin, axis_entity, insert, step: float = 20.0,
                  half_width: float = 15.0, sample: float = 0.5, hscale: float = 1.0,
                  vscale: float = 2.0, columns: int = 4, text_height: float = 1.0,
                  grade: list | None = None, template: _profile.Template | None = None,
                  name: str = "EJE") -> CompositeCommand:
    """Every station's ground across the axis, one little plot each in a
    grid of ``columns``; with a grade and a template the design section is
    drawn over it and the cut and fill areas written."""
    axis = axis_points(axis_entity)
    h = text_height
    grid, text = LAYERS["sections_grid"][0], LAYERS["profile_text"][0]
    commands = layer_commands(document, ("sections", "sections_grid", "profile_text"))
    cell_w = (2 * half_width) * hscale + 6.0 * h
    cell_h = 0.0
    plots = []
    for st in _alignment.stations(axis, step):
        ground = _profile.cross_section(tin, st, half_width, sample)
        if len(ground) < 2:
            continue
        design = None
        zd = _profile.grade_at(grade, st.s) if grade else None
        if zd is not None and template is not None:
            design = _profile.design_section(ground, zd, template)
        zs = [z for _o, z in ground] + ([z for _o, z in design] if design else [])
        datum = _math.floor(min(zs)) - 1.0
        height = (_math.ceil(max(zs)) + 1.0 - datum) * vscale
        cell_h = max(cell_h, height + 6.0 * h)
        plots.append((st, ground, design, datum, height, zd))
    for k, (st, ground, design, datum, height, zd) in enumerate(plots):
        col, row = k % columns, k // columns
        ox = insert[0] + col * cell_w + 3.0 * h + half_width * hscale        # the axis
        oy = insert[1] - row * cell_h - height - 4.0 * h

        def to_xy(o, z, ox=ox, oy=oy, datum=datum):
            return (ox + o * hscale, oy + (z - datum) * vscale)
        commands.append(_line_cmd(to_xy(-half_width, datum), to_xy(half_width, datum), grid, SECTION_TAG))
        commands.append(_line_cmd(to_xy(0.0, datum), to_xy(0.0, datum + height / vscale), grid, SECTION_TAG))
        commands.append(_text_cmd(_alignment.format_station(st.s), to_xy(0.0, datum + height / vscale + 1.5 * h / vscale),
                                  h, text, tag=SECTION_TAG))
        commands.append(_text_cmd(f"{datum:.2f}", to_xy(-half_width - 0.8 * h / hscale, datum), 0.8 * h, text,
                                  align="MIDDLE_RIGHT", tag=SECTION_TAG))
        pts = [to_xy(o, z) for o, z in ground]
        commands.append(AddEntityCommand("TOPO-SECTION", lambda msp, pts=pts, s_=st.s: _section_polyline(
            msp, pts, s_, name), layer=LAYERS["sections"][0]))
        if design:
            dpts = [to_xy(o, z) for o, z in design]
            commands.extend(layer_commands(document, ("grade",)))
            commands.append(AddEntityCommand("TOPO-SECTION", lambda msp, pts=dpts, s_=st.s: _section_polyline(
                msp, pts, s_, name), layer=LAYERS["grade"][0]))
            cut, fill = _profile.areas(ground, design)
            commands.append(_text_cmd(_tr("cut {c:.2f}  fill {f:.2f}", c=cut, f=fill),
                                      to_xy(0.0, datum - 1.5 * h / vscale), 0.8 * h, text, tag=SECTION_TAG))
    return CompositeCommand("sections", commands)


def _section_polyline(msp, pts, s: float, name: str):
    ensure_appid(msp.doc)
    entity = msp.add_lwpolyline(pts)
    entity.set_xdata(APPID, [(1000, SECTION_TAG), (1000, name), (1040, float(s))])
    return entity


# -- earthworks ----------------------------------------------------------------------------

def earthworks_rows(tin: _tin.Tin, axis_entity, grade: list, step: float,
                    template: _profile.Template, half_width: float = 20.0,
                    method: str = "prismoidal") -> list:
    return _profile.earthworks(tin, axis_points(axis_entity), grade, step, template,
                               half_width, method=method)


def earthworks_table(document, rows, insert, text_height: float = 1.0,
                     name: str = "EJE") -> CompositeCommand:
    h = text_height
    data = []
    for r in rows:
        data.append([_alignment.format_station(r.s),
                     "" if r.z_ground is None else f"{r.z_ground:.2f}",
                     "" if r.z_design is None else f"{r.z_design:.2f}",
                     f"{r.cut_area:.2f}", f"{r.fill_area:.2f}",
                     f"{r.cut_volume:.1f}", f"{r.fill_volume:.1f}",
                     f"{r.cut_total:.1f}", f"{r.fill_total:.1f}", f"{r.mass:+.1f}"])
    headers = [_tr("STATION"), _tr("GROUND"), _tr("GRADE"), _tr("CUT AREA"), _tr("FILL AREA"),
               _tr("CUT VOL."), _tr("FILL VOL."), _tr("CUM. CUT"), _tr("CUM. FILL"), _tr("MASS")]
    widths = [w * h for w in (11.0, 8.0, 8.0, 9.0, 9.0, 10.0, 10.0, 10.0, 10.0, 10.0)]
    table = _tables.insert_table(insert, cols=10, col_width=10.0 * h, data_rows=len(data),
                                 row_height=2.0 * h, text_height=h,
                                 title=_tr("EARTHWORKS {name}", name=name), headers=headers,
                                 data=data, col_widths=widths)
    commands = layer_commands(document, ("earthworks",))
    for command in table.commands:
        command.layer = LAYERS["earthworks"][0]
    commands.extend(table.commands)
    return CompositeCommand("earthworks table", commands)


def earthworks_csv(rows) -> str:
    lines = ["station,ground_z,design_z,cut_area,fill_area,cut_volume,fill_volume,"
             "cum_cut,cum_fill,mass"]
    for r in rows:
        lines.append(",".join([
            f"{r.s:.2f}", "" if r.z_ground is None else f"{r.z_ground:.3f}",
            "" if r.z_design is None else f"{r.z_design:.3f}",
            f"{r.cut_area:.3f}", f"{r.fill_area:.3f}", f"{r.cut_volume:.2f}",
            f"{r.fill_volume:.2f}", f"{r.cut_total:.2f}", f"{r.fill_total:.2f}", f"{r.mass:.2f}"]))
    return "\n".join(lines) + "\n"
