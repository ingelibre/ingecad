# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A plugin's derived geometry is modified only with the object it comes
from (core/derived.py, plugin contract level 3).

A plugin that draws its plan from data of its own (the outline of a wall,
the jambs of a door) lost the user's work: a grip or a MOVE on one of those
lines changed the drawing, not the data, and the plugin's next rebuild put
the line back. Typed and clicked as the user does it.
"""
from __future__ import annotations

import pytest

from core import derived
from core.plugins import API_VERSION, PluginContext


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w.new_document()
    yield w
    w.document.dirty = False
    w.close()


def _ctx(win, said=None):
    return PluginContext(host=win, echo=(said.append if said is not None
                                         else (lambda text: None)))


def _lines(win):
    return sorted(win.document.modelspace().query("LINE"),
                  key=lambda e: (e.dxf.start.y, e.dxf.start.x))


def _drawing(win):
    """An owner (y=0) and the line derived from it (y=2), both under key
    W1, and an ordinary line (y=5)."""
    ctx = _ctx(win)
    for y in (0, 2, 5):
        ctx.run_command("LINE", f"0,{y}", f"10,{y}", "")
    owner, line, plain = _lines(win)
    ctx.mark_owner([owner], "W1")
    ctx.mark_derived([line], "W1")
    return owner, line, plain


def _present(win, *entities):
    """Which of ``entities`` the drawing still holds (ERASE keeps an erased
    entity alive for undo)."""
    handles = {e.dxf.handle for e in win.document.modelspace()}
    return [e.dxf.handle in handles for e in entities]


def _said(win):
    return win.command_line.history.toPlainText()


def test_the_contract_is_at_level_three():
    assert API_VERSION >= 3


def test_the_derived_line_alone_is_refused_like_a_locked_layer(win):
    owner, line, plain = _drawing(win)
    t = win.tools
    win._on_command_submitted("MOVE")
    t.on_click(5.0, 2.0)                  # the derived line itself
    win._on_command_submitted("")
    win._on_command_submitted("0,0")
    win._on_command_submitted("0,3")
    assert line.dxf.start.y == 2.0
    assert "derived geometry" in _said(win)


def test_with_its_owner_it_moves(win):
    owner, line, plain = _drawing(win)
    t = win.tools
    win._on_command_submitted("MOVE")
    t.on_click(-1.0, -1.0)
    t.on_click(11.0, 3.0)                 # window over owner and line
    win._on_command_submitted("")
    win._on_command_submitted("0,0")
    win._on_command_submitted("0,10")
    assert owner.dxf.start.y == 10.0 and line.dxf.start.y == 12.0
    assert plain.dxf.start.y == 5.0


def test_pickfirst_delete_keeps_the_derived_line_alone(win):
    owner, line, plain = _drawing(win)
    t = win.tools
    t.on_click(5.0, 2.0)
    t.delete_selection()
    assert _present(win, line) == [True]
    t.on_click(-1.0, -1.0)
    t.on_click(11.0, 3.0)
    assert t.delete_selection()
    assert _present(win, owner, line, plain) == [False, False, True]


def test_derived_geometry_shows_no_grips(win):
    owner, line, plain = _drawing(win)
    t = win.tools
    t.on_click(-1.0, -1.0)
    t.on_click(11.0, 3.0)
    assert t.selection == {owner.dxf.handle, line.dxf.handle}
    assert {g[3] for g in t.grip_points()} == {owner.dxf.handle}


def test_display_only_geometry_is_never_picked(win):
    ctx = _ctx(win)
    ctx.run_command("LINE", "0,0", "10,0", "")
    ctx.run_command("LINE", "0,5", "10,5", "")
    preview, plain = _lines(win)
    ctx.mark_derived([preview])           # no key: display only
    t = win.tools
    t.on_click(-1.0, -1.0)
    t.on_click(11.0, 6.0)                 # a window over both lines
    assert t.selection == {plain.dxf.handle}
    t.clear_selection()
    t.select_all()
    assert t.selection == {plain.dxf.handle}
    t.on_click(5.0, 0.0)                  # the click passes through it
    assert preview.dxf.handle not in t.selection


def test_a_copy_keeps_its_owner_and_its_lines_together(win):
    owner, line, plain = _drawing(win)
    t = win.tools
    win._on_command_submitted("COPY")
    t.on_click(-1.0, -1.0)
    t.on_click(11.0, 3.0)
    win._on_command_submitted("")
    win._on_command_submitted("0,0")
    win._on_command_submitted("0,20")
    win._on_command_submitted("")
    copies = [e for e in _lines(win) if e.dxf.start.y >= 20]
    assert [derived.mark_of(e) for e in copies] == [
        (derived.OWNER, "W1"), (derived.DERIVED, "W1")]
    win._on_command_submitted("MOVE")
    t.on_click(-1.0, 19.0)
    t.on_click(11.0, 23.0)                # the copied pair, without the original
    win._on_command_submitted("")
    win._on_command_submitted("0,0")
    win._on_command_submitted("5,0")
    assert [e.dxf.start.x for e in copies] == [5.0, 5.0]


def test_list_still_reads_derived_geometry(win):
    owner, line, plain = _drawing(win)
    win._on_command_submitted("LIST")
    win.tools.on_click(5.0, 2.0)
    win._on_command_submitted("")
    assert "LINE" in _said(win) and "derived geometry" not in _said(win)


def test_marking_is_one_undo_step_and_undo_is_exact(win):
    ctx = _ctx(win)
    ctx.run_command("LINE", "0,0", "10,0", "")
    (line,) = _lines(win)
    ctx.mark_derived([line], "W1")
    ctx.mark_derived([line], "W2")
    assert derived.mark_of(line) == (derived.DERIVED, "W2")
    win._on_command_submitted("U")
    assert derived.mark_of(line) == (derived.DERIVED, "W1")
    ctx.unmark_derived([line])
    assert derived.mark_of(line) == (None, None)
    win._on_command_submitted("U")
    win._on_command_submitted("U")
    assert not line.has_xdata(derived.APPID)


def test_the_marks_survive_a_saved_drawing(win, tmp_path):
    import ezdxf

    owner, line, plain = _drawing(win)
    path = tmp_path / "derived.dxf"
    win.document.doc.saveas(path)
    doc = ezdxf.readfile(path)
    marks = {e.dxf.start.y: derived.mark_of(e) for e in doc.modelspace().query("LINE")}
    assert marks == {0.0: (derived.OWNER, "W1"), 2.0: (derived.DERIVED, "W1"),
                     5.0: (None, None)}


def test_an_owner_needs_a_key_and_a_foreign_mark_is_none(win):
    ctx = _ctx(win)
    ctx.run_command("LINE", "0,0", "10,0", "")
    (line,) = _lines(win)
    with pytest.raises(ValueError):
        derived.MarkCommand([line], derived.OWNER, "")
    derived._ensure_appid(line.doc)
    line.set_xdata(derived.APPID, [(1000, "SOMETHING")])
    assert derived.mark_of(line) == (None, None)
    assert derived.user_editable([line]) == ([line], [])


def test_the_assistant_cannot_modify_derived_geometry_alone(win):
    from core.ai import tools as ai

    owner, line, plain = _drawing(win)
    with pytest.raises(ai.ToolError, match="derived geometry"):
        ai.erase_entities(win, [line.dxf.handle])
    assert _present(win, line) == [True]
    ai.erase_entities(win, [owner.dxf.handle, line.dxf.handle])
    assert _present(win, owner, line) == [False, False]
