# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Three requests from Rafael's sixth review, chosen by Marco for 0.6.6:
one click to give the selection the current annotation scale (OpenCAD
Studio's "Add Current Scale"), a new drawing's Layout1 that comes with a
viewport onto the model, and PAGESETUP on the Model tab."""
from __future__ import annotations

import ezdxf
from PySide6.QtCore import QTimer

from core import actions, annotative


def _window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.resize(1000, 700)
    win.new_document()
    qapp.processEvents()
    return win


def _wait(qapp, win):
    import time

    t0 = time.monotonic()
    while (win._open_thread is not None or win._regen_worker is not None) \
            and time.monotonic() - t0 < 30:
        qapp.processEvents()
    qapp.processEvents()


def _annotative_text(win):
    win.tools._execute(actions.add_text((0, 0), "2.50", 2.5))
    text = win.document.doc.modelspace().query("TEXT")[-1]
    win.tools._execute(annotative.AnnotativePropertyCommand([text], True))
    return text


# -- 2. Add Current Scale ---------------------------------------------------------

def test_the_status_bar_button_adds_the_current_scale_to_the_selection(qapp):
    win = _window(qapp)
    try:
        if win.annoautoscale() > 0:
            win._set_annoautoscale(-win.annoautoscale())
        text = _annotative_text(win)
        assert win.set_annotation_scale("1:50")
        scale = annotative.find_scale(win.document.doc, "1:50")
        assert not annotative.has_scale(text, scale)
        win.tools.selection = {text.dxf.handle}
        win._anno_add_btn.click()
        assert annotative.has_scale(text, scale), "the button added nothing"
        win._cmd_undo()
        assert not annotative.has_scale(text, scale), "not one undo step"
        win._cmd_redo()
        win.tools.selection = {text.dxf.handle}
        win.tools.start_tool("AIOBJECTSCALEREMOVE")
        assert not annotative.has_scale(text, scale)
    finally:
        win.document.dirty = False
        win.close()


def test_add_current_scale_on_objects_that_already_have_it_finishes(qapp):
    """Rafael's seventh review, 22:01-22:19: + on annotative dimensions
    already at 1:1 printed nothing and took a second Enter. The command
    counted them in ``skipped``, which the tool controller reads as the list
    of entities an edit could not move -- an int there raised TypeError and
    the tool never finished."""
    win = _window(qapp)
    try:
        text = _annotative_text(win)            # born at the current scale
        scale = annotative.scale_or_default(win.document.doc)
        assert annotative.has_scale(text, scale)
        win.tools.selection = {text.dxf.handle}
        win._anno_add_btn.click()
        qapp.processEvents()
        assert win.tools.tool is None, "the tool is left waiting"
        shown = win.command_line.history.toPlainText()
        assert "already supported" in shown or "ya admit" in shown, shown[-200:]
    finally:
        win.document.dirty = False
        win.close()


def test_the_scale_list_offers_the_standard_scales_on_a_foreign_drawing(qapp, tmp_path):
    doc = ezdxf.new("R2018")
    doc.modelspace().add_line((0, 0), (10, 0))
    doc.saveas(tmp_path / "plain.dxf")
    assert not annotative.scale_list(doc)
    win = _window(qapp)
    try:
        win.open_path(tmp_path / "plain.dxf")
        _wait(qapp, win)
        win._refresh_annotation_controls()
        combo = win._anno_scale_combo
        names = [combo.itemText(i) for i in range(combo.count())]
        assert {"1:1", "1:50", "1:100", "2:1"} <= set(names), names
        assert win.set_annotation_scale("1:50")
        assert annotative.current_scale(win.document.doc).name == "1:50"
    finally:
        win.document.dirty = False
        win.close()


# -- 4. Layout1 comes with a viewport -----------------------------------------------

def _viewports(win, name):
    from core.layouts import visible_viewports

    return visible_viewports(win.document.doc.layouts.get(name))


def test_a_new_drawings_layout1_opens_with_a_viewport_on_the_model(qapp):
    win = _window(qapp)
    try:
        win.tools._execute(actions.add_line((0, 0), (5000, 3000)))
        win.switch_layout("Layout1")
        _wait(qapp, win)
        (vp,) = _viewports(win, "Layout1")
        cx, cy = vp.dxf.view_center_point.x, vp.dxf.view_center_point.y
        assert (round(cx), round(cy)) == (2500, 1500), "the model is not in view"
        win.switch_layout("Model")
        _wait(qapp, win)
        win.switch_layout("Layout1")
        _wait(qapp, win)
        assert len(_viewports(win, "Layout1")) == 1, "a second visit added another"
    finally:
        win.document.dirty = False
        win.close()


def test_a_new_layout_gets_one_but_an_opened_drawings_empty_sheet_does_not(qapp, tmp_path):
    doc = ezdxf.new("R2018")
    doc.modelspace().add_line((0, 0), (10, 0))
    doc.saveas(tmp_path / "sheet.dxf")
    win = _window(qapp)
    try:
        win.open_path(tmp_path / "sheet.dxf")
        _wait(qapp, win)
        win.switch_layout("Layout1")
        _wait(qapp, win)
        assert _viewports(win, "Layout1") == [], "the colleague's empty sheet changed"
        win._new_layout_tab()
        win.switch_layout("Layout2")
        _wait(qapp, win)
        assert len(_viewports(win, "Layout2")) == 1
    finally:
        win.document.dirty = False
        win.close()


# -- 5. PAGESETUP on the Model tab ---------------------------------------------------

def test_pagesetup_on_the_model_tab_feeds_plot(qapp, monkeypatch):
    from views import page_setup_dialog, print_dialog

    real_exec = page_setup_dialog.PageSetupDialog.exec

    def setup(dialog):
        a4 = next(i for i in range(dialog.paper.count())
                  if str(dialog.paper.itemText(i)).startswith("ISO A4"))
        dialog.paper.setCurrentIndex(a4)
        dialog.portrait.setChecked(True)
        dialog.area.setCurrentIndex(dialog.area.findData(1))      # extents
        QTimer.singleShot(0, dialog.accept)
        return real_exec(dialog)

    monkeypatch.setattr(page_setup_dialog.PageSetupDialog, "exec", setup)
    win = _window(qapp)
    try:
        win.tools._execute(actions.add_line((0, 0), (100, 50)))
        assert win._active_layout == "Model"
        before = (win.document.doc.modelspace().dxf.get("limmin"),
                  win.document.doc.modelspace().dxf.get("limmax"))
        win._cmd_pagesetup()
        model = win.document.doc.modelspace()
        assert model.dxf.paper_width < model.dxf.paper_height, "portrait not stored"
        assert (model.dxf.get("limmin"), model.dxf.get("limmax")) == before, \
            "the model's limits were overwritten with a sheet's"
        dialog = print_dialog.PrintDialog(win)
        assert dialog.orientation.currentData() is False
        assert dialog.area.currentData() == "extents"
        dialog.deleteLater()
    finally:
        win.document.dirty = False
        win.close()


# -- 1. Selection filter by type ----------------------------------------------------

def _drawing_with_dimensions(win):
    win.tools._execute(actions.add_line((0, 0), (100, 0)))
    win.tools._execute(actions.add_circle((50, 30), 10))
    win.tools._execute(actions.dim_linear((0, 0), (100, 0), (50, -15)))
    win.tools._execute(actions.dim_linear((0, 0), (0, 40), (-15, 20)))
    msp = win.document.doc.modelspace()
    return {e.dxf.handle for e in msp.query("DIMENSION")}


def test_a_window_over_everything_takes_only_the_dimensions(qapp):
    win = _window(qapp)
    try:
        dims = _drawing_with_dimensions(win)
        said = []
        win.command_line.echo = lambda text, *a, **k: said.append(text)
        win.set_pick_filter({"Dimension"})
        assert win._pick_filter_btn.isChecked(), "the button does not show it is on"
        win.tools.osnap_on = False
        win.tools.on_click(-50.0, -50.0)            # window, left to right
        win.tools.on_click(200.0, 100.0)
        assert win.tools.selection == dims
        assert any("left out by the selection filter" in s for s in said)
        win.tools.clear_selection()
        assert win.tools.select_all() == len(dims), "Ctrl+A ignored the filter"
        win.set_pick_filter(None)
        win.tools.clear_selection()
        assert win.tools.select_all() == 4
        assert not win._pick_filter_btn.isChecked()
    finally:
        win.document.dirty = False
        win.close()


def test_the_popup_lists_the_types_present_and_ticking_all_switches_it_off(qapp):
    from PySide6.QtCore import Qt

    from views.pick_filter_popup import PickFilterPopup

    win = _window(qapp)
    try:
        _drawing_with_dimensions(win)
        popup = PickFilterPopup(win)
        items = popup._items()
        assert [i.data(Qt.UserRole) for i in items] == ["Circle", "Dimension", "Line"]
        assert all(i.checkState() == Qt.Checked for i in items)
        popup.none_btn.click()
        items[1].setCheckState(Qt.Checked)           # Dimension only
        assert win.tools.pick_filter == frozenset({"Dimension"})
        popup.all_btn.click()
        assert win.tools.pick_filter is None
        popup.deleteLater()
    finally:
        win.document.dirty = False
        win.close()


def test_a_dimension_is_a_cota_in_spanish_not_the_menu_word(qapp):
    from core import i18n, pickfilter

    i18n.set_language("es")
    try:
        assert pickfilter.display("Dimension") == "Cota"
        assert pickfilter.display("Line") == "Línea"
    finally:
        i18n.set_language("en")
    assert pickfilter.display("Dimension") == "Dimension"


def test_add_current_scale_on_plain_objects_says_the_missing_step(qapp):
    win = _window(qapp)
    try:
        win.tools._execute(actions.add_text((0, 0), "plain", 2.5))
        text = win.document.doc.modelspace().query("TEXT")[-1]
        win.tools.selection = {text.dxf.handle}
        win._anno_add_btn.click()
        qapp.processEvents()
        shown = win.command_line.history.toPlainText()
        assert "Properties > Annotative" in shown or "Propiedades > Anotativo" in shown
    finally:
        win.document.dirty = False
        win.close()
