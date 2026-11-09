# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""DIMCONTINUE and DIMBASELINE go on from an angular dimension.

The ISO 129 review chained angles around a vertex as classic CAD does
(continued, and baseline from the first line) and IngeCAD answered
"Select a linear or aligned dimension.". The next angle shares the
base's vertex: a continued one starts on its second extension line on
the same arc, a baseline one on its first, DIMDLI farther out.
"""
from __future__ import annotations

import math

import ezdxf
import pytest

from tools.dimension import angular_frame


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.resize(1400, 800)
    w.show()
    w.new_document()
    w.tools.osnap_on = False
    yield w
    w.document.dirty = False
    w.close()


def _type(win, *answers):
    for answer in answers:
        win._on_command_submitted(answer)


def _pick(win, x, y):
    win.tools.on_hover(x, y, threshold_world=0.5)
    win.tools.on_click(x, y)


def _angles(win):
    """Each angular dimension as (degrees, arc radius, style)."""
    out = []
    for dim in win.document.modelspace().query("DIMENSION"):
        vertex, p1, p2, radius = angular_frame(dim)
        a1 = math.atan2(p1[1] - vertex[1], p1[0] - vertex[0])
        a2 = math.atan2(p2[1] - vertex[1], p2[0] - vertex[0])
        out.append((round(math.degrees((a2 - a1) % (2 * math.pi)), 6),
                    round(radius, 6), dim.dxf.dimstyle))
    return out


def _base_angle(win):
    """A 45 degree angle at the origin between two lines, its arc at
    radius 50."""
    _type(win, "LINE", "0,0", "100,0", "", "LINE", "0,0", "100,100", "",
          "ZOOM", "E")
    _type(win, "DIMANGULAR")
    _pick(win, 60, 0)
    _pick(win, 60, 60)
    _pick(win, 50 * math.cos(math.radians(22.5)),
          50 * math.sin(math.radians(22.5)))


def test_a_continued_angle_starts_on_the_second_line(win):
    _base_angle(win)
    _type(win, "DIMCONTINUE", "0,100", "-100,0", "", "")
    history = win.command_line.history.toPlainText()
    assert "Select a linear" not in history
    style = _angles(win)[0][2]
    assert sorted(_angles(win)) == [(45.0, 50.0, style),
                                    (45.0, 50.0, style),
                                    (90.0, 50.0, style)]


def test_a_baseline_angle_starts_on_the_first_line_further_out(win):
    _base_angle(win)
    doc = win.document.doc
    style = _angles(win)[0][2]
    dli = doc.dimstyles.get(style).dxf.dimdli
    _type(win, "DIMBASELINE", "0,100", "-100,0", "", "")
    assert sorted(_angles(win)) == [(45.0, 50.0, style),
                                    (90.0, round(50.0 + dli, 6), style),
                                    (180.0, round(50.0 + 2 * dli, 6), style)]


def test_undo_inside_the_chain_drops_the_last_angle(win):
    _base_angle(win)
    _type(win, "DIMCONTINUE", "0,100", "-100,0", "U", "", "")
    assert sorted(a for a, _r, _s in _angles(win)) == [45.0, 45.0]


def test_a_two_line_angle_read_from_a_file_gives_its_sector():
    doc = ezdxf.new("R2010", setup=True)
    msp = doc.modelspace()
    # Two lines crossing at (10, 10); the arc point in the upper sector.
    dim = msp.add_angular_dim_2l(base=(10, 40), line1=((0, 0), (20, 20)),
                                 line2=((20, 0), (0, 20)),
                                 dimstyle="EZDXF").dimension
    vertex, p1, p2, radius = angular_frame(dim)
    assert vertex == pytest.approx((10, 10))
    assert radius == pytest.approx(30.0)
    a1 = math.degrees(math.atan2(p1[1] - 10, p1[0] - 10)) % 360
    a2 = math.degrees(math.atan2(p2[1] - 10, p2[0] - 10)) % 360
    assert (a1, a2) == (pytest.approx(45.0), pytest.approx(135.0))
