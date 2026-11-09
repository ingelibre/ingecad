# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A plugin reads typed input first (input_filters, level 2).

A third-party plugin wrapped the controller's text handling and the
dispatcher's submit and cancel to read bearings and grads, and to end its
own mode on Enter or Esc with no command running. It now declares an
input filter: it can leave the input, rewrite it, or take it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.plugins import CONSUMED, ESCAPE, LoadedPlugin, PluginSpec


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


def _activate(win, *filters):
    spec = PluginSpec(id="ejemplo_input", name="Input",
                      input_filters=tuple(filters))
    win.plugins.loaded[spec.id] = LoadedPlugin(spec.id, Path("."), False,
                                               spec=spec)
    assert win.plugins.activate(spec.id)


@pytest.fixture
def plugin_off(win):
    yield
    win.plugins.deactivate("ejemplo_input")
    win.plugins.loaded.pop("ejemplo_input", None)


def test_a_filter_rewrites_what_is_typed(win, plugin_off):
    def bearings(ctx, text, state):
        # "N45E10" -> 10 units at 45 degrees from north toward east
        if state.tool == "LINE" and text.upper() == "N45E10":
            return "@10<45"
        return None

    _activate(win, bearings)
    for text in ("LINE", "0,0", "N45E10", ""):
        win._on_command_submitted(text)
    (line,) = win.document.modelspace().query("LINE")
    assert (line.dxf.end.x, line.dxf.end.y) == pytest.approx(
        (7.0710678, 7.0710678))
    # the history keeps what the user typed
    assert "N45E10" in win.command_line.history.toPlainText()


def test_a_filter_takes_enter_and_esc_with_no_command(win, plugin_off):
    heard = []

    def mode(ctx, text, state):
        if state.tool == "" and text in ("", ESCAPE):
            heard.append("esc" if text == ESCAPE else "enter")
            return CONSUMED
        return None

    _activate(win, mode)
    win._on_command_submitted("")
    win._on_prompt_cancelled()
    assert heard == ["enter", "esc"]


def test_a_filter_that_leaves_it_changes_nothing(win, plugin_off):
    seen = []
    _activate(win, lambda ctx, text, state: seen.append(text))
    for text in ("CIRCLE", "0,0", "5"):
        win._on_command_submitted(text)
    assert seen == ["CIRCLE", "0,0", "5"]
    assert len(win.document.modelspace().query("CIRCLE")) == 1


def test_a_broken_filter_is_named_and_skipped(win, plugin_off):
    def boom(ctx, text, state):
        raise RuntimeError("boom")

    _activate(win, boom)
    for text in ("CIRCLE", "0,0", "5"):
        win._on_command_submitted(text)
    assert len(win.document.modelspace().query("CIRCLE")) == 1
    assert "Input: RuntimeError: boom" in \
        win.command_line.history.toPlainText()
