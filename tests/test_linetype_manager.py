# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Linetype Manager's model (LINETYPE, reference pp. 1043-1046).

Everything the manager does, headless: load from a LIN file (simple and
complex definitions), reload an already loaded linetype, rename one with
every reference, delete only the unused ones, and the current object
scale (CELTSCALE) given to new objects. PSLTSCALE has its own file.
"""
from __future__ import annotations

import ezdxf
import pytest

from core import linetypes as lt_ops
from core.document import Document

LIN = """;;
;; a piece of acadiso.lin, with a complex line and a continued pattern
;;
*ACAD_ISO02W100,ISO dash __ __ __ __ __ __ __ __ __ __ __ __ __
A,12,-3
*GAS_LINE,Gas line ----GAS----GAS----GAS----GAS----GAS----GAS--
A,12.7,-5.08,["GAS",STANDARD,S=2.54,R=0.0,X=-2.54,Y=-1.27],-6.35
*LONG,A long one split over two lines
A,10,-2,
0,-2
"""


def _document() -> Document:
    doc = ezdxf.new("R2018", setup=False)
    return Document(doc)


# -- LIN files -------------------------------------------------------------------

def test_a_lin_file_reads_simple_complex_and_continued_definitions():
    entries = lt_ops.parse_lin(LIN)
    assert entries["ACAD_ISO02W100"] == (
        "ISO dash __ __ __ __ __ __ __ __ __ __ __ __ __", [12.0, -3.0])
    assert entries["LONG"][1] == [10.0, -2.0, 0.0, -2.0]
    description, pattern = entries["GAS_LINE"]
    assert isinstance(pattern, str) and pattern.startswith("A,12.7,-5.08,[")


def test_a_lin_file_loads_into_the_drawing_and_saves(tmp_path):
    document = _document()
    catalog = lt_ops.parse_lin(LIN)
    command = lt_ops.LoadLinetypesCommand(["GAS_LINE", "LONG"], catalog=catalog)
    command.do(document)
    assert {"GAS_LINE", "LONG"} <= set(lt_ops.loaded_names(document))
    assert lt_ops.pattern_of(document, "LONG") == [10.0, -2.0, 0.0, -2.0]
    document.doc.saveas(tmp_path / "lin.dxf")
    again = ezdxf.readfile(tmp_path / "lin.dxf")
    assert again.linetypes.has_entry("GAS_LINE")
    command.undo(document)
    assert "LONG" not in lt_ops.loaded_names(document)


def test_reload_redefines_in_place_and_undo_puts_it_back():
    """'Linetype X is already loaded. Reload it?' -- Yes keeps the entry,
    so the objects that use it follow the new definition."""
    document = _document()
    lt_ops.LoadLinetypesCommand(["LONG"], catalog=lt_ops.parse_lin(LIN)).do(document)
    handle = document.doc.linetypes.get("LONG").dxf.handle
    newer = {"LONG": ("Longer", [20.0, -5.0])}
    skipped = lt_ops.LoadLinetypesCommand(["LONG"], catalog=newer)
    skipped.do(document)
    assert lt_ops.pattern_of(document, "LONG") == [10.0, -2.0, 0.0, -2.0], (
        "reloaded without being asked to")
    reload = lt_ops.LoadLinetypesCommand(["LONG"], catalog=newer, reload=["LONG"])
    reload.do(document)
    assert lt_ops.pattern_of(document, "LONG") == [20.0, -5.0]
    assert lt_ops.description_of(document, "LONG") == "Longer"
    assert document.doc.linetypes.get("LONG").dxf.handle == handle
    reload.undo(document)
    assert lt_ops.pattern_of(document, "LONG") == [10.0, -2.0, 0.0, -2.0]


# -- rename, delete, description --------------------------------------------------

def test_rename_follows_every_reference_and_undoes():
    document = _document()
    doc = document.doc
    lt_ops.LoadLinetypesCommand(["DASHED"]).do(document)
    line = doc.modelspace().add_line((0, 0), (1, 0), dxfattribs={"linetype": "DASHED"})
    block = doc.blocks.new("B")
    inner = block.add_line((0, 0), (1, 0), dxfattribs={"linetype": "dashed"})
    layer = doc.layers.add("Ejes", linetype="DASHED")
    doc.header["$CELTYPE"] = "DASHED"
    command = lt_ops.RenameLinetypeCommand("DASHED", "TRAZOS")
    command.do(document)
    assert doc.linetypes.has_entry("TRAZOS") and not doc.linetypes.has_entry("DASHED")
    assert line.dxf.linetype == inner.dxf.linetype == layer.dxf.linetype == "TRAZOS"
    assert doc.header["$CELTYPE"] == "TRAZOS"
    command.undo(document)
    assert doc.linetypes.has_entry("DASHED") and not doc.linetypes.has_entry("TRAZOS")
    assert line.dxf.linetype == layer.dxf.linetype == "DASHED"
    assert inner.dxf.linetype == "dashed", "undo must restore the exact spelling"


@pytest.mark.parametrize("old,new,refused", [
    ("Continuous", "X", True),          # reserved
    ("XREF|DASHED", "X", True),         # xref-dependent
    ("DASHED", "CENTER", True),         # taken
    ("DASHED", "a|b", True),            # invalid character
    ("DASHED", "dashed", False),        # a change of case is allowed
])
def test_rename_refusals(old, new, refused):
    document = _document()
    lt_ops.LoadLinetypesCommand(["DASHED", "CENTER"]).do(document)
    reason = lt_ops.RenameLinetypeCommand.check(document, old, new)
    assert (reason is not None) == refused, reason


def test_only_unused_linetypes_may_be_deleted():
    document = _document()
    doc = document.doc
    lt_ops.LoadLinetypesCommand(["DASHED", "CENTER", "HIDDEN", "PHANTOM"]).do(document)
    doc.modelspace().add_line((0, 0), (1, 0), dxfattribs={"linetype": "DASHED"})
    doc.layers.add("Ejes", linetype="CENTER")
    doc.header["$CELTYPE"] = "HIDDEN"
    assert lt_ops.unused_names(document) == ["PHANTOM"]


def test_description_edit_undoes():
    document = _document()
    lt_ops.LoadLinetypesCommand(["DASHED"]).do(document)
    before = lt_ops.description_of(document, "DASHED")
    command = lt_ops.LinetypeDescriptionCommand("DASHED", "Trazos")
    command.do(document)
    assert lt_ops.description_of(document, "DASHED") == "Trazos"
    command.undo(document)
    assert lt_ops.description_of(document, "DASHED") == before


# -- CELTSCALE ---------------------------------------------------------------------

def test_new_objects_take_the_current_object_linetype_scale():
    from core import actions

    document = _document()
    document.doc.header["$CELTSCALE"] = 0.5
    command = actions.add_line((0, 0), (10, 0))
    command.do(document)
    assert command.entity.dxf.ltscale == pytest.approx(0.5)
    document.doc.header["$CELTSCALE"] = 1.0
    other = actions.add_line((0, 1), (10, 1))
    other.do(document)
    assert not other.entity.dxf.hasattr("ltscale"), "1.0 should write nothing"


# -- -LINETYPE -----------------------------------------------------------------------

def _drive(document, answers, files=(), executed=None):
    """Run -LINETYPE answering each prompt in turn; returns (echo, prompts)."""
    lines: list[str] = []
    prompts: list[str] = []
    picks = list(files)

    def execute(command):
        command.do(document)
        if executed is not None:
            executed.append(command)

    prompt = lt_ops.linetype_command(document, execute, lines.append,
                                     lambda caption, save: picks.pop(0))
    for answer in answers:
        assert prompt is not None, f"the command ended before {answer!r}"
        prompts.append(prompt.text)
        prompt = prompt.on_input(answer)
    assert prompt is None or answers[-1] == "", "the command did not end"
    return lines, prompts


def test_dash_linetype_load_with_wildcards_and_reload(tmp_path):
    lin = tmp_path / "mine.lin"
    lin.write_text(LIN, encoding="utf-8")
    document = _document()
    lines, prompts = _drive(document, ["L", "acad_iso*,long", ""], [str(lin)])
    assert prompts[0] == "Enter an option [?/Create/Load/Set]:"
    assert "Enter linetype(s) to load:" in prompts
    assert {"ACAD_ISO02W100", "LONG"} <= set(lt_ops.loaded_names(document))
    assert "Linetype LONG loaded." in lines
    # again: AutoCAD asks before reloading, Enter means Yes
    lin.write_text("*LONG,new\nA,30,-3\n", encoding="utf-8")
    lines, prompts = _drive(document, ["L", "LONG", "", ""], [str(lin)])
    assert any("already loaded" in p for p in prompts)
    assert lt_ops.pattern_of(document, "LONG") == [30.0, -3.0]
    assert "Linetype LONG reloaded." in lines


def test_dash_linetype_set_loads_from_the_library_when_needed():
    document = _document()
    _drive(document, ["S", "DASHED", ""])
    assert document.doc.header["$CELTYPE"] == "DASHED"
    assert "DASHED" in lt_ops.loaded_names(document), (
        "Set did not load a library linetype first")
    _drive(document, ["s", "bylayer", ""])
    assert document.doc.header["$CELTYPE"] == "ByLayer"
    lines, _ = _drive(document, ["S", "NOPE"])
    assert any("not found" in line for line in lines)


def test_dash_linetype_create_writes_a_lin_file_and_load_reads_it(tmp_path):
    target = tmp_path / "custom.lin"
    document = _document()
    lines, prompts = _drive(
        document, ["C", "VALLA", "Valla __ x __", "10,-2,0,-2", ""],
        [str(target)])
    assert "A," in prompts
    assert "New linetype definition saved to file." in lines
    assert lt_ops.read_lin_file(target)["VALLA"] == (
        "Valla __ x __", [10.0, -2.0, 0.0, -2.0])
    # creating it again asks before overwriting; Yes replaces it
    _drive(document, ["C", "VALLA", "Y", "otra", "5,-5", ""], [str(target)])
    entries = lt_ops.read_lin_file(target)
    assert entries["VALLA"] == ("otra", [5.0, -5.0])
    assert target.read_text(encoding="utf-8").count("*VALLA") == 1
    _drive(document, ["L", "VALLA", ""], [str(target)])
    assert lt_ops.pattern_of(document, "VALLA") == [5.0, -5.0]


def test_dash_linetype_question_lists_a_file(tmp_path):
    lin = tmp_path / "mine.lin"
    lin.write_text(LIN, encoding="utf-8")
    lines, _ = _drive(_document(), ["?", ""], [str(lin)])
    assert any(line.startswith("GAS_LINE") for line in lines)


def test_the_standard_library_is_a_lin_file_that_reads_back():
    """-LINETYPE's dialogs propose it, as AutoCAD proposes acad.lin."""
    path = lt_ops.standard_lin_file()
    entries = lt_ops.read_lin_file(path)
    for name, (description, pattern) in lt_ops.library().items():
        if name in lt_ops.RESERVED:
            continue
        assert entries[name][1] == pytest.approx(pattern), name
        assert entries[name][0] == description.rstrip()
