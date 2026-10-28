# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""DRAWORDER (SORTENTSTABLE + canvas groups) and the layer express tools."""
from __future__ import annotations

import pytest

from core.commands import History
from core.document import Document
from core.draworder import DrawOrderCommand, order_groups


def _doc_with_two_solids():
    doc = Document.new()
    msp = doc.modelspace()
    doc.doc.layers.add("ROJA", color=1)
    doc.doc.layers.add("VERDE", color=3)
    s1 = msp.add_solid([(0, 0), (10, 0), (0, 10), (10, 10)],
                       dxfattribs={"layer": "ROJA"})
    s2 = msp.add_solid([(2, 2), (12, 2), (2, 12), (12, 12)],
                       dxfattribs={"layer": "VERDE"})
    return doc, s1, s2


def test_back_writes_a_sort_handle_below_every_natural_one():
    doc, s1, _s2 = _doc_with_two_solids()
    history = History(doc)
    history.execute(DrawOrderCommand([s1], "back"))
    assert order_groups(doc.modelspace()) == {s1.dxf.handle: -1}
    # and it is a REAL SORTENTSTABLE that survives the DXF round trip
    mapping = dict(doc.modelspace().get_redraw_order())
    assert int(mapping[s1.dxf.handle], 16) < int(s1.dxf.handle, 16)


def test_front_goes_above_and_undo_restores():
    doc, _s1, s2 = _doc_with_two_solids()
    history = History(doc)
    history.execute(DrawOrderCommand([s2], "front"))
    assert order_groups(doc.modelspace()) == {s2.dxf.handle: 1}
    history.undo()
    assert order_groups(doc.modelspace()) == {}


def test_the_canvas_honors_the_groups():
    """Back → its bucket packs first (draws under); front → packs last."""
    from render.backend import build_scene

    doc, s1, s2 = _doc_with_two_solids()
    history = History(doc)
    history.execute(DrawOrderCommand([s1], "back"))
    scene = build_scene(doc)
    start_of = {h: r[0][1] for h, r in scene.handle_ranges.items()}
    assert start_of[s1.dxf.handle] < start_of[s2.dxf.handle]
    history.undo()
    history.execute(DrawOrderCommand([s1], "front"))
    scene = build_scene(doc)
    start_of = {h: r[0][1] for h, r in scene.handle_ranges.items()}
    assert start_of[s1.dxf.handle] > start_of[s2.dxf.handle]


# -- layer tools ---------------------------------------------------------------

