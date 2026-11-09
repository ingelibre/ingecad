# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A plugin's operation of several commands is one undo step.

A third-party plugin reached into the undo stack to fold what it drew
into one step, and to take back a half-done operation when the user
cancelled it. The plugin context now offers that: a transaction, and the
mark / fold_since / undo_to it is built on.
"""
from __future__ import annotations

import pytest

from core import actions
from core.plugins import PluginContext


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w.new_document()
    yield w
    w.document.dirty = False
    w.close()


def _ctx(win):
    return PluginContext(host=win, echo=lambda text: None)


def _lines(win):
    return len(win.document.modelspace().query("LINE"))


def _two_lines(ctx):
    ctx.execute(actions.add_line((0, 0), (10, 0)))
    ctx.execute(actions.add_line((0, 5), (10, 5)))


def test_a_transaction_is_one_undo_step(win):
    ctx = _ctx(win)
    with ctx.transaction("Parcel"):
        _two_lines(ctx)
    assert _lines(win) == 2
    win._on_command_submitted("U")
    assert _lines(win) == 0
    win._on_command_submitted("REDO")
    assert _lines(win) == 2


def test_a_failed_transaction_leaves_no_trace(win):
    ctx = _ctx(win)
    ctx.execute(actions.add_line((0, -5), (10, -5)))   # before: stays
    with pytest.raises(RuntimeError):
        with ctx.transaction("Parcel"):
            _two_lines(ctx)
            raise RuntimeError("cancelled")
    assert _lines(win) == 1
    assert not win.history.can_redo
    win._on_command_submitted("U")
    assert _lines(win) == 0


def test_undo_to_a_mark(win):
    ctx = _ctx(win)
    mark = ctx.mark()
    _two_lines(ctx)
    ctx.undo_to(mark)
    assert _lines(win) == 0
    assert ctx.mark() == mark
    assert not win.history.can_redo


def test_fold_since_a_mark(win):
    ctx = _ctx(win)
    mark = ctx.mark()
    _two_lines(ctx)
    ctx.fold_since(mark, "Two lines")
    assert ctx.mark() == mark + 1
    win._on_command_submitted("U")
    assert "Undo: Two lines" in win.command_line.history.toPlainText()
    assert _lines(win) == 0
