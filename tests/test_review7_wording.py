# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Small things Rafael's seventh review showed on screen, in Spanish."""
from __future__ import annotations

import pytest

from core import i18n


@pytest.fixture
def spanish():
    before = i18n.current_language() if hasattr(i18n, "current_language") \
        else "en"
    i18n.set_language("es")
    yield
    i18n.set_language(before or "en")


def test_lineweight_default_reads_in_spanish(spanish):
    from core import layers

    assert layers.lineweight_label(-3) == "Por defecto"
    assert layers.lineweight_label(-1) == "PorCapa"


def test_center_mark_type_and_purge_words(spanish):
    from core.i18n import tr

    assert tr("Mark") == "Marca"
    assert tr("Regapps") == "Aplicaciones registradas"
    assert tr("{count} selected.", count=1) == "1 seleccionado(s)."


def test_xattach_default_matches_its_option(spanish):
    from core.i18n import tr

    prompt = tr("Enter reference type [Attachment/Overlay] <{t}>:",
                t=tr("Attachment"))
    assert prompt.endswith("[Enlazar(A)/Superponer(O)] <Enlazar>:"), prompt


def test_the_styles_panel_opens_on_the_current_style(qapp):
    """Edit with nothing picked did nothing (10:50): the list now starts on
    the current style, as AutoCAD's STYLE does."""
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        win.new_document()
        win.show()
        qapp.processEvents()
        panel = win._styles_panel
        panel.refresh()
        assert panel._selected() is not None, "nothing is picked"
    finally:
        win.document.dirty = False
        win.close()
