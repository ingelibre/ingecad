# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Terrain plugin, G4, the pure part: KML read and written -- points,
lines, polygons with holes, names, descriptions, colours through styles
and StyleMaps, folders, gx:Track, KMZ archives, and the GroundOverlay
with its LatLonQuad."""
from __future__ import annotations

import zipfile

import pytest

from plugins.terreno import kml

SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2">
<Document><name>Arequipa</name>
  <Style id="red"><LineStyle><color>ff0000ff</color><width>3</width></LineStyle>
    <PolyStyle><color>400000ff</color></PolyStyle></Style>
  <Style id="pin"><IconStyle><color>ff00ff00</color></IconStyle></Style>
  <StyleMap id="mapped"><Pair><key>normal</key><styleUrl>#red</styleUrl></Pair>
    <Pair><key>highlight</key><styleUrl>#pin</styleUrl></Pair></StyleMap>
  <Folder><name>Lotes</name>
    <Placemark><name>LOTE 1</name><description>Frente calle</description><styleUrl>#mapped</styleUrl>
      <Polygon><outerBoundaryIs><LinearRing><coordinates>
        -71.5370,-16.4340,0 -71.5365,-16.4340,0 -71.5365,-16.4345,0 -71.5370,-16.4345,0 -71.5370,-16.4340,0
      </coordinates></LinearRing></outerBoundaryIs>
      <innerBoundaryIs><LinearRing><coordinates>
        -71.5368,-16.4342,0 -71.5367,-16.4342,0 -71.5367,-16.4343,0 -71.5368,-16.4343,0 -71.5368,-16.4342,0
      </coordinates></LinearRing></innerBoundaryIs></Polygon></Placemark>
    <Placemark><name>Eje</name><Style><LineStyle><color>ffff8000</color></LineStyle></Style>
      <LineString><coordinates>-71.5372,-16.4338,2335.4 -71.5362,-16.4346,2336.1</coordinates></LineString></Placemark>
  </Folder>
  <Placemark><name>BM-1</name><styleUrl>#pin</styleUrl>
    <Point><coordinates>-71.536944,-16.398889,2335</coordinates></Point></Placemark>
  <Placemark><name>Dos</name><MultiGeometry>
    <Point><coordinates>-71.5,-16.4</coordinates></Point>
    <LineString><coordinates>-71.5,-16.4 -71.4,-16.4</coordinates></LineString></MultiGeometry></Placemark>
  <Placemark><name>Track</name><gx:Track><gx:coord>-71.53 -16.43 2300</gx:coord><gx:coord>-71.52 -16.43 2310</gx:coord></gx:Track></Placemark>
</Document></kml>
"""


def test_colours_go_both_ways_in_kmls_aabbggrr():
    assert kml.kml_color((255, 0, 128)) == "ff8000ff"
    assert kml.kml_color((0, 0, 255), 0x40) == "40ff0000"
    assert kml.parse_color("ff8000ff") == ((255, 0, 128), 255)
    assert kml.parse_color("400000ff") == ((255, 0, 0), 0x40)
    assert kml.parse_color("0000ff") == ((255, 0, 0), 255)
    assert kml.parse_color("zzz") == (None, 255)


def test_parsing_keeps_geometry_names_colours_holes_and_folders():
    feats = kml.parse(SAMPLE)
    by_name = {f.name: f for f in feats}
    lot = by_name["LOTE 1"]
    assert lot.kind == "polygon" and lot.folder == "Lotes" and lot.description == "Frente calle"
    assert len(lot.coords) == 4 and lot.coords[0] == (-16.4340, -71.5370, 0.0)     # closing vertex dropped
    assert len(lot.holes) == 1 and len(lot.holes[0]) == 4
    assert lot.color == (255, 0, 0)                                              # via the StyleMap
    axis = by_name["Eje"]
    assert axis.kind == "line" and axis.color == (0, 128, 255) and axis.coords[1][2] == 2336.1
    bm = by_name["BM-1"]
    assert bm.kind == "point" and bm.color == (0, 255, 0) and bm.coords == [(-16.398889, -71.536944, 2335.0)]
    assert bm.folder == ""
    kinds = [f.kind for f in feats if f.name == "Dos"]
    assert kinds == ["point", "line"]
    track = by_name["Track"]
    assert track.kind == "line" and track.coords[0] == (-16.43, -71.53, 2300.0)
    assert kml.parse("<not kml") == []


def test_writing_then_reading_returns_the_same_features(tmp_path):
    feats = kml.parse(SAMPLE)
    text = kml.write(feats, "Prueba")
    assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    back = kml.parse(text)
    assert [f.kind for f in back] == [f.kind for f in feats]
    assert [f.name for f in back] == [f.name for f in feats]
    assert [f.color for f in back] == [f.color for f in feats]
    for a, b in zip(feats, back):
        for pa, pb in zip(a.coords, b.coords):
            assert pa[:2] == pytest.approx(pb[:2], abs=1e-9) and pa[2] == pytest.approx(pb[2], abs=1e-3)
        assert len(a.holes) == len(b.holes)
    assert back[0].description == "Frente calle"
    # the same through a KMZ on disk, and the plain .kml
    path = kml.write_file(tmp_path / "prueba.kmz", feats, "Prueba")
    assert zipfile.is_zipfile(path) and "doc.kml" in zipfile.ZipFile(path).namelist()
    assert [f.name for f in kml.parse_file(path)] == [f.name for f in feats]
    plain = kml.write_file(tmp_path / "prueba.kml", feats)
    assert plain.read_text(encoding="utf-8").startswith("<?xml") and len(kml.parse_file(plain)) == len(feats)


def test_the_ground_overlay_carries_its_corners_and_opacity(tmp_path):
    overlay = kml.Overlay("plano.png", [(-16.44, -71.54), (-16.44, -71.53), (-16.43, -71.53), (-16.43, -71.54)],
                          opacity=0.7, name="Plano")
    text = kml.write([], "Overlay", overlay)
    assert "<GroundOverlay>" in text.replace("kml:", "") or "GroundOverlay" in text
    assert "b2ffffff" in text                                # 0.7 * 255 = 178 = 0xb2
    assert "LatLonQuad" in text and "plano.png" in text
    assert "-71.540000000,-16.440000000,0 -71.530000000,-16.440000000,0" in text
    path = kml.write_file(tmp_path / "o.kmz", [], "Overlay", overlay, {"plano.png": b"\x89PNG fake"})
    assert kml.overlay_image(path) == b"\x89PNG fake"
    assert kml.parse_file(path) == []                       # an overlay is not a placemark
