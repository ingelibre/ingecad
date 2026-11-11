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
    #: The height system the values are in, said with every result when
    #: known ("NGF-IGN69" for IGN's RGE ALTI); "" for the global sources.
    vertical: str = ""


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


# -- France: IGN's RGE ALTI, 1 m, NGF heights ------------------------------------------------

#: The Géoplateforme WMS serves the RGE ALTI® elevation grid as raw 32-bit
#: floats (``image/x-bil;bits=32``, little-endian, -99999 where there is no
#: data): one request per area instead of one per point, and the values
#: are metres in NGF-IGN69 on the mainland (IGN78 in Corsica, the local
#: systems overseas), the heights a French plan is drawn in.
IGN_WMS = "https://data.geopf.fr/wms-r/wms"
IGN_LAYER = "ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES"

IGN_RGE_ALTI = DemSource(
    id="ign_rge_alti",
    name="IGN RGE ALTI",
    url_template=IGN_WMS,
    max_zoom=0,
    attribution="IGN – RGE ALTI®, Géoplateforme – Licence Ouverte Etalab 2.0",
    encoding="ign_bil",
    data_resolution_m=1.0,
    vertical="NGF-IGN69 (IGN78 in Corsica)",
)

NODATA = -99990.0               # below this, the service had nothing (sea, abroad)
MAX_SIDE_PX = 2048              # one request at most this wide and high
MAX_AREA_PX = 16_000_000        # one prefetch at most this many samples (64 MB of floats)
_M_PER_DEG = 111_320.0


@dataclass
class _Grid:
    """One fetched window: pixel (i, j) has its centre at
    ``lon_w + (i + .5) * dlon``, ``lat_n - (j + .5) * dlat``."""

    lat_n: float
    lon_w: float
    dlat: float
    dlon: float
    values: np.ndarray            # (rows, cols) float32 metres

    def holds(self, lat: float, lon: float) -> bool:
        """Whether the bilinear neighbours of the point are all inside."""
        gx = (lon - self.lon_w) / self.dlon - 0.5
        gy = (self.lat_n - lat) / self.dlat - 0.5
        rows, cols = self.values.shape
        return 0.0 <= gx <= cols - 1 and 0.0 <= gy <= rows - 1

    def sample(self, lat: float, lon: float) -> float:
        gx = (lon - self.lon_w) / self.dlon - 0.5
        gy = (self.lat_n - lat) / self.dlat - 0.5
        rows, cols = self.values.shape
        i0 = min(max(int(math.floor(gx)), 0), cols - 2) if cols > 1 else 0
        j0 = min(max(int(math.floor(gy)), 0), rows - 2) if rows > 1 else 0
        fx = min(max(gx - i0, 0.0), 1.0) if cols > 1 else 0.0
        fy = min(max(gy - j0, 0.0), 1.0) if rows > 1 else 0.0
        v = self.values
        i1, j1 = min(i0 + 1, cols - 1), min(j0 + 1, rows - 1)
        corners = (v[j0, i0], v[j0, i1], v[j1, i0], v[j1, i1])
        if min(corners) < NODATA:
            raise DemError("IGN RGE ALTI has no elevation here (outside France, or at sea)")
        top = corners[0] * (1 - fx) + corners[1] * fx
        bottom = corners[2] * (1 - fx) + corners[3] * fx
        return float(top * (1 - fy) + bottom * fy)


def ign_getmap_url(lat_s: float, lon_w: float, lat_n: float, lon_e: float, width: int, height: int) -> str:
    """WMS 1.3.0 GetMap in EPSG:4326 -- whose axis order is latitude first."""
    return (f"{IGN_WMS}?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&LAYERS={IGN_LAYER}&STYLES="
            f"&CRS=EPSG:4326&BBOX={lat_s:.9f},{lon_w:.9f},{lat_n:.9f},{lon_e:.9f}"
            f"&WIDTH={width}&HEIGHT={height}&FORMAT=image/x-bil;bits=32")


