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


# -- spline and ellipse grips (AutoCAD's sets) --------------------------------

def _msp():
    from core.document import Document

    doc = Document.new()
    return doc, doc.modelspace()


def test_spline_grips_are_its_fit_points_and_drag_refits():
    from core.select import apply_grip_edit, entity_grips

    _doc, msp = _msp()
    spline = msp.add_spline(fit_points=[(0, 0), (10, 5), (20, -3)])
    grips = entity_grips(spline)
    assert [(x, y) for x, y, _r in grips] == [(0, 0), (10, 5), (20, -3)]
    assert all(r == "vertex" for _x, _y, r in grips)
    assert apply_grip_edit(spline, 1, "vertex", (10.0, 9.0))
    assert tuple(spline.fit_points[1])[:2] == (10.0, 9.0)
    assert len(spline.control_points) == 0     # re-fit, no stale frame


def test_ellipse_grips_center_plus_axis_ends():
    from core.select import entity_grips

    _doc, msp = _msp()
    e = msp.add_ellipse((50, 50), major_axis=(20, 0), ratio=0.5)
    grips = entity_grips(e)
    pts = {(round(x), round(y)) for x, y, _r in grips}
    assert pts == {(50, 50), (70, 50), (30, 50), (50, 60), (50, 40)}
    roles = [r for _x, _y, r in grips]
    assert roles[0] == "center" and set(roles[1:]) == {"quadrant"}


def test_ellipse_axis_drags_resize_and_keep_ratio_legal():
    from core.select import apply_grip_edit

    _doc, msp = _msp()
    e = msp.add_ellipse((50, 50), major_axis=(20, 0), ratio=0.5)
    # stretch the major axis to 40: minor stays 10, ratio 0.25
    assert apply_grip_edit(e, 1, "quadrant", (90.0, 50.0))
    assert round(e.dxf.major_axis.x) == 40 and e.dxf.ratio == 0.25
    # drag the minor end out to 15: ratio 15/40
    assert apply_grip_edit(e, 3, "quadrant", (50.0, 65.0))
    assert abs(e.dxf.ratio - 15.0 / 40.0) < 1e-9
    # shrink the major below the minor: axes swap, ratio stays <= 1
    assert apply_grip_edit(e, 1, "quadrant", (58.0, 50.0))
    assert e.dxf.ratio <= 1.0
    import math
    major_len = math.hypot(e.dxf.major_axis.x, e.dxf.major_axis.y)
    assert round(major_len) == 15              # the old minor took over
    # and the center never moved
    assert (round(e.dxf.center.x), round(e.dxf.center.y)) == (50, 50)


def test_ellipse_center_grip_moves_it():
    from core.select import apply_grip_edit

    _doc, msp = _msp()
    e = msp.add_ellipse((50, 50), major_axis=(20, 0), ratio=0.5)
    assert apply_grip_edit(e, 0, "center", (80.0, 20.0))
    assert (e.dxf.center.x, e.dxf.center.y) == (80.0, 20.0)
    assert e.dxf.major_axis.x == 20.0          # shape untouched


def test_every_selectable_type_has_grips_now():
    """The audit: anything IngeCAD can create and select shows grips."""
    from core.select import entity_grips
    from ezdxf.enums import TextEntityAlignment

    _doc, msp = _msp()
    _doc.doc.blocks.new("B1").add_line((0, 0), (1, 1))
    entities = [
        msp.add_text("T", dxfattribs={"height": 2.0, "insert": (1, 2)}),
        msp.add_mtext("M", dxfattribs={"insert": (3, 4)}),
        msp.add_blockref("B1", (5, 6)),
        msp.add_xline((7, 8), (1, 0)),
        msp.add_ray((9, 10), (0, 1)),
        msp.add_solid([(0, 0), (4, 0), (0, 4), (4, 4)]),
    ]
    hatch = msp.add_hatch()
    hatch.paths.add_polyline_path([(0, 0), (4, 0), (4, 4), (0, 4)],
                                  is_closed=True)
    entities.append(hatch)
    entities.append(msp.add_linear_dim(base=(0, 5), p1=(0, 0), p2=(9, 0))
                    .render().dimension)
    for entity in entities:
        assert entity_grips(entity), entity.dxftype()


