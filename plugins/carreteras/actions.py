# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Roads, headless: every operation is an undoable Command over the ezdxf
document, and everything it draws is a plain DXF entity.

An axis (eje) is an open LWPOLYLINE of tangents and arcs on ``CAR-EJE``
whose XDATA, under the plugin's own APPID ``INGECAD_CARRETERAS``, holds its
start station, its direction and the stationing it was last drawn with.
What the plugin draws for an axis -- station ticks, their labels, the PI,
PC and PT marks -- carries the axis handle in the same APPID, so drawing
the stationing again replaces the old one in one undo step. The tables are
plain lines and text (``core.tables``), a snapshot like Topography's chart.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

from core import tables
from core.actions import AddEntityCommand, EraseCommand
from core.commands import Command, CompositeCommand
from core.i18n import tr
from core.layers import NewLayerCommand
from core.surveying import (cad_to_azimuth, format_bearing, format_dms,
                            format_station, readable_rotation)
from core.xdata import ensure_appid

from . import geometry

#: The plugin's own APPID: never ``INGECAD`` (core/xdata.py says why).
APPID = "INGECAD_CARRETERAS"
AXIS_TAG = "CAR-AXIS"
ANNOT_TAG = "CAR-ANNOT"
#: after the axis parameters, an axis with clothoids keeps its exact
#: elements (the polyline only draws them, by chords)
ELEM_TAG = "CAR-ELEMENTS"

#: (layer, ACI colour) per kind of object.
LAYERS = {
    "axis": ("CAR-EJE", 1),
    "ticks": ("CAR-ESTACAS", 7),
    "stations": ("CAR-PROGRESIVAS", 3),
    "curves": ("CAR-CURVAS", 4),
    "tables": ("CAR-CUADROS", 7),
}

#: annotation kinds, each regenerated with the axis
STATIONS = "stations"
CURVES = "curves"


@dataclass(frozen=True)
class AxisParams:
    """What the axis remembers: where its stationing starts and runs, and
    how it was last drawn."""

    start: float = 0.0               # start station, metres
    reverse: bool = False            # stationed from the polyline's last vertex
    interval: float = 20.0
    tick: float = 4.0                # tick length, across the axis
    height: float = 2.0              # text height

    def xdata(self) -> list:
        return [(1000, AXIS_TAG), (1040, self.start), (1070, 1 if self.reverse else 0),
                (1040, self.interval), (1040, self.tick), (1040, self.height)]

    @classmethod
    def from_xdata(cls, tags) -> "AxisParams | None":
        values = [v for _code, v in tags]
        if len(values) < 6 or values[0] != AXIS_TAG:
            return None
        return cls(float(values[1]), bool(int(values[2])), float(values[3]),
                   float(values[4]), float(values[5]))


# -- reading the drawing -------------------------------------------------------------

def _tags(entity):
    try:
        return list(entity.get_xdata(APPID))
    except Exception:
        return None


def axis_params(entity) -> AxisParams | None:
    """The axis data of ``entity``, or None if it is not an axis."""
    if entity.dxftype() != "LWPOLYLINE":
        return None
    tags = _tags(entity)
    return AxisParams.from_xdata(tags) if tags else None


def is_axis(entity) -> bool:
    return axis_params(entity) is not None


def polyline_vertices(entity) -> list:
    """(x, y, bulge) of an LWPOLYLINE in world coordinates; an arc drawn
    with its extrusion pointing down turns the other way seen from above."""
    if entity.dxftype() != "LWPOLYLINE":
        raise ValueError("the axis must be a polyline")
    if entity.closed:
        raise ValueError("the axis must be an open polyline")
    ocs = entity.ocs()
    flip = ocs.uz.z < 0
    out = []
    for x, y, b in entity.get_points("xyb"):
        w = ocs.to_wcs((x, y, 0.0))
        out.append((w.x, w.y, -b if flip else b))
    return out


