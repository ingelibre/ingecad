# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Layout tabs, active-layout switching, paper frame math, LAYOUT command."""
from __future__ import annotations

import pytest

from core import layouts as layout_ops
from core.commands import History
from core.document import Document
from render.backend import build_scene


@pytest.fixture
def doc():
    return Document.new()


# -- names / ordering ----------------------------------------------------------

def test_model_first_then_taborder(doc):
    names = layout_ops.layout_names(doc)
    assert names[0] == "Model"
    assert "Layout1" in names


def test_default_new_name_skips_taken(doc):
    assert layout_ops.default_new_name(doc) == "Layout2"
    doc.doc.layouts.new("layout2")   # case-insensitive collision
    assert layout_ops.default_new_name(doc) == "Layout3"


def test_validate_new_name(doc):
    assert layout_ops.validate_new_name(doc, "Sheet A") is None
    assert layout_ops.validate_new_name(doc, "") is not None
    assert layout_ops.validate_new_name(doc, "LAYOUT1") is not None  # dup
    assert layout_ops.validate_new_name(doc, "bad/name") is not None
    assert layout_ops.validate_new_name(doc, "x" * 256) is not None


# -- switching + $TILEMODE -----------------------------------------------------

def test_switch_active_sets_tilemode_and_block(doc):
    doc.doc.layouts.new("Sheet")
    layout_ops.switch_active(doc, "Sheet")
    assert doc.doc.header["$TILEMODE"] == 0
    assert doc.doc.layouts.active_layout().name == "Sheet"
    assert doc.dirty
    layout_ops.switch_active(doc, "Model")
    assert doc.doc.header["$TILEMODE"] == 1
    # the paperspace active marker is untouched by going back to Model
    assert doc.doc.layouts.active_layout().name == "Sheet"


def test_startup_tab_honors_tilemode(doc):
    assert layout_ops.startup_tab(doc) is None
    layout_ops.switch_active(doc, "Layout1")
    assert layout_ops.startup_tab(doc) == "Layout1"
    layout_ops.switch_active(doc, "Model")
    assert layout_ops.startup_tab(doc) is None


# -- commands (undo/redo) ------------------------------------------------------

def test_new_layout_command_undo(doc):
    history = History(doc)
    history.execute(layout_ops.NewLayoutCommand("Sheet2"))
    assert "Sheet2" in layout_ops.layout_names(doc)
    history.undo()
    assert "Sheet2" not in layout_ops.layout_names(doc)
    history.redo()
    assert "Sheet2" in layout_ops.layout_names(doc)


def test_rename_layout_command_undo(doc):
    history = History(doc)
    history.execute(layout_ops.RenameLayoutCommand("Layout1", "Planta"))
    assert "Planta" in layout_ops.layout_names(doc)
    assert "Layout1" not in layout_ops.layout_names(doc)
    history.undo()
    assert "Layout1" in layout_ops.layout_names(doc)


def test_delete_layout_rules(doc):
    from ezdxf.lldxf.const import DXFValueError

    with pytest.raises(DXFValueError):
        layout_ops.delete_layout(doc, "Model")
    with pytest.raises(DXFValueError):
        layout_ops.delete_layout(doc, "Layout1")   # last paperspace layout
    doc.doc.layouts.new("Extra")
    layout_ops.delete_layout(doc, "Extra")
    assert "Extra" not in layout_ops.layout_names(doc)


# -- paper frame ---------------------------------------------------------------

def test_paper_frame_a4_landscape(doc):
    layout = doc.doc.layouts.get("Layout1")
    layout.dxf.paper_width = 297.0
    layout.dxf.paper_height = 210.0
    layout.dxf.left_margin = 10.0
    layout.dxf.bottom_margin = 5.0
    layout.dxf.right_margin = 10.0
    layout.dxf.top_margin = 5.0
    layout.dxf.plot_rotation = 0
    layout.dxf.plot_paper_units = 1
    layout.dxf.plot_origin_x_offset = 0.0
    layout.dxf.plot_origin_y_offset = 0.0
    frame = layout_ops.paper_frame(layout)
    # paperspace origin = lower-left of the printable area
    assert frame["sheet"] == (-10.0, -5.0, 287.0, 205.0)
    assert frame["printable"] == (0.0, 0.0, 277.0, 200.0)


def test_paper_frame_rotation_swaps(doc):
    layout = doc.doc.layouts.get("Layout1")
    layout.dxf.paper_width = 210.0
    layout.dxf.paper_height = 297.0
    layout.dxf.left_margin = 1.0
    layout.dxf.bottom_margin = 2.0
    layout.dxf.right_margin = 3.0
    layout.dxf.top_margin = 4.0
    layout.dxf.plot_rotation = 1     # 90 CCW: portrait paper shown landscape
    frame = layout_ops.paper_frame(layout)
    x0, y0, x1, y1 = frame["sheet"]
    assert (x1 - x0, y1 - y0) == (297.0, 210.0)
    # margins rotate with the sheet: left <- top, bottom <- left
    assert (x0, y0) == (-4.0, -1.0)


def test_paper_frame_inches_and_garbage(doc):
    layout = doc.doc.layouts.get("Layout1")
    layout.dxf.plot_paper_units = 0            # inches
    layout.dxf.paper_width = 279.4             # stored in mm always (11")
    layout.dxf.paper_height = 215.9            # 8.5"
    layout.dxf.left_margin = 25.4
    layout.dxf.bottom_margin = 0.0
    layout.dxf.right_margin = 0.0
    layout.dxf.top_margin = 0.0
    frame = layout_ops.paper_frame(layout)
    x0, y0, x1, y1 = frame["sheet"]
    assert (x1 - x0, y1 - y0) == pytest.approx((11.0, 8.5))
    assert x0 == pytest.approx(-1.0)
    # corrupt page setup falls back to a default sheet, never nothing
    layout.dxf.paper_width = 0.0
    frame = layout_ops.paper_frame(layout)
    x0, y0, x1, y1 = frame["sheet"]
    assert (x1 - x0, y1 - y0) == (420.0, 297.0)


