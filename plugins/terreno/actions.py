# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Terrain plugin, headless: the drawing's georeference and the
conversions the tools need. Every mutation is a Command; what lands in
the drawing is plain DXF (a POINT and a TEXT on their layer, XDATA under
``INGECAD``), and the declaration itself lives in ``core.georef``."""
from __future__ import annotations

import math
from pathlib import Path

from core.actions import AddEntityCommand
from core.commands import Command, CompositeCommand
from core.georef import Georef, SetGeorefCommand, read_georef
from core.i18n import tr
from core.layers import NewLayerCommand
from core.xdata import APPID, ensure_appid

from . import datum

GEO_TAG = "GEO-POINT"
LAYERS = {"geo": ("TERRENO-GEO", 6)}


def georef_of(document) -> Georef | None:
    return read_georef(document.doc)


def set_georef(document, georef: Georef | None) -> SetGeorefCommand:
    """Declare ``georef`` (None removes it), undoably."""
    return SetGeorefCommand(georef)


def describe(georef: Georef) -> str:
    """``WGS84, UTM zone 19 S`` in the interface language -- and, for a
    datum that has one, its shift."""
    if georef.datum == "WGS84":
        return tr("{datum}, UTM zone {zone}", datum=georef.datum, zone=georef.zone_label())
    dx, dy, dz = georef.shift
    return tr("{datum}, UTM zone {zone} (shift to WGS84 {dx:g}, {dy:g}, {dz:g} m)",
              datum=georef.datum, zone=georef.zone_label(), dx=dx, dy=dy, dz=dz)


def latlon_of(document, point) -> tuple[float, float]:
    """WGS84 latitude and longitude of a drawing point."""
    georef = georef_of(document)
    if georef is None:
        raise ValueError("the drawing is not georeferenced")
    return datum.drawing_to_latlon(georef, float(point[0]), float(point[1]))


def drawing_point(document, lat: float, lon: float) -> tuple[float, float]:
    """The drawing point (its own datum and zone) of a WGS84 lat/lon."""
    georef = georef_of(document)
    if georef is None:
        raise ValueError("the drawing is not georeferenced")
    return datum.latlon_to_drawing(georef, lat, lon)


def layer_commands(document, kinds=("geo",)) -> list[Command]:
    out = []
    for kind in kinds:
        name, color = LAYERS[kind]
        if name not in document.doc.layers:
            out.append(NewLayerCommand(name, color=color))
    return out


def mark_point(document, point, lat: float, lon: float, text_height: float = 1.0) -> CompositeCommand:
    """A POINT at ``point`` (something to snap to) and a TEXT with the
    geographic coordinates beside it, on TERRENO-GEO; the latitude and
    longitude ride in the point's XDATA."""
    label = datum.format_dms(lat, lon)

    def make_point(msp):
        ensure_appid(msp.doc)
        entity = msp.add_point((float(point[0]), float(point[1]), 0.0))
        entity.set_xdata(APPID, [(1000, GEO_TAG), (1040, float(lat)), (1040, float(lon))])
        return entity

    def make_text(msp):
        entity = msp.add_text(label, height=text_height)
        entity.set_placement((point[0] + text_height * 0.5, point[1] + text_height * 0.5))
        return entity

    layer = LAYERS["geo"][0]
    return CompositeCommand("geographic point", layer_commands(document) + [
        AddEntityCommand("GEO-POINT", make_point, layer=layer),
        AddEntityCommand("GEO-LABEL", make_text, layer=layer)])


def geo_points(document) -> list:
    """The POINTs LATLON marked, with ``(entity, lat, lon)``."""
    out = []
    for entity in document.doc.modelspace().query("POINT"):
        if not entity.has_xdata(APPID):
            continue
        values = [value for _code, value in entity.get_xdata(APPID)]
        if values and values[0] == GEO_TAG and len(values) >= 3:
            out.append((entity, float(values[1]), float(values[2])))
    return out


# -- G2: elevations from the DEM ---------------------------------------------------------------

DEM_TAG = "DEM-POINT"
LAYERS["dem"] = ("TERRENO-DEM", 8)


def topography():
    """The Topography plugin's actions -- the loaded plugin when it is on
    (one instance, the one the window uses), the package otherwise (the
    suite); None when neither imports."""
    import importlib
    import sys

    module = sys.modules.get("ingecad_plugin_topografia.actions")
    if module is not None:
        return module
    try:
        return importlib.import_module("plugins.topografia.actions")
    except ImportError:
        return None


