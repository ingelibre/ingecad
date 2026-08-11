# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""DIST, ID, AREA and LIST — headless, through the prompt state machine."""
from __future__ import annotations

import math

import pytest

from core import units as u
from core.commands import History
from core.document import Document
from core.units import Units
from tools.base import ToolContext
from tools.inquiry import (
    AreaTool, DistTool, IdTool, ListTool, describe_entity,
    entity_area_perimeter)


class Harness:
    def __init__(self, units: Units | None = None, entity=None):
        self.document = Document.new()
        self.history = History(self.document)
        self.out: list[str] = []
        self.finished = False
        self._units = units or Units()
        self._entity = entity
        self.ctx = ToolContext(
            execute=self.history.execute,
            prompt=self.out.append,
            echo=self.out.append,
            finish=lambda: setattr(self, "finished", True),
            services=self,
        )

    # -- ToolContext.services duck methods
    def units(self):
        return self._units

    def pick_entity(self, point):
        return self._entity

    @property
    def text(self) -> str:
        return "\n".join(self.out)

    @property
    def msp(self):
        return self.document.modelspace()


# -- DIST ----------------------------------------------------------------------

def test_dist_reports_distance_angle_and_deltas():
    h = Harness()
    tool = DistTool(h.ctx)
    tool.start()
    assert "Specify first point:" in h.out[0]
    tool.on_point((0.0, 0.0))
    assert "Specify second point or <Multiple points>:" in h.out[-1]
    tool.on_point((3.0, 4.0))
    assert "Distance = 5.0000" in h.text
    assert "Angle in XY Plane = 53" in h.text
    assert "Delta X = 3.0000" in h.text and "Delta Y = 4.0000" in h.text
    assert h.finished


def test_dist_prints_in_the_drawing_units():
    h = Harness(Units(u.ARCHITECTURAL, 4))
    tool = DistTool(h.ctx)
    tool.start()
    tool.on_point((0.0, 0.0))
    tool.on_point((15.5, 0.0))
    assert "1'-3 1/2\"" in h.text


def test_dist_multiple_points_keeps_a_running_total():
    h = Harness()
    tool = DistTool(h.ctx)
    tool.start()
    tool.on_point((0.0, 0.0))
    tool.on_enter()                       # <Multiple points> is the default
    tool.on_point((3.0, 0.0))
    tool.on_point((3.0, 4.0))
    assert "Distance = 7.0000" in h.text   # 3 + 4, not the 5 of a straight line
    tool.on_option("T")
    assert h.finished


# -- ID ------------------------------------------------------------------------

def test_id_reports_the_point_and_keeps_it_as_the_last_point():
    h = Harness()
    tool = IdTool(h.ctx)
    tool.start()
    tool.on_point((12.5, -3.0))
    assert "X = 12.5000" in h.text and "Y = -3.0000" in h.text
    assert tool.last_point == (12.5, -3.0)
    assert h.finished


# -- AREA ----------------------------------------------------------------------

def test_area_of_a_square_by_corner_points():
    h = Harness()
    tool = AreaTool(h.ctx)
    tool.start()
    assert "Object/Add area/Subtract area" in h.out[0]
    for point in ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)):
        tool.on_point(point)
    tool.on_enter()
    assert "Area = 100.0000" in h.text
    assert "Perimeter = 40.0000" in h.text
    assert h.finished


def test_area_of_a_circle_object_matches_pi_r_squared():
    document = Document.new()
    circle = document.modelspace().add_circle((0, 0), radius=2.0)
    h = Harness(entity=circle)
    tool = AreaTool(h.ctx)
    tool.start()
    tool.on_enter()                       # <Object> is the bracketed default
    assert "Select object:" in h.out[-1]
    tool.on_point((2.0, 0.0))
    assert f"Area = {math.pi * 4.0:.4f}" in h.text
    assert f"Perimeter = {4.0 * math.pi:.4f}" in h.text


