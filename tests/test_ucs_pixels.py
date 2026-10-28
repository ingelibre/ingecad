# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The grid and the axes follow the UCS on screen (#91).

With the UCS turned 30 degrees, the red X axis must run at 30 degrees
through the UCS origin -- measured on the pixels of the frame, since that
is what the user sees. Needs a real GL context (Xvfb in CI, X11 locally).
"""
from __future__ import annotations

import math

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtTest import QTest

AXIS_X = (122, 46, 46)


@pytest.fixture
def win(qapp):
    if QGuiApplication.platformName() in ("offscreen", "minimal"):
        pytest.skip("no OpenGL on this platform: the pixels need a real context")
    from views.main_window import MainWindow

    window = MainWindow()
    window.new_document("m")
    window.resize(1000, 700)
    window.show()
    QTest.qWaitForWindowExposed(window, 5000)
    for _ in range(5):
        qapp.processEvents()
        QTest.qWait(10)
    yield window
    window.document.dirty = False
    window.close()


def _type(win, *texts):
    edit = win.command_line.input
    for text in texts:
        edit.setFocus()
        if text:
            QTest.keyClicks(edit, text)
        QTest.keyClick(edit, Qt.Key_Return)


def _red_axis_angle(viewport) -> float:
    """The direction of the red X axis on screen, degrees, from a line fit.

    Under Xvfb (CI, no window manager) the window can still be settling
    when the first frame is grabbed: grab until the axis is there."""
    for _ in range(50):
        img = viewport.grabFramebuffer().convertToFormat(QImage.Format_RGB888)
        rows = np.frombuffer(img.constBits(), np.uint8).reshape(
            img.height(), img.bytesPerLine())[:, :img.width() * 3]
        pixels = rows.reshape(img.height(), img.width(), 3).astype(int)
        ys, xs = np.nonzero(np.all(np.abs(pixels - AXIS_X) <= 8, axis=2))
        if len(xs) > 200:
            break
        QTest.qWait(40)
    assert len(xs) > 200, "the red axis is on screen"
    slope = np.polyfit(xs, ys, 1)[0]
    return -math.degrees(math.atan(slope))      # screen Y grows downwards


@pytest.mark.skipif(bool(__import__("os").environ.get("CI")),
                    reason="a setting test_settings_gui leaves hides the "
                           "axes for the next window; to fix after 0.6.8.1")
def test_the_axes_turn_with_the_ucs(win):
    viewport = win.viewport
    view = viewport.view
    view.zoom_extents(-50, -50, 50, 50)
    assert abs(_red_axis_angle(viewport)) < 0.5      # the world: level
    _type(win, "UCS", "Z", "30")
    assert _red_axis_angle(viewport) == pytest.approx(30, abs=0.5)
    _type(win, "UCS", "")                            # back to World
    assert abs(_red_axis_angle(viewport)) < 0.5