# -- build_scene integration ---------------------------------------------------

def test_explicit_model_never_falls_back(doc):
    # empty modelspace + content in Layout1 + saved on the layout tab
    doc.doc.layouts.get("Layout1").add_line((0, 0), (10, 10))
    layout_ops.switch_active(doc, "Layout1")
    scene = build_scene(doc)                   # auto: honors $TILEMODE
    assert scene.layout_name == "Layout1"
    assert scene.paper is not None
    assert scene.background is not None
    scene = build_scene(doc, "Model")          # explicit tab click
    assert scene.layout_name is None
    assert scene.paper is None


def test_layout_scene_carries_paper(doc):
    scene = build_scene(doc, "Layout1")
    assert scene.layout_name == "Layout1"
    assert scene.paper is not None and "sheet" in scene.paper


def test_paper_vertices_shapes():
    from views.viewport import _paper_vertices

    paper = {"sheet": (-10.0, -5.0, 287.0, 205.0),
             "printable": (0.0, 0.0, 277.0, 200.0)}
    tris, lines = _paper_vertices(paper, (100.0, 50.0))
    assert len(tris) == 12                     # shadow + sheet quads
    assert len(lines) >= 8                     # border + margin dashes
    assert len(lines) % 2 == 0
    # origin subtracted: sheet corner lands at (-110, -55)
    xs = tris["pos"][:, 0]
    assert xs.min() == pytest.approx(-110.0, abs=6.0)  # shadow may extend


# -- LAYOUT command flow -------------------------------------------------------

def drive(doc, history, *inputs, current="Model"):
    echoes: list[str] = []
    switches: list[str] = []
    prompt = layout_ops.layout_command(
        doc, history,
        switch=switches.append,
        echo=echoes.append,
        refresh=lambda: None,
        current=lambda: current,
        args=(),
    )
    for text in inputs:
        assert prompt is not None, f"no prompt left for input {text!r}"
        prompt = prompt.on_input(text)
    return echoes, switches, prompt


def test_layout_command_new_and_default_name(doc):
    history = History(doc)
    echoes, _s, prompt = drive(doc, history, "N", "")
    assert prompt is None
    assert "Layout2" in layout_ops.layout_names(doc)
    assert any("Layout2" in e for e in echoes)
    history.undo()
    assert "Layout2" not in layout_ops.layout_names(doc)


def test_layout_command_set_and_question(doc):
    history = History(doc)
    _e, switches, _p = drive(doc, history, "S", "layout1")
    assert switches == ["Layout1"]             # case-insensitive match
    echoes, _s, _p = drive(doc, history, "?")
    assert any("Layout1" in e for e in echoes)


def test_layout_command_enter_defaults_to_set(doc):
    history = History(doc)
    _e, switches, _p = drive(doc, history, "", "")
    assert switches == ["Layout1"]             # <set> then default layout


def test_layout_command_rename_flow(doc):
    history = History(doc)
    echoes, _s, prompt = drive(doc, history, "R", "Layout1", "Planta")
    assert prompt is None
    assert "Planta" in layout_ops.layout_names(doc)
    # renaming Model is refused
    echoes, _s, _p = drive(doc, history, "R", "Model")
    assert any("Model" in e for e in echoes)


def test_layout_command_delete_guards(doc):
    history = History(doc)
    echoes, _s, _p = drive(doc, history, "D", "Layout1")
    assert any("last layout" in e for e in echoes)
    doc.doc.layouts.new("Extra")
    echoes, _s, _p = drive(doc, history, "D", "Extra")
    assert "Extra" not in layout_ops.layout_names(doc)


def test_layout_command_inline_args(doc):
    history = History(doc)
    echoes: list[str] = []
    prompt = layout_ops.layout_command(
        doc, history,
        switch=lambda n: None,
        echo=echoes.append,
        refresh=lambda: None,
        current=lambda: "Model",
        args=("N", "Sheet9"),
    )
    assert prompt is None
    assert "Sheet9" in layout_ops.layout_names(doc)


def test_layout_alias_lo():
    from core.aliases import DEFAULT_ALIASES, resolve

    assert resolve("LO", DEFAULT_ALIASES) == "LAYOUT"


# -- viewports (MVIEW) ---------------------------------------------------------

def _doc_with_model_content():
    doc = Document.new()
    msp = doc.modelspace()
    msp.add_line((0, 0), (100, 50))
    msp.add_circle((50, 25), 20)
    return doc


def test_viewport_content_renders_in_layout_scene():
    doc = _doc_with_model_content()
    psp = doc.doc.layouts.get("Layout1")
    psp.add_viewport(center=(148, 105), size=(200, 140),
                     view_center_point=(50, 25), view_height=70)
    scene = build_scene(doc, "Layout1")
    # model line + circle re-projected into paper coordinates + the border
    assert scene.lines.vertex_count > 300
    x0, y0, x1, y1 = scene.extents
    assert x1 - x0 <= 210.0 and y1 - y0 <= 150.0   # clipped to the viewport


def test_viewport_border_is_drawn_and_owned():
    doc = _doc_with_model_content()
    psp = doc.doc.layouts.get("Layout1")
    vp = psp.add_viewport(center=(100, 100), size=(80, 60),
                          view_center_point=(50, 25), view_height=70)
    scene = build_scene(doc, "Layout1")
    ranges = scene.handle_ranges.get(vp.dxf.handle)
    assert ranges, "viewport border must be attributed to the VIEWPORT handle"
    # the border is 4 segments = 8 line vertices
    assert sum(count for _b, _f, count in ranges) >= 8


