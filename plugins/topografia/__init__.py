# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Topography -- the civil engineer's plugin (docs/plan-complementos.md).

T1, points: import a station's CSV, export, draw by bearing and distance,
renumber, find. T2, polygons: bearings and distances annotated, the
construction chart, sums of areas, subdivision by area, the UTM grid.
T3, the surface: a Delaunay TIN of the points as 3DFACEs, edited and checked.
Everything it draws is plain DXF (POINT, TEXT, LINE, layers), readable by
any CAD; the point numbers and descriptions ride in XDATA.
"""
from __future__ import annotations

from pathlib import Path

from core.plugins import SEPARATOR, MenuItem, PluginSpec, Submenu, ToolbarItem

from .tools import TOOL_CLASSES

PLUGIN = PluginSpec(
    id="topografia",
    name="Topography",
    version="0.5.0a1",
    description="Survey points, contours, profiles and volumes for the civil engineer.",
    tools=dict(TOOL_CLASSES),
    aliases={"PIM": "PIMPORT", "PEX": "PEXPORT", "PRN": "PRENUM", "PFI": "PFIND"},
    menu=(
        Submenu("Points", (
            MenuItem("Import points (CSV)...", "PIMPORT"),
            MenuItem("Export points...", "PEXPORT"),
            SEPARATOR,
            MenuItem("Point by bearing and distance", "PBY"),
            MenuItem("Renumber points", "PRENUM"),
            MenuItem("Find point...", "PFIND"),
        )),
        Submenu("Polygons", (
            MenuItem("Annotate bearings and distances", "ANNOT"),
            MenuItem("Construction chart...", "CTABLE"),
            MenuItem("Sum of areas", "AREASUM"),
            MenuItem("Subdivide polygon...", "SUBDIV"),
        )),
        Submenu("Surface", (
            MenuItem("Triangulate (TIN)...", "TIN"),
            MenuItem("Edit surface...", "TINEDIT"),
            MenuItem("Check surface", "TINCHECK"),
        )),
        SEPARATOR,
        MenuItem("UTM grid...", "UTMGRID"),
    ),
    toolbar=(
        ToolbarItem("Import points (CSV)...", "PIMPORT"),
        ToolbarItem("Point by bearing and distance", "PBY"),
        ToolbarItem("Annotate bearings and distances", "ANNOT"),
        ToolbarItem("Construction chart...", "CTABLE"),
        ToolbarItem("Triangulate (TIN)...", "TIN"),
    ),
    i18n_dir=Path(__file__).parent / "i18n",
)
