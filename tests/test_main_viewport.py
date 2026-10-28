# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A sheet carries AutoCAD's main viewport -- id 1, status 1, the paper
view itself -- before any floating viewport.

IngeCAD's sheets had none, and AutoCAD and ODA, renumbering on opening,
took the FIRST floating viewport for the paper view: a sheet sent to a
colleague lost its first viewport (found checking annotative scales through
ODA, 2026-10-10: the 1:1 viewport came back empty).
"""
from __future__ import annotations

import os
import shutil
import subprocess

import ezdxf
import pytest

from core import layouts as L
from core.commands import History
from core.document import Document


def _viewports(layout):
    return [(v.dxf.id, v.dxf.status) for v in layout if v.dxftype() == "VIEWPORT"]


def test_mview_brings_the_main_viewport_and_undo_takes_it():
    document = Document.new()
    history = History(document)
    sheet = document.doc.layouts.get("Layout1")
    assert _viewports(sheet) == []
    history.execute(L.AddViewportCommand("Layout1", (100, 100), (80, 60), (0, 0), 60))
    ids = _viewports(sheet)
    assert ids[0] == (1, 1), ids
    assert len(ids) == 2 and ids[1][0] != 1
    assert L.visible_viewports(sheet) == [v for v in sheet
                                          if v.dxftype() == "VIEWPORT" and v.dxf.id != 1]
    history.execute(L.AddViewportCommand("Layout1", (200, 100), (80, 60), (0, 0), 60))
    assert [i for i, _s in _viewports(sheet)].count(1) == 1, "a second main one"
    history.undo()
    history.undo()
    assert _viewports(sheet) == []


def test_a_sheet_saved_without_it_gets_it_on_opening(tmp_path):
    doc = ezdxf.new("R2018")
    sheet = doc.layouts.get("Layout1")
    vp = sheet.add_viewport(center=(100, 100), size=(80, 60),
                            view_center_point=(0, 0), view_height=60)
    vp.dxf.id = 3
    doc.saveas(tmp_path / "old.dxf")
    document = Document.load(tmp_path / "old.dxf")
    again = document.doc.layouts.get("Layout1")
    assert _viewports(again)[0] == (1, 1)
    assert len(L.visible_viewports(again)) == 1


@pytest.mark.skipif(shutil.which("ODAFileConverter") is None
                    or not os.environ.get("DISPLAY"),
                    reason="ODA File Converter (a Qt app) is the development "
                           "judge only, and needs a display")
def test_odas_round_trip_keeps_every_floating_viewport(tmp_path):
    document = Document.new()
    for x in (75, 225):
        L.AddViewportCommand("Layout1", (x, 100), (130, 120), (0, 0), 120).do(document)
    (tmp_path / "in").mkdir()
    (tmp_path / "dwg").mkdir()
    (tmp_path / "back").mkdir()
    document.doc.saveas(tmp_path / "in" / "s.dxf")
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    for src, dst, fmt in (("in", "dwg", "DWG"), ("dwg", "back", "DXF")):
        subprocess.run(["ODAFileConverter", str(tmp_path / src), str(tmp_path / dst),
                        "ACAD2018", fmt, "0", "1"], timeout=120, env=env,
                       capture_output=True, check=False)
    back = ezdxf.readfile(tmp_path / "back" / "s.dxf").layouts.get("Layout1")
    assert len(L.visible_viewports(back)) == 2, _viewports(back)
