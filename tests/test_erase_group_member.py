# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""ERASE takes a member out of its group, and U puts it back in.

The architecture plugin found it: the erased member stayed listed in its
group until the next save dropped it, and an undo after that save brought
the object back outside its group (the plugin carried a command of its own
to repair it).
"""
from __future__ import annotations

import pytest

from core import groups as group_ops


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w.new_document()
    w.tools.osnap_on = False
    yield w
    w.document.dirty = False
    w.close()


def _type(win, *texts):
    for text in texts:
        win._on_command_submitted(text)


def _wall(win):
    _type(win, "LINE", "0,0", "10,0", "", "LINE", "0,5", "10,5", "",
          "ZOOM", "E")
    low, high = sorted(win.document.modelspace().query("LINE"),
                       key=lambda e: e.dxf.start.y)
    win.tools._execute(group_ops.CreateGroupCommand("MURO", [low, high]))
    group_ops.set_selectable(win.document, "MURO", False)
    return low, high


def _members(win):
    return {e.dxf.handle for e in group_ops.members(win.document, "MURO")}


def _erase_low(win):
    win.tools.on_hover(5, 0, threshold_world=0.5)
    win.tools.on_click(5, 0)
    _type(win, "ERASE")


def test_the_erased_member_leaves_and_comes_back(win, tmp_path):
    low, high = _wall(win)
    _erase_low(win)
    assert _members(win) == {high.dxf.handle}
    win.document.save_as(tmp_path / "a.dxf")       # the save that dropped it
    _type(win, "U")
    assert low in win.document.modelspace()
    assert _members(win) == {low.dxf.handle, high.dxf.handle}
    win.document.save_as(tmp_path / "b.dxf")
    import ezdxf

    reread = ezdxf.readfile(tmp_path / "b.dxf").groups.get("MURO")
    assert len(list(reread)) == 2


def test_redo_takes_it_out_again(win):
    low, high = _wall(win)
    _erase_low(win)
    _type(win, "U", "REDO")
    assert _members(win) == {high.dxf.handle}
