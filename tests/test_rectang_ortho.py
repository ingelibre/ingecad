# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""RECTANG's opposite corner is not bent by ORTHO, as in AutoCAD.

GeoCad Yaguareté had to patch this: with ORTHO on, the second click was
pulled onto a horizontal or vertical through the first corner, and the
command answered "Zero-size rectangle".
"""
from __future__ import annotations


def test_ortho_leaves_the_opposite_corner_free(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        win.new_document()
        t = win.tools
        t.ortho_on = True
        win.dispatcher.submit("RECTANG")
        t.on_hover(0, 0, threshold_world=0.001)
        t.on_click(0, 0)
        t.on_hover(30, 20, threshold_world=0.001)
        t.on_click(30, 20)
        rects = list(win.document.modelspace().query("LWPOLYLINE"))
        assert len(rects) == 1, "no rectangle drawn"
        xs = sorted({round(p[0], 6) for p in rects[0].get_points("xy")})
        ys = sorted({round(p[1], 6) for p in rects[0].get_points("xy")})
        assert (xs, ys) == ([0, 30], [0, 20])
        # a LINE after it still obeys ORTHO
        win.dispatcher.submit("LINE")
        t.on_hover(0, 0, threshold_world=0.001)
        t.on_click(0, 0)
        t.on_hover(-40, -3, threshold_world=0.001)
        assert t.resolved_point(-40, -3) == (-40, 0)
        t.cancel()
    finally:
        win.document.dirty = False
        win.close()
