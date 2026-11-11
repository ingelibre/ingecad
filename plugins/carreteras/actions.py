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


# =========================================================================================
# C3: the vertical alignment -- parabolic curves on Topography's grade line
# C4: the mass-haul diagram -- from Topography's earthworks
# and the superelevation table of the axis
# =========================================================================================

from . import vertical as _vertical  # noqa: E402

VERT_TAG = "CAR-VERTICAL"
VERTICAL = "vertical"
LAYERS["vertical"] = ("CAR-RASANTE", 1)
LAYERS["vertical_text"] = ("CAR-RASANTE-TEXTO", 7)
LAYERS["masshaul"] = ("CAR-MOVIMIENTO-TIERRAS", 3)


def topography():
    """Topography's actions: the loaded plugin (one instance, the window's),
    else the package (the suite); None when neither imports."""
    import importlib
    import sys

    module = sys.modules.get("ingecad_plugin_topografia.actions")
    if module is not None:
        return module
    try:
        return importlib.import_module("plugins.topografia.actions")
    except ImportError:
        return None


def vertical_of(entity) -> _vertical.VerticalAlignment | None:
    """The vertical alignment a design line keeps, or None."""
    tags = _tags(entity)
    if not tags or tags[0][1] != VERT_TAG:
        return None
    try:
        return _vertical.VerticalAlignment.decode(v for _c, v in tags[1:])
    except ValueError:
        return None


def grade_sommets(document, grade_entity) -> tuple:
    """(sommets, anchor, frame) of a grade line Topography registered."""
    topo = topography()
    if topo is None:
        raise ValueError(tr("Vertical curves need the Topography plugin."))
    if not topo.is_grade(grade_entity):
        raise ValueError(tr("Select a grade line registered with GRADELINE."))
    anchor = topo.grade_profile_anchor(document, grade_entity)
    if anchor is None:
        raise ValueError(tr("The grade line's profile is no longer in the drawing."))
    frame = topo.ProfileFrame.from_entity(anchor)
    sommets = topo.grade_of(grade_entity, frame)
    return sommets, anchor, frame


def vertical_curves(document, grade_entity, radii, text_height: float = 1.0) -> CompositeCommand:
    """VCURVES: the design line with a parabolic curve of ``radii[i]`` at
    each sommet of the grade line, drawn on the profile as a new grade line
    Topography reads (sections, volumes) -- 1 m chords, within s²/8R of the
    parabola -- that keeps its exact sommets and radii; the grades, and each
    curve's sommet, R, T and flèche, and its high or low point, written."""
    topo = topography()
    sommets, anchor, frame = grade_sommets(document, grade_entity)
    valign = _vertical.VerticalAlignment(sommets, radii)
    points = [frame.to_drawing(s, z) for s, z in valign.sample(1.0)]
    xdata = [(1000, VERT_TAG)] + [(1000, item) for item in valign.encode()]
    anchor_handle = anchor.dxf.handle

    def make(msp):
        ensure_appid(msp.doc, APPID)
        ensure_appid(msp.doc)
        entity = msp.add_lwpolyline(points)
        entity.set_xdata(APPID, xdata)
        entity.set_xdata(topo.APPID, [(1000, topo.GRADE_TAG), (1005, anchor_handle)])
        return entity

    commands = layer_commands(document, ("vertical", "vertical_text"))
    line = AddEntityCommand("CAR-VERTICAL", make, layer=LAYERS["vertical"][0])
    commands.append(line)
    link = _link(line)
    layer = LAYERS["vertical_text"][0]
    h = text_height
    # the grade of each straight stretch, between the curves
    bounds = [(valign.start, None)] + [(c.start, c.end) for c in valign.curves()] + [(None, valign.end)]
    for (s0, z0), (s1, z1), (_a, left), (right, _b), p in zip(
            valign.sommets, valign.sommets[1:], bounds, bounds[1:], valign.slopes()):
        a = left if left is not None else s0
        b = right if right is not None else s1
        if b - a < 1e-6:
            continue
        mid = (a + b) / 2.0
        x, y = frame.to_drawing(mid, valign.z_at(mid))
        xa, ya = frame.to_drawing(a, valign.z_at(a))
        xb, yb = frame.to_drawing(b, valign.z_at(b))
        angle = math.degrees(math.atan2(yb - ya, xb - xa))
        commands.append(_text(tr("{p:+.2f} % over {l:.2f} m", p=p * 100.0, l=b - a),
                              (x, y + 1.5 * h), h, layer, VERTICAL, link, readable_rotation(angle)))
    for c in valign.curves():
        x, y = frame.to_drawing(c.s, c.z)
        kind = tr("crest") if c.crest else tr("sag")
        commands.append(_line((x, y - 4.0 * h), (x, y + 4.0 * h), layer, VERTICAL, link))
        commands.append(_text(f"S{c.number}  {format_station(c.s)}  {c.z:.2f}", (x, y + 5.5 * h), h,
                              layer, VERTICAL, link))
        if c.radius > 0:
            commands.append(_text(tr("{kind} R = {r:.0f}  T = {t:.2f}  f = {f:.3f}", kind=kind,
                                     r=c.radius, t=c.tangent, f=c.flech),
                                  (x, y + 7.0 * h), 0.8 * h, layer, VERTICAL, link))
            for s_end in (c.start, c.end):
                xe, ye = frame.to_drawing(s_end, c.z_at(s_end))
                commands.append(_line((xe, ye - 2.0 * h), (xe, ye + 2.0 * h), layer, VERTICAL, link))
            ext = c.extremum
            if ext is not None:
                xe, ye = frame.to_drawing(*ext)
                label = tr("high point") if c.crest else tr("low point")
                commands.append(_text(f"{label} {format_station(ext[0])}  {ext[1]:.2f}",
                                      (xe, ye - 2.5 * h), 0.8 * h, layer, VERTICAL, link))
    command = CompositeCommand("vertical curves", commands)
    command.line_command = line
    command.vertical = valign
    return command