def _fingerprint(verts) -> str:
    """What the polyline looked like when its elements were written: a
    grip edit since changes it, and the elements are then not trusted."""
    import zlib

    text = ";".join(f"{x:.3f},{y:.3f},{b:.6f}" for x, y, b in verts)
    return f"{len(verts)};{zlib.crc32(text.encode()):08x}"


def element_tags(elements, verts) -> list:
    return [(1000, ELEM_TAG), (1000, _fingerprint(verts))] + [(1000, e.encode()) for e in elements]


def _split_tags(tags):
    """(axis parameter tags, element tags) of an axis' XDATA."""
    tags = list(tags or [])
    for i, (_code, value) in enumerate(tags):
        if value == ELEM_TAG:
            return tags[:i], tags[i:]
    return tags, []


def stored_elements(entity) -> list | None:
    """The exact elements an axis keeps (clothoids), or None when it keeps
    none or the polyline was edited since."""
    _params, tail = _split_tags(_tags(entity))
    if len(tail) < 3:
        return None
    try:
        verts = polyline_vertices(entity)
    except ValueError:
        return None
    if str(tail[1][1]) != _fingerprint(verts):
        return None
    try:
        return [geometry.Element.decode(v) for _c, v in tail[2:]]
    except ValueError:
        return None


def alignment_of(entity, params: AxisParams | None = None) -> geometry.Alignment:
    """The axis as stationed geometry, walked the way its stationing runs:
    its exact elements when it keeps clothoids, else its polyline."""
    params = params or axis_params(entity) or AxisParams()
    elements = stored_elements(entity)
    if elements:
        alignment = geometry.ElementAlignment(elements, params.start)
        return alignment.reversed() if params.reverse else alignment
    verts = polyline_vertices(entity)
    if params.reverse:
        verts = geometry.reverse_vertices(verts)
    return geometry.Alignment(verts, params.start)


def annotation_kind(entity) -> tuple[str, str] | None:
    """(kind, axis handle) of something drawn for an axis."""
    tags = _tags(entity)
    if not tags or len(tags) < 3 or tags[0][1] != ANNOT_TAG:
        return None
    return str(tags[1][1]), str(tags[2][1])


def annotations_of(document, axis, kinds=None) -> list:
    handle = axis.dxf.handle
    out = []
    for entity in document.current_space():
        found = annotation_kind(entity)
        if found and found[1] == handle and (kinds is None or found[0] in kinds):
            out.append(entity)
    return out


def axes_in(entities) -> list:
    return [e for e in entities if is_axis(e)]


# -- commands --------------------------------------------------------------------------

def layer_commands(document, kinds) -> list[Command]:
    out = []
    for kind in kinds:
        name, color = LAYERS[kind]
        if name not in document.doc.layers:
            out.append(NewLayerCommand(name, color=color))
    return out


class SetAxisCommand(Command):
    """Make a polyline an axis (or change what its axis remembers): its
    XDATA under the plugin's APPID, and the axis layer. Undo puts both back."""

    name = "road axis"

    def __init__(self, entity, params: AxisParams, layer: str | None = LAYERS["axis"][0]) -> None:
        self.entity = entity
        self.params = params
        self.layer = layer
        self._old_layer = None
        self._old_xdata = None

    def do(self, document) -> None:
        ensure_appid(document.doc, APPID)
        self._old_layer = self.entity.dxf.layer
        self._old_xdata = _tags(self.entity)
        if self.layer and self.layer in document.doc.layers:
            self.entity.dxf.layer = self.layer
        _old, elements = _split_tags(self._old_xdata)
        self.entity.set_xdata(APPID, self.params.xdata() + elements)
        document.dirty = True

    def undo(self, document) -> None:
        self.entity.dxf.layer = self._old_layer
        if self._old_xdata:
            self.entity.set_xdata(APPID, self._old_xdata)
        else:
            self.entity.discard_xdata(APPID)
        document.dirty = True


def _link(axis):
    """The axis handle, read when the entity is made: the axis may be made
    by an earlier step of the same command (HCURVES)."""
    if isinstance(axis, AddEntityCommand):
        return lambda: axis.entity.dxf.handle
    return lambda: axis.dxf.handle


