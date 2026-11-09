# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""DIMTXT and DIMASZ typed set the current dimension style's text height
and arrow size, as DIMSCALE does (a tester's eighth review: classic CAD
users type them, and IngeCAD said 'Unknown command').
"""
from __future__ import annotations

import pytest


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.show()
    w.new_document()
    yield w
    w.document.dirty = False
    w.close()


def _style_value(win, key):
    from core import styles as style_ops

    doc = win.document
    return style_ops.dim_style_attribs(
        doc, doc.doc.header.get("$DIMSTYLE", "Standard")).get(key)


@pytest.mark.parametrize("name, value", [("DIMTXT", "3.5"), ("DIMASZ", "1,8")])
def test_typed_then_value_sets_the_current_style(win, name, value):
    win._on_command_submitted(name)
    win._on_command_submitted(value)
    history = win.command_line.history.toPlainText()
    assert "Unknown command" not in history
    assert _style_value(win, name.lower()) == pytest.approx(
        float(value.replace(",", ".")))
    win._on_command_submitted("U")
    assert _style_value(win, name.lower()) != pytest.approx(
        float(value.replace(",", ".")))


def test_a_new_dimension_takes_the_new_text_height(win):
    win._on_command_submitted("DIMTXT")
    win._on_command_submitted("7")
    for text in ("DIMLINEAR", "0,0", "100,0", "50,10"):
        win._on_command_submitted(text)
    (dim,) = win.document.modelspace().query("DIMENSION")
    block = win.document.doc.blocks.get(dim.dxf.geometry)
    (mtext,) = [e for e in block if e.dxftype() == "MTEXT"]
    scale = _style_value(win, "dimscale") or 1.0
    assert mtext.dxf.char_height == pytest.approx(7.0 * scale)


def test_setvar_reaches_them(win):
    for text in ("SETVAR", "DIMASZ", "4"):
        win._on_command_submitted(text)
    assert _style_value(win, "dimasz") == pytest.approx(4.0)