def _win(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document("mm")
    doc = win.document
    doc.doc.layers.add("MUROS", color=1)
    doc.doc.layers.add("COTAS", color=3)
    doc.doc.layers.add("EJES", color=5)
    return win


def test_layiso_offs_everything_else_and_layuniso_restores(qapp):
    win = _win(qapp)
    try:
        doc = win.document
        entity = doc.modelspace().add_line((0, 0), (1, 1),
                                           dxfattribs={"layer": "MUROS"})
        win.tools.start_tool("LAYISO")
        win.tools.tool.on_selection([entity])
        layers = doc.doc.layers
        assert layers.get("MUROS").is_on()
        assert not layers.get("COTAS").is_on()
        assert not layers.get("EJES").is_on()
        win._cmd_layuniso()
        assert layers.get("COTAS").is_on() and layers.get("EJES").is_on()
    finally:
        win.close()


def test_layoff_turns_off_the_picked_layer_with_undo(qapp):
    win = _win(qapp)
    try:
        doc = win.document
        doc.modelspace().add_line((0, 0), (5, 5), dxfattribs={"layer": "COTAS"})
        win.tools.start_tool("LAYOFF")
        win.tools.tool.on_point((2.5, 2.5))
        assert not doc.doc.layers.get("COTAS").is_on()
        win._cmd_undo()
        assert doc.doc.layers.get("COTAS").is_on()
    finally:
        win.close()


def test_layon_turns_every_layer_on_in_one_step(qapp):
    win = _win(qapp)
    try:
        doc = win.document
        doc.doc.layers.get("COTAS").off()
        doc.doc.layers.get("EJES").off()
        win._cmd_layon()
        assert doc.doc.layers.get("COTAS").is_on()
        assert doc.doc.layers.get("EJES").is_on()
        win._cmd_undo()
        assert not doc.doc.layers.get("COTAS").is_on()
    finally:
        win.close()


def test_draw_order_menu_entries_act_on_the_selection(qapp):
    """Marco asked how to put one object above another — the answer existed
    (DRAWORDER) but only as a command with a Front/Back prompt. The menu and
    the canvas shortcut menu now do it in one click, and with nothing
    selected they ask for objects and then apply without a second question
    (the reference lists the shortcut menu among DRAWORDER's access methods,
    p. 662)."""
    from core.draworder import order_groups
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        win.new_document("mm")
        msp = win.document.modelspace()
        under = msp.add_lwpolyline([(0, 0), (10, 0), (10, 10)], close=True)
        over = msp.add_line((0, 5), (10, 5))
        win.tools._invalidate_geometry()

        win.tools.selection = {under.dxf.handle}
        win._draworder("back")
        assert order_groups(msp).get(under.dxf.handle) == -1
        assert order_groups(msp).get(over.dxf.handle) in (None, 0)

        win.tools.selection = {over.dxf.handle}
        win._draworder("front")
        assert order_groups(msp).get(over.dxf.handle) == 1

        win.history.undo()
        assert order_groups(msp).get(over.dxf.handle) in (None, 0)

        # nothing selected: the command runs and remembers the direction
        win.tools.selection = set()
        win._draworder("front")
        assert win.tools.tool is not None
        assert win.tools.tool.name == "DRAWORDER"
        assert win.tools.tool.mode == "front"
        win.tools.cancel()
    finally:
        win.document.dirty = False
        win.close()


# -- LAYFRZ / LAYTHW / LAYLCK / LAYULK (#40), typed and clicked for real -------
def _line_on(win, layer, p1, p2):
    """Drawn through a Command on ``layer``, as a user would: current layer
    set, LINE's action run -- so the pick index knows it."""
    from core import actions

    header = win.document.doc.header
    before = header.get("$CLAYER", "0")
    header["$CLAYER"] = layer
    try:
        win.history.execute(actions.add_line(p1, p2))
    finally:
        header["$CLAYER"] = before


def _type(win, text):
    win._on_command_submitted(text)


def test_layfrz_freezes_each_picked_layer_until_enter_with_undo(qapp):
    win = _win(qapp)
    try:
        layers = win.document.doc.layers
        _line_on(win, "COTAS", (0, 0), (10, 0))
        _line_on(win, "EJES", (0, 20), (10, 20))
        _type(win, "LAYFRZ")
        assert win.tools.tool is not None and win.tools.tool.name == "LAYFRZ"
        win.tools.on_click(5, 0)
        assert layers.get("COTAS").is_frozen()
        win.tools.on_click(5, 20)                    # still running: next one
        assert layers.get("EJES").is_frozen()
        _type(win, "U")                              # [Undo] the last pick
        assert not layers.get("EJES").is_frozen()
        assert layers.get("COTAS").is_frozen()
        _type(win, "")                               # Enter ends it
        assert win.tools.tool is None
        win._cmd_undo()
        assert not layers.get("COTAS").is_frozen()
    finally:
        win.document.dirty = False
        win.close()


def test_layfrz_refuses_the_current_layer(qapp):
    win = _win(qapp)
    try:
        _line_on(win, "0", (0, 0), (10, 0))
        _type(win, "LAYFRZ")
        win.tools.on_click(5, 0)
        assert not win.document.doc.layers.get("0").is_frozen()
    finally:
        win.document.dirty = False
        win.close()


def test_laythw_thaws_every_layer_in_one_step(qapp):
    win = _win(qapp)
    try:
        layers = win.document.doc.layers
        layers.get("COTAS").freeze()
        layers.get("EJES").freeze()
        _type(win, "LAYTHW")
        assert not layers.get("COTAS").is_frozen()
        assert not layers.get("EJES").is_frozen()
        win._cmd_undo()
        assert layers.get("COTAS").is_frozen() and layers.get("EJES").is_frozen()
    finally:
        win.document.dirty = False
        win.close()


def test_laylck_locks_and_layulk_unlocks_by_picking_an_object(qapp):
    """LAYULK has to reach an object on a LOCKED layer -- that is the
    whole point of it ("unlock that layer without specifying the name")."""
    win = _win(qapp)
    try:
        layer = win.document.doc.layers.get("MUROS")
        _line_on(win, "MUROS", (0, 0), (10, 0))
        _type(win, "LAYLCK")
        win.tools.on_click(5, 0)
        assert layer.is_locked()
        assert win.tools.tool is None                # one object, then done
        _type(win, "LAYULK")
        win.tools.on_click(5, 0)
        assert not layer.is_locked()
        assert win.tools.tool is None
        win._cmd_undo()
        assert layer.is_locked()
    finally:
        win.document.dirty = False
        win.close()


def test_the_four_are_in_format_layer_tools(qapp):
    win = _win(qapp)
    try:
        bar_actions = win._menu_bar.actions()
        fmt = next(a for a in bar_actions
                   if a.text().replace("&", "") == "Format").menu()
        fmt_actions = fmt.actions()
        tools = next(a for a in fmt_actions
                     if a.text() == "Layer Tools").menu()
        labels = [a.text() for a in tools.actions()]
        for label in ("Layer Freeze", "Thaw All Layers", "Layer Lock",
                      "Layer Unlock"):
            assert label in labels
    finally:
        win.document.dirty = False
        win.close()


def test_a_line_sent_to_back_draws_under_a_fill(qapp):
    """GeoCad Yaguarete had to patch this: the canvas drew every fill, then
    every line, whatever their DRAWORDER, so a line sent to the back still
    crossed a hatch. Pixels: the line must not show through the solid."""
    import numpy as np
    from PySide6.QtGui import QGuiApplication, QImage
    from PySide6.QtTest import QTest

    if QGuiApplication.platformName() in ("offscreen", "minimal"):
        pytest.skip("no OpenGL on this platform: the pixels need a real context")
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        win.new_document("m")
        win.resize(900, 700)
        win.show()
        QTest.qWaitForWindowExposed(win, 5000)
        win.viewport.grid_on = False
        doc = win.document
        msp = doc.modelspace()
        line = msp.add_line((-50, 0), (50, 0), dxfattribs={"color": 1})
        hatch = msp.add_hatch(color=5)
        hatch.paths.add_polyline_path([(-20, -20), (20, -20), (20, 20), (-20, 20)])
        win.history.execute(DrawOrderCommand([line], "back"))
        win.regen_in_memory(zoom_after=True)
        import time
        t0 = time.monotonic()
        while win._regen_worker is not None and time.monotonic() - t0 < 20:
            qapp.processEvents()
        for _ in range(5):
            qapp.processEvents()
            QTest.qWait(10)

        def pixels():
            img = win.viewport.grabFramebuffer().convertToFormat(QImage.Format_RGB888)
            w, h = img.width(), img.height()
            arr = np.frombuffer(img.constBits(), np.uint8)
            return arr.reshape(h, img.bytesPerLine())[:, :w * 3].reshape(h, w, 3)

        pixels()
        img = pixels()
        h, w, _ = img.shape
        centre = img[h // 2 - 3:h // 2 + 4, w // 2 - 3:w // 2 + 4].reshape(-1, 3)
        red = ((centre[:, 0] > 150) & (centre[:, 2] < 80)).sum()
        blue = ((centre[:, 2] > 150) & (centre[:, 0] < 80)).sum()
        assert blue > 0, "the solid is not there"
        assert red == 0, "the line sent to the back draws over the fill"
        # outside the solid the line still shows
        x = w // 2 + int(w * 0.3)
        side = img[h // 2 - 3:h // 2 + 4, x - 1:x + 2].reshape(-1, 3)
        assert ((side[:, 0] > 150) & (side[:, 2] < 80)).any()
    finally:
        win.document.dirty = False
        win.close()


def test_each_group_draws_whole_before_the_next():
    """The batches split their runs by DRAWORDER group, so the canvas can
    draw back, default and front one after the other."""
    from render.backend import build_scene

    doc, s1, s2 = _doc_with_two_solids()
    line = doc.modelspace().add_line((0, 5), (12, 5))
    history = History(doc)
    history.execute(DrawOrderCommand([line], "back"))
    scene = build_scene(doc)
    assert scene.lines.group_set() == {-1}
    assert scene.triangles.group_set() == {0}
    rect = (-100, -100, 100, 100)
    assert scene.lines.visible_runs(rect, 1.0, 0.0, -1)
    assert not scene.lines.visible_runs(rect, 1.0, 0.0, 0)
    assert scene.triangles.visible_runs(rect, 1.0, 0.0, 0)


def test_typed_draworder_and_its_undo_redraw_at_once(qapp):
    """DRAWORDER typed (not the menu with a selection) changed the order in
    the drawing but redrew nothing until REGEN; nor did its undo."""
    import time

    import numpy as np
    from PySide6.QtGui import QGuiApplication, QImage
    from PySide6.QtTest import QTest

    if QGuiApplication.platformName() in ("offscreen", "minimal"):
        pytest.skip("no OpenGL on this platform: the pixels need a real context")
    from views.main_window import MainWindow

    win = MainWindow()

    def settle():
        t0 = time.monotonic()
        while win._regen_worker is not None and time.monotonic() - t0 < 20:
            qapp.processEvents()
        for _ in range(5):
            qapp.processEvents()
            QTest.qWait(10)

    def red_in_the_middle():
        win.viewport.grabFramebuffer()
        img = win.viewport.grabFramebuffer().convertToFormat(QImage.Format_RGB888)
        w, h = img.width(), img.height()
        arr = np.frombuffer(img.constBits(), np.uint8)
        arr = arr.reshape(h, img.bytesPerLine())[:, :w * 3].reshape(h, w, 3)
        centre = arr[h // 2 - 3:h // 2 + 4, w // 2 - 3:w // 2 + 4].reshape(-1, 3)
        return int(((centre[:, 0] > 150) & (centre[:, 2] < 80)).sum())

    try:
        win.new_document("m")
        win.resize(900, 700)
        win.show()
        QTest.qWaitForWindowExposed(win, 5000)
        win.viewport.grid_on = False
        msp = win.document.modelspace()
        hatch = msp.add_hatch(color=5)
        hatch.paths.add_polyline_path([(-20, -20), (20, -20), (20, 20), (-20, 20)])
        line = msp.add_line((-50, 0), (50, 0), dxfattribs={"color": 1})
        win.regen_in_memory(zoom_after=True)
        settle()
        assert red_in_the_middle() > 0          # the line over the fill

        win.tools.selection = {line.dxf.handle}
        win._on_command_submitted("DRAWORDER")
        win._on_command_submitted("B")
        settle()
        assert red_in_the_middle() == 0, "typed DRAWORDER did not redraw"

        win._on_command_submitted("U")
        settle()
        assert red_in_the_middle() > 0, "its undo did not redraw"
    finally:
        win.document.dirty = False
        win.close()
