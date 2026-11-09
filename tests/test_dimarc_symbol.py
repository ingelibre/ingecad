# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""An arc length dimension draws its arc symbol, as DIMARCSYM says.

A review video put an arc length dimension next to a linear one and the
two read the same: ezdxf drew the length but never the small arc that
tells an arc length from a chord. DIMARCSYM 0 puts it before the text,
1 above it, 2 leaves it out.
"""
from __future__ import annotations

import pytest

from core import actions


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


def _dimarc(win, dimarcsym):
    doc = win.document.doc
    style = doc.dimstyles.get(doc.header.get("$DIMSTYLE", "Standard"))
    style.dxf.dimarcsym = dimarcsym
    tools = win.tools
    tools._execute(actions.add_arc_3p((10, 0), (0, 10), (-10, 0)))
    win._on_command_submitted("ZOOM")
    win._on_command_submitted("E")
    win._on_command_submitted("DIMARC")
    tools.on_hover(0, 10, threshold_world=0.5)
    tools.on_click(0, 10)
    tools.on_hover(0, 15, threshold_world=0.5)
    tools.on_click(0, 15)
    (dim,) = win.document.modelspace().query("ARC_DIMENSION")
    block = list(doc.blocks.get(dim.dxf.geometry))
    (text,) = [e for e in block if e.dxftype() == "MTEXT"]
    height = text.dxf.char_height
    symbols = [e for e in block if e.dxftype() == "ARC"
               and e.dxf.radius < height]
    return text, symbols


def test_the_symbol_goes_before_the_text(win):
    text, symbols = _dimarc(win, 0)
    (symbol,) = symbols
    assert symbol.dxf.center.x < text.dxf.insert.x
    assert abs(symbol.dxf.center.y - text.dxf.insert.y) < text.dxf.char_height


def test_the_symbol_goes_above_the_text(win):
    text, symbols = _dimarc(win, 1)
    (symbol,) = symbols
    assert symbol.dxf.center.y > text.dxf.insert.y
    assert abs(symbol.dxf.center.x - text.dxf.insert.x) < text.dxf.char_height


def test_none_leaves_it_out(win):
    _text, symbols = _dimarc(win, 2)
    assert symbols == []
