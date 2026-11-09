# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The coordinate readout adds the relative position while a command
measures from a point (#118): "see the radius when drawing a circle ...
and, next to the absolute coordinates, the relative ones from the last
point clicked. Not just for circles, for any element"."""
from __future__ import annotations

import pytest


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.maybe_save_changes = lambda: True
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


def _readout(win, x, y) -> str:
    win.viewport.cursorMoved.emit(float(x), float(y))
    return win._coords_label.text()


def test_idle_it_is_the_absolute_pair_alone(win):
    assert _readout(win, 3, 4) == "3.000, 4.000"


def test_a_circle_being_dragged_reads_its_radius(win):
    _type(win, "CIRCLE", "10,10")
    assert _readout(win, 13, 14) == "13.000, 14.000   @5.000<53.13"
    _type(win, "5")
    assert _readout(win, 13, 14) == "13.000, 14.000"


def test_a_line_reads_from_its_last_point(win):
    _type(win, "LINE", "0,0")
    assert _readout(win, 0, 7).endswith("@7.000<90.00")
    _type(win, "0,7")
    assert _readout(win, 10, 7).endswith("@10.000<0.00")
    _type(win, "")


def test_before_the_first_point_there_is_nothing_to_measure_from(win):
    _type(win, "LINE")
    assert "@" not in _readout(win, 3, 4)
    win.tools.cancel()
