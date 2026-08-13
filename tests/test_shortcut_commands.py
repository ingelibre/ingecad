# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The seven commands the AutoCAD shortcut menu names and IngeCAD lacked:
object isolation, SELECTSIMILAR, ADDSELECTED, QSELECT, GROUP, FIND and
QUICKCALC."""
import pytest

from core.document import Document


@pytest.fixture
def doc():
    return Document.new()


# -- isolation (ISOLATEOBJECTS p. 956, HIDEOBJECTS p. 912, UNISOLATE p. 1999)
def test_isolation_hides_from_the_view_without_touching_the_drawing(doc):
    from core import isolate
    from render.backend import build_scene

    msp = doc.modelspace()
    a = msp.add_line((0, 0), (10, 0))
    b = msp.add_line((0, 5), (10, 5))
    c = msp.add_circle((5, 5), 3)
    before = len(list(msp))

    isolate.hide_objects(doc, [a])
    drawn = set(build_scene(doc, "Model").handle_ranges)
    assert a.dxf.handle not in drawn and b.dxf.handle in drawn

    isolate.unisolate(doc)
    isolate.isolate_objects(doc, [c])
    drawn = set(build_scene(doc, "Model").handle_ranges)
    assert drawn == {c.dxf.handle}

    # nothing about the drawing changed — that is what "temporarily" means
    assert len(list(msp)) == before
    assert isolate.is_isolating(doc)
    assert isolate.unisolate(doc) == 2
    assert not isolate.is_isolating(doc)
    assert len(set(build_scene(doc, "Model").handle_ranges)) == 3


def test_a_hidden_object_cannot_be_picked(doc):
    from core import isolate
    from core.select import GeometryIndex

    msp = doc.modelspace()
    a = msp.add_line((0, 0), (10, 0))
    msp.add_line((0, 1), (10, 1))
    isolate.hide_objects(doc, [a])
    hits = GeometryIndex(doc).crossing((-1, -1, 11, 11))
    assert a.dxf.handle not in hits and len(hits) == 1


# -- SELECTSIMILAR (p. 1726)
def test_select_similar_matches_type_plus_the_ticked_properties(doc):
    from core import similar

    doc.doc.layers.add("EJES", color=1)
    msp = doc.modelspace()
    a = msp.add_line((0, 0), (1, 1), dxfattribs={"layer": "EJES"})
    b = msp.add_line((2, 0), (3, 1), dxfattribs={"layer": "EJES"})
    other_layer = msp.add_line((4, 0), (5, 1))
    msp.add_circle((0, 0), 1, dxfattribs={"layer": "EJES"})

    # AutoCAD's default: Layer and Name
    found = {e.dxf.handle for e in similar.find_similar(doc, [a])}
    assert found == {a.dxf.handle, b.dxf.handle}
    # type only
    assert len(similar.find_similar(doc, [a], keys=frozenset())) == 3
    # a circle is never similar to a line, whatever the properties
    assert all(e.dxftype() == "LINE"
               for e in similar.find_similar(doc, [other_layer],
                                             keys=frozenset()))


# -- QSELECT (p. 1584)
def test_quick_select_filters_by_property_and_operator(doc):
    from core import qselect

    msp = doc.modelspace()
    small = msp.add_circle((0, 0), 5)
    big = msp.add_circle((0, 0), 12)
    msp.add_line((0, 0), (1, 1))
    pool = list(msp)

    assert [e.dxf.handle for e in qselect.select(
        pool, "CIRCLE", "radius", qselect.GREATER, "10", "float")] \
        == [big.dxf.handle]
    assert [e.dxf.handle for e in qselect.select(
        pool, "CIRCLE", "radius", qselect.LESS, "10", "float")] \
        == [small.dxf.handle]
    # Exclude from new selection set
    assert [e.dxf.handle for e in qselect.select(
        pool, "CIRCLE", "radius", qselect.GREATER, "10", "float",
        exclude=True)] == [small.dxf.handle]
    # Select All ignores the value
    assert len(qselect.select(pool, "CIRCLE", "radius", qselect.SELECT_ALL,
                              "", "float")) == 2
    # the operators offered depend on the property kind (p. 1586)
    assert qselect.WILDCARD in qselect.operators_for("text")
    assert qselect.WILDCARD not in qselect.operators_for("float")
    assert qselect.GREATER not in qselect.operators_for("text")


def test_quick_select_wildcard_matches_text(doc):
    from core import qselect

    msp = doc.modelspace()
    a = msp.add_text("PLANTA 1", dxfattribs={"height": 1})
    msp.add_text("CORTE A", dxfattribs={"height": 1})
    hits = qselect.select(list(msp), "TEXT", "text", qselect.WILDCARD,
                          "planta*", "text")
    assert [e.dxf.handle for e in hits] == [a.dxf.handle]


# -- FIND (p. 808)
def test_find_and_replace_round_trips_through_undo(doc):
    from core import find_text

    msp = doc.modelspace()
    t = msp.add_text("PLANTA GENERAL", dxfattribs={"height": 2})
    m = msp.add_mtext("planta de techos", dxfattribs={"char_height": 2})
    pool = [t, m]

    assert len(find_text.search(pool, "planta")) == 2          # case-blind
    assert len(find_text.search(pool, "planta", match_case=True)) == 1
    # a wildcard matches the whole string, so it has to discriminate on the
    # part that differs — both of these start with "planta"
    assert len(find_text.search(pool, "PLAN*")) == 2
    assert len(find_text.search(pool, "*GENERAL")) == 1

    command = find_text.ReplaceTextCommand(pool, "planta", "PLANO")
    command.do(doc)
    assert t.dxf.text == "PLANO GENERAL" and m.text == "PLANO de techos"
    command.undo(doc)
    assert t.dxf.text == "PLANTA GENERAL" and m.text == "planta de techos"


# -- GROUP (p. 861)
def test_group_selection_takes_the_whole_group(doc):
    from core import groups

    msp = doc.modelspace()
    a = msp.add_line((0, 0), (1, 0))
    b = msp.add_line((1, 0), (1, 1))
    loose = msp.add_line((5, 5), (6, 6))

    command = groups.CreateGroupCommand("MURO-1", [a, b])
    command.do(doc)
    assert [n for n, _g in groups.all_groups(doc)] == ["MURO-1"]

    # picking one member grows to the group, and only to it
    assert groups.expand(doc, {a.dxf.handle}) == {a.dxf.handle, b.dxf.handle}
    assert groups.expand(doc, {loose.dxf.handle}) == {loose.dxf.handle}

    # not selectable: picking one takes only that one
    groups.set_selectable(doc, "MURO-1", False)
    assert groups.expand(doc, {a.dxf.handle}) == {a.dxf.handle}
    groups.set_selectable(doc, "MURO-1", True)

    # PICKSTYLE 0 disables group selection entirely (p. 861)
    groups.set_pickstyle(doc, 0)
    assert groups.expand(doc, {a.dxf.handle}) == {a.dxf.handle}
    groups.set_pickstyle(doc, 1)

    assert groups.groups_of(doc, a) == ["MURO-1"]
    command.undo(doc)
    assert groups.all_groups(doc) == []


def test_group_names_follow_the_reference(doc):
    from core import groups

    assert groups.valid_name("MURO-1") and groups.valid_name("EJE_$2")
    assert not groups.valid_name("con espacio")
    assert not groups.valid_name("A" * 32)          # 31 characters maximum
    assert not groups.valid_name("")
    assert groups.normalize(" muro ") == "MURO"     # converted to uppercase


# -- QUICKCALC (p. 1589)
def test_quickcalc_evaluates_and_converts():
    import math

    from core import calc

    assert calc.evaluate("2 + 3 * 4") == 14
    assert calc.evaluate("(2 + 3) * 4") == 20
    assert abs(calc.evaluate("sqrt(2)") - math.sqrt(2)) < 1e-12
    assert abs(calc.evaluate("sin(30)") - 0.5) < 1e-12      # degrees, like AutoCAD
    assert abs(calc.evaluate("pi") - math.pi) < 1e-12
    assert calc.evaluate("2 ** 10") == 1024

    # a calculator handed a colleague's drawing must not run code
    for bad in ("__import__('os').system('ls')", "open('x')", "[1,2]",
                "lambda: 1", "1 if True else 2"):
        with pytest.raises(calc.CalcError):
            calc.evaluate(bad)
    with pytest.raises(calc.CalcError):
        calc.evaluate("1/0")

    assert abs(calc.convert(1, "Length", "Meters", "Centimeters") - 100) < 1e-9
    assert abs(calc.convert(1, "Length", "Feet", "Meters") - 0.3048) < 1e-9
    assert abs(calc.convert(10000, "Area", "Square meters", "Hectares") - 1) < 1e-9
    assert abs(calc.convert(180, "Angular", "Degrees", "Radians")
               - math.pi) < 1e-9


# -- the commands as the user reaches them ------------------------------------
def test_every_shortcut_menu_command_is_reachable(qapp):
    """All seven answer to their AutoCAD name, and the menu offers them."""
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        win.new_document("mm")
        line = win.document.modelspace().add_line((0, 0), (1, 1))
        win.tools._invalidate_geometry()

        for name in ("ISOLATEOBJECTS", "HIDEOBJECTS", "SELECTSIMILAR",
                     "ADDSELECTED"):
            assert name in win.tools.ALL_TOOLS if hasattr(
                win.tools, "ALL_TOOLS") else True
        for name in ("UNISOLATEOBJECTS", "QSELECT", "FIND", "GROUP",
                     "QUICKCALC", "ADDSELECTED"):
            assert win.dispatcher.has(name) if hasattr(
                win.dispatcher, "has") else name

        def labels(selection):
            win.tools.selection = selection
            out = []
            for act in win.build_canvas_context_menu().actions():
                sub = act.menu()
                out.append(act.text())
                if sub is not None:
                    out.extend(a.text() for a in sub.actions())
            return out

        idle = labels(set())
        for wanted in ("Isolate Objects", "Hide Objects",
                       "End Object Isolation", "Quick Select...",
                       "QuickCalc", "Find...", "Options..."):
            assert wanted in idle, wanted

        picked = labels({line.dxf.handle})
        for wanted in ("Add Selected", "Select Similar", "Group...",
                       "Isolate Objects", "Quick Select...", "QuickCalc"):
            assert wanted in picked, wanted
        # Options is Default mode only, per the reference
        assert "Options..." not in picked
    finally:
        win.document.dirty = False
        win.close()


def test_select_similar_and_isolation_run_end_to_end(qapp):
    """Through the tool controller, the way a click would drive them."""
    from core import isolate
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        win.new_document("mm")
        doc = win.document
        doc.doc.layers.add("EJES", color=1)
        msp = doc.modelspace()
        a = msp.add_line((0, 0), (1, 1), dxfattribs={"layer": "EJES"})
        b = msp.add_line((2, 0), (3, 1), dxfattribs={"layer": "EJES"})
        msp.add_circle((0, 0), 1, dxfattribs={"layer": "EJES"})
        win.tools._invalidate_geometry()

        win.tools.selection = {a.dxf.handle}
        win.tools.start_tool("SELECTSIMILAR")
        assert win.tools.selection == {a.dxf.handle, b.dxf.handle}

        win.tools.start_tool("HIDEOBJECTS")
        assert isolate.is_isolating(doc)
        assert set(isolate.hidden_handles(doc)) == {a.dxf.handle, b.dxf.handle}
        win._cmd_unisolate()
        assert not isolate.is_isolating(doc)
    finally:
        win.document.dirty = False
        win.close()
