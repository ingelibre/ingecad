# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The interactive side of the point commands: thin shells over
``actions``, prompting the way AutoCAD prompts.

Every tool works headless too (the suite drives them without a window):
where the GUI would open a file dialog, ``ctx.ask_text`` asks for the
path, and the import options fall back to their defaults.
"""
from __future__ import annotations

from pathlib import Path

from core.i18n import tr
from tools.base import Tool

from . import actions, geometry
from . import tin as tin_mod
from .points import (SurveyPoint, format_points, parse_bearing, parse_points,
                     point_from_bearing, sniff_order)

POINT_FILTER = "Point files (*.csv *.txt *.pnt *.xyz);;All files (*)"


def _window(ctx):
    return getattr(ctx.services, "window", None)


def _document(ctx):
    document = getattr(ctx.services, "document", None)
    if document is None:
        document = getattr(_window(ctx), "document", None)
    return document


def read_text(path) -> str:
    """The file as text: UTF-8, or the Latin-1 a Windows station writes."""
    raw = Path(path).read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


class ImportPointsTool(Tool):
    """PIMPORT: a CSV / TXT of survey points -> POINTs with labels."""

    def start(self) -> None:
        self.name = "PIMPORT"
        window = _window(self.ctx)
        if window is not None:
            from views import file_dialogs

            path = file_dialogs.get_open_file(window, tr("Import points"),
                                              tr(POINT_FILTER))
        else:
            path = self.ctx.ask_text(tr("Points file:"), "")
        if not path:
            self.ctx.finish()
            return
        try:
            text = read_text(path)
        except OSError as exc:
            self.ctx.echo(tr("Cannot read {path}: {error}", path=path, error=exc))
            self.ctx.finish()
            return
        order = sniff_order(text)
        style = actions.LabelStyle()
        if window is not None:
            from .dialogs import ImportOptionsDialog

            dialog = ImportOptionsDialog(window, text, order)
            if not dialog.exec():
                self.ctx.finish()
                return
            order, style = dialog.order(), dialog.style()
        try:
            points = parse_points(text, order)
        except ValueError as exc:
            self.ctx.echo(tr("Nothing imported: {error}", error=exc))
            self.ctx.finish()
            return
        document = _document(self.ctx)
        self.ctx.execute(actions.import_points(document, points, style))
        self.ctx.echo(tr("{n} points imported on {layer}", n=len(points),
                         layer=actions.LAYERS["point"][0]))
        if window is not None and hasattr(window, "viewport"):
            window.viewport.zoom_extents()
        self.ctx.finish()


class ExportPointsTool(Tool):
    """PEXPORT: the selected survey points (or all) -> P,N,E,Z,D text."""

    wants_selection = True

    def start(self) -> None:
        self.name = "PEXPORT"

    def selection_prompt(self) -> str:
        return tr("Select points to export (Enter for all):")

    def on_selection(self, entities: list) -> None:
        document = _document(self.ctx)
        chosen = [e for e in entities if e.dxftype() == "POINT"]
        points = actions.survey_points(document, chosen if chosen else None)
        if not points:
            self.ctx.echo(tr("No survey points to export."))
            self.ctx.finish()
            return
        window = _window(self.ctx)
        if window is not None:
            from views import file_dialogs

            path, _selected = file_dialogs.get_save_file(
                window, tr("Export points"), "puntos.csv",
                tr("CSV (*.csv);;Text (*.txt);;All files (*)"))
        else:
            path = self.ctx.ask_text(tr("Output file:"), "")
        if not path:
            self.ctx.finish()
            return
        Path(path).write_text(format_points(points), encoding="utf-8")
        self.ctx.echo(tr("{n} points written to {path}", n=len(points), path=path))
        self.ctx.finish()


class PointByBearingTool(Tool):
    """PBY: a traverse by bearing and distance from a base point.

    Base point, then bearing (``N45°30'E`` or an azimuth), distance,
    elevation and number for each new point; the new point becomes the
    base, so a boundary is typed leg by leg until Enter.
    """

    def start(self) -> None:
        self.name = "PBY"
        self._base = None
        self._stage = "base"
        self._azimuth = None
        self._distance = None
        self._z = 0.0
        self._last_azimuth = None
        self.prompt("Specify base point:")

    # the base can be clicked or typed as a coordinate
    def on_point(self, point) -> None:
        if self._stage == "base":
            self._base = (point[0], point[1])
            self.last_point = self._base
            self._ask_bearing()

    def _ask_bearing(self) -> None:
        self._stage = "bearing"
        if self._last_azimuth is None:
            self.prompt("Specify bearing (N45°30'E) or azimuth:")
        else:
            self.prompt("Specify bearing (N45°30'E) or azimuth <{last:.4f}>:",
                        last=self._last_azimuth)

    def on_option(self, text: str) -> bool:
        if self._stage == "bearing":
            try:
                self._azimuth = parse_bearing(text)
            except ValueError:
                self.ctx.echo(tr("Invalid bearing: {text}", text=text))
                return True
            self._stage = "distance"
            self.prompt("Specify distance:")
            return True
        if self._stage == "distance":
            try:
                self._distance = float(text.replace(",", "."))
            except ValueError:
                self.ctx.echo(tr("Invalid distance: {text}", text=text))
                return True
            self._stage = "elevation"
            self.prompt("Elevation <{z:g}>:", z=self._z)
            return True
        if self._stage == "elevation":
            try:
                self._z = float(text.replace(",", "."))
            except ValueError:
                self.ctx.echo(tr("Invalid elevation: {text}", text=text))
                return True
            self._ask_number()
            return True
        if self._stage == "number":
            self._place(text.strip())
            return True
        return False

    def _ask_number(self) -> None:
        self._stage = "number"
        self.prompt("Point number <{n}>:", n=actions.next_number(_document(self.ctx)))

    def on_enter(self) -> None:
        if self._stage == "bearing" and self._last_azimuth is not None:
            self._azimuth = self._last_azimuth
            self._stage = "distance"
            self.prompt("Specify distance:")
        elif self._stage == "elevation":
            self._ask_number()
        elif self._stage == "number":
            self._place(actions.next_number(_document(self.ctx)))
        else:
            self.ctx.finish()

    def _place(self, name: str) -> None:
        east, north = point_from_bearing(self._base, self._azimuth, self._distance)
        point = SurveyPoint(name, east, north, self._z)
        self.ctx.execute(actions.add_point(_document(self.ctx), point))
        self.ctx.echo(tr("Point {name} at E={e:.3f} N={n:.3f} Z={z:.3f}",
                         name=name, e=east, n=north, z=self._z))
        self._last_azimuth = self._azimuth
        self._base = (east, north)
        self.last_point = self._base
        self._ask_bearing()

    def preview_segments(self, cursor):
        if self._base is None:
            return []
        if self._stage == "bearing":
            return [(self._base, cursor)]
        if self._azimuth is not None and self._distance is not None:
            return [(self._base, point_from_bearing(self._base, self._azimuth,
                                                    self._distance))]
        return []


class RenumberPointsTool(Tool):
    """PRENUM: new numbers for the selected points, in numeric order."""

    wants_selection = True

    def start(self) -> None:
        self.name = "PRENUM"
        self._points = []

    def selection_prompt(self) -> str:
        return tr("Select points to renumber:")

    def on_selection(self, entities: list) -> None:
        points = [e for e in entities if actions.is_survey_point(e)]
        if not points:
            self.ctx.echo(tr("No survey points in the selection."))
            self.ctx.finish()
            return

        def key(entity):
            name = actions.survey_point(entity).name
            return (0, int(name)) if name.isdigit() else (1, name)

        self._points = sorted(points, key=key)
        self.prompt("Starting number <{n}>:", n=1)

    def on_option(self, text: str) -> bool:
        try:
            start = int(text.strip())
        except ValueError:
            self.ctx.echo(tr("Invalid number: {text}", text=text))
            return True
        self._run(start)
        return True

    def on_enter(self) -> None:
        if self._points:
            self._run(1)
        else:
            self.ctx.finish()

    def _run(self, start: int) -> None:
        self.ctx.execute(actions.renumber(self._points, start))
        self.ctx.echo(tr("{n} points renumbered from {start}",
                         n=len(self._points), start=start))
        self.ctx.finish()


class FindPointTool(Tool):
    """PFIND: locate a point by number -- select it and centre the view."""

    def start(self) -> None:
        self.name = "PFIND"
        self.prompt("Point number:")

    def on_option(self, text: str) -> bool:
        document = _document(self.ctx)
        entity = actions.find_point(document, text)
        if entity is None:
            self.ctx.echo(tr("Point {name} not found.", name=text.strip()))
            self.ctx.finish()
            return True
        point = actions.survey_point(entity)
        self.ctx.echo(tr("Point {name}: E={e:.3f} N={n:.3f} Z={z:.3f} {desc}",
                         name=point.name, e=point.east, n=point.north,
                         z=point.z, desc=point.desc).rstrip())
        window = _window(self.ctx)
        tools = getattr(window, "tools", None)
        if tools is not None:
            tools.selection = {entity.dxf.handle}
            tools._highlight_cache = None
            tools._grips_cache = None
        viewport = getattr(window, "viewport", None)
        if viewport is not None:
            viewport.push_view()
            viewport.view.cx, viewport.view.cy = point.east, point.north
            viewport.update()
        self.ctx.finish()
        return True


# ======================================================================
# T2: annotation, construction chart, areas, subdivision, UTM grid
# ======================================================================

def _number(text: str) -> float:
    return float(text.strip().replace(",", "."))


def _closed_polygon(entities):
    """The first closed polyline among ``entities``, or None."""
    for entity in entities:
        if geometry.polygon_vertices(entity) is not None:
            return entity
    return None


class AnnotateTool(Tool):
    """ANNOT: bearing and distance on lines and polyline segments, arc
    data on arcs; options first, Enter annotates."""

    wants_selection = True

    def start(self) -> None:
        self.name = "ANNOT"
        self._entities = []
        self._style = actions.AnnotationStyle()
        self._await_height = False

    def selection_prompt(self) -> str:
        return tr("Select lines, arcs and polylines to annotate:")

    def on_selection(self, entities: list) -> None:
        self._entities = [e for e in entities
                          if e.dxftype() in ("LINE", "ARC", "LWPOLYLINE", "POLYLINE")]
        if not self._entities:
            self.ctx.echo(tr("Nothing to annotate in the selection."))
            self.ctx.finish()
            return
        self._ask()

    def _ask(self) -> None:
        self._await_height = False
        self.prompt("Enter annotation option [Bearing/Distance/All/aZimuth/Height] "
                    "or press Enter to annotate:")

    def on_option(self, text: str) -> bool:
        if self._await_height:
            try:
                self._style.text_height = _number(text)
            except ValueError:
                self.ctx.echo(tr("Invalid height: {text}", text=text))
                return True
            self._ask()
            return True
        key = self.option(text)
        if key == "B":
            self._style.mode = "bearing"
        elif key == "D":
            self._style.mode = "distance"
        elif key == "A":
            self._style.mode = "both"
        elif key == "Z":
            self._style.azimuth = not self._style.azimuth
        elif key == "H":
            self._await_height = True
            self.prompt("Text height <{h:g}>:", h=self._style.text_height)
            return True
        else:
            return False
        self._ask()
        return True

    def on_enter(self) -> None:
        if self._await_height:
            self._ask()
            return
        if self._entities:
            self.ctx.execute(actions.annotate(_document(self.ctx), self._entities, self._style))
            self.ctx.echo(tr("{n} objects annotated", n=len(self._entities)))
        self.ctx.finish()


class ConstructionTableTool(Tool):
    """CTABLE: the construction chart of a closed polyline, placed by a
    click; options set bearing/azimuth, turn and text height."""

    wants_selection = True

    def start(self) -> None:
        self.name = "CTABLE"
        self._entity = None
        self._style = actions.ChartStyle()
        self._await_height = False

    def selection_prompt(self) -> str:
        return tr("Select the closed polyline:")

    def on_selection(self, entities: list) -> None:
        self._entity = _closed_polygon(entities)
        if self._entity is None:
            self.ctx.echo(tr("The selection has no closed polyline."))
            self.ctx.finish()
            return
        self._ask()

    def _ask(self) -> None:
        self._await_height = False
        self.prompt("Specify insertion point (top-left) or "
                    "[Azimuth/Bearing/Clockwise/cOunterclockwise/Height]:")

    def on_option(self, text: str) -> bool:
        if self._await_height:
            try:
                self._style.text_height = _number(text)
            except ValueError:
                self.ctx.echo(tr("Invalid height: {text}", text=text))
                return True
            self._ask()
            return True
        key = self.option(text)
        if key == "A":
            self._style.azimuth = True
        elif key == "B":
            self._style.azimuth = False
        elif key == "C":
            self._style.clockwise = True
        elif key == "O":
            self._style.clockwise = False
        elif key == "H":
            self._await_height = True
            self.prompt("Text height <{h:g}>:", h=self._style.text_height)
            return True
        else:
            return False
        self._ask()
        return True

    def on_point(self, point) -> None:
        if self._entity is None or self._await_height:
            return
        document = _document(self.ctx)
        data = actions.polygon_data(self._entity, self._style)
        self.ctx.execute(actions.construction_table(document, self._entity, point, self._style))
        self.ctx.echo(tr("Area {area}, perimeter {per}, {n} vertices.",
                         area=geometry.format_area(data.area, self._style.decimals),
                         per=geometry.format_length(data.perimeter, self._style.decimals),
                         n=len(data.vertices)))
        self.ctx.finish()


class AreaSumTool(Tool):
    """AREASUM: the area of the selected closed polylines and circles,
    echoed and optionally written on the drawing."""

    wants_selection = True

    def start(self) -> None:
        self.name = "AREASUM"
        self._total = 0.0
        self._count = 0

    def selection_prompt(self) -> str:
        return tr("Select closed polylines and circles:")

    def on_selection(self, entities: list) -> None:
        areas = [a for a in (actions.area_of(e) for e in entities) if a is not None]
        if not areas:
            self.ctx.echo(tr("No closed objects in the selection."))
            self.ctx.finish()
            return
        self._total, self._count = sum(areas), len(areas)
        self.ctx.echo(tr("Total area: {area} ({n} objects)",
                         area=geometry.format_area(self._total), n=self._count))
        self.prompt("Specify label point (Enter to finish):")

    def on_point(self, point) -> None:
        if not self._count:
            return
        self.ctx.execute(actions.area_label(
            _document(self.ctx), point,
            tr("TOTAL AREA = {area}", area=geometry.format_area(self._total)), 1.0))
        self.ctx.finish()


class SubdivideTool(Tool):
    """SUBDIV: cut a closed polyline -- parallel to a side for a given
    area, through a pivot for a given area, or by two points."""

    wants_selection = True

    def start(self) -> None:
        self.name = "SUBDIV"
        self._entity = None
        self._pts = None
        self._stage = "select"
        self._side = None
        self._pivot = None
        self._first = None
        self._cut = None

    def selection_prompt(self) -> str:
        return tr("Select the closed polyline to divide:")

    def on_selection(self, entities: list) -> None:
        self._entity = _closed_polygon(entities)
        if self._entity is None:
            self.ctx.echo(tr("The selection has no closed polyline."))
            self.ctx.finish()
            return
        self._pts = geometry.polygon_vertices(self._entity)
        self._stage = "method"
        self.prompt("Divide by [Parallel/pOint/Two points] <Parallel>:")

    def on_option(self, text: str) -> bool:
        if self._stage == "method":
            key = self.option(text)
            if key == "P" or not key and not text.strip():
                self._parallel()
            elif key == "O":
                self._stage = "pivot"
                self.prompt("Specify the pivot point on the boundary:")
            elif key == "T":
                self._stage = "two-first"
                self.prompt("Specify first point of the cut:")
            else:
                return False
            return True
        if self._stage in ("area-parallel", "area-point"):
            try:
                wanted = _number(text)
            except ValueError:
                self.ctx.echo(tr("Invalid area: {text}", text=text))
                return True
            if self._stage == "area-parallel":
                self._cut = geometry.cut_parallel_to_side(self._pts, self._side.index, wanted)
            else:
                self._cut = geometry.cut_through_point(self._pts, self._pivot, wanted)
            self._ask_split()
            return True
        if self._stage == "split":
            key = self.option(text)
            if key in ("Y", "N"):
                self._finish(split=(key == "Y"))
                return True
            return False
        return False

    def _parallel(self) -> None:
        self._stage = "side"
        self.prompt("Specify a point near the side the cut runs parallel to:")

    def on_point(self, point) -> None:
        if self._stage == "side":
            self._side = geometry.nearest_side(self._pts, point)
            self._stage = "area-parallel"
            self.prompt("Area of the piece next to that side:")
        elif self._stage == "pivot":
            self._pivot = geometry.project_on_boundary(self._pts, point)
            self._stage = "area-point"
            self.prompt("Area of the piece to the left of the cut, seen from the pivot:")
        elif self._stage == "two-first":
            self._first = point
            self._stage = "two-second"
            self.prompt("Specify second point of the cut:")
        elif self._stage == "two-second":
            self._cut = geometry.cut_by_two_points(self._pts, self._first, point)
            self._ask_split()

    def _ask_split(self) -> None:
        self._stage = "split"
        self.ctx.echo(tr("Pieces: {a} and {b}.",
                         a=geometry.format_area(self._cut.area_left),
                         b=geometry.format_area(self._cut.area_right)))
        self.prompt("Split the polygon into the two pieces? [Yes/No] <No>:")

    def on_enter(self) -> None:
        if self._stage == "method":
            self._parallel()
        elif self._stage == "split":
            self._finish(split=False)
        else:
            self.ctx.finish()

    def _finish(self, split: bool) -> None:
        self.ctx.execute(actions.subdivide(_document(self.ctx), self._entity, self._cut, split))
        self.ctx.echo(tr("Cut drawn from ({x1:.3f}, {y1:.3f}) to ({x2:.3f}, {y2:.3f}).",
                         x1=self._cut.start[0], y1=self._cut.start[1],
                         x2=self._cut.end[0], y2=self._cut.end[1]))
        self.ctx.finish()

    def preview_segments(self, cursor):
        if self._stage == "two-second" and self._first is not None:
            return [(self._first, cursor)]
        return []


class UtmGridTool(Tool):
    """UTMGRID: crosses or lines every N metres, with E/N labels."""

    def start(self) -> None:
        self.name = "UTMGRID"
        self._corner = None
        self._rect = None
        self._spacing = 100.0
        self._crosses = True
        self._stage = "first"
        self.prompt("Specify first corner of the grid or [Extents]:")

    def on_option(self, text: str) -> bool:
        if self._stage == "first" and self.option(text) == "E":
            box = self._extents()
            if box is None:
                self.ctx.echo(tr("The drawing is empty."))
                self.ctx.finish()
                return True
            self._rect = box
            self._ask_spacing()
            return True
        if self._stage == "spacing":
            try:
                self._spacing = _number(text)
                if self._spacing <= 0:
                    raise ValueError(text)
            except ValueError:
                self.ctx.echo(tr("Invalid spacing: {text}", text=text))
                return True
            self._ask_style()
            return True
        if self._stage == "style":
            key = self.option(text)
            if key in ("C", "L"):
                self._crosses = key == "C"
                self._run()
                return True
            return False
        return False

    def _extents(self):
        from ezdxf import bbox

        box = bbox.extents(_document(self.ctx).current_space(), fast=True)
        if not box.has_data:
            return None
        return (box.extmin.x, box.extmin.y, box.extmax.x, box.extmax.y)

    def on_point(self, point) -> None:
        if self._stage == "first":
            self._corner = point
            self.last_point = point
            self._stage = "second"
            self.prompt("Specify opposite corner:")
        elif self._stage == "second":
            self._rect = (self._corner[0], self._corner[1], point[0], point[1])
            self._ask_spacing()

    def _ask_spacing(self) -> None:
        self._stage = "spacing"
        self.prompt("Grid spacing <{s:g}>:", s=self._spacing)

    def _ask_style(self) -> None:
        self._stage = "style"
        self.prompt("Grid style [Crosses/Lines] <Crosses>:")

    def on_enter(self) -> None:
        if self._stage == "spacing":
            self._ask_style()
        elif self._stage == "style":
            self._run()
        else:
            self.ctx.finish()

    def _run(self) -> None:
        x0, y0, x1, y1 = self._rect
        self.ctx.execute(actions.utm_grid(_document(self.ctx), x0, y0, x1, y1,
                                          self._spacing, 1.0, self._crosses))
        nx = len(geometry.grid_values(min(x0, x1), max(x0, x1), self._spacing))
        ny = len(geometry.grid_values(min(y0, y1), max(y0, y1), self._spacing))
        self.ctx.echo(tr("UTM grid: {n} intersections every {s:g} m", n=nx * ny, s=self._spacing))
        self.ctx.finish()

    def preview_segments(self, cursor):
        if self._stage == "second" and self._corner is not None:
            c = self._corner
            return [(c, (cursor[0], c[1])), ((cursor[0], c[1]), cursor),
                    (cursor, (c[0], cursor[1])), ((c[0], cursor[1]), c)]
        return []


# ======================================================================
# T3: the surface
# ======================================================================

class TinTool(Tool):
    """TIN: triangulate the selected points (and breaklines) into a surface."""

    wants_selection = True

    def start(self) -> None:
        self.name = "TIN"
        self._points = []
        self._breaklines = []
        self._name = "TERRENO"
        self._stage = "name"

    def selection_prompt(self) -> str:
        return tr("Select points and breaklines to triangulate:")

    def on_selection(self, entities: list) -> None:
        self._points, self._breaklines = actions.surface_inputs(entities)
        if len(self._points) + sum(len(b) for b in self._breaklines) < 3:
            self.ctx.echo(tr("A surface needs at least three points."))
            self.ctx.finish()
            return
        self._stage = "name"
        self.prompt("Surface name <{name}>:", name=self._name)

    def on_option(self, text: str) -> bool:
        if self._stage == "name":
            self._name = text.strip() or self._name
            self._ask_edge()
            return True
        if self._stage == "edge":
            try:
                value = _number(text)
            except ValueError:
                self.ctx.echo(tr("Invalid length: {text}", text=text))
                return True
            self._run(value if value > 0 else None)
            return True
        return False

    def _ask_edge(self) -> None:
        self._stage = "edge"
        self.prompt("Maximum edge length (Enter for none):")

    def on_enter(self) -> None:
        if self._stage == "name":
            self._ask_edge()
        elif self._stage == "edge":
            self._run(None)
        else:
            self.ctx.finish()

    def _run(self, max_edge) -> None:
        try:
            tin = tin_mod.build_tin(self._points, self._breaklines, max_edge=max_edge,
                                    name=self._name)
        except ValueError as exc:
            self.ctx.echo(tr("Cannot triangulate: {error}", error=exc))
            self.ctx.finish()
            return
        self.ctx.execute(actions.build_surface(_document(self.ctx), tin))
        self.ctx.echo(actions.surface_report(tin))
        self.ctx.finish()


class TinEditTool(Tool):
    """TINEDIT: flip an edge, delete a triangle, insert a point, clip to a
    polygon -- on the drawn surface, each an undo step."""

    def start(self) -> None:
        self.name = "TINEDIT"
        self._stage = "option"
        self._point = None
        self._ask()

    def _faces(self):
        return actions.surface_faces(_document(self.ctx))

    def _ask(self) -> None:
        self._stage = "option"
        self.prompt("Enter option [Flip/Delete/Insert/Clip] or press Enter to finish:")

    def on_option(self, text: str) -> bool:
        if self._stage == "option":
            key = self.option(text)
            prompts = {"F": "Pick a point near the edge to flip:",
                       "D": "Pick a point inside the triangle to delete:",
                       "I": "Specify the point to insert:",
                       "C": "Pick the boundary polyline:"}
            if key not in prompts:
                return False
            self._stage = key
            self.prompt(prompts[key])
            return True
        if self._stage == "z":
            try:
                z = _number(text)
            except ValueError:
                self.ctx.echo(tr("Invalid elevation: {text}", text=text))
                return True
            self._insert(z)
            return True
        return False

    def on_point(self, point) -> None:
        faces = self._faces()
        if not faces:
            self.ctx.echo(tr("There is no surface in this space."))
            self.ctx.finish()
            return
        if self._stage == "F":
            hit = actions.nearest_edge(faces, point)
            command = actions.flip_edge(_document(self.ctx), hit[0], hit[1]) if hit else None
            if command is None:
                self.ctx.echo(tr("That edge cannot be flipped."))
            else:
                self.ctx.execute(command)
                self.ctx.echo(tr("Edge flipped."))
            self._ask()
        elif self._stage == "D":
            face = actions.face_at(faces, point)
            if face is None:
                self.ctx.echo(tr("No triangle there."))
            else:
                self.ctx.execute(actions.delete_faces([face]))
                self.ctx.echo(tr("Triangle deleted."))
            self._ask()
        elif self._stage == "I":
            self._point = point
            tin = actions.read_surface(_document(self.ctx), faces=faces)
            z = tin.z_at(point[0], point[1])
            self._stage = "z"
            self.prompt("Elevation <{z:.2f}>:", z=z if z is not None else 0.0)
        elif self._stage == "C":
            pick = getattr(self.ctx.services, "pick_entity", None)
            entity = pick(point) if pick else None
            polygon = geometry.polygon_vertices(entity) if entity is not None else None
            if polygon is None:
                self.ctx.echo(tr("Pick a closed polyline."))
            else:
                command = actions.clip_surface(faces, polygon)
                self.ctx.execute(command)
                self.ctx.echo(tr("{n} triangles outside the boundary removed.",
                                 n=len(command.commands[0].entities) if command.commands else 0))
            self._ask()

    def on_enter(self) -> None:
        if self._stage == "z":
            tin = actions.read_surface(_document(self.ctx), faces=self._faces())
            z = tin.z_at(self._point[0], self._point[1])
            self._insert(z if z is not None else 0.0)
        elif self._stage == "option":
            self.ctx.finish()
        else:
            self._ask()

    def _insert(self, z: float) -> None:
        command = actions.insert_point(_document(self.ctx), self._faces(),
                                       (self._point[0], self._point[1], z))
        if command is None:
            self.ctx.echo(tr("The point is outside the surface."))
        else:
            self.ctx.execute(command)
            self.ctx.echo(tr("Point inserted at Z={z:.2f}.", z=z))
        self._ask()


class TinCheckTool(Tool):
    """TINCHECK: what the surface in this space is made of."""

    def start(self) -> None:
        self.name = "TINCHECK"
        document = _document(self.ctx)
        names = actions.surface_names(document)
        if not names:
            self.ctx.echo(tr("There is no surface in this space."))
        for name in names:
            tin = actions.read_surface(document, name)
            self.ctx.echo(actions.surface_report(tin))
            bad = tin.stats()["bad_edges"]
            if bad:
                self.ctx.echo(tr("{n} edges are shared by more than two triangles.", n=bad))
        self.ctx.finish()


TOOL_CLASSES = {
    "TIN": TinTool,
    "TINEDIT": TinEditTool,
    "TINCHECK": TinCheckTool,
    "PIMPORT": ImportPointsTool,
    "PEXPORT": ExportPointsTool,
    "PBY": PointByBearingTool,
    "PRENUM": RenumberPointsTool,
    "PFIND": FindPointTool,
    "ANNOT": AnnotateTool,
    "CTABLE": ConstructionTableTool,
    "AREASUM": AreaSumTool,
    "SUBDIV": SubdivideTool,
    "UTMGRID": UtmGridTool,
}