def _tagged(make, kind: str, link):
    def factory(msp):
        ensure_appid(msp.doc, APPID)
        entity = make(msp)
        entity.set_xdata(APPID, [(1000, ANNOT_TAG), (1000, kind), (1005, link())])
        return entity
    return factory


def _line(a, b, layer: str, kind: str, link) -> Command:
    return AddEntityCommand("CAR-LINE", _tagged(
        lambda msp: msp.add_line((a[0], a[1]), (b[0], b[1])), kind, link), layer=layer)


def _text_entity(msp, text, pos, height, rotation, align):
    from ezdxf.enums import TextEntityAlignment

    entity = msp.add_text(text, height=height, dxfattribs={"rotation": rotation})
    entity.set_placement((pos[0], pos[1]), align=getattr(TextEntityAlignment, align))
    return entity


def _text(text, pos, height, layer, kind, link, rotation=0.0, align="MIDDLE_CENTER") -> Command:
    return AddEntityCommand("CAR-TEXT", _tagged(
        lambda msp: _text_entity(msp, text, pos, height, rotation, align), kind, link),
        layer=layer)


def _along(angle_deg: float):
    """(rotation, alignment) for a label written along a direction away
    from its base point, kept readable: flipped, it ends there instead."""
    rotation = readable_rotation(angle_deg)
    flipped = abs(((angle_deg - rotation) % 360.0) - 180.0) < 1e-6
    return rotation, ("MIDDLE_RIGHT" if flipped else "MIDDLE_LEFT")


def station_label(station: float, regular: bool) -> str:
    """``0+020`` at a regular tick, ``0+013.57`` at the start or the end."""
    return format_station(station, 0 if regular else 2)


def stationing_commands(alignment: geometry.Alignment, params: AxisParams, link) -> list[Command]:
    """Ticks across the axis every ``interval`` metres and their labels,
    on the left of the direction of travel; full kilometres longer and
    larger."""
    out: list[Command] = []
    tick_layer, text_layer = LAYERS["ticks"][0], LAYERS["stations"][0]
    for tick in geometry.station_ticks(alignment, params.interval):
        rad = math.radians(tick.angle)
        nx, ny = -math.sin(rad), math.cos(rad)               # left of travel
        half = params.tick / 2.0 * (1.5 if tick.km else 1.0)
        x, y = tick.point
        a, b = (x - nx * half, y - ny * half), (x + nx * half, y + ny * half)
        out.append(_line(a, b, tick_layer, STATIONS, link))
        height = params.height * (1.5 if tick.km else 1.0)
        gap = 0.5 * params.height
        rotation, align = _along(tick.angle + 90.0)
        out.append(_text(station_label(tick.station, tick.regular),
                         (b[0] + nx * gap, b[1] + ny * gap), height, text_layer,
                         STATIONS, link, rotation, align))
    return out


def curve_mark_commands(alignment: geometry.Alignment, params: AxisParams, link) -> list[Command]:
    """At each PI its name; at each curve's PC and PT a radial mark with
    its station, written on the right of the direction of travel -- the
    side the stationing leaves free. They went on the outside of the
    curve, which on a right turn is the stationing's side: the PC and PT
    labels lay over the station labels next to them."""
    out: list[Command] = []
    layer = LAYERS["curves"][0]
    h = params.height
    for pi in geometry.points_of_intersection(alignment):
        px, py = pi.point
        if pi.curve is None:
            out.append(_text(f"PI-{pi.number}", (px, py + 1.5 * h), h, layer, CURVES, link))
            continue
        # the PI label beyond the PI, away from the curve
        (mx, my), _ = alignment.at_station((pi.pc_station + pi.pt_station) / 2.0)
        dx, dy = px - mx, py - my
        d = math.hypot(dx, dy) or 1.0
        out.append(_text(f"PI-{pi.number}", (px + dx / d * 1.5 * h, py + dy / d * 1.5 * h),
                         h, layer, CURVES, link))
        if pi.spiral:
            stops = ((tr("TS"), pi.pc, pi.pc_station), (tr("SC"), pi.sc, pi.sc_station),
                     (tr("CS"), pi.cs, pi.cs_station), (tr("ST"), pi.pt, pi.pt_station))
        else:
            stops = ((tr("PC"), pi.pc, pi.pc_station), (tr("PT"), pi.pt, pi.pt_station))
        for name, point, station in stops:
            _, angle = alignment.at_station(station)
            rad = math.radians(angle)
            nx, ny = -math.sin(rad), math.cos(rad)
            # (nx, ny) is the left of travel, where the stations are
            ox, oy = -nx, -ny
            a = point
            b = (point[0] + ox * params.tick, point[1] + oy * params.tick)
            out.append(_line(a, b, layer, CURVES, link))
            rotation, align = _along(math.degrees(math.atan2(oy, ox)))
            out.append(_text(f"{name} {format_station(station)}",
                             (b[0] + ox * 0.5 * h, b[1] + oy * 0.5 * h), h, layer,
                             CURVES, link, rotation, align))
    return out


