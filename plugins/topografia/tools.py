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
from . import grading as grading_mod
from . import profile as profile_mod
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


# ======================================================================
# T4: contour lines, labels, slope zones
# ======================================================================

def _surface(ctx):
    """The first surface of the current space, or None."""
    document = _document(ctx)
    names = actions.surface_names(document)
    return actions.read_surface(document, names[0]) if names else None


class ContourTool(Tool):
    """CONTOUR: contour lines of the surface, minor and major, optionally
    smoothed (which may let two levels touch -- the prompt says so)."""

    def start(self) -> None:
        self.name = "CONTOUR"
        self._tin = _surface(self.ctx)
        if self._tin is None:
            self.ctx.echo(tr("There is no surface in this space."))
            self.ctx.finish()
            return
        st = self._tin.stats()
        span = st["z_max"] - st["z_min"]
        self._interval = 1.0 if span >= 5.0 else (0.5 if span >= 2.0 else 0.25)
        self._major = 5
        self._smooth = 0
        self._stage = "interval"
        self.prompt("Contour interval <{i:g}>:", i=self._interval)

    def on_option(self, text: str) -> bool:
        if self._stage == "interval":
            try:
                value = _number(text)
                if value <= 0:
                    raise ValueError(text)
            except ValueError:
                self.ctx.echo(tr("Invalid interval: {text}", text=text))
                return True
            self._interval = value
            self._ask_major()
            return True
        if self._stage == "major":
            try:
                self._major = max(0, int(text.strip()))
            except ValueError:
                self.ctx.echo(tr("Invalid number: {text}", text=text))
                return True
            self._ask_smooth()
            return True
        if self._stage == "smooth":
            key = self.option(text)
            if key not in ("N", "L", "S"):
                return False
            self._smooth = {"N": 0, "L": 1, "S": 3}[key]
            self._run()
            return True
        return False

    def _ask_major(self) -> None:
        self._stage = "major"
        self.prompt("Major contour every <{n}> minor:", n=self._major)

    def _ask_smooth(self) -> None:
        self._stage = "smooth"
        self.prompt("Smoothing [None/Light/Strong] <None> (smoothed curves may touch):")

    def on_enter(self) -> None:
        if self._stage == "interval":
            self._ask_major()
        elif self._stage == "major":
            self._ask_smooth()
        elif self._stage == "smooth":
            self._run()
        else:
            self.ctx.finish()

    def _run(self) -> None:
        command = actions.draw_contours(_document(self.ctx), self._tin, self._interval,
                                        self._major, self._smooth)
        drawn = [c for c in command.commands if c.name == "TOPO-CONTOUR"]
        self.ctx.execute(command)
        major = sum(1 for c in drawn if c.layer == actions.LAYERS["contour_major"][0])
        self.ctx.echo(tr("{n} contours drawn from {name} ({m} major), every {i:g} m",
                         n=len(drawn), name=self._tin.name, m=major, i=self._interval))
        self.ctx.finish()


