# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""CHPROP: the properties of a selection, typed (reference p. 323).

Found missing by the release tour (2026-10-10): CHPROP is how an AutoCAD
hand moves objects to a layer without reaching for the mouse. Every test
types on the command line.
"""
from __future__ import annotations

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
    for start, end in (("0,0", "10,0"), ("0,5", "10,5")):
        for text in ("LINE", start, end, ""):
            _type(window, text)
    _type(window, "-LAYER")
    for text in ("N", "cotas", ""):
        _type(window, text)
    yield window
    window.document.dirty = False
    window.close()


def _type(win, text):
    edit = win.command_line.input
    edit.setFocus()
    if text:
        QTest.keyClicks(edit, text)
    QTest.keyClick(edit, Qt.Key_Return)


def _lines(win):
    return list(win.document.modelspace().query("LINE"))


def test_layer_color_and_scale_in_one_run_undo_each(win):
    for text in ("CHPROP", "ALL", "", "LA", "cotas", "C", "red",
                 "S", "2.5", ""):
        _type(win, text)
    lines = _lines(win)
    assert {l.dxf.layer for l in lines} == {"cotas"}
    assert {l.dxf.color for l in lines} == {1}
    assert {l.dxf.ltscale for l in lines} == {2.5}
    assert win.tools.tool is None, "Enter at the menu ends CHPROP"
    win.history.undo()
    assert {l.dxf.get("ltscale", 1.0) for l in lines} == {1.0}
    assert {l.dxf.color for l in lines} == {1}


def test_the_prompt_shows_the_current_value_or_varies(win):
    lines = _lines(win)
    lines[0].dxf.color = 3
    for text in ("CHPROP", "ALL", "", "C"):
        _type(win, text)
    assert win.tools.current_prompt.endswith("<varies>:") \
        or win.tools.current_prompt.endswith("<varía>:")
    _type(win, "")                       # Enter keeps it
    assert lines[0].dxf.color == 3
    win.tools.cancel()


def test_a_missing_layer_is_refused_and_the_menu_returns(win):
    for text in ("CHPROP", "ALL", "", "LA", "nope"):
        _type(win, text)
    history = win.command_line.history.toPlainText()
    assert 'Cannot find layer "nope"' in history \
        or 'No se encuentra la capa "nope"' in history
    assert {l.dxf.layer for l in _lines(win)} == {"0"}
    assert win.tools.tool is not None, "still in CHPROP"
    win.tools.cancel()


def test_a_library_linetype_is_loaded_on_the_way(win):
    assert "DASHED" not in win.document.doc.linetypes
    for text in ("CHPROP", "ALL", "", "LT", "DASHED", "LW", "0.31", ""):
        _type(win, text)
    lines = _lines(win)
    assert {l.dxf.linetype for l in lines} == {"DASHED"}
    assert {l.dxf.lineweight for l in lines} == {30}, "snapped to 0.30 mm"


def test_a_colour_pick_replaces_a_true_colour(win):
    """GeoCad Yaguareté had to patch this: polygons that came from QGIS
    carry a true colour (group 420), which wins over the ACI, so picking a
    colour changed nothing on screen. AutoCAD's pick replaces both."""
    line = _lines(win)[0]
    line.dxf.true_color = 0x00FF8000
    for text in ("CHPROP", "ALL", "", "C", "5", ""):
        _type(win, text)
    assert not line.dxf.hasattr("true_color")
    assert line.dxf.color == 5
    win.history.undo()
    assert line.dxf.true_color == 0x00FF8000
