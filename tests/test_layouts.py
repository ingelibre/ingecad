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