def test_add_viewport_command_undo():
    doc = _doc_with_model_content()
    history = History(doc)
    command = layout_ops.viewport_from_corners(
        doc, "Layout1", (20, 20), (220, 160))
    history.execute(command)
    psp = doc.doc.layouts.get("Layout1")
    vps = [e for e in psp if e.dxftype() == "VIEWPORT"]
    assert len(vps) == 1
    assert vps[0].dxf.width == pytest.approx(200.0)
    history.undo()
    assert not [e for e in psp if e.dxftype() == "VIEWPORT"]
    assert command.removed_handles
    history.redo()
    assert len([e for e in psp if e.dxftype() == "VIEWPORT"]) == 1


def test_model_fit_view_aspect():
    doc = _doc_with_model_content()
    doc.doc.header["$EXTMIN"] = (0, 0, 0)
    doc.doc.header["$EXTMAX"] = (100, 50, 0)
    # wide viewport (4:1): height-limited by model width / aspect
    center, view_height = layout_ops.model_fit_view(doc, 400.0, 100.0)
    assert center == (50.0, 25.0)
    assert view_height == pytest.approx(50.0 * 1.02)
    # tall viewport (1:2): width-limited -> view_height = mw / aspect
    _c, view_height = layout_ops.model_fit_view(doc, 50.0, 100.0)
    assert view_height == pytest.approx(200.0 * 1.02)


def test_viewport_fit_printable_fills_sheet():
    doc = _doc_with_model_content()
    command = layout_ops.viewport_fit_printable(doc, "Layout1")
    layout = doc.doc.layouts.get("Layout1")
    frame = layout_ops.paper_frame(layout)
    px0, py0, px1, py1 = frame["printable"]
    assert command.size == (pytest.approx(px1 - px0), pytest.approx(py1 - py0))


def test_mview_tool_flow():
    from tools.base import ToolContext
    from tools.layout_tools import MviewTool

    doc = _doc_with_model_content()
    history = History(doc)
    executed = []
    echoes = []
    finished = []

    class FakeServices:
        def paper_context(self):
            return doc, "Layout1"

    def execute(command):
        history.execute(command)
        executed.append(command)

    ctx = ToolContext(
        execute=execute, prompt=echoes.append, echo=echoes.append,
        finish=lambda: finished.append(True), services=FakeServices())

    tool = MviewTool(ctx)
    tool.start()
    tool.on_point((20.0, 20.0))
    tool.on_point((220.0, 160.0))
    assert finished and executed
    psp = doc.doc.layouts.get("Layout1")
    assert len([e for e in psp if e.dxftype() == "VIEWPORT"]) == 1

    # Fit option creates a printable-area viewport
    tool2 = MviewTool(ctx)
    tool2.start()
    assert tool2.on_option("F")
    assert len([e for e in psp if e.dxftype() == "VIEWPORT"]) == 2


def test_mview_alias():
    from core.aliases import DEFAULT_ALIASES, resolve

    assert resolve("MV", DEFAULT_ALIASES) == "MVIEW"


# -- viewport scale (MSPACE + ZOOM nXP) ----------------------------------------

def test_parse_xp_factor():
    assert layout_ops.parse_xp_factor("1/100XP") == pytest.approx(0.01)
    assert layout_ops.parse_xp_factor("0.5xp") == pytest.approx(0.5)
    assert layout_ops.parse_xp_factor("2XP") == pytest.approx(2.0)
    assert layout_ops.parse_xp_factor(" 1/50XP ") == pytest.approx(0.02)
    for bad in ("E", "100", "XP", "0XP", "-1XP", "1/0XP", "abcXP"):
        assert layout_ops.parse_xp_factor(bad) is None


def test_scale_label():
    assert layout_ops.scale_label(0.01) == "1:100"
    assert layout_ops.scale_label(0.02) == "1:50"
    assert layout_ops.scale_label(1.0) == "1:1"
    assert layout_ops.scale_label(2.0) == "2:1"


def test_xp_zoom_sets_exact_scale_and_undoes():
    doc = _doc_with_model_content()
    history = History(doc)
    history.execute(layout_ops.viewport_from_corners(
        doc, "Layout1", (0, 0), (200, 100)))
    psp = doc.doc.layouts.get("Layout1")
    vp = [e for e in psp if e.dxftype() == "VIEWPORT"][0]
    before = float(vp.dxf.view_height)

    history.execute(layout_ops.xp_zoom_command(vp, 0.01))   # ZOOM 1/100XP
    assert float(vp.dxf.view_height) == pytest.approx(100.0 / 0.01)
    assert layout_ops.viewport_scale(vp) == pytest.approx(0.01)
    # scale relation from the reference: paper height / model height
    assert vp.dxf.height / vp.dxf.view_height == pytest.approx(0.01)

    history.undo()
    assert float(vp.dxf.view_height) == pytest.approx(before)
    history.redo()
    assert layout_ops.viewport_scale(vp) == pytest.approx(0.01)


def test_viewport_fit_command_recenters():
    doc = _doc_with_model_content()
    doc.doc.header["$EXTMIN"] = (0, 0, 0)
    doc.doc.header["$EXTMAX"] = (100, 50, 0)
    history = History(doc)
    history.execute(layout_ops.viewport_from_corners(
        doc, "Layout1", (0, 0), (200, 100)))
    psp = doc.doc.layouts.get("Layout1")
    vp = [e for e in psp if e.dxftype() == "VIEWPORT"][0]
    history.execute(layout_ops.xp_zoom_command(vp, 2.0))    # zoom way in
    history.execute(layout_ops.viewport_fit_command(doc, vp))
    assert (vp.dxf.view_center_point.x, vp.dxf.view_center_point.y) \
        == (50.0, 25.0)
    assert float(vp.dxf.view_height) == pytest.approx(50.0 * 1.02)


