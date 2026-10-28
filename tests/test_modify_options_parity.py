# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""MOVE, COPY, STRETCH, ROTATE and SCALE answer the prompts AutoCAD offers.

Typed as the user types them. Found by driving the real window through the
daily commands and comparing with the Command Reference:

* "Specify base point or [Displacement]": D, or Enter, asks for a vector;
  Enter at the second point takes the first point as the displacement --
  "MOVE, 2,3, Enter" moved nothing and ended the command (MOVE, p.1211);
* COPY's later prompt has Exit and Undo; U was "Invalid input.";
* ROTATE and SCALE have [Copy/Reference]; C was "Invalid input.".
"""
from __future__ import annotations

import pytest


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    window = MainWindow()
    window.show()
    window.new_document()
    yield window
    window.document.dirty = False
    window.close()


def _type(win, *texts):
    for text in texts:
        win._on_command_submitted(text)


def _circles(win):
    return sorted((round(c.dxf.center.x, 9), round(c.dxf.center.y, 9),
                   round(c.dxf.radius, 9))
                  for c in win.document.modelspace().query("CIRCLE"))


def test_move_takes_the_first_point_or_a_typed_displacement(win):
    _type(win, "CIRCLE", "0,0", "1")
    _type(win, "MOVE", "L", "", "2,3", "")
    assert _circles(win) == [(2, 3, 1)]
    _type(win, "MOVE", "L", "", "D", "1,1")
    assert _circles(win) == [(3, 4, 1)]
    _type(win, "MOVE", "L", "", "", "-3,-4")      # Enter = <Displacement>
    assert _circles(win) == [(0, 0, 1)]


def test_copy_repeats_with_exit_and_undo(win):
    _type(win, "CIRCLE", "0,0", "1")
    _type(win, "COPY", "L", "", "0,0", "5,0", "10,0", "U", "E")
    assert _circles(win) == [(0, 0, 1), (5, 0, 1)]
    # Last is the copy at 5,0; 0,7 then Enter copies it by (0, 7)
    _type(win, "COPY", "L", "", "0,7", "")
    assert (5, 7, 1) in _circles(win)


def test_rotate_and_scale_can_work_on_a_copy(win):
    _type(win, "CIRCLE", "10,0", "1")
    _type(win, "ROTATE", "L", "", "0,0", "C", "90")
    assert _circles(win) == [(0, 10, 1), (10, 0, 1)]
    _type(win, "SCALE", "L", "", "0,0", "C", "2")
    assert (0, 20, 2) in _circles(win) and len(_circles(win)) == 3


def test_stretch_takes_a_displacement_too(win):
    _type(win, "LINE", "0,0", "10,0", "")
    t = win.tools
    _type(win, "STRETCH")
    t.on_click(12.0, 1.0)                 # crossing over the right end
    t.on_click(8.0, -1.0)
    _type(win, "", "D", "2,0")
    line = win.document.modelspace().query("LINE")[0]
    assert (line.dxf.start.x, line.dxf.end.x) == (0.0, 12.0)


def test_undo_takes_a_count(win):
    """UNDO undid one step at once and the 2 typed next was an unknown
    command (UNDO: "Enter the number of operations to undo <1>")."""
    for x in (0, 5, 10):
        _type(win, "CIRCLE", f"{x},0", "1")
    _type(win, "UNDO", "2")
    assert _circles(win) == [(0, 0, 1)]
    _type(win, "UNDO", "")                 # Enter = 1
    assert _circles(win) == []


def test_text_ends_on_enter_at_an_empty_line(win):
    t = win.tools
    _type(win, "TEXT", "0,5", "1", "0")
    for ch in "ABC":
        t.tool.on_char(ch)
    _type(win, "")                         # next line
    _type(win, "")                         # empty line: the command ends
    assert t.tool is None
    assert [e.dxf.text for e in win.document.modelspace().query("TEXT")] \
        == ["ABC"]


def test_erase_all_takes_layers_that_are_off_and_oops_gives_back(win):
    """ALL: "except those objects on frozen or on locked layers"."""
    _type(win, "-LAYER", "M", "OCULTA", "")
    _type(win, "CIRCLE", "0,0", "1")
    _type(win, "-LAYER", "S", "0", "OFF", "OCULTA", "")
    assert win.document.doc.layers.get("OCULTA").is_off()
    _type(win, "CIRCLE", "5,0", "1")
    _type(win, "ERASE", "ALL", "")
    assert _circles(win) == []
    _type(win, "LINE", "0,0", "1,1", "")   # OOPS works after other commands
    _type(win, "OOPS")
    assert _circles(win) == [(0, 0, 1), (5, 0, 1)]
    assert len(win.document.modelspace().query("LINE")) == 1


def test_offset_starts_at_through_and_line_keeps_close_after_undo(win):
    from tools.edit import OffsetTool

    OffsetTool.distance = None            # a fresh session: <Through>
    _type(win, "OFFSET")
    assert "<Through>" in win.command_line.history.toPlainText().splitlines()[-1]
    win.tools.cancel()
    _type(win, "LINE", "0,0", "10,0", "10,10", "0,10", "U")
    assert "Close" in win.command_line.history.toPlainText().splitlines()[-1]
    _type(win, "C")
    assert len(win.document.modelspace().query("LINE")) == 3


def test_dragging_the_text_moves_the_dimension_line_under_dimtmove_0(win):
    """DIMTMOVE 0, the default: "moves the dimension line with dimension
    text". The text moved and the line stayed at y = -5."""
    from core.select import entity_grips

    _type(win, "DIMLINEAR", "0,0", "10,0", "5,-5")
    dim = win.document.modelspace().query("DIMENSION")[-1]
    handle = dim.dxf.handle
    grip = next((x, y, role, handle, i)
                for i, (x, y, role) in enumerate(entity_grips(dim))
                if role == "dim_text")
    win.tools.selection = {handle}
    win.tools.begin_grip_drag(grip)
    win.tools.update_grip_drag(7.0, -8.0)
    win.tools.finish_grip_drag(7.0, -8.0)
    assert dim.dxf.defpoint.y == pytest.approx(-8.0, abs=1.0)
    assert dim.dxf.text_midpoint.x == pytest.approx(7.0)
    assert dim.get_measurement() == pytest.approx(10.0)
    win.history.undo()
    assert dim.dxf.defpoint.y == pytest.approx(-5.0)


