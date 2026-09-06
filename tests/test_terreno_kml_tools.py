# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Terrain plugin, G4 in the drawing: the lot goes to a KMZ and comes
back within a centimetre (the DoD), names and colours included; every
drawable kind finds its KML shape; the overlay renders the plan north-up
on a transparent background with the corners a LatLonQuad needs; the
three tools driven headless, and reachable from the window."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from core.commands import History
from core.document import Document
from core.georef import Georef, SetGeorefCommand
from plugins.terreno import actions, kml
from tools.base import ToolContext

from plugins.topografia.points import parse_points

GEOREF = Georef(19)
SURVEY = Path(__file__).resolve().parent / "data" / "levantamiento-arequipa.csv"
# the lot of the synthetic Arequipa survey (the LOTE corners), UTM 19 S
LOT = [(p.east, p.north) for p in parse_points(SURVEY.read_text(encoding="utf-8"), "PNEZD")
       if p.desc.startswith("LOTE")]


def _document(georef=GEOREF):
    document = Document.new()
    history = History(document)
    if georef is not None:
        history.execute(SetGeorefCommand(georef))
    return document, history


def test_the_lot_goes_to_google_earth_and_comes_back_within_a_centimetre(tmp_path):
    document, history = _document()
    msp = document.doc.modelspace()
    lot = msp.add_lwpolyline(LOT, close=True, dxfattribs={"color": 1})
    features, skipped = actions.kml_features(document, [lot])
    assert skipped == 0 and len(features) == 1
    f = features[0]
    assert f.kind == "polygon" and len(f.coords) == len(LOT) and f.color == (255, 0, 0)
    assert "Area 1523.77 m²" in f.description and "perimeter 156.70 m" in f.description
    path = tmp_path / "lote.kmz"
    assert actions.export_kmz(document, [lot], path, "Lote") == (1, 0)
    back = kml.parse_file(path)
    assert len(back) == 1
    # the trip back: a fresh drawing, same georeference
    other, history2 = _document()
    history2.execute(actions.import_features(other, back))
    poly = other.doc.modelspace().query("LWPOLYLINE")[0]
    assert poly.closed and poly.dxf.layer == "TERRENO-KML" and poly.rgb == (255, 0, 0)
    worst = 0.0
    for (x, y), (ex, ey) in zip(poly.get_points("xy"), LOT):
        worst = max(worst, abs(x - ex), abs(y - ey))
    assert worst < 0.01, worst                              # the DoD: under a centimetre
    assert worst < 0.001                                    # in fact under a millimetre
    history2.undo()
    assert not list(other.doc.modelspace())


def test_every_drawable_kind_finds_its_kml_shape(tmp_path):
    from plugins.topografia import actions as topo
    from plugins.topografia.points import SurveyPoint

    document, history = _document()
    msp = document.doc.modelspace()
    history.execute(topo.import_points(document, [SurveyPoint("5", 229140.0, 8181320.0, 2335.4, "LOTE V1")],
                                       topo.LabelStyle(text_height=0.4)))
    point = msp.query("POINT")[0]
    line = msp.add_line((229100, 8181300), (229200, 8181300), dxfattribs={"layer": "0"})
    circle = msp.add_circle((229150, 8181350), 10.0)
    text = msp.add_text("MZ B", height=1.0)
    text.set_placement((229160, 8181360))
    open_pl = msp.add_lwpolyline([(0, 0), (10, 0), (10, 10)])
    open_pl.rgb = (10, 200, 30)
    hatch = msp.add_hatch()
    entities = [point, line, circle, text, open_pl, hatch]
    features, skipped = actions.kml_features(document, entities)
    assert skipped == 1                                     # the hatch
    kinds = {f.kind for f in features}
    assert kinds == {"point", "line", "polygon"}
    named = {f.name: f for f in features}
    assert named["5"].kind == "point" and named["5"].description == "LOTE V1" and named["5"].coords[0][2] == 2335.4
    assert named["MZ B"].kind == "point"
    circ = next(f for f in features if f.kind == "polygon")
    assert 24 <= len(circ.coords) <= 200 and "Area 31" in circ.description     # 314.16 m² less the flattening
    ln = next(f for f in features if f.kind == "line" and "Length 100.00 m" in f.description)
    assert ln.color == (255, 255, 255)                      # layer 0 is white (ACI 7)
    pl = next(f for f in features if f.color == (10, 200, 30))
    assert pl.kind == "line" and len(pl.coords) == 3
    assert actions.entity_rgb(document, line) == (255, 255, 255)
    document.doc.layers.add("ROJA", color=1)
    line.dxf.layer = "ROJA"
    assert actions.entity_rgb(document, line) == (255, 0, 0)