def test_viewport_hit_topmost():
    doc = _doc_with_model_content()
    psp = doc.doc.layouts.get("Layout1")
    below = psp.add_viewport(center=(100, 100), size=(120, 80),
                             view_center_point=(0, 0), view_height=10)
    above = psp.add_viewport(center=(120, 100), size=(60, 40),
                             view_center_point=(0, 0), view_height=10)
    assert layout_ops.viewport_hit(psp, 120, 100) is above   # overlap: top wins
    assert layout_ops.viewport_hit(psp, 50, 100) is below
    assert layout_ops.viewport_hit(psp, 500, 500) is None
    assert layout_ops.viewport_rect(above) == (90.0, 80.0, 150.0, 120.0)


def test_mspace_pspace_aliases():
    from core.aliases import DEFAULT_ALIASES, resolve

    assert resolve("MS", DEFAULT_ALIASES) == "MSPACE"
    assert resolve("PS", DEFAULT_ALIASES) == "PSPACE"


# -- viewport as selectable entity ---------------------------------------------

def test_viewport_border_hit_edge_only():
    doc = _doc_with_model_content()
    psp = doc.doc.layouts.get("Layout1")
    vp = psp.add_viewport(center=(100, 100), size=(80, 60),
                          view_center_point=(50, 25), view_height=70)
    # on the left border (x=60), inside (center), outside
    assert layout_ops.viewport_border_hit(psp, 60.0, 100.0, 2.0) is vp
    assert layout_ops.viewport_border_hit(psp, 100.0, 100.0, 2.0) is None
    assert layout_ops.viewport_border_hit(psp, 10.0, 10.0, 2.0) is None
    # corner within tolerance
    assert layout_ops.viewport_border_hit(psp, 61.0, 71.0, 2.0) is vp


def test_viewport_grips_layout():
    doc = _doc_with_model_content()
    psp = doc.doc.layouts.get("Layout1")
    vp = psp.add_viewport(center=(100, 100), size=(80, 60),
                          view_center_point=(50, 25), view_height=70)
    grips = layout_ops.viewport_grips(vp)
    assert grips[0] == (60.0, 70.0, "end")
    assert grips[2] == (140.0, 130.0, "end")
    assert grips[4] == (100.0, 100.0, "center")


def test_viewport_move_keeps_view():
    doc = _doc_with_model_content()
    history = History(doc)
    psp = doc.doc.layouts.get("Layout1")
    vp = psp.add_viewport(center=(100, 100), size=(80, 60),
                          view_center_point=(50, 25), view_height=70)
    command = layout_ops.viewport_grip_command(vp, 4, "center", (130.0, 90.0))
    history.execute(command)
    assert (vp.dxf.center.x, vp.dxf.center.y) == (130.0, 90.0)
    assert (vp.dxf.view_center_point.x, vp.dxf.view_center_point.y) == (50.0, 25.0)
    assert float(vp.dxf.view_height) == 70.0
    history.undo()
    assert (vp.dxf.center.x, vp.dxf.center.y) == (100.0, 100.0)


def test_viewport_resize_keeps_scale_and_pins_model():
    doc = _doc_with_model_content()
    history = History(doc)
    psp = doc.doc.layouts.get("Layout1")
    vp = psp.add_viewport(center=(100, 100), size=(80, 60),
                          view_center_point=(50, 25), view_height=30)
    scale = layout_ops.viewport_scale(vp)          # 60/30 = 2.0
    # drag the top-right corner (index 2) outward: opposite corner fixed
    command = layout_ops.viewport_grip_command(vp, 2, "end", (180.0, 150.0))
    history.execute(command)
    assert (vp.dxf.width, vp.dxf.height) == (120.0, 80.0)
    assert layout_ops.viewport_scale(vp) == pytest.approx(scale)
    # model pinned: view center shifted by the paper-center delta / scale
    # old center (100,100) -> new center (120,110): delta (20,10) -> (10,5)
    assert (vp.dxf.view_center_point.x, vp.dxf.view_center_point.y) \
        == (pytest.approx(60.0), pytest.approx(30.0))
    history.undo()
    assert (vp.dxf.width, vp.dxf.height) == (80.0, 60.0)
    assert (vp.dxf.view_center_point.x, vp.dxf.view_center_point.y) \
        == (50.0, 25.0)


def test_viewport_grip_command_degenerate_is_none():
    doc = _doc_with_model_content()
    psp = doc.doc.layouts.get("Layout1")
    vp = psp.add_viewport(center=(100, 100), size=(80, 60),
                          view_center_point=(50, 25), view_height=70)
    # dropping the corner on the opposite corner -> zero-size -> no-op
    assert layout_ops.viewport_grip_command(vp, 2, "end", (60.0, 70.0)) is None
    # dropping the center where it was -> no-op
    assert layout_ops.viewport_grip_command(vp, 4, "center", (100.0, 100.0)) is None


def test_remove_viewport_command_undo():
    doc = _doc_with_model_content()
    history = History(doc)
    psp = doc.doc.layouts.get("Layout1")
    vp = psp.add_viewport(center=(100, 100), size=(80, 60),
                          view_center_point=(50, 25), view_height=70)
    vp.dxf.layer = "0"
    command = layout_ops.RemoveViewportCommand(vp, "Layout1")
    history.execute(command)
    assert not [e for e in psp if e.dxftype() == "VIEWPORT"]
    assert command.removed_handles
    history.undo()
    vps = [e for e in psp if e.dxftype() == "VIEWPORT"]
    assert len(vps) == 1
    assert (vps[0].dxf.center.x, vps[0].dxf.center.y) == (100.0, 100.0)
    assert float(vps[0].dxf.view_height) == 70.0
    assert vps[0].dxf.layer == "0"
    history.redo()
    assert not [e for e in psp if e.dxftype() == "VIEWPORT"]


# -- paper-space selection through the real controller -------------------------

def _layout_window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    win.document.modelspace().add_circle((10, 5), 3)
    psp = win.document.doc.layouts.get("Layout1")
    vp = psp.add_viewport(center=(100, 100), size=(80, 60),
                          view_center_point=(10, 5), view_height=20)
    win._active_layout = "Layout1"     # tab state without waiting for regen
    return win, win.tools, vp


