# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The command history reads like AutoCAD's: an answer goes at the end of
the prompt that asked for it.

Rafael's sixth and seventh reviews: every answer inside a command was
written as a new "Command: 8", "Command: @0,-8", "Command:" -- a typed
number looked like a command name, and an Enter for a default left a bare
"Command:" between the prompts.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest


def _window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document()
    win.show()
    qapp.processEvents()
    return win


def _type(win, text):
    edit = win.command_line.input
    edit.setFocus()
    if text:
        QTest.keyClicks(edit, text)
    QTest.keyClick(edit, Qt.Key_Return)


def _lines(win):
    return win.command_line.history.toPlainText().splitlines()


def test_a_tools_answers_follow_their_prompts(qapp):
    win = _window(qapp)
    try:
        for text in ("LINE", "0,0", "10,0", ""):
            _type(win, text)
        lines = _lines(win)
        start = max(i for i, l in enumerate(lines) if l.endswith(": LINE"))
        tail = lines[start:]
        assert tail[1].endswith(" 0,0"), tail
        assert tail[2].endswith(" 10,0"), tail
        assert not any(l.startswith("Command: 0") or l.startswith("Command: 1")
                       for l in tail), tail
        assert "Command:" not in tail[1:], "an Enter left a bare Command:"
    finally:
        win.document.dirty = False
        win.close()


def test_a_prompt_flows_answer_follows_its_prompt(qapp):
    win = _window(qapp)
    try:
        _type(win, "LTSCALE")
        _type(win, "2")
        lines = _lines(win)
        asked = next(i for i in range(len(lines) - 1, -1, -1)
                     if "linetype scale factor" in lines[i])
        assert lines[asked].endswith(" 2"), lines[asked:]
    finally:
        win.document.dirty = False
        win.close()


def test_a_message_between_prompt_and_answer_repeats_the_prompt(qapp):
    from views.command_line import CommandLine

    line = CommandLine()
    line.echo_prompt("Specify first point:")
    line.echo("Snap on.")
    line.echo_answer("5,5")
    assert line.history.toPlainText().splitlines()[-1] == \
        "Specify first point: 5,5"
    line.deleteLater()


def test_an_answer_at_select_objects_follows_that_prompt(qapp):
    """Found by the release tour: at TRIM's "Select cutting edges" (and every
    "Select objects:") the answer was written after the PREVIOUS command's
    prompt -- "Specify next point or [Undo]: O" in the middle of TRIM --
    since a selection prompt was echoed as plain text."""
    win = _window(qapp)
    try:
        for text in ("LINE", "0,0", "10,0", "", "TRIM", "O", ""):
            _type(win, text)
        text = win.command_line.history.toPlainText()
        trim_part = text[text.rindex(": TRIM"):]
        assert "[Undo]" not in trim_part and "desHacer" not in trim_part, trim_part
        lines = trim_part.splitlines()
        edges = [l for l in lines if l.rstrip().endswith(": O")]
        assert edges and "edge" in edges[0].lower() or "arista" in edges[0].lower(), lines
        win.tools.cancel()
    finally:
        win.document.dirty = False
        win.close()
