# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The curve-flattening tolerance must not cost a walk over the drawing.

Profiling a regen of a 10 847-entity plan showed a third of it going into
``bbox.extents``, walking every entity — purely to pick how finely curves get
flattened. The header carries the same rectangle for free.

Measured on real drawings, the two agree to 1.000–1.002, and the regen of that
plan went from 10.5 s to 7.4 s. What these tests pin is the *guards*: the
header is trusted only when it is a drawing, never when it is a sentinel, and
the walk is still there for everything else.
"""
from __future__ import annotations

import sys
from pathlib import Path

import ezdxf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from render.backend import (FLATTEN_REL, MIN_FLATTEN,  # noqa: E402
                            _flatten_distance, _header_diagonal)


def _doc(extmin, extmax):
    doc = ezdxf.new()
    if extmin is not None:
        doc.header["$EXTMIN"] = extmin
        doc.header["$EXTMAX"] = extmax
    return doc


def test_the_header_is_used_when_it_describes_a_drawing() -> None:
    doc = _doc((0, 0, 0), (300, 400, 0))
    assert _header_diagonal(doc.modelspace()) == 500.0          # 3-4-5
    assert _flatten_distance(doc.modelspace()) == 500.0 * FLATTEN_REL


def test_a_never_regenerated_drawing_is_not_trusted() -> None:
    """AutoCAD leaves ±1e20 in a drawing whose extents were never computed."""
    doc = _doc((1e20, 1e20, 0), (-1e20, -1e20, 0))
    assert _header_diagonal(doc.modelspace()) is None


def test_degenerate_and_broken_headers_fall_back() -> None:
    assert _header_diagonal(_doc((5, 5, 0), (5, 5, 0)).modelspace()) is None
    assert _header_diagonal(_doc(
        (0, 0, 0), (float("inf"), 1, 0)).modelspace()) is None
    assert _header_diagonal(_doc(
        (0, 0, 0), (float("nan"), 1, 0)).modelspace()) is None


def test_without_a_header_it_still_measures_the_drawing() -> None:
    """The fallback is the old behaviour, and it must still be reached."""
    doc = _doc(None, None)
    doc.header["$EXTMIN"] = (1e20, 1e20, 0)      # force the sentinel
    doc.header["$EXTMAX"] = (-1e20, -1e20, 0)
    msp = doc.modelspace()
    msp.add_line((0, 0), (300, 400))
    assert _header_diagonal(msp) is None
    assert _flatten_distance(msp) == 500.0 * FLATTEN_REL


def test_an_empty_drawing_never_returns_zero() -> None:
    doc = _doc(None, None)
    doc.header["$EXTMIN"] = (1e20, 1e20, 0)
    doc.header["$EXTMAX"] = (-1e20, -1e20, 0)
    assert _flatten_distance(doc.modelspace()) > 0.0


def test_a_tiny_drawing_keeps_the_floor() -> None:
    doc = _doc((0, 0, 0), (1e-9, 1e-9, 0))
    assert _flatten_distance(doc.modelspace()) == MIN_FLATTEN


def test_a_paperspace_layout_reads_its_own_extents() -> None:
    doc = _doc((0, 0, 0), (300, 400, 0))
    doc.header["$PEXTMIN"] = (0, 0, 0)
    doc.header["$PEXTMAX"] = (30, 40, 0)
    layout = doc.layout("Layout1")
    assert _header_diagonal(layout) == 50.0     # not the modelspace's 500
