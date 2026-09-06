# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""KML and KMZ, both ways -- the file Google Earth opens with a double
click. Pure: ``xml.etree`` and ``zipfile``, no GIS library, and no
coordinate system to argue about (KML is WGS84 longitude/latitude by
definition; the drawing's UTM comes and goes through the georeference).

What survives the trip: points, lines and polygons (holes included),
their names and descriptions, their colours (KML writes them as
``aabbggrr``), the altitude as a third coordinate. What a GroundOverlay
needs to lay a rendering of the plan on the terrain: the image and its
four corners as a ``gx:LatLonQuad``, so a UTM-aligned raster lands where
its corners really are, not in a lat/lon box that would be a touch off.

Grown from IngeTrazo's ``georef/geoimport.py`` (lines and polygons only).
"""
from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

KML_NS = "http://www.opengis.net/kml/2.2"
GX_NS = "http://www.google.com/kml/ext/2.2"

LatLon = tuple[float, float, float]        # (lat, lon, alt)


@dataclass
class Feature:
    kind: str                                   # "point" | "line" | "polygon"
    coords: list = field(default_factory=list)  # [(lat, lon, alt)]
    name: str = ""
    description: str = ""
    color: Optional[tuple[int, int, int]] = None
    holes: list = field(default_factory=list)   # a polygon's inner rings
    folder: str = ""


@dataclass
class Overlay:
    """A GroundOverlay: the image and where its corners go."""

    href: str
    quad: list                                  # [(lat, lon)] SW, SE, NE, NW
    opacity: float = 1.0
    name: str = ""


# -- colours -----------------------------------------------------------------------------------

def kml_color(rgb, alpha: int = 255) -> str:
    """``(r, g, b)`` -> KML's ``aabbggrr``."""
    r, g, b = (int(c) & 255 for c in rgb)
    return f"{int(alpha) & 255:02x}{b:02x}{g:02x}{r:02x}"


def parse_color(text: str) -> tuple[Optional[tuple[int, int, int]], int]:
    """``aabbggrr`` -> ``((r, g, b), alpha)``; ``(None, 255)`` when unreadable."""
    text = (text or "").strip().lstrip("#")
    if len(text) == 6:
        text = "ff" + text
    if len(text) != 8:
        return None, 255
    try:
        a, b, g, r = (int(text[i:i + 2], 16) for i in (0, 2, 4, 6))
    except ValueError:
        return None, 255
    return (r, g, b), a


# -- reading -------------------------------------------------------------------------------------

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(elem, name: str):
    for c in elem:
        if _local(c.tag) == name:
            return c
    return None


def _text(elem, name: str) -> str:
    c = _child(elem, name) if elem is not None else None
    return (c.text or "").strip() if c is not None and c.text else ""


def _coords(text: str) -> list[LatLon]:
    """``lon,lat[,alt]`` tokens, whitespace separated -> (lat, lon, alt)."""
    out = []
    for token in (text or "").split():
        parts = token.split(",")
        if len(parts) < 2:
            continue
        try:
            lon, lat = float(parts[0]), float(parts[1])
            alt = float(parts[2]) if len(parts) > 2 and parts[2] else 0.0
        except ValueError:
            continue
        out.append((lat, lon, alt))
    return out


def _ring(elem) -> list[LatLon]:
    """The coordinates of a LinearRing (inside a boundary element), the
    closing duplicate dropped."""
    for node in elem.iter():
        if _local(node.tag) == "coordinates":
            pts = _coords(node.text)
            if len(pts) > 1 and abs(pts[0][0] - pts[-1][0]) < 1e-12 and abs(pts[0][1] - pts[-1][1]) < 1e-12:
                pts = pts[:-1]
            return pts
    return []


def _style_colors(style) -> dict:
    """Which colour a Style gives points, lines and polygons."""
    out = {}
    for kind, tag in (("point", "IconStyle"), ("line", "LineStyle"), ("polygon", "PolyStyle")):
        node = _child(style, tag)
        if node is not None:
            rgb, _alpha = parse_color(_text(node, "color"))
            if rgb is not None:
                out[kind] = rgb
    if "polygon" not in out and "line" in out:
        out["polygon"] = out["line"]
    return out


def _collect_styles(root) -> dict:
    """``{style id: colours}``, StyleMaps resolved to their normal Style."""
    styles, maps = {}, {}
    for node in root.iter():
        tag = _local(node.tag)
        sid = node.get("id")
        if tag == "Style" and sid:
            styles[sid] = _style_colors(node)
        elif tag == "StyleMap" and sid:
            for pair in node:
                if _local(pair.tag) == "Pair" and _text(pair, "key") in ("normal", ""):
                    maps[sid] = _text(pair, "styleUrl").lstrip("#")
                    break
    for sid, target in maps.items():
        styles.setdefault(sid, styles.get(target, {}))
    return styles


def _geometries(elem, name, description, colors, folder, out):
    tag = _local(elem.tag)
    if tag == "Point":
        pts = _ring(elem)
        if pts:
            out.append(Feature("point", pts[:1], name, description, colors.get("point"), [], folder))
    elif tag == "LineString" or tag == "LinearRing":
        pts = _ring(elem) if tag == "LinearRing" else _coords(_text(elem, "coordinates"))
        if tag == "LinearRing" and len(pts) >= 3:
            out.append(Feature("polygon", pts, name, description, colors.get("polygon"), [], folder))
        elif len(pts) >= 2:
            out.append(Feature("line", pts, name, description, colors.get("line"), [], folder))
    elif tag == "Polygon":
        outer = _child(elem, "outerBoundaryIs")
        pts = _ring(outer) if outer is not None else []
        holes = [_ring(inner) for inner in elem if _local(inner.tag) == "innerBoundaryIs"]
        if len(pts) >= 3:
            out.append(Feature("polygon", pts, name, description, colors.get("polygon"),
                               [h for h in holes if len(h) >= 3], folder))
    elif tag == "MultiGeometry":
        for child in elem:
            _geometries(child, name, description, colors, folder, out)
    elif tag == "Track" or tag == "MultiTrack":
        pts = []
        for node in elem.iter():
            if _local(node.tag) == "coord" and node.text:
                parts = node.text.split()
                if len(parts) >= 2:
                    pts.append((float(parts[1]), float(parts[0]), float(parts[2]) if len(parts) > 2 else 0.0))
        if len(pts) >= 2:
            out.append(Feature("line", pts, name, description, colors.get("line"), [], folder))


def parse(text: str) -> list[Feature]:
    """Every Placemark's geometry, with its name, description, colour and
    the folder it sits in."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    styles = _collect_styles(root)
    out: list[Feature] = []

    def walk(elem, folder):
        tag = _local(elem.tag)
        if tag in ("Document", "Folder"):
            name = _text(elem, "name")
            here = "/".join(p for p in (folder, name) if p) if tag == "Folder" else folder
            for child in elem:
                walk(child, here)
            return
        if tag == "Placemark":
            name = _text(elem, "name")
            description = _text(elem, "description")
            colors = {}
            url = _text(elem, "styleUrl").lstrip("#")
            if url in styles:
                colors = dict(styles[url])
            inline = _child(elem, "Style")
            if inline is not None:
                colors.update(_style_colors(inline))
            for child in elem:
                _geometries(child, name, description, colors, folder, out)
            return
        for child in elem:
            walk(child, folder)

    walk(root, "")
    return out


def parse_file(path) -> list[Feature]:
    """A ``.kml``, or the ``doc.kml`` (first ``.kml``) inside a ``.kmz``."""
    path = Path(path)
    if path.suffix.lower() == ".kmz" or zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith(".kml")]
            if not names:
                return []
            name = "doc.kml" if "doc.kml" in names else names[0]
            return parse(archive.read(name).decode("utf-8", "replace"))
    return parse(path.read_text(encoding="utf-8", errors="replace"))


# -- writing -----------------------------------------------------------------------------------

def _fmt(pt) -> str:
    lat, lon = pt[0], pt[1]
    alt = pt[2] if len(pt) > 2 else 0.0
    return f"{lon:.9f},{lat:.9f},{alt:.3f}"          # 1e-9 deg is 0.1 mm


def _style_id(rgb) -> str:
    return "c%02x%02x%02x" % tuple(int(c) & 255 for c in rgb)


def write(features: list, name: str = "IngeCAD", overlay: Optional[Overlay] = None) -> str:
    """A KML document: one Style per colour, a Placemark per feature (all
    clamped to the ground: the altitude rides along for the trip back,
    but Google Earth must never bury a boundary under its own terrain),
    and the GroundOverlay if there is one."""
    ET.register_namespace("", KML_NS)
    ET.register_namespace("gx", GX_NS)
    root = ET.Element(f"{{{KML_NS}}}kml")
    doc = ET.SubElement(root, f"{{{KML_NS}}}Document")
    ET.SubElement(doc, f"{{{KML_NS}}}name").text = name
    seen = set()
    for f in features:
        if f.color is None or _style_id(f.color) in seen:
            continue
        seen.add(_style_id(f.color))
        style = ET.SubElement(doc, f"{{{KML_NS}}}Style", id=_style_id(f.color))
        line = ET.SubElement(style, f"{{{KML_NS}}}LineStyle")
        ET.SubElement(line, f"{{{KML_NS}}}color").text = kml_color(f.color)
        ET.SubElement(line, f"{{{KML_NS}}}width").text = "2"
        poly = ET.SubElement(style, f"{{{KML_NS}}}PolyStyle")
        ET.SubElement(poly, f"{{{KML_NS}}}color").text = kml_color(f.color, 0x40)
        icon = ET.SubElement(style, f"{{{KML_NS}}}IconStyle")
        ET.SubElement(icon, f"{{{KML_NS}}}color").text = kml_color(f.color)
    for f in features:
        pm = ET.SubElement(doc, f"{{{KML_NS}}}Placemark")
        if f.name:
            ET.SubElement(pm, f"{{{KML_NS}}}name").text = f.name
        if f.description:
            ET.SubElement(pm, f"{{{KML_NS}}}description").text = f.description
        if f.color is not None:
            ET.SubElement(pm, f"{{{KML_NS}}}styleUrl").text = "#" + _style_id(f.color)
        if f.kind == "point":
            geom = ET.SubElement(pm, f"{{{KML_NS}}}Point")
            ET.SubElement(geom, f"{{{KML_NS}}}altitudeMode").text = "clampToGround"
            ET.SubElement(geom, f"{{{KML_NS}}}coordinates").text = _fmt(f.coords[0])
        elif f.kind == "line":
            geom = ET.SubElement(pm, f"{{{KML_NS}}}LineString")
            ET.SubElement(geom, f"{{{KML_NS}}}tessellate").text = "1"
            ET.SubElement(geom, f"{{{KML_NS}}}altitudeMode").text = "clampToGround"
            ET.SubElement(geom, f"{{{KML_NS}}}coordinates").text = " ".join(_fmt(p) for p in f.coords)
        else:
            geom = ET.SubElement(pm, f"{{{KML_NS}}}Polygon")
            ET.SubElement(geom, f"{{{KML_NS}}}tessellate").text = "1"
            ET.SubElement(geom, f"{{{KML_NS}}}altitudeMode").text = "clampToGround"
            outer = ET.SubElement(ET.SubElement(geom, f"{{{KML_NS}}}outerBoundaryIs"), f"{{{KML_NS}}}LinearRing")
            ring = list(f.coords) + [f.coords[0]]
            ET.SubElement(outer, f"{{{KML_NS}}}coordinates").text = " ".join(_fmt(p) for p in ring)
            for hole in f.holes:
                inner = ET.SubElement(ET.SubElement(geom, f"{{{KML_NS}}}innerBoundaryIs"), f"{{{KML_NS}}}LinearRing")
                ET.SubElement(inner, f"{{{KML_NS}}}coordinates").text = " ".join(_fmt(p) for p in list(hole) + [hole[0]])
    if overlay is not None:
        go = ET.SubElement(doc, f"{{{KML_NS}}}GroundOverlay")
        ET.SubElement(go, f"{{{KML_NS}}}name").text = overlay.name or name
        alpha = max(0, min(255, round(overlay.opacity * 255)))
        ET.SubElement(go, f"{{{KML_NS}}}color").text = f"{alpha:02x}ffffff"
        icon = ET.SubElement(go, f"{{{KML_NS}}}Icon")
        ET.SubElement(icon, f"{{{KML_NS}}}href").text = overlay.href
        quad = ET.SubElement(go, f"{{{GX_NS}}}LatLonQuad")
        ET.SubElement(quad, f"{{{KML_NS}}}coordinates").text = " ".join(
            f"{lon:.9f},{lat:.9f},0" for lat, lon in overlay.quad)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


def write_file(path, features: list, name: str = "IngeCAD", overlay: Optional[Overlay] = None,
               files: Optional[dict] = None) -> Path:
    """``.kmz`` (a zip with ``doc.kml`` and any ``files`` beside it, an
    overlay's image for one) or plain ``.kml``."""
    path = Path(path)
    text = write(features, name, overlay)
    if path.suffix.lower() == ".kmz":
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("doc.kml", text)
            for fname, data in (files or {}).items():
                archive.writestr(fname, data)
    else:
        path.write_text(text, encoding="utf-8")
    return path


def overlay_image(path) -> Optional[bytes]:
    """The GroundOverlay's image inside a KMZ, if any (for the tests)."""
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if name.lower().endswith((".png", ".jpg", ".jpeg")):
                return archive.read(name)
    return None
