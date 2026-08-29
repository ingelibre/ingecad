# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Editing the model THROUGH a floating viewport (MSPACE).

The third state of a layout tab (see
``docs/reference/layout/autocad-editing-in-paperspace.md``): the canvas keeps
showing the sheet, one viewport is current, and every command edits the
modelspace through that viewport's projection.

Two directions have to hold at once, and each test says which:
  * what the mouse gives is PAPER and has to arrive as MODEL (picking,
    snapping, the points a tool collects);
  * what the tools answer is MODEL and has to be drawn on PAPER (highlight,
    grips, previews, the GL overlay).
"""
from __future__ import annotations

import math

import ezdxf
import pytest

from core import layouts as layout_ops


# -- the projection itself (no GUI) --------------------------------------------

def _sheet_doc():
    doc = ezdxf.new("R2018")
    doc.modelspace().add_line((5000, 3000), (5100, 3000))
    psp = doc.layouts.get("Layout1")
    psp.add_viewport(center=(150, 100), size=(200, 120),
                     view_center_point=(5000, 3000), view_height=600)
    return doc


def test_the_projection_round_trips_both_ways():
    vp = _sheet_doc().layouts.get("Layout1").query("VIEWPORT")[0]
    assert layout_ops.viewport_scale(vp) == pytest.approx(0.2)
    for paper in ((150, 100), (250, 160), (50, 40), (123.5, 77.25)):
        model = layout_ops.paper_to_model(vp, *paper)
        back = layout_ops.model_to_paper(vp, *model)
        assert back == pytest.approx(paper)
    # the centre of the frame is the centre of the view, by definition
    assert layout_ops.paper_to_model(vp, 150, 100) == pytest.approx((5000, 3000))
    # and a paper millimetre is 1/scale model units to the right
    east = layout_ops.paper_to_model(vp, 151, 100)
    assert east[0] - 5000.0 == pytest.approx(5.0)


def test_a_twisted_viewport_turns_the_projection_and_still_round_trips():
    vp = _sheet_doc().layouts.get("Layout1").query("VIEWPORT")[0]
    vp.dxf.view_twist_angle = 30.0
    model = layout_ops.paper_to_model(vp, 250, 160)
    assert layout_ops.model_to_paper(vp, *model) == pytest.approx((250, 160))
    # the inverse test: the twist has to MOVE the answer, or the rotation
    # code could be missing entirely and this file would not notice
    vp.dxf.view_twist_angle = 0.0
    straight = layout_ops.paper_to_model(vp, 250, 160)
    assert not math.isclose(straight[0], model[0], rel_tol=1e-9)


def test_a_viewport_without_a_usable_view_states_no_projection():
    vp = _sheet_doc().layouts.get("Layout1").query("VIEWPORT")[0]
    vp.dxf.view_height = 0.0        # degenerate: nothing can be derived
    assert layout_ops.viewport_view(vp) is None
    assert layout_ops.paper_to_model(vp, 150, 100) is None
    assert layout_ops.viewport_placement(vp) is None


def _overlay_colours(document, entities, canvas=None):
    """The RGBA the overlay would paint these entities with."""
    from render.backend import build_scene_for_entities

    scene = build_scene_for_entities(document, entities, 0.1, canvas)
    data = scene.lines.data
    assert len(data), "the overlay drew nothing"
    return {tuple(int(c) for c in row) for row in data["rgba"]}


def test_a_line_drawn_inside_a_viewport_is_not_white_on_white():
    """The v0.4.6 bug, one space deeper. There the overlay resolved against
    the model while drawing on the sheet; here the entity really IS the
    model's -- but it is still drawn on the white sheet, so ACI 7 has to
    come out black. Measured on the real plan: a line drawn through a
    viewport was pure white (255,255,255) over black sheet content.
    """
    from core.document import Document

    doc = _sheet_doc()
    document = Document(doc)
    line = doc.modelspace().add_line((5000, 3000), (5100, 3050))
    sheet = doc.layouts.get("Layout1")
    assert _overlay_colours(document, [line], canvas=sheet) == {(0, 0, 0, 255)}

    # The inverse: the SAME model line, drawn on the model's own dark
    # canvas, is white. Without this the assertion above would also pass
    # with the colour rule deleted.
    assert _overlay_colours(document, [line]) == {(255, 255, 255, 255)}


# -- through the window --------------------------------------------------------

def _wait_regen(qapp, win, timeout_s=20.0):
    import time

    t0 = time.monotonic()
    while win._regen_worker is not None and time.monotonic() - t0 < timeout_s:
        qapp.processEvents()


def _window(qapp):
    """A sheet with a title block, a viewport at 1:5, and a model line.

    The model line runs from (5000, 3000) to (5100, 3000): paper (150, 100)
    to (170, 100) through the viewport.
    """
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    msp = win.document.doc.modelspace()
    msp.add_line((5000, 3000), (5100, 3000))
    psp = win.document.doc.layouts.get("Layout1")
    psp.add_text("PLANO", dxfattribs={"height": 5, "insert": (620, 40)})
    vp = psp.add_viewport(center=(150, 100), size=(200, 120),
                          view_center_point=(5000, 3000), view_height=600)
    win._refresh_layout_tabs()
    qapp.processEvents()
    return win, win.tools, vp


def _enter(qapp, win, vp):
    win.switch_layout("Layout1")
    _wait_regen(qapp, win)
    win._activate_viewport(vp)
    qapp.processEvents()


def test_entering_a_viewport_makes_the_model_the_current_space(qapp):
    win, t, vp = _window(qapp)
    try:
        win.switch_layout("Layout1")
        _wait_regen(qapp, win)
        assert win.document.current_space() is win.document.doc.layouts.get(
            "Layout1"), "the sheet is current before MSPACE"

        win._activate_viewport(vp)
        assert win.document.current_space() is win.document.doc.modelspace()
        assert win.document.active_layout is None
        assert win._active_layout == "Layout1", "the TAB does not change"

        win._deactivate_viewport()
        assert win.document.current_space() is win.document.doc.layouts.get(
            "Layout1")
    finally:
        win.close()


def test_a_click_inside_the_viewport_picks_the_model_through_it(qapp):
    win, t, vp = _window(qapp)
    try:
        _enter(qapp, win, vp)
        t._pick_tolerance = 2.0
        t.on_click(160.0, 100.0)          # paper: the middle of the model line
        assert t.selection, "the model line did not select through the viewport"
        picked = t.index.entity(next(iter(t.selection)))
        assert picked.dxftype() == "LINE"
        assert picked.dxf.start.x == pytest.approx(5000.0)

        # The inverse: the SAME paper point on the sheet selects nothing of
        # the model -- no selection crosses the two spaces.
        win._deactivate_viewport()
        t._pick_tolerance = 2.0
        t.on_click(160.0, 100.0)
        assert not t.selection
    finally:
        win.close()


def test_a_click_on_the_bare_paper_selects_nothing_inside_mspace(qapp):
    win, t, vp = _window(qapp)
    try:
        _enter(qapp, win, vp)
        t._pick_tolerance = 2.0
        # (620, 40) is the title block text, far outside the viewport frame:
        # through the projection it would mean a model point the viewport
        # does not even show.
        t.on_click(622.0, 42.0)
        assert not t.selection
        assert win._active_vp is vp, "the viewport stayed current"
    finally:
        win.close()


def test_a_click_in_another_viewport_makes_that_one_current(qapp):
    win, t, vp = _window(qapp)
    try:
        psp = win.document.doc.layouts.get("Layout1")
        other = psp.add_viewport(center=(600, 300), size=(200, 120),
                                 view_center_point=(5000, 3000),
                                 view_height=600)
        _enter(qapp, win, vp)
        t.on_click(600.0, 300.0)
        assert win._active_vp is other
        assert win.viewport.space_placement["rect"] == layout_ops.viewport_rect(
            other)
    finally:
        win.close()


def test_drawing_in_a_viewport_lands_in_the_model_at_model_coordinates(qapp):
    win, t, vp = _window(qapp)
    try:
        _enter(qapp, win, vp)
        before = len(win.document.doc.modelspace())
        t.start_tool("LINE")
        assert t.active(), "LINE was refused inside a viewport"
        t.osnap_on = False                  # a bare coordinate, not a snap
        t.on_click(150.0, 100.0)            # model (5000, 3000)
        t.on_click(170.0, 100.0)            # model (5100, 3000)
        t.cancel()
        msp = win.document.doc.modelspace()
        assert len(msp) == before + 1, "the line did not land in the model"
        line = msp[-1]
        assert line.dxftype() == "LINE"
        assert (line.dxf.start.x, line.dxf.start.y) == pytest.approx(
            (5000.0, 3000.0))
        assert (line.dxf.end.x, line.dxf.end.y) == pytest.approx(
            (5100.0, 3000.0))
        # and nothing was added to the sheet
        assert not [e for e in win.document.doc.layouts.get("Layout1")
                    if e.dxftype() == "LINE"]
    finally:
        win.close()


def test_undoing_a_viewport_edit_reaches_the_model_from_the_sheet(qapp):
    """The v0.4.6 lesson, one space deeper: a command asks "which space?"
    once, when it runs -- never again at undo time, when the answer may have
    changed under it."""
    win, t, vp = _window(qapp)
    try:
        _enter(qapp, win, vp)
        t.start_tool("LINE")
        t.osnap_on = False
        t.on_click(150.0, 100.0)
        t.on_click(170.0, 100.0)
        t.cancel()
        msp = win.document.doc.modelspace()
        added = len(msp)

        win._deactivate_viewport()          # back to the sheet, then undo
        win._cmd_undo()
        assert len(msp) == added - 1, "undo did not reach the model"
    finally:
        win.close()


def test_the_canvas_draws_model_answers_on_the_paper(qapp):
    """The other direction: what the tool layer answers is model, and the
    canvas has to put it where the viewport shows it."""
    win, t, vp = _window(qapp)
    try:
        _enter(qapp, win, vp)
        canvas = win.viewport
        for model in ((5000.0, 3000.0), (5100.0, 3050.0), (4900.0, 2950.0)):
            a, b, c, d, tx, ty = canvas.space_affine()
            paper = (a * model[0] + b * model[1] + tx,
                     c * model[0] + d * model[1] + ty)
            assert paper == pytest.approx(layout_ops.model_to_paper(vp, *model))
            assert canvas._space_to_screen(*model) == pytest.approx(
                canvas.view.world_to_screen(*paper))
        # a model unit is scale times smaller on the sheet
        assert canvas._space_scale() == pytest.approx(
            canvas.view.scale * layout_ops.viewport_scale(vp))

        # The inverse test: on the sheet the same calls are the identity, or
        # the two directions could be swapped and every assert above would
        # still pass.
        win._deactivate_viewport()
        assert canvas.space_affine() == (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        assert canvas._space_to_screen(5000.0, 3000.0) == pytest.approx(
            canvas.view.world_to_screen(5000.0, 3000.0))
        assert canvas._space_scale() == pytest.approx(canvas.view.scale)
    finally:
        win.close()


def test_snapping_inside_a_viewport_finds_model_geometry(qapp):
    win, t, vp = _window(qapp)
    try:
        _enter(qapp, win, vp)
        t.start_tool("LINE")
        t.osnap_on = True
        t.osnap_modes = {"END"}
        # paper (170, 100) is the model line's endpoint (5100, 3000); hover
        # a hair off it, in paper units, as the mouse would
        t.on_hover(170.3, 100.2, 2.0)
        assert t.snap_hit is not None, "no snap on the model through the viewport"
        assert (t.snap_hit.x, t.snap_hit.y) == pytest.approx((5100.0, 3000.0))
    finally:
        win.close()


def test_the_sheets_own_commands_still_belong_to_paper_space(qapp):
    win, t, vp = _window(qapp)
    try:
        _enter(qapp, win, vp)
        t.start_tool("MOVE")
        assert t.active(), "MOVE was refused inside a viewport"
        t.cancel()
        t.start_tool("MVIEW")
        assert not t.active(), "MVIEW made a viewport from inside a viewport"
    finally:
        win.close()


def test_the_overlay_of_a_viewport_edit_is_drawn_on_the_sheets_canvas(qapp):
    """The window half of the colour rule: while a viewport is active the
    controller hands the overlay the SHEET as its canvas, not the model."""
    win, t, vp = _window(qapp)
    try:
        _enter(qapp, win, vp)
        canvas = t.canvas_space()
        assert canvas is win.document.doc.layouts.get("Layout1")
        win._deactivate_viewport()
        assert t.canvas_space() is None, "on the sheet the canvas is its own"
    finally:
        win.close()


def test_zoom_window_inside_a_viewport_zooms_that_viewport(qapp):
    """The wheel already zooms the viewport's view; ZOOM Window has to mean
    the same thing while a viewport is current, or the two gestures disagree
    about what "zoom" does."""
    win, t, vp = _window(qapp)
    try:
        _enter(qapp, win, vp)
        before_view = (win.viewport.view.cx, win.viewport.view.cy,
                       win.viewport.view.scale)
        # the left half of the frame, in paper millimetres
        assert win.vp_zoom_window(50.0, 40.0, 150.0, 100.0) is True
        assert (vp.dxf.view_center_point.x,
                vp.dxf.view_center_point.y) == pytest.approx((4750.0, 2850.0))
        assert float(vp.dxf.view_height) == pytest.approx(300.0)
        assert (win.viewport.view.cx, win.viewport.view.cy,
                win.viewport.view.scale) == before_view, "the sheet view moved"

        # and it is one undoable step, like every other view change
        win._cmd_undo()
        assert float(vp.dxf.view_height) == pytest.approx(600.0)

        # on the sheet the same call declines, and the canvas does its own zoom
        win._deactivate_viewport()
        assert win.vp_zoom_window(50.0, 40.0, 150.0, 100.0) is False
    finally:
        win.close()


def test_ctrl_r_cycles_the_current_viewport(qapp):
    win, t, vp = _window(qapp)
    try:
        psp = win.document.doc.layouts.get("Layout1")
        other = psp.add_viewport(center=(600, 300), size=(200, 120),
                                 view_center_point=(5000, 3000),
                                 view_height=600)
        _enter(qapp, win, vp)
        seen = []
        for _ in range(4):
            win.cycle_active_viewport()
            seen.append(win._active_vp)
        assert other in seen and vp in seen, seen
        assert seen[0] is not seen[1], "the cycle stood still"
    finally:
        win.close()


def test_the_highlight_of_a_picked_model_entity_lands_inside_the_frame(qapp):
    """The display direction, end to end: pick a model entity through the
    viewport and the pixels its highlight would use have to fall inside the
    viewport's own frame -- not out at the model's coordinates."""
    win, t, vp = _window(qapp)
    try:
        _enter(qapp, win, vp)
        canvas = win.viewport
        canvas.view.zoom_extents(0, 0, 841, 594)     # the whole sheet in view
        t._pick_tolerance = 2.0
        t.on_click(160.0, 100.0)
        assert t.selection
        segs, _circles, _boxes = t.highlight_geometry()
        assert len(segs), "no highlight geometry"
        x0, y0, x1, y1 = layout_ops.viewport_rect(vp)
        fx0, fy0 = canvas.view.world_to_screen(x0, y1)
        fx1, fy1 = canvas.view.world_to_screen(x1, y0)
        for sx, sy, ex, ey in segs[:20]:
            for px, py in (canvas._space_to_screen(sx, sy),
                           canvas._space_to_screen(ex, ey)):
                assert fx0 - 1 <= px <= fx1 + 1, (px, fx0, fx1)
                assert fy0 - 1 <= py <= fy1 + 1, (py, fy0, fy1)
    finally:
        win.close()


def test_the_in_place_text_editor_follows_the_projection(qapp):
    """Editing a model text through a viewport: the floating editor sits
    where the viewport DRAWS the text and is sized in its scale, not at the
    model's own coordinates somewhere off the sheet."""
    from views.mtext_editor import MTextInPlaceEditor

    win, t, vp = _window(qapp)
    try:
        _enter(qapp, win, vp)
        canvas = win.viewport
        canvas.view.zoom_extents(0, 0, 841, 594)
        editor = MTextInPlaceEditor(canvas, top_left=(5000.0, 3000.0),
                                    width_world=50.0, char_height=2.5,
                                    on_commit=lambda *a: None)
        try:
            editor._sync_geometry()
            assert editor._scale() == pytest.approx(canvas._space_scale())
            # the widget sits 2 px up and left of the text corner (its own
            # border), and higher by whatever chrome the toolbar takes
            sx, sy = canvas._space_to_screen(5000.0, 3000.0)
            assert editor.pos().x() == pytest.approx(int(sx) - 2, abs=1)
            assert editor.pos().y() <= sy

            # the inverse: on the sheet it is the plain view again
            win._deactivate_viewport()
            editor._sync_geometry()
            assert editor._scale() == pytest.approx(canvas.view.scale)
        finally:
            editor.deleteLater()
    finally:
        win.close()


def test_the_coordinate_readout_switches_to_model_units(qapp):
    win, t, vp = _window(qapp)
    try:
        _enter(qapp, win, vp)
        win._on_cursor_moved(170.0, 100.0)
        shown = win._coords_label.text()
        assert "5100" in shown, shown
        win._deactivate_viewport()
        win._on_cursor_moved(170.0, 100.0)
        assert "170" in win._coords_label.text()
    finally:
        win.close()
