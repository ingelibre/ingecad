# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""EXPLODE breaks a pattern hatch into its lines.

Classic CAD's EXPLODE turns a hatch into the lines of its pattern, on the
hatch's layer and with its colour; a solid fill has no lines to give and is
left whole ("could not be exploded"). EXPLODE answered "Nothing that can be
exploded was selected." for any hatch.
"""
from __future__ import annotations

import time

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
    w.document.dirty = False
    w.close()


def _type(win, *texts):
    for text in texts:
        win._on_command_submitted(text)


def _hatched_square(win, pattern="ANSI31"):
    _type(win, "LAYER", "M", "RAYADO", "", "COLOR", "1",
          "RECTANG", "0,0", "10,10", "ZOOM", "E")
    if pattern == "SOLID":
        _type(win, "-HATCH", "P", "SOLID", "5,5", "")
    else:
        _type(win, "-HATCH", "P", pattern, "1", "0", "5,5", "")
    (hatch,) = win.document.modelspace().query("HATCH")
    return hatch


def _history(win) -> str:
    return win.command_line.history.toPlainText()


def test_a_pattern_hatch_becomes_lines_on_its_layer(win):
    hatch = _hatched_square(win)
    expected = actions.hatch_pattern_lines(hatch)
    assert expected
    msp = win.document.modelspace()
    lines_before = len(msp.query("LINE"))
    win.tools.select_entities([hatch])
    _type(win, "EXPLODE")
    assert not list(msp.query("HATCH"))
    lines = list(msp.query("LINE"))[lines_before:]
    assert len(lines) == len(expected)
    assert {e.dxf.layer for e in lines} == {hatch.dxf.layer}
    assert {e.dxf.color for e in lines} == {hatch.dxf.color}
    for e in lines:     # every line stays inside the square
        for p in (e.dxf.start, e.dxf.end):
            assert -1e-6 <= p.x <= 10 + 1e-6 and -1e-6 <= p.y <= 10 + 1e-6
    assert "1 exploded." in _history(win)
    _type(win, "U")
    assert len(msp.query("HATCH")) == 1
    assert len(msp.query("LINE")) == lines_before


def test_the_lines_are_picked_and_the_hatch_is_gone_from_the_index(win):
    hatch = _hatched_square(win)
    handle = hatch.dxf.handle
    win.tools.select_entities([hatch])
    _type(win, "EXPLODE")
    handles = set(win.tools.index.window((-1, -1, 11, 11)))
    assert handle not in handles
    db = win.document.doc.entitydb
    assert sum(db[h].dxftype() == "LINE" for h in handles) > 4


def _wait_regen(qapp, win, timeout_s=20.0):
    t0 = time.monotonic()
    while (win._regen_worker is not None or win.viewport._scene is None) \
            and time.monotonic() - t0 < timeout_s:
        qapp.processEvents()
    assert win.viewport._scene is not None, "regen never landed"


def test_a_solid_fill_is_left_whole(qapp, win):
    hatch = _hatched_square(win, "SOLID")
    win.regen_in_memory()
    _wait_regen(qapp, win)
    assert hatch.dxf.handle in win.viewport._scene.handle_ranges
    win.tools.select_entities([hatch])
    _type(win, "EXPLODE")
    assert list(win.document.modelspace().query("HATCH")) == [hatch]
    assert "1 could not be exploded." in _history(win)
    # ...and stays on screen
    assert hatch.dxf.handle not in win.viewport._hidden_rgba


def test_a_hatch_past_the_line_cap_is_left_whole(win, monkeypatch):
    hatch = _hatched_square(win)
    monkeypatch.setattr(actions, "HPMAXLINES", 3)
    win.tools.select_entities([hatch])
    _type(win, "EXPLODE")
    assert list(win.document.modelspace().query("HATCH")) == [hatch]
    assert actions.too_dense_message() in _history(win)