def vertical_table_rows(valign: _vertical.VerticalAlignment) -> list[list[str]]:
    rows = []
    for c in valign.curves():
        ext = c.extremum
        rows.append([f"S{c.number}", format_station(c.s), _f(c.z), f"{c.p1 * 100:+.3f}",
                     f"{c.p2 * 100:+.3f}", tr("Crest") if c.crest else tr("Sag"),
                     _f(c.radius, 0) if c.radius > 0 else "-",
                     _f(c.tangent) if c.radius > 0 else "-", _f(c.flech) if c.radius > 0 else "-",
                     format_station(c.start) if c.radius > 0 else "-",
                     format_station(c.end) if c.radius > 0 else "-",
                     f"{format_station(ext[0])} / {ext[1]:.3f}" if ext else "-"])
    return rows


def vertical_table(document, entity, insert, text_height: float = 2.0) -> CompositeCommand:
    """VCURVETABLE: one row per sommet -- station, elevation, grades in and
    out, crest or sag, R, T, flèche, start and end, high or low point."""
    valign = vertical_of(entity)
    if valign is None:
        raise ValueError(tr("Select a design line drawn by VCURVES."))
    rows = vertical_table_rows(valign)
    if not rows:
        raise ValueError(tr("The design line has no sommet."))
    h = text_height
    headers = [tr("SOMMET"), tr("STATION"), "Z", "p1 %", "p2 %", tr("TYPE"), "R", "T", "f",
               tr("STATION START"), tr("STATION END"), tr("HIGH / LOW POINT")]
    widths = [w * h for w in (7.0, 9.0, 8.0, 7.0, 7.0, 8.0, 7.0, 7.0, 6.0, 10.0, 10.0, 16.0)]
    table = tables.insert_table(insert, cols=len(headers), col_width=8.0 * h, data_rows=len(rows),
                                row_height=2.0 * h, text_height=h, title=tr("VERTICAL CURVES"),
                                headers=headers, data=rows, col_widths=widths)
    return _on_table_layer(document, table, "vertical table")


def verticals_of_axis(document, axis) -> list:
    """Every design line VCURVES drew on a profile of ``axis``."""
    topo = topography()
    if topo is None:
        return []
    out = []
    for entity in document.current_space():
        valign = vertical_of(entity) if entity.dxftype() == "LWPOLYLINE" else None
        if valign is None:
            continue
        anchor = topo.grade_profile_anchor(document, entity)
        frame = topo.ProfileFrame.from_entity(anchor) if anchor is not None else None
        if frame is not None and frame.axis_handle == axis.dxf.handle:
            out.append(valign)
    return out


# -- superelevation -------------------------------------------------------------------------

