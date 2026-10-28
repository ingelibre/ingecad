# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Dimension Style Manager's Description says what a style changes.

Rafael's seventh review (12:45): "Mi estilo", made from ISO-25 with three
real changes (offset from origin 0, arrow 2, text height 2), was described
as "ISO-25 + annotative = True, dimadec = 0, dimarcsym = 0, dimasz = 2.0,
dimaunit = 0, dimazin = 0, dimblk1 = , ..." -- variables ISO-25 has with
the same value but does not write, counted as changes, internal names, and
cut at twelve so the real changes never showed.
"""
from __future__ import annotations

from core import styles as style_ops


def _window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document()
    win.resize(1000, 700)
    win.show()
    qapp.processEvents()
    return win


def _mi_estilo(document):
    """ISO-25's variables written out in full, as the style dialog's OK
    writes them, with Rafael's three changes."""
    iso = document.doc.dimstyles.get("ISO-25")
    # Start With: ISO-25 (what CreateNewDimStyleDialog hands the command)
    attribs = style_ops.dim_style_attribs(document, "ISO-25")
    for key in ("dimadec", "dimaunit", "dimazin", "dimdle", "dimdli",
                "dimdsep", "dimcen", "dimrnd"):
        attribs[key] = iso.dxf.get(key) if iso.dxf.hasattr(key) \
            else iso.dxf.get_default(key)
    attribs["dimtxsty"] = "Standard"
    attribs.update(dimexo=0.0, dimasz=2.0, dimtxt=2.0)
    style_ops.NewDimStyleCommand("Mi estilo", attribs).do(document)


def test_only_real_changes_are_differences(qapp):
    win = _window(qapp)
    try:
        _mi_estilo(win.document)
        diffs = dict(style_ops.dim_style_differences(
            win.document, "Mi estilo", "ISO-25"))
        assert set(diffs) == {"dimexo", "dimasz", "dimtxt"}, diffs
    finally:
        win.document.dirty = False
        win.close()


def test_the_manager_describes_them_in_words(qapp):
    from views.dimstyle_dialog import DimStyleManagerDialog

    win = _window(qapp)
    try:
        _mi_estilo(win.document)
        style_ops.SetCurrentDimStyleCommand("ISO-25").do(win.document)
        dialog = DimStyleManagerDialog(win)
        try:
            for row in range(dialog.list.count()):
                if dialog.list.item(row).text() == "Mi estilo":
                    dialog.list.setCurrentRow(row)
            text = dialog.description.toPlainText()
            assert text.startswith("ISO-25 + ")
            for word in ("Arrow size = 2", "Text height = 2",
                         "Offset from origin = 0"):
                assert word in text, text
            assert "dimadec" not in text and "DIMADEC" not in text, text
            assert text.count("=") == 3, text
        finally:
            dialog.deleteLater()
    finally:
        win.document.dirty = False
        win.close()
