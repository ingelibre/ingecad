# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Topography plugin, T3: the Delaunay triangulation, held to its own
definition (every circumcircle empty), Euler's count, a cocircular grid,
breaklines that become edges, and a time budget."""
from __future__ import annotations

import random
import time

import pytest

from plugins.topografia import tin as tin_mod
from plugins.topografia.tin import Delaunay, build_tin, convex_hull, in_circle, orient


def _random_points(n: int, seed: int = 1, size: float = 1000.0):
    rng = random.Random(seed)
    return [(rng.uniform(0, size), rng.uniform(0, size)) for _ in range(n)]


def _check_delaunay(pts, triangles, samples: int = 200, seed: int = 3):
    """CCW everywhere, and the empty-circumcircle property on a sample."""
    rng = random.Random(seed)
    for a, b, c in triangles:
        assert orient(pts[a], pts[b], pts[c]) > 0
    for a, b, c in rng.sample(triangles, min(samples, len(triangles))):
        for i, p in enumerate(pts):
            if i in (a, b, c):
                continue
            assert not in_circle(pts[a], pts[b], pts[c], p), (a, b, c, i)


def test_random_points_give_a_delaunay_triangulation_with_eulers_count():
    pts = _random_points(1500)
    triangles = Delaunay(pts).triangles()
    hull = len(convex_hull(pts))
    assert len(triangles) == 2 * len(pts) - hull - 2
    _check_delaunay(pts, triangles)


def test_a_regular_grid_is_cocircular_everywhere_and_still_triangulates():
    pts = [(float(i), float(j)) for i in range(30) for j in range(30)]
    triangles = Delaunay(pts).triangles()
    assert len(triangles) == 2 * 29 * 29
    _check_delaunay(pts, triangles, samples=100)


def test_utm_sized_coordinates_do_not_lose_precision():
    pts = [(229140.0 + x, 8181320.0 + y) for x, y in _random_points(400, seed=5, size=60.0)]
    triangles = Delaunay(pts).triangles()
    hull = len(convex_hull(pts))
    assert len(triangles) == 2 * len(pts) - hull - 2
    _check_delaunay(pts, triangles, samples=60)


def test_duplicate_shots_collapse_and_three_points_are_enough():
    tin = build_tin([(0, 0, 10), (10, 0, 11), (0, 10, 12), (0, 0, 99)])
    assert len(tin.points) == 3 and tin.points[0][2] == 10.0       # first Z wins
    assert tin.triangles == [(0, 1, 2)] or len(tin.triangles) == 1
    with pytest.raises(ValueError):
        Delaunay([(0, 0), (1, 1)])


def test_a_breakline_becomes_an_edge_of_the_surface():
    rng = random.Random(9)
    pts = [(rng.uniform(0, 100), rng.uniform(0, 100), rng.uniform(0, 5)) for _ in range(300)]
    # a ridge line from the west edge to the east edge, at heights of its own
    ridge = [(0.0, 50.0, 20.0), (35.0, 52.0, 21.0), (70.0, 48.0, 22.0), (100.0, 50.0, 23.0)]
    tin = build_tin(pts, breaklines=[ridge])
    n0 = len(pts)
    edges = tin.edges()
    for k in range(len(ridge) - 1):
        u, v = n0 + k, n0 + k + 1
        assert ((u, v) if u < v else (v, u)) in edges, f"ridge segment {k} not an edge"
    assert tin.stats()["bad_edges"] == 0
    assert tin.z_at(35.0, 52.0) == pytest.approx(21.0)                 # on the ridge


def test_boundary_and_longest_edge_prune_what_a_survey_never_meant():
    pts = [(float(i), float(j), 0.0) for i in range(0, 50, 5) for j in range(0, 50, 5)]
    full = build_tin(pts)
    clipped = build_tin(pts, boundary=[(0, 0), (25, 0), (25, 25), (0, 25)])
    assert 0 < len(clipped.triangles) < len(full.triangles)
    assert all(tin_mod._centre(clipped.points, t)[0] < 25 for t in clipped.triangles)
    sparse = build_tin(pts + [(200.0, 200.0, 0.0)], max_edge=8.0)
    assert len(sparse.triangles) == len(full.triangles)                 # the far point's slivers go
    stats = full.stats()
    assert stats["points"] == 100 and stats["area_2d"] == pytest.approx(45.0 * 45.0)
    assert stats["boundary_edges"] == 36 and stats["bad_edges"] == 0


def test_the_surface_interpolates_and_answers_none_outside():
    tin = build_tin([(0, 0, 0.0), (10, 0, 10.0), (0, 10, 20.0), (10, 10, 30.0)])
    assert tin.z_at(5.0, 5.0) == pytest.approx(15.0)
    assert tin.z_at(0.0, 0.0) == pytest.approx(0.0)
    assert tin.z_at(50.0, 50.0) is None


def test_twenty_thousand_points_fit_the_budget():
    """The plan's number: 20 000 points in about two seconds locally. The
    assertion is loose for CI; the printed time is the measurement."""
    pts = _random_points(20000, seed=11, size=2000.0)
    t0 = time.perf_counter()
    triangles = Delaunay(pts).triangles()
    elapsed = time.perf_counter() - t0
    print(f"\nDelaunay 20 000 points: {elapsed:.2f} s, {len(triangles)} triangles")
    hull = len(convex_hull(pts))
    assert len(triangles) == 2 * len(pts) - hull - 2
    assert elapsed < 12.0
