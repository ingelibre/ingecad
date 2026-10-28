# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A number typed with a decimal comma in the Properties panel is taken.

"0,0035" in Linetype scale was dropped without a word (a YouTuber's
staircase drawing, reproduced in IngeCAD).
"""
from __future__ import annotations

from PySide6.QtWidgets import QLineEdit, QTreeWidgetItemIterator


def test_linetype_scale_takes_a_decimal_comma(qapp):
    from core import actions
    from core.i18n import tr
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    win.tools._execute(actions.add_line((0, 0), (10, 0)))
    line = win.document.modelspace().query("LINE")[0]
    win.tools.selection = {line.dxf.handle}
    win.toggle_properties_panel()
    panel = win._properties_panel
    panel.refresh()
    editor = None
    it = QTreeWidgetItemIterator(panel.tree)
    while it.value():
        item = it.value()
        if item.text(0) == tr("Linetype scale"):
            editor = panel.tree.itemWidget(item, 1)
        it += 1
    assert isinstance(editor, QLineEdit)
    editor.setText("0,0035")
    editor.editingFinished.emit()
    assert line.dxf.ltscale == 0.0035
    win.document.dirty = False
    win.close()
