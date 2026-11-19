# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The command line completes plugin commands, and never brings back the
prompt of a command that has already finished.

* Completion: the list was set once, while the window was built, before
  ``plugins.activate_enabled()``; a plugin's commands reached the dispatcher
  but never the completer, so typing the start of MURO completed nothing.
* Prompts: ``echo_answer`` repeats the last prompt when a message was
  printed after it. That prompt survived from one command to the next: a
  plugin command that printed its questions as messages had its answers
  shown after PEDIT's "Enter an option [Close/Join/...]".
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.plugins import LoadedPlugin, PluginSpec

P = "demo_plugin"


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.new_document()
    yield w
    w.plugins.deactivate(P)
    w.plugins.loaded.pop(P, None)
    w.document.dirty = False
    w.close()


def _completions(win):
    model = win.command_line.input.completer().model()
    return {model.index(i, 0).data() for i in range(model.rowCount())}


def test_a_plugin_command_is_offered_while_typing(win):
    completer = win.command_line.input.completer()
    assert "LINE" in _completions(win)
    spec = PluginSpec(id=P, name="Demo", commands={"DEMOWALL": lambda ctx, *a: None})
    win.plugins.loaded[P] = LoadedPlugin(P, Path("."), False, spec=spec)
    assert win.plugins.activate(P)
    assert "DEMOWALL" in _completions(win)
    # the same completer, so its inline mode and case rule are kept
    assert win.command_line.input.completer() is completer
    win.plugins.deactivate(P)
    assert "DEMOWALL" not in _completions(win)
    assert "LINE" in _completions(win)


def test_a_finished_command_does_not_lend_its_prompt(win):
    line = win.command_line
    line.echo_prompt("Enter an option [Close/Join/Width/Reverse/Undo/eXit] <eXit>:")
    win.tools._finish()                       # that command is over
    line.echo_input("DEMO")                  # a new one starts
    line.echo("Base height [0.00]:")         # printed as a plain message
    line.echo_answer("5")
    last = line.history.toPlainText().splitlines()[-1]
    assert last == "5"
    assert "Join" not in line.history.toPlainText().splitlines()[-1]


def test_within_a_command_the_prompt_still_comes_back_with_the_answer(win):
    line = win.command_line
    line.echo_input("DEMO")
    line.echo_prompt("Specify height:")
    line.echo("(current height 3.00)")
    line.echo_answer("2.7")
    assert line.history.toPlainText().splitlines()[-1] == "Specify height: 2.7"