def test_moving_the_single_grip_translates_the_entity():
    from core.select import apply_grip_edit, entity_grips

    _doc, msp = _msp()
    text = msp.add_text("T", dxfattribs={"height": 2.0, "insert": (1.0, 2.0)})
    assert apply_grip_edit(text, 0, "center", (11.0, 22.0))
    assert (text.dxf.insert.x, text.dxf.insert.y) == (11.0, 22.0)

    xline = msp.add_xline((0.0, 0.0), (1.0, 0.0))
    assert apply_grip_edit(xline, 0, "center", (5.0, 5.0))
    assert (xline.dxf.start.x, xline.dxf.start.y) == (5.0, 5.0)
    assert xline.dxf.unit_vector.x == 1.0        # direction untouched


def test_aligned_text_grips_at_its_align_point():
    from ezdxf.enums import TextEntityAlignment

    from core.select import apply_grip_edit, entity_grips

    _doc, msp = _msp()
    text = msp.add_text("C", dxfattribs={"height": 2.0})
    text.set_placement((10.0, 10.0), align=TextEntityAlignment.MIDDLE_CENTER)
    (gx, gy, role), = entity_grips(text)
    assert (gx, gy) == (10.0, 10.0) and role == "center"
    assert apply_grip_edit(text, 0, "center", (20.0, 30.0))
    (gx, gy, _), = entity_grips(text)
    assert (gx, gy) == (20.0, 30.0)


def test_solid_corners_move_individually():
    from core.select import apply_grip_edit

    _doc, msp = _msp()
    solid = msp.add_solid([(0, 0), (4, 0), (0, 4), (4, 4)])
    assert apply_grip_edit(solid, 3, "vertex", (9.0, 9.0))
    assert (solid.dxf.vtx3.x, solid.dxf.vtx3.y) == (9.0, 9.0)
    assert (solid.dxf.vtx0.x, solid.dxf.vtx0.y) == (0.0, 0.0)


def test_hatch_grip_moves_the_whole_hatch():
    import ezdxf.bbox as bbox_mod

    from core.select import apply_grip_edit, entity_grips

    _doc, msp = _msp()
    hatch = msp.add_hatch()
    hatch.paths.add_polyline_path([(0, 0), (4, 0), (4, 4), (0, 4)],
                                  is_closed=True)
    (gx, gy, role), = entity_grips(hatch)
    assert (gx, gy) == (2.0, 2.0) and role == "center"
    assert apply_grip_edit(hatch, 0, "center", (12.0, 2.0))
    assert bbox_mod.extents([hatch]).center.x == 12.0


def test_linear_dimension_grips_match_autocads_set():
    from core.select import entity_grips

    _doc, msp = _msp()
    dim = msp.add_linear_dim(base=(0, 10), p1=(0, 0), p2=(30, 0)) \
             .render().dimension
    grips = entity_grips(dim)
    roles = [r for _x, _y, r in grips]
    assert roles == ["dim_defpoint2", "dim_defpoint3", "dim_defpoint",
                     "dim_text"]
    by_role = {r: (x, y) for x, y, r in grips}
    assert by_role["dim_defpoint2"] == (0.0, 0.0)
    assert by_role["dim_defpoint3"] == (30.0, 0.0)


def test_radial_dimension_offers_its_text_grip():
    from core.select import entity_grips

    _doc, msp = _msp()
    msp.add_circle((50, 50), 10)
    dim = msp.add_radius_dim(center=(50, 50), radius=10, angle=30) \
             .render().dimension
    roles = [r for _x, _y, r in entity_grips(dim)]
    assert roles == ["dim_text"]


def test_dim_grip_command_remeasures_and_undoes():
    from core.actions import DimGripCommand
    from core.commands import History

    doc, msp = _msp()
    dim = msp.add_linear_dim(base=(0, 10), p1=(0, 0), p2=(30, 0)) \
             .render().dimension
    history = History(doc)
    block_names = lambda: {b.name for b in doc.doc.blocks if b.name.startswith("*D")}
    before_blocks = block_names()
    history.execute(DimGripCommand(dim, "defpoint3", (45.0, 0.0)))
    assert dim.dxf.defpoint3.x == 45.0
    # exactly one *D block alive: the old one was dropped
    assert len(block_names()) == len(before_blocks)
    history.undo()
    assert dim.dxf.defpoint3.x == 30.0
    assert len(block_names()) == len(before_blocks)
    history.redo()
    assert dim.dxf.defpoint3.x == 45.0
