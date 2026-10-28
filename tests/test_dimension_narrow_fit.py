# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A linear dimension too narrow for its text sets the text BESIDE it (#102).

Rafael's part (2026-10-18, a clothes peg in millimetres, ISO-25): the 2.56
between two arc centres kept its text centred on top of the extension lines
and the arrows, "ahogada", and lifted above the line further than every
other dimension's text. AutoCAD's ISO-25 (DIMATFIT 3, DIMTMOVE 0 "beside
the dimension line") moves it out past the second extension line, at the
usual distance above the line, with the dimension line running on under it.
"""
from __future__ import annotations

import pytest


def _dimension(width: float):
    from core import actions
    from core.templates import new_document

    document = new_document("mm")
    cmd = actions.dim_linear((0.0, 0.0), (width, 0.0), (width / 2, -5.0))
    cmd.do(document)
    return cmd.dim


def _parts(dim):
    block = dim.get_geometry_block()
    texts = [e for e in block if e.dxftype() == "MTEXT"]
    lines = [e for e in block if e.dxftype() == "LINE"]
    assert len(texts) == 1
    return texts[0], lines


def _text_box(text):
    from ezdxf.tools.text_size import mtext_size

    size = mtext_size(text)
    x, y = text.dxf.insert.x, text.dxf.insert.y       # middle centre
    return (x - size.total_width / 2, y - size.total_height / 2,
            x + size.total_width / 2, y + size.total_height / 2)


def test_rafaels_2_56_goes_beside_the_second_extension_line():
    text, lines = _parts(_dimension(2.56))
    left, bottom, right, _top = _text_box(text)
    arrow, gap = 2.5, 0.625
    # outside, past the outward arrowhead, not over the extension lines
    assert left == pytest.approx(2.56 + arrow + gap, abs=0.2)
    # the dimension line runs on under the text, to its far end
    assert any(abs(l.dxf.start.y + 5) < 1e-9 and abs(l.dxf.end.y + 5) < 1e-9
               and max(l.dxf.start.x, l.dxf.end.x) >= right - 0.2
               for l in lines)


def test_the_text_sits_as_far_above_the_line_as_any_other():
    narrow, _ = _parts(_dimension(2.56))
    wide, _ = _parts(_dimension(23.0))
    assert narrow.dxf.insert.y == pytest.approx(wide.dxf.insert.y)
    assert wide.dxf.insert.x == pytest.approx(11.5)         # centred as before


def test_text_that_fits_by_its_real_width_stays_inside():
    # "10,25" is 12.5 wide by ezdxf's one-height-per-character guess, about
    # 9 in Arial at 2.5: it fits between lines 10.25 apart, as in AutoCAD.
    text, _ = _parts(_dimension(10.25))
    wide, _ = _parts(_dimension(23.0))
    assert text.dxf.insert.x == pytest.approx(10.25 / 2)
    assert text.dxf.insert.y == pytest.approx(wide.dxf.insert.y)  # not lifted
