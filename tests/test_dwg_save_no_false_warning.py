# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Save as DWG warns only about real trouble.

Saving any recent AutoCAD plan as DWG said "Saved with a warning": the
bundled LibreDWG logged errors reading back the DXF IngeCAD hands it.

- A hatch boundary edge ending at Y = 0 ("Unknown DXF code 21 for HATCH"):
  in_dxf took 0.0 for "missing". The point came out right; the log lied.
- A detail or section view style -- in every AutoCAD 2013+ drawing --
  which ezdxf keeps verbatim, colors included, in the R2000 DXF:
  in_dxf read those colors only from an R2004+ DXF, lost its place, and
  the style reached the DWG with its sizes and text style zeroed.

Fixed in the vendored LibreDWG (tools/libredwg-patches, in_dxf.c).
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from formats.dwg_bridge import find_dxf2dwg

# As LibreDWG's dwg2dxf writes the Metric50 style of an AutoCAD 2018 plan.
_CLASS = """  0
CLASS
  1
ACDBDETAILVIEWSTYLE
  2
AcDbDetailViewStyle
  3
ObjectDBX Classes
 90
1025
280
0
281
0
"""
_STYLE = """  0
ACDBDETAILVIEWSTYLE
  5
9F00
330
C
100
AcDbModelDocViewStyle
 70
0
  3
Metric50
290
0
300
Metric50
 90
0
100
AcDbDetailViewStyle
 70
0
 71
0
 90
3
 71
1
340
11
 62
256
 40
5.0
340
0
 62
256
 40
5.0
300

 40
7.5
280
1
 71
2
340
16
 90
25
 62
256
 71
3
340
11
 62
256
 40
5.0
 90
0
 40
15.0
 90
1
300
%<\\AcVar ViewDetailId>%
 71
4
340
16
 90
25
 62
256
340
16
 90
25
 62
256
280
0
"""


def _plan_with_view_style(folder: Path):
    from core.document import Document
    from core.templates import new_document

    document = new_document("mm")
    msp = document.doc.modelspace()
    hatch = msp.add_hatch()
    edges = hatch.paths.add_edge_path()           # a boundary ON the X axis
    edges.add_line((0, 0), (10, 0))
    edges.add_line((10, 0), (10, 10))
    edges.add_line((10, 10), (0, 0))
    hatch.set_solid_fill()
    stream = io.StringIO()
    document.doc.write(stream)
    text = stream.getvalue()
    text = text.replace("CLASSES\n", "CLASSES\n" + _CLASS, 1)
    head, tail = text.rsplit("  0\nENDSEC\n  0\nEOF", 1)
    path = folder / "plano.dxf"
    path.write_text(head + _STYLE + "  0\nENDSEC\n  0\nEOF\n", encoding="utf-8")
    return Document.load(path)


@pytest.mark.skipif(find_dxf2dwg() is None, reason="LibreDWG not available")
def test_a_recent_autocad_plan_saves_as_dwg_without_a_warning(tmp_path: Path):
    from formats.dwg_bridge import load_dwg

    document = _plan_with_view_style(tmp_path)
    assert document.doc.entitydb.get("9F00") is not None
    _engine, warnings = document.save_as(tmp_path / "plano.dwg")
    assert warnings == []

    # and the style arrives whole: its identifier offset (7.5) and its
    # label offset (15.0) were zeroed before
    back = load_dwg(tmp_path / "plano.dwg")
    (style,) = [o for o in back.doc.objects
                if o.dxftype() == "ACDBDETAILVIEWSTYLE"]
    numbers = [t.value for t in style.xtags.get_subclass("AcDbDetailViewStyle")
               if t.code == 40]
    assert 7.5 in numbers and 15.0 in numbers