class ContourLabelTool(Tool):
    """CONTOURLABEL: elevations on the contours, every N metres or where
    clicked."""

    def start(self) -> None:
        self.name = "CONTOURLABEL"
        self._contours = actions.contour_entities(_document(self.ctx))
        if not self._contours:
            self.ctx.echo(tr("There are no contours in this space."))
            self.ctx.finish()
            return
        self._spacing = 50.0
        self._height = 1.0
        self._major_only = True
        self._stage = "mode"
        self.prompt("Label contours [Auto/Pick] <Auto>:")

    def _decimals(self) -> int:
        levels = [actions.contour_level(e) for e in self._contours]
        return 0 if all(abs(v - round(v)) < 1e-9 for v in levels) else 2

    def on_option(self, text: str) -> bool:
        if self._stage == "mode":
            key = self.option(text)
            if key == "A":
                self._ask_spacing()
            elif key == "P":
                self._stage = "pick"
                self.prompt("Pick a contour (Enter to finish):")
            else:
                return False
            return True
        if self._stage == "spacing":
            try:
                self._spacing = _number(text)
            except ValueError:
                self.ctx.echo(tr("Invalid spacing: {text}", text=text))
                return True
            self._ask_height()
            return True
        if self._stage == "height":
            try:
                self._height = _number(text)
            except ValueError:
                self.ctx.echo(tr("Invalid height: {text}", text=text))
                return True
            self._ask_which()
            return True
        if self._stage == "which":
            key = self.option(text)
            if key not in ("A", "M"):
                return False
            self._major_only = key == "M"
            self._run_auto()
            return True
        return False

    def _ask_spacing(self) -> None:
        self._stage = "spacing"
        self.prompt("Label spacing along the contour <{s:g}>:", s=self._spacing)

    def _ask_height(self) -> None:
        self._stage = "height"
        self.prompt("Text height <{h:g}>:", h=self._height)

    def _ask_which(self) -> None:
        self._stage = "which"
        self.prompt("Which contours [All/Major] <Major>:")

    def on_enter(self) -> None:
        if self._stage == "mode":
            self._ask_spacing()
        elif self._stage == "spacing":
            self._ask_height()
        elif self._stage == "height":
            self._ask_which()
        elif self._stage == "which":
            self._run_auto()
        else:
            self.ctx.finish()

    def _run_auto(self) -> None:
        major = actions.LAYERS["contour_major"][0]
        chosen = [e for e in self._contours if not self._major_only or e.dxf.layer == major]
        if not chosen:
            chosen = self._contours
        command = actions.label_contours(_document(self.ctx), chosen, self._height,
                                         spacing=self._spacing, decimals=self._decimals())
        self.ctx.execute(command)
        self.ctx.echo(tr("{n} labels placed on {m} contours",
                         n=sum(1 for c in command.commands if c.name == "TOPO-CONTOUR-LABEL"),
                         m=len(chosen)))
        self.ctx.finish()

    def on_point(self, point) -> None:
        if self._stage != "pick":
            return
        pick = getattr(self.ctx.services, "pick_entity", None)
        entity = pick(point) if pick else None
        if entity is None or not actions.is_contour(entity):
            self.ctx.echo(tr("That is not a contour."))
            return
        self.ctx.execute(actions.label_contours(_document(self.ctx), [entity], self._height,
                                                at=point, decimals=self._decimals()))
        self.prompt("Pick a contour (Enter to finish):")


class SlopeZonesTool(Tool):
    """SLOPEZONES: colour the surface by slope class, with a legend."""

    def start(self) -> None:
        self.name = "SLOPEZONES"
        self._tin = _surface(self.ctx)
        if self._tin is None:
            self.ctx.echo(tr("There is no surface in this space."))
            self.ctx.finish()
            return
        self._breaks = [5.0, 10.0, 20.0, 30.0]
        self._stage = "breaks"
        self.prompt("Slope breaks in % <{b}>:", b=", ".join(f"{b:g}" for b in self._breaks))

    def on_option(self, text: str) -> bool:
        if self._stage == "breaks":
            try:
                values = sorted(_number(v) for v in text.replace(";", ",").split(",") if v.strip())
                if not values:
                    raise ValueError(text)
            except ValueError:
                self.ctx.echo(tr("Invalid breaks: {text}", text=text))
                return True
            self._breaks = values
            self._ask_legend()
            return True
        return False

    def _ask_legend(self) -> None:
        self._stage = "legend"
        self.prompt("Specify legend point (Enter for none):")

    def on_enter(self) -> None:
        if self._stage == "breaks":
            self._ask_legend()
        elif self._stage == "legend":
            self._run(None)
        else:
            self.ctx.finish()

    def on_point(self, point) -> None:
        if self._stage == "legend":
            self._run(point)

    def _run(self, legend_at) -> None:
        self.ctx.execute(actions.slope_zones(_document(self.ctx), self._tin, self._breaks, legend_at))
        for label, area, count in actions.slope_report(self._tin, self._breaks):
            if count:
                self.ctx.echo(tr("{label}: {area} ({n} triangles)",
                                 label=label, area=geometry.format_area(area), n=count))
        self.ctx.finish()


# ======================================================================
# T5: profile, grade line, cross sections, earthworks
# ======================================================================

def _axis_in(entities):
    for entity in entities:
        if entity.dxftype() in ("LINE", "LWPOLYLINE", "POLYLINE") and not actions.is_grade(entity) \
                and not actions.is_profile(entity) and not actions.is_contour(entity):
            return entity
    return None


