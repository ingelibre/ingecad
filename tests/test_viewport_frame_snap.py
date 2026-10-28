# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A viewport's frame snaps on the sheet, as in AutoCAD.

Rafael's seventh review (25:45-26:45): placing a second viewport, he could
not snap to the first one's corner -- the snap found the title block's
midpoint behind it -- and the two viewports ended up overlapping 2.5 mm.
"""
from __future__ import annotations

import pytest

from core import layouts


def _sheet(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    psp = win.document.doc.layouts.get("Layout1")
    psp.add_line((0, 190), (267, 190))                 # the title block's edge
    win.tools._execute(layouts.AddViewportCommand(
        "Layout1", (78, 110), (116, 160), (0, 0), 160))
    win._refresh_layout_tabs()
    win.switch_layout("Layout1")
    qapp.processEvents()
    return win


def test_mview_snaps_to_the_corner_of_the_viewport_beside_it(qapp):
    win = _sheet(qapp)
    try:
        t = win.tools
        t.osnap_on = True
        t.osnap_modes = {"END", "MID", "INT"}
        win.dispatcher.submit("MVIEW")
        t.on_hover(136.3, 189.8, threshold_world=3.0)
        assert t.snap_hit is not None and t.snap_hit.kind == "END"
        assert (t.snap_hit.x, t.snap_hit.y) == pytest.approx((136.0, 190.0))
        t.on_hover(136.4, 110.2, threshold_world=3.0)  # middle of its right edge
        assert t.snap_hit.kind == "MID"
        assert (t.snap_hit.x, t.snap_hit.y) == pytest.approx((136.0, 110.0))
        t.cancel()
        win.dispatcher.cancel()
    finally:
        win.document.dirty = False
        win.close()


def test_the_sheets_main_viewport_does_not_snap(qapp):
    """The main viewport stands for the paper view itself, not a window."""
    win = _sheet(qapp)
    try:
        layout = win.document.doc.layouts.get("Layout1")
        shown = layouts.visible_viewports(layout)
        every = [e for e in layout if e.dxftype() == "VIEWPORT"]
        main = [vp for vp in every if vp not in shown]
        from core.snap import SnapEngine

        engine = SnapEngine(win.document, space=layout)
        engine._build()
        frames = 4 * len(shown)
        assert len(engine._segs) == frames + 1, (len(engine._segs), len(main))
    finally:
        win.document.dirty = False
        win.close()
