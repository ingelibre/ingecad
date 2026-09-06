# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A satellite image under the plan: the tiles of a licensed source,
mosaicked in Web Mercator and resampled into the drawing's own UTM grid.

Resampling is the point. A mosaic of tiles is a rectangle in Mercator and
a slightly rotated, slightly stretched one in UTM; instead of explaining
that to an IMAGE entity (which can rotate but never shear) the pixels are
re-drawn on a grid of the drawing's coordinates, so the image lands
axis-aligned at one known metre per pixel and its corners are exactly
where the maths says. The mapping is evaluated exactly on a lattice and
bilinearly in between (PIL's MESH transform), which at a cell of 64
pixels is far below the source's own georeferencing error.
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass

from core.georef import Georef

from . import datum
from .tiles import TILE_PX, TileCache, TileError, deg2num, metres_per_pixel

#: More than this many tiles is a zoom or an area nobody meant.
MAX_TILES = 400
CELL_PX = 64


@dataclass
class Placement:
    """What comes out: the pixels (row 0 = north) and where they go."""

    image: object                      # PIL.Image, RGB or RGBA when clipped
    insert: tuple[float, float]        # lower-left corner, drawing coordinates
    pixel_size: float                  # metres per pixel, square
    zoom: int
    tiles: int

    @property
    def width(self) -> int:
        return self.image.size[0]

    @property
    def height(self) -> int:
        return self.image.size[1]

    @property
    def top(self) -> float:
        return self.insert[1] + self.height * self.pixel_size

    def to_pixel(self, x: float, y: float) -> tuple[float, float]:
        """Drawing point -> image pixel coordinates (origin top-left, y
        down, edges at integers)."""
        return (x - self.insert[0]) / self.pixel_size, (self.top - y) / self.pixel_size

    def clip_boundary(self, polygon) -> list[tuple[float, float]]:
        """The polygon as an IMAGE clip boundary: DXF puts pixel centres at
        integers there, so half a pixel off the edge convention."""
        return [(px - 0.5, py - 0.5) for px, py in (self.to_pixel(x, y) for x, y in polygon)]


def _frame(georef: Georef, polygon, zoom: int):
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    e0, e1, n0, n1 = min(xs), max(xs), min(ys), max(ys)
    lat_c, _lon = datum.drawing_to_latlon(georef, (e0 + e1) / 2, (n0 + n1) / 2)
    res = metres_per_pixel(lat_c, zoom)
    width = max(1, math.ceil((e1 - e0) / res))
    height = max(1, math.ceil((n1 - n0) / res))
    return e0, n0, n1, res, width, height


def _mercator_px(georef: Georef, x: float, y: float, zoom: int) -> tuple[float, float]:
    lat, lon = datum.drawing_to_latlon(georef, x, y)
    tx, ty = deg2num(lat, lon, zoom)
    return tx * TILE_PX, ty * TILE_PX


def _lattice(georef: Georef, e0: float, n1: float, res: float, width: int, height: int, zoom: int):
    """The exact Mercator pixel of every lattice node, with the node's
    output pixel position; cells of about CELL_PX."""
    nx, ny = max(1, math.ceil(width / CELL_PX)), max(1, math.ceil(height / CELL_PX))
    cols = [round(i * width / nx) for i in range(nx + 1)]
    rows = [round(j * height / ny) for j in range(ny + 1)]
    nodes = {}
    for j, py in enumerate(rows):
        for i, px in enumerate(cols):
            nodes[(i, j)] = _mercator_px(georef, e0 + px * res, n1 - py * res, zoom)
    return cols, rows, nodes


def plan(georef: Georef, polygon, zoom: int) -> dict:
    """Everything decided before a byte is fetched: the frame in the
    drawing, and which tiles the Mercator side needs."""
    e0, n0, n1, res, width, height = _frame(georef, polygon, zoom)
    cols, rows, nodes = _lattice(georef, e0, n1, res, width, height, zoom)
    gxs = [g[0] for g in nodes.values()]
    gys = [g[1] for g in nodes.values()]
    n = 2 ** zoom
    tx0, tx1 = int(math.floor(min(gxs) / TILE_PX)), int(math.floor(max(gxs) / TILE_PX))
    ty0, ty1 = int(math.floor(min(gys) / TILE_PX)), int(math.floor(max(gys) / TILE_PX))
    tiles = [(x, y) for x in range(tx0, tx1 + 1) for y in range(ty0, ty1 + 1)
             if 0 <= x < n and 0 <= y < n]
    return {"e0": e0, "n0": n0, "n1": n1, "res": res, "width": width, "height": height,
            "cols": cols, "rows": rows, "nodes": nodes, "tiles": tiles, "tx0": tx0, "ty0": ty0}


def tile_count(georef: Georef, polygon, zoom: int) -> int:
    return len(plan(georef, polygon, zoom)["tiles"])


def satellite_image(georef: Georef, polygon, zoom: int, cache: TileCache,
                    clip: bool = True, progress=None) -> Placement:
    """The tiles fetched, mosaicked and resampled into the drawing's grid;
    ``clip`` makes the pixels outside the polygon transparent (RGBA)."""
    from PIL import Image, ImageDraw

    p = plan(georef, polygon, zoom)
    tiles = p["tiles"]
    if len(tiles) > MAX_TILES:
        raise TileError(f"{len(tiles)} tiles at zoom {zoom}: lower the zoom or shrink the area")
    tx0, ty0 = p["tx0"], p["ty0"]
    ntx = max(x for x, _y in tiles) - tx0 + 1
    nty = max(y for _x, y in tiles) - ty0 + 1
    mosaic = Image.new("RGB", (ntx * TILE_PX, nty * TILE_PX), (0, 0, 0))
    for k, (x, y) in enumerate(tiles):
        data = cache.bytes(zoom, x, y)
        try:
            with Image.open(io.BytesIO(data)) as tile:
                mosaic.paste(tile.convert("RGB"), ((x - tx0) * TILE_PX, (y - ty0) * TILE_PX))
        except Exception as exc:
            cache.forget(zoom, x, y)
            raise TileError(f"{cache.source.url(zoom, x, y)}: not an image ({exc})") from exc
        if progress is not None:
            progress(k + 1, len(tiles))
    ox, oy = tx0 * TILE_PX, ty0 * TILE_PX
    cols, rows, nodes = p["cols"], p["rows"], p["nodes"]
    mesh = []
    for j in range(len(rows) - 1):
        for i in range(len(cols) - 1):
            if cols[i + 1] <= cols[i] or rows[j + 1] <= rows[j]:
                continue
            nw, sw = nodes[(i, j)], nodes[(i, j + 1)]
            se, ne = nodes[(i + 1, j + 1)], nodes[(i + 1, j)]
            quad = (nw[0] - ox, nw[1] - oy, sw[0] - ox, sw[1] - oy,
                    se[0] - ox, se[1] - oy, ne[0] - ox, ne[1] - oy)
            mesh.append(((cols[i], rows[j], cols[i + 1], rows[j + 1]), quad))
    width, height = p["width"], p["height"]
    out = mosaic.transform((width, height), Image.Transform.MESH, mesh, Image.Resampling.BILINEAR)
    placement = Placement(out, (p["e0"], p["n0"]), p["res"], zoom, len(tiles))
    if clip:
        mask = Image.new("L", (width, height), 0)
        ImageDraw.Draw(mask).polygon([placement.to_pixel(x, y) for x, y in polygon], fill=255)
        out = out.convert("RGBA")
        out.putalpha(mask)
        placement.image = out
    return placement


def save(placement: Placement, path) -> None:
    """JPEG when opaque (the DWG's companion everybody expects), PNG when
    the clip needs an alpha channel."""
    if placement.image.mode == "RGBA":
        placement.image.save(path, format="PNG", optimize=True)
    else:
        placement.image.save(path, format="JPEG", quality=90)


def file_extension(placement: Placement) -> str:
    return ".png" if placement.image.mode == "RGBA" else ".jpg"
