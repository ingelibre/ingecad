# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A plugin's controls in the core's own bars (``PluginSpec.bar_controls``,
plugin contract level 3).

A plugin whose state goes with the current layer -- the architecture
plugin's current level, say -- could only show it on a toolbar of its own,
far from the layer it qualifies, and had to poll to keep it true. A
control now sits beside the current layer (or on the status bar), is
refreshed with the Properties bar and leaves with the plugin.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest
from PySide6.QtWidgets import QLabel, QWidget

from core.plugins import API_VERSION, BarControl, LoadedPlugin, PluginSpec

A, B = "nivel_a", "nivel_b"


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.resize(1400, 800)
    w.show()
    w.new_document()
    yield w
    for pid in (A, B):
        w.plugins.deactivate(pid)
        w.plugins.loaded.pop(pid, None)
    w.document.dirty = False
    w.close()


def _label(ctx):
    return QLabel("?")


def _show_layer(ctx, label):
    from core import layers

    label.setText("level of " + layers.current_layer_name(ctx.document))


def _activate(win, spec):
    win.plugins.loaded[spec.id] = LoadedPlugin(spec.id, Path("."), False,
                                               spec=spec)
    return win.plugins.activate(spec.id)


def _after_layer_combo(win):
    """The widgets right after the current-layer combo, up to the next
    separator."""
    bar = win._props_toolbar
    actions = bar.actions()
    index = next(i for i, a in enumerate(actions)
                 if bar.widgetForAction(a) is win._layer_combo)
    out = []
    for action in actions[index + 1:]:
        if action.isSeparator():
            break
        out.append(bar.widgetForAction(action))
    return out


def test_the_contract_is_at_level_three():
    assert API_VERSION >= 3


def test_beside_the_current_layer_and_refreshed_with_it(win):
    spec = PluginSpec(id=A, name="A", api_version=3, bar_controls=(
        BarControl("level", _label, _show_layer),))
    assert _activate(win, spec)
    label = win.plugin_bar_control(A, "level")
    assert _after_layer_combo(win) == [label]
    assert label.text() == "level of 0"
    for text in ("-LAYER", "M", "PB", ""):
        win._on_command_submitted(text)
    assert label.text() == "level of PB"


def test_two_plugins_line_up_and_leave_no_trace(win):
    before = list(win._props_toolbar.actions())
    status_before = len(win.statusBar().findChildren(QWidget))
    a = PluginSpec(id=A, name="A", bar_controls=(BarControl("level", _label),))
    b = PluginSpec(id=B, name="B", bar_controls=(
        BarControl("x", _label), BarControl("s", _label, where="status")))
    assert _activate(win, a) and _activate(win, b)
    first, second = (win.plugin_bar_control(A, "level"),
                     win.plugin_bar_control(B, "x"))
    assert _after_layer_combo(win) == [first, second]
    status = win.plugin_bar_control(B, "s")
    assert status.parent() is not None and status.isVisibleTo(win)
    win.plugins.deactivate(A)
    assert _after_layer_combo(win) == [second]
    win.plugins.deactivate(B)
    assert win._props_toolbar.actions() == before
    assert len(win.statusBar().findChildren(QWidget)) == status_before
    assert not win.findChildren(QWidget, f"plugin_{B}_s")
    assert win.plugin_bar_control(B, "s") is None


def test_a_new_drawing_and_the_language_refresh_it(win):
    calls = []
    spec = PluginSpec(id=A, name="A", bar_controls=(BarControl(
        "level", _label, lambda ctx, w: calls.append(ctx.document)),))
    assert _activate(win, spec)
    calls.clear()
    win.new_document()
    assert calls and calls[-1] is win.document
    calls.clear()
    win._retranslate()
    assert calls


def test_the_context_answers_with_the_widget(win):
    from core.plugins import PluginContext

    spec = PluginSpec(id=A, name="A", bar_controls=(BarControl("level", _label),))
    assert _activate(win, spec)
    ctx = PluginContext(host=win, echo=lambda text: None)
    assert ctx.bar_control(A, "level") is win.plugin_bar_control(A, "level")
    assert ctx.bar_control(A, "other") is None


@pytest.mark.parametrize("controls", [
    (BarControl("x", _label, where="menu"),),
    (BarControl("x", _label), BarControl("x", _label)),
    (BarControl("ok", _label), BarControl("bad", lambda ctx: 1 / 0)),
])
def test_a_bad_control_keeps_the_plugin_off_and_leaves_nothing(win, controls):
    before = list(win._props_toolbar.actions())
    spec = PluginSpec(id=A, name="A", bar_controls=controls)
    assert not _activate(win, spec)
    assert win._props_toolbar.actions() == before
    assert not win.findChildren(QWidget, f"plugin_{A}_ok")


def test_a_failing_refresh_never_stops_the_properties_bar(win, caplog):
    def broken(ctx, widget):
        raise RuntimeError("no level")

    spec = PluginSpec(id=A, name="A", bar_controls=(BarControl("level", _label, broken),))
    with caplog.at_level(logging.ERROR, logger="ingecad.plugins"):
        assert _activate(win, spec)
        for text in ("-LAYER", "M", "PB", ""):
            win._on_command_submitted(text)
    assert win._layer_combo.currentText() == "PB"
    assert "failed to refresh" in caplog.text
