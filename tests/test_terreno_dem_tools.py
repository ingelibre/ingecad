# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Terrain plugin, G2 in the drawing: DEMPOINTS lays the grid at the
DEM's elevations (ready for TIN), DEMPROFILE draws the axis' profile
through the Topography plugin, both say how coarse the data is -- driven
headless on synthetic tiles, plus the plugin's new commands in the window."""
from __future__ import annotations

import pytest

from core.commands import History
from core.document import Document
from core.georef import Georef, SetGeorefCommand
from plugins.terreno import actions, datum, dem
from test_terreno_dem import FakeFetch, analytic
from tools.base import ToolContext

# a 210 x 210 m box around the Arequipa lot: grid nodes every 10 m from
# 229100 to 229300 and 8181300 to 8181500 -> 21 x 21 = 441 points
BOX = [(229095.0, 8181295.0), (229305.0, 8181295.0), (229305.0, 8181505.0), (229095.0, 8181505.0)]


class _Services:
    def __init__(self, document, fake):
        self.document = document
        self.dem = fake


class _Harness:
    def __init__(self, tmp_path, georef=Georef(19), fetch=None):
        self.document = Document.new()
        self.history = History(self.document)
        if georef is not None:
            self.history.execute(SetGeorefCommand(georef))
        self.fetch = fetch or FakeFetch()
        self.dem = dem.Dem(dem.TileStore(dem.AWS_TERRAIN, tmp_path / "cache", self.fetch), 13)
        self.finished = False
        self.echoed: list[str] = []
        self.prompts: list[str] = []
        self.ctx = ToolContext(
            execute=self.history.execute, prompt=self.prompts.append,
            echo=self.echoed.append, finish=lambda: setattr(self, "finished", True),
            undo_last=self.history.undo, services=_Services(self.document, self.dem))

    @property
    def msp(self):
        return self.document.doc.modelspace()


def test_grid_points_align_to_the_spacing_and_respect_a_concave_polygon():
    square = [(0.0, 0.0), (25.0, 0.0), (25.0, 25.0), (0.0, 25.0)]
    pts = actions.grid_points(square, 10.0)
    assert len(pts) == 9 and (10.0, 20.0) in pts
    # an L: the notch (x > 10, y > 10) holds no node
    ell = [(0.0, 0.0), (25.0, 0.0), (25.0, 10.0), (10.0, 10.0), (10.0, 25.0), (0.0, 25.0)]
    pts = actions.grid_points(ell, 5.0)
    assert (5.0, 5.0) in pts and (20.0, 5.0) in pts and (5.0, 20.0) in pts
    assert not [p for p in pts if p[0] > 10.0 and p[1] > 10.0]
    assert actions.grid_points(square, 0.0) == [] and actions.grid_points(square[:2], 5.0) == []


def test_dem_surface_answers_in_drawing_coordinates(tmp_path):
    h = _Harness(tmp_path)
    surface = actions.DemSurface(h.dem, Georef(19))
    x, y = 229140.0, 8181320.0
    lat, lon = datum.drawing_to_latlon(Georef(19), x, y)
    assert surface.z_at(x, y) == pytest.approx(analytic(lat, lon), abs=0.02)
    assert surface.name == "DEM"


def test_dempoints_lays_the_grid_at_the_dems_elevations_and_says_so(tmp_path):
    from plugins.terreno.tools import DemPointsTool

    h = _Harness(tmp_path)
    boundary = h.msp.add_lwpolyline(BOX, close=True)
    tool = DemPointsTool(h.ctx)
    tool.start()
    tool.on_selection([boundary])
    assert h.prompts[-1] == "Grid spacing in metres <30>:"
    assert tool.on_option("abc") and "Invalid number" in h.echoed[-1]
    assert tool.on_option("10")
    assert h.finished
    points = [e for e in h.msp if e.dxftype() == "POINT"]
    assert len(points) == 441
    assert {e.dxf.layer for e in points} == {"TERRENO-DEM"}
    p = points[0]
    lat, lon = datum.drawing_to_latlon(Georef(19), p.dxf.location.x, p.dxf.location.y)
    assert p.dxf.location.z == pytest.approx(analytic(lat, lon), abs=0.02)
    assert [v for _c, v in p.get_xdata("INGECAD")] == ["DEM-POINT", "aws_terrarium"]
    assert any(line.startswith("441 elevation points on TERRENO-DEM, from ") for line in h.echoed)
    assert h.echoed[-1].startswith("Elevations from AWS Terrain Tiles: about 18 m per pixel over 30 m data.")
    assert "preliminary design only" in h.echoed[-1]
    assert h.fetch.urls                                  # tiles were fetched, once each
    assert len(h.fetch.urls) == len(set(h.fetch.urls))
    # one undo step for the grid and its layer
    h.history.undo()
    assert not [e for e in h.msp if e.dxftype() == "POINT"]
    assert "TERRENO-DEM" not in h.document.doc.layers
    # what TIN takes: the same POINTs, through Topography's own reader
    h.history.redo()
    from plugins.topografia import actions as topo
    pts, _breaklines = topo.surface_inputs([e for e in h.msp if e.dxftype() == "POINT"])
    assert len(pts) == 441 and all(len(p) == 3 for p in pts)


