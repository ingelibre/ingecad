# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""TRIM and EXTEND with construction lines, from a tester's video.

He offsets an XLINE to lay out a perpendicular, then trims the infinite
lines at their crossings -- and TRIM answered "supports LINE, PLINE,
CIRCLE, ARC and ELLIPSE for now". Classic CAD trims an XLINE into rays
(and a piece cut at both ends into a line), and both kinds cut and bound
like any other edge.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    w = MainWindow()
    w.show()
    w.new_document()
    w.tools.osnap_on = False
    yield w
    w.document.dirty = False
    w.close()


def _pick(win, x, y):
    t = win.tools
    t.on_hover(x, y, threshold_world=0.3)
    t.on_click(x, y)


def _kinds(win):
    return sorted(e.dxftype() for e in win.document.modelspace())


def test_trim_an_xline_at_another_leaves_a_ray(win):
    from core import actions

    t = win.tools
    t._execute(actions.add_xline((0, 0), 90.0))      # vertical
    t._execute(actions.add_xline((0, 0), 0.0))       # horizontal
    win._on_command_submitted("TRIM")
    win._on_command_submitted("")                    # every object is an edge
    _pick(win, 0, -5)                                # the part below y = 0
    t.cancel()
    rays = [e for e in win.document.modelspace() if e.dxftype() == "RAY"]
    assert _kinds(win) == ["RAY", "XLINE"]
    ray = rays[0]
    assert (ray.dxf.start.x, ray.dxf.start.y) == pytest.approx((0, 0), abs=1e-6)
    assert ray.dxf.unit_vector.y == pytest.approx(1.0)


def test_trim_a_ray_between_two_cutters_leaves_a_line_and_a_ray(win):
    from core import actions

    t = win.tools
    t._execute(actions.add_ray((0, 0), 0.0))
    t._execute(actions.add_line((10, -5), (10, 5)))
    t._execute(actions.add_line((20, -5), (20, 5)))
    win._on_command_submitted("TRIM")
    win._on_command_submitted("")
    _pick(win, 15, 0)
    t.cancel()
    ms = win.document.modelspace()
    kept = [e for e in ms if e.dxftype() == "LINE" and e.dxf.start.y == 0]
    assert len(kept) == 1
    assert (kept[0].dxf.start.x, kept[0].dxf.end.x) == pytest.approx((0, 10))
    ray = next(e for e in ms if e.dxftype() == "RAY")
    assert ray.dxf.start.x == pytest.approx(20.0)


def test_an_xline_cuts_a_line(win):
    from core import actions

    t = win.tools
    t._execute(actions.add_xline((5, 0), 90.0))
    t._execute(actions.add_line((0, 0), (10, 0)))
    win._on_command_submitted("TRIM")
    win._on_command_submitted("")
    _pick(win, 8, 0)
    t.cancel()
    line = next(e for e in win.document.modelspace() if e.dxftype() == "LINE")
    assert (line.dxf.start.x, line.dxf.end.x) == pytest.approx((0, 5))


def test_extend_a_line_to_an_xline(win):
    from core import actions

    t = win.tools
    t._execute(actions.add_xline((50, 0), 90.0))
    t._execute(actions.add_line((0, 0), (10, 0)))
    win._on_command_submitted("EXTEND")
    win._on_command_submitted("")
    _pick(win, 9, 0)
    t.cancel()
    line = next(e for e in win.document.modelspace() if e.dxftype() == "LINE")
    assert line.dxf.end.x == pytest.approx(50.0)


def test_a_hidden_xline_does_not_cut(win):
    from core import actions

    t = win.tools
    for text in ("-LAYER", "M", "Aux", ""):
        win._on_command_submitted(text)
    t._execute(actions.add_xline((5, 0), 90.0))
    win._on_command_submitted("CLAYER")
    win._on_command_submitted("0")
    t._execute(actions.add_line((0, 0), (10, 0)))
    for text in ("-LAYER", "OFF", "Aux", ""):
        win._on_command_submitted(text)
    win._on_command_submitted("TRIM")
    win._on_command_submitted("")
    _pick(win, 8, 0)
    t.cancel()
    line = next(e for e in win.document.modelspace() if e.dxftype() == "LINE")
    assert (line.dxf.start.x, line.dxf.end.x) == (0, 10)
