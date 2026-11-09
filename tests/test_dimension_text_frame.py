# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A negative DIMGAP frames the dimension text (a theoretically exact
dimension, UNE-EN ISO 129-1).

"Draw frame around text" in the Dimension Style dialog stores DIMGAP
negative, as classic CAD does, but the dimension came out without its
frame: the drawing add-on took the gap as it came.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.resize(1400, 800)
    w.show()
    w.new_document()
    w.tools.osnap_on = False
    yield w
    w.document.dirty = False
    w.close()


def _dimension(win, sign, y=0):
    """A dimension whose gap is 0.4 text heights, framed when ``sign``
    is negative."""
    doc = win.document.doc
    style = doc.dimstyles.get(doc.header.get("$DIMSTYLE", "Standard"))
    style.dxf.dimgap = sign * 0.4 * style.dxf.dimtxt
    for text in ("DIMLINEAR", f"0,{y}", f"50,{y}", f"25,{y + 10}"):
        win._on_command_submitted(text)
    dim = list(win.document.modelspace().query("DIMENSION"))[-1]
    block = list(doc.blocks.get(dim.dxf.geometry))
    (text,) = [e for e in block if e.dxftype() == "MTEXT"]
    lines = [e for e in block if e.dxftype() == "LINE"]
    return text, lines


def _frame(text, lines):
    """The lines that lie within two text heights of the text."""
    h = text.dxf.char_height
    x, y = text.dxf.insert.x, text.dxf.insert.y
    return [ln for ln in lines
            if all(abs(p.x - x) < 10 * h and abs(p.y - y) < 2 * h
                   for p in (ln.dxf.start, ln.dxf.end))
            and (ln.dxf.end - ln.dxf.start).magnitude < 10 * h]


def test_a_negative_gap_frames_the_text(win):
    text, lines = _dimension(win, -1)
    frame = _frame(text, lines)
    assert len(frame) == 4
    xs = [p.x for ln in frame for p in (ln.dxf.start, ln.dxf.end)]
    ys = [p.y for ln in frame for p in (ln.dxf.start, ln.dxf.end)]
    h = text.dxf.char_height
    assert min(ys) < text.dxf.insert.y - h / 2 < text.dxf.insert.y + h / 2 \
        < max(ys)
    assert min(xs) < text.dxf.insert.x < max(xs)


def test_the_framed_text_sits_as_far_off_the_line_as_unframed(win):
    plain, _ = _dimension(win, 1)
    framed, _ = _dimension(win, -1, y=100)
    assert framed.dxf.insert.y - 100 == pytest.approx(plain.dxf.insert.y)


def test_a_positive_gap_draws_no_frame(win):
    text, lines = _dimension(win, 1)
    assert _frame(text, lines) == []


def test_centred_text_cuts_the_dimension_line_at_its_frame(win):
    doc = win.document.doc
    style = doc.dimstyles.get(doc.header.get("$DIMSTYLE", "Standard"))
    style.dxf.dimtad = 0
    text, lines = _dimension(win, -1)
    frame = _frame(text, lines)
    left = min(p.x for ln in frame for p in (ln.dxf.start, ln.dxf.end))
    y = text.dxf.insert.y
    dimline = [ln for ln in lines if ln not in frame
               and abs(ln.dxf.start.y - y) < 1e-9
               and abs(ln.dxf.end.y - y) < 1e-9]
    ends = [max(ln.dxf.start.x, ln.dxf.end.x) for ln in dimline
            if min(ln.dxf.start.x, ln.dxf.end.x) < left]
    assert ends and max(ends) == pytest.approx(left)
