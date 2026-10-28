# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A construction line looks infinite and stays out of the extents (#98).

A user: "He estado buscando la manera de poner las líneas auxiliares de
tamaño infinito ... se ven de tamaño finito". ezdxf draws an XLINE 20 units
long. It now reaches several drawing diagonals each way -- past the screen
at any sensible zoom -- while Zoom Extents and an Extents plot still frame
the drawing, as AutoCAD's do.
"""
from __future__ import annotations

import numpy as np
import pytest


def test_an_xline_crosses_the_whole_view_and_zoom_extents_ignores_it(qapp):
    from core import actions
    from views.main_window import MainWindow

    win = MainWindow()
    win.resize(1000, 700)
    win.show()
    win.new_document()
    try:
        t = win.tools
        t._execute(actions.add_line((0, 0), (100, 50)))
        win._on_command_submitted("XLINE")
        t.on_click(50, 25)
        t.on_click(60, 30)                    # through the line's middle
        win._on_command_submitted("")
        (xline,) = win.document.modelspace().query("XLINE")
        win._on_command_submitted("ZOOM")
        win._on_command_submitted("E")
        qapp.processEvents()

        view = win.viewport.view
        assert (view.cx, view.cy) == pytest.approx((50, 25))   # the line, only
        x0, y0, x1, y1 = win.viewport.scene_bounds()
        assert (x0, y0, x1, y1) == pytest.approx((0, 0, 100, 50))
        # where the XLINE's strokes are, in whichever scene holds it
        reach = []
        for scene in (win.viewport._scene, win.viewport._overlay_scene):
            if scene is None:
                continue
            for name, first, count in scene.handle_ranges.get(xline.dxf.handle, ()):
                pos = getattr(scene, name).positions()[first:first + count]
                reach.append(pos.astype(np.float64) + scene.origin)
        pos = np.vstack(reach)
        half_w = view.width / view.scale / 2
        # past both sides of the screen, by far
        assert pos[:, 0].min() < view.cx - 3 * half_w
        assert pos[:, 0].max() > view.cx + 3 * half_w
    finally:
        win.document.dirty = False
        win.close()


def test_an_extents_plot_frames_the_drawing_not_the_xline(qapp):
    from core.document import Document
    from formats.pdf_out import build_graphics_scene, scene_extents

    document = Document.new()
    msp = document.modelspace()
    msp.add_line((0, 0), (100, 50))
    msp.add_xline((50, 25), (1, 0))
    scene = build_graphics_scene(document)
    rect = scene_extents(scene)
    assert rect.width() < 102 and rect.height() < 52
    assert scene.itemsBoundingRect().width() > 500     # it is drawn, long
