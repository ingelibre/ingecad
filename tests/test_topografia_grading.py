# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Topography plugin, T6, the pure part: a platform's plane, side slopes
marched to daylight (with benches), the design surface, and the exact
volume between two surfaces -- against closed forms and a fine grid."""
from __future__ import annotations

import math

import pytest

from plugins.topografia import grading
from plugins.topografia.tin import Tin, build_tin


def _flat(z0: float = 100.0, size: float = 100.0, step: float = 10.0):
    n = int(size / step)
    return build_tin([(i * step, j * step, z0) for i in range(n + 1) for j in range(n + 1)])


SQUARE = [(40.0, 40.0), (60.0, 40.0), (60.0, 60.0), (40.0, 60.0)]      # 20 x 20 in the middle


def test_the_platform_plane_and_the_slope_profile():
    flat = grading.platform_plane((40.0, 40.0), 100.0)
    assert flat(55.0, 57.0) == 100.0
    east_down = grading.platform_plane((40.0, 40.0), 100.0, 2.0, 90.0)   # 2 % falling east
    assert east_down(50.0, 40.0) == pytest.approx(99.8)
    assert east_down(40.0, 50.0) == pytest.approx(100.0)
    north_down = grading.platform_plane((0.0, 0.0), 50.0, 10.0, 0.0)
    assert north_down(0.0, 10.0) == pytest.approx(49.0)
    spec = grading.SlopeSpec(cut_hv=2.0)
    assert grading.slope_rise(4.0, 2.0, spec) == pytest.approx(2.0)      # 2H:1V
    benched = grading.SlopeSpec(cut_hv=1.0, bench_height=3.0, bench_width=2.0)
    assert grading.slope_rise(3.0, 1.0, benched) == pytest.approx(3.0)     # first lift
    assert grading.slope_rise(4.0, 1.0, benched) == pytest.approx(3.0)     # on the bench
    assert grading.slope_rise(6.0, 1.0, benched) == pytest.approx(4.0)     # second lift


def test_daylight_of_a_sunken_square_on_flat_ground_is_a_loop_two_metres_out():
    tin = _flat()
    z_of = grading.platform_plane(SQUARE[0], 98.0)                         # 2 m of cut
    spec = grading.SlopeSpec(cut_hv=1.0, fill_hv=1.5)
    day = grading.daylight_line(tin, SQUARE, z_of, spec, sample=1.0)
    assert all(d is not None for d in day)
    assert all(d.cut for d in day)
    mids = [d for d in day if abs(d.edge_x - 50.0) < 1e-9 or abs(d.edge_y - 50.0) < 1e-9]
    assert mids and all(d.distance == pytest.approx(2.0) for d in mids)       # 1:1 over 2 m
    assert all(d.z == pytest.approx(100.0) for d in day)                      # on the ground
    # at a corner the march follows the bisector: 1:1 over 2 m is 2 m out
    # along it too -- the toe rounds the corner the way a real slope does
    corners = [d for d in day if (d.edge_x, d.edge_y) in SQUARE]
    assert len(corners) == 4 and all(c.distance == pytest.approx(2.0) for c in corners)
    assert corners[0].x == pytest.approx(40.0 - math.sqrt(2)) and corners[0].y == pytest.approx(40.0 - math.sqrt(2))
    # in fill the other slope applies: 2 m up at 1.5:1 is 3 m out
    up = grading.daylight_line(tin, SQUARE, grading.platform_plane(SQUARE[0], 102.0), spec, 1.0)
    assert all(not d.cut and d.distance == pytest.approx(3.0) for d in up
               if abs(d.edge_x - 50.0) < 1e-9)
    lines = grading.hachures(day)
    assert len(lines) == len(day)
    assert math.hypot(lines[0][1][0] - lines[0][0][0], lines[0][1][1] - lines[0][0][1]) > \
        math.hypot(lines[1][1][0] - lines[1][0][0], lines[1][1][1] - lines[1][0][1])   # long, short


def test_the_design_surface_holds_the_platform_and_the_slopes():
    tin = _flat()
    z_of = grading.platform_plane(SQUARE[0], 98.0)
    day = grading.daylight_line(tin, SQUARE, z_of, grading.SlopeSpec(1.0, 1.0), sample=2.0)
    design = grading.design_surface(SQUARE, z_of, day, "PLATAFORMA")
    assert design.name == "PLATAFORMA"
    assert design.z_at(50.0, 50.0) == pytest.approx(98.0)                # the platform
    assert design.z_at(41.0, 50.0) == pytest.approx(98.0)
    assert design.z_at(39.0, 50.0) == pytest.approx(99.0)                # half way up the slope
    assert design.z_at(37.0, 50.0) is None or design.z_at(37.5, 50.0) is None   # beyond daylight
    assert design.stats()["bad_edges"] == 0


def _grid_volume(ground: Tin, design: Tin, step: float = 0.25) -> tuple[float, float]:
    """The same volume by brute-force sampling, the DoD's 'fine sections'."""
    xs = [p[0] for p in design.points]
    ys = [p[1] for p in design.points]
    cut = fill = 0.0
    x = min(xs) + step / 2.0
    while x < max(xs):
        y = min(ys) + step / 2.0
        while y < max(ys):
            zd, zg = design.z_at(x, y), ground.z_at(x, y)
            if zd is not None and zg is not None:
                if zd > zg:
                    fill += (zd - zg) * step * step
                else:
                    cut += (zg - zd) * step * step
            y += step
        x += step
    return cut, fill