def _grade_in(entities):
    for entity in entities:
        if actions.is_grade(entity):
            return entity
    return None


class ProfileTool(Tool):
    """PROFILE: the ground along a selected axis, drawn as a profile with
    its bands at a clicked point; a selected grade line (of an earlier
    profile) comes along as the design line."""

    wants_selection = True

    def start(self) -> None:
        self.name = "PROFILE"
        self._axis = None
        self._grade = None
        self._tin = _surface(self.ctx)
        self._step = 20.0
        self._hscale = 1.0
        self._vscale = 10.0
        self._stage = "step"
        if self._tin is None:
            self.ctx.echo(tr("There is no surface in this space."))
            self.ctx.finish()

    def selection_prompt(self) -> str:
        return tr("Select the axis (and a grade line, if any):")

    def on_selection(self, entities: list) -> None:
        self._axis = _axis_in(entities)
        if self._axis is None:
            self.ctx.echo(tr("The selection has no axis polyline."))
            self.ctx.finish()
            return
        grade_entity = _grade_in(entities)
        if grade_entity is not None:
            anchor = actions.grade_profile_anchor(_document(self.ctx), grade_entity)
            if anchor is not None:
                self._grade = actions.grade_of(grade_entity, actions.ProfileFrame.from_entity(anchor))
        self._stage = "step"
        self.prompt("Station step <{s:g}>:", s=self._step)

    def on_option(self, text: str) -> bool:
        try:
            value = _number(text)
            if value <= 0:
                raise ValueError(text)
        except ValueError:
            self.ctx.echo(tr("Invalid number: {text}", text=text))
            return True
        if self._stage == "step":
            self._step = value
            self._ask_scales()
        elif self._stage == "hscale":
            self._hscale = 1000.0 / value
            self._stage = "vscale"
            self.prompt("Vertical scale 1:<{v:g}>:", v=1000.0 / self._vscale)
        elif self._stage == "vscale":
            self._vscale = 1000.0 / value
            self._ask_point()
        else:
            return False
        return True

    def _ask_scales(self) -> None:
        self._stage = "hscale"
        self.prompt("Horizontal scale 1:<{h:g}>:", h=1000.0 / self._hscale)

    def _ask_point(self) -> None:
        self._stage = "point"
        self.prompt("Specify the bottom-left corner of the profile:")

    def on_enter(self) -> None:
        if self._stage == "step":
            self._ask_scales()
        elif self._stage == "hscale":
            self._stage = "vscale"
            self.prompt("Vertical scale 1:<{v:g}>:", v=1000.0 / self._vscale)
        elif self._stage == "vscale":
            self._ask_point()
        else:
            self.ctx.finish()

    def on_point(self, point) -> None:
        if self._stage != "point":
            return
        try:
            command = actions.draw_profile(_document(self.ctx), self._tin, self._axis, point,
                                           self._step, self._hscale, self._vscale, 1.0,
                                           grade=self._grade)
        except ValueError as exc:
            self.ctx.echo(tr("Cannot draw the profile: {error}", error=exc))
            self.ctx.finish()
            return
        self.ctx.execute(command)
        n = sum(1 for c in command.commands if isinstance(c, type(command.commands[-1])))
        self.ctx.echo(tr("Profile drawn: {n} stations every {s:g} m", n=len(
            profile_mod.ground_profile(self._tin, actions.axis_points(self._axis), self._step)), s=self._step))
        self.ctx.finish()


class GradeLineTool(Tool):
    """GRADELINE: a polyline drawn over a profile becomes its design line,
    with the slope of each segment and the elevation at each vertex."""

    wants_selection = True

    def start(self) -> None:
        self.name = "GRADELINE"

    def selection_prompt(self) -> str:
        return tr("Select the polyline drawn on the profile:")

    def on_selection(self, entities: list) -> None:
        document = _document(self.ctx)
        for entity in entities:
            if entity.dxftype() not in ("LINE", "LWPOLYLINE", "POLYLINE") or actions.is_profile(entity):
                continue
            found = actions.frame_of(document, entity)
            if found is None:
                continue
            anchor, frame = found
            self.ctx.execute(actions.register_grade(document, entity, anchor, frame))
            grade = actions.grade_of(entity, frame)
            slopes = profile_mod.grade_slopes(grade)
            self.ctx.echo(tr("Grade line of {name}: {n} vertices, slopes {slopes}",
                             name=frame.name, n=len(grade),
                             slopes=", ".join(f"{v:+.2f} %" for v in slopes)))
            self.ctx.finish()
            return
        self.ctx.echo(tr("The selection has no polyline drawn on a profile."))
        self.ctx.finish()


