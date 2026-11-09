# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Every tool is a command one can type (#121).

SELECTSIMILAR, ISOLATEOBJECTS and HIDEOBJECTS had a tool, a menu entry and
tests that started the tool directly -- but no command: the shortcut menu
and the keyboard both answered 'Unknown command "SELECTSIMILAR"'. TEXTEDIT
(ED, DDEDIT) and HATCHEDIT were missing the same way, and ADDSELECTED was
registered as submitting itself.
"""
from __future__ import annotations

import pytest

#: Tools only the program starts (a ZOOM option, PLOT's window pick).
INTERNAL = {"PLOTWINDOW", "ZOOMCENTER", "ZOOMWINDOW"}


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.show()
    w.new_document()
    yield w
    w.tools.cancel()
    w.document.dirty = False
    w.close()


def test_every_tool_has_a_command(win):
    from views.tool_controller import ALL_TOOL_CLASSES

    missing = sorted(n for n in ALL_TOOL_CLASSES
                     if n not in INTERNAL and n not in win.dispatcher._commands)
    assert missing == []


@pytest.mark.parametrize("typed, tool", [
    ("SELECTSIMILAR", "SELECTSIMILAR"), ("ISOLATEOBJECTS", "ISOLATEOBJECTS"),
    ("HIDEOBJECTS", "HIDEOBJECTS"), ("ADDSELECTED", "ADDSELECTED"),
    ("ED", "TEXTEDIT"), ("HATCHEDIT", "HATCHEDIT"),
])
def test_typed_starts_the_tool(win, typed, tool):
    win._on_command_submitted(typed)
    history = win.command_line.history.toPlainText()
    assert "Unknown command" not in history
    active = win.tools.active()
    assert active and win.tools.tool.name == tool


def test_select_similar_from_the_shortcut_menu_path(win):
    from core import actions

    for x in (0, 10, 20):
        win.tools._execute(actions.add_circle((x, 0), 2))
    win.tools._execute(actions.add_line((0, 10), (5, 10)))
    circle = win.document.modelspace().query("CIRCLE")[0]
    win.tools.selection = {circle.dxf.handle}
    win._invoke_command("SELECTSIMILAR")
    picked = {win.document.doc.entitydb[h].dxftype()
              for h in win.tools.selection}
    assert len(win.tools.selection) == 3 and picked == {"CIRCLE"}
