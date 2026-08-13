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


# -- the object snap dropdown --------------------------------------------------

def test_the_osnap_menu_lists_every_mode_in_autocads_order(win):
    from core import osnap as osnap_modes

    from views.osnap_dialog import OsnapSettingsDialog

    dialog = OsnapSettingsDialog(win, win.tools.osnap_modes, True)
    try:
        assert list(dialog._boxes) == [m.key for m in osnap_modes.MODES]
        # The three we cannot do yet are listed, disabled, with a reason.
        for key in ("EXT", "APP", "PAR"):
            box = dialog._boxes[key]
            assert not box.isEnabled() and box.toolTip()
        assert "END" in dialog.modes()
    finally:
        dialog.deleteLater()


def test_ticking_a_mode_changes_what_the_engine_is_asked_for(win):
    assert "QUA" not in win.tools.osnap_modes
    win._set_osnap_mode("QUA", True)
    assert "QUA" in win.tools.osnap_modes
    win._set_osnap_mode("END", False)
    assert "END" not in win.tools.osnap_modes


def test_the_running_snaps_survive_a_restart(win, qapp):
    from views.main_window import MainWindow

    win._set_osnap_mode("QUA", True)
    win._set_osnap_mode("MID", False)
    expected = set(win.tools.osnap_modes)

    other = MainWindow()
    try:
        assert other.tools.osnap_modes == expected
    finally:
        other.close()


def test_f3_is_remembered_apart_from_the_ticks(win, qapp):
    """AutoCAD keeps which modes are ticked when the snap is switched off."""
    from views.main_window import MainWindow

    before = set(win.tools.osnap_modes)
    win._toggle_mode("osnap")
    assert win.tools.osnap_on is False

    other = MainWindow()
    try:
        assert other.tools.osnap_on is False
        assert other.tools.osnap_modes == before
    finally:
        other.close()
    win._toggle_mode("osnap")


def test_the_settings_dialog_can_clear_and_select_everything(win):
    from core import osnap as osnap_modes

    from views.osnap_dialog import OsnapSettingsDialog

    dialog = OsnapSettingsDialog(win, win.tools.osnap_modes, True)
    try:
        dialog._set_all(False)
        assert dialog.modes() == set()
        dialog._set_all(True)
        assert dialog.modes() == set(osnap_modes.AVAILABLE)
    finally:
        dialog.deleteLater()


def test_the_standard_toolbar_exists_with_the_classic_order(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        win.new_document("mm")
        labels = [a.text() for a in win._standard_toolbar.actions()
                  if not a.isSeparator()]
        assert labels[:4] == ["New", "Open", "Save", "Plot"]
        assert "Match Properties" in labels and "Zoom Previous" in labels
        # and REVCLOUD reached the Draw toolbar (it had a glyph, no button)
        draw = [a.text() for a in win._draw_toolbar.actions()]
        assert any("Revision" in t for t in draw)
    finally:
        win.close()


def test_clean_screen_hides_all_but_the_command_window(qapp):
    """AutoCAD's CLEANSCREEN rule: toolbars and docks go, the command
    window, menu and status bar stay — and restoring honors what was
    already hidden."""
    from PySide6.QtWidgets import QDockWidget, QToolBar

    from views.main_window import MainWindow

    win = MainWindow()
    try:
        win.new_document("mm")
        win.show()
        win._draw_toolbar.hide()          # the user had hidden this one
        menu_before = win.menuBar().isVisible()
        win.toggle_clean_screen()
        assert not win._standard_toolbar.isVisible()
        assert not win._modify_toolbar.isVisible()
        assert not win._layers_dock.isVisible()
        assert win._command_dock.isVisible()
        assert win.menuBar().isVisible() == menu_before   # untouched
        win.toggle_clean_screen()
        assert win._standard_toolbar.isVisible()
        assert win._layers_dock.isVisible()
        assert not win._draw_toolbar.isVisible()   # stays as the user left it
        # the explicit commands force a state instead of toggling
        win.dispatcher.submit("CLEANSCREENON")
        assert not win._modify_toolbar.isVisible()
        win.dispatcher.submit("CLEANSCREENON")     # already on: no flip
        assert not win._modify_toolbar.isVisible()
        win.dispatcher.submit("CLEANSCREENOFF")
        assert win._modify_toolbar.isVisible()
    finally:
        win.close()


def test_the_shortcut_menu_follows_the_reference(qapp):
    """Marco asked for the right-click menu to match AutoCAD's. It is built
    from the reference's own Access Methods: every command whose page names
    the shortcut menu, and nothing the app cannot do."""
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        win.new_document("mm")
        msp = win.document.modelspace()
        line = msp.add_line((0, 0), (10, 10))
        text = msp.add_text("hola", dxfattribs={"height": 2})
        poly = msp.add_lwpolyline([(0, 0), (5, 0), (5, 5)])
        win.tools._invalidate_geometry()

        def entries(selection):
            win.tools.selection = selection
            out = {}
            for act in win.build_canvas_context_menu().actions():
                if act.isSeparator():
                    continue
                sub = act.menu()
                out[act.text()] = ([a.text() for a in sub.actions()]
                                   if sub is not None else None)
            return out

        idle = entries(set())
        # Default mode: Pan and Zoom are documented "with no objects selected"
        assert "Pan" in idle and "Zoom" in idle
        assert idle["Zoom"] == ["Extents", "Window", "Previous"]
        assert "Undo" in idle and "Redo" in idle
        assert idle["Clipboard"] == ["Cut", "Copy", "Paste"]

        picked = entries({line.dxf.handle})
        # Edit mode: the five edit commands whose pages name the menu
        for label in ("Erase", "Move", "Copy Selection", "Scale", "Rotate"):
            assert label in picked, label
        assert picked["Draw Order"] == ["Bring to Front", "Send to Back"]
        assert "Properties" in picked and "Deselect All" in picked

        # type-specific entries, only for a single object of that kind
        assert "Edit..." in entries({text.dxf.handle})
        assert entries({poly.dxf.handle})["Polyline"] == ["Edit..."]
        assert "Edit..." not in entries({line.dxf.handle})
        assert "Polyline" not in entries({text.dxf.handle, poly.dxf.handle})
    finally:
        win.document.dirty = False
        win.close()
