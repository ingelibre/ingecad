# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""AutoCAD's keyboard, pressed for real (Marco, 2026-09-06: "igual a
AutoCAD"): the function keys and Ctrl keys of the Command Reference's
shortcut table that IngeCAD answers, each one delivered as a key press,
not as a method call -- a shortcut that is registered but never reaches
the window is exactly the bug this file exists to catch."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest

from core import actions


def _window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document("m")
    win.show()
    # Xvfb has no window manager: nobody activates the window for us, and a
    # keystroke sent to an inactive window goes nowhere (test_smoke says so)
    win.activateWindow()
    QTest.qWaitForWindowActive(win, 5000)
    win.viewport.setFocus()
    qapp.processEvents()
    return win


def _press(qapp, win, keys: str) -> None:
    QTest.keySequence(win, QKeySequence(keys))
    qapp.processEvents()


def _close(win) -> None:
    win.document.dirty = False
    win.close()


def test_the_status_bar_modes_answer_their_function_keys_and_ctrl_keys(qapp):
    win = _window(qapp)
    try:
        tools = win.tools
        for fkey, ctrl, attr, is_viewport in (("F9", "Ctrl+B", "snap", False), ("F7", "Ctrl+G", "grid", True),
                                              ("F8", "Ctrl+L", "ortho", False), ("F10", "Ctrl+U", "polar", False),
                                              ("F3", "Ctrl+F", "osnap", False)):
            owner = win.viewport if is_viewport else tools
            before = getattr(owner, f"{attr}_on")
            _press(qapp, win, fkey)
            assert getattr(owner, f"{attr}_on") is (not before), fkey
            assert win._mode_buttons[attr].isChecked() is (not before)
            _press(qapp, win, ctrl)
            assert getattr(owner, f"{attr}_on") is before, ctrl
        assert list(win._mode_buttons)[0] == "snap"              # AutoCAD's status bar order
        assert win._mode_buttons["snap"].text() == "SNAP"
    finally:
        _close(win)


def test_snap_mode_makes_the_cursor_jump_by_the_grid_on_screen(qapp):
    win = _window(qapp)
    try:
        tools = win.tools
        step = tools.snap_spacing()
        assert step and step > 0 and step == win.viewport._grid_spacing()
        assert tools.resolved_point(step * 2.3, step * 0.4) == pytest.approx((step * 2.3, step * 0.4))
        tools.snap_on = True
        assert tools.resolved_point(step * 2.3, step * 0.4) == pytest.approx((step * 2, 0.0))
        assert tools.resolved_point(-step * 1.6, step * 3.5001) == pytest.approx((-step * 2, step * 4))
        # object snap still wins over the grid
        tools.snap_hit = type("Hit", (), {"x": 1.234, "y": 5.678})()
        assert tools.resolved_point(step * 2.3, step * 0.4) == (1.234, 5.678)
        tools.snap_hit = None
    finally:
        _close(win)


def test_shift_held_flips_ortho_for_the_moment(qapp):
    win = _window(qapp)
    try:
        tools = win.tools
        win.dispatcher.submit("LINE")
        tools.tool.on_point((0.0, 0.0))
        assert tools.ortho_on is False and tools.shift_held is False
        assert tools.resolved_point(10.0, 3.0) == (10.0, 3.0)
        QTest.keyPress(win.viewport, Qt.Key_Shift, Qt.ShiftModifier)
        assert tools.shift_held is True
        assert tools.resolved_point(10.0, 3.0) == (10.0, 0.0)              # ortho, while held
        QTest.keyRelease(win.viewport, Qt.Key_Shift, Qt.NoModifier)
        assert tools.shift_held is False
        assert tools.resolved_point(10.0, 3.0) == (10.0, 3.0)
        tools.ortho_on = True
        tools.shift_held = True
        assert tools.resolved_point(10.0, 3.0) == (10.0, 3.0)              # ortho on + Shift = free
        tools.shift_held = False
        assert tools.resolved_point(10.0, 3.0) == (10.0, 0.0)
        tools.cancel()
        win.dispatcher.cancel()
    finally:
        _close(win)


def test_ctrl_a_selects_everything_selectable_and_ctrl_w_stops_cycling(qapp):
    win = _window(qapp)
    try:
        msp = win.document.modelspace()
        win.tools._execute(actions.add_line((0, 0), (10, 0)))
        win.tools._execute(actions.add_line((0, 5), (10, 5)))
        win.document.doc.layers.add("BLOQUEADA").lock()
        frozen = win.tools._execute(actions.add_circle((3, 3), 1))
        circle = [e for e in msp if e.dxftype() == "CIRCLE"][0]
        circle.dxf.layer = "BLOQUEADA"
        win._cmd_select_all()
        assert len(win.tools.selection) == 2                              # the locked layer stays out
        win.tools.clear_selection()
        win.viewport.setFocus()
        qapp.processEvents()
        QTest.keySequence(win.viewport, QKeySequence("Ctrl+A"))           # the canvas action, by key
        qapp.processEvents()
        assert len(win.tools.selection) == 2
        assert win.tools.cycling_on is True
        _press(qapp, win, "Ctrl+W")
        assert win.tools.cycling_on is False
        _press(qapp, win, "Ctrl+W")
        assert win.tools.cycling_on is True
    finally:
        _close(win)


