# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Dashes show in a drawing in metres, on screen and on paper.

ezdxf stretches every dash, gap and dot to 0.1 drawing units -- 10 cm in a
drawing in metres -- so HIDDEN and DASHDOT at the linetype scale such a
drawing needs came out identical and without dots (a YouTuber's staircase
plan, reproduced in IngeCAD: 5 pieces each instead of hundreds).
"""
from __future__ import annotations

from core.document import Document


def _sheet():
    document = Document.new()
    doc = document.doc
    from core.commands import History
    from core.linetypes import LoadLinetypesCommand

    History(document).execute(LoadLinetypesCommand(
        [n for n in ("HIDDEN", "DASHDOT") if n not in doc.linetypes]))
    msp = document.modelspace()
    msp.add_line((0, -0.7), (2, -0.7),
                 dxfattribs={"linetype": "HIDDEN", "ltscale": 0.0035})
    msp.add_line((0, -0.8), (2, -0.8),
                 dxfattribs={"linetype": "DASHDOT", "ltscale": 0.0035})
    msp.add_line((0, 0), (2, 1))          # some extent
    return document


def _pieces(scene, y):
    return sum(1 for item in scene.items()
               if round(item.sceneBoundingRect().center().y(), 3) == y)


def test_the_plot_draws_every_dash_and_dot(qapp):
    from formats import pdf_out

    scene = pdf_out.build_graphics_scene(_sheet(), None, "")
    assert _pieces(scene, -0.7) > 40           # 60 dashes in 2 m; 5 before
    assert _pieces(scene, -0.8) > _pieces(scene, -0.7) * 0.5


def test_the_screen_floor_follows_the_drawing_not_a_unit():
    from render.backend import frontend_config

    document = _sheet()
    config = frontend_config(1e-4, document)
    assert config.min_dash_length <= 1e-4