def grid_points(polygon, spacing: float) -> list[tuple[float, float]]:
    """The nodes of a grid of ``spacing`` (aligned to multiples of it, so
    two runs on overlapping lots share their points) that fall inside
    the polygon."""
    from core.hatch_boundary import point_in_polygon

    if spacing <= 0 or len(polygon) < 3:
        return []
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    x0 = math.floor(min(xs) / spacing) * spacing
    y0 = math.floor(min(ys) / spacing) * spacing
    out = []
    y = y0
    while y <= max(ys) + 1e-9:
        x = x0
        while x <= max(xs) + 1e-9:
            if point_in_polygon(polygon, (x, y)):
                out.append((x, y))
            x += spacing
        y += spacing
    return out


def bbox_latlon(georef: Georef, points) -> tuple[float, float, float, float]:
    """``(lat_s, lon_w, lat_n, lon_e)`` of drawing points."""
    lats, lons = [], []
    for x, y in points:
        lat, lon = datum.drawing_to_latlon(georef, x, y)
        lats.append(lat)
        lons.append(lon)
    return min(lats), min(lons), max(lats), max(lons)


def dem_elevations(document, dem, points) -> list[tuple[float, float, float]]:
    """Each drawing point with its DEM elevation; fetches what it needs."""
    georef = georef_of(document)
    if georef is None:
        raise ValueError("the drawing is not georeferenced")
    if not points:
        return []
    dem.prefetch(*bbox_latlon(georef, points))
    out = []
    for x, y in points:
        lat, lon = datum.drawing_to_latlon(georef, x, y)
        out.append((x, y, dem.elevation(lat, lon)))
    return out


def dem_points(document, samples, source_id: str) -> CompositeCommand:
    """One POINT per sample, at its elevation, on TERRENO-DEM, tagged with
    the source: what TIN takes as it is."""
    def factory(x, y, z):
        def make(msp):
            ensure_appid(msp.doc)
            entity = msp.add_point((x, y, z))
            entity.set_xdata(APPID, [(1000, DEM_TAG), (1000, source_id)])
            return entity
        return make

    layer = LAYERS["dem"][0]
    commands = layer_commands(document, ("dem",))
    commands += [AddEntityCommand("DEM-POINT", factory(x, y, z), layer=layer) for x, y, z in samples]
    return CompositeCommand("DEM points", commands)


def honesty(dem, lat: float) -> str:
    """What every DEM command says at the end: where the numbers come
    from and how coarse they are."""
    return tr("Elevations from {source}: about {pixel:.0f} m per pixel over {data:.0f} m data. "
              "For preliminary design only, never for a survey.",
              source=dem.source.name, pixel=dem.metres_per_pixel(lat),
              data=dem.source.data_resolution_m)


class DemSurface:
    """What the profile needs from a surface -- ``z_at`` -- straight from
    the DEM through the drawing's georeference, so DEMPROFILE draws the
    ground without a survey and without a TIN in the drawing."""

    def __init__(self, dem, georef: Georef, name: str = "DEM") -> None:
        self.dem = dem
        self.georef = georef
        self.name = name

    def z_at(self, x: float, y: float) -> float:
        lat, lon = datum.drawing_to_latlon(self.georef, x, y)
        return self.dem.elevation(lat, lon)


# -- G3: the satellite image under the plan ------------------------------------------------------

SAT_TAG = "SAT-IMAGE"
LAYERS["sat"] = ("TERRENO-SAT", 7)


def image_path(document, source_id: str, extension: str):
    """Where the image file goes: beside the drawing, named after it and
    the source, never over an existing file; an unsaved drawing keeps it
    under the cache folder until it has a home (the path is absolute, so
    the reference survives a Save As anywhere)."""
    from core.recent import cache_dir

    if getattr(document, "path", None):
        # absolute on purpose: a drawing opened as "capturas/x.dwg" would
        # otherwise reference "capturas/x-....jpg", which another CAD reads
        # relative to ITS working folder, not the drawing's
        home = Path(document.path).resolve()
        folder, stem = home.parent, home.stem
    else:
        folder, stem = cache_dir() / "satimage", "untitled"
    folder.mkdir(parents=True, exist_ok=True)
    base = f"{stem}-{source_id}"
    candidate = folder / f"{base}{extension}"
    n = 2
    while candidate.exists():
        candidate = folder / f"{base}-{n}{extension}"
        n += 1
    return candidate