def test_import_gives_holes_altitudes_labels_and_colours():
    document, history = _document()
    features = kml.parse(Path(__file__).with_name("test_terreno_kml.py").read_text(encoding="utf-8")
                         .split('SAMPLE = """')[1].split('"""')[0])
    history.execute(actions.import_features(document, features, text_height=0.5))
    msp = document.doc.modelspace()
    kinds = [e.dxftype() for e in msp]
    assert kinds.count("LWPOLYLINE") == 3                   # the lot, its hole, the "Dos" line
    assert kinds.count("POLYLINE") == 2                     # the axis (2335.4 -> 2336.1) and the track
    assert kinds.count("POINT") == 2 and kinds.count("TEXT") == 2
    lot = [e for e in msp if e.dxftype() == "LWPOLYLINE" and e.closed]
    assert len(lot) == 2 and lot[0].rgb == (255, 0, 0)
    tags = [v for _c, v in lot[1].get_xdata("INGECAD")]
    assert tags[:2] == ["KML", "LOTE 1 (hole)"] and tags[3] == "Lotes"
    labels = {e.dxf.text for e in msp if e.dxftype() == "TEXT"}
    assert labels == {"BM-1", "Dos"}
    assert all(e.dxf.layer == "TERRENO-KML" for e in msp)
    history.undo()
    assert not list(msp) and "TERRENO-KML" not in document.doc.layers


def test_the_overlay_is_north_up_and_transparent(qapp, tmp_path):
    document, _history = _document()
    msp = document.doc.modelspace()
    msp.add_solid([(229100, 8181480), (229300, 8181480), (229300, 8181500), (229100, 8181500)],
                  dxfattribs={"color": 5})                  # a blue band along the NORTH edge
    png, width, height = actions.render_overlay(document, 229100, 8181300, 229300, 8181500, 200)
    assert (width, height) == (200, 200)
    image = Image.open(io.BytesIO(png)).convert("RGBA")
    assert image.size == (200, 200)
    top, middle = image.getpixel((100, 5)), image.getpixel((100, 100))
    assert top[3] == 255 and top[2] > 200 and top[0] < 60          # blue at the top
    assert middle[3] == 0                                            # nothing: transparent
    quad = actions.overlay_quad(GEOREF, 229100, 8181300, 229300, 8181500)
    assert len(quad) == 4 and quad[0][0] < quad[3][0] and quad[0][1] < quad[1][1]   # SW south of NW, west of SE


class _Services:
    def __init__(self, document):
        self.document = document


class _Harness:
    def __init__(self, georef=GEOREF):
        self.document, self.history = _document(georef)
        self.finished = False
        self.echoed: list[str] = []
        self.prompts: list[str] = []
        self.answers: list = []
        self.ctx = ToolContext(
            execute=self.history.execute, prompt=self.prompts.append,
            echo=self.echoed.append, finish=lambda: setattr(self, "finished", True),
            ask_text=lambda prompt, default="": self.answers.pop(0) if self.answers else None,
            undo_last=self.history.undo, services=_Services(self.document))

    @property
    def msp(self):
        return self.document.doc.modelspace()


