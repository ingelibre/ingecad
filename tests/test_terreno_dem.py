# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Terrain plugin, G2: elevations from a tiled DEM -- the tile maths, the
terrarium encoding, bilinear sampling across tile seams, the disk cache
and the errors, all on synthetic tiles. The live download (the DoD's
200 x 200 m in under 10 s cold) runs only with INGECAD_ONLINE=1."""
from __future__ import annotations

import math
import os
import re
import time
from pathlib import Path

import numpy as np
import pytest

from plugins.terreno import dem

AREQUIPA = (-16.434361, -71.536454)          # LOTE V1 of the synthetic survey
_ZXY = re.compile(r"/(\d+)/(\d+)/(\d+)\.png$")


def analytic(lat: float, lon: float) -> float:
    """A gently sloping ground: 2000 m plus 100 m per degree east and north."""
    return 2000.0 + 100.0 * (lon + 71.5) + 100.0 * (lat + 16.4)


class FakeFetch:
    """Serves terrarium tiles of the analytic ground; counts what it served."""

    def __init__(self, ground=analytic, broken: bool = False):
        self.ground = ground
        self.broken = broken
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        if self.broken:
            return b"not a png"
        z, x, y = (int(v) for v in _ZXY.search(url).groups())
        field = np.empty((dem.TILE_PX, dem.TILE_PX), dtype=np.float64)
        for j in range(dem.TILE_PX):
            for i in range(dem.TILE_PX):
                lat, lon = dem.num2deg(x + (i + 0.5) / dem.TILE_PX, y + (j + 0.5) / dem.TILE_PX, z)
                field[j, i] = self.ground(lat, lon)
        return dem.encode_terrarium(field)


def _dem(tmp_path, zoom=13, **kw) -> tuple[dem.Dem, FakeFetch]:
    fetch = FakeFetch(**kw)
    return dem.Dem(dem.TileStore(dem.AWS_TERRAIN, tmp_path / "cache", fetch), zoom), fetch


def test_tile_maths_round_trips_and_finds_arequipas_tile():
    x, y = dem.deg2num(*AREQUIPA, 13)
    assert (int(x), int(y)) == (2468, 4475)
    lat, lon = dem.num2deg(x, y, 13)
    assert (lat, lon) == pytest.approx(AREQUIPA, abs=1e-9)
    assert dem.num2deg(0, 0, 0) == pytest.approx((dem.MAX_LAT, -180.0), abs=1e-6)
    assert dem.tiles_covering(-16.44, -71.54, -16.43, -71.53, 13) == [(2468, 4475)]
    assert len(dem.tiles_covering(-16.5, -71.6, -16.4, -71.5, 13)) == 9      # 3 x 3 of 0.044°
    assert dem.metres_per_pixel(0.0, 13) == pytest.approx(19.1, abs=0.05)
    assert dem.metres_per_pixel(AREQUIPA[0], 13) == pytest.approx(18.3, abs=0.05)
    assert dem.AWS_TERRAIN.url(13, 2468, 4475) == \
        "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/13/2468/4475.png"


def test_terrarium_encodes_and_decodes_to_the_256th_of_a_metre():
    field = np.array([[-32768.0, 0.0], [2335.4, 8848.86]])
    back = dem.decode(dem.encode_terrarium(field))
    assert back.shape == (2, 2) and back.dtype == np.float32
    assert np.abs(back - field).max() < 1 / 256 + 1e-6
    # the Mapbox encoding, from its formula
    from PIL import Image
    import io
    rgb = np.zeros((1, 1, 3), dtype=np.uint8)
    rgb[0, 0] = (1, 0xE2, 0x48)                         # (65536 + 226*256 + 72) * 0.1 - 10000 = 2346.4
    out = io.BytesIO()
    Image.fromarray(rgb, "RGB").save(out, format="PNG")
    assert dem.decode(out.getvalue(), "mapbox")[0, 0] == pytest.approx(2346.4, abs=0.01)
    with pytest.raises(dem.DemError):
        dem.decode(out.getvalue(), "esri")


def test_sampling_is_bilinear_and_seamless_across_tiles(tmp_path):
    d, fetch = _dem(tmp_path)
    for lat, lon in [AREQUIPA, (-16.4, -71.5), (-16.45, -71.55)]:
        assert d.elevation(lat, lon) == pytest.approx(analytic(lat, lon), abs=0.02)
    # walk across the seam between tiles 2468 and 2469: no step
    lat_seam, lon_seam = dem.num2deg(2469, 4475.5, 13)
    values = [d.elevation(lat_seam, lon_seam + k * 1e-5) for k in range(-6, 7)]
    steps = [b - a for a, b in zip(values, values[1:])]
    assert max(steps) - min(steps) < 0.05 and all(s > 0 for s in steps)
    assert {(2468, 4475), (2469, 4475)} <= {
        tuple(int(v) for v in _ZXY.search(u).groups()[1:]) for u in fetch.urls}


def test_the_cache_serves_the_second_run_without_a_download(tmp_path):
    d, fetch = _dem(tmp_path)
    tiles, downloaded = d.prefetch(-16.44, -71.54, -16.43, -71.53)
    assert tiles == 1 and downloaded == 1 and d.store.downloads == 1
    assert d.prefetch(-16.44, -71.54, -16.43, -71.53) == (1, 0)
    assert (tmp_path / "cache" / "aws_terrarium" / "13" / "2468" / "4475.png").is_file()
    again, fetch2 = _dem(tmp_path)
    assert again.elevation(*AREQUIPA) == pytest.approx(analytic(*AREQUIPA), abs=0.02)
    assert fetch2.urls == []                              # not one request
    # a damaged cache file is refetched, not trusted
    (tmp_path / "cache" / "aws_terrarium" / "13" / "2468" / "4475.png").write_bytes(b"junk")
    third, fetch3 = _dem(tmp_path)
    assert third.elevation(*AREQUIPA) == pytest.approx(analytic(*AREQUIPA), abs=0.02)
    assert len(fetch3.urls) == 1


def test_errors_name_the_tile(tmp_path):
    d, _fetch = _dem(tmp_path, broken=True)
    with pytest.raises(dem.DemError, match=r"13/2468/4475\.png: not a DEM tile"):
        d.elevation(*AREQUIPA)
    assert not (tmp_path / "cache" / "aws_terrarium").exists()   # nothing bad was cached

    def refuse(url):
        raise dem.DemError(f"{url}: HTTP 403")
    d2 = dem.Dem(dem.TileStore(dem.AWS_TERRAIN, tmp_path / "c2", refuse), 13)
    with pytest.raises(dem.DemError, match="HTTP 403"):
        d2.prefetch(-16.44, -71.54, -16.43, -71.53)
    assert dem.Dem(dem.TileStore(dem.AWS_TERRAIN, tmp_path / "c3"), 99).zoom == 15


@pytest.mark.skipif(not os.environ.get("INGECAD_ONLINE"), reason="set INGECAD_ONLINE=1 for the live DoD")
def test_live_the_lot_downloads_and_samples_in_under_ten_seconds(tmp_path):
    """The DoD: 200 x 200 m around the Arequipa lot, cold cache under 10 s,
    warm cache instant, and the elevation is Arequipa's."""
    d = dem.Dem(dem.TileStore(dem.AWS_TERRAIN, tmp_path / "live"), 13)
    t0 = time.perf_counter()
    tiles, downloaded = d.prefetch(AREQUIPA[0] - 0.001, AREQUIPA[1] - 0.001,
                                   AREQUIPA[0] + 0.001, AREQUIPA[1] + 0.001)
    z = d.elevation(*AREQUIPA)
    cold = time.perf_counter() - t0
    assert downloaded >= 1 and cold < 10.0, (tiles, downloaded, cold)
    assert 2200 < z < 2500, z                             # the survey says 2335
    t0 = time.perf_counter()
    for k in range(400):
        d.elevation(AREQUIPA[0] + k * 5e-6, AREQUIPA[1])
    assert time.perf_counter() - t0 < 0.5