def superelevation_rows(alignment: geometry.Alignment, norm, category: str,
                        lanes: int = 2) -> list[list[str]]:
    """The dévers along the axis: for each curve the stations where the
    cross-slope changes, with the slope of the left and right lanes in %
    (negative: falling away from the axis; the crown is -2.5 / -2.5). The
    outer lane turns linearly along the clothoid from the crown to the
    curve's superelevation; the inner lane keeps the crown until the outer
    one reaches it. A curve without clothoids gets its value only."""
    from . import norms as _norms

    cat = norm.categories[norm.category_name(category)]
    crown = norm.superelevation.get("crown", -2.5)
    rows = []
    for pi in geometry.points_of_intersection(alignment):
        c = pi.curve
        if c is None:
            continue
        d = _norms.superelevation(norm, cat, c.radius)
        name = f"PI-{pi.number}"
        widen = _norms.widening(cat, c.radius)
        wtxt = _f(widen, 2) if widen else "-"
        if d is None or d < 0:
            rows.append([name, format_station(pi.pc_station), tr("crown kept"),
                         _f(crown, 2), _f(crown, 2), wtxt])
            continue

        def lanes_at(outer: float, inner: float) -> tuple[str, str]:
            # left curve: the right lane is the outer one
            left, right = (inner, outer) if pi.left else (outer, inner)
            return _f(left, 2), _f(right, 2)

        if not pi.spiral:
            l_, r_ = lanes_at(d, -d)
            rows.append([name, format_station(pi.pc_station), tr("PC: superelevation reached before"),
                         l_, r_, wtxt])
            rows.append([name, format_station(pi.pt_station), tr("PT: kept until after"), l_, r_, wtxt])
            continue
        ls = pi.sc_station - pi.pc_station
        span = d - crown

        def station_of(value: float, start: float, rising: bool) -> float:
            frac = (value - crown) / span
            return start + (frac if rising else 1.0 - frac) * ls

        pts = []
        for start, rising, tag in ((pi.pc_station, True, "in"), (pi.cs_station, False, "out")):
            seq = [(crown, crown, tr("crown")), (0.0, crown, tr("outer lane flat")),
                   (-crown, crown, tr("outer lane at the crown slope")), (d, -d, tr("full superelevation"))]
            if not rising:
                seq = list(reversed(seq))
            for outer, inner, what in seq:
                pts.append((station_of(outer, start, rising), outer, inner, what))
        for station, outer, inner, what in pts:
            l_, r_ = lanes_at(outer, inner)
            rows.append([name, format_station(station), what, l_, r_, wtxt])
    return rows


def superelevation_table(document, entity, insert, norm, category: str, lanes: int = 2,
                         text_height: float = 2.0) -> CompositeCommand:
    """SUPERELEV: the table of dévers (and widening) along the axis."""
    rows = superelevation_rows(alignment_of(entity), norm, category, lanes)
    if not rows:
        raise ValueError(tr("The axis has no curves."))
    h = text_height
    headers = ["PI", tr("STATION"), tr("POINT"), tr("LEFT %"), tr("RIGHT %"), tr("WIDENING")]
    widths = [w * h for w in (7.0, 10.0, 26.0, 9.0, 9.0, 10.0)]
    table = tables.insert_table(insert, cols=len(headers), col_width=10.0 * h, data_rows=len(rows),
                                row_height=2.0 * h, text_height=h,
                                title=tr("SUPERELEVATION - {norm} {cat}", norm=norm.id,
                                         cat=norm.category_name(category)),
                                headers=headers, data=rows, col_widths=widths)
    return _on_table_layer(document, table, "superelevation table")


# -- the mass-haul diagram ---------------------------------------------------------------------

@dataclass
class HaulSegment:
    start: float
    end: float
    volume: float            # moved within the segment (the largest ordinate)
    moment: float            # m³·m, the area of the diagram
    forward: bool            # cut carried forward (the ordinate is positive)

    @property
    def distance(self) -> float:
        """Mean haul distance."""
        return self.moment / self.volume if self.volume > 1e-9 else 0.0


@dataclass
class MassHaul:
    stations: list            # s
    ordinates: list           # cumulative cut x coefficient - fill, m³
    segments: list
    balance: float = 0.0

    @property
    def surplus(self) -> float:
        """Positive: to spoil (dépôt); negative: to borrow (emprunt)."""
        return self.ordinates[-1] - self.balance if self.ordinates else 0.0


def mass_haul(rows, coefficient: float = 1.0, balance: float = 0.0) -> MassHaul:
    """The Brückner/Lalanne mass diagram of Topography's earthworks rows:
    the cut is multiplied by ``coefficient`` (what a cubic metre dug
    becomes in the fill), the fill taken as is. Between two points where
    the ordinate crosses the balance line the earth is moved within the
    segment; its volume is the largest ordinate there, its moment the
    area of the diagram, and their quotient the mean haul distance."""
    stations, ordinates = [], []
    m = 0.0
    for r in rows:
        m += r.cut_volume * coefficient - r.fill_volume
        stations.append(r.s)
        ordinates.append(m)
    segments = []
    if len(stations) >= 2:
        y = [o - balance for o in ordinates]
        eps = 1e-9
        start, peak, area, sign = stations[0], abs(y[0]), 0.0, 0.0

        def close(end):
            nonlocal start, peak, area, sign
            if peak > eps:
                segments.append(HaulSegment(start, end, peak, area, sign > 0))
            start, peak, area, sign = end, 0.0, 0.0, 0.0

        for i in range(1, len(stations)):
            s0, s1, y0, y1 = stations[i - 1], stations[i], y[i - 1], y[i]
            if y0 * y1 < 0:                              # crosses inside the interval
                sc = s0 + (s1 - s0) * y0 / (y0 - y1)
                area += abs(y0) * (sc - s0) / 2.0
                peak = max(peak, abs(y0))
                sign = sign or y0
                close(sc)
                area = abs(y1) * (s1 - sc) / 2.0
                peak, sign = abs(y1), y1
            else:
                area += (abs(y0) + abs(y1)) * (s1 - s0) / 2.0
                peak = max(peak, abs(y0), abs(y1))
                sign = sign or (y1 if abs(y1) > eps else y0)
                if abs(y1) <= eps:                       # lands on the balance line
                    close(s1)
        if peak > eps:
            segments.append(HaulSegment(start, stations[-1], peak, area, sign > 0))
    return MassHaul(stations, ordinates, segments, balance)


