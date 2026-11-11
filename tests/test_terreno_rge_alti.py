# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Terrain plugin, France: elevations from IGN's RGE ALTI (1 m, NGF-IGN69)
through the Géoplateforme WMS as raw 32-bit floats -- one request per
area, split past 2048 samples a side, sampled bilinearly, honest about
the sea and abroad; chosen by itself for a drawing in a French system.
Driven on a synthetic ground served the way the WMS serves it."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import numpy as np
import pytest

pytest.importorskip("pyproj")

from core.commands import History  # noqa: E402
from core.document import Document  # noqa: E402
from core.georef import Georef, SetGeorefCommand  # noqa: E402
from plugins.terreno import actions, datum, dem, prefs  # noqa: E402
from tools.base import ToolContext  # noqa: E402

L93 = Georef(crs="EPSG:2154")
ALBI = (43.92850, 2.14250)


def ground(lat, lon):
    """A plane: 150 m at Albi, rising 1000 m per degree north and east."""
    return 150.0 + 1000.0 * (lat - ALBI[0]) + 1000.0 * (lon - ALBI[1])


class FakeWms:
    """Answers GetMap like the Géoplateforme: little-endian float32 rows,
    north first, pixel centres at half steps; -99999 south of ``sea``."""

    def __init__(self, sea: float | None = None, garbage: bool = False):
        self.sea = sea
        self.garbage = garbage
        self.requests: list[dict] = []

    def __call__(self, url: str) -> bytes:
        query = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        self.requests.append(query)
        if self.garbage:
            return b'<?xml version="1.0"?><ServiceExceptionReport>no</ServiceExceptionReport>'
        assert query["CRS"] == "EPSG:4326" and query["FORMAT"] == "image/x-bil;bits=32"
        lat_s, lon_w, lat_n, lon_e = (float(v) for v in query["BBOX"].split(","))
        w, h = int(query["WIDTH"]), int(query["HEIGHT"])
        lons = lon_w + (np.arange(w) + 0.5) * (lon_e - lon_w) / w
        lats = lat_n - (np.arange(h) + 0.5) * (lat_n - lat_s) / h
        field = ground(lats[:, None], lons[None, :])
        if self.sea is not None:
            field = np.where(lats[:, None] < self.sea, -99999.0, field)
        return field.astype("<f4").tobytes()


def _dem(**kw):
    fake = FakeWms(**kw)
    return dem.IgnAltiDem(fetch=fake), fake


def test_the_getmap_url_asks_for_floats_latitude_first():
    url = dem.ign_getmap_url(43.9, 2.1, 44.0, 2.2, 100, 80)
    assert url.startswith("https://data.geopf.fr/wms-r/wms?")
    assert "LAYERS=ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES" in url
    assert "BBOX=43.900000000,2.100000000,44.000000000,2.200000000" in url
    assert "WIDTH=100&HEIGHT=80&FORMAT=image/x-bil;bits=32" in url


def test_a_prefetched_area_is_one_request_and_samples_the_plane_exactly():
    d, fake = _dem()
    requests, downloaded = d.prefetch(43.927, 2.141, 43.930, 2.144)
    assert (requests, downloaded) == (1, 1)
    for lat, lon in ((43.9285, 2.1425), (43.92711, 2.14399), (43.92999, 2.14101)):
        assert d.elevation(lat, lon) == pytest.approx(ground(lat, lon), abs=1e-3)
    assert len(fake.requests) == 1                       # sampling fetches nothing more
    assert d.metres_per_pixel(ALBI[0]) == 1.0


def test_a_large_area_is_split_and_coarsened_but_stays_seamless():
    d, fake = _dem()
    d.prefetch(43.90, 2.10, 43.96, 2.18)                 # about 6.5 x 6.7 km
    assert len(fake.requests) > 1
    assert all(int(q["WIDTH"]) <= dem.MAX_SIDE_PX + 1 and int(q["HEIGHT"]) <= dem.MAX_SIDE_PX + 1
               for q in fake.requests)
    total = sum(int(q["WIDTH"]) * int(q["HEIGHT"]) for q in fake.requests)
    assert total <= dem.MAX_AREA_PX * 1.01
    assert d.metres_per_pixel(ALBI[0]) > 1.0
    # across the seams between requests, still the plane
    for k in range(40):
        lat, lon = 43.90 + 0.06 * k / 39, 2.10 + 0.08 * ((k * 7) % 40) / 39
        assert d.elevation(lat, lon) == pytest.approx(ground(lat, lon), abs=1e-3)


