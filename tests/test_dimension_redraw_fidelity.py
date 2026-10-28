# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A colleague's dimension redrawn in place reads what the author's CAD drew.

A grip edit, STRETCH or a property change re-renders a dimension's block
through ezdxf. Three ways that rewrote the author's number, found by
re-rendering every dimension of a corpus sample in place and comparing the
new block with the one the author's CAD wrote:

* an ALIGNED dimension from AutoCAD carries angle 0 (its direction is its
  two origins); ezdxf measured along that angle, so a vertical 2.54 read 0;
* LibreDWG leaves a DIMSTYLE's zeros implicit and ezdxf filled DIMZIN with
  8, so "0.10" read "0.1";
* a negative DIMLFAC applies in paper space only, and model-space
  dimensions read -10.00 for 10;
* a near-vertical dimension at UTM coordinates, rounded to whole units;
* halves rounded to even (".40" for .405), and a DIMPOST suffix without
  "<>" that aborted the edit.
"""
from __future__ import annotations

import ezdxf
import pytest

from core.actions import DimGripCommand
from core.commands import History
from core.document import Document
from formats.dwg_bridge import find_dxf2dwg, load_dwg


def _texts(doc, dim):
    return [e.plain_text() for e in doc.blocks.get(dim.dxf.geometry)
            if e.dxftype() == "MTEXT"]


def _grip_in_place(document, dim):
    p = dim.dxf.defpoint
    History(document).execute(DimGripCommand(dim, "defpoint", (p.x, p.y)))


def test_aligned_dimension_with_angle_zero_keeps_its_length():
    document = Document.new()
    d = document.doc
    d.dimstyles.new("Plain", dxfattribs={"dimdec": 2, "dimdsep": ord(".")})
    dim = document.modelspace().add_aligned_dim(
        p1=(0, 0), p2=(0, 2.54), distance=1, dimstyle="Plain").dimension
    dim.dxf.dimtype = 33             # aligned, as a DWG arrives
    dim.dxf.angle = 0.0              # what AutoCAD writes for an aligned one
    assert abs(dim.get_measurement() - 2.54) < 1e-9
    _grip_in_place(document, dim)
    assert _texts(d, dim) == ["2.54"]


def test_negative_dimlfac_is_ignored_in_model_space():
    document = Document.new()
    d = document.doc
    d.dimstyles.new("Planta", dxfattribs={
        "dimlfac": -1.0, "dimdec": 2, "dimzin": 0, "dimdsep": ord(".")})
    dim = document.modelspace().add_linear_dim(
        base=(0, 2), p1=(0, 0), p2=(10, 0), dimstyle="Planta") \
        .render().dimension
    _grip_in_place(document, dim)
    assert _texts(d, dim) == ["10.00"]


@pytest.mark.skipif(find_dxf2dwg() is None, reason="LibreDWG not available")
def test_dimstyle_zeros_survive_opening_a_dwg(tmp_path):
    doc = ezdxf.new("R2018")
    doc.dimstyles.new("Ceros", dxfattribs={
        "dimzin": 0, "dimdec": 2, "dimtofl": 0, "dimdsep": ord(".")})
    doc.dimstyles.new("Enteros", dxfattribs={
        "dimzin": 0, "dimdec": 0, "dimdsep": ord(".")})
    doc.modelspace().add_linear_dim(
        base=(0, 1), p1=(0, 0), p2=(0.1, 0), dimstyle="Ceros").render()
    doc.modelspace().add_linear_dim(
        base=(0, 5), p1=(0, 4), p2=(9657.3, 4), dimstyle="Enteros").render()
    dwg = tmp_path / "ceros.dwg"
    Document(doc).save_as(dwg)
    back = load_dwg(dwg)
    style = back.doc.dimstyles.get("Ceros")
    assert style.dxf.get("dimzin") == 0 and style.dxf.get("dimtofl") == 0
    tenth, whole = back.modelspace().query("DIMENSION")
    _grip_in_place(back, tenth)
    assert _texts(back.doc, tenth) == ["0.10"]
    _grip_in_place(back, whole)         # DIMDEC 0, not ezdxf's 2
    assert _texts(back.doc, whole) == ["9657"]


def test_near_vertical_dimension_at_utm_keeps_its_length():
    """AutoCAD's "vertical" origins differ by 1e-13 in x; at UTM
    coordinates ezdxf's slope/intercept rays rounded the dimension line to
    whole units and 1.60 read 2.00 (a reservoir plan, handle 829B)."""
    document = Document.new()
    d = document.doc
    d.dimstyles.new("Plain", dxfattribs={"dimdec": 2, "dimzin": 0,
                                         "dimdsep": ord(".")})
    dim = document.modelspace().add_aligned_dim(
        p1=(724674.2678785534, 8325513.635514607),
        p2=(724674.2678785532, 8325512.035514606),
        distance=0.19, dimstyle="Plain").dimension
    dim.dxf.dimtype = 33
    dim.dxf.angle = 0.0
    _grip_in_place(document, dim)
    assert _texts(d, dim) == ["1.60"]


def test_halves_round_up_and_a_bare_dimpost_is_a_suffix():
    from ezdxf.render import dim_base

    document = Document.new()              # applies the patches
    assert dim_base.format_text(0.405, None, 2, 0, ".") == "0.41"
    assert dim_base.format_text(2.625, None, 2, 0, ".") == "2.63"
    assert dim_base.format_text(2.99499999999, None, 2, 0, ".") == "3.00"
    # noise further below the half is the author's own .31
    assert dim_base.format_text(0.3149999999437, None, 2, 0, ".") == "0.31"
    d = document.doc
    d.dimstyles.new("Metros", dxfattribs={"dimdec": 2, "dimzin": 0,
                                          "dimpost": " m", "dimdsep": ord(".")})
    dim = document.modelspace().add_linear_dim(
        base=(0, 2), p1=(0, 0), p2=(2.5, 0), dimstyle="Metros") \
        .render().dimension
    _grip_in_place(document, dim)
    assert _texts(d, dim) == ["2.50 m"]


def _plain_dim(document, style="Plain", **style_attribs):
    attribs = {"dimdec": 2, "dimzin": 0, "dimdsep": ord(".")}
    attribs.update(style_attribs)
    document.doc.dimstyles.new(style, dxfattribs=attribs)
    return document.modelspace().add_linear_dim(
        base=(0, 2), p1=(0, 0), p2=(10, 0), dimstyle=style).render().dimension


def _block_kinds(document, dim):
    return [e.dxftype() for e in document.doc.blocks.get(dim.dxf.geometry)]


def test_edits_that_aborted_now_redraw():
    """A "_NONE" arrow with no block of the name (1314 dimensions in 8
    plans) and an older block whose text is a TEXT both made the grip edit
    raise."""
    document = Document.new()
    dim = _plain_dim(document, dimblk="_NONE")
    _grip_in_place(document, dim)
    old = _plain_dim(document, "Old")
    block = document.doc.blocks.get(old.dxf.geometry)
    for e in [e for e in block if e.dxftype() == "MTEXT"]:
        block.delete_entity(e)
    block.add_text("10.00", dxfattribs={"insert": (5, 2), "height": 1})
    _grip_in_place(document, old)
    assert _texts(document.doc, old) == ["10.00"]


def test_a_suppressed_dimension_line_takes_its_arrows_along():
    document = Document.new()
    dim = _plain_dim(document, dimsd1=1, dimsd2=1)
    _grip_in_place(document, dim)
    assert "INSERT" not in _block_kinds(document, dim)


def test_hand_placed_text_stays_where_the_author_put_it():
    """AutoCAD keeps group 11 on the line and offsets the text by DIMTAD;
    ezdxf centred it on group 11, so 2013 of 2829 hand-placed labels of a
    corpus sample fell onto their line at the first grip."""
    document = Document.new()
    dim = _plain_dim(document, dimtad=1)
    dim.dxf.dimtype = int(dim.dxf.dimtype) | 128
    block = document.doc.blocks.get(dim.dxf.geometry)
    text = next(e for e in block if e.dxftype() == "MTEXT")
    text.dxf.insert = (3.0, 3.5, 0.0)          # where the author placed it
    _grip_in_place(document, dim)
    block = document.doc.blocks.get(dim.dxf.geometry)
    text = next(e for e in block if e.dxftype() == "MTEXT")
    assert tuple(text.dxf.insert)[:2] == pytest.approx((3.0, 3.5))


def test_a_mirrored_dimension_stays_put_and_undo_gives_it_back():
    """Extrusion (0, 0, -1): the redrawn block landed at -X (477 of 477
    dimensions of a fence plan)."""
    from ezdxf import bbox

    document = Document.new()
    dim = _plain_dim(document)
    dim.dxf.defpoint = (100, 2, 0)
    dim.dxf.defpoint2 = (100, 0, 0)
    dim.dxf.defpoint3 = (110, 0, 0)
    dim.render()
    # the same dimension as AutoCAD's MIRROR stores it
    mid = dim.dxf.text_midpoint
    dim.dxf.text_midpoint = (-mid.x, mid.y, -mid.z)
    dim.dxf.angle = 180.0 - float(dim.dxf.get("angle", 0.0))
    dim.dxf.extrusion = (0, 0, -1)
    history = History(document)
    p = dim.dxf.defpoint
    history.execute(DimGripCommand(dim, "defpoint", (p.x, p.y)))
    box = bbox.extents([dim])
    assert 99 < box.center.x < 111
    assert _texts(document.doc, dim) == ["10.00"]
    history.undo()
    assert tuple(dim.dxf.extrusion) == (0, 0, -1)


def test_a_grip_keeps_the_height_of_the_point_it_moves():
    document = Document.new()
    msp = document.modelspace()
    dim = msp.add_radius_dim(center=(0, 0, 500), radius=1.8, angle=30) \
        .render().dimension
    point = dim.dxf.defpoint4
    History(document).execute(
        DimGripCommand(dim, "defpoint4", (point.x, point.y)))
    assert dim.dxf.defpoint4.z == 500




def test_a_two_line_angular_measures_the_sector_of_its_arc_point():
    """Two lines make four angles; ezdxf went counter-clockwise from the
    first ray to the second whatever the arc point said (27 read 333)."""
    import math

    document = Document.new()
    doc = document.doc
    msp = doc.modelspace()
    a = math.radians(27)
    b = math.radians(9)
    dim = msp.new_entity("DIMENSION", {
        "dimtype": 34, "dimstyle": "Standard",
        "defpoint2": (0, 0), "defpoint3": (10, 0), "defpoint4": (0, 0),
        "defpoint": (10 * math.cos(a), 10 * math.sin(a)),
        "defpoint5": (5 * math.cos(b), 5 * math.sin(b)),
        "text_midpoint": (5, 1)})
    doc.dimstyles.get("Standard").dxf.dimadec = 0
    dim.render()
    assert _texts(doc, dim) == ["27°"]


@pytest.mark.skipif(find_dxf2dwg() is None, reason="LibreDWG not available")
def test_two_line_angular_points_of_an_oda_dwg():
    """LibreDWG swapped DXF 10 and 16 of a 2-line angular, reading and
    writing alike -- so its own round trip agreed with itself and only a
    DWG from another writer shows it. tests/data/angular_2l_oda.dwg is
    ODA File Converter's DWG of a synthetic drawing: line 1 along X, line 2
    to (8, 6), the arc through (6, 2)."""
    from pathlib import Path

    path = Path(__file__).parent / "data" / "angular_2l_oda.dwg"
    dim = load_dwg(path).modelspace().query("DIMENSION")[0]
    assert tuple(round(v, 6) for v in dim.dxf.defpoint)[:2] == (8.0, 6.0)
    assert tuple(round(v, 6) for v in dim.dxf.defpoint5)[:2] == (6.0, 2.0)


def test_a_three_point_angular_measures_the_side_of_its_arc():
    """ezdxf went counter-clockwise from the first point whatever side the
    arc was on: 326 of 709 corpus dimensions read 360 minus their angle."""
    document = Document.new()
    msp = document.modelspace()
    texts = []
    for base in ((5, 5), (-5, -5)):
        dim = msp.add_angular_dim_3p(base=base, center=(0, 0), p1=(10, 0),
                                     p2=(0, 10)).render().dimension
        texts.append(_texts(document.doc, dim))
    assert texts == [["90°"], ["270°"]]


def test_an_arc_length_has_no_text_prefix():
    """DIMARCSYM 0 draws AutoCAD's arc symbol as geometry; ezdxf wrote
    "( " before the number (266 of 402 corpus arc lengths)."""
    document = Document.new()
    document.doc.dimstyles.new("Arco", dxfattribs={
        "dimarcsym": 0, "dimdec": 2, "dimzin": 0, "dimdsep": ord(".")})
    msp = document.modelspace()
    dim = msp.add_arc_dim_cra(center=(0, 0), radius=5, start_angle=0,
                              end_angle=90, distance=1,
                              dimstyle="Arco").render().dimension
    assert _texts(document.doc, dim) == ["7.85"]


def _readable(document, dim):
    """(text, height, rotation in degrees) of a dimension's text."""
    import math

    out = []
    for e in document.doc.blocks.get(dim.dxf.geometry):
        if e.dxftype() == "MTEXT":
            d = e.dxf.get("text_direction", None)
            angle = math.degrees(math.atan2(d.y, d.x)) if d is not None \
                else float(e.dxf.get("rotation", 0.0))
            out.append((e.plain_text(), round(e.dxf.char_height, 9),
                        round(angle, 6)))
    return out


