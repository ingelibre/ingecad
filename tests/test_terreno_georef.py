# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Terrain plugin, G1, in the drawing: the georeference declared, kept
through save and reopen (DXF and DWG), undone exactly; GEOREF and LATLON
driven headless; the plugin reachable from the window with its options
page and its Spanish names."""
from __future__ import annotations

from pathlib import Path

import pytest

from core import georef as georef_mod
from core import i18n
from core.commands import History
from core.document import Document
from core.georef import Georef, SetGeorefCommand, read_georef, write_georef
from plugins.terreno import actions, datum
from tools.base import ToolContext

PACK = Path(__file__).resolve().parent.parent / "plugins" / "terreno" / "i18n"
AREQUIPA = (229038.4878, 8185246.5211)          # WGS84 UTM 19 S of the Plaza de Armas


def _document():
    document = Document.new()
    return document, History(document)


# -- the declaration itself ----------------------------------------------------------

def test_a_georef_validates_labels_and_serialises():
    g = Georef(19)
    assert g.hemisphere == "S" and g.zone_label() == "19 S" and g.label() == "WGS84 UTM 19 S"
    assert g.to_tags() == [(1, "zone=19"), (1, "hemisphere=S"), (1, "datum=WGS84"), (1, "shift=0,0,0")]
    p = Georef(18, True, "PSAD56", (-279, 175, -379))
    assert p.label() == "PSAD56 UTM 18 N" and p.shift == (-279.0, 175.0, -379.0)
    assert Georef.from_tags(p.to_tags()) == p
    with pytest.raises(ValueError):
        Georef(61)
    with pytest.raises(ValueError):
        Georef(19, datum="NAD27")
    # tolerant reading: unknown keys, missing shift, and a record with no zone
    assert Georef.from_tags([(1, "zone=17"), (1, "colour=red")]) == Georef(17)
    assert Georef.from_tags([(1, "hemisphere=N")]) is None
    assert Georef.from_tags([(1, "zone=abc")]) is None


def test_the_drawing_keeps_the_georef_and_undo_puts_back_what_was_there():
    document, history = _document()
    doc = document.doc
    assert read_georef(doc) is None
    history.execute(SetGeorefCommand(Georef(19)))
    assert read_georef(doc) == Georef(19) and document.dirty
    history.execute(SetGeorefCommand(Georef(18, True, "PSAD56", (-279, 175, -379))))
    assert read_georef(doc).datum == "PSAD56"
    history.undo()
    assert read_georef(doc) == Georef(19)
    history.undo()
    assert read_georef(doc) is None
    # nothing left behind: no dictionary, no orphan XRECORD
    assert doc.rootdict.get(georef_mod.DICT_NAME, None) is None
    assert not [o for o in doc.objects if o.dxftype() == "XRECORD"]
    history.redo()
    assert read_georef(doc) == Georef(19)
    # removing explicitly, and undoing that
    history.execute(SetGeorefCommand(None))
    assert read_georef(doc) is None
    history.undo()
    assert read_georef(doc) == Georef(19)


def test_the_georef_survives_dxf_and_dwg(tmp_path):
    from formats.dwg_bridge import find_dwg2dxf, find_dxf2dwg, load_dwg

    document, history = _document()
    wanted = Georef(19, False, "PSAD56", (-279.0, 175.0, -379.0))
    history.execute(SetGeorefCommand(wanted))
    document.doc.modelspace().add_line((0, 0), (1, 1))
    dxf = tmp_path / "geo.dxf"
    document.save_as(dxf)
    assert read_georef(Document.load(dxf).doc) == wanted
    if find_dxf2dwg() is None or find_dwg2dxf() is None:
        pytest.skip("LibreDWG converters not built")
    dwg = tmp_path / "geo.dwg"
    document.save_as(dwg, "r2000")
    loaded = load_dwg(dwg)
    doc = loaded[0] if isinstance(loaded, tuple) else loaded
    back = doc if isinstance(doc, Document) else Document(doc)
    assert read_georef(back.doc) == wanted


def test_describe_speaks_both_languages():
    assert actions.describe(Georef(19)) == "WGS84, UTM zone 19 S"
    assert actions.describe(Georef(18, True, "PSAD56", (-279, 175, -379))) == \
        "PSAD56, UTM zone 18 N (shift to WGS84 -279, 175, -379 m)"
    i18n.register_pack_dir(PACK)
    i18n.set_language("es")
    try:
        assert actions.describe(Georef(19)) == "WGS84, zona UTM 19 S"
    finally:
        i18n.set_language("en")
        i18n.unregister_pack_dir(PACK)


def test_the_descriptive_report_takes_datum_and_zone_from_the_georef():
    from plugins.topografia import actions as topo

    document, history = _document()
    lot = document.doc.modelspace().add_lwpolyline([(0, 0), (12, 0), (12, 10), (0, 10)], close=True)
    assert "datum WGS84, UTM zone 19 S" in topo.memoria_for(document, lot, "L", "", 0, {}).text()
    history.execute(SetGeorefCommand(Georef(18, True, "PSAD56", (-279, 175, -379))))
    assert "datum PSAD56, UTM zone 18 N" in topo.memoria_for(document, lot, "L", "", 0, {}).text()


# -- the tools, headless ------------------------------------------------------------------

class _Services:
    def __init__(self, document):
        self.document = document


class _Harness:
    def __init__(self, document=None):
        self.document, self.history = _document() if document is None else (document, History(document))
        self.finished = False
        self.echoed: list[str] = []
        self.prompts: list[str] = []
        self.ctx = ToolContext(
            execute=self.history.execute, prompt=self.prompts.append,
            echo=self.echoed.append, finish=lambda: setattr(self, "finished", True),
            undo_last=self.history.undo, services=_Services(self.document))

    @property
    def doc(self):
        return self.document.doc


def test_georef_tool_asks_zone_hemisphere_and_datum():
    from plugins.terreno.tools import GeorefTool

    h = _Harness()
    tool = GeorefTool(h.ctx)
    tool.start()
    assert h.prompts[-1].startswith("UTM zone number or [Longitude/Remove] <19>:")
    assert tool.on_option("70")                              # not a zone
    assert "1 to 60" in h.echoed[-1]
    assert tool.on_option("19")
    assert h.prompts[-1] == "Hemisphere [North/South] <South>:"
    assert tool.on_option("S")
    assert h.prompts[-1] == "Datum [WGS84/PSAD56] <WGS84>:"
    assert tool.on_option("W")
    assert h.finished and read_georef(h.doc) == Georef(19)
    assert h.echoed[-1] == "Drawing georeferenced: WGS84, UTM zone 19 S"
    h.history.undo()
    assert read_georef(h.doc) is None


def test_georef_tool_enter_takes_every_default_and_reports_the_current_one():
    from plugins.terreno.tools import GeorefTool

    h = _Harness()
    h.history.execute(SetGeorefCommand(Georef(18, True)))
    tool = GeorefTool(h.ctx)
    tool.start()
    assert h.echoed[-1] == "Drawing georeferenced: WGS84, UTM zone 18 N"
    assert "<18>" in h.prompts[-1]
    tool.on_enter()
    assert "<North>" in h.prompts[-1]
    tool.on_enter()
    tool.on_enter()
    assert h.finished and read_georef(h.doc) == Georef(18, True)


def test_georef_tool_works_the_zone_out_from_a_longitude_and_takes_psad56():
    from plugins.terreno.tools import GeorefTool

    h = _Harness()
    tool = GeorefTool(h.ctx)
    tool.start()
    assert tool.on_option("L")
    assert tool.on_option("200")                             # not a longitude
    assert "between -180 and 180" in h.echoed[-1]
    assert tool.on_option("-75.1")
    assert h.echoed[-1] == "Longitude -75.1° lies in UTM zone 18."
    tool.on_enter()                                          # South
    assert tool.on_option("P")
    assert h.prompts[-1] == "Shift to WGS84 dX,dY,dZ in metres <-279,175,-379>:"
    assert tool.on_option("1,2")                             # not three numbers
    assert "Three numbers" in h.echoed[-1]
    assert tool.on_option("-288, 175, -376")
    assert h.finished
    assert read_georef(h.doc) == Georef(18, False, "PSAD56", (-288.0, 175.0, -376.0))
    assert h.echoed[-1] == ("Drawing georeferenced: PSAD56, UTM zone 18 S "
                            "(shift to WGS84 -288, 175, -376 m)")
    # Enter on the shift keeps the proposed one
    h2 = _Harness()
    t2 = GeorefTool(h2.ctx)
    t2.start()
    t2.on_option("19")
    t2.on_option("S")
    t2.on_option("PSAD56")
    t2.on_enter()
    assert read_georef(h2.doc).shift == (-279.0, 175.0, -379.0)


def test_georef_tool_removes_the_declaration():
    from plugins.terreno.tools import GeorefTool

    h = _Harness()
    tool = GeorefTool(h.ctx)
    tool.start()
    assert tool.on_option("R")
    assert h.finished and h.echoed[-1] == "The drawing is not georeferenced."
    h2 = _Harness()
    h2.history.execute(SetGeorefCommand(Georef(19)))
    t2 = GeorefTool(h2.ctx)
    t2.start()
    assert t2.on_option("Remove")
    assert h2.finished and read_georef(h2.doc) is None and h2.echoed[-1] == "Georeference removed."
    h2.history.undo()
    assert read_georef(h2.doc) == Georef(19)


def test_latlon_tool_needs_a_georef_then_reads_picked_points():
    from plugins.terreno.tools import LatLonTool

    h = _Harness()
    tool = LatLonTool(h.ctx)
    tool.start()
    assert h.finished and "run GEOREF first" in h.echoed[-1]

    h = _Harness()
    h.history.execute(SetGeorefCommand(Georef(19)))
    tool = LatLonTool(h.ctx)
    tool.start()
    assert h.prompts[-1] == "Pick a point or [Type]:"
    tool.on_point(AREQUIPA)
    line = h.echoed[-1]
    assert line.startswith("Lat -16.398889  Lon -71.536944  (16°23'56.00\" S, 71°32'13.00\" W)")
    assert line.endswith("at E=229038.488 N=8185246.521")
    assert not h.finished and h.prompts[-1] == "Pick a point or [Type]:"    # keeps reading
    tool.on_enter()
    assert h.finished


def test_latlon_tool_places_a_point_from_typed_coordinates():
    from plugins.terreno.tools import LatLonTool

    h = _Harness()
    h.history.execute(SetGeorefCommand(Georef(19)))
    tool = LatLonTool(h.ctx)
    tool.start()
    assert not tool.wants_raw_text()
    assert tool.on_option("T")
    assert tool.wants_raw_text()                             # DMS carries spaces
    assert tool.on_option("no se")
    assert h.echoed[-1] == "Cannot read a latitude and longitude in no se."
    assert tool.on_option("16°23'56.0\" S 71°32'13.0\" W")
    assert h.echoed[-1].startswith("E=229038.4") and "(WGS84 UTM 19 S)" in h.echoed[-1]
    assert h.prompts[-1] == "Mark it with a point? [Yes/No] <Yes>:"
    tool.on_enter()                                          # Yes
    assert h.finished
    msp = h.doc.modelspace()
    points = [e for e in msp if e.dxftype() == "POINT"]
    texts = [e for e in msp if e.dxftype() == "TEXT"]
    assert len(points) == 1 and len(texts) == 1
    assert points[0].dxf.layer == "TERRENO-GEO" and texts[0].dxf.layer == "TERRENO-GEO"
    assert points[0].dxf.location.x == pytest.approx(229038.49, abs=0.05)
    assert texts[0].dxf.text == "16°23'56.00\" S, 71°32'13.00\" W"
    assert [(round(lat, 4), round(lon, 4)) for _e, lat, lon in actions.geo_points(h.document)] == [(-16.3989, -71.5369)]
    h.history.undo()
    assert not [e for e in msp if e.dxftype() in ("POINT", "TEXT")]
    # No leaves nothing
    h2 = _Harness()
    h2.history.execute(SetGeorefCommand(Georef(19)))
    t2 = LatLonTool(h2.ctx)
    t2.start()
    t2.on_option("T")
    t2.on_option("-16.398889, -71.536944")
    assert t2.on_option("N")
    assert h2.finished and not list(h2.doc.modelspace())


def test_latlon_tool_refuses_a_paper_layout():
    from plugins.terreno.tools import LatLonTool

    h = _Harness()
    h.history.execute(SetGeorefCommand(Georef(19)))
    h.document.active_layout = "Layout1"
    tool = LatLonTool(h.ctx)
    tool.start()
    assert h.finished and h.echoed[-1] == "Geographic coordinates are read in model space."


def test_the_document_hook_says_what_the_drawing_declares():
    from plugins.terreno import _on_document_open

    echoed = []

    class Ctx:
        echo = staticmethod(echoed.append)

    document, history = _document()
    _on_document_open(Ctx(), document)
    assert echoed == []
    history.execute(SetGeorefCommand(Georef(19)))
    _on_document_open(Ctx(), document)
    assert echoed == ["Drawing georeferenced: WGS84, UTM zone 19 S"]


# -- through the window ------------------------------------------------------------------

def test_the_plugin_is_bundled_on_with_its_menu_names_and_options_page(qapp):
    from PySide6.QtCore import QSettings

    from plugins.terreno import prefs
    from views.main_window import MainWindow
    from views.options_dialog import OptionsDialog

    win = MainWindow()
    settings = QSettings()
    try:
        assert win.plugins.is_active("terreno")
        assert "Terrain" in [a.text() for a in win._menu_bar.actions()]
        for name in ("GEOREF", "LATLON"):
            assert name in win.dispatcher._commands
        assert "plugin_terreno_toolbar" not in [
            t.objectName() for t in win.findChildren(type(win._draw_toolbar))]
        i18n.set_language("es")
        try:
            assert i18n.command_names().get("GEORREFERENCIAR") == "GEOREF"
            assert i18n.command_names().get("GEOGRAFICAS") == "LATLON"
            assert win.dispatcher.resolve_name("GEORREFERENCIAR") == "GEOREF"
        finally:
            i18n.set_language("en")
        # the options page, applied
        for key in (prefs.SETTING_ZONE, prefs.SETTING_HEMISPHERE, prefs.SETTING_SHIFT):
            settings.remove(key)
        dlg = OptionsDialog(win)
        tabs = [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]
        assert "Terrain" in tabs
        page = next(p for p in dlg._plugin_pages if type(p).__name__ == "TerrainOptionsPage")
        assert page.zone.value() == 19 and page.hemisphere.currentData() == "S"
        assert [b.value() for b in page.shift] == [-279.0, 175.0, -379.0]
        page.zone.setValue(18)
        page.hemisphere.setCurrentIndex(0)
        page.shift[0].setValue(-288.0)
        dlg.apply()
        assert prefs.default_zone() == 18 and prefs.default_northern() is True
        assert prefs.default_shift() == (-288.0, 175.0, -379.0)
        dlg.close()
    finally:
        for key in (prefs.SETTING_ZONE, prefs.SETTING_HEMISPHERE, prefs.SETTING_SHIFT):
            settings.remove(key)
        win.close()
    assert prefs.default_zone() == 19 and prefs.default_northern() is False
    assert prefs.default_shift() == datum.PSAD56_PERU_SHIFT
