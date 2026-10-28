# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A polyline being drawn snaps to its own segments, as in AutoCAD.

PLINE keeps its vertices inside the tool until the command ends -- the
LWPOLYLINE is made then -- so the object snaps, which search the drawing,
never saw them: closing on the start point by Endpoint showed no marker
(Marco's recording, 2026-10-09; most likely what the user in Bolivia
reported as "OSNAP on PLINE"). The tool now hands its drawn segments to
the snap search while it runs.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def pline(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    t = win.tools
    t.ortho_on = t.polar_on = t.otrack_on = False
    t.osnap_on = True
    t.osnap_modes = {"END", "MID", "INT", "NEA"}
    for answer in ("PLINE", "0,0", "10,0", "10,10"):
        win._on_command_submitted(answer)
    assert t.tool is not None and t.tool.name == "PLINE"
    yield win, t
    win.document.dirty = False
    win.close()


def test_the_start_point_snaps_to_close_the_polyline(qapp, pline):
    win, t = pline
    t.on_hover(0.3, 0.2, threshold_world=1.0)
    assert t.snap_hit is not None and t.snap_hit.kind == "END"
    assert (t.snap_hit.x, t.snap_hit.y) == (0.0, 0.0)
    assert t.resolved_point(0.3, 0.2) == (0.0, 0.0)


def test_a_drawn_segment_offers_its_midpoint(qapp, pline):
    win, t = pline
    t.on_hover(5.2, 0.3, threshold_world=1.0)
    assert t.snap_hit is not None and t.snap_hit.kind == "MID"
    assert (t.snap_hit.x, t.snap_hit.y) == (5.0, 0.0)


def test_the_rubber_band_is_not_geometry(qapp, pline):
    """The segment from the last point to the cursor is a preview: its
    midpoint must not pull the cursor."""
    win, t = pline
    t.on_hover(10.0, 20.0, threshold_world=1.0)    # band (10,10)-(10,20)
    t.on_hover(10.3, 15.0, threshold_world=1.0)    # near the band's middle
    assert t.snap_hit is None or (t.snap_hit.x, t.snap_hit.y) != (10.0, 15.0)


def test_closing_by_the_snap_makes_a_closed_shape(qapp, pline):
    win, t = pline
    t.on_hover(0.3, 0.2, threshold_world=1.0)
    t.on_click(*t.resolved_point(0.3, 0.2))
    win._on_command_submitted("")                  # Enter ends PLINE
    pl = [e for e in win.document.modelspace() if e.dxftype() == "LWPOLYLINE"][-1]
    pts = [tuple(p[:2]) for p in pl.get_points()]
    assert pts[0] == (0.0, 0.0) and pts[-1] == (0.0, 0.0)