def _drawing_commands(alignment, params, link, kinds) -> list[Command]:
    out: list[Command] = []
    if STATIONS in kinds:
        out.extend(stationing_commands(alignment, params, link))
    if CURVES in kinds:
        out.extend(curve_mark_commands(alignment, params, link))
    return out


def define_axis(document, entity, params: AxisParams) -> CompositeCommand:
    """ROADAXIS: the polyline becomes an axis with ``params``; whatever was
    already drawn for it (stations, curve marks) is redrawn to match."""
    alignment = alignment_of(entity, params)             # refuses a bad polyline now
    existing = annotations_of(document, entity)
    kinds = {annotation_kind(e)[0] for e in existing}
    commands = layer_commands(document, ("axis", "ticks", "stations", "curves"))
    commands.append(SetAxisCommand(entity, params))
    if existing:
        commands.append(EraseCommand(existing))
        commands.extend(_drawing_commands(alignment, params, _link(entity), kinds))
    return CompositeCommand("road axis", commands)


def draw_stationing(document, entity, params: AxisParams | None = None) -> CompositeCommand:
    """STATIONING: the stationing of the axis with ``params`` (or the ones
    it remembers), replacing the one drawn before -- one undo step. A plain
    polyline becomes an axis on the way."""
    params = params or axis_params(entity) or AxisParams()
    alignment = alignment_of(entity, params)
    existing = annotations_of(document, entity)
    kinds = {annotation_kind(e)[0] for e in existing} | {STATIONS}
    commands = layer_commands(document, ("axis", "ticks", "stations", "curves"))
    commands.append(SetAxisCommand(entity, params))
    if existing:
        commands.append(EraseCommand(existing))
    commands.extend(_drawing_commands(alignment, params, _link(entity), kinds))
    return CompositeCommand("stationing", commands)


def regenerate(document, axes) -> CompositeCommand:
    """RESTATION: redraw what each axis has drawn (its stationing, its curve
    marks) from the axis as it is now -- after a grip edit, say."""
    commands: list[Command] = layer_commands(document, ("ticks", "stations", "curves"))
    for entity in axes:
        params = axis_params(entity)
        if params is None:
            continue
        existing = annotations_of(document, entity)
        kinds = {annotation_kind(e)[0] for e in existing} or {STATIONS}
        alignment = alignment_of(entity, params)
        if existing:
            commands.append(EraseCommand(existing))
        commands.extend(_drawing_commands(alignment, params, _link(entity), kinds))
    return CompositeCommand("restation", commands)


def reverse_axis(document, entity) -> CompositeCommand:
    """AXISREVERSE: the stationing runs the other way, from the same start
    station; what was drawn for the axis is redrawn."""
    params = axis_params(entity) or AxisParams()
    return define_axis(document, entity, replace(params, reverse=not params.reverse))


# -- the tables -------------------------------------------------------------------------

def _f(value: float, decimals: int = 3) -> str:
    return f"{value:.{decimals}f}"


# -- angles: degrees (DMS, bearings) or grads (gisements), as the office works ---------------

