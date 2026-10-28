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


@pytest.mark.parametrize("measurement,center", [
    (1, [31.75, -6.35, 6.35, -6.35]),     # acadiso.lin
    (0, [1.25, -0.25, 0.25, -0.25]),      # acad.lin
])
def test_a_metric_drawing_loads_acadiso_values_an_imperial_one_acad(
        measurement, center):
    """AutoCAD picks the library by MEASUREMENT: acadiso.lin for a metric
    drawing, where the classic families are in millimetres (25.4 times
    acad.lin's numbers), acad.lin for an imperial one. The ISO family is the
    same in both. IngeCAD loaded acad.lin's everywhere, so a CENTER line in
    a millimetre plan came out 25 times shorter than AutoCAD's."""
    document = _document()
    document.doc.header["$MEASUREMENT"] = measurement
    lt_ops.LoadLinetypesCommand(["CENTER", "ACAD_ISO02W100"]).do(document)
    assert lt_ops.pattern_of(document, "CENTER") == pytest.approx(center)
    assert lt_ops.pattern_of(document, "ACAD_ISO02W100") == pytest.approx(
        [12.0, -3.0])
    name = "ingecadiso.lin" if measurement else "ingecad.lin"
    assert lt_ops.standard_lin_file(document).name == name


def test_every_library_linetype_loads_with_exactly_its_dashes():
    """What the Load dialog offers is what the drawing gets.

    ezdxf wants ``[total_length, dash, ...]`` and the command used to hand it
    the bare dashes: the first dash was swallowed as the length, so
    ACAD_ISO02W100 [12, -3] loaded as a lone gap and ISO04 as a dotted line.
    A tester saw it as "I pick an ISO linetype and it loads as another one".
    Every entry, not a sample: the classic ones a template preloads would
    hide the bug for the ISO family, which is where it was seen.
    """
    document = _document()
    names = [n for n in lt_ops.library_names() if n != "CONTINUOUS"]
    lt_ops.LoadLinetypesCommand(names).do(document)
    for name in names:
        expected = lt_ops.library(document)[name][1]
        assert lt_ops.pattern_of(document, name) == pytest.approx(expected), name
        entry = document.doc.linetypes.get(name)
        length = [t.value for t in entry.pattern_tags.tags if t.code == 40]
        assert length == pytest.approx([sum(abs(d) for d in expected)]), (
            f"{name}: group 40 is not the pattern length")


def test_a_loaded_iso_linetype_draws_dashes_on_the_canvas():
    """End to end: the bug looked like nothing had loaded, because ezdxf's
    frontend draws a gap-only pattern as a solid line."""
    from render.backend import build_scene

    document = Document.new()
    lt_ops.LoadLinetypesCommand(["ACAD_ISO02W100"]).do(document)
    document.doc.modelspace().add_line(
        (0, 0), (1000, 0), dxfattribs={"linetype": "ACAD_ISO02W100"})
    scene = build_scene(document, "Model")
    # 12 on, 3 off -> 1000 / 15 = 66.7 dashes, two vertices each
    assert len(scene.lines.data) == 134, (
        f"{len(scene.lines.data)} vertices: not the dashes of ISO02")


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


def test_the_load_dialog_offers_the_whole_library_loaded_ones_too(qapp):
    """Load OR RELOAD Linetypes (reference p. 1046): AutoCAD lists every
    definition of the file, the loaded ones too -- picking one of those is a
    reload, which it confirms first. CONTINUOUS is never listed."""
    from views.linetype_dialog import LoadLinetypesDialog

    document = _document()
    lt_ops.LoadLinetypesCommand(["DASHED"]).do(document)
    dialog = LoadLinetypesDialog(None, document)
    try:
        offered = [dialog.table.item(r, 0).text()
                   for r in range(dialog.table.rowCount())]
        assert "CENTER" in offered
        assert "DASHED" in offered, "a loaded linetype cannot be reloaded"
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


# -- the Layers panel's Load button, the way a user reaches it ------------------

@pytest.mark.parametrize("purged_first", [False, True])
def test_load_from_the_layers_panel_loads_and_sets_the_layer(qapp, purged_first):
    """Rafael's seventh review, 23:20: Layers ▸ the layer's linetype ▸ Load...
    ▸ ACAD_ISO04W100 ▸ OK, and nothing was loaded -- before or after PURGE.
    The dialog looked for the undo history through ``parent().window()``;
    its parent, the Layers panel, keeps the main window in an attribute
    called ``window``, which shadows the method, and the TypeError died
    inside the slot. Every click here goes the way the user's did."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton

    from core.cleanup import PurgeCommand
    from core.layers import NewLayerCommand
    from modal import drive_modal
    from views.linetype_dialog import LoadLinetypesDialog, SelectLinetypeDialog
    from views.main_window import MainWindow

    wanted = "ACAD_ISO04W100"
    errors: list[BaseException] = []
    win = MainWindow()
    try:
        win.show()
        win.resize(1200, 800)
        win.new_document()
        qapp.processEvents()
        if purged_first:
            unused = [n for n in lt_ops.loaded_names(win.document)
                      if n.upper() != "CONTINUOUS"]
            win.tools._execute(PurgeCommand({"ltypes": unused}))
        assert wanted not in lt_ops.loaded_names(win.document)
        win.tools._execute(NewLayerCommand("Ejes"))
        panel = win._layers_panel
        panel.refresh()
        qapp.processEvents()
        row = panel._rows.index("Ejes")

        def load_dialog(dialog):
            names = [dialog.table.item(r, 0).text()
                     for r in range(dialog.table.rowCount())]
            dialog.table.selectRow(names.index(wanted))
            dialog.accept()

        def select_dialog(dialog):
            drive_modal(LoadLinetypesDialog, load_dialog, errors)
            load = next(b for b in dialog.findChildren(QPushButton)
                        if b.text().rstrip(".…") in ("Load", "Cargar"))
            load.click()                      # spins the Load dialog's modal
            assert dialog.result_name() == wanted, "loaded but not listed"
            dialog.accept()

        drive_modal(SelectLinetypeDialog, select_dialog, errors)
        table = panel.table
        rect = table.visualItemRect(table.item(row, 6))
        QTest.mouseClick(table.viewport(), Qt.LeftButton, pos=rect.center())
        if errors:
            raise errors[0]

        assert wanted in lt_ops.loaded_names(win.document), "Load loaded nothing"
        layer = win.document.doc.layers.get("Ejes")
        assert layer.dxf.linetype == wanted, "the layer did not take it"
        win._cmd_undo()
        assert layer.dxf.linetype == "Continuous"
        win._cmd_undo()
        assert wanted not in lt_ops.loaded_names(win.document), (
            "the load is not its own undo step")
    finally:
        win.document.dirty = False
        win.close()


def test_a_new_drawing_carries_only_continuous_as_acadiso_dwt():
    """AutoCAD's acadiso.dwt loads no linetype but Continuous; the rest come
    from acadiso.lin when wanted, with its millimetre values. IngeCAD's new
    drawings carried 18 of ezdxf's, with values neither file has."""
    document = Document.new()
    assert lt_ops.loaded_names(document) == ["Continuous"]
