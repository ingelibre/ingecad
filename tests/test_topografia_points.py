# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Topography plugin, T1: survey points.

The file a station hands over becomes POINTs with labels that any CAD
opens; the numbers survive save and reload (XDATA); NOD snaps to the
imported coordinate bit-exactly; a traverse can be typed by bearing and
distance; and the whole thing undoes as one step.
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from core.commands import History
from core.document import Document
from plugins.topografia import actions
from plugins.topografia.points import (SurveyPoint, bearing_between, format_bearing,
                                       format_points, parse_bearing, parse_points,
                                       point_from_bearing, sniff_order)
from tools.base import ToolContext

# Five points of a Peruvian survey (UTM 19S, Arequipa): every delimiter and
# the decimal comma a Latin-American station may emit, one per line.
CSV = """P,N,E,Z,D
1,8180100.123,230050.456,2335.10,BM
2,8180120.000,230070.500,2336.25,CERCO
3;8180140,50;230090,75;2337,40;POSTE
4\t8180160.0\t230110.0\t2338.0\tESQUINA
5 8180180.0 230130.0 2339.0 CASA VERDE
"""


# -- the text side ---------------------------------------------------------------

def test_the_classic_pnezd_file_parses_whatever_the_station_used():
    points = parse_points(CSV, "PNEZD")
    assert [p.name for p in points] == ["1", "2", "3", "4", "5"]
    assert points[0].north == pytest.approx(8180100.123)
    assert points[0].east == pytest.approx(230050.456)
    assert points[2].north == pytest.approx(8180140.50)        # decimal comma
    assert points[2].z == pytest.approx(2337.40)
    assert points[3].desc == "ESQUINA"                        # tab
    assert points[4].desc == "CASA VERDE"                     # spaces, two words


def test_the_column_order_is_guessed_from_the_numbers():
    assert sniff_order(CSV) == "PNEZD"
    assert sniff_order("1,230050.4,8180100.5,2335.1,BM\n") == "PENZD"
    assert sniff_order("8180100.5,230050.4,2335.1\n") == "NEZ"
    assert sniff_order("230050.4,8180100.5,2335.1,BM\n") == "ENZD"
    assert sniff_order("# nothing here\n") == "PNEZD"


def test_other_orders_and_automatic_numbering():
    penzd = parse_points("7,230050.4,8180100.5,2335.1,BM\n", "PENZD")
    assert (penzd[0].east, penzd[0].north) == (230050.4, 8180100.5)
    nez = parse_points("8180100.5,230050.4,2335.1\n8180101.5,230051.4,2336.1\n", "NEZ")
    assert [p.name for p in nez] == ["1", "2"]
    with pytest.raises(ValueError):
        parse_points("only,a,header\n", "PNEZD")
    with pytest.raises(ValueError):
        parse_points(CSV, "XYZ")


def test_export_text_reads_back_as_the_same_points():
    points = parse_points(CSV)
    again = parse_points(format_points(points, decimals=3), "PNEZD")
    assert [(p.name, p.desc) for p in again] == [(p.name, p.desc) for p in points]
    assert all(math.isclose(a.north, b.north, abs_tol=5e-4) for a, b in zip(again, points))


@pytest.mark.parametrize("text, azimuth", [
    ("N45°30'20\"E", 45 + 30 / 60 + 20 / 3600),
    ("N45d30'20\"E", 45 + 30 / 60 + 20 / 3600),
    ("N 45 30 20 E", 45 + 30 / 60 + 20 / 3600),
    ("n45.5e", 45.5),
    ("S30E", 150.0),
    ("S30W", 210.0),
    ("N30W", 330.0),
    ("123.5", 123.5),
    ("123°27'24\"", 123 + 27 / 60 + 24 / 3600),
    ("360", 0.0),
])
def test_bearings_as_a_surveyor_types_them(text, azimuth):
    assert parse_bearing(text) == pytest.approx(azimuth)


def test_bad_bearings_are_refused():
    for bad in ("N95E", "hello", "N45°70'E", ""):
        with pytest.raises(ValueError):
            parse_bearing(bad)


