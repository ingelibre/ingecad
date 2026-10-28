# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A polyline's per-vertex widths survive Save as DWG and opening a DWG.

LibreDWG lost them both ways: its DXF importer flagged the widths with the
const-width bit (4) instead of "has widths" (32), so the DWG carried none
-- a PLINE drawn with Width came back hairline --, and dwg2dxf wrote them
only when the polyline also had bulges, so a colleague's plan opened with
its wide polylines thin (962 polylines in 44 of 200 corpus plans; ODA
reads the widths). Fixed in the vendored LibreDWG
(tools/libredwg-patches/README.md, 2026-10-11).
"""
from __future__ import annotations

import ezdxf
import pytest

from core.document import Document
from formats.dwg_bridge import find_dxf2dwg, load_dwg


@pytest.mark.skipif(find_dxf2dwg() is None, reason="LibreDWG not available")
def test_per_vertex_widths_survive_the_dwg_round_trip(tmp_path):
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    # constant along a straight run, then an arrow; no bulges anywhere
    msp.add_lwpolyline([(0, 0, 0.2, 0.2, 0), (10, 0, 0.2, 0.2, 0),
                        (10, 10, 0.0, 1.0, 0)], format="xyseb")
    # a first segment without width: dwg2dxf writes no 40 for it
    msp.add_lwpolyline([(0, 20, 0, 0, 0), (10, 20, 0.3, 0.6, 0),
                        (20, 20, 0, 0, 0)], format="xyseb")
    dwg = tmp_path / "widths.dwg"
    Document(doc).save_as(dwg)
    back = load_dwg(dwg)
    widths = [[tuple(round(float(v), 6) for v in row[2:4])
               for row in poly.get_points("xyseb")]
              for poly in back.modelspace().query("LWPOLYLINE")]
    assert widths == [
        [(0.2, 0.2), (0.2, 0.2), (0.0, 1.0)],
        [(0.0, 0.0), (0.3, 0.6), (0.0, 0.0)],
    ]
