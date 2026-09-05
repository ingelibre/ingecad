# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Topography plugin, T7 in the drawing: the report of a drawn lot (the
text inside names it), placed as MTEXT, and the areas of many lots as a
table and a CSV -- through the actions and through the tools, headless."""
from __future__ import annotations

from pathlib import Path

import pytest

from core.commands import History
from core.document import Document
from plugins.topografia import actions
from tools.base import ToolContext

LOT = [(100.0, 200.0), (112.0, 200.0), (112.0, 210.0), (100.0, 210.0)]      # 12 x 10


def _document():
    document = Document.new()
    return document, History(document)


def test_the_lot_is_named_by_the_text_inside_and_reported_clockwise_from_the_front():
    document, history = _document()
    msp = document.doc.modelspace()
    lot = msp.add_lwpolyline(LOT, close=True)
    msp.add_text("LOTE 12", dxfattribs={"height": 1.0}).set_placement((105.0, 205.0))
    msp.add_text("AFUERA", dxfattribs={"height": 1.0}).set_placement((150.0, 205.0))
    assert actions.lot_name(document, lot) == "LOTE 12"
    front = actions.front_side_index(lot, (106.0, 199.0))                      # the south side
    m = actions.memoria_for(document, lot, "LOTE 12", "Cayma, Arequipa", front,
                            {front: "Calle Los Arces"})
    assert m.boundaries[0].role == "front" and m.boundaries[0].length == pytest.approx(12.0)
    assert m.boundaries[0].neighbour == "Calle Los Arces"
    assert m.boundaries[1].role == "right" and m.boundaries[1].length == pytest.approx(10.0)
    assert m.area == pytest.approx(120.0) and m.perimeter == pytest.approx(44.0)
    history.execute(actions.memoria_mtext(document, (130.0, 210.0), m.text(), 0.5))
    texts = [e for e in msp if e.dxftype() == "MTEXT"]
    assert len(texts) == 1 and "DESCRIPTIVE REPORT" in texts[0].plain_text()
    assert texts[0].dxf.layer == "TOPO-CUADROS"
    history.undo()
    assert not [e for e in msp if e.dxftype() == "MTEXT"]

    lots = actions.lots_of(document, [lot, msp.add_lwpolyline([(0, 0), (5, 0), (5, 5), (0, 5)], close=True),
                                      msp.add_line((0, 0), (1, 1))])
    assert [(l.name, l.area) for l in lots] == [("LOTE 12", pytest.approx(120.0)), ("LOT 2", pytest.approx(25.0))]
    history.execute(actions.lots_table(document, lots, (200.0, 200.0)))
    texts = [e.dxf.text for e in msp if e.dxftype() == "TEXT"]
    assert "AREAS BY LOT" in texts and "145.00" in texts and "TOTAL" in texts


class _Services:
    def __init__(self, document):
        self.document = document


class _Harness:
    def __init__(self):
        self.document, self.history = _document()
        self.finished = False
        self.echoed: list[str] = []
        self.answers: list = []
        self.ctx = ToolContext(
            execute=self.history.execute, prompt=self.echoed.append,
            echo=self.echoed.append, finish=lambda: setattr(self, "finished", True),
            ask_text=lambda prompt, default="": self.answers.pop(0) if self.answers else None,
            undo_last=self.history.undo, services=_Services(self.document))

    @property
    def msp(self):
        return self.document.doc.modelspace()


def test_memoria_tool_asks_side_by_side_and_writes_text_and_csv(tmp_path):
    from plugins.topografia.tools import MemoriaTool

    h = _Harness()
    lot = h.msp.add_lwpolyline(LOT, close=True)
    out = tmp_path / "memoria.txt"
    h.answers = [str(out)]
    tool = MemoriaTool(h.ctx)
    tool.start()
    tool.on_selection([lot])
    tool.on_point((106.0, 199.0))                                     # the front is the south side
    assert tool.wants_raw_text()
    # clockwise from V1 = (100, 200) the south side is the last one, V4-V1
    assert any("Front (V4-V1, 12.00 m) adjoins:" in line for line in h.echoed)
    assert tool.on_option("Calle Los Arces")
    assert tool.on_option("Lote 13")
    tool.on_enter()                                                   # back: not stated
    assert tool.on_option("Lote 11")
    assert tool.on_option("LOTE 12, MZ. B")                           # name
    assert tool.on_option("Cayma, Arequipa, Arequipa")                # location
    assert out.exists() and out.with_suffix(".csv").exists()
    text = out.read_text(encoding="utf-8")
    assert "Front: adjoins Calle Los Arces, in a straight line of 12.00 m" in text
    assert "Back: adjoins (neighbour not stated)" in text
    assert "Left (entering): adjoins Lote 11" in text
    assert any("LOTE 12, MZ. B: 120.00 m², 44.00 m" in line for line in h.echoed)
    assert tool.on_option("Y")                                        # place it
    tool.on_point((130.0, 210.0))
    assert h.finished
    assert [e for e in h.msp if e.dxftype() == "MTEXT"]


def test_areareport_tool_tables_and_writes(tmp_path):
    from plugins.topografia.tools import AreaReportTool

    h = _Harness()
    a = h.msp.add_lwpolyline(LOT, close=True)
    b = h.msp.add_lwpolyline([(0, 0), (5, 0), (5, 5), (0, 5)], close=True)
    out = tmp_path / "areas.csv"
    h.answers = [str(out)]
    tool = AreaReportTool(h.ctx)
    tool.start()
    tool.on_selection([a, b])
    assert any("2 lots, total 145.00 m²" in line for line in h.echoed)
    tool.on_point((200.0, 200.0))
    assert h.finished
    assert out.read_text(encoding="utf-8").splitlines()[-1] == "TOTAL,145.00,"
    assert "AREAS BY LOT" in [e.dxf.text for e in h.msp if e.dxftype() == "TEXT"]
