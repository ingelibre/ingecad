# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""UCS (#91): typed points, the readout, ORTHO and POLAR follow it.

A tester asked for "temporary UCSs to define the origin and orientation
of the X/Y axes". Every test types on the command line, as the AutoCAD
hand does: UCS, the points, then LINE with coordinates read in the UCS.
"""
from __future__ import annotations

import math

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    window = MainWindow()
    window.show()
    window.new_document()
    qapp.processEvents()
    yield window
    window.document.dirty = False
    window.close()


def _type(win, *texts):
    edit = win.command_line.input
    for text in texts:
        edit.setFocus()
        if text:
            QTest.keyClicks(edit, text)
        QTest.keyClick(edit, Qt.Key_Return)


def _last_line(win):
    line = list(win.document.modelspace().query("LINE"))[-1]
    s, e = line.dxf.start, line.dxf.end
    return (round(s.x, 9), round(s.y, 9)), (round(e.x, 9), round(e.y, 9))


def _history(win):
    return win.command_line.history.toPlainText()


def test_a_moved_origin_shifts_what_is_typed(win):
    _type(win, "UCS", "100,50", "")             # origin, <Accept>
    _type(win, "LINE", "0,0", "10,0", "")
    assert _last_line(win) == ((100, 50), (110, 50))


def test_a_turned_ucs_turns_absolute_relative_and_polar_input(win):
    _type(win, "UCS", "100,50", "100,60", "")   # X along the world's +Y
    _type(win, "LINE", "0,0", "10,0", "@0,5", "@5<0", "")
    lines = [((round(l.dxf.start.x, 9), round(l.dxf.start.y, 9)),
              (round(l.dxf.end.x, 9), round(l.dxf.end.y, 9)))
             for l in win.document.modelspace().query("LINE")]
    assert lines == [((100, 50), (100, 60)),    # 10 along the UCS X
                     ((100, 60), (95, 60)),     # 5 along the UCS Y
                     ((95, 60), (95, 65))]      # 5 at 0 degrees of the UCS


def test_world_previous_and_undo_put_it_back(win):
    from core import ucs

    _type(win, "UCS", "10,10", "")
    _type(win, "UCS", "Z", "30")                # turn the moved one 30
    current = ucs.current(win.document)
    assert (current.ox, current.oy) == (10, 10)
    assert current.degrees == pytest.approx(30)
    _type(win, "UCS", "P")                      # Previous: the moved one
    assert ucs.current(win.document) == ucs.Ucs(10, 10, 0.0)
    _type(win, "UCS", "")                       # <World>
    assert ucs.current(win.document).is_world
    win.history.undo()                          # undo the World...
    assert ucs.current(win.document) == ucs.Ucs(10, 10, 0.0)


def test_z_takes_ninety_by_default(win):
    from core import ucs

    _type(win, "UCS", "Z", "")
    assert ucs.current(win.document).degrees == pytest.approx(90)
    _type(win, "LINE", "0,0", "10,0", "")
    assert _last_line(win) == ((0, 0), (0, 10))


def test_object_aligns_to_the_line_from_its_nearer_end(win):
    from core import ucs

    _type(win, "LINE", "0,0", "30,40", "")
    _type(win, "UCS", "OB", "27,36")            # near the 30,40 end
    current = ucs.current(win.document)
    assert (current.ox, current.oy) == (30, 40)
    assert current.degrees == pytest.approx(math.degrees(math.atan2(-40, -30)))


def test_named_save_restore_list_and_delete(win):
    from core import ucs

    _type(win, "UCS", "5,5", "")
    _type(win, "UCS", "NA", "S", "Lote")
    _type(win, "UCS", "")                       # back to World
    _type(win, "UCS", "NA", "R", "lote")        # names match without case
    assert ucs.current(win.document) == ucs.Ucs(5, 5, 0.0)
    assert ucs.current_name(win.document.doc) == "Lote"
    _type(win, "UCS", "NA", "?", "")
    assert '"Lote"' in _history(win)
    _type(win, "UCS", "NA", "D", "Lote")
    assert ucs.named(win.document.doc) == {}
    assert ucs.current_name(win.document.doc) == ""


def test_ortho_runs_along_the_ucs_axes(win):
    _type(win, "UCS", "0,0", "10,10", "")       # axes at 45 degrees
    tools = win.tools
    tools.ortho_on = True
    _type(win, "LINE", "0,0")
    x, y = tools.resolved_point(9.0, 11.0)      # near the UCS X
    assert x == pytest.approx(y)
    assert math.hypot(x, y) == pytest.approx((9 + 11) / math.sqrt(2))
    _type(win, "")


def test_the_readout_shows_ucs_coordinates(win):
    _type(win, "UCS", "100,50", "100,60", "")
    win._on_cursor_moved(100.0, 60.0)           # 10 along the UCS X
    text = win._coords_label.text()
    numbers = [float(v) for v in text.replace(" ", "").split(",")]
    assert numbers == [pytest.approx(10.0), pytest.approx(0.0, abs=1e-9)]


def test_the_ucs_travels_in_the_dxf(win, tmp_path):
    from core import ucs
    from core.document import Document

    _type(win, "UCS", "100,50", "100,60", "")
    _type(win, "UCS", "NA", "S", "EJE")
    path = tmp_path / "ucs.dxf"
    win.document.save_as(path)
    back = Document.load(path)
    current = ucs.stored(back.doc)
    assert (current.ox, current.oy) == (100, 50)
    assert current.degrees == pytest.approx(90)
    saved = ucs.named(back.doc)["EJE"]
    assert (saved.ox, saved.oy) == (100, 50)
    assert saved.degrees == pytest.approx(90)


def test_a_sheet_keeps_the_world(win):
    from core import ucs

    _type(win, "UCS", "100,50", "")
    layout = next(name for name in win.document.doc.layout_names()
                  if name != "Model")
    win.switch_layout(layout)
    assert not win.document.current_space().is_modelspace
    assert ucs.current(win.document).is_world
    _type(win, "LINE", "0,0", "10,0", "")       # on the sheet: world points
    (line,) = win.document.current_space().query("LINE")
    assert (line.dxf.start.x, line.dxf.start.y) == (0, 0)
    win.switch_layout("Model")
    assert ucs.current(win.document) == ucs.Ucs(100, 50, 0.0)


def _active_ucs(doc):
    from core.ucs import _active_viewports

    (vport,) = _active_viewports(doc)[:1]
    origin, xaxis = vport.dxf.ucs_origin, vport.dxf.ucs_xaxis
    return (round(origin[0], 9), round(origin[1], 9),
            round(xaxis[0], 9), round(xaxis[1], 9))


def test_the_active_viewport_carries_it_too(win):
    """AutoCAD (and ODA File Converter) read the model's current UCS from
    the *Active viewport: with the header alone a saved DWG came back in
    the world."""
    _type(win, "UCS", "100,50", "100,60", "")
    assert _active_ucs(win.document.doc) == (100, 50, 0, 1)
    win.history.undo()
    assert _active_ucs(win.document.doc) == (0, 0, 1, 0)


def test_the_ucs_travels_in_the_dwg(win, tmp_path):
    from core import ucs
    from formats.dwg_bridge import find_dxf2dwg, load_dwg

    if find_dxf2dwg() is None:
        pytest.skip("LibreDWG not available")
    _type(win, "UCS", "100,50", "100,60", "")
    _type(win, "UCS", "NA", "S", "EJE")
    _engine, warnings = win.document.save_as(tmp_path / "ucs.dwg")
    assert warnings == []
    back = load_dwg(tmp_path / "ucs.dwg")
    assert _active_ucs(back.doc) == (100, 50, 0, 1)
    assert ucs.current_name(back.doc) == "EJE"
    assert "EJE" in ucs.named(back.doc)


def test_spanish_scp_and_its_option_names(win):
    """The Spanish name and options work; the English ones never stop."""
    from core import i18n, ucs

    i18n.set_language("es")
    try:
        _type(win, "SCP", "5,5", "")
        assert ucs.current(win.document) == ucs.Ucs(5, 5, 0.0)
        _type(win, "SCP", "Nombre", "Guardar", "lote")
        _type(win, "SCP", "Universal")
        assert ucs.current(win.document).is_world
        _type(win, "SCP", "NA", "R", "lote")
        assert ucs.current(win.document) == ucs.Ucs(5, 5, 0.0)
    finally:
        i18n.set_language("en")


def test_the_new_ucs_menu(win):
    from core import ucs

    actions = win._menu_bar.actions()            # held: see test_plugins
    tools_menu = next(a.menu() for a in actions if a.text() == "Tools")
    entries = tools_menu.actions()
    assert "New UCS" in [a.text() for a in entries]
    win._ucs_from_menu("Z")
    _type(win, "45")
    win._ucs_from_menu("O")                     # origin only: the axes stay
    _type(win, "10,0")
    current = ucs.current(win.document)
    assert current.degrees == pytest.approx(45)
    assert (current.ox, current.oy) == pytest.approx(
        (10 / math.sqrt(2), 10 / math.sqrt(2)))
    win._ucs_from_menu("W")
    assert ucs.current(win.document).is_world
