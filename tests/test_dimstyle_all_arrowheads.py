# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Dimension Style dialog offers the twenty classic arrowheads.

It offered eight: the open 90, the origin indicator and the blank dot that
UNE-EN ISO 129-1 draws (a tester's eighth review) were missing, though the
renderer draws them all.
"""
from __future__ import annotations

import pytest

from views import dimstyle_dialog


def test_twenty_arrowheads_each_once():
    keys = [k for _label, k in dimstyle_dialog.arrow_items()]
    assert len(keys) == len(set(keys)) == 20
    assert {"OPEN90", "DOTBLANK", "ORIGIN", "ORIGIN2", "INTEGRAL"} <= set(keys)


@pytest.mark.parametrize("arrow", ["OPEN90", "DOTBLANK", "ORIGIN"])
def test_a_picked_arrowhead_is_drawn(qapp, clean_settings, arrow):
    from core import styles as style_ops
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    doc = win.document
    try:
        name = style_ops.current_dim_style(doc)
        editor = dimstyle_dialog.DimStyleEditorDialog(
            win, "test", style_ops.dim_style_attribs(doc, name),
            style_ops.text_style_names(doc), style_ops.fixed_text_heights(doc))
        editor.dimblk1.setCurrentIndex(editor.dimblk1.findData(arrow))
        win.history.execute(style_ops.SetDimStylePropsCommand(
            name, editor.changed_props()))
        win.after_style_change()
        editor.deleteLater()
        for text in ("DIMLINEAR", "0,0", "100,0", "50,10"):
            win._on_command_submitted(text)
        (dim,) = doc.modelspace().query("DIMENSION")
        block = doc.doc.blocks.get(dim.dxf.geometry)
        inserts = [e.dxf.name for e in block if e.dxftype() == "INSERT"]
    finally:
        doc.dirty = False
        win.close()
    assert inserts.count("_" + arrow) == 2
