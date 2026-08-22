# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Inquiry commands: DIST, ID, AREA, LIST — the Tools > Inquiry menu.

Prompts follow the AutoCAD Command Reference (`docs/reference/acad_acr.txt`,
DIST p.651, ID p.923, AREA p.145, LIST p.1049) and every number is printed
through the drawing's own unit settings (`core.units`), so a drawing in
architectural units answers in feet and inches like AutoCAD does.

Two documented deviations, both deliberate and both smaller menus rather
than different ones:

* DIST's multiple-point mode offers ``[Total]`` only — the dynamic-input
  Arc/Close/Length/Undo of recent releases are not here.
* AREA's Add/Subtract modes carry ``eXit`` to leave the mode, which is what
  AutoCAD does; the reference lists only the base prompt.

Nothing in this module mutates the document, so nothing here is a Command.
"""
from __future__ import annotations

import math

from core.hatch_boundary import boundary_polygon, polygon_area
from core.i18n import tr
from core.units import Units
from tools.base import Point, Tool


def _units(tool: Tool) -> Units:
    services = tool.ctx.services
    getter = getattr(services, "units", None)
    if getter is None:
        return Units()
    try:
        return getter()
    except Exception:
        return Units()


def _polyline_perimeter(points: list[Point], closed: bool) -> float:
    total = 0.0
    for a, b in zip(points, points[1:]):
        total += math.dist(a, b)
    if closed and len(points) > 2:
        total += math.dist(points[-1], points[0])
    return total


def entity_area_perimeter(entity) -> tuple[float, float, bool] | None:
    """(area, perimeter, closed) for an entity AREA accepts, else None.

    Curves are flattened through ezdxf so a polyline's bulges count as the
    arcs they are — measuring a lot boundary chord-by-chord would quietly
    under-report every curved frontage.
    """
    kind = entity.dxftype()
    if kind == "CIRCLE":
        r = float(entity.dxf.radius)
        return math.pi * r * r, 2.0 * math.pi * r, True
    if kind in ("LWPOLYLINE", "POLYLINE", "ELLIPSE", "SPLINE", "ARC"):
        try:
            from ezdxf import path as ezpath

            p = ezpath.make_path(entity)
            pts = [(v.x, v.y) for v in p.flattening(_flatten_for(entity))]
        except Exception:
            pts = boundary_polygon(entity) or []
        if len(pts) < 2:
            return None
        closed = _is_closed(entity)
        area = polygon_area(pts) if len(pts) > 2 else 0.0
        # An open object's area is computed as if closed, but the closing
        # line is NOT counted in the perimeter (AREA, p.146).
        perimeter = _polyline_perimeter(pts, closed=closed)
        return area, perimeter, closed
    poly = boundary_polygon(entity)
    if poly and len(poly) > 2:
        return polygon_area(poly), _polyline_perimeter(poly, True), True
    return None


def _flatten_for(entity) -> float:
    """Sagitta for curve flattening, scaled to the entity so tiny fillets
    and cadastre-sized arcs both come out accurate."""
    try:
        size = 1.0
        if entity.dxftype() == "CIRCLE":
            size = float(entity.dxf.radius) * 2.0
        elif entity.dxftype() == "ARC":
            size = float(entity.dxf.radius) * 2.0
        else:
            pts = boundary_polygon(entity) or []
            if pts:
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                size = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
        return max(abs(size) / 4000.0, 1e-9)
    except Exception:
        return 1e-3


def _is_closed(entity) -> bool:
    kind = entity.dxftype()
    if kind == "LWPOLYLINE":
        return bool(entity.closed)
    if kind == "POLYLINE":
        return bool(entity.is_closed)
    if kind in ("CIRCLE", "ELLIPSE"):
        return True
    if kind == "SPLINE":
        return bool(entity.closed)
    return False


class DistTool(Tool):
    """DIST: distance, angle and deltas between two points."""

    def start(self) -> None:
        self.name = "DIST"
        self._first: Point | None = None
        self._chain: list[Point] = []
        self._multiple = False
        self.prompt("Specify first point:")

    def on_option(self, text: str) -> bool:
        # The resolver first: it turns the localized keyword, or
        # AutoCAD's _global form, into the English key the
        # branches below have always compared against.
        token = self.option(text) or text.strip().upper()
        if self._first is not None and not self._multiple and token in ("M", "MULTIPLE"):
            self._start_multiple()
            return True
        if self._multiple and token in ("T", "TOTAL"):
            self._report_total()
            return True
        return False

    def on_enter(self) -> None:
        if self._multiple:
            self._report_total()
            return
        if self._first is not None:
            # <Multiple points> is the bracketed default of the second prompt.
            self._start_multiple()
            return
        self.ctx.finish()

    def _start_multiple(self) -> None:
        self._multiple = True
        self._chain = [self._first] if self._first else []
        self.prompt("Specify next point or [Total] <Total>:")

    def _report_total(self) -> None:
        units = _units(self)
        total = _polyline_perimeter(self._chain, closed=False)
        self.ctx.echo(tr("Distance = {value}", value=units.length(total)))
        self.ctx.finish()

    def on_point(self, point: Point) -> None:
        if self._first is None:
            self._first = point
            self.last_point = point
            self.prompt("Specify second point or <Multiple points>:")
            return
        if self._multiple:
            self._chain.append(point)
            self.last_point = point
            units = _units(self)
            running = _polyline_perimeter(self._chain, closed=False)
            self.ctx.echo(tr("Distance = {value}", value=units.length(running)))
            self.prompt("Specify next point or [Total] <Total>:")
            return
        self._report(self._first, point)

    def _report(self, a: Point, b: Point) -> None:
        units = _units(self)
        dx, dy = b[0] - a[0], b[1] - a[1]
        distance = math.hypot(dx, dy)
        angle = math.degrees(math.atan2(dy, dx)) % 360.0
        self.ctx.echo(
            tr("Distance = {d}, Angle in XY Plane = {a}, "
               "Angle from XY Plane = {z}",
               d=units.length(distance), a=units.angle(angle),
               z=units.angle(0.0)))
        self.ctx.echo(
            tr("Delta X = {x}, Delta Y = {y}, Delta Z = {z}",
               x=units.length(dx), y=units.length(dy), z=units.length(0.0)))
        self.ctx.finish()

    def preview_segments(self, cursor: Point):
        if self._multiple and self._chain:
            return [(self._chain[-1], cursor)]
        return [(self._first, cursor)] if self._first else []


class IdTool(Tool):
    """ID: the coordinates of one point, which then becomes the last point."""

    def start(self) -> None:
        self.name = "ID"
        self.prompt("Specify point:")

    def on_point(self, point: Point) -> None:
        units = _units(self)
        self.ctx.echo(
            tr("X = {x}   Y = {y}   Z = {z}",
               x=units.length(point[0]), y=units.length(point[1]),
               z=units.length(0.0)))
        self.last_point = point
        self.ctx.finish()


class AreaTool(Tool):
    """AREA: corner points or an object, with running Add/Subtract totals."""

    # Point mode snaps like any drawing command; the Object phase turns
    # picking on for this INSTANCE only (a ClassVar write would leak into
    # the next AREA the user starts).

    def start(self) -> None:
        self.name = "AREA"
        self._points: list[Point] = []
        self._mode = "start"        # start | points | object
        self._running = 0.0         # Add/Subtract balance
        self._sign = 0              # 0 = plain, +1 = add mode, -1 = subtract
        self.prompt(self._root_prompt())

    # -- prompts --------------------------------------------------------------
    def _root_prompt(self) -> str:
        if self._sign > 0:
            return ("(ADD mode) Specify first corner point or "
                    "[Object/Subtract area/eXit]:")
        if self._sign < 0:
            return ("(SUBTRACT mode) Specify first corner point or "
                    "[Object/Add area/eXit]:")
        return ("Specify first corner point or "
                "[Object/Add area/Subtract area] <Object>:")

    def on_option(self, text: str) -> bool:
        # The resolver first: it turns the localized keyword, or
        # AutoCAD's _global form, into the English key the
        # branches below have always compared against.
        token = self.option(text) or text.strip().upper()
        if self._mode == "points" and self._points:
            return False        # inside a polygon only points and Enter apply
        if token in ("O", "OBJECT"):
            self._mode = "object"
            self.entity_picker = True
            self.prompt("Select object:")
            return True
        if token in ("A", "ADD", "ADD AREA"):
            self._sign = 1
            self._mode = "start"
            self.prompt(self._root_prompt())
            return True
        if token in ("S", "SUBTRACT", "SUBTRACT AREA"):
            self._sign = -1
            self._mode = "start"
            self.prompt(self._root_prompt())
            return True
        if token in ("X", "EXIT") and self._sign:
            self._report_total()
            self.ctx.finish()
            return True
        return False

    def on_enter(self) -> None:
        if self._mode == "points" and len(self._points) >= 3:
            self._finish_polygon()
            return
        if self._mode == "start" and not self._points:
            # <Object> is the bracketed default.
            self._mode = "object"
            self.entity_picker = True
            self.prompt("Select object:")
            return
        self.ctx.finish()

    # -- input ----------------------------------------------------------------
    def on_point(self, point: Point) -> None:
        if self._mode == "object":
            services = self.ctx.services
            entity = services.pick_entity(point) if services else None
            if entity is None:
                self.prompt("Nothing selected. Select object:")
                return
            measured = entity_area_perimeter(entity)
            if measured is None:
                self.ctx.echo(
                    tr("{kind} has no area to report.", kind=entity.dxftype()))
                self.prompt("Select object:")
                return
            area, perimeter, closed = measured
            self._announce(area, perimeter, closed)
            self._accumulate(area)
            if self._sign:
                self.entity_picker = False
                self._mode = "start"
                self.prompt(self._root_prompt())
            else:
                self.entity_picker = False
                self.ctx.finish()
            return

        self._mode = "points"
        self._points.append(point)
        self.last_point = point
        self.prompt("Specify next point or press Enter for total:")

    def _finish_polygon(self) -> None:
        area = polygon_area(self._points)
        perimeter = _polyline_perimeter(self._points, closed=True)
        self._announce(area, perimeter, True)
        self._accumulate(area)
        self._points = []
        if self._sign:
            self._mode = "start"
            self.prompt(self._root_prompt())
        else:
            self.ctx.finish()

    # -- reporting ------------------------------------------------------------
    def _announce(self, area: float, perimeter: float, closed: bool) -> None:
        units = _units(self)
        label = tr("Perimeter") if closed else tr("Length")
        self.ctx.echo(
            tr("Area = {area}, {label} = {perimeter}",
               area=units.area(area), label=label,
               perimeter=units.length(perimeter)))

    def _accumulate(self, area: float) -> None:
        if not self._sign:
            return
        self._running += self._sign * area
        self._report_total()

    def _report_total(self) -> None:
        units = _units(self)
        self.ctx.echo(tr("Total area = {value}", value=units.area(self._running)))

    def preview_segments(self, cursor: Point):
        if not self._points:
            return []
        segments = list(zip(self._points, self._points[1:]))
        segments.append((self._points[-1], cursor))
        if len(self._points) > 1:
            segments.append((cursor, self._points[0]))
        return segments


class ListTool(Tool):
    """LIST: the property dump of the selected objects."""

    wants_selection = True

    def start(self) -> None:
        self.name = "LIST"

    def on_selection(self, entities: list) -> None:
        if not entities:
            self.ctx.echo(tr("Nothing selected."))
            self.ctx.finish()
            return
        units = _units(self)
        for entity in entities:
            for line in describe_entity(entity, units):
                self.ctx.echo(line)
        self.ctx.finish()


def describe_entity(entity, units: Units | None = None) -> list[str]:
    """The LIST report for one entity, in the drawing's units."""
    units = units or Units()
    dxf = entity.dxf
    kind = entity.dxftype()
    space = (tr("Paper space") if getattr(dxf, "paperspace", 0)
             else tr("Model space"))
    lines = [
        f"{kind:>18}      " + tr('Layer: "{layer}"',
                                 layer=getattr(dxf, "layer", "0")),
        f"{'':>18}      " + tr("Space: {space}", space=space),
        f"{'':>18}      " + tr("Handle = {handle}",
                               handle=getattr(dxf, "handle", None) or "-"),
    ]
    # Only non-default properties are listed, like AutoCAD (p.1049).
    if getattr(dxf, "color", 256) not in (256, None):
        lines.append(f"{'':>18}      " + tr("Color: {value}", value=dxf.color))
    linetype = getattr(dxf, "linetype", "BYLAYER")
    if linetype and linetype.upper() != "BYLAYER":
        lines.append(f"{'':>18}      " + tr("Linetype: {value}", value=linetype))
    lineweight = getattr(dxf, "lineweight", -1)
    if lineweight not in (-1, None):
        lines.append(f"{'':>18}      "
                     + tr("Lineweight: {value}", value=lineweight))
    thickness = getattr(dxf, "thickness", 0.0)
    if thickness:
        lines.append(f"{'':>18}      "
                     + tr("Thickness: {value}", value=units.length(thickness)))

    def point_line(label: str, p) -> str:
        return (f"{'':>8}{label}, X = {units.length(p[0])}  "
                f"Y = {units.length(p[1])}  "
                f"Z = {units.length(p[2] if len(p) > 2 else 0.0)}")

    if kind == "LINE":
        a, b = dxf.start, dxf.end
        lines.append(point_line(tr("from point"), (a.x, a.y, a.z)))
        lines.append(point_line(tr("to point"), (b.x, b.y, b.z)))
        dx, dy = b.x - a.x, b.y - a.y
        lines.append(f"{'':>8}" + tr(
            "Length = {length}, Angle in XY Plane = {angle}",
            length=units.length(math.hypot(dx, dy)),
            angle=units.angle(math.degrees(math.atan2(dy, dx)) % 360.0)))
        lines.append(f"{'':>8}" + tr(
            "Delta X = {x}, Delta Y = {y}, Delta Z = {z}",
            x=units.length(dx), y=units.length(dy),
            z=units.length(b.z - a.z)))
    elif kind in ("CIRCLE", "ARC"):
        c = dxf.center
        lines.append(point_line(tr("center point"), (c.x, c.y, c.z)))
        lines.append(f"{'':>8}" + tr("Radius = {value}",
                                     value=units.length(dxf.radius)))
        if kind == "CIRCLE":
            r = float(dxf.radius)
            lines.append(f"{'':>8}" + tr("Circumference = {value}",
                                         value=units.length(2 * math.pi * r)))
            lines.append(f"{'':>8}" + tr("Area = {value}",
                                         value=units.area(math.pi * r * r)))
        else:
            lines.append(f"{'':>8}" + tr(
                "Start angle = {a}, End angle = {b}",
                a=units.angle(dxf.start_angle), b=units.angle(dxf.end_angle)))
    elif kind in ("TEXT", "ATTDEF"):
        p = dxf.insert
        lines.append(point_line(tr("start point"), (p.x, p.y, p.z)))
        lines.append(f"{'':>8}" + tr('Text = "{value}"', value=dxf.text))
        lines.append(f"{'':>8}" + tr("Height = {value}",
                                     value=units.length(dxf.height)))
        if getattr(dxf, "rotation", 0.0):
            lines.append(f"{'':>8}" + tr("Rotation = {value}",
                                         value=units.angle(dxf.rotation)))
    elif kind == "MTEXT":
        p = dxf.insert
        lines.append(point_line(tr("insertion point"), (p.x, p.y, p.z)))
        text = entity.text.replace("\\P", " ")
        lines.append(f"{'':>8}" + tr('Text = "{value}"', value=text[:80]))
        lines.append(f"{'':>8}" + tr("Height = {value}",
                                     value=units.length(dxf.char_height)))
    elif kind == "INSERT":
        p = dxf.insert
        lines.append(f"{'':>8}" + tr('Block name = "{name}"', name=dxf.name))
        lines.append(point_line(tr("insertion point"), (p.x, p.y, p.z)))
        lines.append(f"{'':>8}" + tr(
            "X scale = {x}, Y scale = {y}, Rotation = {r}",
            x=f"{dxf.xscale:g}", y=f"{dxf.yscale:g}",
            r=units.angle(dxf.rotation)))
    elif kind in ("LWPOLYLINE", "POLYLINE"):
        measured = entity_area_perimeter(entity)
        closed = _is_closed(entity)
        lines.append(f"{'':>8}" + (tr("Closed") if closed else tr("Open")))
        if measured:
            area, perimeter, _ = measured
            label = tr("Perimeter") if closed else tr("Length")
            lines.append(f"{'':>8}" + tr("Area = {area}, {label} = {value}",
                                         area=units.area(area), label=label,
                                         value=units.length(perimeter)))
        try:
            points = [(p[0], p[1]) for p in entity.get_points("xy")]
        except Exception:
            points = [(v.dxf.location.x, v.dxf.location.y)
                      for v in getattr(entity, "vertices", [])]
        for point in points:
            lines.append(point_line(tr("at point"), (point[0], point[1], 0.0)))
    elif kind == "ELLIPSE":
        c = dxf.center
        lines.append(point_line(tr("center point"), (c.x, c.y, c.z)))
        major = math.hypot(dxf.major_axis.x, dxf.major_axis.y)
        lines.append(f"{'':>8}" + tr(
            "Major axis = {a}, Minor axis = {b}",
            a=units.length(major), b=units.length(major * dxf.ratio)))
    elif kind == "POINT":
        p = dxf.location
        lines.append(point_line(tr("point"), (p.x, p.y, p.z)))
    return lines


INQUIRY_TOOL_CLASSES = {
    "DIST": DistTool,
    "ID": IdTool,
    "AREA": AreaTool,
    "LIST": ListTool,
}
