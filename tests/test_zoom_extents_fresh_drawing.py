# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Zoom Extents frames what was just drawn, not the origin (#96).

Rafael, recording tutorials (2026-10-14): "Zoom Extents centres 0,0 on the
screen but not the drawn objects." What is drawn since the last regen lives
in the overlay scene; Zoom Extents read only the baked scene, found a new
drawing empty and framed the +-50 box around the origin.
"""
from __future__ import annotations


def test_zoom_extents_frames_lines_drawn_far_from_the_origin(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    qapp.processEvents()
    tools = win.tools
    for a, b in (((5000, 3000), (5100, 3050)), ((5100, 3050), (5000, 3100))):
        win.dispatcher.submit("LINE")
        tools.on_click(*a)
        tools.on_click(*b)
        win.dispatcher.submit("")
        qapp.processEvents()
    assert len(win.document.modelspace().query("LINE")) == 2

    win.dispatcher.submit("ZOOM")
    win.dispatcher.submit("E")
    qapp.processEvents()

    view = win.viewport.view
    assert (view.cx, view.cy) == (5050.0, 3050.0)
    # and the lines fill the view: 100 units tall in the canvas height
    assert 0.8 * view.height <= 100 * view.scale <= view.height
    win.document.dirty = False
    win.close()
