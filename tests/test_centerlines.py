# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""CENTERMARK / CENTERLINE: the norm's chain-line axes on a circle.

A tester using the Center Mark got DIMCENTER's short continuous cross and
asked for what the norm draws: thin dash-dot axes running past the circle,
which is what AutoCAD 2017's CENTERMARK does (CENTERLTYPE Center2,
CENTEREXE past the outline, a cross of 0.1x the diameter and a 0.05x gap).
"""
from __future__ import annotations

import math

import pytest

from core import centerlines
from core.commands import History
from core.document import Document
from tools.base import ToolContext
from tools.dimension import CenterLineTool, CenterMarkTool


# -- geometry ------------------------------------------------------------------

def test_center_mark_is_a_cross_a_gap_and_axes_past_the_circle():
    prefs = centerlines.CenterSettings(exe=3.5, crosssize="0.1x",
                                       crossgap="0.05x")
    segs = centerlines.center_mark_segments((10.0, 20.0), 50.0, prefs)
    assert len(segs) == 6
    # the cross: 0.1 x diameter (100) = 10 each side of the centre
    assert ((0.0, 20.0), (20.0, 20.0)) in segs
    assert ((10.0, 10.0), (10.0, 30.0)) in segs
    # the axes: from the cross + gap (10 + 5) to the circle + CENTEREXE
    assert ((25.0, 20.0), (63.5, 20.0)) in segs
    assert ((-5.0, 20.0), (-43.5, 20.0)) in segs
    assert ((10.0, 35.0), (10.0, 73.5)) in segs
    assert ((10.0, 5.0), (10.0, -33.5)) in segs


def test_sizes_take_a_length_or_a_multiple_of_the_diameter():
    assert centerlines.parse_size("0.1x", 100.0, "1") == 10.0
    assert centerlines.parse_size("2.5", 100.0, "1x") == 2.5
    assert centerlines.parse_size("0,2X", 100.0, "1") == 20.0     # comma, capital
    assert centerlines.parse_size("garbage", 100.0, "0.05x") == 5.0
    assert centerlines.valid_size("0.1x") and centerlines.valid_size("3")
    assert not centerlines.valid_size("-1") and not centerlines.valid_size("abc")


def test_markexe_off_and_tiny_circles_give_the_cross_alone():
    off = centerlines.CenterSettings(markexe=False)
    assert len(centerlines.center_mark_segments((0, 0), 50.0, off)) == 2
    # a circle whose radius + CENTEREXE does not clear the cross and gap
    tiny = centerlines.CenterSettings(exe=0.0, crosssize="1", crossgap="1")
    assert len(centerlines.center_mark_segments((0, 0), 1.5, tiny)) == 2


def test_centerline_between_two_parallel_lines_is_the_midline_extended():
    a = ((0.0, 0.0), (100.0, 0.0))
    b = ((100.0, 10.0), (0.0, 10.0))           # drawn the other way round
    seg = centerlines.centerline_between(a, b, exe=3.5)
    assert seg == ((-3.5, 5.0), (103.5, 5.0))


def test_centerline_between_converging_lines_is_the_bisector():
    a = ((0.0, 0.0), (100.0, 0.0))
    b = ((0.0, 20.0), (100.0, 10.0))
    (x1, y1), (x2, y2) = centerlines.centerline_between(a, b, exe=0.0)
    assert (x1, y1) == (0.0, 10.0) and (x2, y2) == (100.0, 5.0)
    assert centerlines.centerline_between(a, ((5, 5), (5, 5)), 1.0) is None


# -- the command ----------------------------------------------------------------

def _document() -> Document:
    return Document.new()


def test_center_mark_draws_lines_on_the_chain_linetype_in_one_undo_step():
    document = _document()
    history = History()
    history.document = document
    circle = document.modelspace().add_circle((0, 0), 50)
    prefs = centerlines.CenterSettings(ltype="CENTER2")
    history.execute(centerlines.center_mark(circle, prefs))
    lines = document.modelspace().query("LINE")
    assert len(lines) == 6
    assert {ln.dxf.linetype for ln in lines} == {"CENTER2"}
    assert {ln.dxf.layer for ln in lines} == {"0"}, "the current layer"
    history.undo()
    assert len(document.modelspace().query("LINE")) == 0


def test_a_linetype_the_drawing_lacks_is_loaded_inside_the_same_step():
    document = _document()
    history = History()
    history.document = document
    assert "ACAD_ISO04W100" not in document.doc.linetypes
    circle = document.modelspace().add_circle((0, 0), 50)
    prefs = centerlines.CenterSettings(ltype="ACAD_ISO04W100")
    history.execute(centerlines.center_mark(circle, prefs))
    assert "ACAD_ISO04W100" in document.doc.linetypes
    lines = document.modelspace().query("LINE")
    assert {ln.dxf.linetype for ln in lines} == {"ACAD_ISO04W100"}
    # and it carries the long-dash dot, not a mangled pattern (the bug that
    # broke every ISO load until 2026-09-16)
    from core import linetypes as lt_ops
    assert lt_ops.pattern_of(document, "ACAD_ISO04W100") == pytest.approx(
        [24.0, -3.0, 0.0, -3.0])
    history.undo()
    assert "ACAD_ISO04W100" not in document.doc.linetypes
    assert len(document.modelspace().query("LINE")) == 0


def test_an_unknown_linetype_falls_back_to_center2():
    document = _document()
    circle = document.modelspace().add_circle((0, 0), 50)
    prefs = centerlines.CenterSettings(ltype="NO_SUCH_LINETYPE")
    cmd = centerlines.center_mark(circle, prefs)
    cmd.do(document)
    lines = document.modelspace().query("LINE")
    assert {ln.dxf.linetype for ln in lines} == {"CENTER2"}


def test_centerlayer_names_the_layer_and_creates_it_when_missing():
    document = _document()
    history = History()
    history.document = document
    circle = document.modelspace().add_circle((0, 0), 50)
    prefs = centerlines.CenterSettings(layer="EJES")
    history.execute(centerlines.center_mark(circle, prefs))
    assert "EJES" in document.doc.layers
    assert {ln.dxf.layer for ln in document.modelspace().query("LINE")} == {"EJES"}
    history.undo()
    assert "EJES" not in document.doc.layers


# -- the tools, the way the canvas drives them ---------------------------------

class _Harness:
    def __init__(self):
        self.document = Document.new()
        self.history = History()
        self.history.document = self.document
        self.finished = False
        self.echoed = []
        self.prompts = []
        harness = self

        class Pick:
            def pick_entity(self, point):
                best, best_d = None, 1.0
                for e in harness.document.modelspace():
                    if e.dxftype() == "CIRCLE":
                        c = e.dxf.center
                        d = abs(math.dist((c.x, c.y), point) - e.dxf.radius)
                    elif e.dxftype() == "LINE":
                        s, w = e.dxf.start, e.dxf.end
                        dx, dy = w.x - s.x, w.y - s.y
                        t = max(0.0, min(1.0, ((point[0] - s.x) * dx
                                               + (point[1] - s.y) * dy)
                                         / (dx * dx + dy * dy)))
                        d = math.dist(point, (s.x + t * dx, s.y + t * dy))
                    else:
                        continue
                    if d < best_d:
                        best, best_d = e, d
                return best

        self.ctx = ToolContext(
            execute=self.history.execute,
            prompt=self.prompts.append,
            echo=self.echoed.append,
            finish=lambda: setattr(self, "finished", True),
            services=Pick(),
        )

    @property
    def msp(self):
        return self.document.modelspace()


def test_centermark_tool_marks_every_circle_picked_until_enter(monkeypatch):
    monkeypatch.setattr(centerlines, "settings",
                        lambda: centerlines.CenterSettings())
    h = _Harness()
    h.msp.add_circle((0, 0), 50)
    h.msp.add_circle((200, 0), 20)
    tool = CenterMarkTool(h.ctx)
    tool.start()
    tool.on_point((50, 0))                 # on the first circle
    tool.on_point((220, 0))                # on the second
    assert len(h.msp.query("LINE")) == 12
    assert not h.finished, "CENTERMARK keeps asking, like AutoCAD"
    tool.on_point((500, 500))              # nothing there
    assert h.echoed[-1]
    tool.on_enter()
    assert h.finished
    h.history.undo()                       # one circle's mark per undo
    assert len(h.msp.query("LINE")) == 6


def test_centerline_tool_takes_two_lines(monkeypatch):
    monkeypatch.setattr(centerlines, "settings",
                        lambda: centerlines.CenterSettings(exe=2.0))
    h = _Harness()
    h.msp.add_line((0, 0), (100, 0))
    h.msp.add_line((0, 10), (100, 10))
    tool = CenterLineTool(h.ctx)
    tool.start()
    tool.on_point((50, 0))
    tool.on_point((50, 0))                 # the same line again: refused
    assert not h.finished and h.echoed[-1]
    tool.on_point((50, 10))
    assert h.finished
    lines = h.msp.query("LINE")
    assert len(lines) == 3
    axis = [ln for ln in lines if ln.dxf.linetype == "CENTER2"]
    assert len(axis) == 1
    s, e = axis[0].dxf.start, axis[0].dxf.end
    assert (s.x, s.y, e.x, e.y) == pytest.approx((-2.0, 5.0, 102.0, 5.0))


def test_the_commands_are_registered_and_localized(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        assert win.dispatcher.resolve_name("CENTERMARK") == "CENTERMARK"
        assert win.dispatcher.resolve_name("CENTERLINE") == "CENTERLINE"
        assert win.dispatcher.resolve_name("CENTEREXE") == "CENTEREXE"
    finally:
        win.close()


def test_centerexe_is_sheet_millimetres_scaled_to_the_drawing():
    """3.5 mm on paper: 3.5 units in a millimetre drawing at 1:1, 0.35 m in
    a metres plan at 1:100 -- the conversion the templates give text."""
    from core import templates

    mm = templates.new_document("mm")
    assert centerlines.annotation_scale(mm.doc) == pytest.approx(1.0)
    metres = templates.new_document("m")
    assert centerlines.annotation_scale(metres.doc) == pytest.approx(0.1)
    # a colleague's plan: metres, $INSUNITS unitless, 0.20-unit text at 1:1
    import ezdxf
    colleague = ezdxf.new("R2000")
    colleague.header["$INSUNITS"] = 0
    colleague.dimstyles.add("COTAS", dxfattribs={"dimtxt": 0.2, "dimscale": 1.0})
    colleague.header["$DIMSTYLE"] = "COTAS"
    assert centerlines.annotation_scale(colleague) == pytest.approx(0.08)
    circle = metres.modelspace().add_circle((0, 0), 5.0)
    prefs = centerlines.CenterSettings(exe=3.5, crosssize="1", crossgap="0.5")
    centerlines.center_mark(circle, prefs).do(metres)
    xs = sorted(max(ln.dxf.start.x, ln.dxf.end.x)
                for ln in metres.modelspace().query("LINE"))
    assert xs[-1] == pytest.approx(5.35), "radius + 0.35 m"
