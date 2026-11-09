# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Right-click = Enter with objects selected too (Edit mode).

Options > User Preferences > Right-click Customization offered Enter only
with nothing selected; with objects selected the shortcut menu always
came up. A user who works with Enter on the right button asked for it
there as well: classic CAD's Edit mode, which repeats the last command on
the objects selected.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QSettings


@pytest.fixture
def win(qapp, clean_settings, monkeypatch):
    from views.main_window import MainWindow

    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    qapp.processEvents()
    w.new_document()
    w.menus_shown = []
    # the menu's exec() cannot be answered offscreen: record it instead
    monkeypatch.setattr(w, "show_canvas_context_menu",
                        lambda pos: w.menus_shown.append(pos))
    yield w
    w.tools.cancel()
    w.document.dirty = False
    w.close()


def _right_click(win):
    win.on_canvas_right_click(win.viewport.mapToGlobal(QPoint(200, 200)))


def _erase_then_select_a_circle(win):
    win._on_command_submitted("CIRCLE")
    win._on_command_submitted("0,0")
    win._on_command_submitted("5")
    win._on_command_submitted("LINE")
    win._on_command_submitted("20,0")
    win._on_command_submitted("30,0")
    win._on_command_submitted("")
    win._on_command_submitted("ERASE")
    win._on_command_submitted("L")
    win._on_command_submitted("")          # the last command: ERASE
    (circle,) = win.document.modelspace().query("CIRCLE")
    win.tools.select_entities([circle])


def test_by_default_a_selection_gets_the_menu(win):
    from views.options_dialog import RIGHT_CLICK_ENTER, SETTING_RIGHT_CLICK

    QSettings().setValue(SETTING_RIGHT_CLICK, RIGHT_CLICK_ENTER)
    _erase_then_select_a_circle(win)
    _right_click(win)
    assert len(win.menus_shown) == 1
    assert len(win.document.modelspace().query("CIRCLE")) == 1


def test_edit_mode_enter_repeats_the_last_command_on_the_selection(win):
    from views.options_dialog import (RIGHT_CLICK_ENTER,
                                      SETTING_RIGHT_CLICK_EDIT)

    QSettings().setValue(SETTING_RIGHT_CLICK_EDIT, RIGHT_CLICK_ENTER)
    _erase_then_select_a_circle(win)
    _right_click(win)
    assert win.menus_shown == []
    assert len(win.document.modelspace().query("CIRCLE")) == 0


def test_edit_mode_alone_leaves_the_idle_canvas_its_menu(win):
    from views.options_dialog import (RIGHT_CLICK_ENTER,
                                      SETTING_RIGHT_CLICK_EDIT)

    QSettings().setValue(SETTING_RIGHT_CLICK_EDIT, RIGHT_CLICK_ENTER)
    _right_click(win)
    assert len(win.menus_shown) == 1


def test_the_options_dialog_saves_it(win):
    from views.options_dialog import (RIGHT_CLICK_ENTER, RIGHT_CLICK_MENU,
                                      OptionsDialog, right_click_mode)

    dlg = OptionsDialog(win)
    dlg.right_click_edit.setCurrentIndex(
        dlg.right_click_edit.findData(RIGHT_CLICK_ENTER))
    dlg.apply()
    assert right_click_mode(edit=True) == RIGHT_CLICK_ENTER
    assert right_click_mode() == RIGHT_CLICK_MENU
    dlg.close()