class SectionsTool(Tool):
    """SECTIONS: the ground across the axis at every station, one small
    plot each; with a grade line selected too, the design over it."""

    wants_selection = True

    def start(self) -> None:
        self.name = "SECTIONS"
        self._tin = _surface(self.ctx)
        self._axis = None
        self._grade = None
        self._step = 20.0
        self._half = 15.0
        self._template = profile_mod.Template()
        self._stage = "step"
        if self._tin is None:
            self.ctx.echo(tr("There is no surface in this space."))
            self.ctx.finish()

    def selection_prompt(self) -> str:
        return tr("Select the axis (and a grade line, if any):")

    def on_selection(self, entities: list) -> None:
        self._axis = _axis_in(entities)
        if self._axis is None:
            self.ctx.echo(tr("The selection has no axis polyline."))
            self.ctx.finish()
            return
        grade_entity = _grade_in(entities)
        if grade_entity is not None:
            anchor = actions.grade_profile_anchor(_document(self.ctx), grade_entity)
            if anchor is not None:
                self._grade = actions.grade_of(grade_entity, actions.ProfileFrame.from_entity(anchor))
        self._stage = "step"
        self.prompt("Station step <{s:g}>:", s=self._step)

    def on_option(self, text: str) -> bool:
        try:
            value = _number(text)
        except ValueError:
            self.ctx.echo(tr("Invalid number: {text}", text=text))
            return True
        if self._stage == "step":
            self._step = max(value, 0.01)
            self._ask_width()
        elif self._stage == "width":
            self._half = max(value, 0.1)
            self._ask_template()
        elif self._stage == "platform":
            self._template.width = max(value, 0.0)
            self._stage = "cut"
            self.prompt("Cut slope H:V <{v:g}>:", v=self._template.cut_hv)
        elif self._stage == "cut":
            self._template.cut_hv = max(value, 0.01)
            self._stage = "fill"
            self.prompt("Fill slope H:V <{v:g}>:", v=self._template.fill_hv)
        elif self._stage == "fill":
            self._template.fill_hv = max(value, 0.01)
            self._ask_point()
        else:
            return False
        return True

    def _ask_width(self) -> None:
        self._stage = "width"
        self.prompt("Width to each side <{w:g}>:", w=self._half)

    def _ask_template(self) -> None:
        if self._grade is None:
            self._ask_point()
            return
        self._stage = "platform"
        self.prompt("Platform width <{w:g}>:", w=self._template.width)

    def _ask_point(self) -> None:
        self._stage = "point"
        self.prompt("Specify the top-left corner of the sections:")

    def on_enter(self) -> None:
        if self._stage == "step":
            self._ask_width()
        elif self._stage == "width":
            self._ask_template()
        elif self._stage == "platform":
            self._stage = "cut"
            self.prompt("Cut slope H:V <{v:g}>:", v=self._template.cut_hv)
        elif self._stage == "cut":
            self._stage = "fill"
            self.prompt("Fill slope H:V <{v:g}>:", v=self._template.fill_hv)
        elif self._stage == "fill":
            self._ask_point()
        else:
            self.ctx.finish()

    def on_point(self, point) -> None:
        if self._stage != "point":
            return
        command = actions.draw_sections(_document(self.ctx), self._tin, self._axis, point,
                                        self._step, self._half, grade=self._grade,
                                        template=self._template if self._grade else None)
        self.ctx.execute(command)
        n = sum(1 for c in command.commands if c.name == "TOPO-SECTION" and c.layer == actions.LAYERS["sections"][0])
        self.ctx.echo(tr("{n} sections drawn every {s:g} m", n=n, s=self._step))
        self.ctx.finish()