def test_bearing_geometry_round_trips():
    assert format_bearing(150.0) == "S 30°00'00\" E"
    assert format_bearing(45 + 30 / 60 + 20 / 3600) == "N 45°30'20\" E"
    east, north = point_from_bearing((1000.0, 2000.0), 45.0, 100.0)
    assert (east, north) == pytest.approx((1070.7107, 2070.7107), abs=1e-4)
    az, dist = bearing_between((1000.0, 2000.0), (east, north))
    assert (az, dist) == pytest.approx((45.0, 100.0))
    assert bearing_between((0, 0), (0, -5))[0] == pytest.approx(180.0)


# -- the document side -----------------------------------------------------------

def _document():
    document = Document.new()
    return document, History(document)


def test_importing_draws_points_labels_and_layers_as_one_undo_step():
    document, history = _document()
    points = parse_points(CSV)
    history.execute(actions.import_points(document, points))
    msp = document.doc.modelspace()
    drawn = [e for e in msp if e.dxftype() == "POINT"]
    assert len(drawn) == 5
    assert {e.dxf.layer for e in drawn} == {"TOPO-PUNTOS"}
    assert drawn[0].dxf.location.z == pytest.approx(2335.10)
    texts = [e for e in msp if e.dxftype() == "TEXT"]
    assert len(texts) == 15                                   # 3 labels each
    assert {e.dxf.layer for e in texts} == {"TOPO-NUMEROS", "TOPO-COTAS", "TOPO-DESC"}
    assert document.doc.layers.get("TOPO-COTAS").color == 3
    labels = actions.labels_of(document, drawn[2])
    assert labels["number"].dxf.text == "3"
    assert labels["elevation"].dxf.text == "2337.40"
    assert labels["description"].dxf.text == "POSTE"
    back = actions.survey_points(document)
    assert [(p.name, p.desc) for p in back] == [(p.name, p.desc) for p in points]
    assert back[0].east == points[0].east and back[0].north == points[0].north

    history.undo()
    assert not [e for e in msp if e.dxftype() in ("POINT", "TEXT")]
    assert "TOPO-PUNTOS" not in document.doc.layers
    history.redo()
    assert len([e for e in msp if e.dxftype() == "POINT"]) == 5


def test_the_first_import_makes_points_visible_and_respects_a_chosen_marker():
    """A new drawing draws POINTs as one pixel (PDMODE 0): the import switches
    to the X marker sized against the labels, undoably -- and a drawing that
    already picked a marker keeps it."""
    document, history = _document()
    assert int(document.doc.header.get("$PDMODE", 0)) == 0
    history.execute(actions.import_points(document, parse_points(CSV),
                                          actions.LabelStyle(text_height=2.5)))
    assert document.doc.header["$PDMODE"] == 3
    assert document.doc.header["$PDSIZE"] == pytest.approx(2.0)
    history.undo()
    assert int(document.doc.header.get("$PDMODE", 0)) == 0

    chosen, history2 = _document()
    chosen.doc.header["$PDMODE"] = 35
    chosen.doc.header["$PDSIZE"] = 0.5
    history2.execute(actions.import_points(chosen, parse_points(CSV)))
    assert chosen.doc.header["$PDMODE"] == 35 and chosen.doc.header["$PDSIZE"] == 0.5


def test_node_snap_lands_on_the_imported_coordinate_exactly():
    from core.snap import SnapEngine

    document, history = _document()
    history.execute(actions.import_points(document, parse_points(CSV)))
    engine = SnapEngine(document)
    hit = engine.find((230050.456 + 0.3, 8180100.123 - 0.2), 1.0,
                      kinds=frozenset({"NOD"}))
    assert hit is not None and hit.kind == "NOD"
    assert hit.x == 230050.456 and hit.y == 8180100.123          # bit-exact