def test_paper_click_selects_viewport_border(qapp):
    win, t, vp = _layout_window(qapp)
    t._pick_tolerance = 2.0
    t.on_click(60.0, 100.0)            # left border
    assert t.paper_vp is vp
    segs, circles, boxes = t.highlight_geometry()
    assert boxes.shape == (1, 4)
    grips = t.grip_points()
    assert len(grips) == 5
    t.on_click(10.0, 10.0)             # empty paper: deselect
    assert t.paper_vp is None
    win.close()


def test_paper_grip_resize_executes_command(qapp):
    win, t, vp = _layout_window(qapp)
    t._pick_tolerance = 2.0
    t.on_click(60.0, 100.0)
    grip = t.grip_at(140.0, 130.0, 3.0)          # top-right corner grip
    assert grip is not None and grip[2] == "end"
    t.begin_grip_drag(grip)
    assert t._grip_drag is not None
    t.update_grip_drag(180.0, 150.0)
    assert win.viewport.vp_drag_rect is not None
    t.finish_grip_drag(180.0, 150.0)
    assert win.viewport.vp_drag_rect is None
    assert (vp.dxf.width, vp.dxf.height) == (120.0, 80.0)
    win._cmd_undo()
    assert (vp.dxf.width, vp.dxf.height) == (80.0, 60.0)
    win.close()


def test_paper_grip_cancel_reverts_nothing(qapp):
    win, t, vp = _layout_window(qapp)
    t._pick_tolerance = 2.0
    t.on_click(60.0, 100.0)
    grip = t.grip_at(100.0, 100.0, 3.0)          # center grip
    t.begin_grip_drag(grip)
    t.update_grip_drag(130.0, 90.0)
    t.cancel()                                    # Esc mid-drag
    assert t._grip_drag is None
    assert win.viewport.vp_drag_rect is None
    assert (vp.dxf.center.x, vp.dxf.center.y) == (100.0, 100.0)
    assert t.paper_vp is vp                       # still selected
    t.cancel()                                    # Esc again: deselect
    assert t.paper_vp is None
    win.close()


def test_paper_delete_selection_removes_viewport(qapp):
    win, t, vp = _layout_window(qapp)
    t._pick_tolerance = 2.0
    t.on_click(60.0, 100.0)
    assert t.delete_selection()
    psp = win.document.doc.layouts.get("Layout1")
    assert not [e for e in psp if e.dxftype() == "VIEWPORT"]
    win._cmd_undo()
    assert len([e for e in psp if e.dxftype() == "VIEWPORT"]) == 1
    win.close()


# -- wheel/pan navigation inside the active viewport ---------------------------

def test_zoom_viewport_view_keeps_anchor_point():
    doc = _doc_with_model_content()
    psp = doc.doc.layouts.get("Layout1")
    vp = psp.add_viewport(center=(100, 100), size=(80, 60),
                          view_center_point=(50, 25), view_height=30)
    # model point under paper anchor (120, 110) before the zoom
    scale = layout_ops.viewport_scale(vp)                    # 2.0
    mx = 50 + (120 - 100) / scale                            # 60.0
    my = 25 + (110 - 100) / scale                            # 30.0
    layout_ops.zoom_viewport_view(vp, 2.0, anchor=(120.0, 110.0))
    assert float(vp.dxf.view_height) == pytest.approx(15.0)  # zoomed in 2x
    new_scale = layout_ops.viewport_scale(vp)                # 4.0
    # the same model point must still sit under the anchor
    assert vp.dxf.view_center_point.x + (120 - 100) / new_scale \
        == pytest.approx(mx)
    assert vp.dxf.view_center_point.y + (110 - 100) / new_scale \
        == pytest.approx(my)


def test_pan_viewport_view_model_follows_cursor():
    doc = _doc_with_model_content()
    psp = doc.doc.layouts.get("Layout1")
    vp = psp.add_viewport(center=(100, 100), size=(80, 60),
                          view_center_point=(50, 25), view_height=30)
    layout_ops.pan_viewport_view(vp, 10.0, -4.0)   # drag right & down
    # scale 2: view center moves the opposite way by delta/scale
    assert vp.dxf.view_center_point.x == pytest.approx(45.0)
    assert vp.dxf.view_center_point.y == pytest.approx(27.0)


def test_vp_gesture_commits_one_undoable_command(qapp):
    win, t, vp = _layout_window(qapp)
    win._active_vp = vp                       # MSPACE on, without regen dance
    before = (vp.dxf.view_center_point.x, vp.dxf.view_center_point.y,
              float(vp.dxf.view_height))
    # a burst of wheel + pan events...
    assert win.vp_view_zoom(1.2, (100.0, 100.0))
    assert win.vp_view_zoom(1.2, (100.0, 100.0))
    assert win.vp_view_pan(5.0, 2.0)
    assert win._vp_gesture is not None
    after = (vp.dxf.view_center_point.x, vp.dxf.view_center_point.y,
             float(vp.dxf.view_height))
    assert after != before
    # ...settles into ONE history entry
    depth = len(win.history._undo)
    win._vp_gesture_commit()
    assert len(win.history._undo) == depth + 1
    assert win._vp_gesture is None
    # undo restores the pre-gesture view in one step
    win._cmd_undo()
    assert (vp.dxf.view_center_point.x, vp.dxf.view_center_point.y,
            float(vp.dxf.view_height)) == pytest.approx(before)
    win._cmd_redo()
    assert (vp.dxf.view_center_point.x, vp.dxf.view_center_point.y,
            float(vp.dxf.view_height)) == pytest.approx(after)
    win.close()


def test_vp_gesture_noop_commits_nothing(qapp):
    win, t, vp = _layout_window(qapp)
    win._active_vp = vp
    win._vp_gesture_begin(vp)
    depth = len(win.history._undo)
    win._vp_gesture_commit()                  # nothing changed
    assert len(win.history._undo) == depth
    win.close()


# -- display lock (VPLOCK) -----------------------------------------------------

