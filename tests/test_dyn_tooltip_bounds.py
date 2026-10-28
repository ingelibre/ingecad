# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The dynamic-input tooltip stays inside the canvas.

Rafael's seventh review (13:09, 28:56): with DIMLINEAR's long prompt on a
narrow canvas -- the sidebar open and a reference image beside the window
-- the tooltip flipped to the left of the cursor and started at a negative
x, so its beginning and the live distance were off the canvas.
"""
from __future__ import annotations

import pytest

from views.viewport import dyn_tooltip_origin


@pytest.mark.parametrize("cursor_x", [10, 300, 590])
def test_a_wide_tooltip_never_leaves_the_canvas(cursor_x):
    x, y = dyn_tooltip_origin(cursor_x, 200, 520, 40, 600, 400)
    assert x >= 0 and x + 520 <= 600, x


def test_room_on_the_right_keeps_it_below_right_of_the_cursor():
    assert dyn_tooltip_origin(100, 100, 200, 40, 800, 600) == (118, 118)


def test_near_the_bottom_right_it_flips_up_and_left():
    x, y = dyn_tooltip_origin(780, 590, 200, 40, 800, 600)
    assert (x, y) == (780 - 18 - 200, 590 - 18 - 40)
