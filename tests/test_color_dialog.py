# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Select Color dialog -- AutoCAD's Index Color tab."""
from __future__ import annotations

from views.color_dialog import SelectColorDialog


def test_the_swatches_are_big_enough_to_aim_at(qapp):
    """Marco: "el cuadradito de cada color está muy chiquito, tal vez
    hacerlo como 1.5x". They were 16 px. Aiming at one is the entire job of
    this dialog, and the whole palette still has to fit a laptop screen."""
    dialog = SelectColorDialog(None, current=3, include_bylayer=False)
    try:
        from PySide6.QtWidgets import QPushButton

        sides = {b.width() for b in dialog.findChildren(QPushButton)
                 if b.width() == b.height()}
        assert sides, "no square swatches"
        assert min(sides) >= 24, f"a swatch is only {min(sides)} px"
        assert dialog.sizeHint().width() < 900, (
            f"the palette got too wide: {dialog.sizeHint().width()} px")
    finally:
        dialog.deleteLater()
