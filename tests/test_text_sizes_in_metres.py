# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""TEXT, MTEXT and MLEADER start at a paper size in the drawing's units.

The default drawing is in metres at 1:100. TEXT and MTEXT started at 2.5
-- 2.5 m -- and MLEADER at its style's 4.0 with a 2.0 landing gap, so the
text of a leader landed metres away (a YouTuber's staircase plan
reproduced in IngeCAD). AutoCAD keeps TEXTSIZE in the drawing and an
MLEADER follows its multileader style.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    window = MainWindow()
    window.show()
    window.new_document()
    yield window
    window.document.dirty = False
    window.close()


def test_a_first_text_takes_the_drawings_textsize(win):
    assert win.document.doc.header["$TEXTSIZE"] == pytest.approx(0.25)
    for text in ("TEXT", "0,0", "", "0"):      # Enter takes <height>
        win._on_command_submitted(text)
    win.tools.tool.on_char("A")
    win._on_command_submitted("")
    win._on_command_submitted("")
    texts = list(win.document.modelspace().query("TEXT"))
    assert [round(t.dxf.height, 9) for t in texts] == [0.25]


def test_an_mleader_is_sized_by_its_style_in_drawing_units(win):
    from core import leaders

    doc = win.document.doc
    assert leaders.mleader_text_height(doc) == pytest.approx(0.4)
    win.history.execute(leaders.add_mleader([(0, 0), (1, 1)], (1, 1), "x"))
    mleader = win.document.modelspace().query("MULTILEADER")[0]
    assert mleader.context.char_height == pytest.approx(0.4)
    # dogleg 0.8 + landing gap 0.2 from the landing, not 8 + 2
    assert mleader.context.mtext.insert.x == pytest.approx(2.0)
