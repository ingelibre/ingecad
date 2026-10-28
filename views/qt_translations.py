# SPDX-License-Identifier: GPL-3.0-or-later
"""Qt's own strings in the UI language: the standard buttons (OK, Cancel,
Save, Discard...), the context menus of line edits, the file dialogs.

IngeCAD's packs translate what IngeCAD writes; what Qt writes comes from
Qt's catalogs (qtbase_<lang>.qm), shipped with PySide6. Without one, a
Spanish window asks "¿Guardar los cambios?" over English buttons.
"""
from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QTranslator

_installed: QTranslator | None = None


def install(code: str) -> bool:
    """Swap Qt's catalog for language ``code``; True when one was loaded.

    English needs none (Qt's own strings are English), and a language Qt
    does not ship falls back to English the same way.
    """
    global _installed
    app = QCoreApplication.instance()
    if app is None:
        return False
    if _installed is not None:
        app.removeTranslator(_installed)
        _installed = None
    if code == "en":
        return False
    translator = QTranslator(app)
    # QLocale lets Qt try "pt_PT", then "pt"... so "pt" finds qtbase_pt_BR
    # only by name: ask for the region Qt ships when the bare one is missing
    directory = QLibraryInfo.path(QLibraryInfo.TranslationsPath)
    for name in (code, {"pt": "pt_BR", "zh": "zh_CN"}.get(code, code)):
        if translator.load(QLocale(name), "qtbase", "_", directory):
            app.installTranslator(translator)
            _installed = translator
            return True
    return False
