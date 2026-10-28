# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Annotative dimensions measure the same on paper in every viewport.

What Rafael calls "lo único que falla" (reviews 6 and 7): with his
dimensions annotative and the 2:1 scale added, the 2:1 viewport still drew
them twice as big as the 1:1 one -- measured 2.24x. The scale's
representation pointed at the same *D block as the 1:1 one; AutoCAD gives
each scale its own block, drawn at that scale (docs/reference/annotative,
file G: "a 4-scale dimension owns 4 *D blocks").

Measured end to end: the sheet drawn as PLOT draws it, the dimension text
(red) counted in pixels in each viewport. 1.00 is the same paper size.
"""
from __future__ import annotations

import numpy as np
import pytest

from core import actions, annotative as A, layouts as L
from core.commands import CompositeCommand
from core.document import Document


def _run(document, command):
    command.do(document)
    return command


def _sheet(dims_kind: str):
    document = Document.new()
    doc = document.doc
    iso = doc.dimstyles.get("ISO-25")
    iso.dxf.dimclrt = 1                       # red text, to count it
    iso.dxf.dimclrd = 3
    iso.dxf.dimclre = 3
    doc.header["$DIMSTYLE"] = "ISO-25"
    if dims_kind == "born":
        iso.dxf.dimtxt = 2.5
        A.set_style_annotative(iso, True)
    dims = []
    for cmd in (actions.dim_linear((-20, -20), (30, -20), (5, -30)),
                actions.dim_aligned((-20, 0), (20, 20), (-25, 10)),
                # inside what the 2:1 viewport shows (±30 around 5,-5)
                actions.dim_radius((15, 2), 6.0, (21, 8)),
                actions.dim_diameter((-10, 12), 4.0, (-17, 17))):
        _run(document, cmd)
        dims.append(cmd.dim)
    if dims_kind == "after":
        _run(document, A.AnnotativePropertyCommand(dims, True))
    _run(document, A.ObjectScaleCommand(dims, "2:1", add=True))
    vp_a = _run(document, L.AddViewportCommand(
        "Layout1", (75, 100), (130, 120), (5, -5), 120)).entity
    vp_b = _run(document, L.AddViewportCommand(
        "Layout1", (225, 100), (130, 120), (5, -5), 120)).entity
    for vp, ratio, name in ((vp_a, 1.0, "1:1"), (vp_b, 2.0, "2:1")):
        _run(document, CompositeCommand("VPSCALE", [
            L.xp_zoom_command(vp, ratio),
            A.SetAnnotationScaleCommand(A.standard_scale(doc, name).name,
                                        viewport=vp)]))
    return document, dims


def _red_pixels(document) -> tuple[int, int]:
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter

    from formats.pdf_out import build_graphics_scene

    scene = build_graphics_scene(document, "Layout1", ctb="")
    k = 6                                     # pixels per mm
    img = QImage(300 * k, 200 * k, QImage.Format_RGB32)
    img.fill(QColor("white"))
    painter = QPainter(img)
    scene.render(painter, QRectF(0, 0, img.width(), img.height()),
                 QRectF(0, 0, 300, 200))
    painter.end()
    ptr = img.constBits()
    arr = np.frombuffer(ptr, np.uint8).reshape(img.height(), img.width(), 4)
    red = (arr[:, :, 2] > 180) & (arr[:, :, 1] < 90) & (arr[:, :, 0] < 90)
    half = img.width() // 2
    return int(red[:, :half].sum()), int(red[:, half:].sum())


@pytest.mark.parametrize("dims_kind", ["after", "born"])
def test_dimension_text_measures_the_same_in_1_1_and_2_1(qapp, dims_kind):
    document, dims = _sheet(dims_kind)
    at_1, at_2 = _red_pixels(document)
    assert at_1 > 200, f"control: the 1:1 viewport drew {at_1} text pixels"
    assert at_2 / at_1 == pytest.approx(1.0, abs=0.12), (
        f"2:1 / 1:1 = {at_2 / at_1:.2f}")


def test_each_scale_has_its_own_block_drawn_at_its_size(qapp):
    """Radius and diameter included -- they could not carry a scale at all
    ("OBJECTSCALE skipped 2"), and Rafael's part has R10, R26, R3."""
    document, dims = _sheet("born")
    assert len(dims) == 4
    for dim in dims:
        reps = {r.scale.name: r for r in A.representations(dim)}
        assert set(reps) == {"1:1", "2:1"}
        b1, b2 = reps["1:1"].first(2) or dim.dxf.geometry, reps["2:1"].first(2)
        assert b1 != b2, "both scales draw the same block"
        h1 = next(e.dxf.char_height for e in document.doc.blocks.get(b1)
                  if e.dxftype() == "MTEXT")
        h2 = next(e.dxf.char_height for e in document.doc.blocks.get(b2)
                  if e.dxftype() == "MTEXT")
        assert h2 == pytest.approx(h1 / 2.0), (h1, h2)


