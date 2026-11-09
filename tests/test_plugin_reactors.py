# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A plugin keeps its derived objects true after any command (reactors;
level 2).

The architecture plugin keeps a wall's openings and its XDATA in step
after a MOVE, a COPY or a grip edit it does not own. The associative
dimensions already did it inside History; a reactor is the same thing for
a plugin: ``before(document)`` -> state, ``react(document, state)`` -> a
Command, run in the same undo step as the command that caused it.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from core import actions
from core.commands import Command
from core.plugins import LoadedPlugin, PluginSpec

PLUGIN = "ejemplo_reactor"


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w.new_document()
    w.tools.osnap_on = False
    yield w
    w.plugins.deactivate(PLUGIN)
    w.plugins.loaded.pop(PLUGIN, None)
    w.document.dirty = False
    w.close()


class _MoveText(Command):
    name = "LABEL"

    def __init__(self, text, old, new) -> None:
        self.text, self.old, self.new = text, old, new

    def do(self, document) -> None:
        self.text.dxf.insert = self.new

    def undo(self, document) -> None:
        self.text.dxf.insert = self.old


class LabelFollowsCircle:
    """A TEXT kept on its circle's centre, as a plugin's tag would be."""

    def __init__(self) -> None:
        self.pairs = {}               # circle handle -> text entity
        self.calls = 0

    def before(self, document):
        self.calls += 1
        if not self.pairs:
            return None
        msp = document.doc.entitydb
        return {h: tuple(msp[h].dxf.center) for h in self.pairs if h in msp}

    def react(self, document, state):
        db = document.doc.entitydb
        for handle, old in state.items():
            centre = tuple(db[handle].dxf.center)
            if centre != old:
                text = self.pairs[handle]
                return _MoveText(text, tuple(text.dxf.insert), centre)
        return None


def _activate(win, *reactors):
    spec = PluginSpec(id=PLUGIN, name="Reactor", reactors=reactors)
    win.plugins.loaded[spec.id] = LoadedPlugin(spec.id, Path("."), False,
                                               spec=spec)
    assert win.plugins.activate(spec.id)


def _type(win, *texts):
    for text in texts:
        win._on_command_submitted(text)


def _tagged_circle(win, reactor):
    _type(win, "CIRCLE", "0,0", "5")
    win.tools._execute(actions.add_text((0, 0), "A1", 2.5))
    circle = win.document.modelspace().query("CIRCLE")[0]
    text = win.document.modelspace().query("TEXT")[0]
    reactor.pairs[circle.dxf.handle] = text
    return circle, text


def _at(entity, attr):
    return tuple(round(v, 6) for v in entity.dxf.get(attr))[:2]


def test_a_move_brings_the_label_in_the_same_undo_step(win):
    reactor = LabelFollowsCircle()
    _activate(win, reactor)
    circle, text = _tagged_circle(win, reactor)
    win.tools.select_entities([circle])
    _type(win, "MOVE", "0,0", "10,0")
    assert _at(circle, "center") == (10, 0)
    assert _at(text, "insert") == (10, 0)
    _type(win, "U")
    assert _at(circle, "center") == (0, 0)
    assert _at(text, "insert") == (0, 0)
    _type(win, "REDO")
    assert _at(circle, "center") == (10, 0)
    assert _at(text, "insert") == (10, 0)


def test_a_grip_edit_brings_it_too(win):
    reactor = LabelFollowsCircle()
    _activate(win, reactor)
    circle, text = _tagged_circle(win, reactor)
    tools = win.tools
    _type(win, "ZOOM", "E")
    tools.select_entities([circle])
    grip = next(g for g in tools.grip_points()
                if (round(g[0], 6), round(g[1], 6)) == (0.0, 0.0))
    tools.begin_grip_drag(grip)
    tools.update_grip_drag(4.0, 3.0)
    tools.finish_grip_drag(4.0, 3.0)
    assert _at(text, "insert") == (4, 3)
    _type(win, "U")
    assert _at(text, "insert") == (0, 0)


def test_a_folded_script_undoes_the_labels_with_it(win):
    reactor = LabelFollowsCircle()
    _activate(win, reactor)
    circle, text = _tagged_circle(win, reactor)
    ctx = win.plugins.context()
    with ctx.transaction("TWO MOVES"):
        win.tools._execute(actions.move_entities([circle], 5, 0))
        win.tools._execute(actions.move_entities([circle], 0, 5))
    assert _at(text, "insert") == (5, 5)
    _type(win, "U")
    assert _at(circle, "center") == (0, 0)
    assert _at(text, "insert") == (0, 0)
    _type(win, "REDO")
    assert _at(text, "insert") == (5, 5)


def test_deactivated_it_no_longer_reacts(win):
    reactor = LabelFollowsCircle()
    _activate(win, reactor)
    circle, text = _tagged_circle(win, reactor)
    win.plugins.deactivate(PLUGIN)
    calls = reactor.calls
    win.tools._execute(actions.move_entities([circle], 10, 0))
    assert reactor.calls == calls
    assert _at(text, "insert") == (0, 0)


def test_a_broken_reactor_leaves_editing_alone(win, caplog):
    class Broken:
        def before(self, document):
            return {}

        def react(self, document, state):
            raise RuntimeError("boom")

    _activate(win, Broken())
    with caplog.at_level(logging.ERROR, logger="ingecad.plugins"):
        _type(win, "CIRCLE", "0,0", "5")
    circle = win.document.modelspace().query("CIRCLE")[0]
    win.tools._execute(actions.move_entities([circle], 10, 0))
    assert _at(circle, "center") == (10, 0)
    assert "boom" in caplog.text
    _type(win, "U")
    assert _at(circle, "center") == (0, 0)
