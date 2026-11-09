# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""MATCHPROP's destinations come by window and crossing too, and one
object selected beforehand is the source.

A third-party plugin replaced the tool: its destinations could only be
clicked one by one, and a preselected source was ignored.
"""
from __future__ import annotations

import pytest

from core import actions


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w.new_document()
    w.tools.osnap_on = False
    yield w
    w.tools.cancel()
    w.document.dirty = False
    w.close()


def _lines(win):
    """A red source at y=0, three plain lines at y=10, 20 and 30."""
    tools = win.tools
    tools._execute(actions.add_line((0, 0), (10, 0)))
    for y in (10, 20, 30):
        tools._execute(actions.add_line((0, y), (10, y)))
    win._on_command_submitted("ZOOM")
    win._on_command_submitted("E")
    lines = sorted(win.document.modelspace().query("LINE"),
                   key=lambda e: e.dxf.start.y)
    lines[0].dxf.color = 1
    return lines


def _click(win, x, y):
    win.tools.on_hover(x, y, threshold_world=0.3)
    win.tools.on_click(x, y)


def _colors(lines):
    return [e.dxf.get("color", 256) for e in lines]


def test_a_crossing_paints_what_it_touches(win):
    lines = _lines(win)
    win._on_command_submitted("MATCHPROP")
    _click(win, 5, 0)                        # the source
    _click(win, 8, 25)                       # empty: a window starts
    _click(win, 2, 5)                        # right to left: crossing
    assert _colors(lines) == [1, 1, 1, 256]
    win._on_command_submitted("")            # Enter ends the painting
    win._on_command_submitted("U")
    assert _colors(lines) == [1, 256, 256, 256]


def test_a_window_paints_only_what_it_encloses(win):
    lines = _lines(win)
    win._on_command_submitted("MATCHPROP")
    _click(win, 5, 0)
    _click(win, -1, 15)                      # left to right: window,
    _click(win, 6, 35)                       # over half of 20 and 30
    assert _colors(lines) == [1, 256, 256, 256]
    _click(win, -1, 15)                      # the whole of 20
    _click(win, 11, 25)
    assert _colors(lines) == [1, 256, 1, 256]
    _click(win, 5, 10)                       # and a click still paints
    assert _colors(lines) == [1, 1, 1, 256]


def test_a_preselected_object_is_the_source(win):
    lines = _lines(win)
    win.tools.select_entities([lines[0]])
    win._on_command_submitted("MATCHPROP")
    _click(win, 5, 30)
    assert _colors(lines) == [1, 256, 256, 1]
