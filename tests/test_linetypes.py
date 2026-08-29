# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Linetypes: the standard library, loading, and the drawn sample.

AutoCAD's model (LINETYPE, reference p. 1043): a drawing can only use the
linetypes loaded INTO it, the standard definitions come from a library file,
and the manager shows each one as Linetype / **Appearance** / Description --
the Appearance being a drawn sample of the dashes.
"""
from __future__ import annotations

import ezdxf
import pytest

from core import linetypes as lt_ops
from core.commands import History
from core.document import Document


def _document() -> Document:
    doc = ezdxf.new("R2018", setup=False)      # only the mandatory linetypes
    doc.modelspace().add_line((0, 0), (10, 0))
    return Document(doc)


# -- the library ---------------------------------------------------------------

def test_the_library_carries_autocads_classic_patterns():
    names = lt_ops.library_names()
    assert names[0] == "CONTINUOUS", "CONTINUOUS comes first, as in the dialog"
    for classic in ("CENTER", "CENTER2", "CENTERX2", "DASHED", "DASHDOT",
                    "DIVIDE", "DOT", "PHANTOM", "HIDDEN", "HIDDENX2"):
        assert classic in names, classic
    # the family rule the descriptions state: X2 is twice, 2 is half
    base = lt_ops.library()["HIDDEN"][1]
    assert lt_ops.library()["HIDDENX2"][1] == pytest.approx(
        [v * 2 for v in base])
    assert lt_ops.library()["HIDDEN2"][1] == pytest.approx(
        [v / 2 for v in base])


def test_loading_a_linetype_is_an_undoable_change_to_the_drawing():
    document = _document()
    history = History()
    history.document = document
    assert "DASHED" in lt_ops.loadable_names(document)

    history.execute(lt_ops.LoadLinetypesCommand(["DASHED", "CENTER"]))
    assert document.doc.linetypes.has_entry("DASHED")
    assert "DASHED" in lt_ops.loaded_names(document)
    assert "DASHED" not in lt_ops.loadable_names(document), (
        "a loaded linetype is not offered again")

    history.undo()
    assert not document.doc.linetypes.has_entry("DASHED")


def test_loading_never_touches_what_the_drawing_already_defines():
    """A drawing's own definition wins: reloading must not overwrite it."""
    document = _document()
    document.doc.linetypes.add("DASHED", pattern=[9.0, 6.0, -3.0],
                               description="el DASHED del colega, en mm")
    lt_ops.LoadLinetypesCommand(["DASHED"]).do(document)
    assert lt_ops.pattern_of(document, "DASHED") == pytest.approx([6.0, -3.0])


def test_the_pattern_comes_from_the_drawing_not_from_the_library():
    document = _document()
    document.doc.linetypes.add("RAYITAS", pattern=[1.5, 1.0, -0.5],
                               description="__ __ __")
    assert lt_ops.pattern_of(document, "RAYITAS") == pytest.approx([1.0, -0.5])
    assert lt_ops.description_of(document, "RAYITAS") == "__ __ __"
    # CONTINUOUS has no dashes: that IS the solid line
    assert lt_ops.pattern_of(document, "Continuous") == []


# -- the drawn sample ----------------------------------------------------------

def _ink(pixmap) -> int:
    image = pixmap.toImage()
    return sum(1 for x in range(image.width()) for y in range(image.height())
               if image.pixelColor(x, y).alpha() > 40)


def test_the_sample_of_a_dashed_line_has_gaps_and_a_solid_one_does_not(qapp):
    """The Appearance column has to SHOW the difference -- that is the whole
    point of it, and a swatch that draws the same line for every linetype
    would pass any test that only checked it drew something."""
    from views.linetype_dialog import pattern_pixmap

    solid = _ink(pattern_pixmap([]))
    dashed = _ink(pattern_pixmap([0.5, -0.25]))
    dotted = _ink(pattern_pixmap([0.0, -0.25]))
    assert solid > 0, "the solid sample drew nothing"
    assert dashed < solid, "the dashed sample has no gaps"
    assert dotted < dashed, "the dotted sample is not sparser than the dashed"


def test_a_double_scale_pattern_draws_longer_dashes(qapp):
    """CENTER and CENTERX2 must not look the same in the list."""
    from views.linetype_dialog import pattern_pixmap

    from PySide6.QtGui import QImage

    def runs(pattern):
        image = pattern_pixmap(pattern).toImage()
        y = image.height() // 2
        lengths, run = [], 0
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > 40:
                run += 1
            elif run:
                lengths.append(run)
                run = 0
        if run:
            lengths.append(run)
        return lengths

    base = runs([0.5, -0.25])
    twice = runs([1.0, -0.5])
    assert base and twice
    assert max(twice) > max(base), (
        f"the 2x sample's dashes are not longer: {twice} vs {base}")


# -- the dialogs ---------------------------------------------------------------

def test_the_select_dialog_lists_what_is_loaded_with_a_sample(qapp):
    from views.linetype_dialog import SelectLinetypeDialog

    document = _document()
    lt_ops.LoadLinetypesCommand(["DASHED", "CENTER"]).do(document)
    dialog = SelectLinetypeDialog(None, document, current="CENTER")
    try:
        names = [dialog.table.item(r, 0).text()
                 for r in range(dialog.table.rowCount())]
        assert names[0] == "Continuous"
        assert "DASHED" in names and "CENTER" in names
        assert dialog.result_name() == "CENTER", "the current one is selected"
        row = names.index("DASHED")
        assert not dialog.table.item(row, 1).icon().isNull(), (
            "no sample drawn for DASHED")
    finally:
        dialog.deleteLater()


def test_the_load_dialog_offers_only_what_is_missing(qapp):
    from views.linetype_dialog import LoadLinetypesDialog

    document = _document()
    lt_ops.LoadLinetypesCommand(["DASHED"]).do(document)
    dialog = LoadLinetypesDialog(None, document)
    try:
        offered = [dialog.table.item(r, 0).text()
                   for r in range(dialog.table.rowCount())]
        assert "CENTER" in offered
        assert "DASHED" not in offered, "an already loaded linetype was offered"
        assert "CONTINUOUS" not in offered

        # The sample has to be the WHOLE pattern. It was not: the library
        # entries once began with the period's total length, the dialog
        # sliced it off, and after that changed the slice ate the first
        # dash -- every ISO row drew a blank line, which no assertion on
        # "an icon exists" would have caught.
        from views.linetype_dialog import pattern_pixmap

        row = offered.index("ACAD_ISO02W100")
        drawn = dialog.table.item(row, 1).icon().pixmap(
            dialog.table.iconSize())
        assert _ink(drawn) == _ink(pattern_pixmap(
            lt_ops.library()["ACAD_ISO02W100"][1])), (
            "the sample is not the linetype's own pattern")
        assert _ink(drawn) > 20, "the ISO sample is blank"
    finally:
        dialog.deleteLater()