def test_renumbering_rewrites_xdata_and_labels_and_undoes():
    document, history = _document()
    history.execute(actions.import_points(document, parse_points(CSV)))
    drawn = [e for e in document.doc.modelspace() if e.dxftype() == "POINT"]
    history.execute(actions.renumber(drawn, 100, step=10))
    names = [actions.survey_point(e).name for e in drawn]
    assert names == ["100", "110", "120", "130", "140"]
    assert actions.labels_of(document, drawn[1])["number"].dxf.text == "110"
    assert actions.find_point(document, "120") is drawn[2]
    assert actions.next_number(document) == "141"
    history.undo()
    assert [actions.survey_point(e).name for e in drawn] == ["1", "2", "3", "4", "5"]
    assert actions.labels_of(document, drawn[1])["number"].dxf.text == "2"


def test_the_points_survive_a_save_and_a_reload(tmp_path):
    document, history = _document()
    history.execute(actions.import_points(document, parse_points(CSV)))
    path = tmp_path / "puntos.dxf"
    document.save_as(path)
    again = Document.load(path)
    back = actions.survey_points(again)
    assert [(p.name, p.desc, p.z) for p in back] == \
        [("1", "BM", 2335.10), ("2", "CERCO", 2336.25), ("3", "POSTE", 2337.40),
         ("4", "ESQUINA", 2338.0), ("5", "CASA VERDE", 2339.0)]
    assert back[0].east == 230050.456


def test_the_points_survive_the_dwg_the_colleague_gets(tmp_path):
    """Save as DWG (LibreDWG, r2000) and read it back: the promise is that
    the colleague's CAD sees the same five points with their numbers."""
    from formats.dwg_bridge import find_dwg2dxf, find_dxf2dwg, load_dwg

    if find_dxf2dwg() is None or find_dwg2dxf() is None:
        pytest.skip("LibreDWG converters not built")
    document, history = _document()
    history.execute(actions.import_points(document, parse_points(CSV)))
    path = tmp_path / "puntos.dwg"
    document.save_as(path, "r2000")
    loaded = load_dwg(path)
    doc = loaded[0] if isinstance(loaded, tuple) else loaded
    again = Document(doc) if not isinstance(doc, Document) else doc
    back = actions.survey_points(again)
    assert [p.name for p in back] == ["1", "2", "3", "4", "5"]
    assert back[2].desc == "POSTE"
    assert back[0].east == pytest.approx(230050.456, abs=1e-6)


# -- the tools, headless -----------------------------------------------------------

class _Services:
    def __init__(self, document):
        self.document = document


class _Harness:
    def __init__(self, answers=()):
        self.document = Document.new()
        self.history = History(self.document)
        self.finished = False
        self.echoed: list[str] = []
        self._answers = list(answers)
        self.ctx = ToolContext(
            execute=self.history.execute,
            prompt=self.echoed.append,
            echo=self.echoed.append,
            finish=lambda: setattr(self, "finished", True),
            ask_text=lambda prompt, default="": self._answers.pop(0) if self._answers else None,
            undo_last=self.history.undo,
            services=_Services(self.document),
        )

    @property
    def msp(self):
        return self.document.doc.modelspace()


def test_the_import_tool_reads_a_file_headless(tmp_path):
    from plugins.topografia.tools import ImportPointsTool

    path = tmp_path / "levantamiento.csv"
    path.write_text(CSV, encoding="utf-8")
    h = _Harness(answers=[str(path)])
    tool = ImportPointsTool(h.ctx)
    tool.start()
    assert h.finished
    assert len([e for e in h.msp if e.dxftype() == "POINT"]) == 5
    assert any("5 points imported" in line for line in h.echoed)
    # a cancelled file dialog imports nothing and ends the command
    h2 = _Harness(answers=[None])
    ImportPointsTool(h2.ctx).start()
    assert h2.finished and not list(h2.msp)


