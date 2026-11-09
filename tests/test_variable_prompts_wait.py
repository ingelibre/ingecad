# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A variable typed by its bare name waits for its value (#132).

VIEWRES, CURSORSIZE, PICKBOX and the CENTER* variables printed their
question and went back to "Command:", so the number typed next ran as a
command: 'Unknown command "20000"'. They ask, as every other variable
does, and the next Enter answers them.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.show()
    w.new_document()
    yield w
    w.document.dirty = False
    w.close()


def _history(win) -> str:
    return win.command_line.history.toPlainText()


@pytest.mark.parametrize("name,value,read", [
    ("VIEWRES", "20000", lambda: __import__(
        "render.backend", fromlist=["viewres"]).viewres()),
    ("CURSORSIZE", "30", lambda: __import__(
        "views.viewport", fromlist=["cursorsize"]).cursorsize()),
    ("PICKBOX", "7", lambda: __import__(
        "views.apertures", fromlist=["pickbox"]).pickbox()),
    ("CENTEREXE", "2.5", lambda: __import__(
        "core.centerlines", fromlist=["settings"]).settings().exe),
])
def test_bare_variable_then_value(win, name, value, read):
    win._on_command_submitted(name)
    win._on_command_submitted(value)
    assert "Unknown command" not in _history(win)
    assert float(read()) == pytest.approx(float(value))


def test_enter_keeps_the_value(win):
    from render import backend

    before = backend.viewres()
    win._on_command_submitted("VIEWRES")
    win._on_command_submitted("")
    assert backend.viewres() == before
    win._on_command_submitted("LINE")            # a command again, not an answer
    assert win.tools.active()
    win.tools.cancel()
