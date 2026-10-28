# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""File tabs: several drawings open in one window (#71).

Rafael asked for them in his sixth review ("fundamental"): open several
DWGs at once and move between them, as AutoCAD does. Everything here goes
the user's way: files opened through open_path (File > Open, a double
click), the tab's own button clicked, Ctrl+Tab pressed, the x pressed.
"""
from __future__ import annotations

import time

import ezdxf
import pytest
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest


def _drawing(tmp_path, name, *, circles=1):
    doc = ezdxf.new("R2018")
    for i in range(circles):
        doc.modelspace().add_circle((i * 10, 0), 2)
    path = tmp_path / name
    doc.saveas(path)
    return path


def _settle(qapp, win):
    t0 = time.monotonic()
    while (win._open_thread is not None or win._regen_worker is not None) \
            and time.monotonic() - t0 < 30:
        qapp.processEvents()
    qapp.processEvents()


def _open(qapp, win, path):
    win.open_path(path)
    _settle(qapp, win)


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    window = MainWindow()
    window.show()
    window.new_document()
    qapp.processEvents()
    yield window
    for session in window.document_sessions():
        session.document.dirty = False
    window.close()


def _names(win):
    return [s.document.name for s in win.document_sessions()]


def test_open_adds_a_tab_and_drawing1_gives_its_place(qapp, win, tmp_path):
    _open(qapp, win, _drawing(tmp_path, "uno.dxf"))
    assert _names(win) == ["uno.dxf"], "the untouched Drawing1 stays"
    _open(qapp, win, _drawing(tmp_path, "dos.dxf", circles=2))
    assert _names(win) == ["uno.dxf", "dos.dxf"]
    assert win.document.name == "dos.dxf"
    bar = win._file_tabs
    assert [b.text() for b in bar.buttons] == ["uno.dxf", "dos.dxf"]
    assert [b.isChecked() for b in bar.buttons] == [False, True]
    labels = [a.text() for a in win._window_document_actions]
    assert labels == ["&1 uno.dxf", "&2 dos.dxf"], "the Window menu lists them"
    bar.buttons[0].click()
    assert win.document.name == "uno.dxf"
    assert len(win.document.modelspace().query("CIRCLE")) == 1


def test_each_tab_keeps_its_own_undo(qapp, win, tmp_path):
    _open(qapp, win, _drawing(tmp_path, "uno.dxf"))
    win.dispatcher.submit("LINE")
    win.tools.on_text("0,0")
    win.tools.on_text("5,5")
    win.tools.on_text("")                 # Enter ends LINE
    first = win.document
    assert len(first.modelspace().query("LINE")) == 1
    _open(qapp, win, _drawing(tmp_path, "dos.dxf"))
    win._cmd_undo()                       # nothing to undo in this one
    assert len(first.modelspace().query("LINE")) == 1
    win.step_document(-1)
    assert win.document is first
    win._cmd_undo()
    assert len(first.modelspace().query("LINE")) == 0
    win._cmd_redo()
    assert len(first.modelspace().query("LINE")) == 1


def test_coming_back_keeps_the_view_and_does_not_regen(qapp, win, tmp_path):
    _open(qapp, win, _drawing(tmp_path, "uno.dxf", circles=20))
    view = win.viewport.view
    view.cx, view.cy, view.scale = 33.0, -4.0, 2.5
    scene = win.viewport._scene
    assert scene is not None
    _open(qapp, win, _drawing(tmp_path, "dos.dxf"))
    assert win.viewport._scene is not scene
    # a window shortcut needs the window active: under the CI's Xvfb, with
    # no window manager, it may not be until asked
    win.activateWindow()
    QTest.qWaitForWindowActive(win, 2000)
    QTest.keySequence(win, QKeySequence("Ctrl+Tab"))
    qapp.processEvents()
    assert win.document.name == "uno.dxf", "Ctrl+Tab did not switch"
    assert win._regen_worker is None, "an untouched tab was regenerated"
    assert win.viewport._scene is scene
    assert (view.cx, view.cy, view.scale) == (33.0, -4.0, 2.5)


def test_close_asks_for_a_modified_drawing_and_the_last_leaves_a_new_one(
        qapp, win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    _open(qapp, win, _drawing(tmp_path, "uno.dxf"))
    _open(qapp, win, _drawing(tmp_path, "dos.dxf"))
    asked = []

    def answer(*args, **kwargs):
        asked.append(args[2])
        return QMessageBox.Discard

    monkeypatch.setattr(QMessageBox, "warning", answer)
    win.document.dirty = True
    close_buttons = [w for w in win._file_tabs.findChildren(type(win._file_tabs.plus))
                     if w.objectName() == "file_tab_close"]
    close_buttons[1].click()              # the x of dos.dxf
    assert asked and "dos.dxf" in asked[0]
    assert _names(win) == ["uno.dxf"]
    win.dispatcher.submit("CLOSE")
    assert len(win.document_sessions()) == 1
    assert win.document.path is None, "the window always shows a drawing"


def test_leaving_the_window_asks_for_every_modified_tab(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    _open(qapp, win, _drawing(tmp_path, "uno.dxf"))
    win.document.dirty = True
    _open(qapp, win, _drawing(tmp_path, "dos.dxf"))
    asked = []

    def answer(*args, **kwargs):
        asked.append(args[2])
        return QMessageBox.Discard

    monkeypatch.setattr(QMessageBox, "warning", answer)
    assert win.maybe_save_all()
    assert len(asked) == 1 and "uno.dxf" in asked[0], (
        "the modified drawing in the other tab was not asked about")
    for session in win.document_sessions():
        session.document.dirty = False
    win.close()


def test_two_untitled_tabs_autosave_to_different_files(qapp, win):
    win.document.dirty = True                 # Drawing1 is no longer untouched
    first = win._autosave_paths()
    win.new_document()
    second = win._autosave_paths()
    assert first[0] != second[0]
    assert first[0].name.startswith("Untitled_") and second[0].name.startswith("Untitled_")


def test_opening_a_drawing_already_open_brings_its_tab_back(qapp, win, tmp_path):
    """The release tour opened the same plan twice and got two tabs: two
    sets of edits racing for one file. AutoCAD shows the open one."""
    uno = _drawing(tmp_path, "uno.dxf")
    _open(qapp, win, uno)
    _open(qapp, win, _drawing(tmp_path, "dos.dxf"))
    _open(qapp, win, tmp_path / "." / "uno.dxf")
    assert _names(win) == ["uno.dxf", "dos.dxf"]
    assert win.document.name == "uno.dxf"
    assert "uno.dxf is already open." in win.command_line.history.toPlainText() \
        or "uno.dxf ya está abierto." in win.command_line.history.toPlainText()


@pytest.mark.parametrize("typed", [("MOVE",), ("LINE", "0,0"), ("WBLOCK",)])
def test_a_command_halfway_ends_with_new_and_open(qapp, win, tmp_path, typed,
                                                   monkeypatch):
    """Rafael's sixth review: WBLOCK waiting for its objects survived File >
    New and went on to act on the new drawing. AutoCAD's command belongs
    to the drawing it started in."""
    from PySide6.QtCore import Qt

    monkeypatch.setattr(win.tools, "ask_save_file",
                        lambda *a: str(tmp_path / "bloque.dwg"))

    def type_(text):
        edit = win.command_line.input
        edit.setFocus()
        QTest.keyClicks(edit, text)
        QTest.keyClick(edit, Qt.Key_Return)

    for opening in (lambda: win.new_document(),
                    lambda: _open(qapp, win, _drawing(tmp_path, "uno.dxf"))):
        for text in typed:
            type_(text)
        qapp.processEvents()
        assert win.tools.tool is not None or win.tools._selecting_for
        opening()
        assert win.tools.tool is None and win.tools._selecting_for is None
