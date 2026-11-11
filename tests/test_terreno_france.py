# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Terrain plugin, France: IGN's coordinate systems by the names a French
surveyor types (L93, CC44, L2E...), the default system from Options, the
NTF grid tried before PROJ's Helmert and a warning when it cannot be
read, and IGN's open imagery (BD ORTHO HR first, its general orthophoto
where a tile is missing; Plan IGN; the cadastre, transparent)."""
from __future__ import annotations

import io
import math

import pytest
from PIL import Image

pytest.importorskip("pyproj")

from core.georef import Georef, SetGeorefCommand, read_georef  # noqa: E402
from plugins.terreno import datum, imagery, prefs, tiles  # noqa: E402
from tests.test_terreno_georef import _Harness  # noqa: E402

#: Albi, the cathedral square, in WGS84.
ALBI = (43.92850, 2.14250)


# -- the names ------------------------------------------------------------------------------

def test_french_names_give_igns_epsg_codes():
    assert datum.french_system("L93") == datum.french_system("lambert 93") == "EPSG:2154"
    assert datum.french_system("cc44") == "EPSG:3944"
    assert datum.french_system("CC42") == "EPSG:3942" and datum.french_system("CC50") == "EPSG:3950"
    assert datum.french_system("L2E") == datum.french_system("LIIE") == "EPSG:27572"
    assert datum.french_system("Guyane") == "EPSG:2972"
    assert datum.french_system("Réunion") == "EPSG:2975"
    assert datum.french_system("43.93") == "EPSG:3944"          # a latitude: its CC zone
    assert datum.french_system("UTM") is None and datum.french_system("12") is None


def test_a_cc_zone_is_the_nearest_whole_degree_of_latitude():
    assert datum.cc_zone_for_lat(43.93) == 44                  # Albi
    assert datum.cc_zone_for_lat(48.85) == 49                  # Paris
    assert datum.cc_zone_for_lat(41.9) == 42                   # Corsica, clamped
    assert datum.cc_zone_for_lat(51.0) == 50


def test_every_french_system_is_a_projected_system_proj_knows():
    for code in set(datum.FRENCH_SYSTEMS.values()):
        assert datum.check_crs(code).is_projected


# -- the conversions --------------------------------------------------------------------------

@pytest.mark.parametrize("code", ["EPSG:2154", "EPSG:3944"])
def test_lambert_93_and_cc44_agree_with_proj_and_round_trip(code):
    from pyproj import Transformer

    georef = Georef(crs=code)
    e, n = datum.latlon_to_drawing(georef, *ALBI)
    ref = Transformer.from_crs("EPSG:4326", code, always_xy=True).transform(ALBI[1], ALBI[0])
    assert (e, n) == pytest.approx(ref, abs=1e-3)
    lat, lon = datum.drawing_to_latlon(georef, e, n)
    assert (lat, lon) == pytest.approx(ALBI, abs=1e-9)


def test_ntf_tries_the_ign_grid_through_rgf93_and_never_a_ballpark():
    candidates = datum._candidates("EPSG:27572")
    assert any("NTF to RGF93" in t.description for t in candidates)
    assert not any(datum._is_ballpark(t) for t in candidates)
    # the grid comes first; PROJ's Helmert to WGS84 stays as the fallback
    first_helmert = next(i for i, t in enumerate(candidates) if "NTF to WGS 84" in t.description)
    first_grid = next(i for i, t in enumerate(candidates) if "NTF to RGF93" in t.description)
    assert first_grid < first_helmert
    # whichever path answers, the point lands within the Helmert's metres
    e, n = datum.latlon_to_drawing(Georef(crs="EPSG:27572"), *ALBI)
    lat, lon = datum.drawing_to_latlon(Georef(crs="EPSG:27572"), e, n)
    assert (lat, lon) == pytest.approx(ALBI, abs=1e-7)


class _Path:
    def __init__(self, description, accuracy, answer):
        self.description, self.accuracy, self._answer = description, accuracy, answer

    def transform(self, x, y, direction=None):
        return self._answer


def test_the_route_says_when_the_best_path_cannot_be_read(monkeypatch):
    grid = _Path("NTF to RGF93 v1 (1)", 0.05, (math.inf, math.inf))
    helmert = _Path("NTF to WGS 84 (1)", 2.0, (2.14, 43.93))
    monkeypatch.setattr(datum, "_candidates", lambda code: (grid, helmert))
    path = datum.route("EPSG:27572", 600000, 1800000)
    assert path == datum.Route("NTF to WGS 84 (1)", 2.0, True)
    monkeypatch.setattr(datum, "_candidates", lambda code: (helmert,))
    assert datum.route("EPSG:27572", 600000, 1800000).degraded is False


# -- GEOREF -----------------------------------------------------------------------------------

def test_georef_france_takes_l93_a_cc_zone_or_a_latitude():
    from plugins.terreno.tools import GeorefTool

    for typed, code in (("L93", "EPSG:2154"), ("cc44", "EPSG:3944"), ("43.93", "EPSG:3944"),
                        ("L2E", "EPSG:27572")):
        h = _Harness()
        tool = GeorefTool(h.ctx)
        tool.start()
        assert tool.on_option("F")
        assert h.prompts[-1].startswith("French system: L93, CC42 to CC50") and "<L93>" in h.prompts[-1]
        assert tool.on_option(typed)
        assert h.finished and read_georef(h.doc) == Georef(crs=code)
        assert h.echoed[-1].startswith(f"Drawing georeferenced: {code}, ")
        assert any(line.startswith("Conversion to WGS84:") for line in h.echoed)


def test_georef_france_enter_is_lambert_93_and_a_typo_asks_again():
    from plugins.terreno.tools import GeorefTool

    h = _Harness()
    tool = GeorefTool(h.ctx)
    tool.start()
    tool.on_option("F")
    assert tool.on_option("Lambert 2000")
    assert "is not a French system" in h.echoed[-1] and not h.finished
    tool.on_enter()
    assert h.finished and read_georef(h.doc) == Georef(crs="EPSG:2154")
    assert h.echoed[-1] == "Drawing georeferenced: EPSG:2154, RGF93 v1 / Lambert-93"


def test_georef_coordsys_also_reads_a_french_name():
    from plugins.terreno.tools import GeorefTool

    h = _Harness()
    tool = GeorefTool(h.ctx)
    tool.start()
    tool.on_option("C")
    assert tool.on_option("CC44")
    assert h.finished and read_georef(h.doc) == Georef(crs="EPSG:3944")


def test_a_default_system_from_options_is_asked_first(monkeypatch):
    from plugins.terreno.tools import GeorefTool

    monkeypatch.setattr(prefs, "default_crs", lambda: "EPSG:2154")
    h = _Harness()
    tool = GeorefTool(h.ctx)
    tool.start()
    assert h.prompts[-1] == "Coordinate system code, as EPSG:27700 <EPSG:2154>:"
    tool.on_enter()
    assert h.finished and read_georef(h.doc) == Georef(crs="EPSG:2154")
    # UTM is still one word away
    h = _Harness()
    tool = GeorefTool(h.ctx)
    tool.start()
    assert tool.on_option("utm")
    assert h.prompts[-1].startswith("UTM zone number or [Longitude/Coordsys/France/Remove]")
    # a drawing that already declares something is asked about that, as before
    h = _Harness()
    h.history.execute(SetGeorefCommand(Georef(18, True)))
    GeorefTool(h.ctx).start()
    assert "<18>" in h.prompts[-1]


def test_georef_warns_when_the_ntf_grid_cannot_be_read(monkeypatch):
    from plugins.terreno.tools import GeorefTool

    monkeypatch.setattr(datum, "route", lambda code: datum.Route("NTF to WGS 84 (1)", 2.0, True))
    h = _Harness()
    tool = GeorefTool(h.ctx)
    tool.start()
    tool.on_option("F")
    tool.on_option("L2E")
    assert "Conversion to WGS84: NTF to WGS 84 (1) (about 2 m)." in h.echoed
    assert any("more accurate conversion exists" in line for line in h.echoed)
    assert read_georef(h.doc) == Georef(crs="EPSG:27572")


# -- IGN imagery ------------------------------------------------------------------------------

def test_ign_presets_are_open_licensed_and_cached_with_their_format():
    hr = tiles.PRESETS["ign_ortho_hr"]
    assert "LAYER=HR.ORTHOIMAGERY.ORTHOPHOTOS" in hr.url_template and hr.max_zoom == 19
    assert "LAYER=ORTHOIMAGERY.ORTHOPHOTOS&" in hr.fallback_template
    assert hr.url(19, 262540, 189600).endswith("TILEMATRIX=19&TILEROW=189600&TILECOL=262540&FORMAT=image/jpeg")
    assert hr.extension == ".jpg"
    assert tiles.PRESETS["ign_plan"].extension == ".png"
    assert tiles.PRESETS["ign_cadastre"].extension == ".png"
    for key in ("ign_ortho_hr", "ign_plan", "ign_cadastre"):
        assert "Etalab" in tiles.PRESETS[key].attribution and "IGN" in tiles.PRESETS[key].attribution
    # a template the path does not end with an extension still says .bin
    assert tiles.custom_source("https://x.test/tile?z={z}&x={x}&y={y}").extension == ".bin"


def _png(colour, mode="RGB") -> bytes:
    out = io.BytesIO()
    Image.new(mode, (256, 256), colour).save(out, format="PNG")
    return out.getvalue()


def test_a_tile_bd_ortho_hr_lacks_comes_from_the_general_orthophoto(tmp_path):
    hr = tiles.PRESETS["ign_ortho_hr"]
    served = []

    def fetch(url):
        served.append(url)
        if "HR.ORTHOIMAGERY" in url:
            raise tiles.TileError(f"{url}: HTTP 404")
        return _png((10, 20, 30))

    cache = tiles.TileCache(hr, tmp_path, fetch)
    assert cache.bytes(19, 1, 2) == _png((10, 20, 30))
    assert "HR.ORTHOIMAGERY" in served[0] and "LAYER=ORTHOIMAGERY.ORTHOPHOTOS&" in served[1]
    assert cache.cached(19, 1, 2)

    def down(url):
        raise tiles.TileError(f"{url}: timed out")

    with pytest.raises(tiles.TileError):                 # an outage is not a missing tile
        tiles.TileCache(hr, tmp_path / "b", down).bytes(19, 1, 2)


def test_a_transparent_tile_is_laid_on_white_not_black(tmp_path):
    georef = Georef(crs="EPSG:2154")
    e, n = datum.latlon_to_drawing(georef, *ALBI)
    square = [(e - 20, n - 20), (e + 20, n - 20), (e + 20, n + 20), (e - 20, n + 20)]
    source = tiles.PRESETS["ign_cadastre"]
    cache = tiles.TileCache(source, tmp_path, lambda url: _png((0, 0, 0, 0), "RGBA"))
    placement = imagery.satellite_image(georef, square, 17, cache, clip=False)
    assert placement.image.getpixel((placement.width // 2, placement.height // 2))[:3] == (255, 255, 255)


def test_a_drawing_in_a_french_system_gets_bd_ortho_hr_unless_options_say_otherwise(monkeypatch):
    settings = {}
    monkeypatch.setattr(prefs, "_setting", lambda key, default: settings.get(key, default))
    assert prefs.imagery_source(Georef(crs="EPSG:2154")).id == "ign_ortho_hr"
    assert prefs.imagery_source(Georef(crs="EPSG:3944")).id == "ign_ortho_hr"
    assert prefs.imagery_source(Georef(19)).id == "esri_imagery"
    assert prefs.imagery_source(Georef(crs="EPSG:27700")).id == "esri_imagery"
    assert prefs.imagery_source(None).id == "esri_imagery"
    settings[prefs.SETTING_IMG_SOURCE] = "auto"
    assert prefs.imagery_source(Georef(crs="EPSG:2154")).id == "ign_ortho_hr"
    settings[prefs.SETTING_IMG_SOURCE] = "osm"
    assert prefs.imagery_source(Georef(crs="EPSG:2154")).id == "osm"


def test_satimage_offers_the_ign_sources_by_their_letters(monkeypatch):
    from plugins.terreno.tools import SatImageTool

    monkeypatch.setattr(prefs, "_setting", lambda key, default: default)
    h = _Harness()
    h.history.execute(SetGeorefCommand(Georef(crs="EPSG:2154")))
    tool = SatImageTool(h.ctx)
    tool.start()
    assert tool._source.id == "ign_ortho_hr"
    tool._polygon = [(0, 0), (1, 0), (1, 1)]
    tool._after_boundary()
    assert h.prompts[-1] == "Zoom level (1-19) or [Source] <18>:"
    for key, wanted in (("P", "ign_plan"), ("A", "ign_cadastre"), ("I", "ign_ortho_hr")):
        tool.on_option("S")
        assert h.prompts[-1].startswith("Source [Esri/Sentinel/Osm/Ign ortho/Plan ign/cadAstre ign/Custom]")
        tool.on_option(key)
        assert tool._source.id == wanted
