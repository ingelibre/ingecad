# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A plugin may stop an undo, a save or a close, and take a double-click
(on_before, on_double_click; level 2).

A third-party plugin editing a block in its own mode wrapped U, the save
and the window's close to keep the drawing whole until its mode ended,
and wrapped the double-click to open its own editor on its objects.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.plugins import LoadedPlugin, PluginSpec


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w.new_document()
    w.tools.osnap_on = False
    yield w
    w.plugins.deactivate("ejemplo_veto")
    w.plugins.loaded.pop("ejemplo_veto", None)
    w.document.dirty = False
    w.close()


def _activate(win, **hooks):
    spec = PluginSpec(id="ejemplo_veto", name="Veto", **hooks)
    win.plugins.loaded[spec.id] = LoadedPlugin(spec.id, Path("."), False,
                                               spec=spec)
    assert win.plugins.activate(spec.id)


def _history(win):
    return win.command_line.history.toPlainText()


def test_an_undo_is_stopped_with_the_reason(win):
    _activate(win, on_before=lambda ctx, event:
              "finish the edit first" if event == "undo" else None)
    for text in ("CIRCLE", "0,0", "5", "U"):
        win._on_command_submitted(text)
    assert len(win.document.modelspace().query("CIRCLE")) == 1
    assert "Veto: finish the edit first" in _history(win)


def test_a_save_is_stopped(win, tmp_path):
    _activate(win, on_before=lambda ctx, event:
              "not now" if event == "save" else None)
    assert win._write_document(tmp_path / "x.dxf", "r2000") is False
    assert not (tmp_path / "x.dxf").exists()
    assert "Veto: not now" in _history(win)


def test_closing_the_drawing_is_stopped(win):
    _activate(win, on_before=lambda ctx, event:
              "not now" if event == "close" else None)
    document = win.document
    assert win.close_document() is False
    assert win.document is document


def test_closing_the_window_is_stopped(win):
    from PySide6.QtGui import QCloseEvent

    _activate(win, on_before=lambda ctx, event:
              "not now" if event == "close" else None)
    event = QCloseEvent()
    win.closeEvent(event)
    assert not event.isAccepted()


def test_no_reason_lets_everything_go(win):
    _activate(win, on_before=lambda ctx, event: None)
    for text in ("CIRCLE", "0,0", "5", "U"):
        win._on_command_submitted(text)
    assert len(win.document.modelspace().query("CIRCLE")) == 0


def test_a_double_click_goes_to_the_plugin_first(win):
    taken = []

    def mine(ctx, entity):
        if entity.dxftype() == "MTEXT":
            taken.append(entity)
            return True
        return False

    from core import actions

    _activate(win, on_double_click=mine)
    win.tools._execute(actions.add_mtext((0, 0), (20, -5), "Hello", 2.5))
    win._on_command_submitted("ZOOM")
    win._on_command_submitted("E")
    (mtext,) = win.document.modelspace().query("MTEXT")
    win.tools.on_hover(2, -1, threshold_world=2)
    win.on_canvas_double_click(2, -1)
    assert taken == [mtext]
    assert win.tools.tool is None           # the core's editor stayed shut
