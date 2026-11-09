# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A plugin gives an entity type grips of its own (grip_handlers, level 2).

A third-party plugin replaced the module functions that list and apply
grips, and four of the controller's grip methods, to give images a clip
grip and its own objects theirs. It now declares a handler per type; the
core keeps the snapshot, the undo, Esc and the snapping.
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from core import select
from core.plugins import LoadedPlugin, PluginSpec


class TopGrip:
    """A circle gets one grip, on top; dragging it sets the radius."""

    def grips(self, entity):
        c, r = entity.dxf.center, entity.dxf.radius
        return [(c.x, c.y + r, "plugin_top")]

    def move(self, entity, index, role, point):
        if role != "plugin_top":
            return False
        c = entity.dxf.center
        entity.dxf.radius = math.hypot(point[0] - c.x, point[1] - c.y)
        return True


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


def _activate(win, handler, ident="ejemplo_grips"):
    spec = PluginSpec(id=ident, name="Grips",
                      grip_handlers={"CIRCLE": handler})
    win.plugins.loaded[ident] = LoadedPlugin(ident, Path("."), False,
                                             spec=spec)
    assert win.plugins.activate(ident)
    return ident


def _circle(win):
    for text in ("CIRCLE", "0,0", "5", "ZOOM", "E"):
        win._on_command_submitted(text)
    (circle,) = win.document.modelspace().query("CIRCLE")
    win.tools.select_entities([circle])
    return circle


def test_the_plugin_grips_replace_the_cores_and_edit_with_undo(win):
    ident = _activate(win, TopGrip())
    try:
        circle = _circle(win)
        grips = win.tools.grip_points()
        assert [(round(x, 6), round(y, 6), r) for x, y, r, _h, _i in grips] \
            == [(0.0, 5.0, "plugin_top")]
        win.tools.begin_grip_drag(grips[0])
        win.tools.update_grip_drag(0, 8)
        assert circle.dxf.radius == pytest.approx(8.0)      # live
        win.tools.finish_grip_drag(0, 9)
        assert circle.dxf.radius == pytest.approx(9.0)
        win._on_command_submitted("U")
        assert circle.dxf.radius == pytest.approx(5.0)
    finally:
        win.plugins.deactivate(ident)
        win.plugins.loaded.pop(ident, None)


def test_esc_takes_a_plugin_grip_back(win):
    ident = _activate(win, TopGrip())
    try:
        circle = _circle(win)
        win.tools.begin_grip_drag(win.tools.grip_points()[0])
        win.tools.update_grip_drag(0, 8)
        win.tools.cancel()
        assert circle.dxf.radius == pytest.approx(5.0)
    finally:
        win.plugins.deactivate(ident)
        win.plugins.loaded.pop(ident, None)


def test_a_drop_command_of_its_own(win):
    from core.actions import SnapshotCommand

    class OwnDrop(TopGrip):
        made = []

        def drop(self, ctx, entity, index, role, point):
            command = SnapshotCommand([entity])
            entity.dxf.radius = 2.0
            command.commit(ctx.document)
            command.name = "PLUGINGRIP"
            self.made.append(command)
            return command

    handler = OwnDrop()
    ident = _activate(win, handler)
    try:
        circle = _circle(win)
        win.tools.begin_grip_drag(win.tools.grip_points()[0])
        win.tools.update_grip_drag(0, 8)
        win.tools.finish_grip_drag(0, 8)
        assert handler.made and circle.dxf.radius == pytest.approx(2.0)
    finally:
        win.plugins.deactivate(ident)
        win.plugins.loaded.pop(ident, None)


def test_turning_it_off_gives_the_core_grips_back(win):
    ident = _activate(win, TopGrip())
    win.plugins.deactivate(ident)
    win.plugins.loaded.pop(ident, None)
    assert "CIRCLE" not in select._GRIP_HANDLERS
    _circle(win)
    roles = [r for _x, _y, r, _h, _i in win.tools.grip_points()]
    assert "plugin_top" not in roles and "center" in roles


def test_a_handler_that_says_none_keeps_the_cores(win):
    class Shy(TopGrip):
        def grips(self, entity):
            return None

        def move(self, entity, index, role, point):
            return False

    ident = _activate(win, Shy())
    try:
        _circle(win)
        roles = [r for _x, _y, r, _h, _i in win.tools.grip_points()]
        assert "center" in roles
    finally:
        win.plugins.deactivate(ident)
        win.plugins.loaded.pop(ident, None)


def test_grips_shown_before_the_plugin_change_when_it_turns_on(win):
    circle = _circle(win)
    assert "center" in [r for *_x, r, _h, _i in
                        [(g[0], g[1], g[2], g[3], g[4])
                         for g in win.tools.grip_points()]]
    ident = _activate(win, TopGrip())
    try:
        roles = [g[2] for g in win.tools.grip_points()]
        assert roles == ["plugin_top"]
    finally:
        win.plugins.deactivate(ident)
        win.plugins.loaded.pop(ident, None)
    assert "center" in [g[2] for g in win.tools.grip_points()]
    assert circle.is_alive
