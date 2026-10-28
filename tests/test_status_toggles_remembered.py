# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The status-bar toggles come back as the user left them (#103).

Rafael, 2026-10-18: "every time I start the program I have to turn on the
grid, polar tracking, lineweight... by hand; only OSNAP is remembered".
"""
from __future__ import annotations

import pytest

_KEYS = {"grid": "F7", "ortho": "F8", "snap": "F9", "polar": "F10",
         "otrack": "F11", "dyn": "F12"}


@pytest.fixture
def make_window(qapp):
    from views.main_window import MainWindow

    def make():   # conftest closes whatever a test leaves open
        from PySide6.QtTest import QTest

        w = MainWindow()
        w.show()
        # F-keys are window shortcuts: under Xvfb (CI, no window manager)
        # the window turns active late and the first keys went nowhere
        w.activateWindow()
        QTest.qWaitForWindowActive(w, 5000)
        qapp.processEvents()
        return w

    return make


def _press(win, qapp, key: str) -> None:
    from PySide6.QtGui import QKeySequence
    from PySide6.QtTest import QTest

    win.activateWindow()
    win.viewport.setFocus()
    QTest.keySequence(win.viewport, QKeySequence(key))
    qapp.processEvents()


def test_f_keys_are_remembered_by_the_next_window(make_window, qapp):
    first = make_window()
    before = {k: first._mode_state(k) for k in _KEYS}
    for key in _KEYS.values():
        _press(first, qapp, key)
    flipped = {k: first._mode_state(k) for k in _KEYS}
    assert flipped == {k: not v for k, v in before.items()}
    first.close()

    second = make_window()
    assert {k: second._mode_state(k) for k in _KEYS} == flipped
    for key, button in second._mode_buttons.items():
        assert button.isChecked() == second._mode_state(key), key


def test_lineweight_and_a_toggle_turned_back_off_are_remembered(make_window):
    first = make_window()
    lwt = first.viewport.lwt_on
    first._toggle_mode("lwt")               # the LWT button
    first._toggle_mode("polar")
    first._toggle_mode("polar")             # on and off again: stays off
    first.close()

    second = make_window()
    assert second.viewport.lwt_on is (not lwt)
    assert second.tools.polar_on is False


def test_drafting_settings_dialog_is_remembered(make_window, monkeypatch):
    from views import drafting_dialog

    first = make_window()
    assert not first.viewport.grid_on and not first.tools.snap_on

    class Accepting(drafting_dialog.DraftingSettingsDialog):
        def exec(self):
            self.snap_grid.snap_on.setChecked(True)
            self.snap_grid.grid_on.setChecked(True)
            return 1

    monkeypatch.setattr(drafting_dialog, "DraftingSettingsDialog", Accepting)
    first._drafting_settings()
    assert first.viewport.grid_on and first.tools.snap_on
    first.close()

    second = make_window()
    assert second.viewport.grid_on and second.tools.snap_on


def test_osnap_keeps_its_own_bitcode(make_window, qapp):
    from PySide6.QtCore import QSettings

    first = make_window()
    on = first.tools.osnap_on
    _press(first, qapp, "F3")
    assert first.tools.osnap_on is (not on)
    first.close()
    try:
        assert make_window().tools.osnap_on is (not on)
    finally:
        QSettings().remove("osnap/osmode")
