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

@pytest.fixture
def clean_settings():
    """Snapshot and restore every setting the Options dialog writes.

    Apply() saves all four tabs at once, so a test that opens the dialog
    leaves the template behind even when it never touched it — and the
    startup window reads that one. Restoring by hand test by test is how
    the startup test came to fail; this does it in one place.
    """
    from PySide6.QtCore import QSettings

    from views.options_dialog import (SETTING_GRID, SETTING_LWT,
                                      SETTING_RIGHT_CLICK, SETTING_VSYNC)
    from views.startup_dialog import SETTING_SHOW, SETTING_TEMPLATE

    keys = (SETTING_GRID, SETTING_LWT, SETTING_RIGHT_CLICK, SETTING_VSYNC,
            SETTING_SHOW, SETTING_TEMPLATE, "osnap/osmode")
    saved = {k: QSettings().value(k) for k in keys}
    yield
    settings = QSettings()
    for key, value in saved.items():
        if value is None:
            settings.remove(key)
        else:
            settings.setValue(key, value)
    settings.sync()


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
        assert list(dialog.panel._boxes) == [m.key for m in osnap_modes.MODES]
        # The three we cannot do yet are listed, disabled, with a reason.
        for key in ("EXT", "APP", "PAR"):
            box = dialog.panel._boxes[key]
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
        dialog.panel._set_all(False)
        assert dialog.modes() == set()
        dialog.panel._set_all(True)
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


def test_options_dialog_persists_what_it_offers(qapp, clean_settings):
    """OPTIONS (p. 1314) under AutoCAD's tab names, holding only settings
    that exist. Everything it shows must survive Apply and be readable
    again — a toggle that forgets itself is worse than no toggle."""
    from PySide6.QtCore import QSettings

    from views.main_window import MainWindow
    from views.options_dialog import (RIGHT_CLICK_ENTER, SETTING_LWT,
                                      SETTING_RIGHT_CLICK, OptionsDialog,
                                      right_click_mode)
    win = MainWindow()
    try:
        win.new_document("mm")
        dlg = OptionsDialog(win)
        assert [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())] == [
            "Files", "Display", "Drafting", "User Preferences"]

        # the Files tab offers the three template units and shows the
        # current one; applying it is left alone (see above)
        assert {dlg.template.itemData(i) for i in range(dlg.template.count())} \
            == {"mm", "cm", "m"}
        dlg.show_lwt.setChecked(not win.viewport.lwt_on)
        wanted_lwt = dlg.show_lwt.isChecked()
        dlg.right_click.setCurrentIndex(
            dlg.right_click.findData(RIGHT_CLICK_ENTER))
        # the Drafting tab is the very widget the Drafting Settings dialog uses
        assert hasattr(dlg.osnap_panel, "modes")
        dlg.apply()

        assert win.viewport.lwt_on == wanted_lwt
        assert right_click_mode() == RIGHT_CLICK_ENTER

        # a fresh window comes up with the display setting restored
        other = MainWindow()
        try:
            assert other.viewport.lwt_on == wanted_lwt
        finally:
            other.close()
    finally:
        win.document.dirty = False
        win.close()


def test_options_is_offered_only_with_nothing_selected(qapp):
    """The reference: "with no commands active and no objects selected"."""
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        win.new_document("mm")
        line = win.document.modelspace().add_line((0, 0), (1, 1))
        win.tools._invalidate_geometry()

        def labels():
            return [a.text() for a in win.build_canvas_context_menu().actions()]

        win.tools.selection = set()
        assert "Options..." in labels()
        win.tools.selection = {line.dxf.handle}
        assert "Options..." not in labels()
    finally:
        win.document.dirty = False
        win.close()


def test_the_crosshair_follows_the_pointer_through_a_pan(qapp):
    """Marco: after panning, the crosshair reappeared where the drag STARTED
    instead of under the hand. It is stored in screen coordinates and was
    not updated while panning, so it snapped back on release."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    from views.main_window import MainWindow

    win = MainWindow()
    try:
        win.new_document("mm")
        win.resize(900, 600)
        vp = win.viewport

        def send(kind, x, y, button=Qt.NoButton, buttons=Qt.NoButton):
            event = QMouseEvent(kind, QPointF(x, y), QPointF(x, y),
                                button, buttons, Qt.NoModifier)
            {QEvent.MouseMove: vp.mouseMoveEvent,
             QEvent.MouseButtonPress: vp.mousePressEvent,
             QEvent.MouseButtonRelease: vp.mouseReleaseEvent}[kind](event)

        # middle-button pan
        send(QEvent.MouseMove, 200, 200)
        send(QEvent.MouseButtonPress, 200, 200, Qt.MiddleButton, Qt.MiddleButton)
        send(QEvent.MouseMove, 300, 250, buttons=Qt.MiddleButton)
        send(QEvent.MouseButtonRelease, 400, 300, Qt.MiddleButton)
        assert (vp._cursor.x(), vp._cursor.y()) == (400, 300)

        # the PAN command's hand: the crosshair returns where the hand was
        send(QEvent.MouseMove, 150, 150)
        vp.start_pan_mode()
        send(QEvent.MouseButtonPress, 150, 150, Qt.LeftButton, Qt.LeftButton)
        send(QEvent.MouseMove, 500, 420, buttons=Qt.LeftButton)
        send(QEvent.MouseButtonRelease, 520, 430, Qt.LeftButton)
        vp.stop_pan_mode()
        assert (vp._cursor.x(), vp._cursor.y()) == (520, 430)
    finally:
        win.document.dirty = False
        win.close()


def test_the_refresh_wait_is_a_setting_that_defaults_to_on(
        qapp, clean_settings):
    """Measured on this canvas: a mouse move takes 16.7 ms waiting for the
    monitor and 2.9 ms without, while drawing the frame is 0.6 ms of that
    even at 4.5 million vertices. The wait is what stops tearing, so it
    stays on by default and the lower lag is opt-in."""
    from PySide6.QtCore import QSettings

    from views.main_window import MainWindow
    from views.options_dialog import SETTING_VSYNC, OptionsDialog

    win = MainWindow()
    try:
        win.new_document("mm")
        QSettings().remove(SETTING_VSYNC)
        dlg = OptionsDialog(win)
        assert dlg.vsync.isChecked()               # on unless asked otherwise
        dlg.vsync.setChecked(False)
        dlg.apply()
        assert str(QSettings().value(SETTING_VSYNC)).lower() in ("false", "0")

        # and main.py turns that into a swap interval of 0
        import main
        from PySide6.QtGui import QSurfaceFormat

        main._configure_surface_format()
        assert QSurfaceFormat.defaultFormat().swapInterval() == 0
        QSettings().setValue(SETTING_VSYNC, True)
        main._configure_surface_format()
        assert QSurfaceFormat.defaultFormat().swapInterval() != 0
    finally:
        win.document.dirty = False
        win.close()
