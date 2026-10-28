# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A drawing opens where its author left it, as in AutoCAD.

Found by the release tour (2026-10-10): a colleague's plan with two blocks
at their true UTM coordinates, far from the drawing, opened as an empty
screen -- IngeCAD zoomed to the extents, AutoCAD shows the saved view.
"""
from __future__ import annotations

import time

import ezdxf
import pytest


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    window = MainWindow()
    window.resize(1200, 800)
    window.show()
    window.new_document()
    qapp.processEvents()
    yield window
    for session in window.document_sessions():
        session.document.dirty = False
    window.close()


def _open(qapp, win, path):
    win.open_path(path)
    t0 = time.monotonic()
    while (win._open_thread is not None or win._regen_worker is not None) \
            and time.monotonic() - t0 < 30:
        qapp.processEvents()
    qapp.processEvents()


def _view(win):
    v = win.viewport.view
    return v.cx, v.cy, v.height / v.scale


def _colleague(tmp_path, center=(2825.5, 1127.8), height=18.0):
    """The plan around (2800, 1100) and a far block at UTM coordinates."""
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    msp.add_lwpolyline([(2800, 1100), (2850, 1100), (2850, 1150), (2800, 1150)],
                       close=True)
    block = doc.blocks.new("NORTE")
    block.add_circle((0, 0), 2)
    msp.add_blockref("NORTE", (727060, 8255110))
    vport = doc.viewports.get("*Active")[0]
    if center is not None:
        vport.dxf.center = center
        vport.dxf.height = height
        vport.dxf.aspect_ratio = 1.5
    path = tmp_path / "colega.dxf"
    doc.saveas(path)
    return path


def test_a_plan_opens_on_its_saved_view_not_its_extents(qapp, win, tmp_path):
    _open(qapp, win, _colleague(tmp_path))
    cx, cy, h = _view(win)
    assert (cx, cy) == pytest.approx((2825.5, 1127.8))
    assert h == pytest.approx(18.0)


def test_without_a_saved_view_it_opens_on_the_extents(qapp, win, tmp_path):
    _open(qapp, win, _colleague(tmp_path, center=None))
    _cx, _cy, h = _view(win)
    assert h > 1e6, "with no saved view, the extents (far block included)"


def test_a_saved_view_far_from_everything_is_not_used(qapp, win, tmp_path):
    _open(qapp, win, _colleague(tmp_path, center=(-9e6, -9e6), height=5))
    cx, cy, _h = _view(win)
    assert cx > 0 and cy > 0


def test_the_view_left_is_saved_and_comes_back(qapp, win, tmp_path):
    _open(qapp, win, _colleague(tmp_path))
    v = win.viewport.view
    v.cx, v.cy, v.scale = 2810.0, 1120.0, v.height / 7.0
    out = tmp_path / "vuelta.dxf"
    win._save_off_the_ui_thread(out, "R2018")     # what Save As runs
    win.document.dirty = False
    _open(qapp, win, out)
    cx, cy, h = _view(win)
    assert (cx, cy) == pytest.approx((2810.0, 1120.0))
    assert h == pytest.approx(7.0)


def test_each_tab_keeps_its_own_view(qapp, win, tmp_path):
    _open(qapp, win, _colleague(tmp_path))
    v = win.viewport.view
    v.cx, v.cy, v.scale = 2840.0, 1140.0, v.height / 3.0
    win.switch_layout("Layout1")
    t0 = time.monotonic()
    while win._regen_worker is not None and time.monotonic() - t0 < 30:
        qapp.processEvents()
    qapp.processEvents()
    assert _view(win)[2] != pytest.approx(3.0)
    win.switch_layout("Model")
    t0 = time.monotonic()
    while win._regen_worker is not None and time.monotonic() - t0 < 30:
        qapp.processEvents()
    qapp.processEvents()
    cx, cy, h = _view(win)
    assert (cx, cy, h) == pytest.approx((2840.0, 1140.0, 3.0)), (
        "coming back to Model zoomed to the extents again")