def mass_haul_diagram(document, haul: MassHaul, insert, hscale: float = 1.0, height: float = 60.0,
                      text_height: float = 1.0, name: str = "EJE") -> CompositeCommand:
    """The mass diagram at ``insert`` (bottom-left): the ordinate against
    the station, the balance line, the station of each balance point,
    each segment's volume and mean haul distance, and the surplus or
    deficit at the end."""
    if len(haul.stations) < 2:
        raise ValueError(tr("Not enough stations for a mass diagram."))
    layer = LAYERS["masshaul"][0]
    h = text_height
    s0 = haul.stations[0]
    span = max(abs(o - haul.balance) for o in haul.ordinates) or 1.0
    vscale = height / 2.0 / span
    x0, ymid = insert[0], insert[1] + height / 2.0 + 4.0 * h

    def xy(s, m):
        return (x0 + (s - s0) * hscale, ymid + (m - haul.balance) * vscale)

    commands = layer_commands(document, ("masshaul",))
    tag = [(1000, "CAR-MASSHAUL"), (1000, name)]

    def line(a, b):
        def make(msp):
            ensure_appid(msp.doc, APPID)
            e = msp.add_line(a, b)
            e.set_xdata(APPID, tag)
            return e
        return AddEntityCommand("CAR-MASSHAUL", make, layer=layer)

    def text(t, pos, height_, align="MIDDLE_CENTER", rotation=0.0):
        def make(msp):
            ensure_appid(msp.doc, APPID)
            e = _text_entity(msp, t, pos, height_, rotation, align)
            e.set_xdata(APPID, tag)
            return e
        return AddEntityCommand("CAR-MASSHAUL", make, layer=layer)

    x_end = xy(haul.stations[-1], haul.balance)[0]
    commands.append(line((x0, ymid), (x_end, ymid)))                       # the balance line
    commands.append(line((x0, ymid - height / 2.0), (x0, ymid + height / 2.0)))
    pts = [xy(s, m) for s, m in zip(haul.stations, haul.ordinates)]

    def curve(msp):
        ensure_appid(msp.doc, APPID)
        e = msp.add_lwpolyline(pts)
        e.set_xdata(APPID, tag)
        return e
    commands.append(AddEntityCommand("CAR-MASSHAUL", curve, layer=layer))
    commands.append(text(f"+{span:.0f} m³", (x0 - 0.8 * h, ymid + height / 2.0), 0.8 * h, "MIDDLE_RIGHT"))
    commands.append(text(f"-{span:.0f} m³", (x0 - 0.8 * h, ymid - height / 2.0), 0.8 * h, "MIDDLE_RIGHT"))
    for seg in haul.segments:
        for s in (seg.start, seg.end):
            x, y = xy(s, haul.balance)
            commands.append(line((x, y - 1.0 * h), (x, y + 1.0 * h)))
        mid = (seg.start + seg.end) / 2.0
        x, _y = xy(mid, haul.balance)
        y = ymid + (1 if seg.forward else -1) * (height / 2.0 + 2.0 * h)
        commands.append(text(tr("{v:.0f} m³ over {d:.0f} m", v=seg.volume, d=seg.distance), (x, y), 0.8 * h))
    for s in sorted({round(seg.end, 3) for seg in haul.segments[:-1]}):
        x, y = xy(s, haul.balance)
        commands.append(text(format_station(s), (x, y - 2.0 * h), 0.7 * h, rotation=90.0, align="MIDDLE_RIGHT"))
    surplus = haul.surplus
    end_note = (tr("Surplus to spoil: {v:.0f} m³", v=surplus) if surplus > 0
                else tr("Deficit to borrow: {v:.0f} m³", v=-surplus))
    commands.append(text(tr("MASS DIAGRAM {name}", name=name), (x0, insert[1] + height + 10.0 * h),
                         1.4 * h, "MIDDLE_LEFT"))
    commands.append(text(end_note, (x0, insert[1] + 1.0 * h), h, "MIDDLE_LEFT"))
    return CompositeCommand("mass diagram", commands)
