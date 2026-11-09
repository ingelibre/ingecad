# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""An attached image's frame snaps: ENDpoint at its corners, MIDpoint on
its sides, INSertion at its insertion point.

A third-party plugin added these itself; the snap engine skipped IMAGE
altogether, so tracing over a scanned plan could not start on its frame.
"""
from __future__ import annotations

import pytest

from tests.test_image_surgical import _win_with_image


@pytest.fixture
def win(qapp, tmp_path):
    w = _win_with_image(qapp, tmp_path)       # 9.6 x 6.4 at 10,20
    w._on_command_submitted("ZOOM")
    w._on_command_submitted("E")
    yield w
    w.tools.cancel()
    w.document.dirty = False
    w.close()


@pytest.mark.parametrize("modes,cursor,kind,where", [
    ({"END"}, (19.4, 26.2), "END", (19.6, 26.4)),
    ({"MID"}, (14.6, 20.2), "MID", (14.8, 20.0)),
    ({"INS"}, (10.2, 20.2), "INS", (10.0, 20.0)),
])
def test_the_frame_snaps(win, modes, cursor, kind, where):
    tools = win.tools
    tools.osnap_on = True
    tools.osnap_modes = set(modes)
    win._on_command_submitted("LINE")
    tools.on_hover(*cursor, threshold_world=1.0)
    hit = tools.snap_hit
    assert hit is not None and hit.kind == kind
    assert (round(hit.x, 6), round(hit.y, 6)) == where
