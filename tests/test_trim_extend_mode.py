# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""TRIMEXTENDMODE: AutoCAD 2021's Quick and Standard TRIM/EXTEND.

Standard (IngeCAD's start, Marco 2026-10-10) is the classic flow Rafael
uses: pick the edges, Enter for all. Quick picks no edges -- every object
is one -- and erases a picked object nothing crosses (Rafael's seventh
review, 03:48 "le di lo que no era", and 08:23 erasing a stub by hand).
"""
from __future__ import annotations

import pytest

from core import actions, trimmode


@pytest.fixture
def mode(monkeypatch):
    """The setting in memory only: a test must not leave it saved."""
    state = {"value": 0}
    monkeypatch.setattr(trimmode, "trimextendmode", lambda: state["value"])
    monkeypatch.setattr(trimmode, "set_trimextendmode",
                        lambda v: state.__setitem__("value", 1 if v else 0))
    return state


def _window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    qapp.processEvents()
    return win


def _cross(win):
    t = win.tools
    t._execute(actions.add_line((0, 0), (20, 0)))       # the edge
    t._execute(actions.add_line((10, -5), (10, 5)))     # crosses it
    t._execute(actions.add_line((30, -5), (30, 5)))     # crosses nothing
    t.osnap_on = False
    return t


def _lines(win):
    return sorted((round(l.dxf.start.y, 3), round(l.dxf.end.y, 3), round(l.dxf.start.x, 3))
                  for l in win.document.modelspace().query("LINE"))


def test_standard_is_the_start_and_asks_for_edges(qapp, mode):
    win = _window(qapp)
    try:
        _cross(win)
        win.dispatcher.submit("TRIM")
        shown = win.command_line.history.toPlainText()
        assert "Mode=Standard" in shown
        assert win.tools._selecting_for is not None, "no edges were asked for"
        win.tools.cancel()
    finally:
        win.document.dirty = False
        win.close()


def test_quick_trims_on_the_first_pick_and_erases_what_nothing_crosses(qapp, mode):
    mode["value"] = 1
    win = _window(qapp)
    try:
        t = _cross(win)
        win.dispatcher.submit("TRIM")
        assert t._selecting_for is None, "Quick picks no edges"
        t.on_hover(10, 3, threshold_world=0.5)
        t.on_click(10, 3)                                  # the upper half
        t.on_hover(30, 2, threshold_world=0.5)
        t.on_click(30, 2)                                  # crosses nothing
        lines = _lines(win)
        assert (-5.0, 0.0, 10.0) in lines, lines           # trimmed at the edge
        assert not any(x == 30.0 for _a, _b, x in lines), "the stub stayed"
        t.cancel()
    finally:
        win.document.dirty = False
        win.close()


def test_mode_switches_and_is_remembered(qapp, mode):
    win = _window(qapp)
    try:
        t = _cross(win)
        win.dispatcher.submit("TRIM")
        t.on_text("")                                      # every edge
        t.on_text("O")
        t.on_text("Q")
        assert mode["value"] == 1 and t.tool.quick
        assert "cuTting edges" in t.current_prompt or "corTe" in t.current_prompt
        t.cancel()
    finally:
        win.document.dirty = False
        win.close()
