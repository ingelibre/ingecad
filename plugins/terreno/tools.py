# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Terrain plugin's interactive side: GEOREF and LATLON, prompting
the way AutoCAD prompts. Both run headless (the suite drives them
without a window): every answer arrives as a typed token or a point."""
from __future__ import annotations

from core.georef import Georef
from core.i18n import tr
from tools.base import Tool

from . import actions, datum, prefs


def _document(ctx):
    document = getattr(ctx.services, "document", None)
    if document is None:
        document = getattr(getattr(ctx.services, "window", None), "document", None)
    return document


def _in_model(document) -> bool:
    return document.space_name == "Model"


class GeorefTool(Tool):
    """GEOREF: declare the drawing's UTM zone, hemisphere and datum (or
    remove the declaration). The zone can be given, or worked out from
    a longitude; PSAD56 asks for its shift to WGS84."""

    def start(self) -> None:
        self.name = "GEOREF"
        document = _document(self.ctx)
        current = actions.georef_of(document)
        self._current = current
        self._zone = current.zone if current else prefs.default_zone()
        self._northern = current.northern if current else prefs.default_northern()
        self._datum = current.datum if current else "WGS84"
        self._shift = (current.shift if current and current.datum != "WGS84"
                       else prefs.default_shift())
        if current is not None:
            self.ctx.echo(tr("Drawing georeferenced: {what}", what=actions.describe(current)))
        self._ask_zone()

    # -- the questions, one after the other ---------------------------------------
    def _ask_zone(self) -> None:
        self._stage = "zone"
        self.prompt("UTM zone number or [Longitude/Remove] <{zone}>:", zone=self._zone)

    def _ask_hemisphere(self) -> None:
        self._stage = "hemisphere"
        self.prompt("Hemisphere [North/South] <{default}>:",
                    default=tr("North") if self._northern else tr("South"))

    def _ask_datum(self) -> None:
        self._stage = "datum"
        self.prompt("Datum [WGS84/PSAD56] <{default}>:", default=self._datum)

    def _ask_shift(self) -> None:
        self._stage = "shift"
        dx, dy, dz = self._shift
        self.prompt("Shift to WGS84 dX,dY,dZ in metres <{dx:g},{dy:g},{dz:g}>:", dx=dx, dy=dy, dz=dz)

    def on_option(self, text: str) -> bool:
        stage = self._stage
        if stage == "zone":
            key = self.option(text)
            if key == "L":
                self._stage = "longitude"
                self.prompt("Longitude in degrees (west negative):")
                return True
            if key == "R":
                self._remove()
                return True
            try:
                zone = int(text.strip())
            except ValueError:
                zone = 0
            if not 1 <= zone <= 60:
                self.ctx.echo(tr("The UTM zone is a number from 1 to 60."))
                self._ask_zone()
                return True
            self._zone = zone
            self._ask_hemisphere()
            return True
        if stage == "longitude":
            try:
                lon = float(text.strip().replace(",", "."))
            except ValueError:
                try:
                    _lat, lon = datum.parse_latlon("0 N " + text)
                except ValueError:
                    lon = None
            if lon is None or not -180.0 <= lon <= 180.0:
                self.ctx.echo(tr("Longitude must be between -180 and 180."))
                self.prompt("Longitude in degrees (west negative):")
                return True
            self._zone = datum.zone_for_lon(lon)
            self.ctx.echo(tr("Longitude {lon:g}° lies in UTM zone {zone}.", lon=lon, zone=self._zone))
            self._ask_hemisphere()
            return True
        if stage == "hemisphere":
            key = self.option(text)
            if key not in ("N", "S"):
                self._ask_hemisphere()
                return True
            self._northern = key == "N"
            self._ask_datum()
            return True
        if stage == "datum":
            # keys by hand: the capital-letter rule would read WGS84 as
            # the key "WGS84", and nobody types that when W will do
            token = text.strip().upper().lstrip("_")
            if token.startswith("W"):
                self._datum = "WGS84"
                self._apply()
            elif token.startswith("P"):
                self._datum = "PSAD56"
                self._ask_shift()
            else:
                self._ask_datum()
            return True
        if stage == "shift":
            parts = text.replace(";", ",").split(",")
            try:
                values = tuple(float(p) for p in parts)
            except ValueError:
                values = ()
            if len(values) != 3:
                self.ctx.echo(tr("Three numbers, dX,dY,dZ in metres."))
                self._ask_shift()
                return True
            self._shift = values
            self._apply()
            return True
        return False

    def on_enter(self) -> None:
        """Enter takes the default of the question on screen."""
        stage = self._stage
        if stage == "zone":
            self._ask_hemisphere()
        elif stage == "longitude":
            self._ask_zone()
        elif stage == "hemisphere":
            self._ask_datum()
        elif stage == "datum":
            if self._datum == "WGS84":
                self._apply()
            else:
                self._ask_shift()
        elif stage == "shift":
            self._apply()
        else:
            self.ctx.finish()

    def _remove(self) -> None:
        document = _document(self.ctx)
        if self._current is None:
            self.ctx.echo(tr("The drawing is not georeferenced."))
        else:
            self.ctx.execute(actions.set_georef(document, None))
            self.ctx.echo(tr("Georeference removed."))
        self.ctx.finish()

    def _apply(self) -> None:
        document = _document(self.ctx)
        shift = self._shift if self._datum != "WGS84" else (0.0, 0.0, 0.0)
        georef = Georef(self._zone, self._northern, self._datum, shift)
        self.ctx.execute(actions.set_georef(document, georef))
        self.ctx.echo(tr("Drawing georeferenced: {what}", what=actions.describe(georef)))
        self.ctx.finish()


class LatLonTool(Tool):
    """LATLON: the WGS84 latitude and longitude of picked points, or a
    point placed from typed geographic coordinates (decimal or DMS)."""

    def start(self) -> None:
        self.name = "LATLON"
        document = _document(self.ctx)
        self._georef = actions.georef_of(document)
        self._mode = "pick"
        self._pending = None
        if self._georef is None:
            self.ctx.echo(tr("The drawing is not georeferenced: run GEOREF first."))
            self.ctx.finish()
            return
        if not _in_model(document):
            self.ctx.echo(tr("Geographic coordinates are read in model space."))
            self.ctx.finish()
            return
        self.ctx.echo(tr("Drawing georeferenced: {what}", what=actions.describe(self._georef)))
        self._ask_point()

    def _ask_point(self) -> None:
        self._mode = "pick"
        self.prompt("Pick a point or [Type]:")

    def wants_raw_text(self) -> bool:
        return self._mode == "type"          # DMS carries spaces

    def on_point(self, point) -> None:
        if self._mode != "pick":
            return
        lat, lon = datum.drawing_to_latlon(self._georef, point[0], point[1])
        self.ctx.echo(tr("Lat {lat}  Lon {lon}  ({dms})  at E={e:.3f} N={n:.3f}",
                         lat=f"{lat:.6f}", lon=f"{lon:.6f}", dms=datum.format_dms(lat, lon),
                         e=point[0], n=point[1]))
        self.last_point = (point[0], point[1])
        self._ask_point()

    def on_option(self, text: str) -> bool:
        if self._mode == "pick":
            if self.option(text) == "T":
                self._mode = "type"
                self.prompt("Latitude, longitude (decimal degrees or DMS):")
                return True
            return False
        if self._mode == "type":
            try:
                lat, lon = datum.parse_latlon(text)
            except ValueError:
                self.ctx.echo(tr("Cannot read a latitude and longitude in {text}.", text=text.strip()))
                self.prompt("Latitude, longitude (decimal degrees or DMS):")
                return True
            east, north = datum.latlon_to_drawing(self._georef, lat, lon)
            self._pending = (east, north, lat, lon)
            self.ctx.echo(tr("E={e:.3f} N={n:.3f} for {dms} ({zone})", e=east, n=north,
                             dms=datum.format_dms(lat, lon), zone=self._georef.label()))
            self._mode = "mark"
            self.prompt("Mark it with a point? [Yes/No] <Yes>:")
            return True
        if self._mode == "mark":
            key = self.option(text)
            if key == "N":
                self.ctx.finish()
            elif key == "Y":
                self._mark()
            else:
                self.prompt("Mark it with a point? [Yes/No] <Yes>:")
            return True
        return False

    def on_enter(self) -> None:
        if self._mode == "mark":
            self._mark()
        else:
            self.ctx.finish()

    def _mark(self) -> None:
        east, north, lat, lon = self._pending
        document = _document(self.ctx)
        self.ctx.execute(actions.mark_point(document, (east, north), lat, lon))
        self.ctx.echo(tr("Point marked on {layer}.", layer=actions.LAYERS["geo"][0]))
        self.last_point = (east, north)
        self.ctx.finish()


TOOL_CLASSES = {"GEOREF": GeorefTool, "LATLON": LatLonTool}


# ======================================================================
# G2: elevations from the DEM
# ======================================================================

from core.hatch_boundary import boundary_polygon   # noqa: E402
from . import dem as dem_mod                       # noqa: E402


def _dem_of(ctx):
    """The DEM to sample: an injected one (the suite), else Options'."""
    injected = getattr(ctx.services, "dem", None)
    return injected if injected is not None else dem_mod.default_dem()


