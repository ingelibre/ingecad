# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The model THROUGH a floating viewport (MSPACE): navigation only.

The third state of a layout tab (see
``docs/reference/layout/autocad-editing-in-paperspace.md``): the canvas keeps
showing the sheet, one viewport is current, and the wheel, pan, ZOOM (nXP,
Extents, Window) and VPLOCK act on that viewport's view of the model. Nothing
is picked, snapped or drawn through it -- Marco's decision of 2026-09-28,
measured: the pick index and snap engine of a real plan's model cost 2 s of
GIL on every double-click and left the GUI mute for 0.4 s, for a way of
editing that his flow never uses (draw in Model, compose and plot on sheets).

The projection still crosses two layers, and each test says which:
  * what the mouse gives is PAPER and has to arrive as MODEL (the coordinate
    readout, ZOOM Window, the click that makes another viewport current);
  * what the model answers has to be drawn on PAPER (the live view, the
    crosshair clipped to the frame).
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


def test_the_projection_honours_the_view_target_and_the_display_frame():
    """Group 12/22 is the view centre in DISPLAY coordinates relative to the
    view target (17/27), a WCS point. Read raw as a WCS point it was only
    right with no twist and a zero target -- and eight of the thirty
    viewports of a colleague's plan carry a UTM target and a view centre of
    (-528 160, -8 572 730): the model "under the window" was half a
    million units off, so nothing could be picked, snapped or edited
    through them. The truth is ezdxf's own transformation matrix."""
    from ezdxf.math import Vec3

    doc = ezdxf.new("R2018")
    psp = doc.layouts.get("Layout1")
    for target, twist in (((529876.1, 8573039.2, 0.0), 0.0),
                          ((1155.6, 304.2, 4.0), 60.0),
                          ((0.0, 0.0, -1000.0), 0.0),
                          ((10.0, -20.0, 0.0), 720.0)):
        vp = psp.add_viewport(center=(150, 100), size=(200, 120),
                              view_center_point=(-528160.0, -8572729.9),
                              view_height=600)
        vp.dxf.view_target_point = target
        vp.dxf.view_twist_angle = twist
        matrix = vp.get_transformation_matrix()
        inverse = matrix.copy()
        inverse.inverse()
        for paper in ((150, 100), (250, 160), (37.5, 41.25)):
            truth = inverse.transform(Vec3(paper[0], paper[1], 0))
            ours = layout_ops.paper_to_model(vp, *paper)
            assert ours == pytest.approx((truth.x, truth.y), abs=1e-6), (
                f"target {target} twist {twist}: paper {paper}")
            assert layout_ops.model_to_paper(vp, *ours) == pytest.approx(paper)
        # the writers that hold a MODEL point convert it back to group 12/22
        wanted = (1234.5, -67.8)
        vp.dxf.view_center_point = layout_ops.dcs_view_center(vp, wanted)
        assert layout_ops.view_centre_wcs(vp) == pytest.approx(wanted)
        assert layout_ops.paper_to_model(vp, 150, 100) == pytest.approx(wanted)


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


def test_a_click_inside_the_viewport_selects_nothing(qapp):
    """A viewport navigates; it does not pick the model through the paper."""
    win, t, vp = _window(qapp)
    try:
        _enter(qapp, win, vp)
        t._pick_tolerance = 2.0
        t.on_click(160.0, 100.0)          # paper: the middle of the model line
        assert not t.selection, "the model line selected through the viewport"

        # The inverse: the sheet's own click still selects the sheet's own
        # entities, or the rule above could be "clicks never select".
        win._deactivate_viewport()
        t._pick_tolerance = 2.0
        t.on_click(622.0, 42.0)           # the title block text
        assert t.selection
    finally:
        win.close()


