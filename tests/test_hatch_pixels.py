# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A hatch that was created is seen: counted in the pixels of the frame.

A review video hatched a region some 14 000 units wide, far from the
origin, with ANSI31 at scale 0.1: the command line said "Hatch created."
and the screen showed nothing, though the scene held the pattern's lines.
What the scene holds is not what the user sees, so this looks at the frame.
"""
from __future__ import annotations

import time

import pytest


@pytest.fixture
def win(qapp, clean_settings):
    from views.main_window import MainWindow

    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w.new_document()
    yield w
    w.document.dirty = False
    w.close()


def _type(win, *texts):
    for text in texts:
        win._on_command_submitted(text)


def _settle(qapp, win, timeout_s=30.0):
    t0 = time.monotonic()
    while win._regen_worker is not None and time.monotonic() - t0 < timeout_s:
        qapp.processEvents()
    qapp.processEvents()


def _frame(qapp, win):
    _settle(qapp, win)
    win.viewport.update()
    qapp.processEvents()
    win.viewport.grabFramebuffer()            # the first may lack a pass
    return win.viewport.grabFramebuffer()


def _red_share(img, view, x0, y0, x1, y1, step=3) -> float:
    """How much of the world rectangle, as it lies on screen, is red."""
    ax, ay = view.world_to_screen(x0, y0)
    bx, by = view.world_to_screen(x1, y1)
    left, right = sorted((int(ax), int(bx)))
    top, bottom = sorted((int(ay), int(by)))
    lit = seen = 0
    for px in range(max(left, 0), min(right, img.width()), step):
        for py in range(max(top, 0), min(bottom, img.height()), step):
            c = img.pixelColor(px, py)
            seen += 1
            lit += c.red() > 110 and c.green() < 90 and c.blue() < 90
    assert seen > 500, "the region is not on screen"
    return lit / seen


#: The region of the video: far from the origin, 14 000 x 8 000.
X0, Y0, X1, Y1 = 9600.0, 9600.0, 23600.0, 17600.0


@pytest.mark.parametrize("regen", [False, True])
@pytest.mark.parametrize("scale", ["0.1", "1", "40"])
def test_a_pattern_hatch_shows_inside_its_boundary_and_not_outside(
        qapp, win, scale, regen):
    win.document.doc.layers.get("0").color = 1          # red, to count it
    _type(win, "RECTANG", f"{X0},{Y0}", f"{X1},{Y1}", "ZOOM", "E")
    before = _frame(qapp, win)
    view = win.viewport.view
    inside = (X0 + 1500, Y0 + 1500, X1 - 1500, Y1 - 1500)
    assert _red_share(before, view, *inside) < 0.01     # the control: empty

    _type(win, "-HATCH", "P", "ANSI31", scale, "0",
          f"{(X0 + X1) / 2},{(Y0 + Y1) / 2}", "")
    (hatch,) = win.document.modelspace().query("HATCH")
    assert hatch.dxf.pattern_name == "ANSI31"
    if regen:                                   # from the baked scene, too
        win.regen_in_memory()
    after = _frame(qapp, win)

    share = _red_share(after, view, *inside)
    # at 0.1 and 1 the lines lie closer than a pixel: the area reads as a
    # tone; at 40 they are 127 units apart, some 9 pixels: separate lines
    assert share > (0.5 if scale != "40" else 0.05), share
    if scale == "40":
        assert share < 0.6, share               # lines, not a solid fill
    # nothing spills past the boundary
    margin = (X1 - X0) * 0.04
    assert _red_share(after, view, X1 + margin * 0.3, Y0 + 1500,
                      X1 + margin, Y1 - 1500, step=1) < 0.01