def _flush_ui() -> None:
    """Let a 'downloading...' line reach the screen before a blocking fetch."""
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.processEvents()
    except Exception:
        pass


def _number(text: str) -> float:
    return float(text.strip().replace(",", "."))


def _ready(tool) -> bool:
    """The checks both DEM tools open with; False (and finished) if not."""
    document = _document(tool.ctx)
    georef = actions.georef_of(document)
    if georef is None:
        tool.ctx.echo(tr("The drawing is not georeferenced: run GEOREF first."))
        tool.ctx.finish()
        return False
    if not _in_model(document):
        tool.ctx.echo(tr("DEM elevations are taken in model space."))
        tool.ctx.finish()
        return False
    tool._georef = georef
    return True


class DemPointsTool(Tool):
    """DEMPOINTS: a grid of points with ground elevation from the DEM
    inside a polygon (or a rectangle by two corners) -- what TIN and
    CONTOUR take as they are, for a site with no survey yet."""

    wants_selection = True

    def start(self) -> None:
        self.name = "DEMPOINTS"
        self._polygon = None
        self._corner = None
        self._spacing = 30.0
        self._stage = "select"
        _ready(self)

    def selection_prompt(self) -> str:
        return tr("Select the boundary polygon (Enter for two corners):")

    def on_selection(self, entities: list) -> None:
        for entity in entities:
            polygon = boundary_polygon(entity)
            if polygon is not None and len(polygon) >= 3:
                self._polygon = polygon
                break
        if self._polygon is not None:
            self._ask_spacing()
            return
        self._stage = "corner1"
        self.prompt("Specify first corner:")

    def _ask_spacing(self) -> None:
        self._stage = "spacing"
        self.prompt("Grid spacing in metres <{s:g}>:", s=self._spacing)

    def on_point(self, point) -> None:
        if self._stage == "corner1":
            self._corner = (point[0], point[1])
            self.last_point = self._corner
            self._stage = "corner2"
            self.prompt("Specify opposite corner:")
        elif self._stage == "corner2":
            (x0, y0), (x1, y1) = self._corner, (point[0], point[1])
            if abs(x1 - x0) < 1e-9 or abs(y1 - y0) < 1e-9:
                self.ctx.echo(tr("The corners must make a rectangle."))
                self.prompt("Specify opposite corner:")
                return
            self._polygon = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
            self._ask_spacing()

    def on_option(self, text: str) -> bool:
        if self._stage != "spacing":
            return False
        try:
            value = _number(text)
            if value <= 0:
                raise ValueError(text)
        except ValueError:
            self.ctx.echo(tr("Invalid number: {text}", text=text))
            return True
        self._spacing = value
        self._run()
        return True

    def on_enter(self) -> None:
        if self._stage == "spacing":
            self._run()
        else:
            self.ctx.finish()

    def _run(self) -> None:
        document = _document(self.ctx)
        points = actions.grid_points(self._polygon, self._spacing)
        if not points:
            self.ctx.echo(tr("No grid node falls inside the polygon: use a smaller spacing."))
            self.ctx.finish()
            return
        dem = _dem_of(self.ctx)
        self.ctx.echo(tr("Fetching elevations for {n} points from {source}...",
                         n=len(points), source=dem.source.name))
        _flush_ui()
        try:
            samples = actions.dem_elevations(document, dem, points)
        except dem_mod.DemError as exc:
            self.ctx.echo(tr("Could not get elevations: {error}", error=exc))
            self.ctx.finish()
            return
        self.ctx.execute(actions.dem_points(document, samples, dem.source.id))
        zs = [z for _x, _y, z in samples]
        self.ctx.echo(tr("{n} elevation points on {layer}, from {z0:.1f} to {z1:.1f} m.",
                         n=len(samples), layer=actions.LAYERS["dem"][0], z0=min(zs), z1=max(zs)))
        lat, _lon = actions.datum.drawing_to_latlon(self._georef, *points[0])
        self.ctx.echo(actions.honesty(dem, lat))
        self.ctx.finish()


