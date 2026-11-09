# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Attribute Definition dialog's Justification list is translated.

With the interface in Spanish it read Left, Center, Top Left... (a review
video): the dialog built its own English labels. It takes the Properties
panel's list (core.text_justify), translated alike.
"""
from __future__ import annotations

from core import i18n, text_justify


def test_justification_reads_in_the_interface_language(qapp, clean_settings):
    from views.attdef_dialog import AttDefDialog
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document()
    try:
        i18n.set_language("es")
        dialog = AttDefDialog(win, win.document)
        combo = dialog.justification
        labels = [combo.itemText(i) for i in range(combo.count())]
        names = [combo.itemData(i) for i in range(combo.count())]
        dialog.deleteLater()
    finally:
        i18n.set_language("en")
        win.document.dirty = False
        win.close()
    assert names == [n for _l, n in text_justify.JUSTIFICATIONS]
    assert labels[0] == "Izquierda"
    assert "Left" not in labels and "Top Left" not in labels
