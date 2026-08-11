# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Osnap on curves: what each type really owns, and what it must NOT offer.

Before this, the engine knew only LINE / LWPOLYLINE / CIRCLE / ARC / POINT:
an ellipse or a spline was not snappable at all, and a polyline's arc
segments were treated as their chords, so MIDpoint sat off the drawing.

The traps this file guards are the two ways of getting it wrong: offering
nothing, and offering a marker on every flattening vertex.
"""
from __future__ import annotations

import math

import pytest

from core.document import Document
from core.snap import SnapEngine


def engine_for(document) -> SnapEngine:
    engine = SnapEngine(document)
    engine._build()
    return engine


def snap(engine, x, y, threshold=1.0, **kw):
    return engine.find((x, y), threshold, **kw)


# -- polyline arcs: the silent one ---------------------------------------------

def test_a_polyline_arc_snaps_on_the_arc_not_on_its_chord():
    document = Document.new()
    # Bulge 1.0 = half circle below the chord (0,0)-(10,0): centre (5,0),
    # radius 5, so the arc's own midpoint is (5,-5).
    document.modelspace().add_lwpolyline(
        [(0, 0, 0, 0, 1.0), (10, 0, 0, 0, 0)], format="xyseb", close=False)
    engine = engine_for(document)

    end = snap(engine, 0.2, 0.1)
    assert end.kind == "END" and (end.x, end.y) == pytest.approx((0.0, 0.0))

    mid = snap(engine, 5.2, -4.8)
    assert mid.kind == "MID"
    assert (mid.x, mid.y) == pytest.approx((5.0, -5.0))

    centre = snap(engine, 5.1, 0.1)
    assert centre.kind == "CEN"
    assert (centre.x, centre.y) == pytest.approx((5.0, 0.0))

    # And the chord itself is NOT geometry: nothing to snap to at its middle.
    assert snap(engine, 5.0, 0.0, 0.05) is None or \
        snap(engine, 5.0, 0.0, 0.05).kind == "CEN"


def test_an_old_style_polyline_snaps_like_a_lwpolyline():
    document = Document.new()
    document.modelspace().add_polyline2d([(0, 0), (10, 0), (10, 10)])
    engine = engine_for(document)
    assert snap(engine, 10.1, 0.1).kind == "END"
    assert snap(engine, 5.0, 0.1).kind == "MID"


# -- ellipse -------------------------------------------------------------------

def test_an_ellipse_offers_centre_quadrants_and_nearest():
    document = Document.new()
    document.modelspace().add_ellipse((0, 0), major_axis=(10, 0), ratio=0.5)
    engine = engine_for(document)

    centre = snap(engine, 0.3, 0.3)
    assert centre.kind == "CEN" and (centre.x, centre.y) == pytest.approx((0, 0))

    for x, y in ((10.0, 0.0), (-10.0, 0.0), (0.0, 5.0), (0.0, -5.0)):
        hit = snap(engine, x * 0.98, y * 0.98 + (0.2 if y == 0 else 0.0))
        assert hit is not None and hit.kind == "QUA"
        assert (hit.x, hit.y) == pytest.approx((x, y), abs=1e-6)

    on_curve = snap(engine, 7.2, 3.4)
    assert on_curve.kind == "NEA"
    # NEA rides the chord chain, so it lands within the sagitta of the true
    # ellipse — bounded by CURVE_SAGITTA, not exact like END or QUA.
    from core.snap import CURVE_SAGITTA
    implicit = on_curve.x ** 2 / 100.0 + on_curve.y ** 2 / 25.0
    assert implicit == pytest.approx(1.0, abs=20.0 / CURVE_SAGITTA)


def test_a_closed_ellipse_offers_no_endpoint_and_no_midpoint():
    """A closed curve has neither, and a chord chain would invent dozens."""
    document = Document.new()
    document.modelspace().add_ellipse((0, 0), major_axis=(10, 0), ratio=0.5)
    engine = engine_for(document)
    assert snap(engine, 7.2, 3.4, kinds=frozenset({"END"})) is None
    assert snap(engine, 7.2, 3.4, kinds=frozenset({"MID"})) is None


def test_an_elliptical_arc_has_ends_and_only_the_quadrants_it_covers():
    document = Document.new()
    document.modelspace().add_ellipse(
        (0, 0), major_axis=(10, 0), ratio=0.5, start_param=0.0, end_param=1.5)
    engine = engine_for(document)
    start = snap(engine, 9.9, 0.1)
    assert start.kind == "END" and (start.x, start.y) == pytest.approx((10, 0))
    # The sweep stops before the far side: no quadrant there, nothing at all.
    assert snap(engine, -9.9, 0.1) is None


# -- spline --------------------------------------------------------------------

def test_a_spline_offers_its_ends_its_midpoint_and_nearest():
    document = Document.new()
    document.modelspace().add_spline([(0, 20), (5, 26), (12, 18), (20, 24)])
    engine = engine_for(document)
    start = snap(engine, 0.2, 20.2)
    assert start.kind == "END" and (start.x, start.y) == pytest.approx(
        (0, 20), abs=1e-6)
    end = snap(engine, 19.9, 24.1)
    assert end.kind == "END" and (end.x, end.y) == pytest.approx(
        (20, 24), abs=1e-6)
    assert snap(engine, 16.0, 20.0, threshold=2.0).kind in ("NEA", "MID")


def test_a_curve_does_not_intersect_itself():
    """Two chords of one curve meet at every flattening vertex — that is a
    seam of ours, not an intersection in the drawing."""
    document = Document.new()
    document.modelspace().add_spline([(0, 0), (5, 6), (12, -2), (20, 4)])
    engine = engine_for(document)
    for step in range(20):
        x = step
        hit = snap(engine, x, 0.0, threshold=6.0, kinds=frozenset({"INT"}))
        assert hit is None, f"false INT at x={x}: {hit}"


def test_two_different_curves_still_intersect():
    document = Document.new()
    msp = document.modelspace()
    msp.add_ellipse((0, 0), major_axis=(10, 0), ratio=0.5)
    msp.add_line((0, -8), (0, 8))
    engine = engine_for(document)
    hit = snap(engine, 0.3, 4.8, kinds=frozenset({"INT"}))
    assert hit is not None
    assert (hit.x, hit.y) == pytest.approx((0.0, 5.0), abs=0.05)


# -- QUA, new for every round shape --------------------------------------------

def test_quadrants_of_a_circle_and_of_an_arc():
    document = Document.new()
    msp = document.modelspace()
    msp.add_circle((40, 0), 5)
    msp.add_arc((0, 40), 5, start_angle=0, end_angle=90)
    engine = engine_for(document)
    for x, y in ((45, 0), (35, 0), (40, 5), (40, -5)):
        hit = snap(engine, x + 0.1, y + 0.1)
        assert hit.kind == "QUA" and (hit.x, hit.y) == pytest.approx((x, y))
    # An arc offers only the quadrants its sweep reaches. This one runs
    # 30° to 300°, so north/west/south are on it and east is not. (Its own
    # ends are elsewhere, so they cannot mask the answer.)
    msp.add_arc((0, 80), 5, start_angle=30, end_angle=300)
    engine = engine_for(document)
    assert snap(engine, 0.1, 85.1, kinds=frozenset({"QUA"})).kind == "QUA"
    assert snap(engine, -5.1, 80.1, kinds=frozenset({"QUA"})).kind == "QUA"
    assert snap(engine, 0.1, 75.1, kinds=frozenset({"QUA"})).kind == "QUA"
    assert snap(engine, 5.1, 80.1, kinds=frozenset({"QUA"})) is None


def test_an_endpoint_still_beats_a_quadrant():
    """Priority order is AutoCAD's: END before MID before CEN before QUA."""
    document = Document.new()
    msp = document.modelspace()
    msp.add_arc((0, 0), 5, start_angle=0, end_angle=90)   # end at (0,5)
    engine = engine_for(document)
    hit = snap(engine, 0.1, 5.05)
    assert hit.kind == "END"


