# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Annotative scaling, A2: creating annotative objects (issue #43).

An annotative text style has a PAPER height; a text typed in it is born
annotative at the current annotation scale, its model height the paper
height times the scale's factor, with one (default) representation. An
annotative dimension style locks DIMSCALE to 0 and CANNOSCALE sizes the
dimension. The status-bar control and CANNOSCALE set the scale of the
current view as one undo step; OBJECTSCALE adds and deletes scales.
Everything lands where AutoCAD writes it (core.annotative's writer).
"""
from __future__ import annotations

import ezdxf
import pytest

from core import annotative as A
from core import styles as style_ops
from core.document import Document


def _doc(cannoscale="1:50"):
    doc = ezdxf.new("R2018")
    A.ensure_scale(doc, "1:1", 1.0, 1.0)
    s50 = A.ensure_scale(doc, "1:50", 1.0, 50.0)
    A.ensure_scale(doc, "1:100", 1.0, 100.0)
    if cannoscale:
        A.set_current_scale(doc, A.find_scale(doc, cannoscale))
    return doc, s50


# -- styles --------------------------------------------------------------------

def test_the_style_flag_is_written_as_autocad_does_and_undoes():
    doc, _ = _doc()
    document = Document(doc)
    cmd = style_ops.SetTextStylePropsCommand("Standard", {"annotative": True})
    cmd.do(document)
    style = doc.styles.get("Standard")
    assert style.has_xdata(A.ANNO_APPID) and A.is_annotative(style)
    assert style_ops.text_style_props(document, "Standard")["annotative"]
    cmd.undo(document)
    assert not A.is_annotative(style)


def test_an_unchanged_flag_leaves_the_style_untouched():
    """The editor always sends the box's state; off and still off must not
    write an AcadAnnotative flag 0 onto every style the user edits."""
    doc, _ = _doc()
    document = Document(doc)
    style_ops.SetTextStylePropsCommand(
        "Standard", {"annotative": False, "width": 1.0}).do(document)
    assert not doc.styles.get("Standard").has_xdata(A.ANNO_APPID)


def test_an_annotative_dimension_style_locks_dimscale_to_zero():
    doc, _ = _doc()
    document = Document(doc)
    doc.dimstyles.get("Standard").dxf.dimscale = 2.0
    cmd = style_ops.SetDimStylePropsCommand("Standard", {"annotative": True})
    cmd.do(document)
    d = doc.dimstyles.get("Standard")
    assert A.is_annotative(d) and d.dxf.dimscale == 0.0
    cmd.undo(document)
    assert not A.is_annotative(d) and d.dxf.dimscale == 2.0


# -- creation ------------------------------------------------------------------

def test_a_text_in_an_annotative_style_is_born_at_cannoscale():
    from core import actions

    doc, s50 = _doc("1:50")
    document = Document(doc)
    A.set_style_annotative(doc.styles.get("Standard"), True)
    cmd = actions.add_text((10.0, 20.0), "LOTE 7", 2.5, style="Standard")
    cmd.do(document)
    text = cmd.entity
    assert A.is_annotative(text)
    assert text.dxf.height == pytest.approx(125.0)       # 2.5 mm x 50
    reps = A.representations(text)
    assert [(r.scale.name, r.is_default) for r in reps] == [("1:50", True)]
    before = len(list(doc.objects))
    cmd.undo(document)
    assert len(list(doc.objects)) < before, "the representation was orphaned"

    # the inverse: the same text in a plain style is plain
    A.set_style_annotative(doc.styles.get("Standard"), False)
    plain = actions.add_text((0, 0), "X", 2.5, style="Standard")
    plain.do(document)
    assert not A.is_annotative(plain.entity) and plain.entity.dxf.height == 2.5


def test_an_mtext_scales_its_box_too():
    from core import actions

    doc, _ = _doc("1:100")
    document = Document(doc)
    A.set_style_annotative(doc.styles.get("Standard"), True)
    cmd = actions.add_mtext((0, 10), (2, 0), "A", 2.5, style="Standard")
    cmd.do(document)
    m = cmd.entity
    assert m.dxf.char_height == pytest.approx(250.0)
    assert m.dxf.width == pytest.approx(200.0)
    assert A.representations(m)[0].scale.name == "1:100"


def test_an_annotative_dimension_is_sized_by_cannoscale():
    from core import actions

    doc, _ = _doc("1:50")
    document = Document(doc)
    doc.header["$DIMSTYLE"] = "Standard"
    A.set_style_annotative(doc.dimstyles.get("Standard"), True)
    cmd = actions.dim_linear((0, 0), (1000, 0), (500, 300)) \
        if hasattr(actions, "dim_linear") else None
    if cmd is None:
        pytest.skip("no linear dimension factory")
    cmd.do(document)
    dim = cmd.dim
    assert A.is_annotative(dim)
    reps = A.representations(dim)
    assert [(r.scale.name, r.is_default) for r in reps] == [("1:50", True)]
    assert reps[0].first(2) == dim.dxf.geometry
    cmd.undo(document)
    assert not dim.is_alive


# -- the current scale of the view --------------------------------------------

def test_setting_the_annotation_scale_is_one_undo_step_and_autoscale_adds():
    from core import actions

    doc, _ = _doc("1:50")
    document = Document(doc)
    A.set_style_annotative(doc.styles.get("Standard"), True)
    make = actions.add_text((0, 0), "A", 2.5, style="Standard")
    make.do(document)
    text = make.entity
    cmd = A.SetAnnotationScaleCommand("1:100", autoscale=True)
    cmd.do(document)
    assert A.current_scale(doc).name == "1:100"
    assert {r.scale.name for r in A.representations(text)} == {"1:50", "1:100"}
    cmd.undo(document)
    assert A.current_scale(doc).name == "1:50"
    assert {r.scale.name for r in A.representations(text)} == {"1:50"}
    # ANNOAUTOSCALE off: the objects keep their scales
    A.SetAnnotationScaleCommand("1:100", autoscale=False).do(document)
    assert {r.scale.name for r in A.representations(text)} == {"1:50"}


def test_objectscale_adds_and_deletes_but_never_the_default():
    from core import actions

    doc, _ = _doc("1:50")
    document = Document(doc)
    A.set_style_annotative(doc.styles.get("Standard"), True)
    make = actions.add_text((0, 0), "A", 2.5, style="Standard")
    make.do(document)
    text = make.entity
    add = A.ObjectScaleCommand([text], "1:100", add=True)
    add.do(document)
    assert {r.scale.name for r in A.representations(text)} == {"1:50", "1:100"}
    delete = A.ObjectScaleCommand([text], "1:100", add=False)
    delete.do(document)
    assert {r.scale.name for r in A.representations(text)} == {"1:50"}
    delete.undo(document)
    assert {r.scale.name for r in A.representations(text)} == {"1:50", "1:100"}
    default = A.ObjectScaleCommand([text], "1:50", add=False)
    default.do(document)
    assert default.unchanged == 1
    assert {r.scale.name for r in A.representations(text)} == {"1:50", "1:100"}


def test_the_round_trip_keeps_every_representation(tmp_path):
    from core import actions

    doc, _ = _doc("1:50")
    document = Document(doc)
    A.set_style_annotative(doc.styles.get("Standard"), True)
    make = actions.add_text((0, 0), "A", 2.5, style="Standard")
    make.do(document)
    A.ObjectScaleCommand([make.entity], "1:100", add=True).do(document)
    doc.saveas(tmp_path / "a.dxf")
    back = ezdxf.readfile(tmp_path / "a.dxf")
    text = back.modelspace().query("TEXT")[0]
    assert A.is_annotative(text)
    assert {r.scale.name for r in A.representations(text)} == {"1:50", "1:100"}
    assert A.is_annotative(back.styles.get("Standard"))


# -- through the window --------------------------------------------------------

def _window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    doc = win.document.doc
    for name, drawing in (("1:1", 1.0), ("1:50", 50.0), ("1:100", 100.0)):
        A.ensure_scale(doc, name, 1.0, drawing)
    A.set_current_scale(doc, A.find_scale(doc, "1:50"))
    qapp.processEvents()
    return win


def test_typing_text_in_an_annotative_style_asks_for_the_paper_height(qapp):
    win = _window(qapp)
    t = win.tools
    try:
        doc = win.document.doc
        style = doc.header.get("$TEXTSTYLE", "Standard")
        A.set_style_annotative(doc.styles.get(style), True)
        prompts = []
        win.command_line.set_prompt = (
            lambda text, *a, **k: prompts.append(text)) \
            if hasattr(win.command_line, "set_prompt") else None
        t.start_tool("TEXT")
        t.osnap_on = False
        t.on_click(10.0, 20.0)
        assert "Paper text height" in t.tool._prompt_source \
            or "paper text height" in t.tool._prompt_source
        win._on_command_submitted("2.5")
        win._on_command_submitted("0")
        for ch in "LOTE":
            t.tool.on_char(ch) if hasattr(t.tool, "on_char") else None
        t.tool._buffer = "LOTE"
        t.tool._commit_line()
        t.cancel()
        texts = [e for e in doc.modelspace() if e.dxftype() == "TEXT"]
        assert texts, "no TEXT created"
        text = texts[-1]
        assert A.is_annotative(text)
        assert text.dxf.height == pytest.approx(125.0)
    finally:
        win.document.dirty = False
        win.close()


def test_the_status_bar_control_sets_cannoscale_and_the_regen_follows(qapp):
    from core import actions
    from render.backend import build_scene

    win = _window(qapp)
    try:
        doc = win.document.doc
        style = doc.header.get("$TEXTSTYLE", "Standard")
        A.set_style_annotative(doc.styles.get(style), True)
        win.tools._execute(actions.add_text((0, 0), "A", 2.5))
        text = [e for e in doc.modelspace() if e.dxftype() == "TEXT"][-1]
        A.ObjectScaleCommand([text], "1:100", add=True).do(win.document)

        def height():
            scene = build_scene(win.document, "Model")
            parts = [getattr(scene, b).data["pos"][first:first + count]
                     for b, first, count in scene.handle_ranges.get(text.dxf.handle, [])]
            ys = [float(p[1]) for part in parts for p in part]
            return max(ys) - min(ys)

        at50 = height()
        combo = win._anno_scale_combo
        win._refresh_annotation_controls()
        assert combo.currentData() == "1:50"
        combo.activated.emit(combo.findData("1:100"))
        assert A.current_scale(doc).name == "1:100"
        assert height() == pytest.approx(2 * at50, rel=0.05)
        win._cmd_undo()
        assert A.current_scale(doc).name == "1:50"
        # the command line answers the same question
        win._on_command_submitted("CANNOSCALE")
        win._on_command_submitted("1:100")
        assert A.current_scale(doc).name == "1:100"
        win._on_command_submitted("CANNOSCALE")
        win._on_command_submitted("1:7")          # not in the list: refused
        assert A.current_scale(doc).name == "1:100"
    finally:
        win.document.dirty = False
        win.close()


def test_objectscale_through_the_command_line(qapp):
    from core import actions

    win = _window(qapp)
    t = win.tools
    try:
        doc = win.document.doc
        style = doc.header.get("$TEXTSTYLE", "Standard")
        A.set_style_annotative(doc.styles.get(style), True)
        t._execute(actions.add_text((0, 0), "A", 2.5))
        text = [e for e in doc.modelspace() if e.dxftype() == "TEXT"][-1]
        t.selection = {text.dxf.handle}
        win._on_command_submitted("-OBJECTSCALE")
        win._on_command_submitted("A")
        win._on_command_submitted("1:100")
        assert {r.scale.name for r in A.representations(text)} == {"1:50", "1:100"}
        win._cmd_undo()
        assert {r.scale.name for r in A.representations(text)} == {"1:50"}
    finally:
        win.document.dirty = False
        win.close()


def test_annoallvisible_toggles_per_space_and_undoes(qapp):
    win = _window(qapp)
    try:
        msp = win.document.doc.modelspace()
        assert A.all_visible(msp)
        win._on_command_submitted("ANNOALLVISIBLE")
        win._on_command_submitted("0")
        assert not A.all_visible(msp)
        assert not win._anno_visible_btn.isChecked()
        win._cmd_undo()
        assert A.all_visible(msp)
    finally:
        win.document.dirty = False
        win.close()


def test_the_dimension_style_dialog_offers_annotative(qapp):
    from views.dimstyle_dialog import DimStyleEditorDialog

    dlg = DimStyleEditorDialog(None, "t", {"dimscale": 2.0}, ["Standard"])
    assert not dlg.annotative.isChecked() and dlg.dimscale.isEnabled()
    dlg.annotative.setChecked(True)
    assert not dlg.dimscale.isEnabled()
    props = dlg.result_props()
    assert props["annotative"] is True and props["dimscale"] == 0.0
    dlg.deleteLater()


def test_a_new_drawing_carries_autocads_scale_list():
    # #73 (Rafael): a new drawing's scale list was empty, so 1:1 was the
    # only scale ever offered to dimensions and viewports
    names = {s.name for s in A.scale_list(Document.new().doc)}
    assert {"1:1", "1:2", "1:5", "1:10", "1:50", "1:100", "2:1", "5:1"} <= names


def test_a_drawing_without_a_scale_list_takes_a_standard_scale_on_use(qapp, tmp_path):
    # a DXF from another program has no ACAD_SCALELIST: OBJECTSCALE with
    # 1:5 answered "not in the drawing's scale list"
    from core import actions
    from views.main_window import MainWindow

    bare = ezdxf.new("R2018")
    bare.saveas(tmp_path / "bare.dxf")
    win = MainWindow()
    win.maybe_save_changes = lambda: True
    try:
        win.open_path(tmp_path / "bare.dxf")
        while win._open_thread is not None:
            qapp.processEvents()
        doc = win.document.doc
        assert A.scale_list(doc) == []
        style = doc.header.get("$TEXTSTYLE", "Standard")
        A.set_style_annotative(doc.styles.get(style), True)
        win.tools._execute(actions.add_text((0, 0), "A", 2.5))
        text = [e for e in doc.modelspace() if e.dxftype() == "TEXT"][-1]
        win.tools.selection = {text.dxf.handle}
        win._on_command_submitted("-OBJECTSCALE")
        win._on_command_submitted("A")
        win._on_command_submitted("1:5")
        assert "1:5" in {r.scale.name for r in A.representations(text)}
        assert A.find_scale(doc, "1:5").drawing == pytest.approx(5.0)
    finally:
        win.document.dirty = False
        win.close()


def test_objectscale_is_in_the_modify_menu(qapp):
    # AutoCAD: Modify > Annotative Object Scale > Add/Delete Scales...
    from core.i18n import tr

    win = _window(qapp)
    try:
        # PySide: hold every action and menu in a local while it is used
        bar = win._menu_bar.actions()
        modify_action = next(a for a in bar
                             if a.text().replace("&", "") == tr("Modify"))
        modify = modify_action.menu()
        items = modify.actions()
        anno_action = next(a for a in items if a.text().replace("&", "")
                           == tr("Annotative Object Scale"))
        anno = anno_action.menu()
        entries = [a.text() for a in anno.actions()]
        assert tr("Add/Delete Scales...") in entries
    finally:
        win.close()


def test_existing_dimensions_become_annotative_from_properties(qapp):
    # #73, Rafael (review 6, 44:00-47:00): dimensions drawn first, the
    # styles made annotative after -- the dimensions kept their plain size
    # and OBJECTSCALE said "no annotative objects". AutoCAD's way is the
    # Annotative property; then OBJECTSCALE adds the other scales.
    from core import actions
    from core.i18n import tr

    win = _window(qapp)
    try:
        document = win.document
        doc = document.doc
        A.set_current_scale(doc, A.standard_scale(doc, "1:1"))
        dims = []
        for x in (0, 200):
            cmd = actions.dim_linear((x, 0), (x + 100, 0), (x + 50, 20))
            win.tools._execute(cmd)
            dims.append(cmd.dim)
        style = doc.dimstyles.get(dims[0].dxf.dimstyle)
        A.set_style_annotative(style, True)                 # too late for these two
        assert not any(A.is_annotative(d) for d in dims)
        win.tools.selection = {d.dxf.handle for d in dims}
        panel = win._properties_panel
        panel.refresh()
        tree = panel.tree
        combo = None
        for i in range(tree.topLevelItemCount()):
            section = tree.topLevelItem(i)
            for j in range(section.childCount()):
                if section.child(j).text(0) == tr("Annotative"):
                    combo = tree.itemWidget(section.child(j), 1)
        assert combo is not None, "no Annotative row for dimensions"
        combo.activated.emit(combo.findData(1))
        assert all(A.is_annotative(d) for d in dims)
        assert all([r.scale.name for r in A.representations(d)] == ["1:1"] for d in dims)
        win._on_command_submitted("-OBJECTSCALE")
        win._on_command_submitted("A")
        win._on_command_submitted("2:1")
        assert all({r.scale.name for r in A.representations(d)} == {"1:1", "2:1"}
                   for d in dims)
        win._cmd_undo()                                      # the 2:1
        win._cmd_undo()                                      # the property
        assert not any(A.is_annotative(d) for d in dims)
        assert all(A.representations(d) == [] for d in dims)
    finally:
        win.document.dirty = False
        win.close()


def test_an_annotative_text_style_scales_the_dimension_text():
    # #85, Rafael (2026-10-12): in viewports at other scales the arrows of
    # an annotative dimension scaled and its text did not. The dimension
    # text was in an annotative text style with a (paper) height of 2.5,
    # held at 2.5 in the model at every scale.
    from core import actions

    doc, _ = _doc("1:50")
    document = Document(doc)
    doc.header["$DIMSTYLE"] = "Standard"
    style = doc.styles.add("Anno", font="arial.ttf")
    style.dxf.height = 2.5
    A.set_style_annotative(style, True)
    dimstyle = doc.dimstyles.get("Standard")
    dimstyle.dxf.dimtxsty = "Anno"
    A.set_style_annotative(dimstyle, True)
    cmd = actions.dim_linear((0, 0), (1000, 0), (500, 300))
    cmd.do(document)
    A.ObjectScaleCommand([cmd.dim], "1:100", add=True).do(document)

    heights = {}
    for rep in A.representations(cmd.dim):
        (text,) = doc.blocks.get(rep.first(2)).query("MTEXT")
        heights[rep.scale.name] = text.dxf.char_height
    assert heights == {"1:50": pytest.approx(125.0), "1:100": pytest.approx(250.0)}


def test_a_plain_fixed_height_style_still_sets_the_text_unscaled():
    from core import actions

    doc, _ = _doc("1:50")
    document = Document(doc)
    doc.header["$DIMSTYLE"] = "Standard"
    doc.styles.add("Fixed", font="arial.ttf").dxf.height = 2.5
    dimstyle = doc.dimstyles.get("Standard")
    dimstyle.dxf.dimtxsty = "Fixed"
    dimstyle.dxf.dimscale = 50.0
    cmd = actions.dim_linear((0, 0), (1000, 0), (500, 300))
    cmd.do(document)
    (text,) = cmd.dim.get_geometry_block().query("MTEXT")
    assert text.dxf.char_height == pytest.approx(2.5)
