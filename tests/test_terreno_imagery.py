# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Terrain plugin, G3: the satellite image under the plan -- tile sources
and cache, the mosaic resampled into the drawing's UTM grid (the pixels
land where the maths says), the clip, the IMAGE with its attribution
sent to the back, the file beside the drawing, DXF and DWG round trips,
and the tool driven headless on synthetic tiles."""
from __future__ import annotations

import io
import math
import re
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from core.commands import History
from core.document import Document
from core.georef import Georef, SetGeorefCommand
from plugins.terreno import actions, datum, imagery, tiles
from tools.base import ToolContext

GEOREF = Georef(19)
BOX = [(229095.0, 8181295.0), (229305.0, 8181295.0), (229305.0, 8181505.0), (229095.0, 8181505.0)]
TRIANGLE = [(229120.0, 8181320.0), (229280.0, 8181330.0), (229200.0, 8181480.0)]


def paint(lat, lon):
    """A smooth colour field: the test's ground truth for 'which pixel is where'."""
    r = 128 + 120 * np.sin(np.asarray(lon) * 2000.0)
    g = 128 + 120 * np.sin(np.asarray(lat) * 2000.0)
    return r, g, 90.0


class FakeTiles:
    """Serves PNG tiles of the painted field for any source's template."""

    def __init__(self, source: tiles.TileSource):
        pattern = re.escape(source.url_template)
        for key in ("z", "x", "y"):
            pattern = pattern.replace(re.escape("{" + key + "}"), rf"(?P<{key}>\d+)")
        self.pattern = re.compile(pattern)
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        m = self.pattern.match(url)
        z, x, y = int(m["z"]), int(m["x"]), int(m["y"])
        n = 256 * 2 ** z
        gx = x * 256 + np.arange(256) + 0.5
        gy = y * 256 + np.arange(256) + 0.5
        lon = gx / n * 360.0 - 180.0
        lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * gy / n))))
        r, g, b = paint(lat[:, None], lon[None, :])
        rgb = np.stack([np.broadcast_to(r, (256, 256)), np.broadcast_to(g, (256, 256)),
                        np.full((256, 256), b)], axis=-1).astype(np.uint8)
        out = io.BytesIO()
        Image.fromarray(rgb, "RGB").save(out, format="PNG")
        return out.getvalue()


def _cache(tmp_path, source=None) -> tiles.TileCache:
    source = source or tiles.custom_source("https://fake.test/{z}/{x}/{y}.png", 19, "fake")
    return tiles.TileCache(source, tmp_path / "tiles", FakeTiles(source))


def _expected(x, y):
    lat, lon = datum.drawing_to_latlon(GEOREF, x, y)
    r, g, b = paint(lat, lon)
    return float(r), float(g), float(b)


# -- sources and cache ---------------------------------------------------------------------

def test_sources_know_their_url_order_extension_and_licence():
    esri, osm, s2 = tiles.PRESETS["esri_imagery"], tiles.PRESETS["osm"], tiles.PRESETS["s2cloudless"]
    assert esri.url(18, 100, 200).endswith("/tile/18/200/100")          # ArcGIS: z/y/x
    assert osm.url(18, 100, 200).endswith("/18/100/200.png")
    assert (esri.extension, osm.extension, s2.extension) == (".bin", ".png", ".jpg")
    assert all(p.attribution for p in tiles.PRESETS.values())
    hosts = [p.url_template.split("/")[2] for p in tiles.PRESETS.values()]
    assert not [h for h in hosts if "google" in h]          # never a preset; a user's own risk only
    custom = tiles.custom_source("https://x.test/{z}/{x}/{y}.jpg", 17, "Mi servidor")
    assert custom.id == "custom-mi-servidor" and custom.max_zoom == 17 and custom.extension == ".jpg"
    assert tiles.custom_source("https://x.test/{z}/{x}/{y}").id == "custom"


