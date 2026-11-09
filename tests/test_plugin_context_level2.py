# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Level 2 of the plugin contract: what a plugin may ask of the window.

A third-party plugin read the window's private state for all of this --
the selection, the tab in view, the pick tolerance -- and wrapped REGEN to
learn when the drawing was rebuilt. Each read broke on a release. The
context now answers each question publicly.
"""
from __future__ import annotations

import pytest

from core import actions
from core.plugins import API_VERSION, PluginContext, PluginSpec


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


def _ctx(win, said=None):
    return PluginContext(host=win, echo=(said.append if said is not None
                                         else (lambda text: None)))


def test_the_contract_is_at_level_two():
    assert API_VERSION >= 2


def test_run_command_types_as_the_user_would(win):
    _ctx(win).run_command("CIRCLE", "0,0", "5")
    (circle,) = win.document.modelspace().query("CIRCLE")
    assert circle.dxf.radius == pytest.approx(5.0)


def test_selection_and_select(win):
    ctx = _ctx(win)
    ctx.run_command("LINE", "0,0", "10,0", "")
    ctx.run_command("LINE", "0,5", "10,5", "")
    lines = list(win.document.modelspace().query("LINE"))
    assert ctx.selection == []
    assert ctx.select(lines[:1]) == 1
    assert ctx.selection == lines[:1]
    assert win.tools.selection == {lines[0].dxf.handle}


def test_a_locked_layer_stays_out_of_select(win):
    ctx = _ctx(win)
    ctx.run_command("LINE", "0,0", "10,0", "")
    (line,) = win.document.modelspace().query("LINE")
    layer = win.document.doc.layers.get(line.dxf.layer)
    layer.lock()
    assert ctx.select([line]) == 0
    assert ctx.selection == []


def test_active_layout_follows_the_tab(win):
    ctx = _ctx(win)
    assert ctx.active_layout == "Model"
    name = win._layout_names()[1]
    win.switch_layout(name)
    assert ctx.active_layout == name


def test_pick_tolerance_follows_the_zoom(win):
    ctx = _ctx(win)
    ctx.run_command("LINE", "0,0", "1000,0", "")
    ctx.run_command("ZOOM", "E")
    far = ctx.pick_tolerance
    ctx.run_command("ZOOM", "W", "0,0", "10,10")
    near = ctx.pick_tolerance
    assert 0 < near < far


def test_the_regen_hook_hears_when_the_drawing_is_in_view(win):
    from PySide6.QtCore import QCoreApplication, QElapsedTimer

    heard = []
    spec = PluginSpec(id="ejemplo_regen", name="Regen",
                      on_regen_done=lambda ctx, layout: heard.append(layout),
                      api_version=2)
    from core.plugins import LoadedPlugin
    from pathlib import Path

    win.plugins.loaded[spec.id] = LoadedPlugin(spec.id, Path("."), False,
                                               spec=spec)
    assert win.plugins.activate(spec.id)
    try:
        _ctx(win).regen()
        clock = QElapsedTimer()
        clock.start()
        while not heard and clock.elapsed() < 10_000:
            QCoreApplication.processEvents()
        assert heard and heard[-1] == "Model"
    finally:
        win.plugins.deactivate(spec.id)
        win.plugins.loaded.pop(spec.id, None)


def test_a_broken_regen_hook_is_reported_not_raised(win):
    from pathlib import Path

    from core.plugins import LoadedPlugin

    def boom(ctx, layout):
        raise RuntimeError("boom")

    spec = PluginSpec(id="ejemplo_boom", name="Boom", on_regen_done=boom)
    win.plugins.loaded[spec.id] = LoadedPlugin(spec.id, Path("."), False,
                                               spec=spec)
    win.plugins.activate(spec.id)
    try:
        win.plugins.regen_done("Model")
        assert "Boom: RuntimeError: boom" in \
            win.command_line.history.toPlainText()
    finally:
        win.plugins.deactivate(spec.id)
        win.plugins.loaded.pop(spec.id, None)


def test_the_selection_hook_hears_each_new_selection_once(win):
    from pathlib import Path

    from core.plugins import LoadedPlugin

    heard = []
    spec = PluginSpec(
        id="ejemplo_sel", name="Sel",
        on_selection_changed=lambda ctx: heard.append(
            sorted(e.dxf.handle for e in ctx.selection)))
    win.plugins.loaded[spec.id] = LoadedPlugin(spec.id, Path("."), False,
                                               spec=spec)
    win.plugins.activate(spec.id)
    try:
        ctx = _ctx(win)
        ctx.run_command("LINE", "0,0", "10,0", "")
        ctx.run_command("ZOOM", "E")
        (line,) = win.document.modelspace().query("LINE")
        heard.clear()
        win.tools.on_hover(5, 0, threshold_world=0.5)
        win.tools.on_click(5, 0)                 # a pick
        win.tools.on_hover(5, 1, threshold_world=0.5)   # a hover: no news
        assert heard == [[line.dxf.handle]]
        win.tools.clear_selection()
        assert heard == [[line.dxf.handle], []]
    finally:
        win.plugins.deactivate(spec.id)
        win.plugins.loaded.pop(spec.id, None)