class VolumesTool(Tool):
    """VOLUMES: cut and fill per station between the ground and the grade
    line's template, as a table and a CSV."""

    wants_selection = True

    def start(self) -> None:
        self.name = "VOLUMES"
        self._tin = _surface(self.ctx)
        self._axis = None
        self._grade = None
        self._frame = None
        self._template = profile_mod.Template()
        self._method = "prismoidal"
        self._rows = []
        self._stage = "platform"
        if self._tin is None:
            self.ctx.echo(tr("There is no surface in this space."))
            self.ctx.finish()

    def selection_prompt(self) -> str:
        return tr("Select the grade line:")

    def on_selection(self, entities: list) -> None:
        document = _document(self.ctx)
        grade_entity = _grade_in(entities)
        anchor = actions.grade_profile_anchor(document, grade_entity) if grade_entity else None
        if grade_entity is None or anchor is None:
            self.ctx.echo(tr("Select a grade line registered with GRADELINE."))
            self.ctx.finish()
            return
        self._frame = actions.ProfileFrame.from_entity(anchor)
        self._grade = actions.grade_of(grade_entity, self._frame)
        self._axis = next((e for e in document.current_space()
                           if e.dxf.handle == self._frame.axis_handle), None)
        if self._axis is None:
            self.ctx.echo(tr("The profile's axis is no longer in the drawing."))
            self.ctx.finish()
            return
        self._stage = "platform"
        self.prompt("Platform width <{w:g}>:", w=self._template.width)

    def on_option(self, text: str) -> bool:
        if self._stage == "method":
            key = self.option(text)
            if key not in ("P", "E"):
                return False
            self._method = "prismoidal" if key == "P" else "end-area"
            self._compute()
            return True
        try:
            value = _number(text)
        except ValueError:
            self.ctx.echo(tr("Invalid number: {text}", text=text))
            return True
        if self._stage == "platform":
            self._template.width = max(value, 0.0)
            self._stage = "cut"
            self.prompt("Cut slope H:V <{v:g}>:", v=self._template.cut_hv)
        elif self._stage == "cut":
            self._template.cut_hv = max(value, 0.01)
            self._stage = "fill"
            self.prompt("Fill slope H:V <{v:g}>:", v=self._template.fill_hv)
        elif self._stage == "fill":
            self._template.fill_hv = max(value, 0.01)
            self._ask_method()
        else:
            return False
        return True

    def _ask_method(self) -> None:
        self._stage = "method"
        self.prompt("Volume method [Prismoidal/End areas] <Prismoidal>:")

    def on_enter(self) -> None:
        if self._stage == "platform":
            self._stage = "cut"
            self.prompt("Cut slope H:V <{v:g}>:", v=self._template.cut_hv)
        elif self._stage == "cut":
            self._stage = "fill"
            self.prompt("Fill slope H:V <{v:g}>:", v=self._template.fill_hv)
        elif self._stage == "fill":
            self._ask_method()
        elif self._stage == "method":
            self._compute()
        elif self._stage == "point":
            self._write_csv()
        else:
            self.ctx.finish()

    def _compute(self) -> None:
        self._rows = actions.earthworks_rows(self._tin, self._axis, self._grade, self._frame.step,
                                             self._template, method=self._method)
        last = self._rows[-1] if self._rows else None
        if last is not None:
            self.ctx.echo(tr("Cut {c:.1f} m³, fill {f:.1f} m³, mass {m:+.1f} m³ over {n} stations",
                             c=last.cut_total, f=last.fill_total, m=last.mass, n=len(self._rows)))
        self._stage = "point"
        self.prompt("Specify the top-left corner of the table (Enter to skip):")

    def on_point(self, point) -> None:
        if self._stage != "point":
            return
        self.ctx.execute(actions.earthworks_table(_document(self.ctx), self._rows, point,
                                                  name=self._frame.name))
        self._write_csv()

    def _write_csv(self) -> None:
        window = _window(self.ctx)
        if window is not None:
            from views import file_dialogs

            path, _selected = file_dialogs.get_save_file(
                window, tr("Save earthworks CSV"), f"volumenes-{self._frame.name}.csv",
                tr("CSV (*.csv);;All files (*)"))
        else:
            path = self.ctx.ask_text(tr("Earthworks CSV (Enter for none):"), "")
        if path:
            Path(path).write_text(actions.earthworks_csv(self._rows), encoding="utf-8")
            self.ctx.echo(tr("Earthworks written to {path}", path=path))
        self.ctx.finish()


