# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Drafting Settings: the nested grid, polar tracking, and their dialog.

Two of a tester's findings: "la rejilla salta de escala al acercarse" (the
1-2-5 ladder re-flowed the lattice at every step) and "polar no
configurable: no encontré cómo pasar de 45° a 5°" -- with, underneath the
second, a POLAR that rounded every point to the nearest 45° instead of
locking only near a path, so a 30° line could not be drawn with it on.
"""
from __future__ import annotations

import math
import time

import ezdxf
import pytest

from core import drafting
from core.commands import History
from core.document import Document


# -- the grid ------------------------------------------------------------------

def test_grid_levels_are_nested_so_zooming_never_moves_a_line():
    """Every level's lines are a subset of the finer level's: the lattice
    only gains or loses lines between zooms."""
    unit, major = 10.0, 5
    levels = {}
    for ppu in (0.001, 0.004, 0.02, 0.1, 0.5, 2.0, 10.0, 50.0, 250.0):
        spacing, level = drafting.grid_level(unit, major, ppu)
        assert spacing is not None
        assert drafting.GRID_MIN_PX <= spacing * ppu < drafting.GRID_MIN_PX * major
        levels[level] = spacing
    for level, spacing in levels.items():
        assert spacing == pytest.approx(unit * major ** level)
        coarser = levels.get(level + 1)
        if coarser is not None:
            # a coarse line at k*coarser is a fine line at (k*major)*spacing
            for k in range(-3, 4):
                assert (k * coarser / spacing) == pytest.approx(round(k * coarser / spacing))
    assert len(levels) >= 7, "the zoom range crossed several levels"


def test_the_old_ladder_would_have_moved_lines():
    """The control: 1-2-5 is NOT nested (a line at 15 exists at spacing 5,
    not at spacing 2), which is the jump the tester saw."""
    assert (15 / 5) == 3 and (15 / 2) != round(15 / 2)


def test_the_grid_keeps_its_level_across_the_threshold():
    """A wheel notch right at the boundary must not flip the grid back and
    forth: the level on screen survives inside a band around the switch."""
    unit, major = 10.0, 5
    # fresh: 2.45 px/unit gives 24.5 px cells -> level 1
    assert drafting.grid_level(unit, major, 2.45)[1] == 1
    # but a screen already showing level 0 keeps it there (20 px is still
    # within the 0.8 band)...
    assert drafting.grid_level(unit, major, 2.45, current=0)[1] == 0
    # ...and lets go once the cells get genuinely small
    assert drafting.grid_level(unit, major, 1.5, current=0)[1] == 1
    # the other way round: level 1 held while its cells are not yet huge
    assert drafting.grid_level(unit, major, 2.6, current=1)[1] == 1
    assert drafting.grid_level(unit, major, 4.0, current=1)[1] == 0


def test_grid_behaviour_flags():
    unit, major = 10.0, 5
    assert drafting.grid_level(unit, major, 0.1, adaptive=False) == (None, 0), (
        "not adaptive and too dense: not drawn")
    assert drafting.grid_level(unit, major, 1.0, adaptive=False)[0] == 10.0
    assert drafting.grid_level(unit, major, 800.0, subdivide=False)[0] == 10.0
    assert drafting.grid_level(unit, major, 800.0, subdivide=True)[0] == pytest.approx(0.08)
    # a level the flags no longer allow is not kept
    assert drafting.grid_level(unit, major, 800.0, subdivide=False, current=-2)[1] == 0


def test_grid_unit_and_snap_unit_live_in_the_drawings_vport():
    doc = Document.new()
    drawing = doc.doc
    assert drafting.grid_unit(drawing) == 1.0, "a metres drawing: 1 m"
    assert drafting.snap_unit(drawing) == 0.0, "follow the grid on screen"
    assert drafting.grid_major(drawing) == 5
    history = History()
    history.document = doc
    history.execute(drafting.SetGridCommand(grid=2.5, snap=0.5, major=10))
    assert drafting.grid_unit(drawing) == 2.5
    assert drafting.snap_unit(drawing) == 0.5
    assert drafting.grid_major(drawing) == 10
    vport = drafting.active_vport(drawing)
    assert tuple(vport.dxf.grid_spacing)[:2] == (2.5, 2.5)
    history.undo()
    assert drafting.grid_unit(drawing) == 1.0
    assert drafting.snap_unit(drawing) == 0.0
    assert drafting.grid_major(drawing) == 5
    history.redo()
    assert drafting.grid_unit(drawing) == 2.5


def test_a_colleagues_drawing_brings_its_own_grid():
    drawing = ezdxf.new("R2018")
    drawing.header["$INSUNITS"] = 4
    assert drafting.grid_unit(drawing) == 10.0, "AutoCAD's metric default"
    vport = drawing.viewports.get("*Active")[0]
    vport.dxf.grid_spacing = (0.5, 0.5)
    vport.dxf.snap_spacing = (0.25, 0.25)
    assert drafting.grid_unit(drawing) == 0.5
    assert drafting.snap_unit(drawing) == 0.25
    imperial = ezdxf.new("R2018")
    imperial.header["$INSUNITS"] = 1
    assert drafting.grid_unit(imperial) == 0.5


# -- polar tracking --------------------------------------------------------------

def test_polar_angles_fold_the_increment_and_the_additional_ones():
    assert drafting.polar_angles(90) == [0, 90]
    assert drafting.polar_angles(45) == [0, 45, 90, 135]
    assert drafting.polar_angles(5)[:4] == [0, 5, 10, 15] and len(drafting.polar_angles(5)) == 36
    assert 33.0 in drafting.polar_angles(90, [33, 213], use_additional=True)
    assert 33.0 not in drafting.polar_angles(90, [33], use_additional=False)
    assert drafting.parse_angles("33; 45.5 ,abc, 400") == [33.0, 45.5, 40.0]


def test_polar_lock_catches_the_cursor_only_near_a_path():
    angles = drafting.polar_angles(45)
    # 0.5 off the 0° path at 10 out, tolerance 1: locked onto it
    assert drafting.polar_lock((0, 0), (10, 0.5), angles, 1.0) == (
        pytest.approx((10.0, 0.0)), 0.0)
    # 3 off: free
    assert drafting.polar_lock((0, 0), (10, 3), angles, 1.0) is None
    # a path is a full line: the opposite direction reports 180
    _, direction = drafting.polar_lock((0, 0), (-10, 0.2), angles, 1.0)
    assert direction == 180.0
    # relative measurement: angles from the last segment's direction
    point, direction = drafting.polar_lock((0, 0), (7.0, 7.1), [0.0, 90.0], 0.5,
                                           base_deg=45.0)
    assert point == pytest.approx((7.05, 7.05)) and direction == 45.0


# -- through the controller, the way the canvas drives it --------------------------

def _wait_regen(qapp, win, timeout_s=20.0):
    t0 = time.monotonic()
    while win._regen_worker is not None and time.monotonic() - t0 < timeout_s:
        qapp.processEvents()


def _line_started(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    _wait_regen(qapp, win)
    t = win.tools
    # osnap stays as loaded: switching it off here and then opening the
    # dialog would SAVE it off for every window that follows (the running
    # snaps are remembered across restarts); an empty drawing has nothing
    # to snap to anyway
    t.ortho_on = False
    t.otrack_on = False
    t.start_tool("LINE")
    t.on_click(0.0, 0.0)                      # the first point
    return win, t


def test_polar_leaves_the_cursor_free_away_from_a_path(qapp):
    """With POLARANG 90 a 30° point stays a 30° point: rounding every
    point to the nearest polar angle was not polar tracking."""
    win, t = _line_started(qapp)
    try:
        drafting.set_polar_increment(90.0)
        drafting.set_polar_mode(0)
        t.polar_on = True
        t.on_hover(10.0, 5.77, threshold_world=0.5)      # ~30°, far from 0/90
        assert t.resolved_point(10.0, 5.77) == pytest.approx((10.0, 5.77))
        assert t.track_hint is None
    finally:
        win.close()


def test_polar_locks_near_a_path_and_says_so(qapp):
    win, t = _line_started(qapp)
    try:
        drafting.set_polar_increment(90.0)
        drafting.set_polar_mode(0)
        t.polar_on = True
        t.on_hover(10.0, 0.3, threshold_world=0.5)
        assert t.resolved_point(10.0, 0.3) == pytest.approx((10.0, 0.0))
        assert t.track_hint is not None
        assert "Polar" in t.track_hint[2] and "<0°" in t.track_hint[2]
    finally:
        win.close()


def test_polarang_5_locks_a_30_degree_path(qapp):
    """What the tester asked for: 5° increments, so 30° is a path."""
    win, t = _line_started(qapp)
    try:
        drafting.set_polar_increment(5.0)
        drafting.set_polar_mode(0)
        t.polar_on = True
        x, y = 10.0 * math.cos(math.radians(30)), 10.0 * math.sin(math.radians(30))
        t.on_hover(x, y + 0.2, threshold_world=0.5)
        point = t.resolved_point(x, y + 0.2)
        assert math.degrees(math.atan2(point[1], point[0])) == pytest.approx(30.0)
        assert "<30°" in t.track_hint[2]
        drafting.set_polar_increment(90.0)
    finally:
        win.close()


def test_polar_relative_to_the_last_segment(qapp):
    win, t = _line_started(qapp)
    try:
        drafting.set_polar_increment(90.0)
        drafting.set_polar_mode(drafting.POLAR_RELATIVE)
        t.polar_on = True
        t.on_click(10.0, 10.0)                # first segment at 45°
        # 90° from that segment is 135°: near (-5, 5) from the last point
        t.on_hover(10.0 - 5.0, 10.0 + 5.2, threshold_world=0.5)
        point = t.resolved_point(10.0 - 5.0, 10.0 + 5.2)
        assert point == pytest.approx((4.9, 15.1)) or math.degrees(
            math.atan2(point[1] - 10, point[0] - 10)) == pytest.approx(135.0)
        assert "<135°" in t.track_hint[2]
        drafting.set_polar_mode(0)
    finally:
        win.close()


def test_ortho_still_wins_over_polar(qapp):
    win, t = _line_started(qapp)
    try:
        drafting.set_polar_increment(45.0)
        t.polar_on = True
        t.ortho_on = True
        t.on_hover(10.0, 9.0, threshold_world=0.5)
        assert t.resolved_point(10.0, 9.0) == pytest.approx((10.0, 0.0))
        drafting.set_polar_increment(90.0)
    finally:
        win.close()


def test_object_snap_tracking_uses_the_polar_angles_when_told_to(qapp):
    win, t = _line_started(qapp)
    try:
        drafting.set_polar_increment(45.0)
        t.polar_on = True
        drafting.set_polar_mode(0)
        assert [round(math.degrees(a)) for a in t._track_angles()] == [0, 90]
        drafting.set_polar_mode(drafting.POLAR_OTRACK_ALL)
        assert [round(math.degrees(a)) for a in t._track_angles()] == [0, 45, 90, 135]
        t.polar_on = False
        assert [round(math.degrees(a)) for a in t._track_angles()] == [0, 90]
        drafting.set_polar_mode(0)
        drafting.set_polar_increment(90.0)
    finally:
        win.close()


def test_snap_follows_the_grid_unless_the_drawing_fixes_snapunit(qapp):
    win, t = _line_started(qapp)
    try:
        assert t.snap_spacing() == win.viewport._grid_spacing()
        win.history.execute(drafting.SetGridCommand(snap=0.25))
        assert t.snap_spacing() == 0.25
    finally:
        win.close()


# -- the canvas grid and the dialog -------------------------------------------------

def test_the_canvas_grid_takes_the_drawings_unit_and_nests_across_zooms(qapp):
    win, t = _line_started(qapp)
    try:
        vp = win.viewport
        assert vp._grid_unit == 1.0 and vp._grid_major == 5
        spacings = set()
        for scale in (0.02, 0.1, 0.5, 2.5, 12.5, 62.5):
            vp.view.scale = scale
            vp._grid_level = None
            spacings.add(vp._grid_spacing())
        for s in spacings:
            assert math.log(s, 5) == pytest.approx(round(math.log(s, 5)))
        assert len(spacings) >= 5
        # DSETTINGS changed the drawing's unit: the canvas follows
        win.history.execute(drafting.SetGridCommand(grid=2.0, major=4))
        win.refresh_grid_settings()
        assert vp._grid_unit == 2.0 and vp._grid_major == 4
    finally:
        win.close()


def test_the_dialog_has_autocads_three_tabs_and_applies_on_ok(qapp, monkeypatch):
    from views.drafting_dialog import (TAB_POLAR, TAB_SNAP_GRID,
                                       DraftingSettingsDialog)

    win, t = _line_started(qapp)
    try:
        captured = {}

        def fake_exec(self):
            captured["tabs"] = [self.tabs.tabText(i)
                                for i in range(self.tabs.count())]
            captured["tab"] = self.tabs.currentIndex()
            self.polar.increment.setEditText("5")
            self.polar.polar_on.setChecked(True)
            self.polar.relative.setChecked(True)
            self.snap_grid.grid_spacing.setValue(2.5)
            self.snap_grid.grid_major.setValue(10)
            self.snap_grid.snap_follows_grid.setChecked(False)
            self.snap_grid.snap_spacing.setValue(0.5)
            return True

        monkeypatch.setattr(DraftingSettingsDialog, "exec", fake_exec)
        win._drafting_settings(TAB_POLAR)
        assert captured["tabs"] == ["Snap and Grid", "Polar Tracking", "Object Snap"]
        assert captured["tab"] == TAB_POLAR
        assert drafting.polar_increment() == 5.0
        assert drafting.polar_mode() & drafting.POLAR_RELATIVE
        assert t.polar_on
        assert drafting.grid_unit(win.document.doc) == 2.5
        assert drafting.grid_major(win.document.doc) == 10
        assert drafting.snap_unit(win.document.doc) == 0.5
        assert win.viewport._grid_unit == 2.5 and win.viewport._grid_major == 10
        # the grid change is one undo step
        win.history.undo()
        assert drafting.grid_unit(win.document.doc) == 1.0
        # the status-bar toggles offer Settings... on their own tab
        from PySide6.QtCore import Qt
        from views.drafting_dialog import TAB_OSNAP
        for key, tab in (("snap", TAB_SNAP_GRID), ("grid", TAB_SNAP_GRID),
                         ("polar", TAB_POLAR), ("otrack", TAB_POLAR),
                         ("osnap", TAB_OSNAP)):
            assert win._mode_settings_tab(key) == tab
            assert win._mode_buttons[key].contextMenuPolicy() == Qt.CustomContextMenu
        assert win._mode_settings_tab("lwt") is None
        drafting.set_polar_increment(90.0)
        drafting.set_polar_mode(0)
    finally:
        win.close()


def test_the_typed_variables(qapp):
    win, t = _line_started(qapp)
    try:
        win.dispatcher.submit("POLARANG")
        win.dispatcher.submit("15")
        assert drafting.polar_increment() == 15.0
        win.dispatcher.submit("GRIDUNIT")
        win.dispatcher.submit("0.5")
        assert drafting.grid_unit(win.document.doc) == 0.5
        assert win.viewport._grid_unit == 0.5
        win.dispatcher.submit("GRIDMAJOR")
        win.dispatcher.submit("10")
        assert drafting.grid_major(win.document.doc) == 10
        win.dispatcher.submit("POLARADDANG")
        win.dispatcher.submit("33;66")
        assert drafting.polar_additional() == [33.0, 66.0]
        assert win.dispatcher.resolve_name("DS") == "DSETTINGS"
        assert win.dispatcher.resolve_name("OS") == "OSNAP"
        drafting.set_polar_increment(90.0)
        drafting.set_polar_additional([])
    finally:
        win.close()


# -- tanda D: the origin snap and LASTPOINT ---------------------------------------

def test_the_origin_is_a_snap_when_ticked_and_not_otherwise(qapp):
    """No CAD has it; a tester insisted it is elementary. The (0, 0) of the
    current space snaps like a node when Origin is ticked -- and is not on
    offer at all when it is not, so nobody's plan gains a phantom point."""
    from core import osnap as osnap_modes
    from core.snap import ALL_KINDS

    assert "ORI" in osnap_modes.AVAILABLE and "ORI" not in ALL_KINDS
    win, t = _line_started(qapp)
    try:
        t.osnap_on = True
        t.osnap_modes = {"END", "MID"}
        t.on_hover(0.3, -0.2, threshold_world=1.0)
        assert t.snap_hit is None or t.snap_hit.kind != "ORI"
        t.osnap_modes = {"END", "MID", "ORI"}
        t.on_hover(0.3, -0.2, threshold_world=1.0)
        assert t.snap_hit is not None and t.snap_hit.kind == "ORI"
        assert (t.snap_hit.x, t.snap_hit.y) == (0.0, 0.0)
        assert t.resolved_point(0.3, -0.2) == (0.0, 0.0)
        # it is a mode of the dialog and the dropdown like any other, with
        # a marker of its own
        from views.osnap_dialog import marker_icon
        assert not marker_icon("ORI").isNull()
        assert osnap_modes.label_of("ORI") == "Origin"
    finally:
        win.close()


