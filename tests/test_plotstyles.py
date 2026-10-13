# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Plot style tables (.ctb) in PLOT and PUBLISH to one PDF (issue #41)."""
from __future__ import annotations

import os

import pytest

from core import plotstyles
from core.document import Document


@pytest.fixture
def styles_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))   # Windows
    return plotstyles.folder()


def test_the_four_standard_tables_are_written_once_and_load_back(styles_dir):
    names = plotstyles.available()
    assert names[0] == "acad.ctb"
    assert set(plotstyles.BUILTIN) <= set(names)
    for name in plotstyles.BUILTIN:
        table = plotstyles.load(name)
        assert table is not None, f"{name} did not load back"
    # a second call keeps the files (a user's edit would survive)
    stamp = (styles_dir / "monochrome.ctb").stat().st_mtime
    plotstyles.available()
    assert (styles_dir / "monochrome.ctb").stat().st_mtime == stamp


def test_pen_colours_follow_the_table(styles_dir):
    red = (255, 0, 0)
    assert plotstyles.load("acad.ctb").pen_color(1, red) == red
    assert plotstyles.load("monochrome.ctb").pen_color(1, red) == (0, 0, 0)
    grey = plotstyles.load("Grayscale.ctb").pen_color(1, red)
    assert grey[0] == grey[1] == grey[2] and 0 < grey[0] < 255
    screened = plotstyles.load("Screening 50%.ctb").pen_color(1, red)
    assert screened == (255, 128, 128)


def test_a_table_name_from_a_windows_drawing_resolves_case_insensitively(styles_dir):
    assert plotstyles.resolve("MONOCHROME.CTB") == styles_dir / "monochrome.ctb"
    assert plotstyles.resolve("") is None
    assert plotstyles.resolve("nothing.ctb") is None
    assert plotstyles.load("nothing.ctb") is None


def _drawing():
    doc = Document.new()
    doc.modelspace().add_line((0, 0), (100, 0), dxfattribs={"color": 1})
    doc.modelspace().add_line((0, 10), (100, 10), dxfattribs={"true_color": 0x00FF00})
    return doc


def _pen_colours(scene):
    return {item.pen().color().name() for item in scene.items() if hasattr(item, "pen")}


def test_plot_applies_the_table_to_aci_and_true_colours(qapp, styles_dir):
    from formats import pdf_out

    doc = _drawing()
    assert _pen_colours(pdf_out.build_graphics_scene(doc, "Model", ctb="")) \
        >= {"#ff0000", "#00ff00"}
    assert _pen_colours(pdf_out.build_graphics_scene(
        doc, "Model", ctb="monochrome.ctb")) == {"#000000"}


def test_the_layouts_own_table_is_the_default(qapp, styles_dir):
    from formats import pdf_out

    doc = _drawing()
    doc.doc.modelspace().dxf_layout.dxf.current_style_sheet = "monochrome.ctb"
    assert _pen_colours(pdf_out.build_graphics_scene(doc, "Model")) == {"#000000"}
    doc.doc.modelspace().dxf_layout.dxf.current_style_sheet = ""
    assert "#ff0000" in _pen_colours(pdf_out.build_graphics_scene(doc, "Model"))


def test_publish_writes_one_pdf_with_a_page_per_sheet(qapp, styles_dir, tmp_path):
    from formats import pdf_out

    doc = _drawing()
    a = doc.doc.layouts.new("A-01")
    a.add_line((10, 10), (200, 100))
    b = doc.doc.layouts.new("A-02")
    b.add_circle((100, 100), 40)
    out = tmp_path / "set.pdf"
    assert pdf_out.publish(doc, ["A-01", "A-02", "Model"], str(out),
                           ctb="monochrome.ctb") == 2
    data = out.read_bytes()
    assert data.count(b"/Type /Page\n") == 2 or data.count(b"/Type /Page") >= 2
    assert pdf_out.publish(doc, ["Model"], str(tmp_path / "none.pdf")) == 0


def test_the_publish_dialog_lists_the_sheets_checked_in_tab_order(qapp, styles_dir):
    from views.main_window import MainWindow
    from views.publish_dialog import PublishDialog, publish_selection

    win = MainWindow()
    win.show()
    win.new_document()
    try:
        win.document.doc.layouts.new("A-02")
        win.document.doc.layouts.new("A-01")
        dlg = PublishDialog(win)
        names = publish_selection(dlg)
        assert "Model" not in names and set(names) == {"Layout1", "A-02", "A-01"}
        from PySide6.QtCore import Qt
        dlg.layouts.item(0).setCheckState(Qt.Unchecked)
        assert len(publish_selection(dlg)) == 2
        dlg.deleteLater()
    finally:
        win.document.dirty = False
        win.close()
