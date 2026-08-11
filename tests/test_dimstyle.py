# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""DIMSTYLE: the Dimension Style Manager, the tabbed editor, the commands."""
from __future__ import annotations

import pytest

from core import actions
from core import styles as style_ops
from core.commands import History
from core.document import Document


def _doc_with_dim():
    doc = Document.new()
    style_ops.install_default_styles(doc)
    history = History(doc)
    history.execute(actions.dim_linear((0, 0), (10, 0), (5, 4)))
    return doc, history


def _dim_text_height(doc):
    dim = doc.modelspace().query("DIMENSION")[0]
    blk = doc.doc.blocks[dim.dxf.geometry]
    for e in blk:
        if e.dxftype() == "MTEXT":
            return e.dxf.char_height
        if e.dxftype() == "TEXT":
            return e.dxf.height
    return None


# -- commands ------------------------------------------------------------------

def test_modify_style_rerenders_existing_dimensions():
    doc, history = _doc_with_dim()
    assert _dim_text_height(doc) == pytest.approx(2.5)
    history.execute(style_ops.SetDimStylePropsCommand("ISO-25",
                                                      {"dimtxt": 5.0}))
    assert _dim_text_height(doc) == pytest.approx(5.0)   # AutoCAD behavior
    history.undo()
    assert _dim_text_height(doc) == pytest.approx(2.5)
    # exactly one *D block per dimension at every step (no leaks)
    blocks = [b.name for b in doc.doc.blocks if b.name.startswith("*D")]
    assert len(blocks) == 1


def test_rename_style_repoints_dimensions_and_header():
    doc, history = _doc_with_dim()
    doc.doc.header["$DIMSTYLE"] = "ISO-25"
    history.execute(style_ops.RenameDimStyleCommand("ISO-25", "Mio"))
    assert "Mio" in doc.doc.dimstyles and "ISO-25" not in doc.doc.dimstyles
    assert doc.doc.header["$DIMSTYLE"] == "Mio"
    assert doc.modelspace().query("DIMENSION")[0].dxf.dimstyle == "Mio"
    history.undo()
    assert "ISO-25" in doc.doc.dimstyles
    assert doc.modelspace().query("DIMENSION")[0].dxf.dimstyle == "ISO-25"


def test_dim_style_attribs_excludes_identity():
    doc, _ = _doc_with_dim()
    attribs = style_ops.dim_style_attribs(doc, "ISO-25")
    assert "name" not in attribs and "handle" not in attribs
    assert attribs["dimtxt"] == pytest.approx(2.5)


# -- the editor dialog ---------------------------------------------------------

def test_editor_round_trips_iso25(qapp):
    from views.dimstyle_dialog import DimStyleEditorDialog

    doc, _ = _doc_with_dim()
    attribs = style_ops.dim_style_attribs(doc, "ISO-25")
    dlg = DimStyleEditorDialog(None, "t", attribs, ["Standard"])
    props = dlg.result_props()
    assert props["dimtxt"] == pytest.approx(2.5)
    assert props["dimasz"] == pytest.approx(2.5)
    assert props["dimexe"] == pytest.approx(1.25)
    assert props["dimtad"] == 1                      # ISO: text above
    assert props["dimdsep"] == ord(",")
    assert props["dimzin"] == 8                      # trailing suppressed
    dlg.deleteLater()


def test_editor_maps_special_controls(qapp):
    from views.dimstyle_dialog import DimStyleEditorDialog

    doc, _ = _doc_with_dim()
    attribs = style_ops.dim_style_attribs(doc, "ISO-25")
    dlg = DimStyleEditorDialog(None, "t", attribs, ["Standard"])
    # Center marks: Line mode -> negative DIMCEN
    dlg.cen_mode.setCurrentIndex(2)                  # Line
    dlg.cen_size.setValue(3.0)
    # Frame around text -> negative DIMGAP
    dlg.frame_text.setChecked(True)
    dlg.dimgap.setValue(1.0)
    # Text alignment Horizontal -> DIMTIH=1, DIMTOH=1
    dlg.text_align.setCurrentIndex(0)
    # Prefix/suffix -> DIMPOST
    dlg.prefix.setText("~")
    dlg.suffix.setText(" m")
    # First arrowhead syncs the second (official behavior)
    dlg.dimblk1.setCurrentIndex(4)                   # Architectural tick
    props = dlg.result_props()
    assert props["dimcen"] == pytest.approx(-3.0)
    assert props["dimgap"] == pytest.approx(-1.0)
    assert props["dimtih"] == 1 and props["dimtoh"] == 1
    assert props["dimpost"] == "~<> m"
    assert props["dimblk1"] == "ARCHTICK"
    assert props["dimblk2"] == "ARCHTICK"
    dlg.deleteLater()


def test_preview_renders_ink(qapp):
    from views.dimstyle_dialog import render_dim_preview, _PREVIEW_BG

    doc, _ = _doc_with_dim()
    pm = render_dim_preview(style_ops.dim_style_attribs(doc, "ISO-25"))
    img = pm.toImage()
    bg = _PREVIEW_BG.rgb()
    ink = sum(1 for x in range(0, img.width(), 3)
              for y in range(0, img.height(), 3)
              if img.pixel(x, y) != bg)
    assert ink > 50                                  # something real drawn


# -- the manager window --------------------------------------------------------

def test_manager_lists_and_sets_current(qapp):
    from views.main_window import MainWindow
    from views.dimstyle_dialog import DimStyleManagerDialog

    win = MainWindow()
    win.new_document()
    try:
        dlg = DimStyleManagerDialog(win)
        names = [dlg.list.item(i).data(0x0100)      # Qt.UserRole
                 for i in range(dlg.list.count())]
        assert "ISO-25" in names and "Acot-100" in names
        for i in range(dlg.list.count()):
            if dlg.list.item(i).data(0x0100) == "Acot-100":
                dlg.list.setCurrentRow(i)
        dlg._set_current()
        assert style_ops.current_dim_style(win.document) == "Acot-100"
        win.history.undo()
        dlg.deleteLater()
    finally:
        win.close()


def test_manager_modify_executes_command(qapp, monkeypatch):
    from views.main_window import MainWindow
    from views import dimstyle_dialog as mod

    win = MainWindow()
    win.new_document()
    try:
        dlg = mod.DimStyleManagerDialog(win)
        for i in range(dlg.list.count()):
            if dlg.list.item(i).data(0x0100) == "ISO-25":
                dlg.list.setCurrentRow(i)

        class FakeEditor:
            def __init__(self, *a, **k):
                self._attribs = a[2]

            def exec(self):
                return True

            def result_props(self):
                props = dict(self._attribs)
                props["dimtxt"] = 4.0
                return {"dimtxt": 4.0}

        monkeypatch.setattr(mod, "DimStyleEditorDialog", FakeEditor)
        # The seeded height depends on the drawing's template (a metres
        # drawing carries 0.0025, a millimetre one 2.5), so undo is checked
        # against what was there, not against a hard-coded number.
        style = win.document.doc.dimstyles.get("ISO-25")
        seeded = style.dxf.dimtxt
        dlg._modify()
        assert style.dxf.dimtxt == pytest.approx(4.0)
        win.history.undo()
        assert style.dxf.dimtxt == pytest.approx(seeded)
        dlg.deleteLater()
    finally:
        win.close()
