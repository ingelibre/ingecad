# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A large text is never culled as tiny because its layer's texts are small
(GeoCad's review, plan 0.6.8 item 4.1).

Text below 2 px is skipped when zoomed out, judged per batch range by the
AVERAGE glyph height -- and texts of one layer and colour shared a batch
whatever their size. A layer of a thousand small labels and one title: the
average was the labels', and the title vanished with them. Texts now batch
by size step, so a range's average describes texts of about one size.
"""
from __future__ import annotations

import ezdxf
import numpy as np

from core.document import Document
from render.backend import build_scene


def _visible_handles(scene, px_per_unit):
    x0, y0, x1, y1 = scene.extents             # ranges are bounded in world
    rect = (x0 - 1, y0 - 1, x1 + 1, y1 + 1)
    runs = scene.triangles.visible_runs(rect, px_per_unit, 2.0)
    shown = np.zeros(scene.triangles.vertex_count, dtype=bool)
    for first, count in runs:
        shown[first:first + count] = True
    return {h for h, rs in scene.handle_ranges.items()
            if any(name == "triangles" and shown[f:f + c].any()
                   for name, f, c in rs)}


def test_a_title_among_small_labels_survives_the_zoom_out():
    doc = ezdxf.new("R2018", setup=True)
    msp = doc.modelspace()
    for i in range(1000):
        msp.add_text("p", height=1.0, dxfattribs={"insert": (i * 3.0, 0.0)})
    title = msp.add_text("PLANTA GENERAL", height=50.0,
                         dxfattribs={"insert": (0.0, 100.0)})
    scene = build_scene(Document(doc))
    shown = _visible_handles(scene, 0.5)        # labels 0.5 px, title 25 px
    assert title.dxf.handle in shown
    # and the culling still does its job on the small ones
    assert len(shown) < 20
