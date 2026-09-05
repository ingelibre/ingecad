# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Terrain plugin, headless: the drawing's georeference and the
conversions the tools need. Every mutation is a Command; what lands in
the drawing is plain DXF (a POINT and a TEXT on their layer, XDATA under
``INGECAD``), and the declaration itself lives in ``core.georef``."""
from __future__ import annotations

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