def is_satellite(entity) -> bool:
    if entity.dxftype() != "IMAGE" or not entity.has_xdata(APPID):
        return False
    values = [v for _c, v in entity.get_xdata(APPID)]
    return bool(values) and values[0] == SAT_TAG


def insert_satellite(document, placement, path, polygon, clip: bool, source,
                     text_height: float | None = None) -> CompositeCommand:
    """The image file written, then one undo step: the IMAGE on
    TERRENO-SAT (clipped to the polygon when asked, transparent outside
    it), the attribution the licence asks for as TEXT beside it, and the
    image sent to the back so the plan stays on top."""
    from core.actions import attach_image
    from core.commands import DeferredCommand
    from core.draworder import DrawOrderCommand
    from . import imagery

    imagery.save(placement, path)
    layer = LAYERS["sat"][0]
    attach = attach_image(str(path), (placement.width, placement.height), placement.insert,
                          placement.pixel_size)
    attach.layer = layer

    def tag(_document):
        from ezdxf.entities import Image

        entity = attach.entity
        ensure_appid(entity.doc)
        entity.set_xdata(APPID, [(1000, SAT_TAG), (1000, source.id), (1070, int(placement.zoom)),
                                 (1040, float(placement.pixel_size))])
        if clip:
            entity.set_boundary_path(placement.clip_boundary(polygon))
            entity.dxf.flags |= Image.USE_CLIPPING_BOUNDARY
        if placement.image.mode == "RGBA":
            entity.dxf.flags |= Image.USE_TRANSPARENCY
        return None

    height = text_height or max(0.5, 0.02 * min(placement.width, placement.height) * placement.pixel_size)
    caption = tr("Imagery: {attribution}", attribution=source.attribution)

    def make_text(msp):
        entity = msp.add_text(caption, height=height)
        entity.set_placement((placement.insert[0] + height, placement.insert[1] + height))
        return entity

    def send_back(_document):
        return DrawOrderCommand([attach.entity], "back")

    return CompositeCommand("satellite image", layer_commands(document, ("sat",)) + [
        attach,
        DeferredCommand("clip and tag", tag),
        AddEntityCommand("SAT-CAPTION", make_text, layer=layer),
        DeferredCommand("send to back", send_back),
    ])


# -- G4: to and from Google Earth ------------------------------------------------------------------

KML_TAG = "KML"
LAYERS["kml"] = ("TERRENO-KML", 7)


def entity_rgb(document, entity) -> tuple[int, int, int]:
    """The colour the entity shows: its true colour, else its ACI, else
    its layer's -- as RGB, which is what a KML wants."""
    from ezdxf import colors as ezcolors

    rgb = entity.rgb
    if rgb is not None:
        return tuple(int(c) for c in rgb)
    aci = entity.dxf.get("color", 256)
    if aci in (0, 256) or aci is None:
        layers = document.doc.layers
        layer = layers.get(entity.dxf.layer) if entity.dxf.layer in layers else None
        aci = abs(int(layer.color)) if layer is not None else 7
    if not 1 <= int(aci) <= 255:
        aci = 7
    return tuple(int(c) for c in ezcolors.aci2rgb(int(aci)))


def _kml_xdata(entity) -> tuple[str, str, str]:
    """(name, description, folder) a KML import left on the entity."""
    if entity.has_xdata(APPID):
        values = [v for _c, v in entity.get_xdata(APPID)]
        if values and values[0] == KML_TAG:
            return (str(values[1]) if len(values) > 1 else "",
                    str(values[2]) if len(values) > 2 else "",
                    str(values[3]) if len(values) > 3 else "")
    return "", "", ""


def _flat_vertices(entity) -> list[tuple[float, float, float]]:
    """A curve's vertices for a KML: arcs flattened to 5 cm, Z kept."""
    import ezdxf.path

    kind = entity.dxftype()
    if kind == "LINE":
        s, e = entity.dxf.start, entity.dxf.end
        return [(s.x, s.y, s.z), (e.x, e.y, e.z)]
    if kind == "POLYLINE" and entity.is_3d_polyline:
        return [(v.dxf.location.x, v.dxf.location.y, v.dxf.location.z) for v in entity.vertices]
    path = ezdxf.path.make_path(entity)
    return [(p.x, p.y, p.z) for p in path.flattening(0.05)]