def _scale_block(document, dim, name):
    rep = next(r for r in A.representations(dim) if r.scale.name == name)
    return document.doc.blocks.get(rep.first(2) or dim.dxf.geometry)


def _text_of(block) -> str:
    return next(e.text for e in block if e.dxftype() == "MTEXT")


def _xs(block):
    return sorted(round(e.dxf.start.x, 6) for e in block if e.dxftype() == "LINE")


def test_the_other_scales_follow_a_move_and_its_undo(qapp):
    from core.commands import History

    document, dims = _sheet("born")
    dim = dims[0]
    history = History(document)
    before = _xs(_scale_block(document, dim, "2:1"))
    history.execute(actions.move_entities([dim], 10, 0))
    after = _xs(_scale_block(document, dim, "2:1"))
    assert after == pytest.approx([x + 10 for x in before]), "2:1 stayed behind"
    history.undo()
    assert _xs(_scale_block(document, dim, "2:1")) == pytest.approx(before)


def test_the_other_scales_follow_a_grip_edit_and_its_undo(qapp):
    from core.commands import History

    document, dims = _sheet("born")
    dim = dims[0]                                   # 50 long
    history = History(document)
    assert "50" in _text_of(_scale_block(document, dim, "2:1"))
    history.execute(actions.DimGripCommand(dim, "defpoint3", (40, -20)))
    assert "60" in _text_of(_scale_block(document, dim, "2:1")), "2:1 kept 50"
    history.undo()
    assert "50" in _text_of(_scale_block(document, dim, "2:1"))
    # no block is left behind that nothing draws
    names = {dim.dxf.geometry} | {r.first(2) for r in A.representations(dim)}
    assert all(n in document.doc.blocks for n in names if n)


def test_the_scale_blocks_survive_save_and_reopen(qapp, tmp_path):
    import ezdxf

    document, _dims = _sheet("born")
    path = tmp_path / "anno.dxf"
    document.doc.saveas(path)
    again = Document(ezdxf.readfile(path))
    for dim in again.doc.modelspace().query("DIMENSION"):
        for rep in A.representations(dim):
            name = rep.first(2) or dim.dxf.geometry
            assert name in again.doc.blocks, f"{rep.scale.name}: {name} lost"
    at_1, at_2 = _red_pixels(again)
    assert at_2 / at_1 == pytest.approx(1.0, abs=0.12)


def _have_libredwg() -> bool:
    from formats.dwg_bridge import find_dxf2dwg

    return find_dxf2dwg() is not None


@pytest.mark.skipif(not _have_libredwg(), reason="LibreDWG not available")
def test_the_scales_survive_save_as_dwg(qapp, tmp_path):
    """Rafael works in DWG. LibreDWG's DXF importer dropped every context
    object (object_alias tested ACAD_ for ACDB_ names, and a dimension's
    embedded body aborted the import): after Save as DWG the dimensions came
    back with no scale and the 2:1 viewport drew them three times bigger.
    The vendor patch of 2026-10-10 imports them; checked here through
    IngeCAD's own save and open."""
    from formats.dwg_bridge import load_dwg

    document, _dims = _sheet("born")
    path = tmp_path / "anno.dwg"
    _engine, warnings = document.save_as(path)
    assert not warnings, warnings
    again = load_dwg(path)
    for dim in again.doc.modelspace().query("DIMENSION"):
        assert {r.scale.name for r in A.representations(dim)} == {"1:1", "2:1"}
    at_1, at_2 = _red_pixels(again)
    assert at_1 > 200 and at_2 / at_1 == pytest.approx(1.0, abs=0.12)
