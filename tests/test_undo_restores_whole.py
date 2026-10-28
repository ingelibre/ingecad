# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Undo gives back the whole object, not only its DXF attributes.

A randomized sweep of modify commands over 41 real plans, with a
fingerprint before and after each undo, found what the snapshot (an ezdxf
copy) left out: a dimension's block -- it drew nothing after the undo of
a STRETCH or a property edit --, a POLYLINE's vertices, an INSERT's
attributes, a hatch's pattern lines; and the *D blocks of copied
dimensions that an undo left for Save to write.
"""
from __future__ import annotations

from core import actions, modify
from core.commands import History
from core.document import Document


def _dim(document, y=0.0):
    return document.modelspace().add_linear_dim(
        base=(0, y + 2), p1=(0, y), p2=(10, y)).render().dimension


def _block_texts(document, dim):
    name = dim.dxf.get("geometry", None)
    assert name and name in document.doc.blocks, "the dimension lost its block"
    return [e.text for e in document.doc.blocks.get(name)
            if e.dxftype() == "MTEXT"]


def _dim_blocks(document):
    return {b.name for b in document.doc.blocks if b.name.startswith("*D")}


def test_a_dimension_keeps_its_block_through_stretch_and_property_undo():
    document = Document.new()
    history = History(document)
    dim = _dim(document)
    history.execute(modify.stretch_entities(
        [dim], [(-100, -100, 100, 100)], 5, 0))
    history.undo()
    assert _block_texts(document, dim)
    other = _dim(document, 10)

    def mutate():
        other.dxf.text = "X"
        actions.rerender_dimension(document, other)

    actions.apply_in_place(history, [other], mutate)
    history.undo()
    assert _block_texts(document, other)
    history.redo()
    assert _block_texts(document, other) == ["X"]


def test_a_grip_undo_gives_back_the_authors_own_block():
    """A no-op grip and its undo turned the author's "0.50" into ezdxf's
    "0.5" on every dimension of a colleague's plan."""
    document = Document.new()
    history = History(document)
    dim = _dim(document)
    for e in document.doc.blocks.get(dim.dxf.geometry):
        if e.dxftype() == "MTEXT":
            e.text = "AUTHOR"                  # what the author's CAD drew
    p = dim.dxf.defpoint
    history.execute(actions.DimGripCommand(dim, "defpoint", (p.x, p.y + 3)))
    assert _block_texts(document, dim) != ["AUTHOR"]
    history.undo()
    assert _block_texts(document, dim) == ["AUTHOR"]
    assert dim.dxf.defpoint.y == p.y


def test_polyline_vertices_and_insert_attributes_come_back():
    document = Document.new()
    history = History(document)
    msp = document.modelspace()
    poly = msp.add_polyline2d([(0, 0), (10, 0), (10, 5)])
    history.execute(actions.mirror_entities([poly], (0, 0), (1, 0)))
    history.undo()
    assert [tuple(v.dxf.location)[:2] for v in poly.vertices] \
        == [(0, 0), (10, 0), (10, 5)]
    block = document.doc.blocks.new("TAG")
    block.add_attdef("T", (0, 1))
    insert = msp.add_blockref("TAG", (0, 0))
    insert.add_auto_attribs({"T": "A"})
    history.execute(modify.stretch_entities(
        [insert], [(-1, -1, 1, 1)], 5, 0))
    history.undo()
    assert tuple(insert.attribs[0].dxf.insert)[:2] == (0, 1)


def test_undoing_a_copy_leaves_no_dimension_block_behind():
    document = Document.new()
    history = History(document)
    dim = _dim(document)
    before = _dim_blocks(document)
    history.execute(actions.copy_entities([dim], 50, 50))
    assert len(_dim_blocks(document)) > len(before)
    history.undo()
    assert _dim_blocks(document) == before


def test_explode_shows_the_attribute_definitions():
    """"Exploding a block that contains attributes deletes the attribute
    values and redisplays the attribute definitions" (EXPLODE); the tags
    vanished with the values."""
    document = Document.new()
    msp = document.modelspace()
    block = document.doc.blocks.new("TAG", base_point=(1, 0))
    block.add_line((0, 0), (1, 0))
    block.add_attdef("NUM", (0, 1), dxfattribs={"height": 0.5})
    insert = msp.add_blockref("TAG", (5, 5), dxfattribs={"rotation": 90})
    insert.add_auto_attribs({"NUM": "42"})
    history = History(document)
    history.execute(actions.explode_entities([insert]))
    attdefs = [e for e in msp if e.dxftype() == "ATTDEF"]
    assert [a.dxf.tag for a in attdefs] == ["NUM"]
    assert tuple(round(v, 9) for v in attdefs[0].dxf.insert)[:2] == (4, 4)
    assert not [e for e in msp if e.dxftype() == "ATTRIB"]
    history.undo()
    assert [e.dxftype() for e in msp] == ["INSERT"]


def test_a_clipped_viewport_takes_its_boundary_along():
    document = Document.new()
    sheet = document.doc.layouts.get("Layout1")
    boundary = sheet.add_lwpolyline([(10, 10), (60, 10), (60, 40), (10, 40)],
                                    close=True)
    vp = sheet.add_viewport(center=(35, 25), size=(50, 30),
                            view_center_point=(0, 0), view_height=30)
    vp.dxf.clipping_boundary_handle = boundary.dxf.handle
    vp.dxf.flags = vp.dxf.flags | 0x10000
    assert vp.has_extended_clipping_path
    history = History(document)
    history.execute(actions.move_entities([vp], 100, 0))
    assert boundary.get_points("xy")[0] == (110, 10)
    history.undo()
    assert boundary.get_points("xy")[0] == (10, 10)


def test_mirror_keeps_a_hatch_pattern_direction():
    """MIRRHATCH 0, the initial value: "Retains hatch pattern direction".
    About an oblique axis the pattern turned by twice the axis angle."""
    document = Document.new()
    hatch = document.modelspace().add_hatch()
    hatch.set_pattern_fill("ANSI31", scale=1.0)
    hatch.paths.add_polyline_path([(0, 0), (4, 0), (4, 4), (0, 4)],
                                  is_closed=True)
    history = History(document)
    for keep in (False, True):
        history.execute(actions.mirror_entities(
            [hatch], (0, 0), (1, 2), keep_source=keep))
    for h in document.modelspace().query("HATCH"):
        assert [round(line.angle, 9) for line in h.pattern.lines] == [45.0]
