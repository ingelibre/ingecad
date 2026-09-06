# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A layer that a command creates (a plugin's grid on its own layer) or
removes (the undo of it) reaches the Layers tab in the same command --
the tab used to learn of it only from its own actions, while the layer
control of the toolbar already keyed on the tables' content."""
from __future__ import annotations

from core.actions import AddEntityCommand
from core.commands import CompositeCommand
from core.layers import NewLayerCommand


def test_a_layer_a_command_creates_reaches_the_layers_tab_and_leaves_with_the_undo(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        win.new_document("m")
        panel = win._layers_panel
        assert panel is not None and "TERRENO-DEM" not in panel._rows
        win.tools._execute(CompositeCommand("DEM points", [
            NewLayerCommand("TERRENO-DEM", color=8),
            AddEntityCommand("DEM-POINT", lambda msp: msp.add_point((1.0, 2.0, 3.0)), layer="TERRENO-DEM"),
        ]))
        win.tools.changed.emit()        # what every click, typed answer and finish does after executing
        assert "TERRENO-DEM" in panel._rows
        assert [win._layer_combo.itemText(i) for i in range(win._layer_combo.count())].count("TERRENO-DEM") == 1
        win.dispatcher.submit("U")
        assert "TERRENO-DEM" not in panel._rows
        assert "TERRENO-DEM" not in win.document.doc.layers
        # and the refresh is keyed: a command that touches no table leaves the key alone
        key = win._layers_panel_key
        win.tools._execute(AddEntityCommand("LINE", lambda msp: msp.add_line((0, 0), (1, 1))))
        win.tools.changed.emit()
        assert win._layers_panel_key == key
    finally:
        win.document.dirty = False
        win.close()