def test_the_export_tool_writes_all_points_when_nothing_is_selected(tmp_path):
    from plugins.topografia.tools import ExportPointsTool

    out = tmp_path / "salida.csv"
    h = _Harness(answers=[str(out)])
    h.history.execute(actions.import_points(h.document, parse_points(CSV)))
    tool = ExportPointsTool(h.ctx)
    tool.start()
    tool.on_selection([])
    assert h.finished
    back = parse_points(out.read_text(encoding="utf-8"), "PNEZD")
    assert [p.name for p in back] == ["1", "2", "3", "4", "5"]
    assert back[4].desc == "CASA VERDE"


def test_a_traverse_is_typed_leg_by_leg_by_bearing_and_distance():
    from plugins.topografia.tools import PointByBearingTool

    h = _Harness()
    tool = PointByBearingTool(h.ctx)
    tool.start()
    tool.on_point((1000.0, 2000.0))
    assert tool.on_option("N45E")
    assert tool.on_option("100")
    tool.on_enter()                          # elevation: default 0
    tool.on_enter()                          # number: default 1
    first = [e for e in h.msp if e.dxftype() == "POINT"]
    assert len(first) == 1
    assert (first[0].dxf.location.x, first[0].dxf.location.y) == \
        pytest.approx((1070.7107, 2070.7107), abs=1e-4)
    assert actions.survey_point(first[0]).name == "1"
    # the new point is the base; Enter repeats the bearing
    tool.on_enter()
    assert tool.on_option("50")
    assert tool.on_option("10")              # elevation
    assert tool.on_option("7")               # number
    second = [e for e in h.msp if e.dxftype() == "POINT"][1]
    assert (second.dxf.location.x, second.dxf.location.y) == \
        pytest.approx((1070.7107 + 35.3553, 2070.7107 + 35.3553), abs=1e-4)
    assert second.dxf.location.z == 10.0
    assert actions.survey_point(second).name == "7"
    assert any("Invalid bearing" in line for line in h.echoed) is False
    assert not tool.on_option("hello") or "Invalid bearing" in h.echoed[-1]
    tool.on_cancel()
    assert h.finished
    # one undo per point: the traverse is not one blob
    h.history.undo()
    assert len([e for e in h.msp if e.dxftype() == "POINT"]) == 1


def test_renumber_and_find_tools_headless():
    from plugins.topografia.tools import FindPointTool, RenumberPointsTool

    h = _Harness()
    h.history.execute(actions.import_points(h.document, parse_points(CSV)))
    drawn = [e for e in h.msp if e.dxftype() == "POINT"]
    tool = RenumberPointsTool(h.ctx)
    tool.start()
    tool.on_selection(list(reversed(drawn)))       # selection order must not matter
    assert tool.on_option("200")
    assert h.finished
    assert [actions.survey_point(e).name for e in drawn] == ["200", "201", "202", "203", "204"]

    h2 = _Harness()
    h2.document, h2.history = h.document, h.history
    h2.ctx = ToolContext(execute=h.history.execute, prompt=h2.echoed.append,
                         echo=h2.echoed.append,
                         finish=lambda: setattr(h2, "finished", True),
                         services=_Services(h.document))
    find = FindPointTool(h2.ctx)
    find.start()
    assert find.on_option("202")
    assert h2.finished
    assert "Point 202: E=230090.750 N=8180140.500 Z=2337.400 POSTE" in h2.echoed[-1]
    h3 = _Harness()
    FindPointTool(h3.ctx).start()
    assert FindPointTool(h3.ctx).on_option("99") and "not found" in h3.echoed[-1]


# -- through the window ------------------------------------------------------------

def test_the_plugin_is_bundled_on_and_reachable(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        assert win.plugins.is_active("topografia")
        actions_ = win._menu_bar.actions()
        assert "Topography" in [a.text() for a in actions_]
        d = win.dispatcher
        for name in ("PIMPORT", "PEXPORT", "PBY", "PRENUM", "PFIND"):
            assert name in d._commands
        assert d.resolve_name("PIM") == "PIMPORT"
        assert d.resolve_name("PBY") == "PBY"
        assert "plugin_topografia_toolbar" in [
            t.objectName() for t in win.findChildren(type(win._draw_toolbar))]
    finally:
        win.close()
