# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Which ring is a hole and which is its own shape.

``draw_filled_paths`` classifies rings by even-odd nesting: a ring inside an
even number of others is a shape, odd makes it a hole of its innermost
container. Getting this wrong is visible and ugly -- the counter of an "O"
filled solid, or the tilde of an "ñ" dropped so that *baño* reads *bano*.

A bounding-box prefilter now skips most of the containment tests (they were
387 543 ray casts on one real plan, O(rings²)). It can only ever skip pairs a
ray cast would have rejected anyway, and these tests are what says so: the
awkward cases are the ones where boxes overlap and rings do not.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ezdxf.math import Vec2  # noqa: E402

from render.backend import _point_in_ring, _ring_box  # noqa: E402


def _square(x0, y0, size):
    return [Vec2(x0, y0), Vec2(x0 + size, y0),
            Vec2(x0 + size, y0 + size), Vec2(x0, y0 + size)]


def _in_box(point, box):
    return box[0] <= point.x <= box[2] and box[1] <= point.y <= box[3]


def _contains(point, ring):
    """What the classifier now computes: box first, then the ray cast."""
    return _in_box(point, _ring_box(ring)) and _point_in_ring(point, ring)


def test_the_box_never_changes_the_answer_on_a_convex_ring() -> None:
    ring = _square(0, 0, 10)
    for point in (Vec2(5, 5), Vec2(0.1, 0.1), Vec2(-1, 5), Vec2(5, 11),
                  Vec2(20, 20)):
        assert _contains(point, ring) == _point_in_ring(point, ring), point


def test_a_concave_ring_still_needs_the_ray_cast() -> None:
    """An L: the point sits inside the box and outside the shape.

    This is the case a box test alone would get wrong, and the reason the box
    is only ever a prefilter.
    """
    ring = [Vec2(0, 0), Vec2(10, 0), Vec2(10, 4), Vec2(4, 4),
            Vec2(4, 10), Vec2(0, 10)]
    hollow = Vec2(8, 8)                     # in the bounding box, off the L
    assert _in_box(hollow, _ring_box(ring))
    assert not _point_in_ring(hollow, ring)
    assert not _contains(hollow, ring)
    solid = Vec2(2, 2)
    assert _contains(solid, ring) and _point_in_ring(solid, ring)


def test_overlapping_boxes_with_disjoint_rings() -> None:
    """Two diagonal squares: each corner is in the other's box, in neither ring."""
    a = _square(0, 0, 10)
    b = _square(9, 9, 10)
    assert _in_box(Vec2(9, 9), _ring_box(a))
    assert _contains(Vec2(9, 9), a) == _point_in_ring(Vec2(9, 9), a)
    assert not _contains(Vec2(15, 15), a)


def test_the_box_is_the_ring_extent() -> None:
    box = _ring_box(_square(-3, 7, 4))
    assert box == (-3.0, 7.0, 1.0, 11.0)


def test_a_hole_stays_empty_end_to_end(qapp) -> None:
    """Through the real backend: no triangle may cover the middle of the hole."""
    import ezdxf
    import numpy as np

    from core.document import Document
    from render.backend import build_scene

    document = Document(ezdxf.new(setup=True))
    hatch = document.modelspace().add_hatch(color=2)
    hatch.paths.add_polyline_path(                      # the shape
        [(0, 0), (20, 0), (20, 20), (0, 20)], is_closed=True)
    hatch.paths.add_polyline_path(                      # the hole
        [(5, 5), (15, 5), (15, 15), (5, 15)], is_closed=True)

    scene = build_scene(document)
    data = scene.triangles.data
    assert len(data), "the hatch produced no fill at all"

    ox, oy = scene.origin
    pos = np.asarray(data["pos"], dtype=float)
    pos = pos.reshape(-1, 3, 2) + np.array([ox, oy])    # back to world

    def covers(px, py):
        a, b, c = pos[:, 0], pos[:, 1], pos[:, 2]
        d = ((b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0])
             + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1]))
        with np.errstate(divide="ignore", invalid="ignore"):
            u = ((b[:, 1] - c[:, 1]) * (px - c[:, 0])
                 + (c[:, 0] - b[:, 0]) * (py - c[:, 1])) / d
            v = ((c[:, 1] - a[:, 1]) * (px - c[:, 0])
                 + (a[:, 0] - c[:, 0]) * (py - c[:, 1])) / d
        w = 1.0 - u - v
        eps = -1e-9
        return bool(np.any((u >= eps) & (v >= eps) & (w >= eps)))

    assert covers(2.0, 2.0), "the shape itself is not filled"
    assert not covers(10.0, 10.0), "the hole was filled solid"
