# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Terrain -- the ground under the drawing (docs/plan-complementos.md, §4).

G1, georeferencing: GEOREF declares the drawing's UTM zone, hemisphere and
datum (WGS84, or PSAD56 with the shift Peru's older plans need), kept in
the drawing itself as plain DXF; LATLON reads the geographic coordinates
of picked points and places a point from typed ones. The UTM maths is
its own (ported from IngeTrazo, checked against PROJ), so nothing new is
installed. G2, the ground without a survey: DEMPOINTS lays a grid of
points at the elevation of a global 30 m DEM (AWS Terrain Tiles, no key,
cached on disk) inside a polygon, ready for TIN and CONTOUR; DEMPROFILE
draws an axis' profile straight from the DEM. Both say, every time, that
the numbers are for a preliminary design. G3: SATIMAGE puts the
satellite image of a polygon under the plan -- a licensed tile source
(Esri World Imagery, Sentinel-2 cloudless, OpenStreetMap, or the user's
own XYZ), resampled into the drawing's UTM grid, saved beside the drawing
and referenced as a plain IMAGE with its attribution. To come: G4 KML/KMZ
to and from Google Earth.
"""
from __future__ import annotations

from pathlib import Path

from core.i18n import tr
from core.plugins import SEPARATOR, MenuItem, PluginSpec

from .tools import TOOL_CLASSES


def _options_page(dialog, window):
    from .options import TerrainOptionsPage

    return TerrainOptionsPage(dialog, window)


def _on_document_open(ctx, document) -> None:
    """Say what the opened drawing declares, so nobody reads a PSAD56
    plan as WGS84 without noticing."""
    from . import actions

    georef = actions.georef_of(document)
    if georef is not None:
        ctx.echo(tr("Drawing georeferenced: {what}", what=actions.describe(georef)))


PLUGIN = PluginSpec(
    id="terreno",
    name="Terrain",
    version="0.6.0",
    description="Georeference the drawing (UTM zone, WGS84 or PSAD56), read or type geographic "
                "coordinates, take ground elevations from a global DEM, and put the satellite "
                "image under the plan.",
    tools=dict(TOOL_CLASSES),
    menu=(
        MenuItem("Georeference drawing...", "GEOREF"),
        MenuItem("Geographic coordinates...", "LATLON"),
        SEPARATOR,
        MenuItem("Elevation points from DEM...", "DEMPOINTS"),
        MenuItem("Profile from DEM...", "DEMPROFILE"),
        SEPARATOR,
        MenuItem("Satellite image...", "SATIMAGE"),
    ),
    options_page=_options_page,
    i18n_dir=Path(__file__).parent / "i18n",
    on_document_open=_on_document_open,
)
