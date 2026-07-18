# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Dimension creation: DIMLINEAR, DIMALIGNED, DIMRADIUS, DIMDIAMETER."""
from __future__ import annotations

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
        # nearest circle/arc whose centre is close enough (test helper)
        import math
        best = None
        for e in self.document.modelspace():
            if e.dxftype() in ("CIRCLE", "ARC"):
                c = e.dxf.center
                if math.dist((c.x, c.y), point) <= e.dxf.radius + 1:
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


def test_dimension_uses_current_style():
    h = Harness()
    h.document.doc.header["$DIMSTYLE"] = "Acot-100"
    tool = DimLinearTool(h.ctx)
    tool.start()
    for p in ((0, 0), (10, 0), (5, 4)):
        tool.on_point(p)
    assert h.msp.query("DIMENSION")[0].dxf.dimstyle == "Acot-100"
