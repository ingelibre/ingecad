# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Selecting and editing a hatch.

Marco, dogfooding: "apliqué hatch a un dibujo, bien, sólo que quiero
editarlo o eliminarlo, traté de seleccionar con el mouse y no se selecciona;
en AutoCAD selecciono un área pequeña donde está el hatch, se selecciona y
elimino. ¿Ahora cómo edito?"

Two answers, both from the reference: a hatch is picked by clicking on it,
and HATCHEDIT (p. 896) "modifies an existing hatch or fill" -- reached from
Modify > Object > Hatch, the shortcut menu, or a double-click on the hatch.
"""
from __future__ import annotations

import ezdxf
import pytest

from core import actions
from core.document import Document
from core.select import GeometryIndex

#: An L: the corner of its bounding box is NOT part of the hatch.
L_SHAPE = [(0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)]


def _document(pattern: str = "ANSI31"):
    doc = ezdxf.new("R2018", setup=True)
    msp = doc.modelspace()
    hatch = msp.add_hatch(color=2)
    hatch.paths.add_polyline_path(L_SHAPE, is_closed=True)
    if pattern == "SOLID":
        hatch.set_solid_fill(color=2)
    else:
        hatch.set_pattern_fill(pattern, scale=0.5)
    return Document(doc), hatch


def _picked(index, x, y, tolerance=0.2):
    handle = index.pick((x, y), tolerance)
    entity = index.entity(handle) if handle else None
    return entity.dxftype() if entity is not None else None


# -- picking -------------------------------------------------------------------

def test_a_click_inside_a_hatch_selects_it():
    document, _hatch = _document()
    index = GeometryIndex(document)
    assert _picked(index, 2, 2) == "HATCH", "the fill did not answer the click"
    assert _picked(index, 0.02, 5) == "HATCH", "nor did its own edge"


def test_the_hatch_answers_for_its_shape_not_its_bounding_box():
    """The reason this is a polygon test and not a rectangle: the corner of
    an L-shaped hatch's box is empty paper."""
    document, _hatch = _document()
    index = GeometryIndex(document)
    assert _picked(index, 8, 8) is None
    assert _picked(index, 50, 50) is None


def test_a_hole_in_a_hatch_is_not_part_of_it():
    document, hatch = _document()
    hatch.paths.add_polyline_path([(1, 1), (3, 1), (3, 3), (1, 3)],
                                  is_closed=True)
    index = GeometryIndex(document)
    assert _picked(index, 2, 2) is None, "a click in the island selected it"
    assert _picked(index, 6, 2) == "HATCH"


def test_anything_drawn_over_a_hatch_still_wins_the_click():
    """The fill is the LAST candidate, so it never steals a line's click --
    which is what made it safe to answer clicks at all."""
    document, _hatch = _document()
    document.doc.modelspace().add_line((0, 2), (10, 2))
    index = GeometryIndex(document)
    assert _picked(index, 5, 2) == "LINE"
    # ... and cycling still reaches the hatch underneath
    kinds = [index.entity(h).dxftype() for h in index.pick_all((5, 2), 0.2)]
    assert kinds[0] == "LINE" and "HATCH" in kinds, kinds


def test_an_erased_hatch_stops_answering_clicks():
    document, hatch = _document()
    index = GeometryIndex(document)
    assert _picked(index, 2, 2) == "HATCH"
    handle = hatch.dxf.handle
    document.doc.modelspace().delete_entity(hatch)
    index.remove_handles([handle])
    assert _picked(index, 2, 2) is None


# -- editing -------------------------------------------------------------------

def test_the_settings_of_an_existing_hatch_are_what_the_dialog_shows():
    _doc, hatch = _document("ANSI31")
    hatch.set_pattern_fill("ANSI31", scale=0.5, angle=15.0)
    assert actions.hatch_settings(hatch) == {
        "pattern": "ANSI31", "angle": 15.0, "scale": 0.5,
        "color": hatch.dxf.color}

    _doc2, solid = _document("SOLID")
    assert actions.hatch_settings(solid)["pattern"] == "SOLID"


def test_editing_a_hatch_keeps_its_boundary_its_handle_and_its_island_style():
    """That is what makes it an EDIT of that hatch and not a new one."""
    document, hatch = _document()
    hatch.dxf.hatch_style = 1              # Outer
    handle = hatch.dxf.handle
    paths_before = len(hatch.paths)

    actions.apply_hatch_settings(hatch, {"pattern": "EARTH", "scale": 2.0,
                                         "angle": 45.0, "color": 256})
    assert hatch.dxf.handle == handle
    assert len(hatch.paths) == paths_before
    assert hatch.dxf.hatch_style == 1, "the island style was reset"
    assert hatch.dxf.color == 256, "ByLayer turned into a real colour"
    assert actions.hatch_settings(hatch) == {
        "pattern": "EARTH", "angle": 45.0, "scale": 2.0, "color": 256}


