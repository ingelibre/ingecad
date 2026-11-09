# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A tool adds object snaps of its own while it asks for a point, and LINE
and PLINE tell the direction of their last segment (Tool.extra_osnaps,
Tool.last_segment_direction; level 2).

A third-party plugin wrapped the controller's snap_kinds to add Midpoint
and Endpoint while its break-at-point tool ran, and read LINE's and
PLINE's private lists to know the previous segment's direction.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.plugins import LoadedPlugin, PluginSpec
from tools.base import Tool

PLUGIN = "ejemplo_referencias"


class PickPoint(Tool):
    always = False

    def start(self) -> None:
        self.name = "PICKMID"
        self.prompt("Specify a point:")

    def on_point(self, point) -> None:
        self.ctx.finish()

    def extra_osnaps(self):
        return frozenset({"MID", "NOPE"})      # an unknown key is ignored

    @property
    def extra_osnaps_always(self):
        return PickPoint.always


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w.new_document()
    spec = PluginSpec(id=PLUGIN, name="Ref", tools={"PICKMID": PickPoint})
    w.plugins.loaded[spec.id] = LoadedPlugin(spec.id, Path("."), False,
                                             spec=spec)
    assert w.plugins.activate(spec.id)
    for text in ("LINE", "0,0", "20,0", "", "ZOOM", "E"):
        w._on_command_submitted(text)
    w.tools.osnap_on = True
    w.tools.osnap_modes = {"END"}
    PickPoint.always = False
    yield w
    w.tools.cancel()
    w.plugins.deactivate(PLUGIN)
    w.plugins.loaded.pop(PLUGIN, None)
    w.document.dirty = False
    w.close()


def _kind_at_midpoint(win):
    win.tools.on_hover(10.0, 0.3, threshold_world=2.0)
    hit = win.tools.snap_hit
    return hit.kind if hit is not None else None


def test_the_tool_s_snaps_join_the_running_ones(win):
    win._on_command_submitted("LINE")
    assert _kind_at_midpoint(win) != "MID"              # control: not running
    win.tools.cancel()
    win._on_command_submitted("PICKMID")
    assert _kind_at_midpoint(win) == "MID"
    assert "NOPE" not in win.tools.snap_kinds()


def test_osnap_off_drops_them_unless_the_tool_says_always(win):
    win.tools.osnap_on = False
    win._on_command_submitted("PICKMID")
    assert _kind_at_midpoint(win) is None
    PickPoint.always = True
    assert _kind_at_midpoint(win) == "MID"


def test_a_one_shot_snap_still_replaces_them(win):
    win._on_command_submitted("PICKMID")
    win._on_command_submitted("END")
    assert _kind_at_midpoint(win) != "MID"


@pytest.mark.parametrize("command,points,expected", [
    ("LINE", ("0,0",), None),
    ("LINE", ("0,0", "10,10"), 45.0),
    ("LINE", ("0,0", "10,10", "10,0"), -90.0),
    ("PLINE", ("0,0",), None),
    ("PLINE", ("0,0", "-10,0"), 180.0),
])
def test_line_and_pline_tell_their_last_direction(win, command, points,
                                                  expected):
    for text in (command, *points):
        win._on_command_submitted(text)
    direction = win.tools.tool.last_segment_direction()
    assert direction == (None if expected is None
                         else pytest.approx(expected))