def test_viewport_lock_flag_and_command():
    doc = _doc_with_model_content()
    history = History(doc)
    psp = doc.doc.layouts.get("Layout1")
    vp = psp.add_viewport(center=(100, 100), size=(80, 60),
                          view_center_point=(50, 25), view_height=30)
    assert not layout_ops.is_viewport_locked(vp)
    history.execute(layout_ops.SetViewportLockCommand(vp, True))
    assert layout_ops.is_viewport_locked(vp)
    history.undo()
    assert not layout_ops.is_viewport_locked(vp)
    history.redo()
    assert layout_ops.is_viewport_locked(vp)
    # unlocking preserves the other flag bits
    other_flags = int(vp.dxf.flags) & ~0x4000
    history.execute(layout_ops.SetViewportLockCommand(vp, False))
    assert not layout_ops.is_viewport_locked(vp)
    assert (int(vp.dxf.flags) & ~0x4000) == other_flags


def test_locked_viewport_ignores_wheel_and_pan(qapp):
    win, t, vp = _layout_window(qapp)
    win._active_vp = vp
    win.history.execute(layout_ops.SetViewportLockCommand(vp, True))
    view_before = (vp.dxf.view_center_point.x, vp.dxf.view_center_point.y,
                   float(vp.dxf.view_height))
    assert not win.vp_view_zoom(1.2, (100.0, 100.0))   # falls through
    assert not win.vp_view_pan(5.0, 2.0)
    assert (vp.dxf.view_center_point.x, vp.dxf.view_center_point.y,
            float(vp.dxf.view_height)) == view_before
    assert win._vp_gesture is None                     # no gesture opened
    win.close()


def test_locked_viewport_refuses_xp(qapp):
    win, t, vp = _layout_window(qapp)
    win._active_vp = vp
    win.history.execute(layout_ops.SetViewportLockCommand(vp, True))
    height_before = float(vp.dxf.view_height)
    win._zoom_option("1/100XP")
    assert float(vp.dxf.view_height) == height_before
    win._zoom_option("E")
    assert float(vp.dxf.view_height) == height_before
    # unlock through the command surface, then XP works again
    win._cmd_vplock("OFF")
    win._zoom_option("1/100XP")
    assert float(vp.dxf.view_height) == pytest.approx(vp.dxf.height * 100.0)
    win.close()


def test_vplock_targets_selected_viewport(qapp):
    win, t, vp = _layout_window(qapp)
    t._pick_tolerance = 2.0
    t.on_click(60.0, 100.0)                    # select by border, no MSPACE
    assert t.paper_vp is vp
    win._cmd_vplock()                          # toggle -> locked
    assert layout_ops.is_viewport_locked(vp)
    win._cmd_vplock()                          # toggle -> unlocked
    assert not layout_ops.is_viewport_locked(vp)
    win.close()


# -- page setup (PAGESETUP) ----------------------------------------------------

def test_page_setup_command_writes_fields_and_spares_viewports():
    doc = _doc_with_model_content()
    history = History(doc)
    psp = doc.doc.layouts.get("Layout1")
    vp = psp.add_viewport(center=(100, 100), size=(80, 60),
                          view_center_point=(50, 25), view_height=30)
    view_before = (vp.dxf.view_center_point.x, vp.dxf.view_center_point.y,
                   float(vp.dxf.view_height))
    old = layout_ops.effective_page(psp)

    history.execute(layout_ops.page_setup_command(
        psp, 297.0, 210.0, (5.0, 10.0, 5.0, 10.0), "ISO A4"))
    page = layout_ops.effective_page(psp)
    assert (page["width"], page["height"]) == (297.0, 210.0)
    assert page["margins"] == (5.0, 10.0, 5.0, 10.0)
    assert psp.dxf.paper_size.startswith("ISO_A4_")
    assert psp.dxf.plot_rotation == 0
    # THE invariant: the colleague's viewports survive untouched
    vps = [e for e in psp if e.dxftype() == "VIEWPORT"]
    assert len(vps) == 1 and vps[0] is vp
    assert (vp.dxf.view_center_point.x, vp.dxf.view_center_point.y,
            float(vp.dxf.view_height)) == view_before

    history.undo()
    back = layout_ops.effective_page(psp)
    assert (back["width"], back["height"]) == (old["width"], old["height"])
    history.redo()
    assert layout_ops.effective_page(psp)["width"] == 297.0


def test_page_setup_limits_follow_autocad_convention():
    doc = _doc_with_model_content()
    history = History(doc)
    psp = doc.doc.layouts.get("Layout1")
    history.execute(layout_ops.page_setup_command(
        psp, 210.0, 297.0, (5.0, 6.0, 7.0, 8.0)))
    # limits = sheet rect relative to the printable-area corner
    assert tuple(psp.dxf.limmin)[:2] == (-8.0, -7.0)
    assert tuple(psp.dxf.limmax)[:2] == (202.0, 290.0)
    # and the rendered sheet agrees with the same convention
    frame = layout_ops.paper_frame(psp)
    assert frame["sheet"] == (-8.0, -7.0, 202.0, 290.0)


def test_effective_page_reads_rotated_layouts():
    doc = _doc_with_model_content()
    layout = doc.doc.layouts.get("Layout1")
    layout.dxf.paper_width = 210.0
    layout.dxf.paper_height = 297.0
    layout.dxf.top_margin = 4.0
    layout.dxf.right_margin = 3.0
    layout.dxf.bottom_margin = 2.0
    layout.dxf.left_margin = 1.0
    layout.dxf.plot_rotation = 1
    page = layout_ops.effective_page(layout)
    assert (page["width"], page["height"]) == (297.0, 210.0)
    assert page["margins"] == (3.0, 2.0, 1.0, 4.0)   # rotated with the sheet


