# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A hatch's scale and angle typed in Properties redraw its pattern (#86).

Rafael (2026-10-12): "el sombreado se genera bien, pero cuando intento
cambiar su escala desde las propiedades, no cambia". The pattern lines of a
hatch carry its scale and angle; the panel set the DXF value alone, so the
number changed and the drawing did not.
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QLineEdit, QTreeWidgetItemIterator


def _type_in(panel, label, text):
    from core.i18n import tr

    editor = None
    it = QTreeWidgetItemIterator(panel.tree)
    while it.value():
        item = it.value()
        if item.text(0) == tr(label):
            editor = panel.tree.itemWidget(item, 1)
        it += 1
    assert isinstance(editor, QLineEdit), label
    editor.setText(text)
    editor.editingFinished.emit()


def _spacing(hatch):
    line = hatch.pattern.lines[0]
    return round(line.offset.magnitude, 6), round(line.angle, 6)


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    window = MainWindow()
    window.show()
    window.new_document()
    yield window
    window.document.dirty = False
    window.close()


def test_scale_and_angle_typed_in_properties_redraw_the_pattern(win):
    from core import actions

    square = [(0, 0), (100, 0), (100, 100), (0, 100)]
    win.tools._execute(actions.add_hatch([square], pattern="ANSI31", scale=1.0))
    hatch = win.document.modelspace().query("HATCH")[0]
    offset, angle = _spacing(hatch)
    win.tools.selection = {hatch.dxf.handle}
    win.toggle_properties_panel()
    panel = win._properties_panel
    panel.refresh()

    _type_in(panel, "Pattern scale", "4")
    assert hatch.dxf.pattern_scale == 4.0
    assert _spacing(hatch)[0] == pytest.approx(4 * offset)
    panel.refresh()
    _type_in(panel, "Pattern angle", "30")
    assert hatch.dxf.pattern_angle == 30.0
    assert _spacing(hatch) == pytest.approx((4 * offset, angle + 30))

    win._cmd_undo()
    win._cmd_undo()
    assert hatch.dxf.pattern_scale == 1.0
    assert _spacing(hatch) == pytest.approx((offset, angle))


def test_a_zero_scale_is_refused(win):
    from core import actions

    square = [(0, 0), (100, 0), (100, 100), (0, 100)]
    win.tools._execute(actions.add_hatch([square], pattern="ANSI31", scale=2.0))
    hatch = win.document.modelspace().query("HATCH")[0]
    before = _spacing(hatch)
    win.tools.selection = {hatch.dxf.handle}
    win.toggle_properties_panel()
    win._properties_panel.refresh()
    _type_in(win._properties_panel, "Pattern scale", "0")
    assert hatch.dxf.pattern_scale == 2.0 and _spacing(hatch) == before