def test_entering_a_viewport_builds_no_caches_and_keeps_the_sheets(qapp):
    """The lag Marco felt on the double-click: the warmer that indexed the
    whole model for editing. Nothing is edited there now, so nothing is
    built -- and the sheet's own index survives the round trip."""
    win, t, vp = _window(qapp)
    try:
        win.switch_layout("Layout1")
        _wait_regen(qapp, win)
        while t._warmers:
            qapp.processEvents()
        t._pick_tolerance = 2.0
        t.on_click(622.0, 42.0)           # builds/uses the sheet's index
        assert t.selection
        sheet_index = t.index
        assert sheet_index is not None and not sheet_index._dirty

        win._activate_viewport(vp)
        assert not t._warmers, "a cache warmer started on entering a viewport"
        assert not t.selection, "the selection crossed into MSPACE"
        assert t.index is sheet_index and not sheet_index._dirty

        win._deactivate_viewport()
        assert not t._warmers, "leaving rebuilt the sheet's caches"
        assert t.index is sheet_index and not sheet_index._dirty
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


def test_a_double_click_on_the_bare_paper_leaves_the_viewport(qapp):
    """Even where the projection would land on a model text: outside the
    active viewport's frame the double-click is the paper's, and the
    paper's double-click is PSPACE. The text's editor opened instead, and
    the tester could not find the way out."""
    win, t, vp = _window(qapp)
    try:
        # a model MTEXT whose projection falls on the bare paper at (400, 100)
        mx, my = layout_ops.paper_to_model(vp, 400.0, 100.0)
        win.document.doc.modelspace().add_mtext(
            "FUERA", dxfattribs={"char_height": 50, "insert": (mx, my)})
        _enter(qapp, win, vp)
        t._invalidate_geometry()
        opened = []
        win.tools.open_text_editor_for = lambda e: opened.append(e) or True
        win.on_canvas_double_click(400.0, 100.0)
        assert not opened, "the model text's editor opened through the paper"
        assert win._active_vp is None, "PSPACE"
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


def test_drawing_commands_are_refused_inside_a_viewport(qapp):
    win, t, vp = _window(qapp)
    try:
        _enter(qapp, win, vp)
        before = len(win.document.doc.modelspace())
        said = []
        win.command_line.echo = lambda text, *a, **k: said.append(text)
        t.start_tool("LINE")
        assert not t.active(), "LINE ran inside a viewport"
        assert said and "not available inside a viewport" in said[-1]
        t.on_click(150.0, 100.0)
        t.on_click(170.0, 100.0)
        assert len(win.document.doc.modelspace()) == before
        assert not [e for e in win.document.doc.layouts.get("Layout1")
                    if e.dxftype() == "LINE"]

        # the inverse: the same command runs on the sheet once the
        # viewport is left
        win._deactivate_viewport()
        t.start_tool("LINE")
        assert t.active()
        t.cancel()
    finally:
        win.close()


def test_entering_a_viewport_ends_the_sheets_running_command(qapp):
    """A LINE started on the sheet cannot collect points inside a viewport
    (they would be model points); the double-click ends it, like Esc."""
    win, t, vp = _window(qapp)
    try:
        win.switch_layout("Layout1")
        _wait_regen(qapp, win)
        t.start_tool("LINE")
        assert t.active()
        win._activate_viewport(vp)
        assert not t.active(), "the sheet's command survived into MSPACE"
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


def test_hovering_inside_a_viewport_snaps_to_nothing(qapp):
    """No tool can run there, so no snap engine for the model is built:
    the hover neither snaps nor pays the model walk."""
    win, t, vp = _window(qapp)
    try:
        _enter(qapp, win, vp)
        t.osnap_on = True
        t.osnap_modes = {"END"}
        # (the sheet's warmer may already hold a model engine: the SHEET
        # snaps through its viewports; that is paper-space work, kept)
        engine_before = t.snap_engine
        model_before = t._model_snap_engine
        t.on_hover(170.3, 100.2, 2.0)   # paper (170, 100) = model (5100, 3000)
        assert t.snap_hit is None
        assert t.snap_engine is engine_before, "a snap engine was built"
        assert t._model_snap_engine is model_before, "a model engine was built"
        # the readout still speaks model units through the projection
        assert t._cursor == pytest.approx((5101.5, 3001.0))
    finally:
        win.close()