def test_the_volume_between_two_surfaces_is_exact():
    ground = _flat()
    # the same surface: nothing
    assert grading.volume_between(ground, ground) == (pytest.approx(0.0), pytest.approx(0.0))
    # the ground lifted 1 m: fill = its area, exactly
    lifted = Tin([(x, y, z + 1.0) for x, y, z in ground.points], list(ground.triangles), "UP")
    cut, fill = grading.volume_between(ground, lifted)
    assert cut == pytest.approx(0.0) and fill == pytest.approx(100.0 * 100.0)
    # a tilted design over a flat ground: the zero line splits it, cut == fill
    tilted = Tin([(x, y, 100.0 + 0.1 * (x - 50.0)) for x, y, z in ground.points],
                 list(ground.triangles), "TILT")
    cut, fill = grading.volume_between(ground, tilted)
    assert cut == pytest.approx(fill) and cut == pytest.approx(0.5 * 50.0 * 5.0 * 100.0)


def test_a_sunken_platform_cut_matches_the_frustum_and_the_fine_grid():
    """The DoD: a platform on the ground, the daylight closes, and the
    TIN-vs-TIN volume agrees with fine sections within 2 %."""
    ground = _flat()
    z_of = grading.platform_plane(SQUARE[0], 98.0)
    spec = grading.SlopeSpec(cut_hv=1.0, fill_hv=1.0)
    day = grading.daylight_line(ground, SQUARE, z_of, spec, sample=0.5)
    assert all(d is not None for d in day)                                # the loop closes
    design = grading.design_surface(SQUARE, z_of, day)
    cut, fill = grading.volume_between(ground, design)
    assert fill == pytest.approx(0.0, abs=1e-6)
    # a 20 x 20 platform 2 m down with 1:1 slopes: frustum 2/3 (400 + 576 + 480) = 970.67,
    # minus the corners, which the marched normals round off
    assert 930.0 < cut < 975.0
    grid_cut, grid_fill = _grid_volume(ground, design)
    assert cut == pytest.approx(grid_cut, rel=0.02) and grid_fill == pytest.approx(0.0, abs=0.5)
    assert grading.footprint_area(design) > 400.0


def test_the_volume_is_still_exact_with_utm_coordinates():
    """The same checks a UTM plan away: eastings of 229 000 and northings
    of 8 181 000. The first version lost the constant term of each plane
    to cancellation and reported 1 918 m³ of fill on a pad that has 13."""
    ground = build_tin([(229100.0 + i * 10.0, 8181300.0 + j * 10.0, 2335.0)
                        for i in range(11) for j in range(11)])
    lifted = Tin([(x, y, z + 1.0) for x, y, z in ground.points], list(ground.triangles), "UP")
    cut, fill = grading.volume_between(ground, lifted)
    assert cut == pytest.approx(0.0, abs=1e-6) and fill == pytest.approx(10000.0, rel=1e-9)
    pad = [(229140.0, 8181340.0), (229160.0, 8181340.0), (229160.0, 8181360.0), (229140.0, 8181360.0)]
    z_of = grading.platform_plane(pad[0], 2333.0)
    day = grading.daylight_line(ground, pad, z_of, grading.SlopeSpec(1.0, 1.0), sample=0.5)
    design = grading.design_surface(pad, z_of, day)
    cut, fill = grading.volume_between(ground, design)
    grid_cut, grid_fill = _grid_volume(ground, design)
    assert cut == pytest.approx(grid_cut, rel=0.02) and fill == pytest.approx(0.0, abs=1e-6)
