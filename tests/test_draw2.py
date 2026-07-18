# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Phase 6 draw tools: ellipse, point, text, mtext, arc SCE."""
from __future__ import annotations

import math

import ezdxf
import pytest

from core.commands import History
from core.document import Document
from tools.base import ToolContext
from tools.draw import ArcTool, EllipseTool, MTextTool, PointTool, TextTool


class Harness:
    def __init__(self, text_answer="Hola"):
        self.document = Document(ezdxf.new("R2018", setup=True))
        self.history = History(self.document)
        self.finished = False
        self.ctx = ToolContext(
            execute=self.history.execute,
            prompt=lambda *_a: None,
            echo=lambda *_a: None,
            finish=lambda: setattr(self, "finished", True),
            ask_text=lambda *_a: text_answer,
        )

    @property
    def msp(self):
        return self.document.modelspace()


def test_ellipse_axis_mode():
    h = Harness()
    tool = EllipseTool(h.ctx)
    tool.start()
    tool.on_point((-10, 0))     # axis endpoint 1
    tool.on_point((10, 0))      # axis endpoint 2 -> major length 10, center 0
    tool.on_point((0, 4))       # distance to other axis: 4 -> ratio 0.4
    e = h.msp.query("ELLIPSE")[0]
    assert e.dxf.center.x == pytest.approx(0.0)
    assert e.dxf.ratio == pytest.approx(0.4)
    assert math.hypot(e.dxf.major_axis.x, e.dxf.major_axis.y) == pytest.approx(10.0)


def test_ellipse_center_mode():
    h = Harness()
    tool = EllipseTool(h.ctx)
    tool.start()
    assert tool.on_option("C")
    tool.on_point((0, 0))       # center
    tool.on_point((10, 0))      # major axis endpoint -> length 10
    tool.on_point((0, 5))       # distance to other axis 5 -> ratio 0.5
    e = h.msp.query("ELLIPSE")[0]
    assert e.dxf.ratio == pytest.approx(0.5)


def test_point_repeats():
    h = Harness()
    tool = PointTool(h.ctx)
    tool.start()
    tool.on_point((1, 1))
    tool.on_point((2, 2))
    tool.on_point((3, 3))
    assert len(h.msp.query("POINT")) == 3
    assert not h.finished          # stays active until Enter/Esc


def _type(tool, s):
    for ch in s:
        tool.on_char(ch)


def test_text_tool_in_place_typing():
    # DTEXT: point -> height -> rotation -> type in place; Esc finishes.
    h = Harness()
    tool = TextTool(h.ctx)
    tool.start()
    tool.on_point((5, 5))
    tool.on_option("3")            # height 3
    tool.on_option("45")           # rotation 45
    assert tool.typing
    _type(tool, "PLANO")
    tool.on_backspace()            # -> PLAN
    _type(tool, "O")               # -> PLANO
    tool.finish_typing()           # Esc keeps the text
    t = h.msp.query("TEXT")[0]
    assert t.dxf.text == "PLANO"
    assert t.dxf.height == pytest.approx(3.0)
    assert t.dxf.rotation == pytest.approx(45.0)
    assert h.finished


def test_text_tool_multiple_lines():
    # Enter commits a line and drops to a new one below (separate TEXT each).
    h = Harness()
    tool = TextTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))
    tool.on_enter()               # default height
    tool.on_enter()               # rotation 0 -> begin typing
    _type(tool, "linea uno")
    tool.on_enter()               # commit, new line below
    _type(tool, "linea dos")
    tool.finish_typing()
    texts = sorted(t.dxf.text for t in h.msp.query("TEXT"))
    assert texts == ["linea dos", "linea uno"]
    # second line sits 1.5*height below the first
    ys = sorted(t.dxf.insert.y for t in h.msp.query("TEXT"))
    assert ys[0] == pytest.approx(-1.5 * TextTool.default_height)


def test_mtext_tool():
    h = Harness(text_answer="línea 1\nlínea 2")
    tool = MTextTool(h.ctx)
    tool.start()
    tool.on_point((0, 10))
    tool.on_point((40, 0))
    m = h.msp.query("MTEXT")[0]
    assert "línea 1" in m.text
    assert m.dxf.width == pytest.approx(40.0)


def test_arc_start_center_end():
    h = Harness()
    tool = ArcTool(h.ctx)
    tool.start()
    tool.on_point((10, 0))        # start
    assert tool.on_option("C")    # switch to Start/Center/End
    tool.on_point((0, 0))         # center -> radius 10
    tool.on_point((0, 10))        # end direction (90 deg)
    arc = h.msp.query("ARC")[0]
    assert arc.dxf.radius == pytest.approx(10.0)
    assert arc.dxf.start_angle == pytest.approx(0.0)
    assert arc.dxf.end_angle == pytest.approx(90.0)


def test_arc_three_point_still_works():
    h = Harness()
    tool = ArcTool(h.ctx)
    tool.start()
    for p in ((0, 0), (5, 5), (10, 0)):
        tool.on_point(p)
    assert len(h.msp.query("ARC")) == 1