def test_every_command_is_refused_inside_a_viewport_with_the_way_out(qapp):
    win, t, vp = _window(qapp)
    try:
        _enter(qapp, win, vp)
        said = []
        win.command_line.echo = lambda text, *a, **k: said.append(text)
        for name in ("MOVE", "MVIEW", "ERASE", "COPY"):
            t.start_tool(name)
            assert not t.active(), f"{name} ran inside a viewport"
            assert "PSPACE" in said[-1] and "Model tab" in said[-1], said[-1]
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


def test_a_double_click_on_a_model_text_inside_the_viewport_opens_nothing(qapp):
    """The double-click's edit action belongs to the sheet's own objects;
    a model text seen through the viewport is not edited from here."""
    win, t, vp = _window(qapp)
    try:
        mx, my = layout_ops.paper_to_model(vp, 200.0, 120.0)   # inside the frame
        win.document.doc.modelspace().add_mtext(
            "DENTRO", dxfattribs={"char_height": 50, "insert": (mx, my)})
        _enter(qapp, win, vp)
        opened = []
        win.tools.open_text_editor_for = lambda e: opened.append(e) or True
        win.on_canvas_double_click(200.0, 120.0)
        assert not opened, "a model text opened its editor through the viewport"
        assert win._active_vp is vp, "the viewport stayed current"
    finally:
        win.close()


def test_the_live_model_is_shared_by_every_sheet(qapp):
    """One tessellation of the model serves every layout tab: keyed per
    sheet, each tab switch rebuilt the whole model (2.3 s on a real plan)
    for identical vertices."""
    from views.main_window import _LiveSceneWorker

    win, t, vp = _window(qapp)
    try:
        doc = win.document.doc
        doc.layouts.new("Layout2")
        win._refresh_layout_tabs()
        win.switch_layout("Layout1")
        _wait_regen(qapp, win)
        worker = getattr(win, "_vp_live_worker", None)
        while worker is not None and worker.isRunning():
            qapp.processEvents()
        qapp.processEvents()
        scene = win._vp_model_scene_ready()
        assert scene is not None, "no live model after the sheet's regen"

        win.switch_layout("Layout2")
        _wait_regen(qapp, win)
        assert win._vp_model_scene_ready() is scene, "Layout2 rebuilt the model"
        worker = getattr(win, "_vp_live_worker", None)
        assert worker is None or not worker.isRunning()

        # the inverse: a model edit does drop it
        win.invalidate_vp_model_cache()
        assert win._vp_model_cache is None
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



def test_zoom_window_on_the_sheet_snaps_to_paper_geometry(qapp):
    """#80 on a layout: ZOOM Window on the sheet takes its corners with
    object snaps, here the ends of a paper line."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    win, t, vp = _window(qapp)
    try:
        psp = win.document.doc.layouts.get("Layout1")
        psp.add_line((300, 20), (380, 60))
        win.switch_layout("Layout1")
        _wait_regen(qapp, win)
        edit = win.command_line.input
        for text in ("ZOOM", "W"):
            edit.setFocus()
            QTest.keyClicks(edit, text)
            QTest.keyClick(edit, Qt.Key_Return)
        assert t.tool is not None and t.tool.name == "ZOOMWINDOW"
        t.osnap_on = True
        t.osnap_modes = {"END"}
        for x, y in ((300.6, 20.4), (379.5, 59.6)):
            t.on_hover(x, y, threshold_world=2.0)
            assert t.snap_hit is not None and t.snap_hit.kind == "END"
            t.on_click(x, y)
        x0, y0, x1, y1 = win.viewport._view_world_rect()
        assert ((x0 + x1) / 2, (y0 + y1) / 2) == pytest.approx((340, 40))
    finally:
        win.document.dirty = False
        win.close()