class DemProfileTool(Tool):
    """DEMPROFILE: the longitudinal profile of an axis over the DEM,
    drawn by the Topography plugin's profile machinery -- no survey and
    no surface in the drawing needed."""

    wants_selection = True

    def start(self) -> None:
        self.name = "DEMPROFILE"
        self._axis = None
        self._step = 20.0
        self._hscale = 1.0
        self._vscale = 10.0
        self._stage = "select"
        if not _ready(self):
            return
        self._topo = actions.topography()
        if self._topo is None:
            self.ctx.echo(tr("DEMPROFILE draws with the Topography plugin: turn it on in Tools > Plugins."))
            self.ctx.finish()

    def selection_prompt(self) -> str:
        return tr("Select the axis:")

    def on_selection(self, entities: list) -> None:
        for entity in entities:
            if entity.dxftype() in ("LINE", "LWPOLYLINE", "POLYLINE"):
                self._axis = entity
                break
        if self._axis is None:
            self.ctx.echo(tr("The selection has no axis."))
            self.ctx.finish()
            return
        self._stage = "step"
        self.prompt("Station step <{s:g}>:", s=self._step)

    def on_option(self, text: str) -> bool:
        if self._stage not in ("step", "hscale", "vscale"):
            return False
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
        else:
            self._vscale = 1000.0 / value
            self._ask_point()
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
        document = _document(self.ctx)
        dem = _dem_of(self.ctx)
        axis = self._topo.axis_points(self._axis)
        self.ctx.echo(tr("Fetching elevations along the axis from {source}...", source=dem.source.name))
        _flush_ui()
        try:
            dem.prefetch(*actions.bbox_latlon(self._georef, [(p[0], p[1]) for p in axis]))
            surface = actions.DemSurface(dem, self._georef)
            command = self._topo.draw_profile(document, surface, self._axis, point,
                                              self._step, self._hscale, self._vscale, 1.0)
        except dem_mod.DemError as exc:
            self.ctx.echo(tr("Could not get elevations: {error}", error=exc))
            self.ctx.finish()
            return
        except ValueError as exc:
            self.ctx.echo(tr("Cannot draw the profile: {error}", error=exc))
            self.ctx.finish()
            return
        self.ctx.execute(command)
        lat, _lon = actions.datum.drawing_to_latlon(self._georef, axis[0][0], axis[0][1])
        self.ctx.echo(actions.honesty(dem, lat))
        self.ctx.finish()


TOOL_CLASSES.update({"DEMPOINTS": DemPointsTool, "DEMPROFILE": DemProfileTool})