def test_dempoints_takes_two_corners_and_refuses_without_a_georef(tmp_path):
    from plugins.terreno.tools import DemPointsTool

    h = _Harness(tmp_path)
    tool = DemPointsTool(h.ctx)
    tool.start()
    tool.on_selection([])                                  # nothing closed: corners
    assert h.prompts[-1] == "Specify first corner:"
    tool.on_point((229095.0, 8181295.0))
    tool.on_point((229095.0, 8181400.0))                   # degenerate
    assert h.echoed[-1] == "The corners must make a rectangle."
    tool.on_point((229305.0, 8181505.0))
    tool.on_enter()                                        # spacing 30
    assert h.finished
    assert len([e for e in h.msp if e.dxftype() == "POINT"]) == 7 * 7

    h2 = _Harness(tmp_path, georef=None)
    t2 = DemPointsTool(h2.ctx)
    t2.start()
    assert h2.finished and "run GEOREF first" in h2.echoed[-1]
    h3 = _Harness(tmp_path)
    h3.document.active_layout = "Layout1"
    t3 = DemPointsTool(h3.ctx)
    t3.start()
    assert h3.finished and h3.echoed[-1] == "DEM elevations are taken in model space."


def test_dempoints_reports_a_download_failure_and_draws_nothing(tmp_path):
    from plugins.terreno.tools import DemPointsTool

    def refuse(url):
        raise dem.DemError(f"{url}: HTTP 503")
    h = _Harness(tmp_path, fetch=refuse)
    boundary = h.msp.add_lwpolyline(BOX, close=True)
    tool = DemPointsTool(h.ctx)
    tool.start()
    tool.on_selection([boundary])
    tool.on_option("50")
    assert h.finished
    assert h.echoed[-1].startswith("Could not get elevations: ") and "HTTP 503" in h.echoed[-1]
    assert not list(h.msp)[1:]                           # only the boundary
    h4 = _Harness(tmp_path)
    tiny = h4.msp.add_lwpolyline([(229101, 8181301), (229102, 8181301), (229102, 8181302), (229101, 8181302)],
                                 close=True)                       # between the grid's nodes
    t4 = DemPointsTool(h4.ctx)
    t4.start()
    t4.on_selection([tiny])
    t4.on_option("30")
    assert h4.finished and "No grid node" in h4.echoed[-1]


def test_demprofile_draws_the_axis_profile_from_the_dem(tmp_path):
    from plugins.terreno.tools import DemProfileTool

    h = _Harness(tmp_path)
    axis = h.msp.add_line((229100.0, 8181300.0), (229300.0, 8181480.0))
    tool = DemProfileTool(h.ctx)
    tool.start()
    tool.on_selection([axis])
    assert h.prompts[-1] == "Station step <20>:"
    assert tool.on_option("25")
    assert h.prompts[-1] == "Horizontal scale 1:<1000>:"
    tool.on_enter()
    tool.on_enter()
    assert h.prompts[-1] == "Specify the bottom-left corner of the profile:"
    tool.on_point((229400.0, 8181300.0))
    assert h.finished
    kinds = [e.dxftype() for e in h.msp]
    assert kinds.count("LWPOLYLINE") >= 1 and kinds.count("TEXT") > 5
    layers = {e.dxf.layer for e in h.msp}
    assert "TOPO-PERFIL" in layers and "TOPO-PERFIL-GRILLA" in layers
    assert h.echoed[-1].startswith("Elevations from AWS Terrain Tiles:")
    # the ground line's elevations are the DEM's: its first vertex sits at the
    # profile origin's height for the analytic ground at the axis start
    from plugins.topografia import actions as topo
    ground = next(e for e in h.msp if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "TOPO-PERFIL")
    frame = topo.ProfileFrame.from_entity(ground)
    s0, z0 = frame.to_chainage(*ground.get_points("xy")[0])
    lat, lon = datum.drawing_to_latlon(Georef(19), 229100.0, 8181300.0)
    assert s0 == pytest.approx(0.0, abs=1e-6) and z0 == pytest.approx(analytic(lat, lon), abs=0.05)
    h.history.undo()
    assert [e.dxftype() for e in h.msp] == ["LINE"]

    h2 = _Harness(tmp_path)
    t2 = DemProfileTool(h2.ctx)
    t2.start()
    t2.on_selection([h2.msp.add_circle((0, 0), 5)])
    assert h2.finished and h2.echoed[-1] == "The selection has no axis."


def test_the_window_runs_dempoints_from_the_command_line_and_the_layers_tab_follows(qapp, tmp_path):
    """The real path: the command typed, the corners typed, the grid on
    its layer -- and the Layers tab showing that layer at once (the gap
    the first capture of G2 exposed), gone again with U."""
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        for name in ("DEMPOINTS", "DEMPROFILE"):
            assert name in win.dispatcher._commands
        bar_actions = win._menu_bar.actions()               # held: a dropped wrapper kills its menu
        terrain = next(a for a in bar_actions if a.text() == "Terrain")
        menu = terrain.menu()
        labels = [a.text() for a in menu.actions() if a.text()]
        assert labels[:5] == ["Georeference drawing...", "Geographic coordinates...",
                              "Elevation points from DEM...", "Profile from DEM...",
                              "Satellite image..."]           # G4 checks its own three
        win.new_document("m")
        win.tools._execute(SetGeorefCommand(Georef(19)))
        win.tools.dem = dem.Dem(dem.TileStore(dem.AWS_TERRAIN, tmp_path / "cache", FakeFetch()), 13)
        win.dispatcher.submit("DEMPOINTS")
        win.tools.on_text("")                                # no polygon: two corners
        win.tools.on_text("229095,8181295")
        win.tools.on_text("229305,8181505")
        win.tools.on_text("30")
        msp = win.document.doc.modelspace()
        assert len([e for e in msp if e.dxftype() == "POINT"]) == 49
        assert "TERRENO-DEM" in win._layers_panel._rows
        win.dispatcher.submit("U")
        assert not [e for e in msp if e.dxftype() == "POINT"]
        assert "TERRENO-DEM" not in win._layers_panel._rows
    finally:
        win.tools.dem = None
        if win.document is not None:
            win.document.dirty = False
        win.close()
