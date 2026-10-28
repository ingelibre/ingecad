# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""BREAK on polylines keeps arcs arcs and closed shapes whole.

GeoCad Yaguarete (Fernando Bellocchio's plugin) had to work around it:
BREAK at one point turned a cut arc segment into a straight chord, lost a
closed polyline's closing segment, and a circle broken at one point
vanished. AutoCAD: "Closed objects such as circles cannot be broken at a
single point" (BREAK, p. 271).
"""
from __future__ import annotations

import math

import ezdxf
import pytest
from ezdxf import path as ezpath

from core import modify
from core.commands import History
from core.document import Document


def _length(rows):
    doc = ezdxf.new()
    poly = doc.modelspace().add_lwpolyline(rows, format="xyseb")
    return sum(math.dist(a, b) for a, b in zip(
        list(ezpath.make_path(poly).flattening(1e-4)),
        list(ezpath.make_path(poly).flattening(1e-4))[1:]))


def _poly(points, closed=False):
    doc = ezdxf.new()
    poly = doc.modelspace().add_lwpolyline(points, format="xyb")
    poly.closed = closed
    return poly


def test_a_cut_arc_segment_stays_an_arc():
    # a semicircle of radius 10, counterclockwise from (0,0) to (20,0):
    # it runs below, through (10,-10)
    poly = _poly([(0, 0, 1.0), (20, 0, 0.0)])
    pieces = modify.break_pieces(poly, (10, -10), (10, -10))
    assert len(pieces) == 2
    for _kind, rows, closed in pieces:
        assert not closed
        assert rows[0][4] == pytest.approx(math.tan(math.pi / 8)), \
            "the quarter arc became a chord"
        # ezdxf traces arcs as Bezier curves: 1e-4 off the true length
        assert _length(rows) == pytest.approx(math.pi * 10 / 2, rel=1e-3)


def test_a_closed_polyline_opens_once_with_its_closing_segment():
    square = _poly([(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)], closed=True)
    # remove from (5,0) forward to (10,5): 5 + 5 along the polyline
    pieces = modify.break_pieces(square, (5, 0), (10, 5))
    assert len(pieces) == 1
    _kind, rows, closed = pieces[0]
    assert not closed
    assert (rows[0][0], rows[0][1]) == (10, 5)
    assert (rows[-1][0], rows[-1][1]) == (5, 0)
    assert _length(rows) == pytest.approx(30), "the closing segment was lost"


def test_a_closed_object_is_not_broken_at_one_point():
    square = _poly([(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)], closed=True)
    with pytest.raises(modify.ClosedAtOnePoint):
        modify.break_pieces(square, (5, 0), (5, 0))
    circle = ezdxf.new().modelspace().add_circle((0, 0), 5)
    with pytest.raises(modify.ClosedAtOnePoint):
        modify.break_pieces(circle, (5, 0), (5, 0))


def test_break_at_one_point_on_a_circle_leaves_it_and_says_why(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        win.new_document()
        t = win.tools
        circle = win.document.modelspace().add_circle((0, 0), 5)
        t.attach_document(win.document)
        win.dispatcher.submit("BREAK")
        t.on_hover(5, 0, threshold_world=0.5)
        t.on_click(5, 0)
        t.on_text("@")                 # the same point, as AutoCAD types it
        assert circle.is_alive, "the circle vanished"
        assert "cannot be broken at a single point" in \
            win.command_line.history.toPlainText() or \
            "no se pueden partir en un solo punto" in \
            win.command_line.history.toPlainText()
    finally:
        win.document.dirty = False
        win.close()


def test_an_open_polyline_cut_at_a_vertex_has_no_repeated_vertex():
    poly = _poly([(0, 0, 0), (10, 0, 0), (10, 10, 0)])
    pieces = modify.break_pieces(poly, (10, 0), (10, 0))
    assert [len(rows) for _k, rows, _c in pieces] == [2, 2]
