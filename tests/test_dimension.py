# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Dimension creation: DIMLINEAR, DIMALIGNED, DIMRADIUS, DIMDIAMETER."""
from __future__ import annotations

import math

import ezdxf
import pytest

from core import actions
from core.commands import History
from core.document import Document
from tools.base import ToolContext
from tools.dimension import (
    DimAlignedTool,
    DimDiameterTool,
    DimLinearTool,
    DimRadiusTool,
)


class Services:
    def __init__(self, document):
        self.document = document

    def pick_entity(self, point):
        import math
        best = None
        for e in self.document.modelspace():
            t = e.dxftype()
            if t in ("CIRCLE", "ARC"):
                c = e.dxf.center
                if math.dist((c.x, c.y), point) <= e.dxf.radius + 1:
                    best = e
            elif t == "LINE":
                s, w = e.dxf.start, e.dxf.end
                # distance from point to the segment
                dx, dy = w.x - s.x, w.y - s.y
                L2 = dx * dx + dy * dy or 1.0
                u = max(0.0, min(1.0, ((point[0]-s.x)*dx + (point[1]-s.y)*dy)/L2))
                px, py = s.x + u*dx, s.y + u*dy
                if math.dist((px, py), point) <= 0.5:
                    best = e
        return best


class Harness:
    def __init__(self):
        self.document = Document.new()
        self.history = History(self.document)
        self.finished = False
        self.ctx = ToolContext(
            execute=self.history.execute,
            prompt=lambda *_a: None,
            echo=lambda *_a: None,
            finish=lambda: setattr(self, "finished", True),
            services=Services(self.document),
        )

    @property
    def msp(self):
        return self.document.modelspace()


def test_linear_dim_horizontal():
    h = Harness()
    tool = DimLinearTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))
    tool.on_point((10, 0))
    tool.on_point((5, 4))          # dim line above -> horizontal
    dims = h.msp.query("DIMENSION")
    assert len(dims) == 1
    assert dims[0].get_measurement() == pytest.approx(10.0)
    assert h.finished


def test_linear_dim_vertical():
    h = Harness()
    tool = DimLinearTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))
    tool.on_point((0, 8))
    tool.on_point((4, 4))          # dim line to the side -> vertical
    assert h.msp.query("DIMENSION")[0].get_measurement() == pytest.approx(8.0)


def test_linear_dim_undo_removes_dim_and_block():
    h = Harness()
    tool = DimLinearTool(h.ctx)
    tool.start()
    for p in ((0, 0), (10, 0), (5, 4)):
        tool.on_point(p)
    block = h.msp.query("DIMENSION")[0].dxf.geometry
    assert block in h.document.doc.blocks
    h.history.undo()
    assert len(h.msp.query("DIMENSION")) == 0
    assert block not in h.document.doc.blocks


def test_aligned_dim_measures_true_length():
    h = Harness()
    tool = DimAlignedTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))
    tool.on_point((3, 4))          # length 5
    tool.on_point((0, 4))          # offset to a side
    assert h.msp.query("DIMENSION")[0].get_measurement() == pytest.approx(5.0)


def test_radius_dim_on_circle():
    h = Harness()
    h.msp.add_circle((0, 0), 6)
    tool = DimRadiusTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))          # picks the circle
    tool.on_point((6, 0))          # dimension line location
    assert len(h.msp.query("DIMENSION")) == 1
    assert h.finished


def test_diameter_dim_on_circle():
    h = Harness()
    h.msp.add_circle((0, 0), 6)
    tool = DimDiameterTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))
    tool.on_point((6, 0))
    assert len(h.msp.query("DIMENSION")) == 1


def test_linear_dim_select_object():
    # Enter on the first prompt -> pick a line -> it dimensions the whole line.
    h = Harness()
    h.msp.add_line((2, 2), (12, 2))
    tool = DimLinearTool(h.ctx)
    tool.start()
    tool.on_enter()                # switch to select-object mode
    assert tool.entity_picker is True
    tool.on_point((7, 2))          # click on the line
    assert tool._p1 is not None and tool._p2 is not None
    assert tool.entity_picker is False   # snapping returns for the location
    tool.on_point((7, 6))          # place the dimension line
    dims = h.msp.query("DIMENSION")
    assert len(dims) == 1
    assert dims[0].get_measurement() == pytest.approx(10.0)


def test_linear_preview_dimension():
    # While placing, a rich dimension preview (frame + measurement) is offered.
    h = Harness()
    tool = DimLinearTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))
    assert tool.preview_dimension((0, 2)) is None    # only one point yet
    tool.on_point((10, 0))
    dim = tool.preview_dimension((5, 4))             # cursor above -> horizontal
    assert dim["d1"] == (0, 4) and dim["d2"] == (10, 4)
    assert dim["text"] == "10.00"
    # cursor to the side -> vertical measurement
    side = tool.preview_dimension((14, 0))
    assert side["text"] == "0.00"      # p1,p2 share Y, vertical extent is 0


