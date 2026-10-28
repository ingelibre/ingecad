# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Objects on a locked layer cannot be modified (LAYER, Command Reference).

Only ALL left them out: a window, a crossing or a single pick handed them
to ERASE and MOVE like any other, and a pickfirst Delete erased them. Typed
and clicked as the user does it.
"""
from __future__ import annotations


def _window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    for text in ("-LAYER", "M", "EJES", ""):
        win._on_command_submitted(text)
    for text in ("LINE", "0,0", "10,0", ""):
        win._on_command_submitted(text)
    for text in ("-LAYER", "S", "0", ""):
        win._on_command_submitted(text)
    for text in ("LINE", "0,5", "10,5", ""):
        win._on_command_submitted(text)
    for text in ("-LAYER", "LO", "EJES", ""):
        win._on_command_submitted(text)
    assert win.document.doc.layers.get("EJES").is_locked()
    return win


def _layers(win):
    return sorted(e.dxf.layer for e in win.document.modelspace().query("LINE"))


def test_window_and_pick_leave_a_locked_layer_alone(qapp):
    win = _window(qapp)
    t = win.tools
    win._on_command_submitted("ERASE")
    t.on_click(-2.0, -2.0)
    t.on_click(12.0, 7.0)                 # window over both lines
    win._on_command_submitted("")
    assert _layers(win) == ["EJES"]
    win._on_command_submitted("U")
    win._on_command_submitted("MOVE")
    t.on_click(5.0, 0.0)                  # the locked line itself
    win._on_command_submitted("")
    win._on_command_submitted("0,0")
    win._on_command_submitted("3,0")
    line = next(e for e in win.document.modelspace().query("LINE")
                if e.dxf.layer == "EJES")
    assert line.dxf.start.x == 0.0
    win.close()


def test_pickfirst_delete_keeps_a_locked_layer(qapp):
    win = _window(qapp)
    t = win.tools
    t.on_click(12.0, 7.0)                 # crossing, no command running
    t.on_click(-2.0, -2.0)
    assert t.delete_selection()
    assert _layers(win) == ["EJES"]
    win.close()


def test_list_still_reads_a_locked_layer(qapp):
    win = _window(qapp)
    t = win.tools
    win._on_command_submitted("LIST")
    t.on_click(5.0, 0.0)
    win._on_command_submitted("")
    assert "EJES" in win.command_line.history.toPlainText()
    win.close()
