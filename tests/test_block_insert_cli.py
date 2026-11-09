# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""-BLOCK and -INSERT: the block commands answered wholly at the prompt,
in the classic order (name, point, then the rest), for scripts and for the
hands that never leave the keyboard."""
from __future__ import annotations

import pytest


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.maybe_save_changes = lambda: True
    w.resize(1400, 800)
    w.show()
    w.new_document()
    # no dialog may answer for the prompt: a modal one hangs offscreen
    w.tools._ask_choice = lambda *a, **k: pytest.fail("a dialog was opened")
    w.tools._ask_text = lambda *a, **k: pytest.fail("a dialog was opened")
    yield w
    w.document.dirty = False
    w.close()


def _type(win, *texts):
    for text in texts:
        win._on_command_submitted(text)


def _history(win) -> str:
    return win.command_line.history.toPlainText()


def _of(win, kind):
    return list(win.document.modelspace().query(kind))


def _door(win):
    _type(win, "RECTANG", "0,0", "10,20", "ZOOM", "E")
    _type(win, "-BLOCK", "DOOR", "0,0", "ALL", "")


def test_block_defines_from_the_prompt_and_takes_the_objects(win):
    _door(win)
    blocks = win.document.doc.blocks
    assert "DOOR" in blocks
    assert [e.dxftype() for e in blocks.get("DOOR")] == ["LWPOLYLINE"]
    # the classic ending: the objects are gone, and no reference is left
    assert _of(win, "LWPOLYLINE") == [] and _of(win, "INSERT") == []
    assert not win.tools.active()
    _type(win, "U")
    assert len(_of(win, "LWPOLYLINE")) == 1 and "DOOR" not in blocks


def test_block_name_may_have_spaces_and_question_mark_lists(win):
    _type(win, "RECTANG", "0,0", "10,20", "ZOOM", "E")
    _type(win, "-BLOCK", "front door", "0,0", "ALL", "")
    assert "front door" in win.document.doc.blocks
    _type(win, "-BLOCK", "?")
    assert "front door" in _history(win).splitlines()[-1] \
        or "front door" in _history(win)
    assert not win.tools.active()


def test_block_asks_before_redefining(win):
    _door(win)
    _type(win, "CIRCLE", "0,0", "5")
    _type(win, "-BLOCK", "DOOR")
    assert "Redefine it?" in _history(win)
    _type(win, "Y", "0,0", "ALL", "")
    assert [e.dxftype() for e in win.document.doc.blocks.get("DOOR")] \
        == ["CIRCLE"]


def test_insert_asks_point_scales_and_rotation(win):
    _door(win)
    _type(win, "-INSERT", "door", "100,50", "2", "3", "90")
    (ref,) = _of(win, "INSERT")
    assert ref.dxf.name == "DOOR"                 # found whatever its case
    assert tuple(ref.dxf.insert)[:2] == (100.0, 50.0)
    assert (ref.dxf.xscale, ref.dxf.yscale) == (2.0, 3.0)
    assert ref.dxf.rotation == pytest.approx(90.0)
    assert not win.tools.active()


def test_insert_enter_takes_every_default(win):
    _door(win)
    _type(win, "-INSERT", "DOOR", "100,50", "", "", "")
    (ref,) = _of(win, "INSERT")
    assert (ref.dxf.xscale, ref.dxf.yscale, ref.dxf.rotation) == (1, 1, 0)


def test_insert_y_follows_x_and_a_point_shows_the_rotation(win):
    _door(win)
    _type(win, "-INSERT", "DOOR", "100,50", "2", "", "100,60")
    (ref,) = _of(win, "INSERT")
    assert (ref.dxf.xscale, ref.dxf.yscale) == (2.0, 2.0)
    assert ref.dxf.rotation == pytest.approx(90.0)


def test_insert_presets_skip_their_questions(win):
    _door(win)
    _type(win, "-INSERT", "DOOR", "S", "4", "R", "30", "100,50")
    (ref,) = _of(win, "INSERT")
    assert (ref.dxf.xscale, ref.dxf.yscale) == (4.0, 4.0)
    assert ref.dxf.rotation == pytest.approx(30.0)
    assert not win.tools.active()


def test_insert_of_an_unknown_name_asks_again(win):
    _door(win)
    _type(win, "-INSERT", "WINDOW")
    assert 'Block "WINDOW" not found.' in _history(win)
    assert win.tools.active()
    _type(win, "DOOR", "1,1", "", "", "")
    assert len(_of(win, "INSERT")) == 1


def test_the_short_names_run_them(win):
    _door(win)
    _type(win, "-I", "?")
    assert "DOOR" in _history(win)
    _type(win, "-B", "?")
    assert not win.tools.active()
