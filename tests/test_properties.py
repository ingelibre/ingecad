# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Context-sensitive Properties: row schema + edit/undo paths (headless)."""
from __future__ import annotations

import ezdxf
import pytest

from core import actions
from core.commands import History
from core.document import Document
from views import properties_panel as pp


class StubPanel:
    """Enough of PropertiesPanel for the module-level row builders."""

    def __init__(self, doc, entity):
        self._doc = Document(doc)
        self.history = History(self._doc)
        self._ent = [entity]

    @property
    def _document(self):
        return self._doc

    def _active(self):
        return self._ent

    def _set_prop(self, prop, value):
        self.history.execute(
            actions.SetPropertyCommand(self._active(), prop, value))

    def _in_place(self, mutate):
        actions.apply_in_place(self.history, self._active(), mutate)

    def _set_comp(self, attr, axis, value):
        def mutate():
            for e in self._active():
                v = e.dxf.get(attr)
                c = [v.x, v.y, v.z]
                c[axis] = value
                e.dxf.set(attr, tuple(c))
        self._in_place(mutate)


def _row(rows, label):
    for r in rows:
        if r.label == label:
            return r
    raise KeyError(label)


def test_circle_rows_read_and_edit():
    doc = ezdxf.new("R2018", setup=True)
    c = doc.modelspace().add_circle((3, 4), radius=10)
    panel = StubPanel(doc, c)
    _title, rows = pp._circle_rows(panel, c)

    assert _row(rows, "Radius").get(c) == pytest.approx(10)
    assert _row(rows, "Diameter").get(c) == pytest.approx(20)
    assert _row(rows, "Area").get(c) == pytest.approx(3.14159265 * 100, rel=1e-6)

    # editing diameter sets radius to half
    _row(rows, "Diameter").apply(50)
    assert c.dxf.radius == pytest.approx(25)
    # undo restores it
    panel.history.undo()
    assert c.dxf.radius == pytest.approx(10)


def test_center_component_edit_and_undo():
    doc = ezdxf.new("R2018", setup=True)
    c = doc.modelspace().add_circle((3, 4), radius=1)
    panel = StubPanel(doc, c)
    _title, rows = pp._circle_rows(panel, c)

    _row(rows, "Center X").apply(99)
    assert c.dxf.center.x == pytest.approx(99)
    assert c.dxf.center.y == pytest.approx(4)   # untouched
    panel.history.undo()
    assert c.dxf.center.x == pytest.approx(3)


def test_text_rows_edit_contents_and_style():
    doc = ezdxf.new("R2018", setup=True)
    t = doc.modelspace().add_text("A", height=2.5)
    panel = StubPanel(doc, t)
    _title, rows = pp._text_rows(panel, t)

    _row(rows, "Contents").apply("PLANO")
    assert t.dxf.text == "PLANO"
    _row(rows, "Height").apply(3.0)
    assert t.dxf.height == pytest.approx(3.0)
    # style combo is populated from the STYLE table
    assert ("Standard", "Standard") in _row(rows, "Style").items


def test_line_geometry_readouts():
    doc = ezdxf.new("R2018", setup=True)
    ln = doc.modelspace().add_line((0, 0), (3, 4))
    panel = StubPanel(doc, ln)
    _title, rows = pp._line_rows(panel, ln)
    assert _row(rows, "Length").get(ln) == pytest.approx(5.0)
    assert _row(rows, "Angle").get(ln) == pytest.approx(53.13010, rel=1e-4)


def test_polyline_area_only_when_closed():
    doc = ezdxf.new("R2018", setup=True)
    pl = doc.modelspace().add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 10)])
    panel = StubPanel(doc, pl)
    labels_open = [r.label for r in pp._lwpolyline_rows(panel, pl)[1]]
    assert "Area" not in labels_open
    pl.close(True)
    rows = pp._lwpolyline_rows(panel, pl)[1]
    assert "Area" in [r.label for r in rows]
    assert _row(rows, "Area").get(pl) == pytest.approx(100.0)


# -- the Properties bar: current settings vs the selection ---------------------

