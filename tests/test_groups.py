# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""GROUP (p. 861) end to end.

Marco asked to "afinar" groups for 0.4.2 because he was not sure they were
right. They had no tests at all, and the audit against the Object Grouping
dialog page found three real gaps, each pinned below:

* the Selectable flag lived in a Python set on the Document, so it was lost
  on save -- the round-trip invariant says a flag AutoCAD keeps in the file
  must go back to the file (DXF group code 71);
* there was no way to add or remove members ("Change Group", p.863);
* PICKSTYLE was implemented but unreachable, so once a group existed, one
  of its members could never be selected on its own again.
"""
import io

import pytest

from core import groups as group_ops
from core.commands import History
from core.document import Document


@pytest.fixture
def doc():
    return Document.new()


def _three(doc):
    msp = doc.modelspace()
    return (msp.add_line((0, 0), (10, 0)),
            msp.add_line((10, 0), (10, 10)),
            msp.add_circle((5, 5), 2))


def _grouped(doc, name="MURO"):
    a, b, c = _three(doc)
    History(doc).execute(group_ops.CreateGroupCommand(name, [a, b]))
    return a, b, c


# -- the behaviour that makes GROUP worth having -------------------------------
def test_picking_one_member_takes_the_whole_group(doc):
    a, b, c = _grouped(doc)
    grown = group_ops.expand(doc, {a.dxf.handle})
    assert grown == {a.dxf.handle, b.dxf.handle}
    assert group_ops.expand(doc, {c.dxf.handle}) == {c.dxf.handle}


def test_an_unselectable_group_does_not_grow_a_pick(doc):
    a, b, _c = _grouped(doc)
    group_ops.set_selectable(doc, "MURO", False)
    assert group_ops.expand(doc, {a.dxf.handle}) == {a.dxf.handle}
    group_ops.set_selectable(doc, "MURO", True)
    assert group_ops.expand(doc, {a.dxf.handle}) == {a.dxf.handle, b.dxf.handle}


def test_pickstyle_0_turns_group_selection_off_wholesale(doc):
    a, b, _c = _grouped(doc)
    group_ops.set_pickstyle(doc, 0)
    assert group_ops.expand(doc, {a.dxf.handle}) == {a.dxf.handle}
    group_ops.set_pickstyle(doc, 1)
    assert group_ops.expand(doc, {a.dxf.handle}) == {a.dxf.handle, b.dxf.handle}


# -- the flag has to reach the file (the gap this suite was written for) -------
def test_selectable_survives_a_save_and_reload(doc):
    """Was broken: the flag lived in ``document._unselectable_groups``.

    AutoCAD keeps it in the GROUP object (code 71), so a colleague opening
    the drawing must see the same thing the author set.
    """
    _grouped(doc)
    group_ops.set_selectable(doc, "MURO", False)

    stream = io.StringIO()
    doc.doc.write(stream)
    stream.seek(0)
    import ezdxf

    reloaded = Document(ezdxf.read(stream))
    assert group_ops.is_selectable(reloaded, "MURO") is False, \
        "the Selectable flag did not reach the file"
    group_ops.set_selectable(reloaded, "MURO", True)
    assert group_ops.is_selectable(reloaded, "MURO") is True


def test_the_description_reaches_the_file_too(doc):
    _grouped(doc)
    group_ops.set_description(doc, "MURO", "muro perimetral norte")
    stream = io.StringIO()
    doc.doc.write(stream)
    stream.seek(0)
    import ezdxf

    reloaded = Document(ezdxf.read(stream))
    assert group_ops.description(reloaded, "MURO") == "muro perimetral norte"


def test_a_description_is_capped_at_64_characters(doc):
    """"You can use up to 64 characters for a description name" (p.863)."""
    _grouped(doc)
    group_ops.set_description(doc, "MURO", "x" * 200)
    assert len(group_ops.description(doc, "MURO")) == 64


# -- Change Group: Add and Remove (p.863-864) ----------------------------------
def test_add_and_remove_members_with_exact_undo(doc):
    a, b, c = _grouped(doc)
    history = History(doc)

    history.execute(group_ops.ChangeGroupMembersCommand("MURO", [c], add=True))
    assert {e.dxf.handle for e in group_ops.members(doc, "MURO")} == \
        {a.dxf.handle, b.dxf.handle, c.dxf.handle}
    history.undo()
    assert {e.dxf.handle for e in group_ops.members(doc, "MURO")} == \
        {a.dxf.handle, b.dxf.handle}

    history.execute(group_ops.ChangeGroupMembersCommand("MURO", [b], add=False))
    assert {e.dxf.handle for e in group_ops.members(doc, "MURO")} == \
        {a.dxf.handle}
    history.undo()
    assert {e.dxf.handle for e in group_ops.members(doc, "MURO")} == \
        {a.dxf.handle, b.dxf.handle}


def test_adding_a_member_twice_does_not_duplicate_it(doc):
    a, b, _c = _grouped(doc)
    History(doc).execute(
        group_ops.ChangeGroupMembersCommand("MURO", [a], add=True))
    assert len(group_ops.members(doc, "MURO")) == 2


def test_removing_every_member_keeps_the_group_defined(doc):
    """"If you remove all the group's objects, the group remains defined"."""
    a, b, _c = _grouped(doc)
    History(doc).execute(
        group_ops.ChangeGroupMembersCommand("MURO", [a, b], add=False))
    assert group_ops.members(doc, "MURO") == []
    assert [n for n, _g in group_ops.all_groups(doc)] == ["MURO"]


def test_removed_objects_stay_in_the_drawing(doc):
    a, b, _c = _grouped(doc)
    History(doc).execute(
        group_ops.ChangeGroupMembersCommand("MURO", [a], add=False))
    assert a.is_alive and a in list(doc.modelspace())


# -- Find Name (p.863) ---------------------------------------------------------
def test_find_name_lists_every_group_an_object_belongs_to(doc):
    a, b, c = _three(doc)
    history = History(doc)
    history.execute(group_ops.CreateGroupCommand("MURO", [a, b]))
    history.execute(group_ops.CreateGroupCommand("PLANTA", [a, c]))
    assert sorted(group_ops.groups_of(doc, a)) == ["MURO", "PLANTA"]
    assert group_ops.groups_of(doc, b) == ["MURO"]


# -- names (p.862) -------------------------------------------------------------
@pytest.mark.parametrize("name,ok", [
    ("MURO", True), ("EJE-1", True), ("A_$1", True), ("con espacio", False),
    ("", False), ("x" * 32, False), ("x" * 31, True)])
def test_group_names_follow_the_reference(name, ok):
    assert group_ops.valid_name(name) is ok


def test_a_name_is_stored_uppercase(doc):
    a, b, _c = _three(doc)
    History(doc).execute(group_ops.CreateGroupCommand("muro", [a, b]))
    assert [n for n, _g in group_ops.all_groups(doc)] == ["MURO"]


def test_ungroup_leaves_the_objects_and_undo_brings_the_group_back(doc):
    a, b, _c = _grouped(doc)
    history = History(doc)
    history.execute(group_ops.DeleteGroupCommand("MURO"))
    assert group_ops.all_groups(doc) == []
    assert a.is_alive and b.is_alive
    history.undo()
    assert {e.dxf.handle for e in group_ops.members(doc, "MURO")} == \
        {a.dxf.handle, b.dxf.handle}


# -- the dialog (p.861-864) ----------------------------------------------------
def _dialog(qapp):
    """A MainWindow with three objects, two of them grouped, and the
    Object Grouping dialog open on that group."""
    from views.group_dialog import ObjectGroupingDialog
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document("mm")
    msp = win.document.modelspace()
    a = msp.add_line((0, 0), (10, 0))
    b = msp.add_line((10, 0), (10, 10))
    c = msp.add_circle((5, 5), 2)
    win.tools._invalidate_geometry()
    win.tools.selection = {a.dxf.handle, b.dxf.handle}
    dialog = ObjectGroupingDialog(win)
    dialog.name.setText("MURO")
    dialog.create()
    return win, dialog, a, b, c


def test_the_dialog_keeps_the_selected_row_across_a_refresh(qapp):
    """Found by driving the dialog, not by reading it.

    Every action ends in ``refresh()``, which rebuilt the list and left
    NOTHING selected -- so the next Add/Remove/Selectable silently did
    nothing at all, because ``_current_name()`` was None. Two consecutive
    actions on one group is the ordinary case, so the feature was broken
    for anyone who used it twice.
    """
    win, dialog, a, b, c = _dialog(qapp)
    try:
        assert dialog._current_name() == "MURO"
        dialog.refresh()
        assert dialog._current_name() == "MURO"

        win.tools.selection = {c.dxf.handle}
        dialog.add_objects()
        assert dialog._current_name() == "MURO", "the row was lost by Add"
        assert len(group_ops.members(win.document, "MURO")) == 3

        win.tools.selection = {c.dxf.handle}
        dialog.remove_objects()
        assert len(group_ops.members(win.document, "MURO")) == 2, \
            "Remove ran against no group"
    finally:
        win.close()


def test_the_selectable_switch_reaches_the_group(qapp):
    win, dialog, _a, _b, _c = _dialog(qapp)
    try:
        dialog.selectable.setChecked(False)
        assert group_ops.is_selectable(win.document, "MURO") is False
        dialog.selectable.setChecked(True)
        assert group_ops.is_selectable(win.document, "MURO") is True
    finally:
        win.close()


def test_the_pickstyle_command_toggles_and_takes_a_value(qapp):
    win, _dlg, _a, _b, _c = _dialog(qapp)
    try:
        assert group_ops.pickstyle(win.document) == 1
        win._cmd_pickstyle()                 # bare: toggles
        assert group_ops.pickstyle(win.document) == 0
        win._cmd_pickstyle()
        assert group_ops.pickstyle(win.document) == 1
        win._cmd_pickstyle("0")              # explicit
        assert group_ops.pickstyle(win.document) == 0
        win._cmd_pickstyle("nonsense")       # refused, value unchanged
        assert group_ops.pickstyle(win.document) == 0
    finally:
        win.close()
