# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""F11 and F12 as functions (Marco, 2026-09-06): object snap tracking --
pause on a snap point to acquire it, ride the alignment paths from it,
lock on their intersections, released with the point -- and dynamic
input: the prompt and the live coordinates beside the cursor, typed
coordinates relative after a first point, ``#`` for absolute."""
from __future__ import annotations

import pytest
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest

from core import actions
from core.coords import parse_point


def _window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document("m")
    win.show()
    win.activateWindow()
    QTest.qWaitForWindowActive(win, 5000)
    win.viewport.setFocus()
    qapp.processEvents()
    return win


def _close(win) -> None:
    win.document.dirty = False
    win.close()


def _press(qapp, win, keys: str) -> None:
    QTest.keySequence(win, QKeySequence(keys))
    qapp.processEvents()


def test_f11_and_f12_are_status_bar_modes_in_autocads_order(qapp):
    win = _window(qapp)
    try:
        assert list(win._mode_buttons) == ["snap", "grid", "ortho", "polar", "osnap", "otrack", "dyn", "lwt"]
        assert win._mode_buttons["otrack"].text() == "OTRACK" and win._mode_buttons["dyn"].text() == "DYN"
        for key, attr in (("F11", "otrack_on"), ("F12", "dyn_on")):
            assert getattr(win.tools, attr) is False
            _press(qapp, win, key)
            assert getattr(win.tools, attr) is True and win._mode_buttons[attr[:-3]].isChecked()
            _press(qapp, win, key)
            assert getattr(win.tools, attr) is False
    finally:
        _close(win)


def _tracking_scene(win):
    t = win.tools
    t._execute(actions.add_line((0, 0), (100, 0)))
    t._execute(actions.add_line((50, 50), (50, 150)))
    t.osnap_on = True
    t.osnap_modes = {"END"}
    t.otrack_on = True
    win.dispatcher.submit("LINE")
    return t


def test_a_paused_snap_point_is_acquired_and_the_cursor_rides_its_paths(qapp):
    win = _window(qapp)
    try:
        t = _tracking_scene(win)
        t.on_hover(100.5, 0.3, threshold_world=3.0)
        assert t.snap_hit is not None and (t.snap_hit.x, t.snap_hit.y) == (100.0, 0.0)
        assert t.track_points() == []                      # not yet: the dwell has not elapsed
        assert t._track_timer.isActive()
        t.acquire_now()                                     # the dwell timer's slot
        assert [(x, y, k) for x, y, k in t.track_points()] == [(100.0, 0.0, "END")]
        # away from the point, near its vertical path: locked onto the path
        t.on_hover(100.4, 37.0, threshold_world=3.0)
        assert t.snap_hit is None
        assert t.resolved_point(100.4, 37.0) == pytest.approx((100.0, 37.0))
        assert t.track_hint is not None
        (sx, sy), (px, py), label = t.track_hint
        assert (sx, sy) == (100.0, 0.0) and (px, py) == pytest.approx((100.0, 37.0))
        assert label == "Endpoint: <90°"
        # near its horizontal path
        assert t.resolved_point(-40.0, 0.8) == pytest.approx((-40.0, 0.0))
        assert t.track_hint[2] == "Endpoint: <0°"
        # off every path: the cursor is free again and there is no hint
        assert t.resolved_point(60.0, 30.0) == (60.0, 30.0) and t.track_hint is None
        # the dwell timer is what waits: its interval is AutoCAD-short
        assert 100 <= t.TRACK_DWELL_MS <= 1000
    finally:
        _close(win)