# ======================================================================
# T6: platforms, daylight, volumes between surfaces
# ======================================================================

class PlatformTool(Tool):
    """PLATFORM: a closed polyline becomes a graded platform -- elevation,
    optional slope, cut and fill side slopes, benches -- with its daylight
    line, hachures, design surface and volumes. DAYLIGHT is the same
    without the surface."""

    line_only = False

    def start(self) -> None:
        self.name = "DAYLIGHT" if self.line_only else "PLATFORM"
        self._tin = _surface(self.ctx)
        self._polygon = None
        self._z = None
        self._slope = 0.0
        self._azimuth = 0.0
        self._spec = grading_mod.SlopeSpec()
        self._name = "PLATAFORMA"
        self._stage = "elevation"
        if self._tin is None:
            self.ctx.echo(tr("There is no surface in this space."))
            self.ctx.finish()

    def selection_prompt(self) -> str:
        return tr("Select the closed polyline of the platform:")

    wants_selection = True

    def on_selection(self, entities: list) -> None:
        entity = _closed_polygon(entities)
        if entity is None:
            self.ctx.echo(tr("The selection has no closed polyline."))
            self.ctx.finish()
            return
        self._polygon = geometry.polygon_vertices(entity)
        ground = self._tin.z_at(*self._polygon[0])
        self._z = ground if ground is not None else 0.0
        self._stage = "elevation"
        self.prompt("Platform elevation at the first vertex <{z:.2f}>:", z=self._z)

    def on_option(self, text: str) -> bool:
        if self._stage == "name":
            self._name = text.strip() or self._name
            self._run()
            return True
        try:
            value = _number(text)
        except ValueError:
            self.ctx.echo(tr("Invalid number: {text}", text=text))
            return True
        if self._stage == "elevation":
            self._z = value
            self._ask("slope", "Slope of the platform in % (0 = flat) <{v:g}>:", v=self._slope)
        elif self._stage == "slope":
            self._slope = value
            if value != 0.0:
                self._ask("azimuth", "Azimuth the platform falls along <{v:g}>:", v=self._azimuth)
            else:
                self._ask("cut", "Cut slope H:V <{v:g}>:", v=self._spec.cut_hv)
        elif self._stage == "azimuth":
            self._azimuth = value
            self._ask("cut", "Cut slope H:V <{v:g}>:", v=self._spec.cut_hv)
        elif self._stage == "cut":
            self._spec.cut_hv = max(value, 0.01)
            self._ask("fill", "Fill slope H:V <{v:g}>:", v=self._spec.fill_hv)
        elif self._stage == "fill":
            self._spec.fill_hv = max(value, 0.01)
            self._ask("bench_h", "Bench every (height, 0 = none) <{v:g}>:", v=self._spec.bench_height)
        elif self._stage == "bench_h":
            self._spec.bench_height = max(value, 0.0)
            if self._spec.bench_height > 0:
                self._ask("bench_w", "Bench width <{v:g}>:", v=self._spec.bench_width or 2.0)
            else:
                self._after_slopes()
        elif self._stage == "bench_w":
            self._spec.bench_width = max(value, 0.0)
            self._after_slopes()
        else:
            return False
        return True

    def _ask(self, stage: str, prompt: str, **kw) -> None:
        self._stage = stage
        self.prompt(prompt, **kw)

    def _after_slopes(self) -> None:
        if self.line_only:
            self._run()
        else:
            self._ask("name", "Surface name <{name}>:", name=self._name)

    def on_enter(self) -> None:
        defaults = {"elevation": lambda: self.on_option(f"{self._z}"),
                    "slope": lambda: self.on_option(f"{self._slope}"),
                    "azimuth": lambda: self.on_option(f"{self._azimuth}"),
                    "cut": lambda: self.on_option(f"{self._spec.cut_hv}"),
                    "fill": lambda: self.on_option(f"{self._spec.fill_hv}"),
                    "bench_h": lambda: self.on_option(f"{self._spec.bench_height}"),
                    "bench_w": lambda: self.on_option(f"{self._spec.bench_width or 2.0}"),
                    "name": lambda: self._run()}
        action = defaults.get(self._stage)
        if action is None:
            self.ctx.finish()
        else:
            action()

    def _run(self) -> None:
        z_of = grading_mod.platform_plane(self._polygon[0], self._z, self._slope, self._azimuth)
        result = actions.grade_platform(self._tin, self._polygon, z_of, self._spec,
                                        name=self._name, with_surface=not self.line_only)
        found = sum(1 for d in result.daylight if d is not None)
        if found < 3:
            self.ctx.echo(tr("The slopes never meet the ground: is the platform on the surface?"))
            self.ctx.finish()
            return
        self.ctx.execute(actions.draw_platform(_document(self.ctx), result))
        if not result.closed:
            self.ctx.echo(tr("The daylight line is open: {n} of {m} slope lines left the surface.",
                             n=len(result.daylight) - found, m=len(result.daylight)))
        else:
            self.ctx.echo(tr("Daylight line closed, {m} slope lines.", m=len(result.daylight)))
        if result.design is not None:
            self.ctx.echo(tr("{name}: cut {c:.1f} m³, fill {f:.1f} m³, net {n:+.1f} m³",
                             name=self._name, c=result.cut, f=result.fill, n=result.fill - result.cut))
        self.ctx.finish()


