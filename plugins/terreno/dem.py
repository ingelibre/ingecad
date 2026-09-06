from __future__ import annotations

import io
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .tiles import (MAX_LAT, TILE_PX, TileCache, TileError, TileSource, deg2num,  # noqa: F401
                    default_cache_dir as tiles_cache_dir, fetch_url, metres_per_pixel,
                    num2deg, tiles_covering)


class DemError(TileError):
    """A DEM tile could not be fetched or read; the message says which and why."""


@dataclass(frozen=True)
class DemSource(TileSource):
    """A raster DEM provider: a tile source plus its RGB encoding
    (``terrarium`` or ``mapbox``) and the resolution of the data behind
    it, which is what the commands report."""

    encoding: str = "terrarium"
    data_resolution_m: float = 30.0


AWS_TERRAIN = DemSource(
    id="aws_terrarium",
    name="AWS Terrain Tiles",
    url_template="https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png",
    max_zoom=15,
    attribution="Terrain Tiles on AWS (Mapzen / Nextzen): SRTM, NED, Copernicus and others. "
                "https://registry.opendata.aws/terrain-tiles/",
    encoding="terrarium",
    data_resolution_m=30.0,
)

ENCODINGS = ("terrarium", "mapbox")


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


# -- decoded tiles ---------------------------------------------------------------------------

def default_cache_dir():
    return tiles_cache_dir()


class TileStore:
    """Decoded heightfields of one DEM source, in memory once read; the
    bytes come from the shared :class:`TileCache` (disk, then network)."""

    def __init__(self, source: DemSource, cache_dir=None, fetch=fetch_url) -> None:
        self.source = source
        self.cache = TileCache(source, cache_dir, fetch)
        self._fields: dict[tuple[int, int, int], np.ndarray] = {}

    @property
    def cache_dir(self):
        return self.cache.cache_dir

    @property
    def downloads(self) -> int:
        return self.cache.downloads

    def path(self, z: int, x: int, y: int):
        return self.cache.path(z, x, y)

    def cached(self, z: int, x: int, y: int) -> bool:
        return (z, x, y) in self._fields or self.cache.cached(z, x, y)

    def field(self, z: int, x: int, y: int) -> np.ndarray:
        key = (z, x, y)
        field = self._fields.get(key)
        if field is not None:
            return field
        was_cached = self.cache.cached(z, x, y)
        data = self.cache.bytes(z, x, y)
        try:
            field = decode(data, self.source.encoding)
        except DemError:
            raise
        except Exception as exc:
            if was_cached:                              # a damaged cache entry: refetch once
                self.cache.forget(z, x, y)
                data = self.cache.bytes(z, x, y)
                try:
                    field = decode(data, self.source.encoding)
                except DemError:
                    raise
                except Exception as exc2:
                    self.cache.forget(z, x, y)
                    raise DemError(f"{self.source.url(z, x, y)}: not a DEM tile ({exc2})") from exc2
            else:
                self.cache.forget(z, x, y)
                raise DemError(f"{self.source.url(z, x, y)}: not a DEM tile ({exc})") from exc
        self._fields[key] = field
        return field


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
