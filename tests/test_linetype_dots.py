# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The dot of DASHDOT, CENTER and PHANTOM is drawn (#87).

Rafael (2026-10-12): "en el estilo «dash dot» el punto es muy difícil de
ver". A linetype's 0.0 dash reaches the backend as a zero-length line, and
GL rasterizes a zero-length line as nothing; the thick packer dropped them
outright. A thin dot is now a one-pixel point, a thick one a square as
wide as the pen.
"""
from __future__ import annotations

import ezdxf
import numpy as np
import pytest

from core.document import Document
from render.backend import build_scene


def _scene(lineweight):
    doc = ezdxf.new("R2018", setup=True)
    # DASHDOT here: a 2.54 dash, a 0.508 gap, the dot, a 0.508 gap
    doc.modelspace().add_line((0.0, 0.0), (100.0, 0.0), dxfattribs={
        "linetype": "DASHDOT", "lineweight": lineweight})
    return build_scene(Document(doc))


def _dots_x(scene):
    pos = scene.points.positions().astype(np.float64) + scene.origin
    return sorted(round(x, 3) for x in pos[:, 0])


def test_a_thin_dashdot_line_draws_its_dots():
    scene = _scene(25)
    expected = [3.048 + 3.556 * k for k in range(28)]
    # (each dot still takes ezdxf's min_dash_length of the pattern: a drift)
    assert _dots_x(scene) == pytest.approx(expected, abs=0.2)
    assert scene.handle_ranges, "the dots must belong to the line"
    (handle,) = scene.handle_ranges
    assert any(name == "points" for name, _f, _c in scene.handle_ranges[handle])


def test_a_thick_dashdot_line_draws_its_dots_as_squares():
    scene = _scene(50)
    assert scene.points.vertex_count == 0
    normals = scene.thick.data["normal"].reshape(-1, 6, 2)
    squares = [n for n in normals if np.allclose(np.abs(n), 1.0)]
    assert len(squares) == 28
    # each covers the pen's width both ways: corners at (+-1, +-1) halves
    assert {tuple(c) for c in squares[0]} == {(-1, 1), (-1, -1), (1, 1), (1, -1)}


def test_the_plot_draws_each_dot_as_wide_as_the_pen(qapp):
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QImage, QPainter

    from formats import pdf_out

    class Page:
        class Unit:
            DevicePixel = 0

        def pageRect(self, _unit):
            return QRect(0, 0, 1000, 1000)

        def resolution(self):
            return 600

    document = Document.new()
    doc = document.doc
    # 0.2 dash, 0.05 gap, dot, 0.05 gap: at 40 paper mm per unit a dot
    # every 12 mm, and a 0.50 mm pen is 12 px at 600 dpi
    doc.linetypes.add("PUNTO", pattern=[0.3, 0.2, -0.05, 0.0, -0.05],
                      description="dash dot")
    document.modelspace().add_line((0, 0.5), (1, 0.5), dxfattribs={
        "linetype": "PUNTO", "lineweight": 50})
    image = QImage(1000, 1000, QImage.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    pdf_out.plot(document, Page(), area=(0, 0, 1, 1), mm_per_unit=40.0,
                 painter=painter)
    painter.end()
    rows = [y for y in range(1000)
            if any(image.pixelColor(x, y).lightness() < 128 for x in range(0, 1000, 2))]
    y = (rows[0] + rows[-1]) // 2                 # through the line's middle
    row = [image.pixelColor(x, y).lightness() < 128 for x in range(1000)]
    runs, n = [], 0
    for dark in row + [False]:
        if dark:
            n += 1
        elif n:
            runs.append(n)
            n = 0
    dots = [r for r in runs if r < 30]
    dashes = [r for r in runs if r >= 30]
    assert len(dashes) >= 4
    assert len(dots) >= len(dashes) - 1, runs
    assert all(8 <= r <= 14 for r in dots), runs