# -- the cache stays correct through edits -------------------------------------

def test_an_ellipse_added_after_the_build_is_snappable():
    document = Document.new()
    engine = engine_for(document)
    ellipse = document.modelspace().add_ellipse(
        (0, 0), major_axis=(10, 0), ratio=0.5)
    engine.add_entities([ellipse])
    assert snap(engine, 9.9, 0.1).kind == "QUA"


def test_moving_an_ellipse_moves_its_snaps():
    document = Document.new()
    ellipse = document.modelspace().add_ellipse(
        (0, 0), major_axis=(10, 0), ratio=0.5)
    engine = engine_for(document)
    engine.translate_handles({ellipse.dxf.handle}, 100.0, 0.0)
    assert snap(engine, 0.3, 0.3) is None
    centre = snap(engine, 100.3, 0.3)
    assert centre.kind == "CEN" and centre.x == pytest.approx(100.0)


def test_erasing_an_ellipse_removes_its_snaps():
    document = Document.new()
    ellipse = document.modelspace().add_ellipse(
        (0, 0), major_axis=(10, 0), ratio=0.5)
    engine = engine_for(document)
    engine.remove_handles({ellipse.dxf.handle})
    assert snap(engine, 0.3, 0.3) is None
    assert snap(engine, 9.9, 0.1) is None
