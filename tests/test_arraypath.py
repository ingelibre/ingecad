# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""ARRAYPATH: copies along a curve (trees along a road, lamp posts).

Asked for in a review video: classic CAD's path array, by distance
between items (Measure) or spread over the curve (Divide). Ours makes plain
copies, as ARRAY does. The first item is the original where it is, and
each copy keeps its offset from the path, turning as the path turns.
"""
from __future__ import annotations

import math

import pytest

from core import actions, modify


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w.new_document()
    w.tools.osnap_on = False
    yield w
    w.document.dirty = False
    w.close()


def _type(win, *texts):
    for text in texts:
        win._on_command_submitted(text)


def _history(win) -> str:
    return win.command_line.history.toPlainText()


def _circles(win):
    return sorted(((round(c.dxf.center.x, 6), round(c.dxf.center.y, 6))
                   for c in win.document.modelspace().query("CIRCLE")))


def _tree_and_road(win, road=("0,0", "100,0")):
    """A tree (circle r=1) 3 units off a road (a line) at its start."""
    _type(win, "CIRCLE", "0,3", "1", "LINE", *road, "", "ZOOM", "E")
    (tree,) = win.document.modelspace().query("CIRCLE")
    road_line = list(win.document.modelspace().query("LINE"))[-1]
    return tree, road_line


def _pick(win, entity, point):
    """Select ``entity`` for the command, then click ``point`` on the path."""
    win.tools.select_entities([entity])
    _type(win, "ARRAYPATH")
    win.tools.on_click(*point)


def test_measure_places_copies_every_distance_along_a_line(win):
    tree, road = _tree_and_road(win)
    _pick(win, tree, (1.0, 0.0))
    assert "Type = Path  Associative = No" in _history(win)
    _type(win, "I", "20", "", "")      # every 20, fill the road, then Enter
    assert _circles(win) == [(x, 3.0) for x in (0, 20, 40, 60, 80, 100)]
    assert "5 copies placed." in _history(win)
    _type(win, "U")
    assert _circles(win) == [(0.0, 3.0)]


def test_the_path_runs_from_the_end_picked(win):
    tree, road = _tree_and_road(win, road=("0,0", "100,0"))
    tree.dxf.center = (100, 3)
    _pick(win, tree, (99.0, 0.0))
    _type(win, "I", "25", "", "")
    assert _circles(win) == [(x, 3.0) for x in (0, 25, 50, 75, 100)]


def test_a_number_of_items_caps_the_fill(win):
    tree, road = _tree_and_road(win)
    _pick(win, tree, (1.0, 0.0))
    _type(win, "I", "10", "3", "")
    assert _circles(win) == [(0.0, 3.0), (10.0, 3.0), (20.0, 3.0)]


def test_divide_spreads_the_items_over_the_whole_path(win):
    tree, road = _tree_and_road(win)
    _pick(win, tree, (1.0, 0.0))
    _type(win, "M", "D", "I", "5", "X")
    assert _circles(win) == [(x, 3.0) for x in (0, 25, 50, 75, 100)]


def test_copies_turn_with_the_path_and_keep_their_offset(win):
    # an L-shaped road: along X, then up Y; a tree 3 units to its left
    tree, _ = _tree_and_road(win, road=("0,0", "0,0"))
    _type(win, "ERASE", "L", "", "PLINE", "0,0", "50,0", "50,50", "")
    road = list(win.document.modelspace().query("LWPOLYLINE"))[-1]
    _pick(win, tree, (1.0, 0.0))
    _type(win, "I", "25", "", "")
    centers = _circles(win)
    # on the second leg the left side is -X: 3 units to the left of x=50
    assert (47.0, 25.0) in centers and (47.0, 50.0) in centers
    assert (25.0, 3.0) in centers
    assert road.dxf.handle in {e.dxf.handle for e in
                               win.document.modelspace()}


def test_align_no_keeps_the_offset_as_it_is(win):
    tree, _ = _tree_and_road(win, road=("0,0", "0,0"))
    _type(win, "ERASE", "L", "", "PLINE", "0,0", "50,0", "50,50", "")
    _pick(win, tree, (1.0, 0.0))
    _type(win, "A", "N", "I", "25", "", "")
    assert (50.0, 28.0) in _circles(win)


def test_a_base_point_puts_the_originals_on_the_path(win):
    tree, road = _tree_and_road(win)
    _pick(win, tree, (1.0, 0.0))
    _type(win, "B", "0,2", "I", "50", "", "")
    # the tree's point (0,2) rides the road: the original moves too
    assert _circles(win) == [(0.0, 1.0), (50.0, 1.0), (100.0, 1.0)]
    _type(win, "U")
    assert _circles(win) == [(0.0, 3.0)]


def test_a_closed_path_never_doubles_the_first_item(win):
    _type(win, "CIRCLE", "0,0", "10", "CIRCLE", "10,0", "0.5", "ZOOM", "E")
    ring, post = list(win.document.modelspace().query("CIRCLE"))
    _pick(win, post, (0.0, 10.0))
    _type(win, "M", "D", "I", "4", "")
    posts = [c for c in _circles(win) if c != (0.0, 0.0)]
    assert len(posts) == 4
    for x, y in posts:
        assert math.hypot(x, y) == pytest.approx(10.0)


def test_the_array_shows_while_its_options_are_edited(win):
    tree, road = _tree_and_road(win)
    _pick(win, tree, (1.0, 0.0))
    _type(win, "I", "20", "")
    ghosts = win.tools.tool.preview_entities((0.0, 0.0))
    assert sorted(round(g.dxf.center.x) for g in ghosts) == [20, 40, 60, 80,
                                                             100]
    assert _circles(win) == [(0.0, 3.0)]      # nothing placed yet


def test_not_a_curve_is_refused(win):
    tree, road = _tree_and_road(win)
    win.tools._execute(actions.add_text((50, 20), "ROAD", 2.0))
    assert win.tools.pick_entity((51.0, 21.0)).dxftype() == "TEXT"
    _pick(win, tree, (51.0, 21.0))
    assert "Select a line, arc, circle, ellipse, polyline or spline." in \
        _history(win)
    win.tools.on_click(1.0, 0.0)      # the road is still asked for
    _type(win, "I", "50", "", "")
    assert len(_circles(win)) == 3


def test_positions_and_fill():
    assert modify.path_fill_count(100.0, False, 20.0) == 6
    assert modify.path_fill_count(100.0, True, 25.0) == 4
    assert modify.path_positions(100.0, False, "divide", 3) == [0, 50, 100]
    assert modify.path_positions(100.0, True, "divide", 4) == [0, 25, 50, 75]
    assert modify.path_positions(100.0, False, "measure", 3, 30.0) == [
        0, 30, 60]
