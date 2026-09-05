# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Topography plugin, T7: the descriptive report of a lot and the report
of areas by lot -- the pure text and, in the drawing, the tools."""
from __future__ import annotations

from pathlib import Path

import pytest

from core import i18n
from core.commands import History
from core.document import Document
from plugins.topografia import memoria
from tools.base import ToolContext

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def test_roles_walk_clockwise_from_the_front():
    assert memoria.side_roles(4, 0) == ["front", "right", "back", "left"]
    assert memoria.side_roles(4, 2) == ["back", "left", "front", "right"]
    assert memoria.side_roles(5, 1) == ["side 5", "front", "side 2", "side 3", "side 4"]
    assert memoria.role_label("right") == "Right (entering)"
    assert memoria.role_label("side 3") == "Side 3"


def _rows():
    return [["V1", "V1-V2", "10.00", "N 0°00'00\" E", "90°00'00\"", "100.00", "200.00"],
            ["V2", "V2-V3", "12.00", "N 90°00'00\" E", "90°00'00\"", "100.00", "210.00"],
            ["V3", "V3-V4", "10.00", "S 0°00'00\" E", "90°00'00\"", "112.00", "210.00"],
            ["V4", "V4-V1", "12.00", "N 90°00'00\" W", "90°00'00\"", "112.00", "200.00"]]


def test_the_report_reads_like_a_filing_in_both_languages():
    m = memoria.build_memoria("LOTE 12, MZ. B", "Cayma, Arequipa, Arequipa", _rows(), 120.0, 44.0,
                              front=1, neighbours={1: "Calle Los Arces", 3: "Lote 11"})
    assert [b.role for b in m.boundaries] == ["front", "right", "back", "left"]
    assert m.boundaries[0].side == "V2-V3" and m.boundaries[0].neighbour == "Calle Los Arces"
    text = m.text()
    assert text.startswith("DESCRIPTIVE REPORT\nLOTE 12, MZ. B\n")
    assert "Front: adjoins Calle Los Arces, in a straight line of 12.00 m (side V2-V3" in text
    assert "Right (entering): adjoins (neighbour not stated)" in text
    assert "AREA: 120.00 m²" in text and "PERIMETER: 44.00 m" in text
    assert "TECHNICAL DATA (datum WGS84, UTM zone 19 S)" in text
    assert "V1        V1-V2      10.00" in text
    csv = m.csv()
    assert csv.splitlines()[0] == "vertex,side,distance,bearing,interior_angle,east,north"
    assert csv.splitlines()[-2] == "area,120.00"
    # the plugin's pack joins the language only while the plugin is on:
    # register it the way activation does
    pack = Path(__file__).resolve().parent.parent / "plugins" / "topografia" / "i18n"
    i18n.register_pack_dir(pack)
    i18n.set_language("es")
    try:
        es = m.text()
        assert es.startswith("MEMORIA DESCRIPTIVA\n")
        assert "Por el frente: colinda con Calle Los Arces, en línea recta de 12.00 m" in es
        assert "Por la derecha entrando:" in es and "Por el fondo:" in es and "Por la izquierda entrando:" in es
        assert "ÁREA: 120.00 m²" in es and "PERÍMETRO: 44.00 m" in es
    finally:
        i18n.set_language("en")
        i18n.unregister_pack_dir(pack)


def test_lots_rows_and_csv_total():
    lots = [memoria.Lot("LOTE 1", 120.0, 44.0), memoria.Lot("LOTE 2", 80.5, 36.0)]
    rows = memoria.lots_rows(lots)
    assert rows[0] == ["LOTE 1", "120.00", "44.00"] and rows[-1] == ["TOTAL", "200.50", ""]
    assert memoria.lots_csv(lots).splitlines()[-1] == "TOTAL,200.50,"
