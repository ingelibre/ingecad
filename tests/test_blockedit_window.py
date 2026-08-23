# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""BEDIT through the real window: commands, guards, picking, propagation."""
from __future__ import annotations

import time

import ezdxf


def _wait_regen(qapp, win, timeout_s=20.0):
    t0 = time.monotonic()
    while win._regen_worker is not None and time.monotonic() - t0 < timeout_s:
        qapp.processEvents()


def _make(qapp):
    from views.main_window import MainWindow
    from core import actions

    win = MainWindow()
    win.new_document()
    doc = win.document
    chair = doc.doc.blocks.new("SILLA")
    chair.add_line((0, 0), (10, 0))
    doc.doc.modelspace().add_blockref("SILLA", (50, 50))
    win.tools._invalidate_geometry()
    win.regen_in_memory()
    _wait_regen(qapp, win)
    return win


def test_bedit_by_name_and_bclose_saves(qapp) -> None:
    from core import actions

    win = _make(qapp)
    win.dispatcher.submit("BEDIT SILLA")
    assert win._block_session is not None
    assert win.document.edit_block == "SILLA"
    assert "Block Editor" in win.windowTitle() or "SILLA" in win.windowTitle()

    win.tools._execute(actions.add_circle((5, 5), 2))
    assert len(list(win.document.doc.blocks.get("SILLA"))) == 2

    # BCLOSE would raise its Save/Discard dialog here (the session is
    # dirty), which blocks a headless test -- close through the same path
    # the dialog's Save button takes:
    win._end_block_session(save=True)
    assert win._block_session is None
    assert win.document.edit_block is None
    assert len(list(win.document.doc.blocks.get("SILLA"))) == 2


def test_the_be_alias_reaches_bedit(qapp) -> None:
    win = _make(qapp)
    assert win.dispatcher.resolve_name("BE") == "BEDIT"


def test_picking_inside_the_editor_sees_the_definition(qapp) -> None:
    """The index follows the space: the block's own line is clickable at its
    definition coordinates, and the modelspace insert is not there."""
    win = _make(qapp)
    win.dispatcher.submit("BEDIT SILLA")
    _wait_regen(qapp, win)
    win.tools._pick_tolerance = 0.8
    hit = win.tools.pick_entity((5.0, 0.0))     # the line, at the origin
    assert hit is not None and hit.dxftype() == "LINE"
    assert win.tools.pick_entity((50.0, 50.0)) is None   # no insert here
    win._end_block_session(save=True)


def test_layout_tabs_are_locked_during_a_session(qapp) -> None:
    win = _make(qapp)
    win.document.doc.layouts.new("Sheet")
    win._refresh_layout_tabs()
    win.dispatcher.submit("BEDIT SILLA")
    win.switch_layout("Sheet")
    assert win._active_layout == "Model", "the tab switch went through"
    win._end_block_session(save=False)


def test_undo_is_refused_at_the_session_floor(qapp) -> None:
    from core import actions

    win = _make(qapp)
    win.tools._execute(actions.add_line((90, 90), (99, 99)))   # drawing edit
    win.dispatcher.submit("BEDIT SILLA")
    before = len(win.history._undo)
    win._cmd_undo()                                   # must be refused
    assert len(win.history._undo) == before
    win._end_block_session(save=False)
    win._cmd_undo()                                   # outside: works again
    assert len(win.history._undo) == before - 1


def test_insert_picker_hides_what_would_recurse(qapp) -> None:
    win = _make(qapp)
    table = win.document.doc.blocks.new("MESA")
    table.add_blockref("SILLA", (0, 0))
    win.dispatcher.submit("BEDIT SILLA")
    names = win.tools.block_names()
    assert "SILLA" not in names, "self-insertion offered"
    assert "MESA" not in names, "transitive recursion offered"
    win._end_block_session(save=False)
    assert "MESA" in win.tools.block_names()


def test_bsave_then_discard_keeps_the_saved_state(qapp) -> None:
    from core import actions

    win = _make(qapp)
    win.dispatcher.submit("BEDIT SILLA")
    win.tools._execute(actions.add_circle((5, 5), 2))
    win.dispatcher.submit("BSAVE")
    win.tools._execute(actions.add_circle((7, 7), 1))
    win._end_block_session(save=False)
    assert len(list(win.document.doc.blocks.get("SILLA"))) == 2


def test_bsave_and_bclose_outside_a_session_only_echo(qapp) -> None:
    win = _make(qapp)
    win.dispatcher.submit("BSAVE")
    win.dispatcher.submit("BCLOSE")
    assert win._block_session is None


def test_bedit_from_a_layout_tab_lands_in_the_editor(qapp) -> None:
    win = _make(qapp)
    win.document.doc.layouts.new("Sheet")
    win._refresh_layout_tabs()
    win.switch_layout("Sheet")
    _wait_regen(qapp, win)
    win.dispatcher.submit("BEDIT SILLA")
    assert win._active_layout == "Model"
    assert win.document.edit_block == "SILLA"
    win._end_block_session(save=False)


def test_opening_another_file_drops_the_session(qapp, tmp_path) -> None:
    """Reported by Marco: open casa bueno while editing a block, and the NEW
    document's layout tabs answer "Close the Block Editor first" -- a session
    of a document that no longer exists kept guarding the window."""
    import ezdxf as _ez

    win = _make(qapp)
    win.dispatcher.submit("BEDIT SILLA")
    assert win._block_session is not None

    other = tmp_path / "otro.dxf"
    doc2 = _ez.new(setup=True)
    doc2.modelspace().add_line((0, 0), (1, 1))
    doc2.layouts.new("Sheet")
    doc2.saveas(other)
    win.document.dirty = False           # skip the save prompt
    win.open_path(other)
    t0 = time.monotonic()
    while win._block_session is not None and time.monotonic() - t0 < 20:
        qapp.processEvents()

    assert win._block_session is None
    _wait_regen(qapp, win)
    win._refresh_layout_tabs()
    win.switch_layout("Sheet")           # must NOT be refused
    assert win._active_layout == "Sheet"


def test_new_document_drops_the_session(qapp) -> None:
    win = _make(qapp)
    win.dispatcher.submit("BEDIT SILLA")
    win.document.dirty = False
    win.new_document()
    assert win._block_session is None
    assert win.document.edit_block is None


def test_the_block_editor_toolbar_appears_and_goes(qapp) -> None:
    """The classic toolbar the reference promises (p. 223): without it the
    first real user edited a block and had no visible way to save or leave."""
    win = _make(qapp)
    assert not win._blockedit_toolbar.isVisible() or not win.isVisible()
    win.show()
    assert not win._blockedit_toolbar.isVisible()
    win.dispatcher.submit("BEDIT SILLA")
    assert win._blockedit_toolbar.isVisible()
    assert "SILLA" in win._blockedit_label.text()
    labels = [a.text() for a in win._blockedit_toolbar.actions()]
    assert any("BSAVE" in t for t in labels)
    assert any("BCLOSE" in t for t in labels)
    win._end_block_session(save=True)
    assert not win._blockedit_toolbar.isVisible()
