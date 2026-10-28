# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""What TRIM, BREAK, OFFSET, JOIN and PEDIT hand back is the same object.

They build new entities from 2D points, so a contour at elevation 3500
came back at 0 -- the survey plugin's contours lost their heights -- and a
0.5-wide polyline came back hairline. AutoCAD gives back the object,
shortened, with its elevation, thickness and width.
"""
from __future__ import annotations

from core import modify
from core.commands import History
from core.document import Document


def _contour(msp, points, **extra):
    attribs = {"elevation": 3500.0, "const_width": 0.5, "thickness": 2.0}
    attribs.update(extra)
    return msp.add_lwpolyline(points, dxfattribs=attribs)


def _body(poly):
    return (poly.dxf.get("elevation"), poly.dxf.get("const_width"),
            poly.dxf.get("thickness"))


def test_break_and_join_keep_elevation_width_and_thickness():
    document = Document.new()
    history = History(document)
    msp = document.modelspace()
    contour = _contour(msp, [(0, 0), (10, 0), (20, 0)])
    command = modify.break_entity(contour, (4, 0), (6, 0))
    history.execute(command)
    assert [_body(p) for p in command.new_entities] == [(3500.0, 0.5, 2.0)] * 2
    line = msp.add_line((0, 5, 100), (10, 5, 100))
    command = modify.break_entity(line, (4, 5), (6, 5))
    history.execute(command)
    assert {p.dxf.start.z for p in command.new_entities} == {100.0}
    a = _contour(msp, [(0, 50), (10, 50)])
    b = _contour(msp, [(10, 50), (20, 55)])
    result = modify.join_entities([a, b])
    command = result[0] if isinstance(result, tuple) else result
    history.execute(command)
    assert [_body(p) for p in command.new_entities] == [(3500.0, 0.5, 2.0)]


def test_trim_and_offset_keep_a_contours_height(qapp):
    from core import actions
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    t = win.tools
    t._execute(actions.add_line((10, -5), (10, 5)))          # the edge
    t._execute(actions.add_polyline([(0, 0), (20, 0)]))
    contour = next(e for e in win.document.modelspace()
                   if e.dxftype() == "LWPOLYLINE")
    contour.dxf.elevation = 3500.0
    contour.dxf.const_width = 0.5
    t.osnap_on = False
    win._on_command_submitted("TRIM")
    win._on_command_submitted("")              # every object is an edge
    t.on_hover(15, 0, threshold_world=0.3)
    t.on_click(15, 0)
    t.cancel()
    piece = next(e for e in win.document.modelspace()
                 if e.dxftype() == "LWPOLYLINE")
    assert piece.get_points("xy")[-1][0] == 10.0, "TRIM did not cut"
    assert (piece.dxf.get("elevation"), piece.dxf.get("const_width")) \
        == (3500.0, 0.5)
    for text in ("OFFSET", "2"):
        win._on_command_submitted(text)
    t.on_click(5, 0)
    t.on_click(5, 5)
    t.cancel()
    offsets = [e for e in win.document.modelspace()
               if e.dxftype() == "LWPOLYLINE" and e is not piece]
    assert offsets and offsets[0].dxf.get("elevation") == 3500.0
    win.document.dirty = False
    win.close()


def test_pedit_reverse_keeps_the_widths():
    document = Document.new()
    arrow = document.modelspace().add_lwpolyline(
        [(0, 0, 0, 1, 0), (10, 0, 0.5, 0.5, 0), (20, 0, 0, 0, 0)],
        format="xyseb")
    modify.apply_pedit(arrow, "reverse")
    assert [tuple(r)[2:4] for r in arrow.get_points("xyseb")] \
        == [(0.5, 0.5), (1.0, 0.0), (0.0, 0.0)]
    modify.apply_pedit(arrow, "reverse")
    assert [tuple(r)[2:4] for r in arrow.get_points("xyseb")] \
        == [(0.0, 1.0), (0.5, 0.5), (0.0, 0.0)]
