# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Terrain plugin, headless: the drawing's georeference and the
conversions the tools need. Every mutation is a Command; what lands in
the drawing is plain DXF (a POINT and a TEXT on their layer, XDATA under
``INGECAD``), and the declaration itself lives in ``core.georef``."""
from __future__ import annotations

import math

from core.actions import AddEntityCommand
from core.commands import Command, CompositeCommand
from core.georef import Georef, SetGeorefCommand, read_georef
from core.i18n import tr
from core.layers import NewLayerCommand
from core.xdata import APPID, ensure_appid

from . import datum

GEO_TAG = "GEO-POINT"
LAYERS = {"geo": ("TERRENO-GEO", 6)}


def georef_of(document) -> Georef | None:
    return read_georef(document.doc)


def set_georef(document, georef: Georef | None) -> SetGeorefCommand:
    """Declare ``georef`` (None removes it), undoably."""
    return SetGeorefCommand(georef)


def describe(georef: Georef) -> str:
    """``WGS84, UTM zone 19 S`` in the interface language -- and, for a
    datum that has one, its shift."""
    if georef.datum == "WGS84":
        return tr("{datum}, UTM zone {zone}", datum=georef.datum, zone=georef.zone_label())
    dx, dy, dz = georef.shift
    return tr("{datum}, UTM zone {zone} (shift to WGS84 {dx:g}, {dy:g}, {dz:g} m)",
              datum=georef.datum, zone=georef.zone_label(), dx=dx, dy=dy, dz=dz)


def latlon_of(document, point) -> tuple[float, float]:
    """WGS84 latitude and longitude of a drawing point."""
    georef = georef_of(document)
    if georef is None:
        raise ValueError("the drawing is not georeferenced")
    return datum.drawing_to_latlon(georef, float(point[0]), float(point[1]))


def drawing_point(document, lat: float, lon: float) -> tuple[float, float]:
    """The drawing point (its own datum and zone) of a WGS84 lat/lon."""
    georef = georef_of(document)
    if georef is None:
        raise ValueError("the drawing is not georeferenced")
    return datum.latlon_to_drawing(georef, lat, lon)


def layer_commands(document, kinds=("geo",)) -> list[Command]:
    out = []
    for kind in kinds:
        name, color = LAYERS[kind]
        if name not in document.doc.layers:
            out.append(NewLayerCommand(name, color=color))
    return out


def mark_point(document, point, lat: float, lon: float, text_height: float = 1.0) -> CompositeCommand:
    """A POINT at ``point`` (something to snap to) and a TEXT with the
    geographic coordinates beside it, on TERRENO-GEO; the latitude and
    longitude ride in the point's XDATA."""
    label = datum.format_dms(lat, lon)

    def make_point(msp):
        ensure_appid(msp.doc)
        entity = msp.add_point((float(point[0]), float(point[1]), 0.0))
        entity.set_xdata(APPID, [(1000, GEO_TAG), (1040, float(lat)), (1040, float(lon))])
        return entity

    def make_text(msp):
        entity = msp.add_text(label, height=text_height)
        entity.set_placement((point[0] + text_height * 0.5, point[1] + text_height * 0.5))
        return entity

    layer = LAYERS["geo"][0]
    return CompositeCommand("geographic point", layer_commands(document) + [
        AddEntityCommand("GEO-POINT", make_point, layer=layer),
        AddEntityCommand("GEO-LABEL", make_text, layer=layer)])


def geo_points(document) -> list:
    """The POINTs LATLON marked, with ``(entity, lat, lon)``."""
    out = []
    for entity in document.doc.modelspace().query("POINT"):
        if not entity.has_xdata(APPID):
            continue
        values = [value for _code, value in entity.get_xdata(APPID)]
        if values and values[0] == GEO_TAG and len(values) >= 3:
            out.append((entity, float(values[1]), float(values[2])))
    return out


# -- G2: elevations from the DEM ---------------------------------------------------------------

DEM_TAG = "DEM-POINT"
LAYERS["dem"] = ("TERRENO-DEM", 8)


def topography():
    """The Topography plugin's actions -- the loaded plugin when it is on
    (one instance, the one the window uses), the package otherwise (the
    suite); None when neither imports."""
    import importlib
    import sys

    module = sys.modules.get("ingecad_plugin_topografia.actions")
    if module is not None:
        return module
    try:
        return importlib.import_module("plugins.topografia.actions")
    except ImportError:
        return None


def grid_points(polygon, spacing: float) -> list[tuple[float, float]]:
    """The nodes of a grid of ``spacing`` (aligned to multiples of it, so
    two runs on overlapping lots share their points) that fall inside
    the polygon."""
    from core.hatch_boundary import point_in_polygon

    if spacing <= 0 or len(polygon) < 3:
        return []
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    x0 = math.floor(min(xs) / spacing) * spacing
    y0 = math.floor(min(ys) / spacing) * spacing
    out = []
    y = y0
    while y <= max(ys) + 1e-9:
        x = x0
        while x <= max(xs) + 1e-9:
            if point_in_polygon(polygon, (x, y)):
                out.append((x, y))
            x += spacing
        y += spacing
    return out


def bbox_latlon(georef: Georef, points) -> tuple[float, float, float, float]:
    """``(lat_s, lon_w, lat_n, lon_e)`` of drawing points."""
    lats, lons = [], []
    for x, y in points:
        lat, lon = datum.drawing_to_latlon(georef, x, y)
        lats.append(lat)
        lons.append(lon)
    return min(lats), min(lons), max(lats), max(lons)


def dem_elevations(document, dem, points) -> list[tuple[float, float, float]]:
    """Each drawing point with its DEM elevation; fetches what it needs."""
    georef = georef_of(document)
    if georef is None:
        raise ValueError("the drawing is not georeferenced")
    if not points:
        return []
    dem.prefetch(*bbox_latlon(georef, points))
    out = []
    for x, y in points:
        lat, lon = datum.drawing_to_latlon(georef, x, y)
        out.append((x, y, dem.elevation(lat, lon)))
    return out


def dem_points(document, samples, source_id: str) -> CompositeCommand:
    """One POINT per sample, at its elevation, on TERRENO-DEM, tagged with
    the source: what TIN takes as it is."""
    def factory(x, y, z):
        def make(msp):
            ensure_appid(msp.doc)
            entity = msp.add_point((x, y, z))
            entity.set_xdata(APPID, [(1000, DEM_TAG), (1000, source_id)])
            return entity
        return make

    layer = LAYERS["dem"][0]
    commands = layer_commands(document, ("dem",))
    commands += [AddEntityCommand("DEM-POINT", factory(x, y, z), layer=layer) for x, y, z in samples]
    return CompositeCommand("DEM points", commands)


def honesty(dem, lat: float) -> str:
    """What every DEM command says at the end: where the numbers come
    from and how coarse they are."""
    return tr("Elevations from {source}: about {pixel:.0f} m per pixel over {data:.0f} m data. "
              "For preliminary design only, never for a survey.",
              source=dem.source.name, pixel=dem.metres_per_pixel(lat),
              data=dem.source.data_resolution_m)


class DemSurface:
    """What the profile needs from a surface -- ``z_at`` -- straight from
    the DEM through the drawing's georeference, so DEMPROFILE draws the
    ground without a survey and without a TIN in the drawing."""

    def __init__(self, dem, georef: Georef, name: str = "DEM") -> None:
        self.dem = dem
        self.georef = georef
        self.name = name

    def z_at(self, x: float, y: float) -> float:
        lat, lon = datum.drawing_to_latlon(self.georef, x, y)
        return self.dem.elevation(lat, lon)
