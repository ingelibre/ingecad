# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The three stalls Marco reported on 0.4.1, pinned as behaviour.

He described them as feel ("se queda pegado", "tarda unos segundos"), and
each turned out to be a different piece of work done per frame or per edit
that did not need doing. Timings make flaky tests, so what is pinned here is
the *structural* property behind each fix -- revert any of them and one of
these fails.

Measured before and after on his own plans, for the record:

============================== =========== ==========
                                    before      after
============================== =========== ==========
frame with 3000 objects picked     20.6 ms     6.7 ms
releasing a big window              95 ms      31 ms
grabbing a dimension grip          3392 ms     34 ms
dropping a dimension grip          3081 ms    100 ms
drawing a dimension                 163 ms     25 ms
============================== =========== ==========
"""
import pytest

from core import actions


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    window = MainWindow()
    window.new_document("mm")
    yield window
    window.close()


# -- 1. grips past GRIPOBJLIMIT (p.2339) ---------------------------------------
def test_grips_are_suppressed_past_the_object_limit(win):
    """AutoCAD suppresses them ENTIRELY past the limit -- it does not thin
    them. We used to keep the first 200 entities, which on a cadastre meant
    thousands of squares repainted every frame (8.8 ms of a 20 ms frame)."""
    from views.tool_controller import gripobjlimit

    msp = win.document.modelspace()
    lines = [msp.add_line((i, 0), (i, 1)) for i in range(gripobjlimit() + 5)]
    win.tools._invalidate_geometry()

    win.tools.selection = {e.dxf.handle for e in lines[:10]}
    win.tools._grips_cache = None
    assert win.tools.grip_points(), "a small selection must still show grips"

    win.tools.selection = {e.dxf.handle for e in lines}
    win.tools._grips_cache = None
    assert win.tools.grip_points() == []


def test_the_limit_is_a_setting_the_user_can_lift(win):
    from PySide6.QtCore import QSettings
    from views.tool_controller import SETTING_GRIPOBJLIMIT, gripobjlimit

    settings = QSettings()
    previous = settings.value(SETTING_GRIPOBJLIMIT, None)
    try:
        settings.setValue(SETTING_GRIPOBJLIMIT, 0)   # 0 = always show
        msp = win.document.modelspace()
        lines = [msp.add_line((i, 0), (i, 1)) for i in range(120)]
        win.tools._invalidate_geometry()
        win.tools.selection = {e.dxf.handle for e in lines}
        win.tools._grips_cache = None
        assert win.tools.grip_points(), "0 must mean 'never suppress'"
        assert gripobjlimit() == 0
    finally:
        if previous is None:
            settings.remove(SETTING_GRIPOBJLIMIT)
        else:
            settings.setValue(SETTING_GRIPOBJLIMIT, previous)


# -- 2. editing a dimension goes through the overlay, not a full regen ----------
@pytest.mark.parametrize("name", ["DimGripCommand", "DimTextTranslateCommand",
                                  "DimTextEditCommand"])
def test_dimension_edits_do_not_demand_a_full_regen(name):
    """``needs_regen`` re-tessellates the WHOLE drawing on the spot: ~3 s on
    a 10 000-entity plan, for one dimension. The overlay can draw a
    dimension (see test_dimension_display), so the surgical path -- hide the
    stale copy, draw the new one -- is enough, exactly as for MATCHPROP."""
    command = getattr(actions, name)
    assert command.needs_regen is False
    assert "entities" in dir(command), \
        "the display paths find the touched entity through .entities"


def test_a_dimension_grip_edit_exposes_the_dimension_it_touched(win):
    msp = win.document.modelspace()
    dim = msp.add_linear_dim(base=(0, 5), p1=(0, 0), p2=(10, 0))
    dim.render()
    command = actions.DimGripCommand(dim.dimension, "defpoint", (0, 8))
    assert [e.dxf.handle for e in command.entities] == \
        [dim.dimension.dxf.handle]


# -- 3. one edit must not queue a rebuild of the whole drawing ------------------
def test_a_small_edit_schedules_no_background_rebuild(win):
    """The merge exists to bound the overlay's growth, so below the
    threshold nothing is scheduled. It used to fire after EVERY edit, and
    the rebuild -- nominally in a worker, but a pure-Python one holds the
    GIL -- froze the UI 2.5 s later, right as the user grabbed the next
    grip. That was the "a veces se queda pegado"."""
    tools = win.tools
    msp = win.document.modelspace()
    a = msp.add_line((0, 0), (10, 0))
    tools._invalidate_geometry()
    tools._merge_timer.stop()

    tools._execute(actions.move_entities([a], 1.0, 1.0))
    assert not tools._merge_timer.isActive(), \
        "one MOVE queued a full re-tessellation of the drawing"


def test_a_big_overlay_still_gets_merged(win):
    """The other half: the guard must not disable the merge altogether, or
    the overlay grows without bound."""
    from views.tool_controller import MERGE_THRESHOLD

    tools = win.tools
    msp = win.document.modelspace()
    lines = [msp.add_line((i, 0), (i, 1)) for i in range(MERGE_THRESHOLD + 20)]
    tools._invalidate_geometry()
    tools._merge_timer.stop()
    tools._pending_render = list(lines)      # a session's worth of drawing

    tools._execute(actions.move_entities(lines[:1], 1.0, 1.0))
    assert tools._merge_timer.isActive()


# -- 4. the dimension magnet stops walking the drawing per mouse move -----------
def test_the_dimension_magnet_reuses_its_candidates_within_a_drag(win):
    """It ran ``query("DIMENSION")`` over the whole modelspace on every
    mouse move of a dimension-line grip."""
    from views.tool_controller import _dim_line_candidates

    msp = win.document.modelspace()
    for i in range(3):
        msp.add_linear_dim(base=(0, 5 + i), p1=(0, 0), p2=(10, 0)).render()
    first = _dim_line_candidates(win.document)
    assert _dim_line_candidates(win.document) is first, "recomputed per move"

    msp.add_linear_dim(base=(0, 20), p1=(0, 0), p2=(10, 0)).render()
    win.document.dirty = True                # any edit invalidates it
    assert _dim_line_candidates(win.document) is not first


# -- 5. the properties chrome stops rebuilding on every selection change --------
def test_the_layer_control_is_not_rebuilt_for_a_selection_change(win):
    """Rebuilding four combo boxes (an icon rendered per row) cost ~39 ms of
    the stall on releasing a big selection window."""
    msp = win.document.modelspace()
    win.document.doc.layers.add("MUROS", color=1)
    a = msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "MUROS"})
    b = msp.add_line((0, 5), (10, 5))
    win.tools._invalidate_geometry()
    win._refresh_props_toolbar()

    calls = []
    original = win._layer_combo.clear
    win._layer_combo.clear = lambda: (calls.append(1), original())[1]
    try:
        win.tools.selection = {a.dxf.handle}
        win._refresh_props_toolbar()
        win.tools.selection = {b.dxf.handle}
        win._refresh_props_toolbar()
        assert calls == [], "the layer list was rebuilt for a mere selection"
        assert win._layer_combo.currentText() == "0"

        # ...but a NEW layer must still appear, even though adding one
        # through the table bumps no revision
        win.document.doc.layers.add("EJES", color=5)
        win._refresh_props_toolbar()
        assert calls, "a new layer never reached the control"
        assert win._layer_combo.findText("EJES") >= 0
    finally:
        win._layer_combo.clear = original