def _is_closed(entity) -> bool:
    kind = entity.dxftype()
    if kind in ("CIRCLE", "ELLIPSE"):
        return kind == "CIRCLE" or abs(entity.dxf.end_param - entity.dxf.start_param) >= 2 * math.pi - 1e-9
    if kind == "LWPOLYLINE":
        return bool(entity.closed)
    if kind == "POLYLINE":
        return bool(entity.is_closed)
    return False


def kml_features(document, entities) -> tuple[list, int]:
    """The entities as KML features (WGS84), and how many could not go:
    points (named as the surveyor named them), lines and polylines
    (arcs flattened), circles and closed polylines as polygons, texts as
    named points. The description says the layer, and an area or a
    length."""
    from core.hatch_boundary import polygon_area
    from . import kml as kml_mod

    georef = georef_of(document)
    if georef is None:
        raise ValueError("the drawing is not georeferenced")
    topo = topography()
    features, skipped = [], 0

    def latlon(x, y, z=0.0):
        lat, lon = datum.drawing_to_latlon(georef, float(x), float(y))
        return (lat, lon, float(z))

    for entity in entities:
        kind = entity.dxftype()
        name, description, folder = _kml_xdata(entity)
        color = entity_rgb(document, entity)
        layer_note = tr("Layer {layer}", layer=entity.dxf.layer)
        if kind == "POINT":
            loc = entity.dxf.location
            if topo is not None and topo.is_survey_point(entity):
                point = topo.survey_point(entity)
                name, description = name or point.name, description or point.desc
            features.append(kml_mod.Feature("point", [latlon(loc.x, loc.y, loc.z)], name,
                                            description or layer_note, color, [], folder))
        elif kind in ("TEXT", "MTEXT"):
            insert = entity.dxf.insert
            text = entity.plain_text() if kind == "MTEXT" else entity.dxf.text
            features.append(kml_mod.Feature("point", [latlon(insert.x, insert.y, insert.z)],
                                            name or text, description or layer_note, color, [], folder))
        elif kind in ("LINE", "LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC", "ELLIPSE", "SPLINE"):
            try:
                verts = _flat_vertices(entity)
            except Exception:
                skipped += 1
                continue
            if len(verts) < 2:
                skipped += 1
                continue
            closed = _is_closed(entity)
            if closed and len(verts) > 2 and abs(verts[0][0] - verts[-1][0]) < 1e-9 \
                    and abs(verts[0][1] - verts[-1][1]) < 1e-9:
                verts = verts[:-1]
            coords = [latlon(*v) for v in verts]
            if closed and len(coords) >= 3:
                flat = [(v[0], v[1]) for v in verts]
                per = sum(math.hypot(flat[(i + 1) % len(flat)][0] - flat[i][0],
                                     flat[(i + 1) % len(flat)][1] - flat[i][1]) for i in range(len(flat)))
                note = description or tr("{layer_note}. Area {area:.2f} m², perimeter {per:.2f} m",
                                         layer_note=layer_note, area=polygon_area(flat), per=per)
                features.append(kml_mod.Feature("polygon", coords, name, note, color, [], folder))
            else:
                length = sum(math.hypot(verts[i + 1][0] - verts[i][0], verts[i + 1][1] - verts[i][1])
                             for i in range(len(verts) - 1))
                note = description or tr("{layer_note}. Length {length:.2f} m",
                                         layer_note=layer_note, length=length)
                features.append(kml_mod.Feature("line", coords, name, note, color, [], folder))
        else:
            skipped += 1
    return features, skipped


def export_kmz(document, entities, path, name: str = "IngeCAD") -> tuple[int, int]:
    """Write the entities to ``path`` (.kmz or .kml); (written, skipped)."""
    from . import kml as kml_mod

    features, skipped = kml_features(document, entities)
    if features:
        kml_mod.write_file(path, features, name)
    return len(features), skipped


