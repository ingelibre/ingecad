# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The commands AutoCAD squares to the UCS, squared to it here (#91).

In a turned UCS a rectangle, a polygon, a horizontal xline, a rectangular
array, a block, a text, a hatch pattern, a horizontal dimension and an
ordinate datum all run along the UCS's axes, and ID and DIST read in it.
Every test types on the command line; the UCS used is turned 90 degrees
(its X along the world's +Y) or 30 degrees, so a world-squared result
cannot pass by accident.
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


def _r(p):
    return (round(p[0], 6) + 0.0, round(p[1], 6) + 0.0)


def _turned_90(win):
    _type(win, "UCS", "100,50", "100,60", "")      # X along the world's +Y


def _history(win):
    return win.command_line.history.toPlainText()


def test_rectang_is_square_to_the_ucs(win):
    _type(win, "UCS", "Z", "30")      # 90 would square it to the world too
    _type(win, "RECTANG", "0,0", "10,5")
    (rect,) = win.document.modelspace().query("LWPOLYLINE")
    c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
    assert sorted(_r(p) for p in rect.get_points("xy")) == sorted(
        _r((x * c - y * s, x * s + y * c))
        for x, y in [(0, 0), (10, 0), (10, 5), (0, 5)])


def test_polygon_by_typed_radius_has_its_bottom_edge_on_the_ucs_x(win):
    _type(win, "UCS", "Z", "30")
    _type(win, "POLYGON", "4", "0,0", "C", "5")
    (poly,) = win.document.modelspace().query("LWPOLYLINE")
    points = [p for p in poly.get_points("xy")]
    edges = [math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 90.0
             for a, b in zip(points, points[1:] + points[:1])]
    assert all(e == pytest.approx(30.0) for e in edges)


def test_xline_hor_and_ver_run_along_the_ucs(win):
    _turned_90(win)
    _type(win, "XLINE", "H", "0,0", "")
    _type(win, "XLINE", "V", "0,0", "")
    hor, ver = win.document.modelspace().query("XLINE")
    assert _r(hor.dxf.unit_vector) in ((0, 1), (0, -1))
    assert _r(ver.dxf.unit_vector) in ((1, 0), (-1, 0))


def test_rectangular_array_rows_and_columns_follow_the_ucs(win):
    _turned_90(win)
    _type(win, "CIRCLE", "0,0", "1")
    _type(win, "-ARRAY", "L", "", "R", "1", "2", "10")
    centers = sorted(_r(c.dxf.center) for c in
                     win.document.modelspace().query("CIRCLE"))
    assert centers == [(100, 50), (100, 60)]


def test_insert_rotation_is_measured_from_the_ucs_x(win, monkeypatch):
    doc = win.document.doc
    doc.blocks.new("MARCA").add_line((0, 0), (1, 0))
    _turned_90(win)
    # the Insert dialog's choice (a modal dialog hangs offscreen)
    monkeypatch.setattr(win.tools, "_ask_choice",
                        lambda *args, **kwargs: "MARCA")
    _type(win, "INSERT", "0,0")
    (ref,) = win.document.modelspace().query("INSERT")
    assert ref.dxf.rotation % 360.0 == pytest.approx(90.0)
    assert _r(ref.dxf.insert) == (100, 50)


def test_text_default_rotation_runs_along_the_ucs_x(win):
    _turned_90(win)
    _type(win, "TEXT", "0,0", "2.5", "")         # <0>: along the UCS's X
    QTest.keyClicks(win.viewport, "ABC")         # typed on the canvas
    QTest.keyClick(win.viewport, Qt.Key_Escape)
    (text,) = win.document.modelspace().query("TEXT")
    assert text.dxf.rotation % 360.0 == pytest.approx(90.0)
    assert _r(text.dxf.insert) == (100, 50)


def test_hatch_pattern_angle_is_measured_from_the_ucs_x(win):
    _type(win, "UCS", "Z", "30")
    _type(win, "-HATCH", "P", "ANSI31", "1", "0", "W", "",
          "0,0", "10,0", "10,10", "", "")
    (hatch,) = win.document.modelspace().query("HATCH")
    assert hatch.dxf.pattern_angle == pytest.approx(30.0)


def test_dimlinear_horizontal_is_the_ucs_x(win):
    _turned_90(win)
    _type(win, "DIMLINEAR", "0,0", "10,0", "5,-4")
    (dim,) = win.document.modelspace().query("DIMENSION")
    assert dim.dxf.angle % 360.0 == pytest.approx(90.0)
    assert dim.get_measurement() == pytest.approx(10.0)


def test_dimordinate_measures_from_the_ucs_origin(win):
    _turned_90(win)
    _type(win, "DIMORDINATE", "7,3", "7,9")       # leader along the UCS Y
    (dim,) = win.document.modelspace().query("DIMENSION")
    assert _r(dim.dxf.defpoint) == (100, 50)       # the datum: UCS origin
    assert _r(dim.dxf.defpoint2) == (97, 57)       # the feature, in place
    block = win.document.doc.blocks.get(dim.dxf.geometry)
    texts = [e.plain_text() for e in block if e.dxftype() == "MTEXT"]
    assert texts == ["7"]                          # its X in the UCS


def test_id_and_dist_read_in_the_ucs(win):
    _turned_90(win)
    _type(win, "ID", "3,4")
    assert "X = 3" in _history(win) and "Y = 4" in _history(win)
    _type(win, "DIST", "0,0", "0,5")
    tail = _history(win)[-300:]
    assert "Angle in XY Plane = 90" in tail
    assert "Delta X = 0" in tail and "Delta Y = 5" in tail


def test_mtext_runs_along_the_ucs_x():
    from core import actions, ucs
    from core.templates import new_document

    document = new_document("mm")
    frame = ucs.Ucs(100.0, 50.0, math.pi / 2)
    command = actions.add_mtext((100, 50), (90, 70), "ABC", 2.5, frame=frame)
    command.do(document)
    (mtext,) = document.doc.modelspace().query("MTEXT")
    assert mtext.dxf.rotation == pytest.approx(90.0)
    assert mtext.dxf.width == pytest.approx(20.0)  # along the UCS X
    assert _r(mtext.dxf.insert) == (90, 50)        # its top-left corner
