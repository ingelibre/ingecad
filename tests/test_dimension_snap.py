# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A dimension snaps through what it draws, as in AutoCAD.

Rafael's seventh review (16:36-16:45): to check the standard's 8 mm from
the part to the arrow tip he measured with DIST -- "no me coge aquí el
puntito" -- and picked the tip by eye: no object snap reached a dimension.
"""
from __future__ import annotations

import pytest

from core import actions


def _window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    qapp.processEvents()
    return win


def test_dist_from_the_part_to_the_arrow_tip_measures_eight(qapp):
    win = _window(qapp)
    try:
        t = win.tools
        t._execute(actions.add_line((0, 0), (40, 0)))           # the part
        t._execute(actions.dim_linear((0, 0), (40, 0), (20, -8)))
        t.osnap_on = True
        t.osnap_modes = {"END", "MID", "NOD"}
        win.dispatcher.submit("DIST")
        # a metre drawing at 1:100: the arrow is 0.25 long, the aperture ~0.1
        t.on_hover(0.02, 0.03, threshold_world=0.1)
        t.on_click(0.02, 0.03)                                   # the part's end
        t.on_hover(0.04, -7.96, threshold_world=0.1)
        assert t.snap_hit is not None and t.snap_hit.kind == "END"
        assert (t.snap_hit.x, t.snap_hit.y) == pytest.approx((0.0, -8.0))
        t.on_click(0.04, -7.96)
        shown = win.command_line.history.toPlainText()
        assert "8.0" in shown.split("Distance")[-1] or "8,0" in shown, shown[-300:]
    finally:
        win.document.dirty = False
        win.close()


def test_a_dimension_line_offers_its_midpoint_and_its_definition_points(qapp):
    from core.snap import SnapEngine

    win = _window(qapp)
    try:
        win.tools._execute(actions.dim_linear((0, 0), (40, 0), (20, -8)))
        engine = SnapEngine(win.document)
        mid = engine.find((20.0, -8.1), 1.0, kinds=frozenset({"MID"}))
        assert mid is not None and (mid.x, mid.y) == pytest.approx((20.0, -8.0))
        node = engine.find((40.2, 0.1), 1.0, kinds=frozenset({"NOD"}))
        assert node is not None and (node.x, node.y) == pytest.approx((40.0, 0.0))
    finally:
        win.document.dirty = False
        win.close()
