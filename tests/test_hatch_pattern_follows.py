# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A hatch's pattern goes where its hatch goes: inside a block reference,
after MOVE, after EXPLODE.

A colleague's plan, its walls drawn as blocks with hatches lined up by
their author, showed the brick pattern cut and doubled at every joint
(a review video, casquillo.dwg). ezdxf's transform moved the boundary
but left the pattern's base points where they were, so every hatch in a
block was drawn anchored to the block's origin in the world instead of
its insertion point. MOVE slid the pattern under the hatch the same way.
"""
from __future__ import annotations

import ezdxf
import pytest

from core import actions, ezdxf_patches

ezdxf_patches.apply()


def _base(hatch):
    point = hatch.pattern.lines[0].base_point
    return round(point[0], 6), round(point[1], 6)


def test_a_block_s_hatch_is_drawn_from_its_insertion_point():
    doc = ezdxf.new("R2010")
    block = doc.blocks.new("WALL")
    hatch = block.add_hatch()
    hatch.paths.add_polyline_path([(0, 0), (10, 0), (10, 2), (0, 2)])
    hatch.set_pattern_fill("ANSI31", scale=1.0)
    hatch.pattern.lines[0].base_point = (0.0, 0.0)
    insert = doc.modelspace().add_blockref("WALL", (13.7, 4.2))
    (drawn,) = [e for e in insert.virtual_entities() if e.dxftype() == "HATCH"]
    assert _base(drawn) == (13.7, 4.2)


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


def _hatched_square(win):
    _type(win, "RECTANG", "0,0", "10,10", "ZOOM", "E",
          "-HATCH", "P", "ANSI31", "1", "0", "5,5", "")
    (hatch,) = win.document.modelspace().query("HATCH")
    return hatch


def test_move_takes_the_pattern_along(win):
    hatch = _hatched_square(win)
    x, y = _base(hatch)
    win.tools.select_entities([hatch])
    _type(win, "MOVE", "0,0", "3.3,1.1")
    assert _base(hatch) == (round(x + 3.3, 6), round(y + 1.1, 6))
    _type(win, "U")
    assert _base(hatch) == (x, y)


def test_explode_leaves_the_pattern_where_it_was_drawn(win):
    hatch = _hatched_square(win)
    x, y = _base(hatch)
    win.tools._execute(actions.create_block("CUADRO", (0, 0), [hatch]))
    win.tools._execute(actions.insert_block("CUADRO", (20, 7)))
    (insert,) = [i for i in win.document.modelspace().query("INSERT")
                 if tuple(i.dxf.insert)[:2] == (20, 7)]
    before = set(win.document.modelspace().query("HATCH"))
    win.tools.select_entities([insert])
    _type(win, "EXPLODE")
    (exploded,) = [h for h in win.document.modelspace().query("HATCH")
                   if h not in before]
    assert _base(exploded) == (round(x + 20, 6), round(y + 7, 6))
