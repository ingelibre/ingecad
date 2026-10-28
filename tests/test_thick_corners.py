# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A polyline with a lineweight closes its corners (no notch).

Each thick segment was a rectangle ending square at its vertex, so every
corner of a wall drawn with LWT on showed a notch on its outside (a
plugin author patched the packer to fix it). Joined segments now end on
the shared miter, with no vertex added; past the miter limit a very
sharp corner keeps its notch rather than grow a spike.
"""
from __future__ import annotations

import ezdxf
import numpy as np
import pytest

from core.document import Document
from render.backend import build_scene

HALF = 1.0          # the shader's half width, in drawing units, for the test


def _triangles(points):
    doc = ezdxf.new("R2018")
    doc.modelspace().add_lwpolyline(points, close=True,
                                    dxfattribs={"lineweight": 100})
    scene = build_scene(Document(doc))
    data = scene.thick.data
    pos = data["pos"].astype(np.float64) + scene.origin
    corners = pos + data["normal"].astype(np.float64) * HALF
    return corners.reshape(-1, 3, 2)


def _covered(tris, p) -> bool:
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]

    def side(u, v):
        return ((v[:, 0] - u[:, 0]) * (p[1] - u[:, 1])
                - (v[:, 1] - u[:, 1]) * (p[0] - u[:, 0]))

    s1, s2, s3 = side(a, b), side(b, c), side(c, a)
    inside = (((s1 >= -1e-9) & (s2 >= -1e-9) & (s3 >= -1e-9))
              | ((s1 <= 1e-9) & (s2 <= 1e-9) & (s3 <= 1e-9)))
    return bool(inside.any())


@pytest.mark.parametrize("corner, outside", [
    ((100.0, 0.0), (100.9, -0.9)),          # the right angles of a wall
    ((100.0, 60.0), (100.9, 60.9)),
    ((0.0, 60.0), (-0.9, 60.9)),
    ((0.0, 0.0), (-0.9, -0.9)),             # the closing corner too
])
def test_every_corner_of_a_closed_wall_is_filled(corner, outside):
    tris = _triangles([(0, 0), (100, 0), (100, 60), (0, 60)])
    assert _covered(tris, np.array(outside))


def test_a_sharp_corner_gets_no_spike():
    # a 5 degree spike: the miter would reach 23 half widths out
    tris = _triangles([(0, 0), (100, 0), (0, 8.75)])
    assert not _covered(tris, np.array((105.0, 0.0)))
    assert tris.reshape(-1, 2)[:, 0].max() < 100 + 4 * HALF + 1e-6
