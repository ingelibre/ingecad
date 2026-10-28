# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""What Rafael's sixth review video showed besides its headline issues,
found going through it frame by frame: the Xrefs palette still listing
the previous drawing after File > New, Qt's buttons in English under a
Spanish UI, "prueba.dwg.pdf", two "Point" entries in the Draw menu, a
WBLOCK that proposed block.dxf and lost its file silently, and a PLOT
dialog that forgot its last settings."""
from __future__ import annotations

from pathlib import Path

import ezdxf
from PySide6.QtCore import QCoreApplication, QTimer

from core import i18n


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


def test_file_new_empties_the_xrefs_palette(qapp, tmp_path):
    from ezdxf import xref as ezxref

    ref = ezdxf.new("R2018")
    ref.modelspace().add_line((0, 0), (10, 0))
    ref.saveas(tmp_path / "formato.dxf")
    host = ezdxf.new("R2018")
    ezxref.attach(host, block_name="formato", filename="formato.dxf", insert=(0, 0))
    host.saveas(tmp_path / "host.dxf")

    win = _window(qapp)
    try:
        win.open_path(tmp_path / "host.dxf")
        _wait(qapp, win)
        win.toggle_xrefs_panel()
        assert win._xrefs_panel.table.rowCount() == 1
        win.new_document()
        qapp.processEvents()
        assert win._xrefs_panel.table.rowCount() == 0, \
            "the palette still lists the previous drawing's reference"
    finally:
        win.document.dirty = False
        win.close()


def test_qt_own_buttons_follow_the_ui_language(qapp):
    win = _window(qapp)
    try:
        win._set_language("es")
        assert QCoreApplication.translate("QPlatformTheme", "Cancel") == "Cancelar"
        assert QCoreApplication.translate("QPlatformTheme", "Save") == "Guardar"
        win._set_language("en")
        assert QCoreApplication.translate("QPlatformTheme", "Cancel") == "Cancel"
    finally:
        win._set_language("en")
        i18n.set_language("en")
        win.close()


def test_an_unsaved_drawing_is_untitled_in_the_ui_language(qapp):
    from core.document import Document

    i18n.set_language("es")
    try:
        assert Document.new().name == "Sin nombre"
    finally:
        i18n.set_language("en")
    assert Document.new().name == "Untitled"


def test_save_pdf_proposes_the_drawing_name_without_dwg(qapp, tmp_path, monkeypatch):
    from views import file_dialogs, print_dialog

    seen = []
    monkeypatch.setattr(file_dialogs, "get_save_file",
                        lambda parent, caption, name, *a, **k: (seen.append(name), ("", ""))[1])
    win = _window(qapp)
    try:
        win.document.path = tmp_path / "prueba.dwg"
        dialog = print_dialog.PrintDialog(win)
        dialog._to_pdf()
        assert seen == ["prueba.pdf"]
        dialog.deleteLater()
    finally:
        win.document.path = None
        win.document.dirty = False
        win.close()


def test_the_draw_menu_has_one_point_entry_holding_point(qapp):
    win = _window(qapp)
    try:
        bar_actions = win._menu_bar.actions()    # held: see test_plugins
        draw = next(a.menu() for a in bar_actions if a.text() == "Draw")
        draw_actions = draw.actions()
        entries = [a for a in draw_actions if a.text() == "Point"]
        assert len(entries) == 1, "a Point item beside a Point submenu"
        sub = entries[0].menu()
        assert sub is not None
        sub_actions = sub.actions()
        labels = [a.text() for a in sub_actions]
        assert labels[:3] == ["Multiple Point", "Divide", "Measure"]
    finally:
        win.document.dirty = False
        win.close()


def test_point_states_the_point_modes_first(qapp):
    win = _window(qapp)
    try:
        said = []
        win.command_line.echo = lambda text, *a, **k: said.append(text)
        win.document.doc.header["$PDMODE"] = 3
        win.tools.start_tool("POINT")
        assert "Current point modes:  PDMODE=3  PDSIZE=0.0000" in said
        assert win.tools.current_prompt.startswith("Specify a point")
        win.tools.cancel()
    finally:
        win.document.dirty = False
        win.close()


def test_wblock_proposes_a_dwg_and_says_when_nothing_was_written(qapp, tmp_path,
                                                                  monkeypatch):
    from views import file_dialogs

    out = tmp_path / "bloque.dwg"
    asked = []

    def save(parent, caption, name, name_filter, **kwargs):
        asked.append((name, name_filter))
        return str(out), ""

    monkeypatch.setattr(file_dialogs, "get_save_file", save)
    win = _window(qapp)
    try:
        said = []
        win.command_line.echo = lambda text, *a, **k: said.append(text)
        win.tools.start_tool("WBLOCK")
        (name, name_filter), = asked
        assert name.endswith(".dwg") and name_filter.startswith("DWG")
        win.tools.cancel()                       # walks away at the prompt
        assert any("nothing was written" in s and str(out) in s for s in said)
        assert not out.exists()
    finally:
        win.document.dirty = False
        win.close()


def test_plot_reopens_with_the_last_settings(qapp, tmp_path, monkeypatch):
    from views import file_dialogs, print_dialog

    monkeypatch.setattr(file_dialogs, "get_save_file",
                        lambda *a, **k: (str(tmp_path / "out.pdf"), ""))
    opened = []
    real_exec = print_dialog.PrintDialog.exec

    def fake_exec(dialog):
        opened.append(dialog)
        if len(opened) == 1:
            dialog.units.setCurrentIndex(dialog.units.findData(1.0))   # mm
            dialog.scale.setCurrentIndex(dialog.scale.findText("1:1"))
            QTimer.singleShot(0, dialog._to_pdf)
        else:
            QTimer.singleShot(0, dialog.reject)
        return real_exec(dialog)

    monkeypatch.setattr(print_dialog.PrintDialog, "exec", fake_exec)
    win = _window(qapp)
    try:
        from core import actions

        win.tools._execute(actions.add_line((0, 0), (100, 50)))
        win._plot_dialog()
        assert (tmp_path / "out.pdf").exists()
        win._plot_dialog()
        second = opened[1]
        assert second.units.currentData() == 1.0
        assert second.scale.currentText() == "1:1"
    finally:
        win.document.dirty = False
        win.close()