def test_aligned_preview_measures_true_length():
    h = Harness()
    tool = DimAlignedTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))
    tool.on_point((3, 4))
    dim = tool.preview_dimension((0, 4))
    assert dim["text"] == "5.00"


class FixedPick:
    """pick_entity always returns one preset entity (option-flow tests)."""

    def __init__(self, entity):
        self._entity = entity

    def pick_entity(self, point):
        return self._entity


# -- wave B: Mtext/Text/Angle + Horizontal/Vertical/Rotated --------------------

def test_linear_text_override_with_placeholder():
    h = Harness()
    tool = DimLinearTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))
    tool.on_point((10, 0))
    assert tool.on_option("T")            # Text option at the location prompt
    assert tool.on_option("<> m")         # <> stands for the measurement
    tool.on_point((5, 4))
    dim = h.msp.query("DIMENSION")[0]
    assert dim.dxf.text == "<> m"
    assert h.finished


def test_linear_text_enter_keeps_measurement():
    h = Harness()
    tool = DimLinearTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))
    tool.on_point((10, 0))
    assert tool.on_option("T")
    tool.on_enter()                       # empty Enter -> keep <measured>
    tool.on_point((5, 4))
    assert h.msp.query("DIMENSION")[0].dxf.text == "<>"


def test_linear_angle_rotates_text_only():
    h = Harness()
    tool = DimLinearTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))
    tool.on_point((10, 0))
    assert tool.on_option("A")
    assert tool.on_option("30")
    tool.on_point((5, 4))
    dim = h.msp.query("DIMENSION")[0]
    assert dim.dxf.text_rotation == pytest.approx(30.0)
    assert dim.get_measurement() == pytest.approx(10.0)   # measurement intact


def test_linear_forced_vertical():
    h = Harness()
    tool = DimLinearTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))
    tool.on_point((3, 4))
    assert tool.on_option("V")
    tool.on_point((2, 10))                # auto rule would say horizontal here
    assert h.msp.query("DIMENSION")[0].get_measurement() == pytest.approx(4.0)


def test_linear_rotated_projects_measurement():
    h = Harness()
    tool = DimLinearTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))
    tool.on_point((10, 0))
    assert tool.on_option("R")
    assert tool.on_option("45")
    tool.on_point((5, 6))
    m = h.msp.query("DIMENSION")[0].get_measurement()
    assert m == pytest.approx(10 * math.cos(math.radians(45)))


def test_linear_select_circle_quadrant_rule():
    # Official: a pick near the N/S quadrant -> horizontal (W-E endpoints).
    h = Harness()
    circle = h.msp.add_circle((5, 5), 3)
    h.ctx.services = FixedPick(circle)
    tool = DimLinearTool(h.ctx)
    tool.start()
    tool.on_enter()                       # select-object mode
    tool.on_point((5, 7.9))               # near north
    assert tool._p1 == (2, 5) and tool._p2 == (8, 5)
    tool.on_point((5, 12))
    assert h.msp.query("DIMENSION")[0].get_measurement() == pytest.approx(6.0)


def test_aligned_select_circle_uses_pick_diameter():
    h = Harness()
    circle = h.msp.add_circle((0, 0), 5)
    h.ctx.services = FixedPick(circle)
    tool = DimAlignedTool(h.ctx)
    tool.start()
    tool.on_enter()
    tool.on_point((3, 3))                 # diameter through the pick (45 deg)
    assert tool._p1[0] == pytest.approx(-tool._p2[0])
    assert math.dist(tool._p1, tool._p2) == pytest.approx(10.0)


def test_linear_select_polyline_segment():
    h = Harness()
    pl = h.msp.add_lwpolyline([(0, 0), (10, 0), (10, 8)])
    h.ctx.services = FixedPick(pl)
    tool = DimLinearTool(h.ctx)
    tool.start()
    tool.on_enter()
    tool.on_point((5, 0.1))               # nearest the bottom segment
    assert tool._p1 == (0, 0) and tool._p2 == (10, 0)


def test_radius_text_and_angle_options():
    h = Harness()
    h.msp.add_circle((0, 0), 6)
    tool = DimRadiusTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))                 # picks the circle
    assert tool.on_option("T")
    assert tool.on_option("<> TYP")
    assert tool.on_option("A")
    assert tool.on_option("15")
    tool.on_point((6, 0))
    dim = h.msp.query("DIMENSION")[0]
    assert dim.dxf.text == "<> TYP"
    assert dim.dxf.text_rotation == pytest.approx(15.0)


def test_preview_text_substitutes_placeholder():
    h = Harness()
    tool = DimLinearTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))
    tool.on_point((10, 0))
    assert tool.on_option("T")
    assert tool.on_option("<> m")
    assert tool.preview_dimension((5, 4))["text"] == "10.00 m"


def test_dimension_uses_current_style():
    h = Harness()
    h.document.doc.header["$DIMSTYLE"] = "Acot-100"
    tool = DimLinearTool(h.ctx)
    tool.start()
    for p in ((0, 0), (10, 0), (5, 4)):
        tool.on_point(p)
    assert h.msp.query("DIMENSION")[0].dxf.dimstyle == "Acot-100"