def test_area_add_and_subtract_keep_a_running_balance():
    h = Harness()
    tool = AreaTool(h.ctx)
    tool.start()
    tool.on_option("A")                   # Add mode
    assert "(ADD mode)" in h.out[-1]
    for point in ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)):
        tool.on_point(point)
    tool.on_enter()
    assert "Total area = 100.0000" in h.text
    tool.on_option("S")                   # Subtract mode
    for point in ((0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)):
        tool.on_point(point)
    tool.on_enter()
    assert "Total area = 96.0000" in h.text
    tool.on_option("X")
    assert h.finished


def test_area_object_mode_does_not_leak_entity_picking_to_the_next_command():
    """The Object phase turns picking on; it must not stay on for the class."""
    document = Document.new()
    circle = document.modelspace().add_circle((0, 0), radius=1.0)
    h = Harness(entity=circle)
    first = AreaTool(h.ctx)
    first.start()
    first.on_enter()
    assert first.entity_picker is True
    first.on_point((1.0, 0.0))
    second = AreaTool(Harness().ctx)
    second.start()
    assert second.entity_picker is False


def test_an_open_polyline_area_closes_but_its_length_does_not():
    document = Document.new()
    poly = document.modelspace().add_lwpolyline(
        [(0, 0), (10, 0), (10, 10)], close=False)
    area, length, closed = entity_area_perimeter(poly)
    assert closed is False
    assert area == pytest.approx(50.0)
    assert length == pytest.approx(20.0)      # the closing 14.14 is NOT added


def test_a_bulged_polyline_counts_the_arc_not_the_chord():
    """A half-circle bulge over a 10-unit chord adds the semicircle's area."""
    document = Document.new()
    poly = document.modelspace().add_lwpolyline(
        [(0, 0, 0, 0, 1.0), (10, 0, 0, 0, 0)], format="xyseb", close=True)
    area, _perimeter, _closed = entity_area_perimeter(poly)
    assert area == pytest.approx(math.pi * 25.0 / 2.0, rel=1e-3)


# -- LIST ----------------------------------------------------------------------

def test_list_reports_type_layer_space_and_geometry():
    document = Document.new()
    line = document.modelspace().add_line(
        (0, 0), (3, 4), dxfattribs={"layer": "MUROS"})
    lines = describe_entity(line, Units())
    text = "\n".join(lines)
    assert "LINE" in text
    assert 'Layer: "MUROS"' in text
    assert "Model space" in text
    # The real DXF handle, not a dash: LIST is how a user finds an entity.
    assert f"Handle = {line.dxf.handle}" in text
    assert line.dxf.handle and "Handle = -" not in text
    assert "Length = 5.0000" in text
    assert "Delta X = 3.0000" in text


def test_list_only_mentions_properties_that_are_not_bylayer():
    document = Document.new()
    plain = document.modelspace().add_line((0, 0), (1, 0))
    assert "Color" not in "\n".join(describe_entity(plain))
    coloured = document.modelspace().add_line(
        (0, 0), (1, 0), dxfattribs={"color": 1, "linetype": "DASHED"})
    text = "\n".join(describe_entity(coloured))
    assert "Color: 1" in text and "Linetype: DASHED" in text


def test_list_runs_over_a_selection():
    document = Document.new()
    msp = document.modelspace()
    entities = [msp.add_line((0, 0), (1, 0)), msp.add_circle((0, 0), 2.0)]
    h = Harness()
    tool = ListTool(h.ctx)
    tool.start()
    tool.on_selection(entities)
    assert "LINE" in h.text and "CIRCLE" in h.text
    assert "Circumference = 12.5664" in h.text
    assert h.finished


def test_list_of_a_closed_polyline_reports_its_area():
    document = Document.new()
    poly = document.modelspace().add_lwpolyline(
        [(0, 0), (10, 0), (10, 10), (0, 10)], close=True)
    text = "\n".join(describe_entity(poly))
    assert "Closed" in text
    assert "Area = 100.0000" in text and "Perimeter = 40.0000" in text
