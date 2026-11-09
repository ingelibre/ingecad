# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""HATCH's internal point sees the curves inside block references.

A review video picked a point inside a room drawn as a block and HATCH
answered "No closed boundary found at that point.": the boundary set was
the loose entities of the model only. Classic CAD traces what is shown,
blocks (nested ones too) included.
"""
from __future__ import annotations

import pytest

from core import actions


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.resize(1400, 800)
    w.show()
    w.new_document()
    yield w
    w.document.dirty = False
    w.close()


def _type(win, *texts):
    for text in texts:
        win._on_command_submitted(text)


def _square_block(win, name, size=100.0):
    """A square made into a block, then inserted at the origin."""
    doc = win.document
    _type(win, "RECTANG", "0,0", f"{size},{size}")
    square = list(doc.modelspace().query("LWPOLYLINE"))[-1]
    win.tools._execute(actions.create_block(name, (0, 0), [square]))
    win.tools._execute(actions.insert_block(name, (0, 0)))


def _hatches(win):
    return list(win.document.modelspace().query("HATCH"))


def test_a_point_inside_a_block_finds_its_boundary(win):
    _square_block(win, "ROOM")
    assert not list(win.document.modelspace().query("LWPOLYLINE"))
    _type(win, "ZOOM", "E", "-HATCH", "P", "SOLID", "50,50", "")
    history = win.command_line.history.toPlainText()
    assert "No closed boundary found" not in history
    (hatch,) = _hatches(win)
    xs = [v[0] for path in hatch.paths for v in path.vertices]
    assert min(xs) == pytest.approx(0.0) and max(xs) == pytest.approx(100.0)


def test_a_nested_block_bounds_too(win):
    _square_block(win, "ROOM")
    insert = list(win.document.modelspace().query("INSERT"))[-1]
    win.tools._execute(actions.create_block("FLOOR", (0, 0), [insert]))
    win.tools._execute(actions.insert_block("FLOOR", (500, 0)))
    _type(win, "ZOOM", "E", "-HATCH", "P", "SOLID", "550,50", "")
    (hatch,) = _hatches(win)
    xs = [v[0] for path in hatch.paths for v in path.vertices]
    assert min(xs) == pytest.approx(500.0) and max(xs) == pytest.approx(600.0)