def test_zero_and_enter_at_the_first_point_is_the_origin(qapp):
    """AutoCAD's LASTPOINT: a direct distance before the command has a
    point of its own is measured from the last point entered -- the
    origin in a fresh drawing. So "0" at "Specify first point:" IS (0, 0),
    and "5" is five units from it toward the cursor."""
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    _wait_regen(qapp, win)
    t = win.tools
    t.osnap_on = False
    t.ortho_on = False
    try:
        t.start_tool("LINE")
        t.on_hover(30.0, 40.0, threshold_world=0.5)
        assert t.on_text("0")
        assert t.tool.last_point == (0.0, 0.0)
        assert t.on_text("10,0")
        assert t.tool.last_point == (10.0, 0.0)
        t.cancel()
        # LASTPOINT outlives the command: the next LINE's "@" and direct
        # distance start from (10, 0)
        assert t.lastpoint == (10.0, 0.0)
        t.start_tool("LINE")
        t.on_hover(10.0, 100.0, threshold_world=0.5)       # straight up
        assert t.on_text("5")
        assert t.tool.last_point == pytest.approx((10.0, 5.0))
        t.cancel()
        t.start_tool("LINE")
        assert t.on_text("@3,4")
        assert t.tool.last_point == pytest.approx((13.0, 9.0))
        t.cancel()
        # a fresh drawing starts LASTPOINT over
        win.new_document()
        _wait_regen(qapp, win)
        assert win.tools.lastpoint == (0.0, 0.0)
    finally:
        win.close()


