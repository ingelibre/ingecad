# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""An arc length dimension's extension lines: orthogonal under 90 degrees.

The ISO 129 review noted that a short arc's length dimension came out
with radial extension lines. Classic CAD draws them parallel to the arc's
bisector while the arc spans less than 90 degrees, and radial from 90 up;
the dimension line ends where they meet it.
"""
from __future__ import annotations

import math

import pytest

from core import actions


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


def _dimarc(win, sweep):
    """DIMARC on an arc of radius 10 centred on the Y axis, the
    dimension line 5 units out."""
    half = math.radians(sweep / 2.0)
    start = (10 * math.sin(half), 10 * math.cos(half))
    end = (-start[0], start[1])
    tools = win.tools
    tools._execute(actions.add_arc_3p(start, (0, 10), end))
    win._on_command_submitted("ZOOM")
    win._on_command_submitted("E")
    win._on_command_submitted("DIMARC")
    tools.on_hover(0, 10, threshold_world=0.5)
    tools.on_click(0, 10)
    tools.on_hover(0, 15, threshold_world=0.5)
    tools.on_click(0, 15)
    (dim,) = win.document.modelspace().query("ARC_DIMENSION")
    block = list(win.document.doc.blocks.get(dim.dxf.geometry))
    lines = [e for e in block if e.dxftype() == "LINE"]
    (dimline,) = [e for e in block if e.dxftype() == "ARC"
                  and e.dxf.radius > 10]
    return lines, dimline


def _direction(line):
    d = line.dxf.end - line.dxf.start
    return math.degrees(math.atan2(d.y, d.x)) % 180.0


def test_a_short_arc_has_orthogonal_extension_lines(win):
    lines, dimline = _dimarc(win, 60)
    assert len(lines) == 2
    for line in lines:
        assert _direction(line) == pytest.approx(90.0, abs=1e-6)
        assert abs(line.dxf.start.x) == pytest.approx(5.0, abs=1e-6)
    # They cross the dimension line at x = +-5 on radius 15, and the
    # dimension line (shortened by its arrows) ends there.
    for line in lines:
        assert line.dxf.end.y > math.sqrt(15.0 ** 2 - 5.0 ** 2)
    reach = math.degrees(math.asin(5.0 / 15.0))
    assert 90.0 - reach <= dimline.dxf.start_angle < 90.0 - reach + 2.0
    assert 90.0 + reach - 2.0 < dimline.dxf.end_angle <= 90.0 + reach


def test_a_wide_arc_keeps_radial_extension_lines(win):
    lines, dimline = _dimarc(win, 120)
    assert sorted(round(_direction(line), 6) for line in lines) == [30.0,
                                                                     150.0]
    assert 30.0 <= dimline.dxf.start_angle < 32.0
    assert 148.0 < dimline.dxf.end_angle <= 150.0
