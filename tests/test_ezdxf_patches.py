# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The runtime patches applied to ezdxf, and what they must not change.

``core/ezdxf_patches.py`` rewrites a few ezdxf internals at import. Most
correct a defect; this one corrects a cost. Either way the rule is the same:
the patched function must answer exactly what the original answered, and these
tests are what keeps that true when ezdxf is upgraded.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_lwpolyline_get_points_is_patched_and_exact() -> None:
    """The fast path must answer exactly what ezdxf's format_point answers.

    ezdxf builds a dict per vertex (``locals()`` inside ``format_point``), and
    the drawing frontend asks every LWPOLYLINE for "xyb" on its way to a Path:
    ~20% of a regen of a real 10 847-entity plan, two million calls. The
    replacement resolves the format once per call instead of once per point.
    """
    import random

    import ezdxf
    from ezdxf.entities.lwpolyline import LWPolyline, format_point

    from core import ezdxf_patches

    ezdxf_patches.apply()
    assert getattr(LWPolyline.get_points, "_ingecad_patch", False)

    doc = ezdxf.new()
    msp = doc.modelspace()
    random.seed(7)
    polylines = [
        msp.add_lwpolyline(
            [(random.uniform(-1e6, 1e6), random.uniform(-1e6, 1e6),
              random.uniform(0, 3), random.uniform(0, 3),
              random.choice([0.0, 0.3, -1.7])) for _ in range(n)],
            format="xyseb")
        for n in (2, 3, 17, 400)
    ]
    # every shape of format string, including the odd ones: order follows the
    # string, unknown characters are skipped, "v" is the (x, y) pair
    formats = ["xyseb", "xyb", "xy", "v", "vb", "xyse", "yx", "bxy", "xyzb",
               "", "XYB", "sebxy", "vv", "bb", "z"]
    for polyline in polylines:
        for fmt in formats:
            expected = [format_point(p, format=fmt) for p in polyline.lwpoints]
            assert polyline.get_points(fmt) == expected, fmt
        assert polyline.get_points() == [format_point(p)
                                         for p in polyline.lwpoints]


def test_applying_the_patches_twice_is_harmless() -> None:
    from ezdxf.entities.lwpolyline import LWPolyline

    from core import ezdxf_patches

    ezdxf_patches.apply()
    first = LWPolyline.get_points
    ezdxf_patches._patch_lwpolyline_get_points()
    assert LWPolyline.get_points is first