def test_rotate_scale_and_mirror_redraw_a_dimension_as_autocad_does():
    """Found redrawing a YouTuber's staircase: ROTATE 90 left the text
    upside down, SCALE 2 kept 0.28 on a 0.56 run at twice the height, and
    MIRROR drew the copies on top of the originals."""
    from ezdxf import bbox

    document = Document.new()
    msp = document.modelspace()
    document.doc.dimstyles.new("P", dxfattribs={
        "dimdec": 2, "dimzin": 0, "dimdsep": ord("."), "dimtxt": 0.04,
        "dimasz": 0.03})
    dim = msp.add_linear_dim(base=(0, 0.3), p1=(0, 0), p2=(0.28, 0),
                             dimstyle="P").render().dimension
    history = History(document)
    history.execute(actions_rotate([dim], 90))
    text, height, angle = _readable(document, dim)[0]
    assert text == "0.28" and height == 0.04
    assert -90.0 < angle <= 90.0, "the text reads upside down"
    history.undo()
    assert dim.dxf.defpoint3.x == 0.28            # the author's, exactly
    history.execute(actions_scale([dim], 2))
    assert _readable(document, dim)[0][:2] == ("0.56", 0.04)
    history.undo()
    from core import actions

    history.execute(actions.mirror_entities([dim], (-1, 0), (-1, 1),
                                            keep_source=True))
    copy = list(msp.query("DIMENSION"))[-1]
    assert bbox.extents([copy]).center.x < -1.0
    assert _readable(document, copy)[0][0] == "0.28"


def actions_rotate(entities, angle):
    from core import actions

    return actions.rotate_entities(entities, (0, 0), angle)


def actions_scale(entities, factor):
    from core import actions

    return actions.scale_entities(entities, (0, 0), factor)
