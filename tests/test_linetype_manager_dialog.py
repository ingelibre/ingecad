# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Linetype Manager window, reached the way a user reaches it.

LINETYPE was "not available yet (arrives in Phase 6)" through 0.6.6, so
Format > Linetype answered nothing (Rafael's seventh review). Every test
here types the command on the command line, or picks "Other..." on the
Properties bar, and presses the window's own buttons.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from core import linetypes as lt_ops
from modal import drive_modal


def _window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.resize(1200, 800)
    win.new_document()
    qapp.processEvents()
    return win


def _type(win, text):
    edit = win.command_line.input
    edit.setFocus()
    QTest.keyClicks(edit, text)
    QTest.keyClick(edit, Qt.Key_Return)


def _run(qapp, win, how, action):
    """Open the manager ``how`` and run ``action(dialog)`` inside it."""
    from views.linetype_dialog import LinetypeManagerDialog

    errors: list[BaseException] = []
    drive_modal(LinetypeManagerDialog, action, errors)
    how(win)
    qapp.processEvents()
    if errors:
        raise errors[0]


def _load(dialog, *names, reload=False):
    """Press Load..., pick ``names``, accept (answering a reload prompt)."""
    from views.linetype_dialog import LoadLinetypesDialog

    inner: list[BaseException] = []

    def pick(load):
        load.ask_reload = lambda _name: reload
        from PySide6.QtCore import QItemSelectionModel

        rows = [load.table.item(r, 0).text() for r in range(load.table.rowCount())]
        model = load.table.selectionModel()
        for name in names:                       # Ctrl+click each one
            model.select(load.table.model().index(rows.index(name), 0),
                         QItemSelectionModel.Select | QItemSelectionModel.Rows)
        load.accept()

    drive_modal(LoadLinetypesDialog, pick, inner)
    dialog.load_button.click()
    if inner:
        raise inner[0]


@pytest.mark.parametrize("typed", ["LINETYPE", "LT", "ltype"])
def test_the_command_opens_the_manager_and_current_lands_on_ok(qapp, typed):
    win = _window(qapp)
    try:
        def inside(dialog):
            assert dialog.windowTitle() in ("Linetype Manager",
                                            "Administrador de tipos de línea")
            _load(dialog, "ACAD_ISO04W100")
            assert dialog.selected_names() == ["ACAD_ISO04W100"]
            dialog.current_button.click()
            dialog._ok()

        _run(qapp, win, lambda w: _type(w, typed), inside)
        doc = win.document.doc
        assert doc.header["$CELTYPE"] == "ACAD_ISO04W100"
        win._cmd_undo()          # Current (the OK step)
        assert doc.header["$CELTYPE"].upper() == "BYLAYER"
        win._cmd_undo()          # the Load
        assert not doc.linetypes.has_entry("ACAD_ISO04W100")
    finally:
        win.document.dirty = False
        win.close()


def test_cancel_keeps_the_settings_as_they_were(qapp):
    win = _window(qapp)
    try:
        header = win.document.doc.header
        before = (header["$LTSCALE"], header.get("$CELTSCALE", 1.0),
                  header.get("$CELTYPE", "ByLayer"))

        def inside(dialog):
            dialog.details_button.click()
            dialog.global_scale.setText("50")
            dialog.object_scale.setText("2")
            dialog.select("Continuous")
            dialog.current_button.click()
            dialog.reject()

        _run(qapp, win, lambda w: _type(w, "LINETYPE"), inside)
        assert (header["$LTSCALE"], header.get("$CELTSCALE", 1.0),
                header.get("$CELTYPE", "ByLayer")) == before
    finally:
        win.document.dirty = False
        win.close()


def test_details_set_the_three_scales_in_one_undo_step(qapp):
    win = _window(qapp)
    try:
        header = win.document.doc.header
        ltscale_before = header["$LTSCALE"]

        def inside(dialog):
            _load(dialog, "ACAD_ISO02W100")
            dialog.details_button.click()
            assert dialog.details.isVisible()
            dialog.global_scale.setText("50")
            assert dialog.pen_width.isEnabled(), "an ISO linetype is selected"
            dialog.pen_width.setCurrentIndex(dialog.pen_width.findData(0.5))
            dialog.pen_width.activated.emit(dialog.pen_width.currentIndex())
            assert dialog.object_scale.text() == "0.5000"
            dialog.paper_units.setChecked(False)
            dialog._ok()

        _run(qapp, win, lambda w: _type(w, "LINETYPE"), inside)
        assert header["$LTSCALE"] == pytest.approx(50)
        assert header["$CELTSCALE"] == pytest.approx(0.5)
        assert header["$PSLTSCALE"] == 0
        win._cmd_undo()
        assert header["$LTSCALE"] == pytest.approx(ltscale_before)
        assert header.get("$PSLTSCALE", 1) == 1
    finally:
        win.document.dirty = False
        win.close()


def test_delete_removes_only_the_unused(qapp):
    win = _window(qapp)
    try:
        doc = win.document.doc
        warnings: list[str] = []

        def inside(dialog):
            dialog.warn = warnings.append
            _load(dialog, "ACAD_ISO02W100", "ACAD_ISO03W100")
            doc.layers.add("Ejes", linetype="ACAD_ISO02W100")
            dialog.table.clearSelection()
            dialog.select("ACAD_ISO02W100")
            dialog.delete_button.click()
            assert warnings, "deleting a used linetype said nothing"
            dialog.table.clearSelection()
            dialog.select("ACAD_ISO03W100")
            dialog.delete_button.click()
            dialog._ok()

        _run(qapp, win, lambda w: _type(w, "LINETYPE"), inside)
        assert doc.linetypes.has_entry("ACAD_ISO02W100")
        assert not doc.linetypes.has_entry("ACAD_ISO03W100")
        win._cmd_undo()
        assert doc.linetypes.has_entry("ACAD_ISO03W100"), "Delete is undoable"
    finally:
        win.document.dirty = False
        win.close()


def test_rename_and_description_on_ok(qapp):
    win = _window(qapp)
    try:
        doc = win.document.doc
        layer = doc.layers.add("Ejes", linetype="Continuous")

        def inside(dialog):
            _load(dialog, "ACAD_ISO04W100")
            layer.dxf.linetype = "ACAD_ISO04W100"
            dialog.details_button.click()
            dialog.name_edit.setText("EJE")
            dialog.name_edit.editingFinished.emit()
            dialog.description_edit.setText("Eje de simetría")
            dialog.description_edit.editingFinished.emit()
            assert "EJE" in [dialog.table.item(r, 0).text()
                             for r in range(dialog.table.rowCount())]
            dialog._ok()

        _run(qapp, win, lambda w: _type(w, "LINETYPE"), inside)
        assert doc.linetypes.has_entry("EJE")
        assert layer.dxf.linetype == "EJE"
        assert lt_ops.description_of(win.document, "EJE") == "Eje de simetría"
        win._cmd_undo()
        assert layer.dxf.linetype == "ACAD_ISO04W100"
    finally:
        win.document.dirty = False
        win.close()


def test_filters_and_invert(qapp):
    win = _window(qapp)
    try:
        def inside(dialog):
            _load(dialog, "ACAD_ISO02W100")
            names = lambda: [dialog.table.item(r, 0).data(Qt.UserRole)  # noqa: E731
                             for r in range(dialog.table.rowCount())]
            assert names()[:2] == ["ByLayer", "ByBlock"]
            dialog.filter.setCurrentIndex(1)            # used
            assert "ACAD_ISO02W100" not in names()
            assert "Continuous" in names()
            dialog.invert.setChecked(True)              # unused
            assert "ACAD_ISO02W100" in names()
            assert "Continuous" not in names()
            dialog.reject()

        _run(qapp, win, lambda w: _type(w, "LINETYPE"), inside)
    finally:
        win.document.dirty = False
        win.close()


def test_load_reads_a_lin_file_and_reloads_on_yes(qapp, tmp_path):
    from views.linetype_dialog import LoadLinetypesDialog

    lin = tmp_path / "mine.lin"
    lin.write_text("*ACAD_ISO02W100,Mine\nA,20,-5\n*PROPIO,Propio\nA,7,-3\n",
                   encoding="cp1252")
    win = _window(qapp)
    try:
        doc = win.document.doc

        def inside(dialog):
            _load(dialog, "ACAD_ISO02W100")
            errors: list[BaseException] = []

            def pick(load):
                assert load.load_file(lin)
                assert load.file_name.text() == "mine.lin"
                load.ask_reload = lambda _n: True
                rows = [load.table.item(r, 0).text()
                        for r in range(load.table.rowCount())]
                assert rows == ["ACAD_ISO02W100", "PROPIO"]
                load.table.selectAll()
                load.accept()

            drive_modal(LoadLinetypesDialog, pick, errors)
            dialog.load_button.click()
            if errors:
                raise errors[0]
            dialog._ok()

        _run(qapp, win, lambda w: _type(w, "LINETYPE"), inside)
        assert lt_ops.pattern_of(win.document, "ACAD_ISO02W100") == [20.0, -5.0]
        assert lt_ops.pattern_of(win.document, "PROPIO") == [7.0, -3.0]
    finally:
        win.document.dirty = False
        win.close()


def test_the_properties_bar_other_opens_the_manager(qapp):
    from views.main_window import _OTHER_LINETYPE

    win = _window(qapp)
    try:
        combo = win._linetype_combo
        labels = [combo.itemText(i) for i in range(combo.count())]
        assert labels[0] in ("ByLayer", "PorCapa")
        index = combo.findData(_OTHER_LINETYPE)
        assert index == combo.count() - 1, "Other... is not the last entry"
        opened = []

        def inside(dialog):
            opened.append(True)
            dialog.reject()

        _run(qapp, win, lambda w: w._on_prop_linetype(index), inside)
        assert opened, "Other... did not open the Linetype Manager"
    finally:
        win.document.dirty = False
        win.close()


def test_dash_lt_typed_in_the_window_loads_from_the_proposed_file(qapp, monkeypatch):
    """-LT, L, a name, and the file dialog's Open on the file it proposes."""
    from views import file_dialogs

    proposed = []

    def fake_open(parent, caption, name_filter, preferred=None, select_file=None):
        proposed.append(select_file)
        return str(select_file)

    monkeypatch.setattr(file_dialogs, "get_open_file", fake_open)
    win = _window(qapp)
    try:
        for text in ("-LT", "L", "ACAD_ISO10W100", ""):
            _type(win, text)
        assert proposed and proposed[0] == lt_ops.standard_lin_file(win.document)
        assert win.document.doc.linetypes.has_entry("ACAD_ISO10W100")
        combo = win._linetype_combo
        assert combo.findData("ACAD_ISO10W100") >= 0, "the bar did not refresh"
        win._cmd_undo()
        assert not win.document.doc.linetypes.has_entry("ACAD_ISO10W100")
    finally:
        win.document.dirty = False
        win.close()


def test_library_descriptions_read_in_the_interface_language(qapp):
    """The release tour found "Dashed __ __" in a Spanish window: the
    library's wording is shown translated, the drawing keeps its own, and
    looking at a description without editing it changes nothing."""
    from core import i18n

    i18n.set_language("es")
    win = _window(qapp)
    try:
        def inside(dialog):
            _load(dialog, "DASHED", "ACAD_ISO02W100")
            rows = {dialog.table.item(r, 0).data(Qt.UserRole):
                    dialog.table.item(r, 2).text()
                    for r in range(dialog.table.rowCount())}
            assert rows["DASHED"].startswith("Trazos __ __")
            assert rows["ACAD_ISO02W100"].startswith("Trazo ISO __")
            dialog.select("DASHED")
            dialog.details_button.click()
            assert dialog.description_edit.text().startswith("Trazos")
            dialog.description_edit.editingFinished.emit()
            dialog._ok()

        _run(qapp, win, lambda w: _type(w, "LINETYPE"), inside)
        stored = win.document.doc.linetypes.get("DASHED").dxf.description
        assert stored.startswith("Dashed __"), "the drawing keeps its wording"
    finally:
        i18n.set_language("en")
        win.document.dirty = False
        win.close()