def test_a_new_layer_is_the_selected_row_and_plots(qapp):
    """The row highlighted after New was whatever index was current before
    the re-sort -- another layer, Defpoints typically, which does not plot.
    A tester read that crossed-out printer as his new layer's. The new layer
    is now the current row, its name open for typing, and it plots."""
    from core import layers as layer_ops
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    _wait_regen(qapp, win)
    try:
        if win._layers_panel is None:
            win.toggle_layers_panel()
        panel = win._layers_panel
        panel.refresh()
        defpoints = panel._rows.index("Defpoints")
        panel.table.setCurrentCell(defpoints, 8)      # the plot column, even
        panel._new_layer()
        qapp.processEvents()
        row = panel.table.currentRow()
        name = panel._row_layer(row)
        assert name.startswith("Layer"), f"the current row is {name!r}"
        assert panel.table.item(row, 8).text() == "🖶"
        info = next(i for i in layer_ops.layer_list(win.document) if i.name == name)
        assert info.plot
        assert win.document.doc.layers.get(name).dxf.get("plot", 1) == 1
    finally:
        win.close()


def test_the_canvas_never_hands_the_os_a_cursor_while_panning(qapp):
    """A tester: "el puntero parpadea al panear". The app changed the OS
    cursor exactly twice per drag (closed hand on press, blank on release)
    -- measured -- so the flicker is the system cursor itself over a GL
    surface flipping sixty times a second, a known artefact of some
    driver/compositor pairs (NVIDIA under XWayland). The hands and the
    zoom cross are now painted into the frame like the crosshair; the OS
    pointer over the canvas stays blank at all times."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    _wait_regen(qapp, win)
    vp = win.viewport
    shapes = []
    original = vp.setCursor
    vp.setCursor = lambda c: (shapes.append(c.shape()), original(c))
    try:
        def send(kind, x, y, button=Qt.NoButton, buttons=Qt.NoButton):
            qapp.sendEvent(vp, QMouseEvent(kind, QPointF(x, y), button,
                                           buttons, Qt.NoModifier))

        send(QEvent.MouseMove, 200, 200)
        send(QEvent.MouseButtonPress, 200, 200, Qt.MiddleButton, Qt.MiddleButton)
        assert vp._soft_cursor == "closed_hand"
        assert vp._soft_cursor_pos() is not None
        for i in range(1, 30):
            send(QEvent.MouseMove, 200 + 3 * i, 200 + i, buttons=Qt.MiddleButton)
        assert vp._soft_cursor == "closed_hand"
        send(QEvent.MouseButtonRelease, 290, 230, Qt.MiddleButton)
        assert vp._soft_cursor is None, "the crosshair is back"
        assert shapes == [], f"the OS cursor was changed: {shapes}"
        assert vp.cursor().shape() == Qt.BlankCursor

        # the PAN command: open hand, closed while dragging, open again
        vp.start_pan_mode()
        assert vp._soft_cursor == "open_hand"
        send(QEvent.MouseButtonPress, 150, 150, Qt.LeftButton, Qt.LeftButton)
        assert vp._soft_cursor == "closed_hand"
        send(QEvent.MouseButtonRelease, 160, 160, Qt.LeftButton)
        assert vp._soft_cursor == "open_hand"
        vp.stop_pan_mode()
        assert vp._soft_cursor is None
        # ZOOM Window's cross too
        vp.start_zoom_window()
        assert vp._soft_cursor == "cross"
        vp._zoom_window = False
        vp._set_soft_cursor(None)
        assert shapes == []
    finally:
        win.document.dirty = False
        win.close()
