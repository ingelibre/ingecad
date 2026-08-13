# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""v0.2 wave A: XLINE, RAY, DIVIDE, MEASURE, REVCLOUD."""
from __future__ import annotations

import math

import pytest

from core import actions
from core.commands import History
from core.document import Document
from tools.base import ToolContext
from tools.construct import (
    DivideTool, MeasureTool, RayTool, RevcloudTool, XlineTool)


@pytest.fixture(autouse=True)
def _fresh():
    RevcloudTool.arc_length = 5.0
    RevcloudTool.style = "Normal"
    RevcloudTool.last_mode = "Freehand"
    XlineTool._offset = 1.0
    yield


class Harness:
    def __init__(self):
        self.document = Document.new()
        self.history = History(self.document)
        self.prompts: list[str] = []
        self.finished = False
        self.ctx = ToolContext(
            execute=self.history.execute,
            prompt=self.prompts.append,
            echo=self.prompts.append,
            finish=lambda: setattr(self, "finished", True),
            undo_last=self.history.undo,
        )

    @property
    def msp(self):
        return self.document.modelspace()


class PickServices:
    def __init__(self, entity, blocks=()):
        self._entity = entity
        self._blocks = list(blocks)

    def pick_entity(self, point):
        return self._entity

    def block_names(self):
        return self._blocks


# -- XLINE / RAY ---------------------------------------------------------------

def test_xline_two_point_repeats():
    h = Harness()
    tool = XlineTool(h.ctx)
    tool.start()
    tool.on_point((0.0, 0.0))
    tool.on_point((10.0, 10.0))
    tool.on_point((10.0, 0.0))          # second xline through the same root
    xs = h.msp.query("XLINE")
    assert len(xs) == 2
    u = xs[0].dxf.unit_vector
    assert (round(u.x, 6), round(u.y, 6)) == (round(math.cos(math.pi/4), 6),
                                              round(math.sin(math.pi/4), 6))


def test_xline_hor_ver_and_angle_reference():
    h = Harness()
    tool = XlineTool(h.ctx)
    tool.start()
    assert tool.on_option("H")
    tool.on_point((5.0, 5.0))
    tool.on_point((5.0, 9.0))
    assert len(h.msp.query("XLINE")) == 2
    assert h.msp.query("XLINE")[0].dxf.unit_vector.y == pytest.approx(0.0)

    h2 = Harness()
    line = h2.msp.add_line((0.0, 0.0), (10.0, 10.0))   # 45 degrees
    h2.ctx.services = PickServices(line)
    tool2 = XlineTool(h2.ctx)
    tool2.start()
    assert tool2.on_option("A")
    assert tool2.on_option("R")                        # Reference
    tool2.on_point((5.0, 5.0))                         # pick the line
    assert tool2.on_option("15")                       # 45 + 15 = 60
    tool2.on_point((0.0, 0.0))
    x = h2.msp.query("XLINE")[0]
    ang = math.degrees(math.atan2(x.dxf.unit_vector.y, x.dxf.unit_vector.x))
    assert ang == pytest.approx(60.0)


def test_xline_bisect_and_offset():
    h = Harness()
    tool = XlineTool(h.ctx)
    tool.start()
    assert tool.on_option("B")
    tool.on_point((0.0, 0.0))          # vertex
    tool.on_point((10.0, 0.0))         # start ray: 0 deg
    tool.on_point((0.0, 10.0))         # end ray: 90 deg -> bisector 45
    x = h.msp.query("XLINE")[0]
    ang = math.degrees(math.atan2(x.dxf.unit_vector.y, x.dxf.unit_vector.x))
    assert ang == pytest.approx(45.0)

    h2 = Harness()
    line = h2.msp.add_line((0.0, 0.0), (10.0, 0.0))
    h2.ctx.services = PickServices(line)
    tool2 = XlineTool(h2.ctx)
    tool2.start()
    assert tool2.on_option("O")
    assert tool2.on_option("3")        # distance
    tool2.on_point((5.0, 0.0))         # select the line
    tool2.on_point((5.0, 9.0))         # side above
    x = h2.msp.query("XLINE")[0]
    assert x.dxf.start.y == pytest.approx(3.0)


def test_ray_repeats_from_start():
    h = Harness()
    tool = RayTool(h.ctx)
    tool.start()
    tool.on_point((1.0, 1.0))
    tool.on_point((5.0, 1.0))
    tool.on_point((1.0, 5.0))
    rays = h.msp.query("RAY")
    assert len(rays) == 2
    assert all((r.dxf.start.x, r.dxf.start.y) == (1.0, 1.0) for r in rays)


