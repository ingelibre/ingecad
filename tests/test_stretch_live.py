# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""STRETCH drags the objects live and ends without rebuilding indexes.

GeoCad Yaguarete (Fernando Bellocchio's plugin) had to patch both: the drag
showed only a rubber band, and every STRETCH threw the pick and snap
indexes away -- its command did not say which entities it touched -- so
the next mouse move rebuilt them over the whole drawing.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest


def _type(win, text):
    edit = win.command_line.input
    edit.setFocus()
    if text:
        QTest.keyClicks(edit, text)
    QTest.keyClick(edit, Qt.Key_Return)


def test_the_drag_shows_the_stretched_shape_and_the_end_is_surgical(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        win.show()
        win.new_document()
        for text in ("RECTANG", "0,0", "40,20"):
            _type(win, text)
        rect = win.document.modelspace().query("LWPOLYLINE")[0]
        t = win.tools
        t.osnap_on = False
        for text in ("STRETCH", "C", "35,-5", "45,25", "", "40,0"):
            _type(win, text)
        assert t.tool is not None and t.tool.name == "STRETCH"
        segments = t.tool.preview_segments((50.0, 0.0))
        ends = {(round(a[0], 6), round(a[1], 6)) for a, _b in segments[1:]} | \
               {(round(b[0], 6), round(b[1], 6)) for _a, b in segments[1:]}
        assert {(50, 0), (50, 20), (0, 0), (0, 20)} <= ends, segments
        assert [tuple(p) for p in rect.get_points("xy")][1] == (40, 0), \
            "the preview changed the drawing"
        for cache in (t.index, t.snap_engine):     # as the warmer leaves them
            if cache._dirty:
                cache._build()
        regens = []
        real = win.regen_in_memory
        win.regen_in_memory = lambda *a, **k: (regens.append(1), real(*a, **k))
        _type(win, "50,0")
        assert sorted({round(p[0], 6) for p in rect.get_points("xy")}) == [0, 50]
        assert not regens and not t._regen_timer.isActive(), \
            "STRETCH ended in a full regeneration"
        assert not t.index._dirty and not t.snap_engine._dirty, (
            "the pick and snap indexes were thrown away: the next mouse "
            "move rebuilds them over the whole drawing")
        assert t.index.pick((50, 10), 0.5) == rect.dxf.handle
        win.regen_in_memory = real
        win.history.undo()
        assert sorted({round(p[0], 6) for p in rect.get_points("xy")}) == [0, 40]
    finally:
        win.document.dirty = False
        win.close()
