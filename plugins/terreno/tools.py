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