SETTING_ANGLES = "carreteras/angles"
UNITS = ("deg", "grad")


def angle_unit() -> str:
    try:
        from PySide6.QtCore import QSettings

        unit = str(QSettings().value(SETTING_ANGLES, "deg"))
    except Exception:
        unit = "deg"
    return unit if unit in UNITS else "deg"


def set_angle_unit(unit: str) -> None:
    try:
        from PySide6.QtCore import QSettings

        QSettings().setValue(SETTING_ANGLES, unit if unit in UNITS else "deg")
    except Exception:
        pass


def format_angle(degrees: float, unit: str = "deg") -> str:
    """An angle (a deflection, Δ): DMS, or grads to the ten-thousandth."""
    if unit == "grad":
        return f"{degrees * 400.0 / 360.0:.4f} gr"
    return format_dms(degrees)


def gisement(cad_angle: float) -> float:
    """The direction as a French gisement: grads, from north, clockwise."""
    return cad_to_azimuth(cad_angle) * 400.0 / 360.0 % 400.0


def axis_table_rows(alignment: geometry.Alignment, unit: str = "deg") -> list[list[str]]:
    """Start, every PI, end: station, east, north, and the tangent leaving
    it -- bearing, azimuth and distance to the next one (in grads: the
    gisement and the distance)."""
    pis = geometry.points_of_intersection(alignment)
    (x0, y0), _ = alignment.at(0.0)
    (x1, y1), _ = alignment.at(alignment.length)
    stops = [(tr("START"), (x0, y0), alignment.start_station)]
    stops += [(f"PI-{p.number}", p.point, p.station) for p in pis]
    stops.append((tr("END"), (x1, y1), alignment.end_station))
    rows = []
    for i, (name, (x, y), station) in enumerate(stops):
        if unit == "grad":
            row = [name, format_station(station), _f(x), _f(y), "", ""]
        else:
            row = [name, format_station(station), _f(x), _f(y), "", "", ""]
        if i + 1 < len(stops):
            nx, ny = stops[i + 1][1]
            cad = math.degrees(math.atan2(ny - y, nx - x))
            if unit == "grad":
                row[4] = f"{gisement(cad):.4f}"
                row[5] = _f(math.hypot(nx - x, ny - y))
            else:
                az = cad_to_azimuth(cad)
                row[4] = format_bearing(az)
                row[5] = format_dms(az)
                row[6] = _f(math.hypot(nx - x, ny - y))
        rows.append(row)
    return rows


def axis_table(document, entity, insert, text_height: float = 2.0,
               unit: str | None = None) -> CompositeCommand:
    """AXISTABLE: the cuadro del eje at ``insert`` (top-left)."""
    unit = unit or angle_unit()
    alignment = alignment_of(entity)
    rows = axis_table_rows(alignment, unit)
    h = text_height
    if unit == "grad":
        headers = ["PI", tr("STATION"), tr("EAST"), tr("NORTH"), tr("GISEMENT (gr)"), tr("DISTANCE")]
        widths = [w * h for w in (7.0, 9.0, 10.0, 11.0, 11.0, 10.0)]
    else:
        headers = ["PI", tr("STATION"), tr("EAST"), tr("NORTH"), tr("BEARING"),
                   tr("AZIMUTH"), tr("DISTANCE")]
        widths = [w * h for w in (7.0, 9.0, 10.0, 11.0, 12.0, 10.0, 10.0)]
    table = tables.insert_table(insert, cols=len(headers), col_width=10.0 * h, data_rows=len(rows),
                                row_height=2.0 * h, text_height=h, title=tr("AXIS TABLE"),
                                headers=headers, data=rows, col_widths=widths)
    return _on_table_layer(document, table, "axis table")


def has_spirals(alignment: geometry.Alignment) -> bool:
    return any(e.is_spiral for e in geometry.as_elements(alignment))


