# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Terrain -- the ground under the drawing (docs/plan-complementos.md, §4).

G1, georeferencing: GEOREF declares the drawing's UTM zone, hemisphere and
datum (WGS84, or PSAD56 with the shift Peru's older plans need), kept in
the drawing itself as plain DXF; LATLON reads the geographic coordinates
of picked points and places a point from typed ones. The UTM maths is
its own (ported from IngeTrazo, checked against PROJ), so nothing new is
installed. To come: G2 elevations from a global DEM, G3 satellite imagery,
G4 KML/KMZ to and from Google Earth.
"""
from __future__ import annotations

from pathlib import Path

from core.i18n import tr
from core.plugins import MenuItem, PluginSpec

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
    description="Georeference the drawing (UTM zone, WGS84 or PSAD56) and read or type geographic coordinates.",
    tools=dict(TOOL_CLASSES),
    menu=(
        MenuItem("Georeference drawing...", "GEOREF"),
        MenuItem("Geographic coordinates...", "LATLON"),
    ),
    options_page=_options_page,
    i18n_dir=Path(__file__).parent / "i18n",
    on_document_open=_on_document_open,
)