def test_an_edit_can_be_undone_exactly():
    document, hatch = _document()
    before = actions.hatch_settings(hatch)
    snapshot = actions.SnapshotCommand([hatch])
    actions.apply_hatch_settings(hatch, {"pattern": "SOLID", "color": 1})
    snapshot.commit(document)
    assert actions.hatch_settings(hatch)["pattern"] == "SOLID"

    snapshot.undo(document)
    assert actions.hatch_settings(hatch) == before


# -- through the window --------------------------------------------------------

def _window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.resize(800, 600)
    win.show()
    win.new_document()
    # through the app's own path: adding to the modelspace behind the
    # controller's back leaves the pick index without it (a fixture trap
    # this suite has fallen into before).
    command = actions.add_hatch([L_SHAPE], pattern="ANSI31", scale=0.5,
                                color=2)
    win.tools._execute(command)
    qapp.processEvents()
    return win, command.entity


def test_a_double_click_on_a_hatch_opens_the_editor(qapp):
    win, hatch = _window(qapp)
    try:
        opened = []
        win.tools.edit_hatch = lambda e: (opened.append(e), True)[1]
        win.tools._pick_tolerance = 0.2
        win.on_canvas_double_click(2.0, 2.0)
        assert opened and opened[0] is hatch, "the double-click did not reach it"
    finally:
        win.close()


def test_hatchedit_edits_the_hatch_already_selected(qapp):
    win, hatch = _window(qapp)
    try:
        edited = []
        win.tools.edit_hatch = lambda e: (edited.append(e), True)[1]
        win.tools._pick_tolerance = 0.2
        win.tools.on_click(2.0, 2.0)                 # select it, as a user does
        assert win.tools.selection, "the hatch did not select"
        win.tools.start_tool("HATCHEDIT")
        assert edited and edited[0] is hatch
        assert not win.tools.active(), "the tool stayed running"
    finally:
        win.close()


# -- the pattern palette -------------------------------------------------------

def _swatch_ink(name: str) -> float:
    """Fraction of the swatch the pattern inks."""
    from views.hatch_dialog import _pattern_pixmap

    image = _pattern_pixmap(name).toImage()
    dark = sum(1 for x in range(image.width()) for y in range(image.height())
               if image.pixelColor(x, y).lightness() < 128)
    return dark / float(image.width() * image.height())


def test_every_swatch_is_a_pattern_and_not_a_blob(qapp):
    """GRAVEL is 41 line families whose spacings run 25 to 508 units.
    Scaling the tile to the widest one squeezed the other forty on top of
    each other and drew a solid black square -- which is a preview that
    tells the user nothing about the pattern he is choosing."""
    for name in ("ANSI31", "ANSI37", "BRICK", "DOTS", "GRAVEL", "AR-CONC",
                 "EARTH", "HONEY"):
        ink = _swatch_ink(name)
        # DOTS really is 0.7% of the tile -- it is dots; the bound that
        # matters is the upper one, which GRAVEL used to blow through at
        # 100%.
        assert 0.003 < ink < 0.75, f"{name} inks {ink:.1%} of its swatch"
    assert _swatch_ink("SOLID") > 0.75, "SOLID is the one that fills the tile"


def test_two_different_patterns_draw_two_different_swatches(qapp):
    """The gallery used to draw a fan of lines from the angle alone, so
    patterns that share an angle looked identical."""
    from views.hatch_dialog import _pattern_pixmap

    def pixels(name):
        image = _pattern_pixmap(name).toImage()
        return bytes(image.constBits())

    shots = {n: pixels(n) for n in ("ANSI31", "ANSI32", "ANSI37", "BRICK",
                                    "NET", "DOTS")}
    assert len(set(shots.values())) == len(shots), (
        "two patterns drew the same swatch")


def test_every_predefined_pattern_has_its_definition():
    """Ten of the 172 names carry a lowercase letter (V_MASONRY200x100).
    Looking them up as name.upper() found nothing, so their hatches were
    created WITHOUT a definition -- and their swatches all drew the
    "unknown pattern" diagonal, six identical cells in the palette."""
    names = actions.hatch_pattern_names()
    assert len(names) > 150, names[:5]
    missing = [n for n in names
               if n != "SOLID" and not actions.pattern_definition(n)]
    assert not missing, missing[:8]
    # the lookup is case-insensitive both ways, and answers with the
    # library's own spelling
    assert actions.pattern_definition("v_masonry200x100")
    assert actions.canonical_pattern_name("V_MASONRY200X100") == \
        "V_MASONRY200x100"


def test_a_hatch_of_a_lowercase_named_pattern_carries_its_definition():
    document, hatch = _document()
    actions.apply_hatch_settings(hatch, {"pattern": "V_MASONRY200x100",
                                         "scale": 1.0, "angle": 0.0,
                                         "color": 256})
    assert hatch.dxf.pattern_name == "V_MASONRY200x100"
    assert len(hatch.pattern.lines) == 2, "the pattern went in without lines"
