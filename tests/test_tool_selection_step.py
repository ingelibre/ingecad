# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A tool hears each step of its "Select objects:" phase
(Tool.on_selection_step; level 2).

A third-party plugin's MATCHPROP-like tool wrapped the controller's
selection click to show, while the user was still picking, what each
object would become. The plugins' on_selection_changed only tells a new
selection with no command running.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core import actions
from core.plugins import LoadedPlugin, PluginSpec
from tools.base import Tool

PLUGIN = "ejemplo_pasos"


class Picker(Tool):
    wants_selection = True
    steps: list = []
    chosen: list = []

    def start(self) -> None:
        self.name = "PICKSTEPS"

    def on_selection_step(self, handles) -> None:
        Picker.steps.append(set(handles))

    def on_selection(self, entities) -> None:
        Picker.chosen = list(entities)
        self.ctx.finish()


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w.new_document()
    w.tools.osnap_on = False
    spec = PluginSpec(id=PLUGIN, name="Pasos", tools={"PICKSTEPS": Picker})
    w.plugins.loaded[spec.id] = LoadedPlugin(spec.id, Path("."), False,
                                             spec=spec)
    assert w.plugins.activate(spec.id)
    Picker.steps, Picker.chosen = [], []
    yield w
    w.tools.cancel()
    w.plugins.deactivate(spec.id)
    w.plugins.loaded.pop(spec.id, None)
    w.document.dirty = False
    w.close()


def _pick(win, x, y):
    win.tools.on_hover(x, y, threshold_world=0.5)
    win.tools.on_click(x, y)


def test_each_pick_and_remove_is_told(win):
    win.tools._execute(actions.add_line((0, 0), (10, 0)))
    win.tools._execute(actions.add_line((0, 5), (10, 5)))
    win._on_command_submitted("ZOOM")
    win._on_command_submitted("E")
    low, high = (e.dxf.handle for e in win.document.modelspace())
    win._on_command_submitted("PICKSTEPS")
    _pick(win, 5, 0)
    _pick(win, 5, 5)
    win._on_command_submitted("R")
    _pick(win, 5, 0)
    assert Picker.steps == [{low}, {low, high}, {high}]
    win._on_command_submitted("")
    assert [e.dxf.handle for e in Picker.chosen] == [high]


def test_without_a_tool_asking_nobody_is_told(win):
    win.tools._execute(actions.add_line((0, 0), (10, 0)))
    win._on_command_submitted("ZOOM")
    win._on_command_submitted("E")
    _pick(win, 5, 0)
    assert win.tools.selection and Picker.steps == []