def test_two_acquired_points_lock_their_intersection_and_a_point_releases_them(qapp):
    win = _window(qapp)
    try:
        t = _tracking_scene(win)
        t.on_hover(100.5, 0.3, threshold_world=3.0)
        t.acquire_now()
        t.on_hover(50.2, 150.1, threshold_world=3.0)
        t.acquire_now()
        assert len(t.track_points()) == 2
        # where the vertical from (100, 0) meets the horizontal from (50, 150)
        t.on_hover(100.3, 149.6, threshold_world=3.0)
        assert t.resolved_point(100.3, 149.6) == pytest.approx((100.0, 150.0))
        assert t.track_hint[2] == "Endpoint: <90°, Endpoint: <0°"
        # pausing on an acquired point again lets it go
        t.on_hover(50.2, 150.1, threshold_world=3.0)
        t.acquire_now()
        assert [(x, y) for x, y, _k in t.track_points()] == [(100.0, 0.0)]
        # a click uses the tracked point and releases what was acquired
        t.on_hover(100.4, 37.0, threshold_world=3.0)
        t.on_click(100.4, 37.0)
        assert t.tool.last_point == pytest.approx((100.0, 37.0))
        assert t.track_points() == [] and t.track_hint is None
        # ending the command clears too; turning the mode off as well
        t.on_hover(100.5, 0.3, threshold_world=3.0)
        t.acquire_now()
        assert len(t.track_points()) == 1
        win._toggle_mode("otrack")
        assert t.otrack_on is False and t.track_points() == []
        t.cancel()
        win.dispatcher.cancel()
    finally:
        _close(win)


def test_the_last_point_joins_the_paths_while_polar_or_ortho_is_on(qapp):
    win = _window(qapp)
    try:
        t = _tracking_scene(win)
        t.on_hover(100.5, 0.3, threshold_world=3.0)
        t.acquire_now()
        t.tool.on_point((20.0, 80.0))                    # the line's first point
        t.ortho_on = True
        # the vertical from the acquired (100, 0) meets the horizontal from the last point (20, 80)
        t.on_hover(99.7, 80.4, threshold_world=3.0)
        assert t.resolved_point(99.7, 80.4) == pytest.approx((100.0, 80.0))
        assert "Polar" in t.track_hint[2] and "Endpoint" in t.track_hint[2]
        t.cancel()
        win.dispatcher.cancel()
    finally:
        _close(win)


def test_dynamic_input_shows_prompt_and_live_input_and_reads_relative(qapp):
    win = _window(qapp)
    try:
        t = win.tools
        assert t.dyn_lines() == []                        # off: nothing beside the cursor
        t.dyn_on = True
        t._cursor = (30.0, 40.0)
        assert t.dyn_lines() == ["30.000, 40.000"]        # idle: pointer input, absolute
        win.dispatcher.submit("LINE")
        assert t.dyn_lines() == ["Specify first point", "30.000, 40.000"]
        t.tool.on_point((0.0, 0.0))
        assert t.dyn_lines()[0].startswith("Specify next point")
        assert t.dyn_lines()[1].startswith("50.000 < 53.1")     # distance < angle from the last point
        win.command_line.input.setText("10,5")
        assert t.dyn_lines()[1] == "10,5"                 # what is being typed, echoed
        win.command_line.input.clear()
        # typed coordinates: relative after a first point, # for absolute, @ still relative
        t.on_text("10,5")
        assert t.tool.last_point == pytest.approx((10.0, 5.0))
        t.on_text("10,5")
        assert t.tool.last_point == pytest.approx((20.0, 10.0))
        t.on_text("#7,7")
        assert t.tool.last_point == pytest.approx((7.0, 7.0))
        t.on_text("@1<0")
        assert t.tool.last_point == pytest.approx((8.0, 7.0))
        t.dyn_on = False
        t.on_text("10,5")
        assert t.tool.last_point == pytest.approx((10.0, 5.0))  # off: absolute, as always
        t.cancel()
        win.dispatcher.cancel()
        assert t.current_prompt == ""
    finally:
        _close(win)


def test_parse_point_knows_the_hash_prefix_and_the_relative_default():
    assert parse_point("#10,5", (100.0, 100.0), relative_default=True) == parse_point("10,5")
    assert parse_point("10,5", (100.0, 100.0), relative_default=True).x == 110.0
    assert parse_point("10<90", (100.0, 100.0), relative_default=True).y == pytest.approx(110.0)
    assert parse_point("10,5", None, relative_default=True).x == 10.0       # no first point: absolute
    assert parse_point("10,5", (100.0, 100.0)).x == 10.0                    # off: absolute
    assert parse_point("@10,5", (100.0, 100.0)).x == 110.0
