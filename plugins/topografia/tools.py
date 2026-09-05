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

from . import actions
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


TOOL_CLASSES = {
    "PIMPORT": ImportPointsTool,
    "PEXPORT": ExportPointsTool,
    "PBY": PointByBearingTool,
    "PRENUM": RenumberPointsTool,
    "PFIND": FindPointTool,
}