def test_the_cache_fetches_a_tile_once_and_can_forget_it(tmp_path):
    cache = _cache(tmp_path)
    a = cache.bytes(15, 4936, 8950)
    b = cache.bytes(15, 4936, 8950)
    assert a == b and cache.downloads == 1
    path = cache.path(15, 4936, 8950)
    assert path.is_file() and path.suffix == ".png" and "custom-fake" in str(path)
    cache.forget(15, 4936, 8950)
    assert not path.exists()
    cache.bytes(15, 4936, 8950)
    assert cache.downloads == 2

    def refuse(url):
        raise tiles.TileError(f"{url}: HTTP 429")
    with pytest.raises(tiles.TileError, match="HTTP 429"):
        tiles.TileCache(tiles.PRESETS["osm"], tmp_path / "t2", refuse).bytes(1, 0, 0)


# -- the image in the drawing's grid --------------------------------------------------------

def test_the_plan_frames_the_polygon_in_the_drawings_grid():
    p = imagery.plan(GEOREF, BOX, 15)
    res = tiles.metres_per_pixel(-16.4344, 15)
    assert p["res"] == pytest.approx(res, rel=1e-3)
    assert p["width"] == p["height"] == math.ceil(210.0 / p["res"])
    assert (p["e0"], p["n0"], p["n1"]) == (229095.0, 8181295.0, 8181505.0)
    assert 1 <= len(p["tiles"]) <= 4 and imagery.tile_count(GEOREF, BOX, 15) == len(p["tiles"])
    assert imagery.tile_count(GEOREF, [(229000, 8181000), (234000, 8181000), (234000, 8186000),
                                       (229000, 8186000)], 19) > imagery.MAX_TILES


def test_the_pixels_land_where_the_maths_says(tmp_path):
    cache = _cache(tmp_path)
    placement = imagery.satellite_image(GEOREF, BOX, 15, cache, clip=False)
    assert placement.image.mode == "RGB"
    assert placement.width == placement.height == math.ceil(210.0 / placement.pixel_size)
    assert placement.insert == (229095.0, 8181295.0)
    assert placement.top == pytest.approx(8181295.0 + placement.height * placement.pixel_size)
    for x, y in [(229100.0, 8181300.0), (229300.0, 8181500.0), (229200.0, 8181400.0),
                 (229300.0, 8181300.0), (229100.0, 8181500.0)]:
        px, py = placement.to_pixel(x, y)
        got = placement.image.getpixel((min(int(px), placement.width - 1), min(int(py), placement.height - 1)))
        want = _expected(x, y)
        assert abs(got[0] - want[0]) <= 15 and abs(got[1] - want[1]) <= 15, ((x, y), got, want)
    assert cache.downloads == placement.tiles


def test_the_clip_leaves_the_outside_transparent(tmp_path):
    cache = _cache(tmp_path)
    placement = imagery.satellite_image(GEOREF, TRIANGLE, 15, cache, clip=True)
    assert placement.image.mode == "RGBA"
    cx = sum(p[0] for p in TRIANGLE) / 3
    cy = sum(p[1] for p in TRIANGLE) / 3
    px, py = placement.to_pixel(cx, cy)
    assert placement.image.getpixel((int(px), int(py)))[3] == 255
    assert placement.image.getpixel((placement.width - 1, 0))[3] == 0          # the NE corner: outside
    boundary = placement.clip_boundary(TRIANGLE)
    assert len(boundary) == 3 and boundary[0][0] == pytest.approx(
        (TRIANGLE[0][0] - placement.insert[0]) / placement.pixel_size - 0.5)
    assert imagery.file_extension(placement) == ".png"
    with pytest.raises(tiles.TileError, match="lower the zoom"):
        imagery.satellite_image(GEOREF, [(229000, 8181000), (234000, 8181000), (234000, 8186000),
                                         (229000, 8186000)], 19, cache)


# -- in the drawing ------------------------------------------------------------------------------

