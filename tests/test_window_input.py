# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The main window's keyboard and mouse hooks, without an app-wide filter.

They used to live in one event filter installed on the whole application,
so every event of the app -- paints, timers, widgets being deleted -- went
through Python, and while a worker thread held the GIL each one waited its
turn: Save as DWG froze the window 1.05 s for it on Plaza Yanque, 0.29 s
without (release bench, 0.6.6). The hooks now watch only the native window,
the canvas and the layout tabs. Every input here is sent as the system
sends it: to the native window, which hands it to the widget under it.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtTest import QTest


@pytest.fixture
def window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document("m")
    win.resize(1000, 700)
    win.show()
    win.activateWindow()
    QTest.qWaitForWindowActive(win, 5000)
    win.viewport.setFocus()
    yield win
    win.document.dirty = False
    win.close()


def test_no_app_wide_event_filter(qapp, monkeypatch):
    """An event for some other widget never runs MainWindow.eventFilter."""
    from PySide6.QtWidgets import QApplication
    from views.main_window import MainWindow

    seen = []
    real = MainWindow.eventFilter

    def spy(self, obj, event):
        seen.append(event.type())
        return real(self, obj, event)

    # before the window exists: Shiboken looks the override up once
    monkeypatch.setattr(MainWindow, "eventFilter", spy)
    win = MainWindow()
    win.new_document("m")
    win.show()
    try:
        QApplication.sendEvent(win.command_line, QEvent(QEvent.User))
        assert QEvent.User not in seen
    finally:
        win.document.dirty = False
        win.close()


def _type(handle, text):
    # QTest.keyClicks takes widgets only; one key at a time takes a QWindow
    for ch in text:
        QTest.keyClick(handle, getattr(Qt, f"Key_{ch.upper()}"))


def test_text_typed_in_place_goes_to_the_text(qapp, window):
    for answer in ("TEXT", "0,0", "2.5", "0"):
        window._on_command_submitted(answer)
    assert window.tools.text_capturing()
    handle = window.windowHandle()
    _type(handle, "hola")
    QTest.keyClick(handle, Qt.Key_Escape)
    texts = [e.dxf.text for e in window.document.modelspace() if e.dxftype() == "TEXT"]
    assert texts == ["hola"]
    assert window.command_line.input.text() == ""


def test_typing_over_the_canvas_lands_in_the_command_line(qapp, window):
    _type(window.windowHandle(), "circle")
    assert window.command_line.input.text().upper() == "CIRCLE"


def test_a_press_on_the_border_resizes_the_frameless_window(qapp, window, monkeypatch):
    if window.isMaximized():
        window.showNormal()
    handle = window.windowHandle()
    edges = []
    monkeypatch.setattr(handle, "startSystemResize",
                        lambda e: edges.append(e) or True, raising=False)
    QTest.mousePress(handle, Qt.LeftButton, Qt.NoModifier,
                     QPoint(2, window.height() // 2))
    QTest.mouseRelease(handle, Qt.LeftButton, Qt.NoModifier,
                       QPoint(2, window.height() // 2))
    assert edges == [Qt.LeftEdge]


def test_double_click_on_a_layout_tab_renames_it(qapp, window, monkeypatch):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    renamed = []
    monkeypatch.setattr(window, "_rename_layout_tab", renamed.append)
    layout = next(n for n in window._tab_buttons.values() if n != "Model")
    # As a hand does it, the first click activates the tab and rebuilds the
    # tabs; the double-click then lands on the rebuilt button. Sent to the
    # button itself: the CI's Xvfb has no window manager, and where a
    # frameless window's tabs end up there is not this test's question.
    window.switch_layout(layout)
    QTest.qWait(50)
    button = next(b for b, n in window._tab_buttons.items() if n == layout)
    centre = QPointF(button.rect().center())
    QApplication.sendEvent(button, QMouseEvent(
        QEvent.MouseButtonDblClick, centre, QPointF(button.mapToGlobal(centre.toPoint())),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    assert renamed == [layout]