def test_a_point_outside_the_prefetch_gets_its_own_small_window():
    d, fake = _dem()
    lat, lon = 44.1, 2.3
    assert d.elevation(lat, lon) == pytest.approx(ground(lat, lon), abs=1e-3)
    assert (fake.requests[-1]["WIDTH"], fake.requests[-1]["HEIGHT"]) == ("16", "16")


def test_the_sea_and_a_wrong_answer_say_so():
    d, _fake = _dem(sea=43.9285)
    d.prefetch(43.927, 2.141, 43.930, 2.144)
    assert d.elevation(43.9295, 2.1425) == pytest.approx(ground(43.9295, 2.1425), abs=1e-3)
    with pytest.raises(dem.DemError, match="no elevation here"):
        d.elevation(43.9275, 2.1425)
    d, _fake = _dem(garbage=True)
    with pytest.raises(dem.DemError, match="ServiceExceptionReport"):
        d.prefetch(43.927, 2.141, 43.930, 2.144)

    def down(url):
        raise dem.TileError(f"{url}: timed out")

    with pytest.raises(dem.DemError, match="timed out"):
        dem.IgnAltiDem(fetch=down).prefetch(43.927, 2.141, 43.930, 2.144)


def test_a_french_drawing_gets_rge_alti_unless_options_say_otherwise(monkeypatch):
    settings = {}
    monkeypatch.setattr(prefs, "_setting", lambda key, default: settings.get(key, default))
    assert isinstance(dem.default_dem(L93), dem.IgnAltiDem)
    assert isinstance(dem.default_dem(Georef(crs="EPSG:3944")), dem.IgnAltiDem)
    assert isinstance(dem.default_dem(Georef(19)), dem.Dem)
    assert isinstance(dem.default_dem(None), dem.Dem)
    settings[prefs.SETTING_DEM_ENCODING] = "terrarium"
    assert isinstance(dem.default_dem(L93), dem.Dem)
    settings[prefs.SETTING_DEM_ENCODING] = "ign"
    assert isinstance(dem.default_dem(Georef(19)), dem.IgnAltiDem)
    settings[prefs.SETTING_DEM_ENCODING] = "auto"
    settings[prefs.SETTING_DEM_URL] = "https://my.server/{z}/{x}/{y}.png"
    assert isinstance(dem.default_dem(L93), dem.Dem)     # the user's own tiles win


def test_the_honesty_line_names_ngf():
    d, _fake = _dem()
    line = actions.honesty(d, ALBI[0])
    assert line.startswith("Elevations from IGN RGE ALTI: about 1 m per pixel over 1 m data.")
    assert line.endswith("Heights in NGF-IGN69 (IGN78 in Corsica).")
    assert "Heights in" not in actions.honesty(dem.Dem(dem.TileStore(dem.AWS_TERRAIN)), ALBI[0])


class _Services:
    def __init__(self, document, d):
        self.document = document
        self.dem = d


def test_dempoints_on_a_lambert_93_drawing_lays_ngf_points():
    from plugins.terreno.tools import DemPointsTool

    document = Document.new()
    history = History(document)
    history.execute(SetGeorefCommand(L93))
    d, fake = _dem()
    echoed, prompts, done = [], [], []
    ctx = ToolContext(execute=history.execute, prompt=prompts.append, echo=echoed.append,
                      finish=lambda: done.append(True), undo_last=history.undo,
                      services=_Services(document, d))
    e, n = datum.latlon_to_drawing(L93, *ALBI)
    e, n = round(e / 30) * 30, round(n / 30) * 30        # nodes at e-30, e, e+30
    box = [(e - 45, n - 45), (e + 45, n - 45), (e + 45, n + 45), (e - 45, n + 45)]
    boundary = document.doc.modelspace().add_lwpolyline(box, close=True)
    tool = DemPointsTool(ctx)
    tool.start()
    tool.on_selection([boundary])
    tool.on_option("30")
    assert done and len(fake.requests) == 1
    points = list(document.doc.modelspace().query("POINT"))
    assert len(points) == 9
    for p in points:
        lat, lon = datum.drawing_to_latlon(L93, p.dxf.location.x, p.dxf.location.y)
        assert p.dxf.location.z == pytest.approx(ground(lat, lon), abs=1e-3)
    assert any("NGF-IGN69" in line for line in echoed)
    assert re.search(r"9 elevation points on TERRENO-DEM", "\n".join(echoed))