def test_page_setup_dialog_roundtrip(qapp):
    from views.page_setup_dialog import PageSetupDialog

    win, t, vp = _layout_window(qapp)
    layout = win.document.doc.layouts.get("Layout1")
    win.history.execute(layout_ops.page_setup_command(
        layout, 297.0, 210.0, (5.0, 5.0, 5.0, 5.0), "ISO A4"))
    dialog = PageSetupDialog(win, layout)
    # prefill: A4 matched, landscape, margins loaded
    assert dialog.paper.currentData()[0] == "ISO A4"
    assert dialog.orientation.currentData() is True
    assert dialog.margin_top.value() == 5.0
    # switch to A3 portrait and read back
    for i in range(dialog.paper.count()):
        if dialog.paper.itemData(i) != "custom" \
                and dialog.paper.itemData(i)[0] == "ISO A3":
            dialog.paper.setCurrentIndex(i)
            break
    dialog.orientation.setCurrentIndex(1)      # portrait
    values = dialog.values()
    assert (values["width"], values["height"]) == (297.0, 420.0)
    assert values["size_name"] == "ISO A3"
    win.close()


def test_page_setup_full_options_roundtrip():
    doc = _doc_with_model_content()
    history = History(doc)
    psp = doc.doc.layouts.get("Layout1")
    vp = psp.add_viewport(center=(100, 100), size=(80, 60),
                          view_center_point=(50, 25), view_height=30)
    history.execute(layout_ops.page_setup_command(
        psp, 297.0, 210.0, (5.0, 5.0, 5.0, 5.0), "ISO A4",
        device="DWG To PDF.pc3",
        plot_type=layout_ops.PLOT_TYPE_EXTENTS,
        offset=(10.0, 4.0), centered=True,
        scale=(1, 1), scale_lineweights=True,
        style_sheet="monochrome.ctb",
        plot_lineweights=True, plot_styles=True,
        paperspace_last=False, hide_paperspace=False,
        shade_plot=0, shade_quality=2, shade_dpi=300))
    dxf = psp.dxf
    assert dxf.plot_configuration_file == "DWG To PDF.pc3"
    assert dxf.plot_type == layout_ops.PLOT_TYPE_EXTENTS
    assert (dxf.plot_origin_x_offset, dxf.plot_origin_y_offset) == (10.0, 4.0)
    assert dxf.current_style_sheet == "monochrome.ctb"
    assert dxf.standard_scale_type == 16       # 1:1 from the standard list
    flags = int(dxf.plot_layout_flags)
    assert flags & layout_ops.FLAG_PLOT_CENTERED
    assert flags & layout_ops.FLAG_SCALE_LINEWEIGHTS
    assert flags & layout_ops.FLAG_PRINT_LINEWEIGHTS
    assert not (flags & layout_ops.FLAG_USE_STANDARD_SCALE)
    # limits account for the plot offset
    assert tuple(dxf.limmin)[:2] == (-15.0, -9.0)
    # the viewport still survives the full write
    assert [e for e in psp if e.dxftype() == "VIEWPORT"] == [vp]
    history.undo()
    assert int(dxf.plot_type) == 5             # back to schema default


def test_page_setup_fit_to_paper_and_upside_down():
    doc = _doc_with_model_content()
    history = History(doc)
    psp = doc.doc.layouts.get("Layout1")
    history.execute(layout_ops.page_setup_command(
        psp, 297.0, 210.0, (1.0, 2.0, 3.0, 4.0), "ISO A4",
        upside_down=True, fit_to_paper=True))
    dxf = psp.dxf
    assert dxf.plot_rotation == 2
    assert dxf.standard_scale_type == 0        # scaled to fit
    assert int(dxf.plot_layout_flags) & layout_ops.FLAG_USE_STANDARD_SCALE
    # displayed margins come back exactly as the user typed them
    page = layout_ops.effective_page(psp)
    assert page["margins"] == (1.0, 2.0, 3.0, 4.0)
    assert (page["width"], page["height"]) == (297.0, 210.0)


def test_page_setup_dialog_prefills_options(qapp):
    from views.page_setup_dialog import PageSetupDialog

    win, t, vp = _layout_window(qapp)
    layout = win.document.doc.layouts.get("Layout1")
    win.history.execute(layout_ops.page_setup_command(
        layout, 297.0, 210.0, (5.0, 5.0, 5.0, 5.0), "ISO A4",
        device="DWG To PDF.pc3", style_sheet="monochrome.ctb",
        scale=(1, 50), plot_lineweights=True))
    dialog = PageSetupDialog(win, layout)
    assert dialog.device.currentData() == "DWG To PDF.pc3"
    assert dialog.style_sheet.currentData() == "monochrome.ctb"
    assert dialog.scale.currentData() == (1, 50)
    assert dialog.plot_lineweights.isChecked()
    assert not dialog.fit_to_paper.isChecked()
    assert dialog.landscape.isChecked()
    values = dialog.values()
    assert values["scale"] == (1.0, 50.0)
    assert values["style_sheet"] == "monochrome.ctb"
    win.close()


# -- classic UI surfaces: MODEL/PAPER toggle + viewport scale combo ------------

def test_space_button_reflects_state(qapp):
    win, t, vp = _layout_window(qapp)
    win._update_space_button()
    assert win._space_btn.text() == "PAPER"     # layout tab, paper space
    win._active_vp = vp
    win._update_space_button()
    assert win._space_btn.text() == "MODEL"     # inside the viewport
    win._active_vp = None
    win._active_layout = "Model"
    win._update_space_button()
    assert win._space_btn.text() == "MODEL"
    win.close()


