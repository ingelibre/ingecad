# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Model/layout tabs in a narrow window, as AutoCAD shows them.

Found by the release tour (2026-10-10): with five tabs and a window 1000 px
wide the status bar gave the row 134 px and the tabs piled on top of each
other, unreadable. Now the ones that do not fit wait behind "…", and Model
and the active layout are always on the row.
"""
from __future__ import annotations

import time

import ezdxf
import pytest

NAMES = ("Planta general", "Cortes A-A", "Detalles")


@pytest.fixture
def win(qapp, tmp_path):
    from views.main_window import MainWindow

    doc = ezdxf.new("R2018")
    for name in NAMES:
        doc.layouts.new(name)
    path = tmp_path / "laminas.dxf"
    doc.saveas(path)
    window = MainWindow()
    window.resize(1000, 700)
    window.show()
    window.open_path(path)
    _settle(qapp, window)
    yield window
    window.document.dirty = False
    window.close()


def _settle(qapp, win):
    t0 = time.monotonic()
    while (win._open_thread is not None or win._regen_worker is not None) \
            and time.monotonic() - t0 < 30:
        qapp.processEvents()
    for _ in range(5):
        qapp.processEvents()


def _shown(win):
    return [(b, n) for b, n in win._tab_buttons.items() if b.isVisible()]


def _no_overlap(win):
    spans = sorted((b.x(), b.x() + b.width()) for b, _ in _shown(win))
    return all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))


def test_tabs_that_do_not_fit_wait_behind_the_overflow(qapp, win):
    shown = [n for _, n in _shown(win)]
    assert "Model" in shown
    assert len(shown) < 5 and win._layout_more.isVisible()
    assert _no_overlap(win), "tabs drawn on top of each other"
    for b, _ in _shown(win):
        assert b.width() >= b.sizeHint().width(), "a tab cut short"


def test_the_active_layout_is_always_on_the_row(qapp, win):
    win.switch_layout("Detalles")
    _settle(qapp, win)
    assert "Detalles" in [n for _, n in _shown(win)]
    assert _no_overlap(win)


def test_a_wider_window_brings_every_tab_back(qapp, win):
    win.resize(2200, 700)
    for _ in range(10):
        qapp.processEvents()
    assert len(_shown(win)) == 5
    assert not win._layout_more.isVisible()
    assert _no_overlap(win)
