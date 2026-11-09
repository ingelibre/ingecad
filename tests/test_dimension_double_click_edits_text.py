# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A double-click on a dimension opens its text in the in-place editor.

It did nothing (a tester's eighth review, carried over from 0.7): the
classic double-click action of a dimension is the text editor. The editor
shows the text drawn; left as it is nothing changes, anything else is the
dimension's text override, undone in one step.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.show()
    w.new_document()
    w.tools.osnap_on = False
    for text in ("DIMLINEAR", "0,0", "100,0", "50,10"):
        w._on_command_submitted(text)
    yield w
    editor = getattr(w.tools, "_mtext_editor", None)
    if editor is not None and not getattr(editor, "_closed", True):
        editor.cancel(ask=False)
    w.document.dirty = False
    w.close()


def _dim(win):
    (dim,) = win.document.modelspace().query("DIMENSION")
    return dim


def _double_click_text(win):
    mid = _dim(win).dxf.text_midpoint
    win.tools._mtext_editor = None
    win.on_canvas_double_click(mid.x, mid.y)
    editor = win.tools._mtext_editor
    assert editor is not None, "no in-place editor opened"
    return editor


def _drawn_text(win):
    dim = _dim(win)
    block = win.document.doc.blocks.get(dim.dxf.geometry)
    return [e.plain_text() for e in block if e.dxftype() == "MTEXT"][0]


def test_the_editor_shows_the_measured_text(win):
    editor = _double_click_text(win)
    assert editor._initial.strip() == _drawn_text(win).strip()


def test_a_new_text_becomes_the_override_and_undoes(win):
    editor = _double_click_text(win)
    editor._on_commit("<> TYP.", {})
    dim = _dim(win)
    assert dim.dxf.text == "<> TYP."
    assert _drawn_text(win).endswith("TYP.")
    win._on_command_submitted("U")
    assert _dim(win).dxf.get("text", "") in ("", "<>")


def test_left_as_it_was_nothing_changes(win):
    before = len(win.history._undo) if hasattr(win.history, "_undo") else None
    editor = _double_click_text(win)
    editor._on_commit(editor._initial, {})
    assert _dim(win).dxf.get("text", "") in ("", "<>")
    if before is not None:
        assert len(win.history._undo) == before