class IgnAltiDem:
    """Elevation at any latitude and longitude in France from IGN's RGE
    ALTI (1 m), fetched by area: :meth:`prefetch` takes the box a command
    needs in as few requests as fit, :meth:`elevation` samples bilinearly
    and fetches a small window for a point outside what it holds. The
    same three things :class:`Dem` offers, so the commands take either."""

    def __init__(self, source: DemSource = IGN_RGE_ALTI, resolution_m: float = 1.0,
                 fetch=fetch_url) -> None:
        self.source = source
        self.resolution_m = float(resolution_m)
        self.fetch = fetch
        self.downloads = 0
        self._grids: list[_Grid] = []
        self._used_m = self.resolution_m

    def metres_per_pixel(self, lat: float) -> float:
        """The grid step actually fetched (coarser than 1 m for a large area)."""
        return self._used_m

    def _get(self, lat_s: float, lon_w: float, lat_n: float, lon_e: float,
             width: int, height: int) -> _Grid:
        url = ign_getmap_url(lat_s, lon_w, lat_n, lon_e, width, height)
        try:
            data = self.fetch(url)
        except TileError as exc:
            raise DemError(str(exc)) from exc
        self.downloads += 1
        values = np.frombuffer(data, dtype="<f4")
        if values.size != width * height:
            text = data[:200].decode("utf-8", "replace").strip()
            raise DemError(f"IGN RGE ALTI answered something else than elevations: {text}")
        grid = _Grid(lat_n, lon_w, (lat_n - lat_s) / height, (lon_e - lon_w) / width,
                     values.reshape(height, width).astype(np.float32))
        self._grids.append(grid)
        return grid

    def prefetch(self, lat_s: float, lon_w: float, lat_n: float, lon_e: float) -> tuple[int, int]:
        """Fetch the box (plus two samples of margin) at the finest step
        that keeps it under :data:`MAX_AREA_PX`; returns ``(requests,
        downloaded)`` like :meth:`Dem.prefetch`."""
        lat_c = (lat_s + lat_n) / 2.0
        m_lon = _M_PER_DEG * max(math.cos(math.radians(lat_c)), 1e-6)
        height_m = max((lat_n - lat_s) * _M_PER_DEG, 1.0)
        width_m = max((lon_e - lon_w) * m_lon, 1.0)
        step = max(self.resolution_m, math.sqrt(width_m * height_m / MAX_AREA_PX))
        self._used_m = step
        dlat, dlon = step / _M_PER_DEG, step / m_lon
        lat_s, lat_n = lat_s - 2 * dlat, lat_n + 2 * dlat
        lon_w, lon_e = lon_w - 2 * dlon, lon_e + 2 * dlon
        cols = max(2, math.ceil((lon_e - lon_w) / dlon))
        rows = max(2, math.ceil((lat_n - lat_s) / dlat))
        before = self.downloads
        requests = 0
        for r0 in range(0, rows, MAX_SIDE_PX):
            for c0 in range(0, cols, MAX_SIDE_PX):
                h = min(MAX_SIDE_PX, rows - r0) + (1 if r0 + MAX_SIDE_PX < rows else 0)
                w = min(MAX_SIDE_PX, cols - c0) + (1 if c0 + MAX_SIDE_PX < cols else 0)
                n = lat_n - r0 * dlat
                west = lon_w + c0 * dlon
                self._get(n - h * dlat, west, n, west + w * dlon, max(w, 2), max(h, 2))
                requests += 1
        return requests, self.downloads - before

    def elevation(self, lat: float, lon: float) -> float:
        """Metres in NGF-IGN69 (IGN78 in Corsica)."""
        for grid in reversed(self._grids):
            if grid.holds(lat, lon):
                return grid.sample(lat, lon)
        # outside what was prefetched: a 16-sample window around the point
        lat_c = math.radians(lat)
        dlat = self._used_m / _M_PER_DEG
        dlon = self._used_m / (_M_PER_DEG * max(math.cos(lat_c), 1e-6))
        grid = self._get(lat - 8 * dlat, lon - 8 * dlon, lat + 8 * dlat, lon + 8 * dlon, 16, 16)
        return grid.sample(lat, lon)


def default_dem(georef=None):
    """The DEM the commands use: the source and zoom from Options -- and,
    unless Options name another, IGN's RGE ALTI for a drawing in a French
    coordinate system."""
    from . import prefs

    if prefs.dem_is_ign(georef):
        return IgnAltiDem()
    return Dem(TileStore(prefs.dem_source()), prefs.dem_zoom())
