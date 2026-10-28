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


# -- linear dimensions: the pick order of the origins must not show ------------

def _dim_block_signature(doc, dim):
    """What the *D block draws, independent of entity order: the line
    segments (endpoints unordered), the arrowheads (name, tip, rotation)
    and the text (insert, rotation)."""
    from ezdxf.math import Vec2

    def r(v):
        return (round(v.x, 6), round(v.y, 6))

    lines, arrows, texts = set(), set(), set()
    for e in doc.blocks.get(dim.dxf.geometry):
        if e.dxftype() == "LINE":
            lines.add(frozenset((r(Vec2(e.dxf.start)), r(Vec2(e.dxf.end)))))
        elif e.dxftype() == "INSERT":
            arrows.add((e.dxf.name, r(Vec2(e.dxf.insert)),
                        round(e.dxf.rotation % 360.0, 6)))
        elif e.dxftype() in ("MTEXT", "TEXT"):
            texts.add((r(Vec2(e.dxf.insert)),
                       round(e.dxf.get("rotation", 0.0) % 360.0, 6)))
    return lines, arrows, texts


def test_linear_dimensions_draw_the_same_whichever_origin_is_picked_first():
    """A tester dimensioned a rectangle from its right corner to its left
    one and got the text under the line and the arrowheads outside pointing
    in (ezdxf follows defpoint2 -> defpoint3; AutoCAD follows the angle).
    Both orders, horizontal and vertical, linear and aligned: identical
    blocks, text above the line reading from the bottom or the right, and
    the entity keeps the order the user picked."""
    from core import ezdxf_patches
    from core.document import Document

    ezdxf_patches.apply()
    doc = Document.new().doc          # ISO-25: text above the line
    msp = doc.modelspace()

    def linear(p1, p2, base, angle):
        return msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle,
                                  dimstyle="ISO-25").render().dimension

    def aligned(p1, p2, distance):
        return msp.add_aligned_dim(p1=p1, p2=p2, distance=distance,
                                   dimstyle="ISO-25").render().dimension

    cases = [
        (linear((10, 10), (60, 10), (35, 20), 0),
         linear((60, 10), (10, 10), (35, 20), 0)),
        (linear((10, 10), (10, 60), (20, 35), 90),
         linear((10, 60), (10, 10), (20, 35), 90)),
        (aligned((10, 10), (60, 10), 10.0),
         aligned((60, 10), (10, 10), -10.0)),
        (aligned((10, 10), (10, 60), -10.0),
         aligned((10, 60), (10, 10), 10.0)),
    ]
    for forward, backward in cases:
        assert _dim_block_signature(doc, forward) \
            == _dim_block_signature(doc, backward)

    # the horizontal text sits ABOVE its line, unrotated; the vertical one
    # reads bottom-to-top on the LEFT of its line -- AutoCAD's placement
    horizontal, vertical = cases[0][1], cases[1][1]
    _, _, texts = _dim_block_signature(doc, horizontal)
    (insert, rotation), = texts
    assert rotation == 0.0 and insert[1] > 20.0
    _, _, texts = _dim_block_signature(doc, vertical)
    (insert, rotation), = texts
    assert rotation == 90.0 and insert[0] < 20.0

    # the entity is untouched: the user's order and angle survive the render
    backward = cases[0][1]
    assert tuple(backward.dxf.defpoint2)[:2] == (60.0, 10.0)
    assert tuple(backward.dxf.defpoint3)[:2] == (10.0, 10.0)
    backward_aligned = cases[2][1]
    assert backward_aligned.dxf.angle == 180.0


def test_reading_angle_folds_into_bottom_or_right():
    from core.ezdxf_patches import reading_angle

    assert reading_angle(0.0) == 0.0
    assert reading_angle(90.0) == 90.0
    assert reading_angle(180.0) == 0.0
    assert reading_angle(270.0) == 90.0
    assert reading_angle(-90.0) == 90.0
    assert reading_angle(200.0) == 20.0
    assert reading_angle(300.0) == -60.0
    assert reading_angle(89.0) == 89.0


def test_fixed_height_text_style_is_not_scaled_by_dimscale():
    """A fixed-height text style sets dimension text as is, as AutoCAD does.

    A colleague's portico plan (DIMSCALE 304.8, style height 62.5): ezdxf
    multiplied the style's height by DIMSCALE, so the first grip drop grew
    every label from 62.5 to 19050. Driven through the grip's own Command.
    """
    from core.actions import DimGripCommand
    from core.commands import History
    from core.document import Document

    doc = Document.new()
    d = doc.doc
    d.styles.add("FixedNarrow", font="arial.ttf").dxf.height = 62.5
    d.dimstyles.new("Portico", dxfattribs={
        "dimscale": 304.8, "dimtxt": 2.5, "dimtxsty": "FixedNarrow"})
    dim = doc.modelspace().add_linear_dim(
        base=(0, 1000), p1=(0, 0), p2=(5000, 0), dimstyle="Portico") \
        .render().dimension

    def text_height():
        for e in d.blocks.get(dim.dxf.geometry):
            if e.dxftype() == "MTEXT":
                return e.dxf.char_height
        raise AssertionError("no text in the dimension block")

    assert abs(text_height() - 62.5) < 1e-9
    History(doc).execute(DimGripCommand(dim, "defpoint", (0.0, 1500.0)))
    assert abs(text_height() - 62.5) < 1e-9
    # a variable-height style still scales DIMTXT by DIMSCALE
    d.dimstyles.new("Variable", dxfattribs={"dimscale": 10.0, "dimtxt": 2.5})
    other = doc.modelspace().add_linear_dim(
        base=(0, 100), p1=(0, 0), p2=(500, 0), dimstyle="Variable") \
        .render().dimension
    heights = [e.dxf.char_height for e in d.blocks.get(other.dxf.geometry)
               if e.dxftype() == "MTEXT"]
    assert heights and abs(heights[0] - 25.0) < 1e-9