def curve_table_rows(alignment: geometry.Alignment, unit: str = "deg") -> list[list[str]]:
    """One row per curve. With clothoids: Δ, direction, R, Ls, A, T, the
    circle's length, E and the four points' stations (TS, SC, CS, ST)."""
    rows = []
    n = 0
    spirals = has_spirals(alignment)
    for pi in geometry.points_of_intersection(alignment):
        c = pi.curve
        if c is None:
            continue
        n += 1
        side = tr("Left") if pi.left else tr("Right")
        if spirals:
            ls = getattr(c, "ls", 0.0)
            arc = getattr(c, "arc_length", c.length)
            a = _f(math.sqrt(ls * c.radius), 2) if ls > 0 else "-"
            rows.append([f"C-{n}", f"PI-{pi.number}", format_angle(c.delta, unit), side,
                         _f(c.radius, 2), _f(ls, 2) if ls > 0 else "-", a, _f(c.tangent), _f(arc),
                         _f(c.external), format_station(pi.pc_station),
                         format_station(pi.sc_station) if pi.sc_station is not None else "-",
                         format_station(pi.cs_station) if pi.cs_station is not None else "-",
                         format_station(pi.pt_station)])
        else:
            rows.append([f"C-{n}", f"PI-{pi.number}", format_angle(c.delta, unit), side,
                         _f(c.radius, 2), _f(c.tangent), _f(c.length), _f(c.external),
                         _f(c.middle_ordinate), _f(c.chord),
                         format_station(pi.pc_station), format_station(pi.pt_station)])
    return rows


def curve_table(document, entity, insert, text_height: float = 2.0,
                unit: str | None = None) -> CompositeCommand:
    """CURVETABLE: one row per curve of the axis -- Δ, direction, R, T, Lc,
    E, M, C and the PC and PT stations (with clothoids: Ls, A and the TS,
    SC, CS and ST stations)."""
    unit = unit or angle_unit()
    alignment = alignment_of(entity)
    rows = curve_table_rows(alignment, unit)
    if not rows:
        raise ValueError(tr("The axis has no curves."))
    h = text_height
    if has_spirals(alignment):
        headers = [tr("CURVE"), "PI", "Δ", tr("DIRECTION"), "R", "Ls", "A", "T", "Lc", "E",
                   tr("TS"), tr("SC"), tr("CS"), tr("ST")]
        widths = [w * h for w in (7.0, 6.0, 10.0, 10.0, 7.0, 6.0, 7.0, 7.0, 7.0, 6.0, 9.0, 9.0, 9.0, 9.0)]
    else:
        headers = [tr("CURVE"), "PI", "Δ", tr("DIRECTION"), "R", "T", "Lc", "E", "M", "C",
                   tr("PC"), tr("PT")]
        widths = [w * h for w in (7.0, 6.0, 10.0, 10.0, 7.0, 7.0, 7.0, 6.0, 6.0, 7.0, 9.0, 9.0)]
    table = tables.insert_table(insert, cols=len(headers), col_width=7.0 * h, data_rows=len(rows),
                                row_height=2.0 * h, text_height=h,
                                title=tr("HORIZONTAL CURVE ELEMENTS"),
                                headers=headers, data=rows, col_widths=widths)
    return _on_table_layer(document, table, "curve table")


def element_table_rows(alignment: geometry.Alignment, unit: str = "deg") -> list[list[str]]:
    """The French tableau des éléments: every straight, arc and clothoid,
    with its stations, length, radius, A, direction and start point."""
    rows = []
    run = alignment.start_station
    kinds = {"line": tr("Straight"), "arc": tr("Arc"), "clothoid": tr("Clothoid")}
    for n, e in enumerate(geometry.as_elements(alignment), 1):
        if e.is_line:
            radius, a, side = "-", "-", "-"
        elif e.is_arc:
            radius, a = _f(e.radius, 2), "-"
            side = tr("Left") if e.left else tr("Right")
        else:
            r0 = "∞" if abs(e.k0) < 1e-15 else _f(1.0 / abs(e.k0), 2)
            r1 = "∞" if abs(e.k1) < 1e-15 else _f(1.0 / abs(e.k1), 2)
            radius, a = f"{r0} → {r1}", _f(e.parameter, 2)
            side = tr("Left") if e.left else tr("Right")
        direction = (f"{gisement(e.start_angle):.4f}" if unit == "grad"
                     else format_dms(cad_to_azimuth(e.start_angle)))
        rows.append([str(n), kinds[e.kind], side, format_station(run), format_station(run + e.length),
                     _f(e.length), radius, a, direction, _f(e.start[0]), _f(e.start[1])])
        run += e.length
    return rows