@pytest.fixture
def standard_trim(monkeypatch):
    from core import trimmode

    monkeypatch.setattr(trimmode, "trimextendmode", lambda: 0)
    monkeypatch.setattr(trimmode, "set_trimextendmode", lambda value: None)


def _xs(win):
    return sorted((round(min(l.dxf.start.x, l.dxf.end.x), 6),
                   round(max(l.dxf.start.x, l.dxf.end.x), 6))
                  for l in win.document.modelspace().query("LINE")
                  if l.dxf.start.y == l.dxf.end.y)


def test_trim_fence_and_undo(win, standard_trim):
    """[Fence/Crossing/.../Undo] (TRIM, p.1951): F and U were "Invalid
    input."; a fence trims everything it crosses, Undo takes back the
    whole fence at once."""
    win.tools.osnap_on = False
    _type(win, "LINE", "10,-5", "10,5", "")
    for y in (0, 1, 2):
        _type(win, "LINE", f"0,{y}", f"20,{y}", "")
    _type(win, "TRIM")
    win.tools.on_click(10.0, -4.0)          # the cutting edge
    _type(win, "")
    _type(win, "F", "15,-1", "15,3", "")
    assert _xs(win) == [(0, 10)] * 3
    _type(win, "U")
    assert _xs(win) == [(0, 20)] * 3
    _type(win, "C", "16,-1", "18,0.5")      # typed Crossing: y = 0 only
    assert _xs(win) == [(0, 10), (0, 20), (0, 20)]
    _type(win, "")
    assert win.tools.tool is None


def test_array_asks_only_the_spacing_it_needs(win):
    """One row: -ARRAY asks no distance between rows. It did, so the video's
    "1, 6, 0.20" put 0.20 between rows and an Enter stacked five copies
    on the original; "COU" was taken as one row."""
    _type(win, "CIRCLE", "0,0", "0.004")
    _type(win, "-ARRAY", "L", "", "R", "COU")
    assert "positive integer" in win.command_line.history.toPlainText()
    _type(win, "1", "6", "", "0.20")
    xs = sorted(round(c.dxf.center.x, 9)
                for c in win.document.modelspace().query("CIRCLE"))
    assert xs == [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]


def test_autocad_aliases_and_variables_an_autocad_user_types(win):
    """Typed in a YouTuber's session and unknown: DIMASSOC, CELTSCALE,
    LWEIGHT, SETVAR...; and R, CH, PR fell to prefix completion and ran
    RAY, CHAMFER and a survey command."""
    from core.aliases import load_aliases
    from views import viewport as vp

    aliases = load_aliases()
    assert aliases["R"] == "REDRAW" and aliases["CH"] == "PROPERTIES"
    assert aliases["PR"] == "PROPERTIES" and aliases["ED"] == "TEXTEDIT"
    for text in ("R", "CH", "PR"):
        _type(win, text)
        assert win.tools.tool is None, f"{text} started a tool"
    header = win.document.doc.header
    _type(win, "CELTSCALE", "0.0035")
    assert header["$CELTSCALE"] == 0.0035
    _type(win, "LWEIGHT", "0.6")
    assert header["$CELWEIGHT"] == 60
    _type(win, "SETVAR", "DIMASSOC", "1")
    assert header["$DIMASSOC"] == 1
    _type(win, "ZOOMFACTOR", "30")
    assert vp.wheel_step() == pytest.approx(1.1)
    _type(win, "ZOOMFACTOR", "60")


def test_dimassoc_0_draws_a_dimension_as_loose_pieces(win):
    _type(win, "DIMASSOC", "0")
    _type(win, "DIMLINEAR", "0,0", "10,0", "5,-5")
    msp = win.document.modelspace()
    assert not list(msp.query("DIMENSION"))
    kinds = {e.dxftype() for e in msp}
    assert "LINE" in kinds and ({"MTEXT", "TEXT"} & kinds)
    _type(win, "U")
    assert not list(msp)
    _type(win, "DIMASSOC", "2")