def test_kmlout_and_kmlin_round_the_trip_headless(tmp_path):
    from plugins.terreno.tools import KmlInTool, KmlOutTool

    h = _Harness()
    lot = h.msp.add_lwpolyline(LOT, close=True)
    h.msp.add_text("LOTE 1", height=1.0).set_placement((229155, 8181340))
    h.msp.add_hatch()
    out = tmp_path / "salida.kmz"
    h.answers = [str(out)]
    tool = KmlOutTool(h.ctx)
    tool.start()
    tool.on_selection([])                                   # Enter: everything
    assert h.finished and out.is_file()
    assert h.echoed[-2] == f"2 placemarks written to {out}: open it in Google Earth."
    assert h.echoed[-1] == "1 objects of other kinds were left out."

    h2 = _Harness()
    h2.answers = [str(out)]
    t2 = KmlInTool(h2.ctx)
    t2.start()
    assert h2.finished
    assert h2.echoed[-1] == "2 placemarks imported on TERRENO-KML: 1 points, 0 lines, 1 polygons."
    poly = h2.msp.query("LWPOLYLINE")[0]
    assert max(abs(x - ex) + abs(y - ey) for (x, y), (ex, ey) in zip(poly.get_points("xy"), LOT)) < 0.01
    assert {e.dxf.text for e in h2.msp if e.dxftype() == "TEXT"} == {"LOTE 1"}

    h3 = _Harness(georef=None)
    t3 = KmlOutTool(h3.ctx)
    t3.start()
    assert h3.finished and "run GEOREF first" in h3.echoed[-1]
    h4 = _Harness()
    h4.answers = [str(tmp_path / "vacio.kmz")]
    t4 = KmlOutTool(h4.ctx)
    t4.start()
    t4.on_selection([h4.msp.add_hatch()])
    assert h4.finished and h4.echoed[-1].startswith("Nothing to export")
    h5 = _Harness()
    h5.answers = [str(tmp_path / "nada.kml")]
    (tmp_path / "nada.kml").write_text("<kml/>", encoding="utf-8")
    t5 = KmlInTool(h5.ctx)
    t5.start()
    assert h5.finished and h5.echoed[-1].startswith("No placemarks in")


def test_kmloverlay_writes_a_kmz_with_the_image_and_its_corners(qapp, tmp_path):
    from plugins.terreno.tools import KmlOverlayTool

    h = _Harness()
    h.msp.add_lwpolyline(LOT, close=True)
    out = tmp_path / "plano-overlay.kmz"
    h.answers = [str(out)]
    tool = KmlOverlayTool(h.ctx)
    tool.start()
    tool.on_selection([])
    tool.on_point((229100.0, 8181300.0))
    tool.on_point((229300.0, 8181400.0))
    assert h.prompts[-1] == "Image width in pixels <2048>:"
    assert tool.on_option("400")
    assert h.prompts[-1] == "Opacity in percent <70>:"
    tool.on_enter()
    assert h.finished and out.is_file()
    assert h.echoed[-1].startswith("Overlay 400 x 200 px at 70% opacity written to")
    names = zipfile.ZipFile(out).namelist()
    assert "doc.kml" in names and "overlay.png" in names
    text = zipfile.ZipFile(out).read("doc.kml").decode("utf-8")
    assert "LatLonQuad" in text and "b2ffffff" in text and "overlay.png" in text
    image = Image.open(io.BytesIO(kml.overlay_image(out)))
    assert image.size == (400, 200) and image.mode == "RGBA"


def test_the_window_has_the_google_earth_commands(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        for name in ("KMLIN", "KMLOUT", "KMLOVERLAY"):
            assert name in win.dispatcher._commands
        bar_actions = win._menu_bar.actions()
        terrain = next(a for a in bar_actions if a.text() == "Terrain")
        labels = [a.text() for a in terrain.menu().actions() if a.text()]
        assert labels[-3:] == ["Import KML / KMZ...", "Export to Google Earth (KMZ)...",
                               "Plan overlay for Google Earth..."]
    finally:
        win.close()