def _fresh_window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document("mm")
    return win


def test_with_nothing_selected_the_bar_sets_what_comes_next(qapp):
    from core import layers as layer_ops

    win = _fresh_window(qapp)
    try:
        win._apply_property("linetype", "DASHED")
        win._apply_property("lineweight", 50)
        win._apply_property("color", 1)
        assert layer_ops.current_property(win.document, "linetype") == "DASHED"
        assert layer_ops.current_property(win.document, "lineweight") == 50
        assert layer_ops.current_property(win.document, "color") == 1

        win._on_command_submitted("LINE")
        win.tools.tool.on_point((0, 0))
        win.tools.tool.on_point((10, 0))
        win.tools.tool.on_enter()
        drawn = list(win.document.modelspace())[-1]
        assert drawn.dxf.linetype == "DASHED"
        assert drawn.dxf.lineweight == 50
        assert drawn.dxf.color == 1
    finally:
        win.close()


def test_a_fresh_drawing_draws_bylayer(qapp):
    """The defaults must stay ByLayer, or a layer stops controlling anything."""
    win = _fresh_window(qapp)
    try:
        win._on_command_submitted("LINE")
        win.tools.tool.on_point((0, 0))
        win.tools.tool.on_point((10, 0))
        win.tools.tool.on_enter()
        drawn = list(win.document.modelspace())[-1]
        assert drawn.dxf.get("color", 256) == 256
        assert drawn.dxf.get("linetype", "ByLayer") == "ByLayer"
        assert drawn.dxf.get("lineweight", -1) == -1
    finally:
        win.close()


def test_with_a_selection_the_bar_edits_it_and_leaves_the_default_alone(qapp):
    from core import layers as layer_ops

    win = _fresh_window(qapp)
    try:
        line = win.document.modelspace().add_line((0, 0), (10, 0))
        win.tools.index.invalidate()
        win.tools.index._build()
        win.tools.selection = {line.dxf.handle}

        win._apply_property("color", 3)
        assert line.dxf.color == 3
        # The current setting is untouched: this was an edit, not a default.
        assert layer_ops.current_property(win.document, "color") == 256
        # And it undoes.
        win.history.undo()
        assert line.dxf.get("color", 256) == 256
    finally:
        win.close()


def test_the_bar_shows_the_selection_and_falls_back_to_the_defaults(qapp):
    win = _fresh_window(qapp)
    try:
        line = win.document.modelspace().add_line(
            (0, 0), (10, 0), dxfattribs={"linetype": "DASHED", "color": 5})
        win.tools.index.invalidate()
        win.tools.index._build()
        win.tools.selection = {line.dxf.handle}
        win._refresh_props_toolbar()
        assert win._linetype_combo.currentData() == "DASHED"
        assert win._color_combo.currentData() == 5

        win.tools.selection = set()
        win._refresh_props_toolbar()
        assert win._linetype_combo.currentData() == "ByLayer"
        assert win._color_combo.currentData() == 256
    finally:
        win.close()


def test_a_mixed_selection_shows_nothing_rather_than_a_lie(qapp):
    win = _fresh_window(qapp)
    try:
        msp = win.document.modelspace()
        a = msp.add_line((0, 0), (1, 0), dxfattribs={"color": 1})
        b = msp.add_line((0, 1), (1, 1), dxfattribs={"color": 3})
        win.tools.index.invalidate()
        win.tools.index._build()
        win.tools.selection = {a.dxf.handle, b.dxf.handle}
        win._refresh_props_toolbar()
        assert win._color_combo.currentIndex() == -1
    finally:
        win.close()


def test_the_linetype_list_offers_what_the_drawing_carries(qapp):
    from core import layers as layer_ops

    win = _fresh_window(qapp)
    try:
        names = [win._linetype_combo.itemData(i)
                 for i in range(win._linetype_combo.count())]
        assert names[:2] == ["ByLayer", "ByBlock"]
        for name in layer_ops.available_linetypes(win.document):
            assert name in names
        assert "DASHED" in names and "CENTER" in names
    finally:
        win.close()
