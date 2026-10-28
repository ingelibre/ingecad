# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""PSLTSCALE: linetypes in viewports, measured on the sheet.

AutoCAD (Linetype Manager, "Use paper space units for scaling", reference
p. 1046): with PSLTSCALE=1 -- every new drawing's default -- a dash measures
pattern x LTSCALE on PAPER in every viewport, so a sheet with a 1:1 and a
1:2 view shows the same dashes in both; with 0 the dashes are model units.
"""
from __future__ import annotations

import ezdxf
import numpy as np
import pytest

from core.document import Document


def _first_dash(scene, handle, x_min, x_max) -> float:
    """Length on the sheet of the first whole dash inside [x_min, x_max]."""
    parts = [getattr(scene, batch).data["pos"][first:first + count].astype(float)
             for batch, first, count in scene.handle_ranges.get(handle, [])]
    pos = np.concatenate(parts) + np.array(scene.origin)
    segments = pos.reshape(-1, 2, 2)
    xs = [(min(a[0], b[0]), max(a[0], b[0])) for a, b in segments]
    inside = sorted((x0, x1) for x0, x1 in xs if x0 > x_min and x1 < x_max)
    x0, x1 = inside[1]                       # not the one cut by the edge
    return x1 - x0


@pytest.mark.parametrize("psltscale,at_half", [(1, 10.0), (0, 5.0)])
def test_viewport_dashes_measure_on_paper_what_autocad_draws(
        tmp_path, psltscale, at_half):
    """A 10-unit dash seen through a 1:1 and a 1:2 viewport, LTSCALE 1.
    AutoCAD: PSLTSCALE=1 (the default) draws it 10 mm on the sheet in both;
    PSLTSCALE=0 draws it 10 model units, 5 mm at 1:2. Before this, ezdxf's
    own scaling drew it 20 mm at 1:2 -- longer the smaller the scale."""
    from render.backend import build_scene

    doc = ezdxf.new("R2018", setup=False)
    doc.header["$PSLTSCALE"] = psltscale
    doc.linetypes.add("T", pattern=[15.0, 10.0, -5.0], description="test")
    line = doc.modelspace().add_line((-1000, 0), (1000, 0),
                                     dxfattribs={"linetype": "T"})
    sheet = doc.layouts.new("A3")
    sheet.add_viewport(center=(60, 50), size=(100, 60),
                       view_center_point=(0, 0), view_height=60)    # 1:1
    sheet.add_viewport(center=(200, 50), size=(100, 60),
                       view_center_point=(0, 0), view_height=120)   # 1:2
    doc.saveas(tmp_path / "sheet.dxf")
    document = Document(ezdxf.readfile(tmp_path / "sheet.dxf"))
    scene = build_scene(document, "A3")
    assert _first_dash(scene, line.dxf.handle, 10, 110) == pytest.approx(10.0, abs=0.05)
    assert _first_dash(scene, line.dxf.handle, 150, 250) == pytest.approx(
        at_half, abs=0.05)
