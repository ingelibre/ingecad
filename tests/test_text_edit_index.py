# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A text edited in place is picked by its new extent at once.

A third-party plugin compared signatures in the selection highlight to
make up for a pick index that kept the text's old box after an in-place
edit: a word made longer could not be picked by its new end.
"""
from __future__ import annotations

import time

import pytest

from core import actions


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w.new_document()
    w.tools.osnap_on = False
    yield w
    w.document.dirty = False
    w.close()


def _settle(qapp, win):
    t0 = time.monotonic()
    while win._regen_worker is not None and time.monotonic() - t0 < 30:
        qapp.processEvents()
    for _ in range(5):
        qapp.processEvents()


def test_the_new_end_is_picked(win, qapp):
    tools = win.tools
    tools._execute(actions.add_text((0, 0), "AB", 2.5))
    win._on_command_submitted("ZOOM")
    win._on_command_submitted("W")
    win._on_command_submitted("-5,-10")
    win._on_command_submitted("60,10")
    _settle(qapp, win)
    (text,) = win.document.modelspace().query("TEXT")
    far = (40.0, 1.2)                         # within the new 50 units
    assert not tools.index.pick_all(far, 0.5)          # control: nothing yet
    assert tools.open_text_editor_for(text)
    editor = tools._mtext_editor
    editor.edit.setPlainText("AB" + "W" * 14)
    editor.commit()
    _settle(qapp, win)
    assert text.dxf.handle in tools.index.pick_all(far, 0.5)


def test_undo_gives_the_old_extent_back(win, qapp):
    tools = win.tools
    tools._execute(actions.add_text((0, 0), "AB", 2.5))
    for text in ("ZOOM", "W", "-5,-10", "60,10"):
        win._on_command_submitted(text)
    _settle(qapp, win)
    (text,) = win.document.modelspace().query("TEXT")
    assert tools.open_text_editor_for(text)
    tools._mtext_editor.edit.setPlainText("AB" + "W" * 14)
    tools._mtext_editor.commit()
    _settle(qapp, win)
    win._on_command_submitted("U")
    _settle(qapp, win)
    assert text.dxf.text == "AB"
    assert not tools.index.pick_all((40.0, 1.2), 0.5)
