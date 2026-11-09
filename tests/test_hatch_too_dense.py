# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A hatch past HPMAXLINES is refused, as classic CAD does.

A review video drew a region some 14 000 units wide and hatched it with
EARTH at scale 1: about twenty million dashes. The window froze while the
pattern was drawn, the drawing gave up after its time limit and the hatch
came out half drawn. Classic CAD caps a hatch at HPMAXLINES (1 000 000)
lines and says "Hatch spacing too dense, or dash size too small for
object." instead; the boundaries stay picked, for another scale.
"""
from __future__ import annotations

import pytest

from core import actions


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.resize(1600, 900)
    w.show()
    w.new_document()
    yield w
    w.document.dirty = False
    w.close()


def _type(win, *texts):
    for text in texts:
        win._on_command_submitted(text)


def _history(win) -> str:
    return win.command_line.history.toPlainText()


def _hatches(win):
    return list(win.document.modelspace().query("HATCH"))


def _big_square(win):
    _type(win, "RECTANG", "0,0", "14000,8000", "ZOOM", "E")


def _cli_hatch(win, pattern, scale):
    _type(win, "-HATCH", "P", pattern, scale, "0", "7000,4000", "")


DENSE = "Hatch spacing too dense, or dash size too small for object."


def test_earth_at_one_over_a_large_region_is_refused(win):
    _big_square(win)
    _cli_hatch(win, "EARTH", "1")
    assert _hatches(win) == []
    assert DENSE in _history(win)
    assert "Hatch created." not in _history(win)


def test_the_boundary_stays_picked_for_another_scale(win):
    _big_square(win)
    _cli_hatch(win, "EARTH", "1")
    _type(win, "P", "EARTH", "100", "0", "")
    (hatch,) = _hatches(win)
    assert hatch.dxf.pattern_name == "EARTH"
    assert hatch.dxf.pattern_scale == pytest.approx(100.0)


@pytest.mark.parametrize("scale", ["1", "0.1"])
def test_a_fine_pattern_under_the_cap_is_created(win, scale):
    # ANSI31 at 1 on this region is some 5 000 lines: it reads as solid
    # at this zoom, as it does in classic CAD, and it is created.
    _big_square(win)
    _cli_hatch(win, "ANSI31", scale)
    assert len(_hatches(win)) == 1
    assert DENSE not in _history(win)


def test_the_hatch_dialog_refuses_it_too(win, monkeypatch):
    # The pattern already chosen, as the Palette launches HATCH: the
    # dialog's own exec() cannot be answered offscreen.
    from tools.blocks import HatchTool

    _big_square(win)
    monkeypatch.setattr(HatchTool, "_last", {
        "pattern": "EARTH", "scale": 1.0, "angle": 0.0, "color": 256})
    monkeypatch.setattr(HatchTool, "_skip_dialog", True)
    _type(win, "HATCH", "7000,4000", "")
    assert _hatches(win) == []
    assert DENSE in _history(win)


def test_properties_refuses_a_scale_past_the_cap(win):
    _big_square(win)
    _cli_hatch(win, "ANSI31", "1")
    (hatch,) = _hatches(win)
    from views.properties_panel import _set_hatch_pattern

    panel = win._properties_panel
    panel._active = lambda: [hatch]
    _set_hatch_pattern(panel, "scale", 0.0001)
    assert hatch.dxf.pattern_scale == pytest.approx(1.0)
    assert DENSE in _history(win)
    _set_hatch_pattern(panel, "scale", 2.0)
    assert hatch.dxf.pattern_scale == pytest.approx(2.0)


def test_the_estimate_counts_dashes_and_spacing():
    square = [[(0, 0), (14000, 0), (14000, 8000), (0, 8000)]]
    small = [[(0, 0), (10, 0), (10, 8), (0, 8)]]
    assert actions.hatch_segment_estimate(square, "SOLID") == 0
    assert actions.hatch_segment_estimate(square, "ANSI31", 1) < 10_000
    assert actions.hatch_too_dense(square, "EARTH", 1)
    assert not actions.hatch_too_dense(small, "EARTH", 1)
    assert not actions.hatch_too_dense(square, "EARTH", 100)
    # A user-defined pattern: its spacing alone decides.
    assert actions.hatch_too_dense(square, user_def=(0.0, 0.01, False))
    assert not actions.hatch_too_dense(square, user_def=(0.0, 10.0, True))