class DaylightTool(PlatformTool):
    line_only = True


class VoltinTool(Tool):
    """VOLTIN: cut and fill between two surfaces of the drawing, exact."""

    def start(self) -> None:
        self.name = "VOLTIN"
        names = actions.surface_names(_document(self.ctx))
        if len(names) < 2:
            self.ctx.echo(tr("Two surfaces are needed; this space has {n}.", n=len(names)))
            self.ctx.finish()
            return
        self._names = names
        self._base = "TERRENO" if "TERRENO" in names else names[0]
        self._design = next((n for n in names if n != self._base), names[-1])
        self._cut = self._fill = 0.0
        self._stage = "base"
        self.prompt("Base surface <{name}> ({options}):", name=self._base, options=", ".join(names))

    def on_option(self, text: str) -> bool:
        value = text.strip()
        if self._stage == "base":
            if value not in self._names:
                self.ctx.echo(tr("No surface called {name}.", name=value))
                return True
            self._base = value
            self._ask_design()
        elif self._stage == "design":
            if value not in self._names:
                self.ctx.echo(tr("No surface called {name}.", name=value))
                return True
            self._design = value
            self._compute()
        else:
            return False
        return True

    def _ask_design(self) -> None:
        self._stage = "design"
        self.prompt("Compared surface <{name}>:", name=self._design)

    def on_enter(self) -> None:
        if self._stage == "base":
            self._ask_design()
        elif self._stage == "design":
            self._compute()
        else:
            self.ctx.finish()

    def _compute(self) -> None:
        result = actions.volumes_between(_document(self.ctx), self._base, self._design)
        if result is None:
            self.ctx.echo(tr("No surface called {name}.", name=self._design))
            self.ctx.finish()
            return
        self._cut, self._fill = result
        self.ctx.echo(tr("{design} vs {base}: cut {c:.1f} m³, fill {f:.1f} m³, net {n:+.1f} m³",
                         design=self._design, base=self._base, c=self._cut, f=self._fill,
                         n=self._fill - self._cut))
        self._stage = "label"
        self.prompt("Specify label point (Enter to finish):")

    def on_point(self, point) -> None:
        if self._stage != "label":
            return
        self.ctx.execute(actions.volume_label(_document(self.ctx), point, self._base, self._design,
                                              self._cut, self._fill))
        self.ctx.finish()


TOOL_CLASSES = {
    "PLATFORM": PlatformTool,
    "DAYLIGHT": DaylightTool,
    "VOLTIN": VoltinTool,
    "PROFILE": ProfileTool,
    "GRADELINE": GradeLineTool,
    "SECTIONS": SectionsTool,
    "VOLUMES": VolumesTool,
    "CONTOUR": ContourTool,
    "CONTOURLABEL": ContourLabelTool,
    "SLOPEZONES": SlopeZonesTool,
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