def test_insert_satellite_is_one_undo_step_with_clip_caption_and_draw_order(tmp_path):
    from formats.dwg_bridge import find_dwg2dxf, find_dxf2dwg, load_dwg

    document = Document.new()
    document.path = tmp_path / "lote.dxf"
    history = History(document)
    history.execute(SetGeorefCommand(GEOREF))
    msp = document.doc.modelspace()
    msp.add_line((229100, 8181300), (229300, 8181480))
    cache = _cache(tmp_path)
    placement = imagery.satellite_image(GEOREF, TRIANGLE, 15, cache, clip=True)
    path = actions.image_path(document, cache.source.id, imagery.file_extension(placement))
    assert path == tmp_path / "lote-custom-fake.png"
    history.execute(actions.insert_satellite(document, placement, path, TRIANGLE, True, cache.source))
    assert path.is_file() and Image.open(path).mode == "RGBA"
    image = msp.query("IMAGE")[0]
    assert image.dxf.layer == "TERRENO-SAT" and image.image_def.dxf.filename == str(path)
    assert (image.dxf.insert.x, image.dxf.insert.y) == placement.insert
    assert image.dxf.image_size == (placement.width, placement.height)
    assert image.dxf.u_pixel.x == pytest.approx(placement.pixel_size)
    assert image.dxf.flags & 4 and image.dxf.flags & 8
    wcs = [(p.x, p.y) for p in image.boundary_path_wcs()][:3]
    for (x, y), (ex, ey) in zip(wcs, TRIANGLE):
        assert (x, y) == pytest.approx((ex, ey), abs=placement.pixel_size)
    assert actions.is_satellite(image)
    assert [v for _c, v in image.get_xdata("INGECAD")][:3] == ["SAT-IMAGE", "custom-fake", 15]
    caption = msp.query("TEXT")[0]
    assert caption.dxf.text.startswith("Imagery: custom source") and caption.dxf.layer == "TERRENO-SAT"
    order = dict(msp.get_redraw_order())
    assert image.dxf.handle in order and int(order[image.dxf.handle], 16) < int(msp.query("LINE")[0].dxf.handle, 16)
    history.undo()
    assert not msp.query("IMAGE") and not msp.query("TEXT") and "TERRENO-SAT" not in document.doc.layers
    history.redo()
    image = msp.query("IMAGE")[0]
    assert image.dxf.flags & 4 and len(list(image.boundary_path_wcs())) >= 3
    # a second image beside the same drawing does not overwrite the first
    assert actions.image_path(document, cache.source.id, ".png") == tmp_path / "lote-custom-fake-2.png"
    # the file survives DXF and DWG
    document.save_as(document.path)
    again = Document.load(document.path)
    back = again.doc.modelspace().query("IMAGE")[0]
    assert back.image_def.dxf.filename == str(path) and back.dxf.flags & 4
    if find_dxf2dwg() is None or find_dwg2dxf() is None:
        pytest.skip("LibreDWG converters not built")
    dwg = tmp_path / "lote.dwg"
    document.save_as(dwg, "r2000")
    loaded = load_dwg(dwg)
    doc = loaded[0] if isinstance(loaded, tuple) else loaded
    doc = doc.doc if isinstance(doc, Document) else doc
    images = doc.modelspace().query("IMAGE")
    assert len(images) == 1
    assert Path(images[0].image_def.dxf.filename).name == path.name
    assert len(list(images[0].boundary_path_wcs())) >= 3


def test_an_untitled_drawing_keeps_the_image_under_the_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    document = Document.new()
    path = actions.image_path(document, "esri_imagery", ".jpg")
    assert path == tmp_path / "IngeCAD" / "satimage" / "untitled-esri_imagery.jpg"


# -- the tool ---------------------------------------------------------------------------------------

class _Services:
    def __init__(self, document, tmp_path):
        self.document = document
        self.tmp_path = tmp_path
        self.caches = {}

    def tiles(self, source):
        if source.id not in self.caches:
            self.caches[source.id] = tiles.TileCache(source, self.tmp_path / "tiles", FakeTiles(source))
        return self.caches[source.id]


class _Harness:
    def __init__(self, tmp_path, georef=GEOREF):
        self.document = Document.new()
        self.history = History(self.document)
        if georef is not None:
            self.history.execute(SetGeorefCommand(georef))
        self.finished = False
        self.echoed: list[str] = []
        self.prompts: list[str] = []
        self.services = _Services(self.document, tmp_path)
        self.ctx = ToolContext(
            execute=self.history.execute, prompt=self.prompts.append,
            echo=self.echoed.append, finish=lambda: setattr(self, "finished", True),
            undo_last=self.history.undo, services=self.services)

    @property
    def msp(self):
        return self.document.doc.modelspace()


