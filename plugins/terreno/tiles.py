# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Slippy-map tiles: the sources, the maths of the Web Mercator grid,
and one cache that fetches a tile once and keeps it on disk. The DEM
(G2) and the satellite imagery (G3) both ride on this -- one answer to
"how do I get tile z/x/y".

Ported from IngeTrazo's ``georef/tiles.py`` and ``tile_fetcher.py`` minus
Qt: ``urllib`` with a real User-Agent (OpenStreetMap's tile policy asks
for one), atomic writes, and a swappable ``fetch`` so the suite serves
synthetic tiles. The shipped presets are all licensed for this use; a
user's own XYZ template goes through :func:`custom_source`, where the
terms are the user's business. Google is never a preset.
"""
from __future__ import annotations

import math
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

TILE_PX = 256
MAX_LAT = 85.05112878          # the Web Mercator limit
_EARTH_CIRCUMFERENCE = 40075016.686


class TileError(Exception):
    """A tile could not be fetched or read; the message names it and why."""


@dataclass(frozen=True)
class TileSource:
    """A ``{z}/{x}/{y}`` URL template (any order: ArcGIS serves z/y/x) plus
    what the drawing must say about it."""

    id: str
    name: str
    url_template: str
    max_zoom: int = 19
    attribution: str = ""

    def url(self, z: int, x: int, y: int) -> str:
        return (self.url_template.replace("{z}", str(z)).replace("{x}", str(x))
                .replace("{y}", str(y)))

    @property
    def extension(self) -> str:
        """The cache file's extension, from the template (.png / .jpg / .bin)."""
        match = re.search(r"\.(png|jpe?g|webp)(?:\?|$)", self.url_template, re.IGNORECASE)
        return "." + match.group(1).lower() if match else ".bin"


PRESETS: dict[str, TileSource] = {
    "esri_imagery": TileSource(
        id="esri_imagery",
        name="Esri World Imagery",
        url_template="https://server.arcgisonline.com/ArcGIS/rest/services/"
                     "World_Imagery/MapServer/tile/{z}/{y}/{x}",
        max_zoom=19,
        attribution="Esri, Maxar, Earthstar Geographics, and the GIS User Community",
    ),
    "s2cloudless": TileSource(
        id="s2cloudless",
        name="Sentinel-2 cloudless (EOX)",
        url_template="https://tiles.maps.eox.at/wmts/1.0.0/"
                     "s2cloudless-2020_3857/default/GoogleMapsCompatible/{z}/{y}/{x}.jpg",
        max_zoom=17,
        attribution="Sentinel-2 cloudless by EOX IT Services GmbH, https://s2maps.eu "
                    "(contains modified Copernicus Sentinel data 2020)",
    ),
    "osm": TileSource(
        id="osm",
        name="OpenStreetMap",
        url_template="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        max_zoom=19,
        attribution="© OpenStreetMap contributors",
    ),
}

DEFAULT_SOURCE_ID = "esri_imagery"


def source_slug(name: str) -> str:
    """A filesystem-safe id for a user-named source (the cache folder)."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "fuente"


def custom_source(url_template: str, max_zoom: int = 19, name: str | None = None) -> TileSource:
    """A user-pasted XYZ template; the terms of use are the user's."""
    return TileSource(id="custom-" + source_slug(name) if name else "custom",
                      name=name or "custom XYZ tiles", url_template=url_template,
                      max_zoom=max_zoom, attribution="custom source (user-defined)")


# -- the Web Mercator grid ----------------------------------------------------------------

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


# -- fetching and caching --------------------------------------------------------------------

def _user_agent() -> str:
    try:
        from core.version import __version__
    except Exception:
        __version__ = "dev"
    return f"IngeCAD/{__version__} (+https://ingecad.org)"


def fetch_url(url: str, timeout: float = 20.0) -> bytes:
    """The bytes at ``url``, or a TileError that names the URL and the cause."""
    request = urllib.request.Request(url, headers={"User-Agent": _user_agent()})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise TileError(f"{url}: HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        reason = getattr(exc, "reason", None) or exc
        raise TileError(f"{url}: {reason}") from exc


def default_cache_dir() -> Path:
    from core.recent import cache_dir

    return cache_dir() / "tiles"


class TileCache:
    """The bytes of a source's tiles: the disk cache first, the network
    after, each tile written whole or not at all."""

    def __init__(self, source: TileSource, cache_dir: Optional[Path] = None,
                 fetch: Callable[[str], bytes] = fetch_url) -> None:
        self.source = source
        self.cache_dir = Path(cache_dir) if cache_dir is not None else default_cache_dir()
        self.fetch = fetch
        self.downloads = 0

    def path(self, z: int, x: int, y: int) -> Path:
        return self.cache_dir / self.source.id / str(z) / str(x) / f"{y}{self.source.extension}"

    def cached(self, z: int, x: int, y: int) -> bool:
        return self.path(z, x, y).is_file()

    def forget(self, z: int, x: int, y: int) -> None:
        """Drop a cached tile that turned out unreadable."""
        self.path(z, x, y).unlink(missing_ok=True)

    def bytes(self, z: int, x: int, y: int) -> bytes:
        path = self.path(z, x, y)
        if path.is_file():
            try:
                return path.read_bytes()
            except OSError:
                pass
        data = self.fetch(self.source.url(z, x, y))
        self.downloads += 1
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".part")
            tmp.write_bytes(data)
            os.replace(tmp, path)
        except OSError:
            pass                                       # the cache is a convenience
        return data
