# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Elevations from a global DEM served as raster tiles, with no key:
AWS Terrain Tiles (terrarium encoding) by default; a Mapbox Terrain-RGB
URL works too if the user pastes one. Tiles are cached on disk under the
app's cache directory and decoded once into NumPy heightfields; sampling
is bilinear on the GLOBAL pixel grid, so a point on a tile seam reads the
same from either side.

Honesty, on screen every time: the data is a ~30 m DEM (SRTM and its
relatives), good for a preliminary design and useless for a survey.

Ported from IngeTrazo's ``georef/dem.py`` and ``georef/tiles.py`` minus
Qt: plain ``urllib`` and Pillow, so it runs headless and in the suite.
"""
from __future__ import annotations

import io
import math
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np

TILE_PX = 256
MAX_LAT = 85.05112878          # the Web Mercator limit
_EARTH_CIRCUMFERENCE = 40075016.686


class DemError(Exception):
    """A tile could not be fetched or read; the message says which and why."""


@dataclass(frozen=True)
class DemSource:
    """A raster DEM provider: a ``{z}/{x}/{y}`` URL plus its RGB encoding
    (``terrarium`` or ``mapbox``) and the resolution of the data behind
    it, which is what the commands report."""

    id: str
    name: str
    url_template: str
    encoding: str = "terrarium"
    max_zoom: int = 15
    attribution: str = ""
    data_resolution_m: float = 30.0

    def url(self, z: int, x: int, y: int) -> str:
        return (self.url_template.replace("{z}", str(z)).replace("{x}", str(x))
                .replace("{y}", str(y)))


AWS_TERRAIN = DemSource(
    id="aws_terrarium",
    name="AWS Terrain Tiles",
    url_template="https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png",
    encoding="terrarium",
    max_zoom=15,
    attribution="Terrain Tiles on AWS (Mapzen / Nextzen): SRTM, NED, Copernicus and others. "
                "https://registry.opendata.aws/terrain-tiles/",
    data_resolution_m=30.0,
)

ENCODINGS = ("terrarium", "mapbox")


# -- tile maths --------------------------------------------------------------------------

def deg2num(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    """Degrees -> fractional tile coordinates at ``zoom`` (integer part:
    the tile; fraction: where inside it)."""
    lat = max(-MAX_LAT, min(MAX_LAT, lat))
    n = 2 ** zoom
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


def num2deg(x: float, y: float, zoom: int) -> tuple[float, float]:
    """Fractional tile coordinates -> ``(lat, lon)``; integers give the
    tile's north-west corner."""
    n = 2 ** zoom
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lat, lon


def tiles_covering(lat_s: float, lon_w: float, lat_n: float, lon_e: float,
                   zoom: int) -> list[tuple[int, int]]:
    """Every ``(x, y)`` tile overlapping the box at ``zoom``."""
    x0, y0 = deg2num(lat_n, lon_w, zoom)
    x1, y1 = deg2num(lat_s, lon_e, zoom)
    n = 2 ** zoom
    xa, xb = int(math.floor(min(x0, x1))), int(math.floor(max(x0, x1)))
    ya, yb = int(math.floor(min(y0, y1))), int(math.floor(max(y0, y1)))
    return [(tx, ty) for tx in range(xa, xb + 1) for ty in range(ya, yb + 1)
            if 0 <= tx < n and 0 <= ty < n]


def metres_per_pixel(lat: float, zoom: int) -> float:
    """Ground size of one tile pixel at this latitude and zoom."""
    lat = max(-MAX_LAT, min(MAX_LAT, lat))
    return _EARTH_CIRCUMFERENCE * math.cos(math.radians(lat)) / (TILE_PX * 2 ** zoom)


# -- encoding ------------------------------------------------------------------------------

def decode(data: bytes, encoding: str = "terrarium") -> np.ndarray:
    """A tile's PNG bytes -> ``(H, W)`` float32 metres.

    terrarium: ``h = R * 256 + G + B / 256 - 32768``;
    mapbox: ``h = -10000 + (R * 65536 + G * 256 + B) * 0.1``.
    """
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    if encoding == "mapbox":
        return -10000.0 + (r * 65536.0 + g * 256.0 + b) * 0.1
    if encoding != "terrarium":
        raise DemError(f"unknown DEM encoding {encoding!r}")
    return (r * 256.0 + g + b / 256.0) - 32768.0


def encode_terrarium(field: np.ndarray) -> bytes:
    """Metres -> terrarium PNG bytes (the suite's fake tiles; also what a
    user would need to serve their own DEM as tiles)."""
    from PIL import Image

    v = np.clip(np.rint((np.asarray(field, dtype=np.float64) + 32768.0) * 256.0), 0, 2 ** 24 - 1)
    v = v.astype(np.uint32)
    rgb = np.stack([(v >> 16) & 255, (v >> 8) & 255, v & 255], axis=-1).astype(np.uint8)
    out = io.BytesIO()
    Image.fromarray(rgb, "RGB").save(out, format="PNG")
    return out.getvalue()