def test_vp_scale_combo_applies_and_tracks(qapp):
    win, t, vp = _layout_window(qapp)
    t._pick_tolerance = 2.0
    t.on_click(60.0, 100.0)                     # select the viewport
    combo = win._vp_scale_combo
    win._refresh_vp_scale_combo()
    target = None
    for i in range(combo.count()):
        if combo.itemData(i) == (1, 50):
            target = i
            break
    assert target is not None
    win._on_vp_scale_combo(target)
    assert layout_ops.viewport_scale(vp) == pytest.approx(1.0 / 50.0)
    assert combo.currentIndex() == target       # refresh matched the ratio
    # locked viewport: the combo refuses and re-syncs
    win.history.execute(layout_ops.SetViewportLockCommand(vp, True))
    for i in range(combo.count()):
        if combo.itemData(i) == (1, 100):
            win._on_vp_scale_combo(i)
            break
    assert layout_ops.viewport_scale(vp) == pytest.approx(1.0 / 50.0)
    win.close()


# -- PLOT: layout -> PDF at 1:1 ------------------------------------------------

def test_plot_layout_pdf_page_size_and_true_scale(qapp, tmp_path):
    import shutil
    import subprocess

    from formats import pdf_out

    doc = Document.new()
    doc.modelspace().add_circle((10.0, 5.0), 3.0)     # Ø 6 m in meters
    history = History(doc)
    psp = doc.doc.layouts.get("Layout1")
    history.execute(layout_ops.page_setup_command(
        psp, 297.0, 210.0, (5.0, 5.0, 5.0, 5.0), "ISO A4"))
    # viewport at 10:1 (meters on a mm sheet = real 1:100): Ø 6 m -> Ø 60 mm
    psp.add_viewport(center=(100.0, 80.0), size=(200.0, 140.0),
                     view_center_point=(10.0, 5.0), view_height=14.0)

    path = str(tmp_path / "layout.pdf")
    printer = pdf_out.make_pdf_printer_mm(path, 297.0, 210.0)
    pdf_out.plot_layout(doc, printer, "Layout1")
    assert (tmp_path / "layout.pdf").exists()

    if shutil.which("pdfinfo"):
        info = subprocess.run(["pdfinfo", path], capture_output=True,
                              text=True).stdout
        size_line = next(l for l in info.splitlines() if "Page size" in l)
        # 297 x 210 mm = 841.89 x 595.28 pts
        w_pts = float(size_line.split(":")[1].split()[0])
        h_pts = float(size_line.split(":")[1].split()[2])
        assert w_pts == pytest.approx(841.89, abs=1.0)
        assert h_pts == pytest.approx(595.28, abs=1.0)

    if shutil.which("pdftoppm"):
        # measure with a ruler, in pixels: at 150 dpi the Ø 60 mm circle
        # must span 60 * 150 / 25.4 = 354 px
        subprocess.run(["pdftoppm", "-r", "150", "-gray", "-png", path,
                        str(tmp_path / "page")], check=True)
        import numpy as np
        from PIL import Image

        page = next(tmp_path.glob("page*.png"))
        img = np.array(Image.open(page).convert("L"))
        ys, xs = np.nonzero(img < 128)
        assert len(xs), "the plot produced no ink"
        diameter_px = xs.max() - xs.min()
        assert diameter_px == pytest.approx(60.0 * 150.0 / 25.4, abs=6.0)


def test_plot_layout_borders_follow_flag(qapp):
    from formats import pdf_out

    doc = Document.new()
    doc.modelspace().add_circle((10.0, 5.0), 3.0)
    psp = doc.doc.layouts.get("Layout1")
    psp.add_viewport(center=(100.0, 80.0), size=(200.0, 140.0),
                     view_center_point=(10.0, 5.0), view_height=14.0)
    # default flags: no viewport borders in the plot
    n_default = len(pdf_out.build_graphics_scene(doc, "Layout1").items())
    psp.dxf.plot_layout_flags = int(
        psp.dxf.get_default("plot_layout_flags")) | 1
    n_borders = len(pdf_out.build_graphics_scene(doc, "Layout1").items())
    assert n_borders > n_default


# -- canvas right-click routing ------------------------------------------------

def test_right_click_is_enter_during_a_tool(qapp):
    from PySide6.QtCore import QPoint

    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    win.tools.start_tool("LINE")
    win.tools.on_click(0.0, 0.0)
    win.tools.on_click(10.0, 5.0)
    assert win.tools.active()
    win.on_canvas_right_click(QPoint(0, 0))    # classic: right-click = Enter
    assert not win.tools.active()
    lines = [e for e in win.document.modelspace() if e.dxftype() == "LINE"]
    assert len(lines) == 1
    win.close()


def test_right_click_accepts_prompt_default(qapp):
    from PySide6.QtCore import QPoint

    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    win.dispatcher.submit("ZOOM")
    assert win.dispatcher.pending_prompt is not None
    win.on_canvas_right_click(QPoint(0, 0))    # accepts <Extents>
    assert win.dispatcher.pending_prompt is None
    win.close()


def test_a_cheap_sheet_pans_synchronously(qapp, monkeypatch):
    """Per-tick THREADED regens made viewport pan trail the cursor. A sheet
    whose regen is measured cheap rebuilds inline: the new scene is on the
    canvas when vp_view_pan returns, no worker involved."""
    win, t, vp = _layout_window(qapp)
    win._active_vp = vp
    win._regen_ms[win._active_layout] = 5.0        # measured: cheap
    before = win.viewport._scene
    assert win.vp_view_pan(5.0, 2.0)
    assert win.viewport._scene is not before       # adopted inline
    assert win._regen_worker is None               # nothing left in flight
    assert win._active_layout in win._regen_ms     # measurement refreshed
    win._vp_gesture_commit()
    win.close()


def test_a_heavy_sheet_keeps_the_threaded_path(qapp, monkeypatch):
    win, t, vp = _layout_window(qapp)
    win._active_vp = vp
    win._regen_ms[win._active_layout] = 500.0      # measured: heavy
    called = []
    monkeypatch.setattr(win, "regen_in_memory", lambda *a, **k: called.append(1))
    scene = win.viewport._scene
    assert win.vp_view_pan(5.0, 2.0)
    assert called                                   # threaded fallback
    assert win.viewport._scene is scene             # no inline adoption
    win._vp_gesture_commit()
    win.close()