def element_table(document, entity, insert, text_height: float = 2.0,
                  unit: str | None = None) -> CompositeCommand:
    """AXISELEMENTS: the tableau des éléments du tracé en plan."""
    unit = unit or angle_unit()
    rows = element_table_rows(alignment_of(entity), unit)
    h = text_height
    headers = ["N°", tr("TYPE"), tr("DIRECTION"), tr("STATION START"), tr("STATION END"),
               tr("LENGTH"), "R", "A", tr("GISEMENT (gr)") if unit == "grad" else tr("AZIMUTH"),
               "X", "Y"]
    widths = [w * h for w in (4.0, 9.0, 8.0, 10.0, 10.0, 8.0, 13.0, 7.0, 10.0, 11.0, 12.0)]
    table = tables.insert_table(insert, cols=len(headers), col_width=9.0 * h, data_rows=len(rows),
                                row_height=2.0 * h, text_height=h,
                                title=tr("HORIZONTAL ALIGNMENT ELEMENTS"),
                                headers=headers, data=rows, col_widths=widths)
    return _on_table_layer(document, table, "element table")


def _on_table_layer(document, table: CompositeCommand, name: str) -> CompositeCommand:
    commands = layer_commands(document, ("tables",))
    for command in table.commands:
        command.layer = LAYERS["tables"][0]
    commands.extend(table.commands)
    return CompositeCommand(name, commands)


# -- C2: horizontal curves --------------------------------------------------------------

def tangent_points(entity) -> list:
    """The vertices of a chain of tangents (an open polyline without arcs)."""
    verts = polyline_vertices(entity)
    if any(abs(v[2]) > 1e-12 for v in verts):
        raise ValueError(tr("The polyline already has arcs: draw the tangents only."))
    pts = []
    for x, y, _b in verts:
        if not pts or math.hypot(x - pts[-1][0], y - pts[-1][1]) > geometry.EPS:
            pts.append((x, y))
    if len(pts) < 3:
        raise ValueError(tr("The polyline needs at least two tangents."))
    return pts


def fit_axis(document, tangents_entity, radii, params: AxisParams | None = None,
             spirals=None) -> CompositeCommand:
    """HCURVES: a new axis on ``CAR-EJE`` through the tangents with a simple
    curve of ``radii[i]`` at each PI -- introduced by symmetric clothoids
    of length ``spirals[i]`` when given -- and its PI, PC and PT (TS, SC,
    CS, ST) marks. The chain of tangents stays as it was. Raises
    geometry.TangentOverlap and geometry.SpiralTooLong."""
    params = params or AxisParams()
    points = tangent_points(tangents_entity)
    if spirals and any(ls > 0 for ls in spirals):
        elements = geometry.fit_spiral_curves(points, radii, spirals)
        alignment = geometry.ElementAlignment(elements, params.start)
        vertices = alignment.vertices
        xdata = params.xdata() + element_tags(elements, vertices)
    else:
        vertices = geometry.fit_curves(points, radii)
        alignment = geometry.Alignment(vertices, params.start)
        xdata = params.xdata()

    def make(msp):
        ensure_appid(msp.doc, APPID)
        entity = msp.add_lwpolyline(vertices, format="xyb")
        entity.set_xdata(APPID, xdata)
        return entity

    commands = layer_commands(document, ("axis", "ticks", "stations", "curves"))
    axis_cmd = AddEntityCommand("CAR-AXIS", make, layer=LAYERS["axis"][0])
    commands.append(axis_cmd)
    commands.extend(curve_mark_commands(alignment, params, _link(axis_cmd)))
    command = CompositeCommand("horizontal curves", commands)
    command.axis_command = axis_cmd
    return command