def test_ctrl_j_repeats_the_last_command_and_ctrl_bracket_cancels(qapp):
    win = _window(qapp)
    try:
        win.dispatcher.submit("LINE")
        assert win.tools.tool is not None and win.tools.tool.name == "LINE"
        _press(qapp, win, "Ctrl+[")
        assert win.tools.tool is None
        _press(qapp, win, "Ctrl+J")
        assert win.tools.tool is not None and win.tools.tool.name == "LINE"
        _press(qapp, win, "Ctrl+\\")
        assert win.tools.tool is None
        _press(qapp, win, "Ctrl+M")
        assert win.tools.tool is not None and win.tools.tool.name == "LINE"
        _press(qapp, win, "Ctrl+[")
    finally:
        _close(win)


def test_ctrl_9_ctrl_i_ctrl_1_and_the_layout_keys(qapp):
    win = _window(qapp)
    try:
        assert win._command_dock.isVisible() or not win.isVisible()
        shown = win._command_dock.isVisibleTo(win)
        _press(qapp, win, "Ctrl+9")
        assert win._command_dock.isVisibleTo(win) is (not shown)
        _press(qapp, win, "Ctrl+9")
        assert win._command_dock.isVisibleTo(win) is shown
        assert win._coords_label.isVisibleTo(win)
        _press(qapp, win, "Ctrl+I")
        assert not win._coords_label.isVisibleTo(win)
        _press(qapp, win, "Ctrl+I")
        assert win._coords_label.isVisibleTo(win)
        _press(qapp, win, "Ctrl+1")
        assert win._sidebar_tabs.currentWidget() is win._properties_panel
        names = list(win._layout_names())
        assert names[0] == "Model" and len(names) >= 2
        _press(qapp, win, "Ctrl+PgDown")
        assert win._active_layout == names[1]
        _press(qapp, win, "Ctrl+PgUp")
        assert win._active_layout == "Model"
        _press(qapp, win, "Ctrl+PgUp")                                    # wraps around
        assert win._active_layout == names[-1]
        win.switch_layout("Model")
    finally:
        _close(win)


def test_f1_opens_the_help_site_and_ctrl_f_no_longer_finds(qapp, monkeypatch):
    from PySide6.QtGui import QDesktopServices

    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toString()) or True))
    win = _window(qapp)
    try:
        _press(qapp, win, "F1")
        assert opened == ["https://ingecad.org"]
        win.dispatcher.submit("HELP")
        assert len(opened) == 2
        # Ctrl+F is object snap in AutoCAD: the Find entry keeps no key
        bar_actions = win._menu_bar.actions()
        edit = next(a for a in bar_actions if a.text() == "Edit").menu()
        find = next(a for a in edit.actions() if a.text() == "Find...")
        assert find.shortcut().isEmpty()
    finally:
        _close(win)


def test_copy_with_base_point_and_paste_as_block(qapp):
    win = _window(qapp)
    try:
        msp = win.document.modelspace()
        win.tools._execute(actions.add_line((0, 0), (10, 0)))
        win.tools._execute(actions.add_line((0, 0), (0, 10)))
        win.tools.select_all()
        win.dispatcher.submit("COPYBASE")
        win.tools.on_text("5,5")
        assert win.tools._clipboard[1] == (5.0, 5.0)
        win.dispatcher.submit("PASTEBLOCK")
        win.tools.on_text("105,205")
        inserts = [e for e in msp if e.dxftype() == "INSERT"]
        assert len(inserts) == 1 and inserts[0].dxf.name.startswith("A$C")
        assert (inserts[0].dxf.insert.x, inserts[0].dxf.insert.y) == (105.0, 205.0)
        assert [e.dxftype() for e in msp].count("LINE") == 2               # the pasted pair lives in the block
        block = win.document.doc.blocks.get(inserts[0].dxf.name)
        assert len(list(block)) == 2
        win.dispatcher.submit("U")
        assert not [e for e in msp if e.dxftype() == "INSERT"]
        assert [e.dxftype() for e in msp].count("LINE") == 2
        # the Edit menu carries the three AutoCAD entries with their keys
        bar_actions = win._menu_bar.actions()
        edit = next(a for a in bar_actions if a.text() == "Edit").menu()
        keys = {a.text(): a.shortcut().toString() for a in edit.actions() if a.text()}
        assert keys["Copy with Base Point"] == "Ctrl+Shift+C"
        assert keys["Paste as Block"] == "Ctrl+Shift+V"
        assert keys["Select All"] == "Ctrl+A"
    finally:
        _close(win)


def test_canvas_shortcuts_stay_unique_across_menu_rebuilds(qapp):
    """Turning a plugin on or off rebuilds the menus; the clipboard actions
    on the canvas must not pile up, or Qt calls the key ambiguous and
    fires none of them -- measured: three copies of Ctrl+C with two plugins
    on, and Ctrl+C on the canvas copying nothing."""
    from PySide6.QtGui import QAction

    win = _window(qapp)
    try:
        win.tools._execute(actions.add_line((0, 0), (10, 0)))
        for pid in [p for p, loaded in win.plugins.loaded.items() if loaded.bundled]:
            win.plugins.deactivate(pid)
            win.plugins.activate(pid)
        for seq in ("Ctrl+C", "Ctrl+X", "Ctrl+V", "Ctrl+A", "Ctrl+Shift+C", "Ctrl+Shift+V"):
            bound = [a for a in win.viewport.actions() if a.shortcut().toString() == seq]
            assert len(bound) == 1, (seq, len(bound))
        win.tools.select_all()
        win.viewport.setFocus()
        qapp.processEvents()
        QTest.keySequence(win.viewport, QKeySequence("Ctrl+C"))
        qapp.processEvents()
        assert win.tools._clipboard is not None and len(win.tools._clipboard[0]) == 1
    finally:
        _close(win)