# -- fetching and caching --------------------------------------------------------------------

def _user_agent() -> str:
    try:
        from core.version import __version__
    except Exception:
        __version__ = "dev"
    return f"IngeCAD/{__version__} (+https://ingecad.org)"


def fetch_url(url: str, timeout: float = 20.0) -> bytes:
    """The bytes at ``url``, or a DemError that names the URL and the cause."""
    request = urllib.request.Request(url, headers={"User-Agent": _user_agent()})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise DemError(f"{url}: HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        reason = getattr(exc, "reason", None) or exc
        raise DemError(f"{url}: {reason}") from exc


def default_cache_dir() -> Path:
    from core.recent import cache_dir

    return cache_dir() / "dem"


class TileStore:
    """Tiles of one source: memory, then the disk cache, then the network.
    ``fetch`` is swappable, so the suite serves synthetic tiles."""

    def __init__(self, source: DemSource, cache_dir: Optional[Path] = None,
                 fetch: Callable[[str], bytes] = fetch_url) -> None:
        self.source = source
        self.cache_dir = Path(cache_dir) if cache_dir is not None else default_cache_dir()
        self.fetch = fetch
        self.downloads = 0
        self._fields: dict[tuple[int, int, int], np.ndarray] = {}

    def path(self, z: int, x: int, y: int) -> Path:
        return self.cache_dir / self.source.id / str(z) / str(x) / f"{y}.png"

    def cached(self, z: int, x: int, y: int) -> bool:
        return (z, x, y) in self._fields or self.path(z, x, y).is_file()

    def field(self, z: int, x: int, y: int) -> np.ndarray:
        key = (z, x, y)
        field = self._fields.get(key)
        if field is not None:
            return field
        path = self.path(z, x, y)
        if path.is_file():
            try:
                field = decode(path.read_bytes(), self.source.encoding)
            except Exception:
                path.unlink(missing_ok=True)          # a damaged cache entry: refetch
                field = None
        if field is None:
            url = self.source.url(z, x, y)
            data = self.fetch(url)
            self.downloads += 1
            try:
                field = decode(data, self.source.encoding)
            except DemError:
                raise
            except Exception as exc:
                raise DemError(f"{url}: not a DEM tile ({exc})") from exc
            self._write(path, data)
        self._fields[key] = field
        return field

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        """Atomic: a half-written tile must never read as a cache hit."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            tmp.write_bytes(data)
            os.replace(tmp, path)
        except OSError:
            pass                                       # the cache is a convenience


class Dem:
    """Elevation at any latitude and longitude, bilinear on the global
    pixel grid of one zoom level."""

    def __init__(self, store: TileStore, zoom: int = 13) -> None:
        self.store = store
        self.zoom = max(0, min(int(zoom), store.source.max_zoom))

    @property
    def source(self) -> DemSource:
        return self.store.source

    def metres_per_pixel(self, lat: float) -> float:
        return metres_per_pixel(lat, self.zoom)

    def _pixel(self, i: int, j: int) -> float:
        n = TILE_PX * 2 ** self.zoom
        i = min(max(i, 0), n - 1)
        j = min(max(j, 0), n - 1)
        field = self.store.field(self.zoom, i // TILE_PX, j // TILE_PX)
        return float(field[j % TILE_PX, i % TILE_PX])

    def elevation(self, lat: float, lon: float) -> float:
        """Metres above the DEM's datum (the ellipsoid-agnostic height the
        source publishes; SRTM's is EGM96 orthometric)."""
        xf, yf = deg2num(lat, lon, self.zoom)
        gx, gy = xf * TILE_PX - 0.5, yf * TILE_PX - 0.5      # pixel centres at .5
        i0, j0 = int(math.floor(gx)), int(math.floor(gy))
        fx, fy = gx - i0, gy - j0
        top = self._pixel(i0, j0) * (1 - fx) + self._pixel(i0 + 1, j0) * fx
        bottom = self._pixel(i0, j0 + 1) * (1 - fx) + self._pixel(i0 + 1, j0 + 1) * fx
        return top * (1 - fy) + bottom * fy

    def prefetch(self, lat_s: float, lon_w: float, lat_n: float, lon_e: float) -> tuple[int, int]:
        """Fetch every tile the box (plus the pixel of margin bilinear
        sampling reaches) needs; returns ``(tiles, downloaded)``."""
        pad = 1.5 / (TILE_PX * 2 ** self.zoom) * 360.0       # one pixel and a half, in degrees
        tiles = tiles_covering(lat_s - pad, lon_w - pad, lat_n + pad, lon_e + pad, self.zoom)
        before = self.store.downloads
        for x, y in tiles:
            self.store.field(self.zoom, x, y)
        return len(tiles), self.store.downloads - before


def default_dem() -> Dem:
    """The DEM the commands use: the source and zoom from Options."""
    from . import prefs

    return Dem(TileStore(prefs.dem_source()), prefs.dem_zoom())
