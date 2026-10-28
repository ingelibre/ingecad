# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Point style, PDMODE and PDSIZE (#69, Rafael's review 6): a POINT was all
but invisible -- no way to choose its symbol or size, and a size relative to
the screen drew it one unit wide. The snap must still go to the point."""
from __future__ import annotations

import pytest

from core import points
from core.commands import History
from core.document import Document
from render.backend import build_scene


def _drawing(mode, size, view_height=None):
    document = Document.new()
    document.doc.header["$PDMODE"] = mode
    document.doc.header["$PDSIZE"] = size
    document.modelspace().add_point((100, 50))
    if view_height is not None:
        document.point_view_height = view_height
    return document


def _symbol_width(document) -> float:
    bounds = build_scene(document, "Model").lines.bounds     # one row per stroke
    return float(bounds[:, 2].max() - bounds[:, 0].min())


def test_an_absolute_size_is_drawing_units():
    # style 32 is a circle alone: its diameter IS the point size
    assert _symbol_width(_drawing(32, 10.0)) == pytest.approx(10.0, abs=0.5)


@pytest.mark.parametrize("size, percent", [(-10.0, 10.0), (0.0, 5.0)])
def test_a_size_relative_to_the_screen_follows_the_view(size, percent):
    # ezdxf drew these 1 unit wide; AutoCAD: -N is N % of the view height,
    # 0 is 5 %
    width = _symbol_width(_drawing(32, size, view_height=400.0))
    assert width == pytest.approx(400.0 * percent / 100.0, abs=1.0)


def test_snap_goes_to_the_point_not_to_its_symbol():
    # Rafael saw another CAD snap to the ends of the symbol's strokes
    from core.snap import SnapEngine

    document = _drawing(3, 10.0)            # an X
    engine = SnapEngine(document)
    hit = engine.find((101.0, 51.0), 3.0)
    assert hit is not None and (hit.x, hit.y) == pytest.approx((100.0, 50.0))
    assert hit.kind == "NOD"
    # the X's tips (about 10 away) are no snap targets
    assert engine.find((110.0, 60.0), 2.0) is None


def test_the_dialog_stores_a_relative_size_negative_and_undo_restores():
    document = _drawing(0, 0.0)
    history = History(document)
    history.execute(points.set_point_style_command(35, -7.5))
    assert (points.pdmode(document.doc), points.pdsize(document.doc)) == (35, -7.5)
    history.undo()
    assert (points.pdmode(document.doc), points.pdsize(document.doc)) == (0, 0.0)


def test_pdmode_and_ddptype_from_the_command_line(qapp):
    from views.main_window import MainWindow
    from views.point_style_dialog import PointStyleDialog

    win = MainWindow()
    win.new_document()
    try:
        win._on_command_submitted("PDMODE")
        win._on_command_submitted("34")
        assert points.pdmode(win.document.doc) == 34
        win._on_command_submitted("PDSIZE")
        win._on_command_submitted("-5")
        assert points.pdsize(win.document.doc) == -5.0
        dialog = PointStyleDialog(win, win.document.doc)
        assert dialog.shapes.checkedId() == 34 and dialog.relative.isChecked()
        assert dialog.values() == (34, -5.0)
        win._cmd_undo()
        assert points.pdsize(win.document.doc) == 0.0
    finally:
        win.document.dirty = False
        win.close()
