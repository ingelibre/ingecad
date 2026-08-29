# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Editing on a layout tab — the sheet is a space like any other.

AutoCAD: "Commands operate in either model space or paper space" (MSPACE,
reference p. 1213). A title block, its lines and its text are paper-space
objects, so every draw/edit/snap/pick path has to reach them exactly as it
reaches the model — and must NOT reach across the two spaces.
"""
from __future__ import annotations

import ezdxf
import numpy as np
import pytest
from ezdxf.math import Matrix44

from core import actions
from core.commands import History
from core.document import Document
from core.select import GeometryIndex
from core.snap import SnapEngine


def make_doc() -> Document:
    """An A1 sheet with a title block, plus something in the model."""
    doc = ezdxf.new("R2018")
    doc.modelspace().add_line((0, 0), (100, 100))
    psp = doc.layouts.get("Layout1")
    psp.add_lwpolyline([(10, 10), (830, 10), (830, 584), (10, 584)],
                       close=True)
    psp.add_line((600, 10), (600, 80))
    psp.add_text("PLANO", dxfattribs={"height": 5, "insert": (620, 40)})
    psp.add_viewport(center=(300, 300), size=(400, 300),
                     view_center_point=(0, 0), view_height=100)
    return Document(doc)


# -- the current space ---------------------------------------------------------

def test_current_space_follows_the_active_layout():
    document = make_doc()
    assert document.current_space() is document.doc.modelspace()
    assert document.space_name == "Model"
    document.active_layout = "Layout1"
    assert document.current_space() is document.doc.layouts.get("Layout1")
    assert document.space_name == "Layout1"
    document.active_layout = None
    assert document.current_space() is document.doc.modelspace()


def test_a_deleted_layout_falls_back_to_the_model():
    document = make_doc()
    document.active_layout = "Ghost"          # never existed
    assert document.current_space() is document.doc.modelspace()
    assert document.active_layout is None     # and it stops asking


# -- picking, both ways --------------------------------------------------------

def test_the_sheet_is_pickable_and_the_model_is_not():
    document = make_doc()
    document.active_layout = "Layout1"
    index = GeometryIndex(document)
    frame = index.pick((830.0, 300.0), tolerance=2.0)        # sheet frame
    assert frame is not None
    assert document.doc.entitydb.get(frame).dxftype() == "LWPOLYLINE"
    # A model line crosses paper coordinates (50, 50); selecting across
    # spaces is exactly what AutoCAD does not allow.
    assert index.pick((50.0, 50.0), tolerance=2.0) is None

    # and the inverse: on the Model tab the sheet is unreachable
    document.active_layout = None
    index = GeometryIndex(document)
    assert index.pick((50.0, 50.0), tolerance=2.0) is not None
    assert index.pick((830.0, 300.0), tolerance=2.0) is None


def test_a_viewport_is_picked_by_its_border_only():
    document = make_doc()
    document.active_layout = "Layout1"
    index = GeometryIndex(document)
    vp = [e for e in document.current_space() if e.dxftype() == "VIEWPORT"][0]
    assert index.pick((300.0, 150.0), tolerance=2.0) == vp.dxf.handle
    assert index.pick((300.0, 300.0), tolerance=2.0) is None   # inside


def test_window_selection_catches_sheet_objects():
    document = make_doc()
    document.active_layout = "Layout1"
    index = GeometryIndex(document)
    hits = index.window((590.0, 5.0, 700.0, 90.0))
    kinds = sorted(document.doc.entitydb.get(h).dxftype() for h in hits)
    assert kinds == ["LINE", "TEXT"]      # both sit fully inside the rect


def test_snap_reaches_a_title_block_corner():
    document = make_doc()
    document.active_layout = "Layout1"
    engine = SnapEngine(document)
    hit = engine.find((830.0, 584.0), 5.0, kinds=frozenset({"END"}))
    assert hit is not None and (hit.x, hit.y) == (830.0, 584.0)
    # the model's endpoints are not offered on the sheet
    assert engine.find((100.0, 100.0), 5.0,
                       kinds=frozenset({"END"})) is None


# -- editing -------------------------------------------------------------------

def test_move_on_the_sheet_leaves_the_model_alone():
    document = make_doc()
    document.active_layout = "Layout1"
    history = History()
    history.document = document
    text = document.current_space().query("TEXT")[0]
    model_before = [(e.dxf.start.x, e.dxf.start.y)
                    for e in document.doc.modelspace()]
    history.execute(actions.TransformCommand(
        "MOVE", [text], Matrix44.translate(-10, 0, 0)))
    assert text.dxf.insert.x == pytest.approx(610.0)
    history.undo()
    assert text.dxf.insert.x == pytest.approx(620.0)
    assert [(e.dxf.start.x, e.dxf.start.y)
            for e in document.doc.modelspace()] == model_before


def test_erase_on_the_sheet_removes_from_the_layout():
    document = make_doc()
    document.active_layout = "Layout1"
    history = History()
    history.document = document
    line = document.current_space().query("LINE")[0]
    history.execute(actions.EraseCommand([line]))
    assert not document.current_space().query("LINE")
    assert len(document.doc.modelspace()) == 1      # untouched
    history.undo()
    assert len(document.current_space().query("LINE")) == 1


def test_a_new_entity_is_born_on_the_sheet():
    document = make_doc()
    document.active_layout = "Layout1"
    history = History()
    history.document = document
    before_model = len(document.doc.modelspace())
    history.execute(actions.AddEntityCommand(
        "LINE", lambda space: space.add_line((20, 20), (40, 40))))
    assert len(document.current_space().query("LINE")) == 2
    assert len(document.doc.modelspace()) == before_model


# -- what must NOT follow the tab ----------------------------------------------

def test_model_extents_ignore_the_active_layout():
    """MVIEW fits a viewport to the MODEL, whatever tab is current."""
    from core import layouts as layout_ops

    document = make_doc()
    document.active_layout = "Layout1"
    box = layout_ops._model_extents(document)
    assert box is not None
    x0, y0, x1, y1 = box
    # the model line, not the 830x584 sheet
    assert (x0, y0, x1, y1) == pytest.approx((0.0, 0.0, 100.0, 100.0))


def test_build_scene_model_renders_the_model_from_a_layout_tab():
    from render.backend import build_scene

    document = make_doc()
    document.active_layout = "Layout1"
    scene = build_scene(document, "Model")
    assert scene.layout_name is None


# -- the overlay colour trap ---------------------------------------------------

def _overlay_colours(document, entities):
    """The RGBA the overlay would paint these entities with."""
    from render.backend import build_scene_for_entities

    scene = build_scene_for_entities(document, entities, 0.1)
    data = scene.lines.data
    assert len(data), "the overlay drew nothing"
    return {tuple(int(c) for c in row) for row in data["rgba"]}


def test_a_line_drawn_on_the_sheet_is_not_white_on_white():
    """draw_entities never sets a layout, so the overlay used to keep
    ezdxf's dark-model defaults: ACI 7 resolved to WHITE, and a line drawn
    on the white sheet was invisible until the next full regen."""
    document = make_doc()
    document.active_layout = "Layout1"
    line = document.current_space().add_line((20, 20), (40, 40))
    assert _overlay_colours(document, [line]) == {(0, 0, 0, 255)}

    # The inverse, which is what makes the assertion above mean something:
    # the SAME ACI 7 line on the dark model canvas comes out white.
    document.active_layout = None
    model_line = document.doc.modelspace().add_line((20, 20), (40, 40))
    assert _overlay_colours(document, [model_line]) == {(255, 255, 255, 255)}


# -- through the real window ---------------------------------------------------

def _wait_regen(qapp, win, timeout_s=20.0):
    import time

    t0 = time.monotonic()
    while win._regen_worker is not None and time.monotonic() - t0 < timeout_s:
        qapp.processEvents()


def _window(qapp):
    """A window on a drawing with a title block on Layout1."""
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    win.document.doc.modelspace().add_line((0, 0), (100, 100))
    psp = win.document.doc.layouts.get("Layout1")
    psp.add_lwpolyline([(10, 10), (830, 10), (830, 584), (10, 584)],
                       close=True)
    psp.add_text("PLANO", dxfattribs={"height": 5, "insert": (620, 40)})
    vp = psp.add_viewport(center=(300, 300), size=(400, 300),
                          view_center_point=(0, 0), view_height=100)
    win._refresh_layout_tabs()
    qapp.processEvents()
    return win, win.tools, vp


def test_switching_tabs_moves_the_pick_index_to_the_sheet(qapp):
    win, t, _vp = _window(qapp)
    try:
        win.switch_layout("Layout1")
        _wait_regen(qapp, win)
        assert win.document.active_layout == "Layout1"
        t._pick_tolerance = 2.0
        t.on_click(830.0, 300.0)                 # the title block frame
        assert t.selection, "the sheet frame did not select"
        picked = t.index.entity(next(iter(t.selection)))
        assert picked.dxftype() == "LWPOLYLINE"

        win.switch_layout("Model")
        _wait_regen(qapp, win)
        assert win.document.active_layout is None
        assert not t.selection, "a selection crossed the space boundary"
        t._pick_tolerance = 2.0
        t.on_click(50.0, 50.0)                   # the model line
        assert t.selection
        assert t.index.entity(next(iter(t.selection))).dxftype() == "LINE"
    finally:
        win.close()


def test_editing_tools_run_on_a_layout_tab(qapp):
    win, t, vp = _window(qapp)
    try:
        win.switch_layout("Layout1")
        _wait_regen(qapp, win)
        t.start_tool("MOVE")
        assert t.active(), "MOVE was refused on the sheet"
        t.cancel()

        # ... and inside a viewport too, where they reach the MODEL through
        # its projection (see tests/test_mspace_editing.py). What flips is
        # the sheet's OWN commands: a viewport is made on the paper.
        win._activate_viewport(vp)
        t.start_tool("MOVE")
        assert t.active(), "MOVE was refused inside a viewport"
        t.cancel()
        t.start_tool("MVIEW")
        assert not t.active()
    finally:
        win.close()


def test_a_sheet_edit_survives_undo_through_the_window(qapp):
    win, t, _vp = _window(qapp)
    try:
        win.switch_layout("Layout1")
        _wait_regen(qapp, win)
        text = win.document.current_space().query("TEXT")[0]
        t._execute(actions.TransformCommand(
            "MOVE", [text], Matrix44.translate(0, 25, 0)))
        assert text.dxf.insert.y == pytest.approx(65.0)
        win._cmd_undo()
        assert text.dxf.insert.y == pytest.approx(40.0)
    finally:
        win.close()


def test_warm_caches_built_for_another_space_are_discarded(qapp):
    """A tab switch does NOT bump document.revision (the per-tab scene cache
    depends on that), so the revision alone cannot tell a warmer that its
    caches describe the wrong space."""
    win, t, _vp = _window(qapp)
    try:
        win.switch_layout("Layout1")
        _wait_regen(qapp, win)
        document = win.document
        t._invalidate_geometry()
        stale = GeometryIndex(document)
        stale._build()
        engine = SnapEngine(document)
        engine._build()

        t._on_caches_warm(document, stale, engine, document.revision, "Model")
        assert t.index is not stale, "a Model-tab index was adopted on a sheet"

        # control: the same payload, correctly labelled, IS adopted
        t._on_caches_warm(document, stale, engine, document.revision,
                          "Layout1")
        assert t.index is stale
    finally:
        win.close()


def test_erasing_a_viewport_forces_a_regen(qapp):
    win, t, vp = _window(qapp)
    try:
        win.switch_layout("Layout1")
        _wait_regen(qapp, win)
        command = actions.EraseCommand([vp])
        assert t._touches_viewport(command)
        # and the ordinary case does not pay for it
        text = win.document.current_space().query("TEXT")[0]
        assert not t._touches_viewport(actions.EraseCommand([text]))
    finally:
        win.close()


def test_double_click_edits_sheet_text_before_entering_a_viewport(qapp):
    win, t, vp = _window(qapp)
    try:
        win.switch_layout("Layout1")
        _wait_regen(qapp, win)
        t._pick_tolerance = 2.0
        opened = []
        t.open_text_editor_for = lambda e: (opened.append(e), True)[1]

        # the title block's text sits OUTSIDE the viewport rectangle
        win.on_canvas_double_click(622.0, 42.0)
        assert opened and opened[0].dxftype() == "TEXT"
        assert win._active_vp is None, "the text lost to the viewport rule"

        # empty paper inside the viewport still enters it (AutoCAD's rule)
        win.on_canvas_double_click(300.0, 300.0)
        assert win._active_vp is vp
    finally:
        win.close()


def test_the_in_place_editor_opens_for_every_text_kind_on_the_sheet(qapp):
    """The editor itself, not the routing to it.

    The routing test above stubs ``open_text_editor_for`` out, so nothing
    ever ran it on a real entity — and it asked every one of them for
    ``line_spacing_factor``, which only MTEXT has: double-clicking a
    single-line TEXT raised DXFAttributeError and no editor appeared. A
    title block is mostly single-line text, so on a colleague's sheet the
    text was the one thing that would not edit.
    """
    win, t, _vp = _window(qapp)
    try:
        psp = win.document.doc.layouts.get("Layout1")
        block = win.document.doc.blocks.new("TB")
        block.add_attdef("SHEET", insert=(0, 0), text="A01",
                         dxfattribs={"height": 5})
        insert = psp.add_blockref("TB", (700, 40))
        insert.add_auto_attribs({"SHEET": "A01"})
        attrib = insert.attribs[0]
        attdef = block.query("ATTDEF")[0]
        mtext = psp.add_mtext("PLANIMETRIA", dxfattribs={
            "char_height": 5, "insert": (620, 60)})
        text = psp.query("TEXT")[0]
        win.switch_layout("Layout1")
        _wait_regen(qapp, win)

        for entity in (text, mtext, attrib, attdef):
            t._mtext_editor = None
            assert t.open_text_editor_for(entity), entity.dxftype()
            editor = t._mtext_editor
            assert editor is not None, entity.dxftype()
            # it opens ON the text, carrying what the text says
            assert editor.edit.toPlainText().startswith(
                "PLANIMETRIA" if entity.dxftype() == "MTEXT"
                else ("PLANO" if entity is text else "A01")), entity.dxftype()
            editor.cancel(ask=False)

        # and the inverse: a kind DDEDIT does not edit is declined, so the
        # double-click falls through to the layout's enter/leave rule
        t._mtext_editor = None
        assert not t.open_text_editor_for(psp.query("LWPOLYLINE")[0])
        assert t._mtext_editor is None
    finally:
        win.close()


def test_editing_a_sheet_text_writes_it_and_undo_puts_it_back(qapp):
    """Single-line text edits end to end, on the sheet, through history."""
    win, t, _vp = _window(qapp)
    try:
        win.switch_layout("Layout1")
        _wait_regen(qapp, win)
        text = win.document.doc.layouts.get("Layout1").query("TEXT")[0]
        assert text.dxf.text == "PLANO"

        assert t.open_text_editor_for(text)
        t._mtext_editor.edit.setPlainText("PLANTA GENERAL")
        t._mtext_editor.commit()
        qapp.processEvents()
        assert text.dxf.text == "PLANTA GENERAL"

        win.history.undo()
        qapp.processEvents()
        assert text.dxf.text == "PLANO"
    finally:
        win.close()


# -- a viewport is an object you can move and scale ----------------------------

def _viewport(document):
    return [e for e in document.current_space() if e.dxftype() == "VIEWPORT"][0]


def test_moving_a_viewport_takes_its_picture_along():
    """ezdxf refuses to transform a VIEWPORT; a user still moves one."""
    document = make_doc()
    document.active_layout = "Layout1"
    history = History()
    history.document = document
    vp = _viewport(document)
    view_before = (vp.dxf.view_center_point.x, vp.dxf.view_center_point.y,
                   float(vp.dxf.view_height))
    history.execute(actions.TransformCommand(
        "MOVE", [vp], Matrix44.translate(50, 20, 0)))
    assert (vp.dxf.center.x, vp.dxf.center.y) == pytest.approx((350.0, 320.0))
    assert (float(vp.dxf.width), float(vp.dxf.height)) == (400.0, 300.0)
    # the view is untouched: the same model area travels with the window
    assert (vp.dxf.view_center_point.x, vp.dxf.view_center_point.y,
            float(vp.dxf.view_height)) == pytest.approx(view_before)
    history.undo()
    assert (vp.dxf.center.x, vp.dxf.center.y) == pytest.approx((300.0, 300.0))


def test_scaling_a_viewport_halves_the_frame_and_keeps_the_view():
    """The A1 -> A3 case: half the sheet, half the picture on it."""
    document = make_doc()
    document.active_layout = "Layout1"
    history = History()
    history.document = document
    vp = _viewport(document)
    height_before = float(vp.dxf.view_height)
    history.execute(actions.TransformCommand(
        "SCALE", [vp], Matrix44.scale(0.5, 0.5, 1.0)))
    assert (float(vp.dxf.width), float(vp.dxf.height)) == (200.0, 150.0)
    assert (vp.dxf.center.x, vp.dxf.center.y) == pytest.approx((150.0, 150.0))
    # view_height untouched => the same model area, drawn half the size,
    # which IS what scaling the object means
    assert float(vp.dxf.view_height) == height_before
    history.undo()
    assert (float(vp.dxf.width), float(vp.dxf.height)) == (400.0, 300.0)


def test_a_viewport_is_left_alone_by_a_rotation():
    document = make_doc()
    document.active_layout = "Layout1"
    history = History()
    history.document = document
    vp = _viewport(document)
    line = document.current_space().query("LINE")[0]
    command = actions.TransformCommand("ROTATE", [vp, line],
                                       Matrix44.z_rotate(0.5))
    history.execute(command)
    assert [e.dxftype() for e in command.skipped] == ["VIEWPORT"]
    assert (float(vp.dxf.width), float(vp.dxf.height)) == (400.0, 300.0)
    assert line.dxf.end.x != pytest.approx(600.0)   # the line DID rotate
    history.undo()
    assert line.dxf.end.x == pytest.approx(600.0)


# -- undo does not follow the user to another tab ------------------------------

def _sheet_and_model(document):
    return (len(list(document.doc.layouts.get("Layout1"))),
            len(document.doc.modelspace()))


def test_undo_puts_a_sheet_object_back_on_the_sheet():
    """The command asks "which space?" once, when it runs. Asking again at
    undo time answers about the tab the user is on NOW, and an ERASE on a
    sheet undone from the Model tab used to resurrect the object in the
    modelspace."""
    document = make_doc()
    document.active_layout = "Layout1"
    history = History()
    history.document = document
    line = document.current_space().query("LINE")[0]
    sheet0, model0 = _sheet_and_model(document)
    history.execute(actions.EraseCommand([line]))
    assert _sheet_and_model(document) == (sheet0 - 1, model0)

    document.active_layout = None            # the user clicks the Model tab
    history.undo()
    assert _sheet_and_model(document) == (sheet0, model0)


def test_undo_and_redo_of_a_sheet_draw_survive_a_tab_switch():
    document = make_doc()
    document.active_layout = "Layout1"
    history = History()
    history.document = document
    sheet0, model0 = _sheet_and_model(document)
    history.execute(actions.AddEntityCommand(
        "LINE", lambda space: space.add_line((20, 20), (40, 40))))
    assert _sheet_and_model(document) == (sheet0 + 1, model0)

    document.active_layout = None
    history.undo()
    assert _sheet_and_model(document) == (sheet0, model0)
    history.redo()
    assert _sheet_and_model(document) == (sheet0 + 1, model0), (
        "redo from another tab added the object to the wrong space")


def test_undo_of_a_model_edit_from_a_sheet_stays_in_the_model():
    document = make_doc()
    history = History()
    history.document = document
    sheet0, model0 = _sheet_and_model(document)
    history.execute(actions.AddEntityCommand(
        "LINE", lambda space: space.add_line((1, 1), (2, 2))))
    assert _sheet_and_model(document) == (sheet0, model0 + 1)
    document.active_layout = "Layout1"
    history.undo()
    assert _sheet_and_model(document) == (sheet0, model0)
