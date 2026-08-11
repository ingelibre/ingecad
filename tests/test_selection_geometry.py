# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Selection geometry: what is traced for real and what stays a rectangle.

An entity that falls back to its bounding box is picked from anywhere inside
that rectangle, caught by any crossing window that touches the rectangle, and
highlighted AS a rectangle. On a busy drawing that is selection garbage, so
everything we know how to trace is traced.
"""
from __future__ import annotations

import pytest

from core.document import Document
from core.select import BOXED_TYPES, GeometryIndex


def index_of(document) -> GeometryIndex:
    index = GeometryIndex(document)
    index._build()
    return index


def geometry(index, entity):
    handles = {entity.dxf.handle}
    return (len(index.segments_of(handles)), len(index.circles_of(handles)),
            len(index.boxes_of(handles)))


# -- the reported bug ----------------------------------------------------------

def test_an_ellipse_is_traced_not_boxed():
    document = Document.new()
    ellipse = document.modelspace().add_ellipse(
        (0, 0), major_axis=(10, 0), ratio=0.5)
    index = index_of(document)
    segments, circles, boxes = geometry(index, ellipse)
    assert boxes == 0, "an ellipse must not be a rectangle"
    assert segments > 8


def test_clicking_inside_an_ellipse_selects_nothing():
    document = Document.new()
    document.modelspace().add_ellipse((0, 0), major_axis=(10, 0), ratio=0.5)
    index = index_of(document)
    # Dead centre: inside the bounding box, far from the curve.
    assert index.pick((0.0, 0.0), 0.2) is None
    # On the curve: picked.
    assert index.pick((10.0, 0.0), 0.2) is not None


def test_a_crossing_window_inside_an_ellipse_catches_nothing():
    document = Document.new()
    document.modelspace().add_ellipse((0, 0), major_axis=(10, 0), ratio=0.5)
    index = index_of(document)
    assert index.crossing((-3.0, -1.0, 3.0, 1.0)) == []
    # A window that does touch the curve still catches it.
    assert len(index.crossing((9.0, -1.0, 11.0, 1.0))) == 1


# -- every other type that used to be a rectangle ------------------------------

def test_curves_quads_and_construction_lines_are_all_traced():
    document = Document.new()
    msp = document.modelspace()
    cases = {
        "ELLIPSE": msp.add_ellipse((0, 0), major_axis=(10, 0), ratio=0.5),
        "SPLINE": msp.add_spline([(20, 0), (23, 4), (28, 1), (32, 6)]),
        "POLYLINE2D": msp.add_polyline2d([(40, 0), (45, 0), (45, 5)]),
        "POLYLINE3D": msp.add_polyline3d([(50, 0, 0), (55, 0, 2), (55, 5, 4)]),
        "SOLID": msp.add_solid([(60, 0), (62, 0), (60, 2), (62, 2)]),
        "TRACE": msp.add_trace([(65, 0), (67, 0), (65, 2), (67, 2)]),
        "3DFACE": msp.add_3dface([(70, 0), (72, 0), (72, 2), (70, 2)]),
        "XLINE": msp.add_xline((0, 20), (1, 0)),
        "RAY": msp.add_ray((0, 25), (1, 0)),
        "LEADER": msp.add_leader([(80, 0), (83, 3), (86, 3)]),
    }
    index = index_of(document)
    for name, entity in cases.items():
        segments, _circles, boxes = geometry(index, entity)
        assert boxes == 0, f"{name} still falls back to a rectangle"
        assert segments >= 1, f"{name} produced no pick geometry"


def test_a_polyline_with_bulges_is_picked_on_the_arc_not_the_chord():
    document = Document.new()
    # Bulge 1.0 is a half circle, and a positive bulge sweeps
    # counter-clockwise: from (0,0) to (10,0) that puts the arc BELOW the
    # chord, apex at (5,-5).
    poly = document.modelspace().add_lwpolyline(
        [(0, 0, 0, 0, 1.0), (10, 0, 0, 0, 0)], format="xyseb", close=True)
    index = index_of(document)
    assert geometry(index, poly)[2] == 0
    assert index.pick((5.0, -5.0), 0.2) == poly.dxf.handle
    # Between the chord and the arc there is nothing: empty space, and the
    # chord-only tracing this replaces would have claimed the point at y=0.
    assert index.pick((5.0, -2.5), 0.2) is None


def test_a_hatch_is_traced_by_its_boundary():
    document = Document.new()
    hatch = document.modelspace().add_hatch(color=2)
    hatch.paths.add_polyline_path(
        [(0, 0), (10, 0), (10, 10), (0, 10)], is_closed=True)
    index = index_of(document)
    segments, _circles, boxes = geometry(index, hatch)
    assert boxes == 0 and segments >= 4
    assert index.pick((10.0, 5.0), 0.1) == hatch.dxf.handle


def test_a_dimension_is_traced_through_its_geometry_block():
    document = Document.new()
    msp = document.modelspace()
    dim = msp.add_linear_dim(base=(0, 15), p1=(0, 0), p2=(10, 0))
    dim.render()
    entity = [e for e in msp if e.dxftype() == "DIMENSION"][0]
    index = index_of(document)
    segments, _circles, boxes = geometry(index, entity)
    assert boxes == 0, "a dimension must not be a rectangle over what it measures"
    assert segments >= 4
    # The dimension line runs at y=15 — and is split by the gap the text
    # sits in, so pick beside the text, not through it.
    assert index.pick((2.0, 15.0), 0.3) == entity.dxf.handle
    # The text is part of the dimension too.
    assert index.pick((5.0, 15.3), 0.3) == entity.dxf.handle
    # Between the extension lines there is nothing: a box over the whole
    # dimension would have claimed this point, and the object being measured
    # sits exactly there.
    assert index.pick((5.0, 7.0), 0.3) is None


# -- what stays a rectangle, on purpose ----------------------------------------

def test_text_and_blocks_stay_boxed_and_the_list_says_so():
    document = Document.new()
    msp = document.modelspace()
    text = msp.add_text("HOLA", height=2)
    text.set_placement((0, 0))
    block = document.doc.blocks.new(name="TESTBLK")
    block.add_line((0, 0), (1, 1))
    insert = msp.add_blockref("TESTBLK", (20, 0))
    index = index_of(document)
    assert geometry(index, text)[2] == 1
    assert geometry(index, insert)[2] == 1
    assert {"TEXT", "INSERT"} <= BOXED_TYPES


def test_nothing_outside_the_declared_list_falls_back_to_a_box():
    """The safety net: a type that starts being boxed must be declared.

    Otherwise a regression in the tracing code turns entities back into
    rectangles silently, which is exactly the bug this file is about.
    """
    document = Document.new()
    msp = document.modelspace()
    msp.add_ellipse((0, 0), major_axis=(10, 0), ratio=0.5)
    msp.add_spline([(20, 0), (23, 4), (28, 1), (32, 6)])
    msp.add_solid([(60, 0), (62, 0), (60, 2), (62, 2)])
    msp.add_xline((0, 20), (1, 0))
    hatch = msp.add_hatch(color=2)
    hatch.paths.add_polyline_path([(0, 0), (5, 0), (5, 5)], is_closed=True)
    dim = msp.add_linear_dim(base=(0, 15), p1=(0, 0), p2=(10, 0))
    dim.render()
    text = msp.add_text("T", height=1)
    text.set_placement((90, 0))

    index = index_of(document)
    boxed_owners = {index._owners[i] for i in index._box_oidx}
    boxed_types = {e.dxftype() for e in msp if e.dxf.handle in boxed_owners}
    assert boxed_types <= BOXED_TYPES, (
        f"undeclared fallback to a rectangle: {boxed_types - BOXED_TYPES}")


def test_incremental_add_traces_the_same_way_as_a_full_build():
    """Drawing an ellipse must not box it just because the index was warm."""
    document = Document.new()
    index = index_of(document)
    ellipse = document.modelspace().add_ellipse(
        (0, 0), major_axis=(10, 0), ratio=0.5)
    index.add_entities([ellipse])
    segments, _circles, boxes = geometry(index, ellipse)
    assert boxes == 0 and segments > 8


def test_the_dimension_text_answers_a_click_but_not_a_crossing_window():
    """The click-only box: selecting a dimension by its number must not turn
    the number's rectangle into something a crossing window drags in."""
    document = Document.new()
    msp = document.modelspace()
    dim = msp.add_linear_dim(base=(0, 15), p1=(0, 0), p2=(10, 0))
    dim.render()
    entity = [e for e in msp if e.dxftype() == "DIMENSION"][0]
    index = index_of(document)

    # Inside the text: picked.
    assert index.pick((5.0, 15.0), 0.05) == entity.dxf.handle
    # The click-only box never reaches the highlight...
    assert len(index.boxes_of({entity.dxf.handle})) == 0
    # ...nor window/crossing: a rect strictly inside the text finds nothing.
    assert index.crossing((4.9, 14.9, 5.1, 15.1)) == []
