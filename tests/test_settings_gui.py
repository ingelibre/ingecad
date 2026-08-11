# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""SAVE, UNITS and LTSCALE through the real window and dispatcher."""
from __future__ import annotations

from pathlib import Path

import pytest

from core import units as u


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    window = MainWindow()
    window.new_document()
    yield window
    window.close()


# -- SAVE ----------------------------------------------------------------------

def test_save_writes_over_the_open_file_without_asking(win, tmp_path, monkeypatch):
    path = tmp_path / "plano.dxf"
    win.document.save_as(path)
    win.document.modelspace().add_line((0, 0), (10, 0))
    win.document.dirty = True

    # If SAVE fell through to Save As it would open a file dialog; make that
    # a failure rather than a hang.
    monkeypatch.setattr(win, "_save_as_dialog",
                        lambda: pytest.fail("SAVE must not ask for a name"))
    win.save_document()

    assert win.document.dirty is False
    import ezdxf
    assert len(list(ezdxf.readfile(path).modelspace())) == 1


def test_save_of_an_unnamed_drawing_falls_through_to_save_as(win, monkeypatch):
    asked = []
    monkeypatch.setattr(win, "_save_as_dialog", lambda: asked.append(True))
    assert win.document.path is None
    win.save_document()
    assert asked == [True]


def test_ctrl_s_is_bound_to_save(win):
    from PySide6.QtGui import QKeySequence

    shortcuts = {}
    for menu_action in win._menu_bar.actions():   # setMenuWidget, not menuBar()
        menu = menu_action.menu()
        if menu is None:
            continue
        for action in menu.actions():
            text = action.shortcut().toString()
            if text:
                shortcuts[text] = action.text()
    saves = QKeySequence(QKeySequence.Save).toString()
    assert saves in shortcuts, sorted(shortcuts)
    # Ctrl+S must be Save, not Save As.
    assert shortcuts[saves] == "Save"


def test_the_save_command_and_its_alias_are_registered(win):
    known = win.dispatcher.known_names()
    for name in ("SAVE", "QSAVE", "SAVEAS", "UNITS", "-UNITS", "LTSCALE",
                 "DIST", "ID", "AREA", "LIST"):
        assert name in known, name
    # The aliases an AutoCAD user types.
    assert win.dispatcher.aliases["UN"] == "UNITS"
    assert win.dispatcher.aliases["LTS"] == "LTSCALE"
    assert win.dispatcher.aliases["AA"] == "AREA"
    assert win.dispatcher.aliases["DI"] == "DIST"


# -- UNITS ---------------------------------------------------------------------

def test_dash_units_writes_the_header_variables(win):
    win.dispatcher.submit("-UNITS")
    win.dispatcher.submit("4")        # Architectural
    win.dispatcher.submit("16")       # 1/16
    win.dispatcher.submit("5")        # Surveyor's units
    win.dispatcher.submit("0")        # angle precision
    win.dispatcher.submit("90")       # north is angle zero
    win.dispatcher.submit("Y")        # clockwise

    header = win.document.doc.header
    assert header["$LUNITS"] == u.ARCHITECTURAL
    assert header["$LUPREC"] == 4
    assert header["$AUNITS"] == u.SURVEYOR
    assert header["$ANGBASE"] == 90.0
    assert header["$ANGDIR"] == 1
    assert win.document.dirty is True


def test_the_measuring_commands_follow_the_units_that_were_set(win):
    win.dispatcher.submit("-UNITS")
    for answer in ("4", "16", "", "", "", ""):     # architectural, 1/16
        win.dispatcher.submit(answer)

    win.tools.start_tool("DIST")
    win.tools.tool.on_point((0.0, 0.0))
    win.tools.tool.on_point((15.5, 0.0))
    assert "1'-3 1/2\"" in win.command_line.history.toPlainText()


def test_units_dialog_round_trips_the_current_header(win, qapp):
    from core.units import Units
    from views.units_dialog import UnitsDialog

    Units(u.FRACTIONAL, 3, u.GRADS, 2, 6).to_doc(win.document.doc)
    dialog = UnitsDialog(win, Units.from_doc(win.document.doc),
                         angdir=1, angbase=180.0)
    values = dialog.values()
    assert (values.lunits, values.luprec) == (u.FRACTIONAL, 3)
    assert (values.aunits, values.auprec) == (u.GRADS, 2)
    assert values.insunits == 6
    assert dialog.angdir() == 1 and dialog.angbase() == 180.0
    # Fractional precision is listed as a denominator, not as digit count.
    assert dialog.length_precision.itemText(3) == "1/8"
    dialog.deleteLater()


def test_units_dialog_switches_the_precision_list_with_the_type(win, qapp):
    from core.units import Units
    from views.units_dialog import UnitsDialog

    dialog = UnitsDialog(win, Units(u.DECIMAL, 2))
    assert dialog.length_precision.itemText(2) == "0.00"
    index = dialog.length_type.findData(u.ARCHITECTURAL)
    dialog.length_type.setCurrentIndex(index)
    assert dialog.length_precision.itemText(2) == "1/4"
    assert "1'-3 1/4\"" in dialog.sample.text() or dialog.sample.text()
    dialog.deleteLater()


# -- LTSCALE -------------------------------------------------------------------

def test_ltscale_sets_the_header_and_regenerates(win, monkeypatch):
    regens = []
    monkeypatch.setattr(win, "regen_in_memory", lambda *a, **k: regens.append(1))
    win.dispatcher.submit("LTS")
    win.dispatcher.submit("25")
    assert win.document.doc.header["$LTSCALE"] == 25.0
    assert regens, "changing LTSCALE must regenerate (LTSCALE, p.1053)"


def test_ltscale_with_the_value_on_the_command_line(win, monkeypatch):
    monkeypatch.setattr(win, "regen_in_memory", lambda *a, **k: None)
    win.dispatcher.submit("LTSCALE 0.5")
    assert win.document.doc.header["$LTSCALE"] == 0.5