# -- DIVIDE / MEASURE ----------------------------------------------------------

def test_divide_points_one_undo():
    h = Harness()
    line = h.msp.add_line((0.0, 0.0), (100.0, 0.0))
    h.ctx.services = PickServices(line)
    tool = DivideTool(h.ctx)
    tool.start()
    tool.on_point((50.0, 0.0))
    assert tool.on_option("5")
    pts = h.msp.query("POINT")
    assert len(pts) == 4
    assert sorted(round(p.dxf.location.x, 6) for p in pts) == [20, 40, 60, 80]
    h.history.undo()                    # ONE undo removes all four
    assert len(h.msp.query("POINT")) == 0


def test_divide_block_aligned():
    h = Harness()
    blk = h.document.doc.blocks.new("MARCA")
    blk.add_line((0, 0), (1, 0))
    arc_entity = h.msp.add_line((0.0, 0.0), (0.0, 90.0))   # vertical
    h.ctx.services = PickServices(arc_entity, blocks=["MARCA"])
    tool = DivideTool(h.ctx)
    tool.start()
    tool.on_point((0.0, 45.0))
    assert tool.on_option("B")
    assert tool.on_option("MARCA")
    assert tool.on_option("")           # align <Y>
    assert tool.on_option("3")
    inserts = h.msp.query("INSERT")
    assert len(inserts) == 2
    assert inserts[0].dxf.rotation == pytest.approx(90.0)  # tangent-aligned


def test_measure_from_nearest_end():
    h = Harness()
    line = h.msp.add_line((0.0, 0.0), (100.0, 0.0))
    h.ctx.services = PickServices(line)
    tool = MeasureTool(h.ctx)
    tool.start()
    tool.on_point((98.0, 0.0))          # pick near the RIGHT end
    assert tool.on_option("30")
    xs = sorted(round(p.dxf.location.x, 6) for p in h.msp.query("POINT"))
    assert xs == [10, 40, 70]           # steps of 30 from x=100 leftward


# -- REVCLOUD ------------------------------------------------------------------

def test_revcloud_rectangular_bulges_outward():
    h = Harness()
    tool = RevcloudTool(h.ctx)
    tool.start()
    assert tool.on_option("A")
    assert tool.on_option("10")
    assert tool.on_option("R")
    tool.on_point((0.0, 0.0))
    tool.on_point((60.0, 40.0))
    pl = h.msp.query("LWPOLYLINE")[0]
    assert pl.closed
    pts = pl.get_points("xyseb")
    assert len(pts) >= 12
    assert all(p[4] != 0.0 for p in pts)           # every chord is an arc
    assert RevcloudTool.arc_length == 10.0         # sticky
    # ...and the arcs bulge OUTWARD: the flattened ink must exceed the
    # 0..60 x 0..40 frame by the sagitta (the old sign kept every arc
    # inside — Marco's saw-blade capture; this test only checked != 0).
    import ezdxf.path as ezpath
    from ezdxf.math import BoundingBox2d

    box = BoundingBox2d(v for v in ezpath.make_path(pl).flattening(0.05))
    assert box.extmin.x < -0.5 and box.extmin.y < -0.5
    assert box.extmax.x > 60.5 and box.extmax.y > 40.5


def test_revcloud_polygonal_and_calligraphy():
    h = Harness()
    tool = RevcloudTool(h.ctx)
    tool.start()
    assert tool.on_option("S")
    assert tool.on_option("C")                     # Calligraphy
    assert tool.on_option("P")
    for p in ((0.0, 0.0), (40.0, 0.0), (40.0, 30.0), (0.0, 30.0)):
        tool.on_point(p)
    tool.on_enter()
    pts = h.msp.query("LWPOLYLINE")[0].get_points("xyseb")
    assert all(p[3] > 0.0 for p in pts)            # calligraphy taper


def test_revcloud_object_replaces_in_one_undo():
    h = Harness()
    circle = h.msp.add_circle((20.0, 20.0), 15.0)
    h.ctx.services = PickServices(circle)
    tool = RevcloudTool(h.ctx)
    tool.start()
    assert tool.on_option("O")
    tool.on_point((35.0, 20.0))
    tool.on_enter()                                # Reverse <No>
    assert len(h.msp.query("CIRCLE")) == 0         # replaced
    assert len(h.msp.query("LWPOLYLINE")) == 1
    h.history.undo()                               # one step restores it
    assert len(h.msp.query("CIRCLE")) == 1
    assert len(h.msp.query("LWPOLYLINE")) == 0
