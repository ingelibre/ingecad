# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Switching language with the window open reaches everything (#74):
Rafael's Spanish interface still showed the side tabs, the status-bar
toggles, the Xrefs palette and "Multileader" in English -- only the menus
had been rebuilt."""
from __future__ import annotations

from PySide6.QtCore import QSettings

from core import i18n


def _texts(win):
    tabs = win._layers_panel.parentWidget().parentWidget()
    tab_texts = [tabs.tabText(i) for i in range(tabs.count())]
    toggles = {k: b.text() for k, b in win._mode_buttons.items()}
    table = win._xrefs_panel.table
    headers = [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
    dim_bar = win.findChild(type(win.addToolBar("x")), "dimension_toolbar")
    actions = [a.text() for a in dim_bar.actions()]
    return tab_texts, toggles, headers, actions


def test_the_whole_window_follows_a_live_language_switch(qapp):
    from views.main_window import MainWindow

    i18n.set_language("en")
    win = MainWindow()
    try:
        win._set_language("es")
        tabs, toggles, headers, actions = _texts(win)
        assert tabs[:3] == ["Capas", "Propiedades", "Paleta"]
        assert (toggles["grid"], toggles["ortho"], toggles["osnap"]) == \
            ("REJILLA", "ORTO", "REFENT")
        assert headers[0] == "Nombre de referencia"
        assert "Directriz múltiple" in actions and "Multileader" not in actions
        colors = [win._color_combo.itemText(i) for i in range(win._color_combo.count())]
        assert "PorCapa" in colors and "ByLayer" not in colors
        win._set_language("en")
        tabs, toggles, headers, actions = _texts(win)
        assert tabs[:3] == ["Layers", "Properties", "Palette"]
        assert toggles["grid"] == "GRID"
        assert headers[0] == "Reference Name"
        assert "Multileader" in actions
    finally:
        i18n.set_language("en")
        QSettings().setValue("language", "en")
        win.close()
