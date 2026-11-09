# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Properties panel's names are not cut short.

A dimension's "Text position X/Y/Z" read "Posición del te..." in Spanish
(a tester's eighth review): the names' column kept Qt's default width. It
is now as wide as the longest name, up to a share of the panel, and every
name shows whole in its tooltip.
"""
from __future__ import annotations

from PySide6.QtWidgets import QTreeWidgetItemIterator

from core import i18n


def test_a_dimensions_names_fit(qapp, clean_settings):
    from views.main_window import MainWindow

    win = MainWindow()
    win.resize(1600, 900)
    win.show()
    win.new_document()
    try:
        i18n.set_language("es")
        for text in ("DIMLINEAR", "0,0", "100,0", "50,10"):
            win._on_command_submitted(text)
        (dim,) = win.document.modelspace().query("DIMENSION")
        win.tools.selection = {dim.dxf.handle}
        win.toggle_properties_panel()
        panel = win._properties_panel
        panel.resize(420, 700)
        panel.refresh()
        tree = panel.tree
        metrics = tree.fontMetrics()
        widths, tips = [], []
        it = QTreeWidgetItemIterator(tree)
        while it.value():
            item = it.value()
            if item.parent() is not None:
                widths.append(metrics.horizontalAdvance(item.text(0)))
                tips.append(item.toolTip(0) == item.text(0))
            it += 1
    finally:
        i18n.set_language("en")
        win.document.dirty = False
        win.close()
    assert all(tips)
    assert tree.columnWidth(0) >= max(widths)
    assert tree.columnWidth(0) <= 420 * panel.LABEL_SHARE + 1