def import_features(document, features, text_height: float = 1.0) -> CompositeCommand:
    """KML features -> plain entities on TERRENO-KML, one undo step: a
    point is a POINT with its name as TEXT beside it, a line an
    LWPOLYLINE (a 3D POLYLINE when it carries altitudes), a polygon a
    closed LWPOLYLINE with each hole as another; the colour goes on the
    entity as true colour, name, description and folder in XDATA."""
    georef = georef_of(document)
    if georef is None:
        raise ValueError("the drawing is not georeferenced")
    layer = LAYERS["kml"][0]

    def xy(coord):
        return datum.latlon_to_drawing(georef, coord[0], coord[1])

    def tags(f, suffix: str = ""):
        return [(1000, KML_TAG), (1000, (f.name + suffix)[:255]), (1000, f.description[:255]),
                (1000, f.folder[:255])]

    def paint(entity, f):
        if f.color is not None:
            entity.rgb = tuple(int(c) for c in f.color)

    commands = layer_commands(document, ("kml",))
    for f in features:
        if f.kind == "point":
            x, y = xy(f.coords[0])
            z = f.coords[0][2]

            def make_point(msp, f=f, x=x, y=y, z=z):
                ensure_appid(msp.doc)
                entity = msp.add_point((x, y, z))
                entity.set_xdata(APPID, tags(f))
                paint(entity, f)
                return entity
            commands.append(AddEntityCommand("KML-POINT", make_point, layer=layer))
            if f.name:
                def make_label(msp, f=f, x=x, y=y):
                    entity = msp.add_text(f.name, height=text_height)
                    entity.set_placement((x + text_height * 0.5, y + text_height * 0.5))
                    paint(entity, f)
                    return entity
                commands.append(AddEntityCommand("KML-LABEL", make_label, layer=layer))
        elif f.kind == "line":
            pts = [xy(c) + (c[2],) for c in f.coords]
            three_d = any(abs(p[2]) > 1e-9 for p in pts) and len({round(p[2], 3) for p in pts}) > 1

            def make_line(msp, f=f, pts=pts, three_d=three_d):
                ensure_appid(msp.doc)
                if three_d:
                    entity = msp.add_polyline3d(pts)
                else:
                    entity = msp.add_lwpolyline([(p[0], p[1]) for p in pts],
                                                dxfattribs={"elevation": pts[0][2]})
                entity.set_xdata(APPID, tags(f))
                paint(entity, f)
                return entity
            commands.append(AddEntityCommand("KML-LINE", make_line, layer=layer))
        else:
            rings = [(f.coords, "")] + [(hole, tr(" (hole)")) for hole in f.holes]
            for ring, suffix in rings:
                pts = [xy(c) for c in ring]

                def make_ring(msp, f=f, pts=pts, suffix=suffix):
                    ensure_appid(msp.doc)
                    entity = msp.add_lwpolyline(pts, close=True)
                    entity.set_xdata(APPID, tags(f, suffix))
                    paint(entity, f)
                    return entity
                commands.append(AddEntityCommand("KML-POLYGON", make_ring, layer=layer))
    return CompositeCommand("KML import", commands)


def overlay_quad(georef: Georef, e0: float, n0: float, e1: float, n1: float) -> list:
    """The rectangle's corners as (lat, lon), SW, SE, NE, NW -- the order
    a gx:LatLonQuad wants."""
    return [datum.drawing_to_latlon(georef, x, y) for x, y in ((e0, n0), (e1, n0), (e1, n1), (e0, n1))]


def render_overlay(document, e0: float, n0: float, e1: float, n1: float,
                   width_px: int) -> tuple[bytes, int, int]:
    """The model space inside the rectangle as a PNG with a transparent
    background, north up, ``width_px`` wide; (bytes, width, height)."""
    from PySide6.QtCore import QBuffer, QIODevice, QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    from formats.pdf_out import build_graphics_scene

    width_px = max(16, min(int(width_px), 8192))
    height_px = max(16, int(round(width_px * (n1 - n0) / (e1 - e0))))
    scene = build_graphics_scene(document, "Model")
    scene.setBackgroundBrush(Qt.NoBrush)                  # the terrain shows through
    image = QImage(width_px, height_px, QImage.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        # the scene keeps world Y (north up) and Qt paints Y down: flip
        painter.translate(0, height_px)
        painter.scale(1, -1)
        scene.render(painter, QRectF(0, 0, width_px, height_px), QRectF(e0, n0, e1 - e0, n1 - n0),
                     Qt.IgnoreAspectRatio)
    finally:
        painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data()), width_px, height_px