def test_satimage_tool_asks_zoom_source_and_clip_then_inserts(tmp_path, monkeypatch):
    from plugins.terreno.tools import SatImageTool

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    h = _Harness(tmp_path)
    lot = h.msp.add_lwpolyline(TRIANGLE, close=True)
    tool = SatImageTool(h.ctx)
    tool.start()
    tool.on_selection([lot])
    assert h.prompts[-1].startswith("Zoom level (1-19) or [Source] <18>:")
    assert tool.on_option("25") and "serves zoom levels 1 to 19" in h.echoed[-1]
    assert tool.on_option("S")
    assert h.prompts[-1] == "Source [Esri/Sentinel/Osm/Custom] <Esri World Imagery>:"
    assert tool.on_option("C") and "No custom XYZ source" in h.echoed[-1]
    assert tool.on_option("S")
    assert tool.on_option("Osm")
    assert h.prompts[-1].startswith("Zoom level (1-19) or [Source] <18>:")
    assert tool.on_option("15")
    assert h.prompts[-1] == "Clip the image to the polygon? [Yes/No] <Yes>:"
    tool.on_enter()
    assert h.finished
    image = h.msp.query("IMAGE")[0]
    assert image.dxf.layer == "TERRENO-SAT" and image.dxf.flags & 4
    assert [v for _c, v in image.get_xdata("INGECAD")][1] == "osm"
    path = Path(image.image_def.dxf.filename)
    assert path.is_file() and path.parent == tmp_path / "IngeCAD" / "satimage" and path.suffix == ".png"
    assert any(line.startswith("Satellite image ") and "px at " in line for line in h.echoed)
    assert h.echoed[-1].endswith("© OpenStreetMap contributors")
    assert h.msp.query("TEXT")[0].dxf.text == "Imagery: © OpenStreetMap contributors"
    h.history.undo()
    assert not h.msp.query("IMAGE")


def test_satimage_tool_refuses_too_many_tiles_and_needs_a_georef(tmp_path, monkeypatch):
    from plugins.terreno.tools import SatImageTool

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    h = _Harness(tmp_path)
    tool = SatImageTool(h.ctx)
    tool.start()
    tool.on_selection([])
    tool.on_point((229000.0, 8181000.0))
    tool.on_point((234000.0, 8186000.0))
    assert tool.on_option("19")
    assert tool.on_option("N")                             # no clip
    assert h.finished and "lower the zoom or shrink the area" in h.echoed[-1]
    assert not h.msp.query("IMAGE") and not h.services.caches
    h2 = _Harness(tmp_path, georef=None)
    t2 = SatImageTool(h2.ctx)
    t2.start()
    assert h2.finished and "run GEOREF first" in h2.echoed[-1]


def test_the_window_runs_satimage_and_the_layers_tab_follows(qapp, tmp_path, monkeypatch):
    from views.main_window import MainWindow

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    win = MainWindow()
    try:
        assert "SATIMAGE" in win.dispatcher._commands
        win.new_document("m")
        win.tools._execute(SetGeorefCommand(GEOREF))
        services = _Services(win.document, tmp_path)
        win.tools.tiles = services.tiles
        win.dispatcher.submit("SATIMAGE")
        win.tools.on_text("")
        win.tools.on_text("229095,8181295")
        win.tools.on_text("229305,8181505")
        win.tools.on_text("15")
        win.tools.on_text("N")
        msp = win.document.doc.modelspace()
        image = msp.query("IMAGE")[0]
        assert Path(image.image_def.dxf.filename).suffix == ".jpg"
        assert "TERRENO-SAT" in win._layers_panel._rows
        win.dispatcher.submit("U")
        assert not msp.query("IMAGE") and "TERRENO-SAT" not in win._layers_panel._rows
    finally:
        win.tools.tiles = None
        win.document.dirty = False
        win.close()
