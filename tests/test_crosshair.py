# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Customising the cursor, under AutoCAD's own names.

Marco: "sería bueno poder personalizar el crosshair, algo así como lo hace
AutoCAD". AutoCAD spreads it over two tabs and two system variables:
CURSORSIZE (p. 2202) on Display, PICKBOX (p. 2452) on Selection, and the
crosshair colour through the Colors dialog. All three are here.

The one that is more than a preference is PICKBOX: it drives the box you SEE
and the aperture that actually picks. Those used to be two constants that
happened to read 8 -- and since one was a full width and the other a
half-size, the box on screen was half the size of what it caught.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor

from views import viewport as vp


@pytest.fixture
def prefs():
    settings = QSettings()
    keys = (vp.SETTING_CURSORSIZE, vp.SETTING_PICKBOX,
            vp.SETTING_CROSSHAIR_COLOR)
    saved = {k: settings.value(k, None) for k in keys}
    yield settings
    for k, v in saved.items():
        settings.remove(k) if v is None else settings.setValue(k, v)


# -- CURSORSIZE (p. 2202) ------------------------------------------------------
def test_the_crosshair_is_full_screen_by_default(prefs):
    """AutoCAD ships 5, IngeCAD ships 100 -- changing the default would
    shrink every existing user's cursor without being asked."""
    prefs.remove(vp.SETTING_CURSORSIZE)
    assert vp.cursorsize() == 100


@pytest.mark.parametrize("value", [1, 5, 30, 99, 100])
def test_a_valid_cursorsize_is_kept(prefs, value):
    prefs.setValue(vp.SETTING_CURSORSIZE, value)
    assert vp.cursorsize() == value


@pytest.mark.parametrize("bad", [0, -1, 101, "abc", "", None])
def test_a_nonsense_cursorsize_falls_back(prefs, bad):
    prefs.setValue(vp.SETTING_CURSORSIZE, bad)
    assert vp.cursorsize() == 100


# -- the colour ----------------------------------------------------------------
def test_no_colour_means_follow_the_background(prefs):
    prefs.remove(vp.SETTING_CROSSHAIR_COLOR)
    assert vp.crosshair_color() is None


def test_a_chosen_colour_comes_back(prefs):
    prefs.setValue(vp.SETTING_CROSSHAIR_COLOR, "#3ad64a")
    assert vp.crosshair_color() == QColor("#3ad64a")


def test_an_unreadable_colour_falls_back_to_automatic(prefs):
    prefs.setValue(vp.SETTING_CROSSHAIR_COLOR, "no-es-un-color")
    assert vp.crosshair_color() is None


# -- PICKBOX drives BOTH the box and the aperture ------------------------------
def test_the_pickbox_sets_what_you_see_and_what_it_catches(qapp, prefs):
    """The property worth a test: doubling the box doubles the aperture.

    Otherwise the square is decoration -- a user who shrinks it would still
    pick at the old distance, which is exactly the state this replaced.
    """
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        win.new_document("mm")
        win.viewport.refresh_cursor_prefs()
        win.tools.on_hover(0.0, 0.0, 1.0)
        base = win.tools._pick_tolerance
        assert base > 0

        prefs.setValue(vp.SETTING_PICKBOX, vp.PICKBOX_PX * 2)
        win.viewport.refresh_cursor_prefs()
        assert win.viewport._pickbox_px == vp.PICKBOX_PX * 2
        win.tools.on_hover(0.0, 0.0, 1.0)
        assert win.tools._pick_tolerance == pytest.approx(base * 2)
    finally:
        win.close()


def test_the_default_pickbox_changes_nothing(qapp, prefs):
    """A new setting must not move behaviour on its default value."""
    from views.main_window import MainWindow
    from views.tool_controller import PICK_PX, SNAP_PX

    prefs.remove(vp.SETTING_PICKBOX)
    win = MainWindow()
    try:
        win.new_document("mm")
        win.viewport.refresh_cursor_prefs()
        win.tools.on_hover(0.0, 0.0, 1.0)
        assert win.tools._pick_tolerance == pytest.approx(PICK_PX / SNAP_PX)
    finally:
        win.close()


# -- the commands --------------------------------------------------------------
@pytest.mark.parametrize("command,key,ok,bad", [
    ("_cmd_cursorsize", vp.SETTING_CURSORSIZE, "30", "0"),
    ("_cmd_pickbox", vp.SETTING_PICKBOX, "20", "99"),
])
def test_the_system_variables_are_typable(qapp, prefs, command, key, ok, bad):
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        win.new_document("mm")
        getattr(win, command)(ok)
        assert str(QSettings().value(key)) == ok
        getattr(win, command)(bad)          # out of range: refused
        assert str(QSettings().value(key)) == ok
        getattr(win, command)("nonsense")   # not a number: refused
        assert str(QSettings().value(key)) == ok
        getattr(win, command)()             # bare: reports, changes nothing
        assert str(QSettings().value(key)) == ok
    finally:
        win.close()
