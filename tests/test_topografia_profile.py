# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Topography plugin, T5, the pure part: chainage along an axis, the
ground profile and cross sections on a TIN, the design template to
daylight, cut and fill areas, and prismoidal volumes -- all checked
against cases with closed-form answers."""
from __future__ import annotations

import math

import pytest

from plugins.topografia import alignment, profile
from plugins.topografia.tin import build_tin


def _plane(gx: float = 0.0, gy: float = 0.0, z0: float = 100.0, size: float = 200.0, step: float = 10.0):
    n = int(size / step)
    return build_tin([(i * step, j * step, z0 + gx * i * step + gy * j * step)
                      for i in range(n + 1) for j in range(n + 1)])


# -- alignment ----------------------------------------------------------------------------

def test_stations_every_twenty_metres_plus_the_vertices():
    axis = [(0.0, 0.0), (50.0, 0.0), (50.0, 30.0)]
    sts = alignment.stations(axis, 20.0)
    assert [round(s.s, 3) for s in sts] == [0.0, 20.0, 40.0, 50.0, 60.0, 80.0]
    assert [s.vertex for s in sts] == [True, False, False, True, False, True]
    assert (sts[1].x, sts[1].y, sts[1].angle) == (20.0, 0.0, 0.0)
    assert (sts[4].x, sts[4].y) == pytest.approx((50.0, 10.0)) and sts[4].angle == pytest.approx(90.0)
    assert sts[4].offset_point(5.0) == pytest.approx((55.0, 10.0))          # right of a northbound axis
    assert sts[1].offset_point(-3.0) == pytest.approx((20.0, 3.0))          # left of an eastbound one
    assert alignment.format_station(20.0) == "0+020.00"
    assert alignment.format_station(1234.567) == "1+234.57"
    assert alignment.station_of(axis, (30.0, 5.0)) == pytest.approx(30.0)
    assert alignment.station_of(axis, (52.0, 12.0)) == pytest.approx(62.0)
    with pytest.raises(ValueError):
        alignment.stations(axis, 0.0)


# -- profile and grade ----------------------------------------------------------------------

def test_the_ground_profile_of_a_sloping_plane_and_a_grade_line():
    tin = _plane(gx=0.05)                                     # 5 % rising east
    axis = [(10.0, 100.0), (110.0, 100.0)]
    prof = profile.ground_profile(tin, axis, 25.0)
    assert [p.s for p in prof] == [0.0, 25.0, 50.0, 75.0, 100.0]
    assert [p.z for p in prof] == pytest.approx([100.5, 101.75, 103.0, 104.25, 105.5])
    off = profile.ground_profile(tin, [(0.0, 100.0), (300.0, 100.0)], 100.0)
    assert off[-1].z is None                                    # the axis leaves the surface
    grade = [(0.0, 101.0), (100.0, 103.0)]
    assert profile.grade_at(grade, 50.0) == pytest.approx(102.0)
    assert profile.grade_at(grade, 120.0) is None
    assert profile.grade_slopes([(0.0, 100.0), (50.0, 101.0), (100.0, 100.0)]) == pytest.approx([2.0, -2.0])


# -- sections, template, areas ----------------------------------------------------------------

def test_a_cross_section_and_a_template_in_cut_and_in_fill():
    tin = _plane(gy=0.10)                                     # 10 % rising north
    st = alignment.point_at([(50.0, 100.0), (150.0, 100.0)], 50.0)
    ground = profile.cross_section(tin, st, 10.0, 1.0)
    assert ground[0] == pytest.approx((-10.0, 111.0)) and ground[-1] == pytest.approx((10.0, 109.0))
    template = profile.Template(width=4.0, cut_hv=1.0, fill_hv=1.0)
    # platform 2 m below the ground at the axis: cut on both sides
    design = profile.design_section(ground, 108.0, template)
    assert design[1] == (-2.0, 108.0) and design[2] == (2.0, 108.0)
    # left daylight: ground 110 + 0.1*(-o)... solve 108 + (o - (-2))*(-1)... = ground
    left, right = design[0], design[-1]
    assert left[0] < -2.0 and right[0] > 2.0
    assert profile._z_on(ground, left[0]) == pytest.approx(left[1], abs=1e-6)     # ON the ground
    assert profile._z_on(ground, right[0]) == pytest.approx(right[1], abs=1e-6)
    cut, fill = profile.areas(ground, design)
    assert fill == pytest.approx(0.0) and cut > 0
    # platform 2 m above the ground: fill on both sides, same magnitude by symmetry
    design_up = profile.design_section(ground, 112.0, template)
    cut2, fill2 = profile.areas(ground, design_up)
    assert cut2 == pytest.approx(0.0) and fill2 == pytest.approx(cut, rel=1e-6)


def test_areas_have_closed_forms_on_flat_ground():
    tin = _plane()                                           # flat at 100
    st = alignment.point_at([(50.0, 100.0), (150.0, 100.0)], 30.0)
    ground = profile.cross_section(tin, st, 20.0, 1.0)
    template = profile.Template(width=6.0, cut_hv=1.0, fill_hv=2.0)
    # 1 m of cut: rectangle 6 x 1 plus two 1:1 triangles of 0.5
    cut, fill = profile.areas(ground, profile.design_section(ground, 99.0, template))
    assert cut == pytest.approx(6.0 + 2 * 0.5) and fill == 0.0
    # 1 m of fill: rectangle 6 x 1 plus two 2:1 triangles of 1.0
    cut, fill = profile.areas(ground, profile.design_section(ground, 101.0, template))
    assert fill == pytest.approx(6.0 + 2 * 1.0) and cut == 0.0
    # at grade: nothing
    assert profile.areas(ground, profile.design_section(ground, 100.0, template)) == (0.0, 0.0)


def test_prismoidal_volumes_along_a_ramp_match_the_calculus():
    """Flat ground at 100, a grade going from 1 m of fill to 1 m of cut over
    100 m: the fill and cut wedges have closed-form volumes."""
    tin = _plane()
    axis = [(10.0, 100.0), (110.0, 100.0)]
    grade = [(0.0, 101.0), (100.0, 99.0)]
    template = profile.Template(width=6.0, cut_hv=1.0, fill_hv=1.0)
    rows = profile.earthworks(tin, axis, grade, 10.0, template, half_width=20.0)
    assert [r.s for r in rows] == [float(s) for s in range(0, 101, 10)]
    assert rows[0].fill_area == pytest.approx(7.0) and rows[-1].cut_area == pytest.approx(7.0)
    assert rows[5].cut_area == pytest.approx(0.0) and rows[5].fill_area == pytest.approx(0.0)
    # fill area at depth d is 6d + d^2; integrate over the first 50 m where d = 1 - s/50
    expected = sum_wedge = 0.0
    n = 100000
    for k in range(n):
        s = 50.0 * (k + 0.5) / n
        d = 1 - s / 50.0
        expected += (6 * d + d * d) * 50.0 / n
    assert rows[-1].fill_total == pytest.approx(expected, rel=2e-3)
    assert rows[-1].cut_total == pytest.approx(expected, rel=2e-3)
    assert rows[-1].mass == pytest.approx(0.0, abs=0.05)
    end_area = profile.earthworks(tin, axis, grade, 10.0, template, method="end-area")
    assert end_area[-1].fill_total > rows[-1].fill_total * 0.99      # both agree closely here
    assert profile.prismoidal(1.0, 1.0, 1.0, 12.0) == 12.0 and profile.end_area(2.0, 4.0, 10.0) == 30.0


def test_a_grade_that_only_covers_part_of_the_axis_leaves_blank_rows():
    tin = _plane()
    axis = [(10.0, 100.0), (110.0, 100.0)]
    rows = profile.earthworks(tin, axis, [(20.0, 99.0), (60.0, 99.0)], 20.0, profile.Template())
    assert [r.z_design for r in rows] == [None, 99.0, 99.0, 99.0, None, None]
    assert rows[1].cut_volume == 0.0 and rows[2].cut_volume > 0 and rows[4].cut_volume == 0.0
