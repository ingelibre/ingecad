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
