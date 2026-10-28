# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Block attributes (#35): ATTDEF / -ATTDEF, INSERT prompting, EATTEDIT and
the double-click, -ATTEDIT, ATTSYNC, BATTMAN, ATTDISP.

Headless first (Commands and tools with a fake context), then through the
window by the real path (typed text on the command line, double-click).
"""
from __future__ import annotations

import ezdxf
import pytest

from core import attributes as att
from core.commands import History
from core.document import Document
from tools.attributes import (AttDefCliTool, AttDispTool, AttEditCliTool,
                              AttSyncTool)
from tools.base import ToolContext
from tools.blocks import InsertTool


# -- fixtures --------------------------------------------------------------------

class Services:
    def __init__(self, document):
        self.document = document
        self.window = None

    def block_names(self):
        return sorted(b.name for b in self.document.doc.blocks
                      if not b.name.startswith("*"))

    def pick_entity(self, point):
        for e in self.document.modelspace():
            if e.dxftype() == "INSERT":
                ip = e.dxf.insert
                if abs(ip.x - point[0]) < 1.0 and abs(ip.y - point[1]) < 1.0:
                    return e
        return None


class Harness:
    def __init__(self, doc=None):
        self.document = Document(doc or ezdxf.new("R2018", setup=True))
        self.history = History(self.document)
        self.finished = False
        self.prompts: list[str] = []
        self.echoed: list[str] = []
        self.services = Services(self.document)
        self.ctx = ToolContext(
            execute=self.history.execute,
            prompt=self.prompts.append,
            echo=self.echoed.append,
            finish=lambda: setattr(self, "finished", True),
            services=self.services,
            ask_choice=lambda p, items, d="": items[0] if items else None,
        )

    @property
    def msp(self):
        return self.document.modelspace()

    def type(self, tool, text):
        """What the command line does with a typed line."""
        if text == "":
            tool.on_enter()
        elif not tool.on_option(text):
            raise AssertionError(f"{tool.name} refused {text!r} at "
                                 f"{tool._prompt_source!r}")


def _title_block(doc, tag_default=(("SHEET", "A01"), ("TITLE", "PLANTA"))):
    block = doc.blocks.new("TB")
    block.add_lwpolyline([(0, 0), (100, 0), (100, 20), (0, 20)], close=True)
    y = 15.0
    for tag, default in tag_default:
        block.add_attdef(tag, insert=(5, y), text=default,
                         dxfattribs={"prompt": f"Enter {tag.lower()}",
                                     "height": 2.5})
        y -= 5.0
    return block


def _fingerprint(space):
    return [(e.dxftype(), e.dxf.handle,
             tuple(sorted((k, str(v)) for k, v in
                          e.dxf.all_existing_dxf_attribs().items()
                          if k not in ("owner",))))
            for e in space]


# -- -ATTDEF ------------------------------------------------------------------------

def test_attdef_cli_walks_autocads_prompts_and_makes_a_definition():
    h = Harness()
    tool = AttDefCliTool(h.ctx)
    tool.start()
    assert h.echoed[0].startswith("Current attribute modes: Invisible=N "
                                  "Constant=N Verify=N Preset=N "
                                  "Lock position=Y")
    assert h.prompts[-1].startswith("Enter an option to change [Invisible/"
                                    "Constant/Verify/Preset/Lock position/"
                                    "Annotative/Multiple lines] <done>:")
    h.type(tool, "I")                       # toggle Invisible
    assert "Invisible=Y" in h.echoed[-1]
    h.type(tool, "")                        # done with the modes
    assert h.prompts[-1] == "Enter attribute tag name:"
    assert tool.wants_raw_text()
    h.type(tool, "sheet no")                # spaces go, uppercase
    assert h.prompts[-1] == "Enter attribute prompt:"
    h.type(tool, "Enter the sheet number")
    assert h.prompts[-1] == "Enter default attribute value:"
    h.type(tool, "A01")
    assert not tool.wants_raw_text()
    assert h.prompts[-1] == "Specify start point of text or [Justify/Style]:"
    tool.on_point((5.0, 15.0))
    assert h.prompts[-1].startswith("Specify height <")
    h.type(tool, "2.5")
    assert h.prompts[-1].startswith("Specify rotation angle of text <")
    h.type(tool, "")
    assert h.finished
    defs = [e for e in h.msp if e.dxftype() == "ATTDEF"]
    assert len(defs) == 1
    a = defs[0]
    assert a.dxf.tag == "SHEETNO"
    assert a.dxf.prompt == "Enter the sheet number"
    assert a.dxf.text == "A01"
    assert a.is_invisible and not a.is_const
    assert a.dxf.lock_position == 1
    assert (a.dxf.insert.x, a.dxf.insert.y) == (5.0, 15.0)
    assert a.dxf.height == 2.5
    # undo removes it exactly
    h.history.undo()
    assert not [e for e in h.msp if e.dxftype() == "ATTDEF"]
    h.history.redo()
    assert len([e for e in h.msp if e.dxftype() == "ATTDEF"]) == 1
    AttDefCliTool.mode = att.AttMode()      # the session sticky mode: reset


def test_attdef_constant_mode_asks_the_value_not_a_prompt():
    h = Harness()
    tool = AttDefCliTool(h.ctx)
    tool.start()
    h.type(tool, "C")
    h.type(tool, "")
    h.type(tool, "FIRM")
    assert h.prompts[-1] == "Enter attribute value:"
    h.type(tool, "INGELIBRE")
    assert h.prompts[-1] == "Specify start point of text or [Justify/Style]:"
    tool.on_point((0, 0)); h.type(tool, "3"); h.type(tool, "0")
    a = [e for e in h.msp if e.dxftype() == "ATTDEF"][0]
    assert a.is_const and a.dxf.text == "INGELIBRE" and a.dxf.prompt == ""
    AttDefCliTool.mode = att.AttMode()


# -- INSERT with attributes ----------------------------------------------------------

def test_insert_asks_each_attribute_value_and_places_it_by_the_matrix():
    h = Harness()
    _title_block(h.document.doc)
    tool = InsertTool(h.ctx)
    tool.start()
    h.type(tool, "R"); h.type(tool, "90")      # rotate 90
    tool.on_point((1000.0, 500.0))
    assert h.echoed[-1] == "Enter attribute values"
    assert h.prompts[-1] == "Enter sheet <A01>:"
    assert tool.wants_raw_text()
    h.type(tool, "A07")
    assert h.prompts[-1] == "Enter title <PLANTA>:"
    h.type(tool, "")                           # keep the default
    assert h.finished
    inserts = [e for e in h.msp if e.dxftype() == "INSERT"]
    assert len(inserts) == 1
    ins = inserts[0]
    values = {a.dxf.tag: a.dxf.text for a in ins.attribs}
    assert values == {"SHEET": "A07", "TITLE": "PLANTA"}
    # the ATTRIB sits where the reference's matrix puts the ATTDEF: (5, 15)
    # rotated 90 deg about the insertion point -> (1000 - 15, 500 + 5)
    sheet = ins.get_attrib("SHEET")
    assert (sheet.dxf.insert.x, sheet.dxf.insert.y) == pytest.approx(
        (985.0, 505.0))
    assert sheet.dxf.rotation == pytest.approx(90.0)
    h.history.undo()
    assert not [e for e in h.msp if e.dxftype() == "INSERT"]


def test_insert_with_attreq_off_takes_every_default_and_preset_never_asks(
        monkeypatch):
    from tools import attributes as tools_att

    h = Harness()
    block = _title_block(h.document.doc)
    preset = [a for a in block.attdefs() if a.dxf.tag == "TITLE"][0]
    preset.is_preset = True
    tool = InsertTool(h.ctx)
    tool.start()
    tool.on_point((0.0, 0.0))
    assert h.prompts[-1] == "Enter sheet <A01>:", "Preset TITLE was asked"
    h.type(tool, "")
    assert h.finished
    ins = [e for e in h.msp if e.dxftype() == "INSERT"][0]
    assert {a.dxf.tag: a.dxf.text for a in ins.attribs} == {
        "SHEET": "A01", "TITLE": "PLANTA"}

    monkeypatch.setattr(tools_att.AttReqTool, "value", classmethod(lambda c: 0))
    h2 = Harness()
    _title_block(h2.document.doc)
    tool = InsertTool(h2.ctx)
    tool.start()
    tool.on_point((0.0, 0.0))
    assert h2.finished and not [p for p in h2.prompts if p.startswith("Enter sheet")]
    ins = [e for e in h2.msp if e.dxftype() == "INSERT"][0]
    assert len(ins.attribs) == 2


def test_a_constant_definition_gets_no_attrib_but_is_drawn_by_the_reference():
    from render.backend import build_scene

    h = Harness()
    block = _title_block(h.document.doc, (("FIRM", "INGELIBRE"),))
    const = [a for a in block.attdefs() if a.dxf.tag == "FIRM"][0]
    const.is_const = True
    h.history.execute(att.insert_block_with_attribs("TB", (0.0, 0.0)))
    ins = [e for e in h.msp if e.dxftype() == "INSERT"][0]
    assert not ins.attribs, "a Constant attribute made an ATTRIB"
    with_text = build_scene(h.document, "Model")
    n_with = len(with_text.triangles.data)      # glyphs are filled triangles
    const.dxf.text = ""
    without = build_scene(h.document, "Model")
    assert n_with > len(without.triangles.data), (
        "the constant definition's text is not drawn in the reference")


# -- editing ------------------------------------------------------------------------

def _inserted(h):
    _title_block(h.document.doc)
    h.history.execute(att.insert_block_with_attribs(
        "TB", (0.0, 0.0), values={"SHEET": "A01"}))
    return [e for e in h.msp if e.dxftype() == "INSERT"][0]


def test_attedit_cli_one_at_a_time_value_height_layer_color_next():
    h = Harness()
    ins = _inserted(h)
    tool = AttEditCliTool(h.ctx)
    tool.start()
    assert h.prompts[-1] == "Edit attributes one at a time? [Yes/No] <Y>:"
    h.type(tool, "")
    assert h.prompts[-1] == "Enter block name specification <*>:"
    h.type(tool, ""); h.type(tool, ""); h.type(tool, "")
    assert h.prompts[-1] == "Select Attributes:"
    tool.on_point((0.0, 0.0))
    h.type(tool, "")                       # done selecting
    assert h.prompts[-1] == ("Enter an option [Value/Position/Height/Angle/"
                             "Style/Layer/Color/Next] <N>:")
    h.type(tool, "V")
    assert h.prompts[-1] == "Enter type of value modification [Change/Replace] <R>:"
    h.type(tool, "")
    assert h.prompts[-1] == "Enter new attribute value:"
    h.type(tool, "A02")
    sheet = ins.get_attrib("SHEET")
    assert sheet.dxf.text == "A02"
    h.type(tool, "H"); h.type(tool, "4")
    assert sheet.dxf.height == 4.0
    h.type(tool, "C"); h.type(tool, "red")
    assert sheet.dxf.color == 1
    h.type(tool, "N")                      # next attribute: TITLE
    assert "TITLE" in h.echoed[-1]
    h.type(tool, "V"); h.type(tool, "C")   # Change a substring
    h.type(tool, "PLAN"); h.type(tool, "ELEV")
    assert ins.get_attrib("TITLE").dxf.text == "ELEVTA"
    h.type(tool, "")                       # Next past the end: done
    assert h.finished
    # every step is its own undo
    h.history.undo()
    assert ins.get_attrib("TITLE").dxf.text == "PLANTA"
    h.history.undo(); h.history.undo(); h.history.undo()
    assert sheet.dxf.text == "A01" and sheet.dxf.height == 2.5
    assert not sheet.dxf.hasattr("color")


def test_attedit_cli_global_replaces_a_string_in_every_matching_value():
    h = Harness()
    ins = _inserted(h)
    h.history.execute(att.insert_block_with_attribs(
        "TB", (50.0, 0.0), values={"SHEET": "A11"}))
    other = [e for e in h.msp if e.dxftype() == "INSERT"][1]
    tool = AttEditCliTool(h.ctx)
    tool.start()
    h.type(tool, "N")
    assert h.prompts[-1] == "Edit only attributes visible on screen? [Yes/No] <Y>:"
    h.type(tool, "")
    h.type(tool, ""); h.type(tool, "SHEET"); h.type(tool, "")
    tool.on_point((0.0, 0.0)); tool.on_point((50.0, 0.0)); h.type(tool, "")
    assert h.prompts[-1] == "Enter string to change:"
    h.type(tool, "A"); h.type(tool, "E")
    assert h.finished
    assert ins.get_attrib("SHEET").dxf.text == "E01"
    assert other.get_attrib("SHEET").dxf.text == "E11"
    assert ins.get_attrib("TITLE").dxf.text == "PLANTA", "tag filter ignored"
    h.history.undo()
    assert ins.get_attrib("SHEET").dxf.text == "A01"


def test_attsync_adds_missing_attribs_removes_orphans_and_keeps_values():
    h = Harness()
    ins = _inserted(h)
    block = h.document.doc.blocks.get("TB")
    block.add_attdef("SCALE", insert=(5, 5), text="1:100",
                     dxfattribs={"height": 2.5})
    title = [a for a in block.attdefs() if a.dxf.tag == "TITLE"][0]
    block.unlink_entity(title)
    tool = AttSyncTool(h.ctx)
    tool.start()
    assert h.prompts[-1] == "Enter an option [?/Name/Select] <Select>:"
    h.type(tool, "N")
    assert h.prompts[-1] == "Enter name of block to sync or [?]:"
    h.type(tool, "TB")
    assert h.prompts[-1] == "ATTSYNC block TB? [Yes/No] <Yes>:"
    h.type(tool, "")
    assert h.finished
    tags = {a.dxf.tag: a.dxf.text for a in ins.attribs}
    assert tags == {"SHEET": "A01", "SCALE": "1:100"}
    h.history.undo()
    assert {a.dxf.tag for a in ins.attribs} == {"SHEET", "TITLE"}
    assert ins.get_attrib("SHEET").dxf.text == "A01"


def test_attdisp_sets_attmode_and_the_renderer_honours_it():
    from render.backend import build_scene

    h = Harness()
    ins = _inserted(h)
    ins.get_attrib("SHEET").is_invisible = True
    def glyphs():
        return len(build_scene(h.document, "Model").triangles.data)

    normal = glyphs()
    tool = AttDispTool(h.ctx)
    tool.start()
    assert h.prompts[-1] == ("Enter attribute visibility setting "
                             "[Normal/ON/OFF] <Normal>:")
    h.type(tool, "ON")
    assert h.document.doc.header["$ATTMODE"] == 2
    shown = glyphs()
    assert shown > normal, "ON did not show the invisible attribute"
    tool = AttDispTool(h.ctx); tool.start(); h.type(tool, "OFF")
    hidden = glyphs()
    assert hidden < normal, "OFF did not hide the visible attribute"
    h.history.undo()
    assert h.document.doc.header["$ATTMODE"] == 2


def test_untouched_attributes_survive_a_save_byte_for_byte(tmp_path):
    """The round-trip invariant: a drawing with attributed inserts, opened,
    an unrelated line moved, saved -- the inserts and their attribs identical."""
    from core import actions
    from ezdxf.math import Matrix44

    doc = ezdxf.new("R2018", setup=True)
    _title_block(doc)
    msp = doc.modelspace()
    ins = msp.add_blockref("TB", (0, 0))
    ins.add_auto_attribs({"SHEET": "A03"})
    ins.get_attrib("SHEET").is_invisible = True
    line = msp.add_line((0, 0), (10, 0))
    path = tmp_path / "tb.dxf"
    doc.saveas(path)

    document = Document.load(path)
    before = [f for f in _fingerprint(document.modelspace())
              if f[0] != "LINE"]
    attr_before = [_fingerprint(e.attribs) for e in document.modelspace()
                   if e.dxftype() == "INSERT"]
    history = History(document)
    target = [e for e in document.modelspace() if e.dxftype() == "LINE"][0]
    history.execute(actions.TransformCommand(
        "MOVE", [target], Matrix44.translate(0, 5, 0)))
    out = tmp_path / "tb2.dxf"
    document.doc.saveas(out)
    again = Document.load(out)
    after = [f for f in _fingerprint(again.modelspace()) if f[0] != "LINE"]
    attr_after = [_fingerprint(e.attribs) for e in again.modelspace()
                  if e.dxftype() == "INSERT"]
    assert after == before
    assert attr_after == attr_before


# -- through the window ---------------------------------------------------------------

def _window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document("mm")
    win.show()
    qapp.processEvents()
    _title_block(win.document.doc)
    win.history.execute(att.insert_block_with_attribs(
        "TB", (0.0, 0.0), values={"SHEET": "A01"}))
    win.tools._invalidate_geometry()
    win.tools.index.invalidate()
    win.tools.index._build()
    qapp.processEvents()
    return win


def test_double_click_on_an_attributed_block_opens_the_attribute_editor(
        qapp, monkeypatch):
    from PySide6.QtCore import QTimer

    from views import attribute_dialogs

    win = _window(qapp)
    try:
        seen = []

        class Editing(attribute_dialogs.EnhancedAttributeEditor):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                seen.append(self)
                self.set_value(0, "A09")
                QTimer.singleShot(0, self.accept)

        monkeypatch.setattr(attribute_dialogs, "EnhancedAttributeEditor",
                            Editing)
        opened_text = []
        win.tools.open_text_editor_for = lambda e: (opened_text.append(e), True)[1]
        win.on_canvas_double_click(50.0, 10.0)      # inside the title block
        qapp.processEvents()
        assert seen, "the Enhanced Attribute Editor did not open"
        assert not opened_text, "the text editor took the double-click"
        ins = [e for e in win.document.modelspace() if e.dxftype() == "INSERT"][0]
        assert ins.get_attrib("SHEET").dxf.text == "A09"
        win.history.undo()
        assert ins.get_attrib("SHEET").dxf.text == "A01"
    finally:
        win.document.dirty = False
        win.close()


def test_typed_attedit_reaches_the_tool_with_raw_text(qapp):
    """The real path: -ATTEDIT and its answers typed on the command line;
    a value like 'END' must not be eaten as an object snap."""
    win = _window(qapp)
    try:
        ins = [e for e in win.document.modelspace() if e.dxftype() == "INSERT"][0]
        submit = win._on_command_submitted
        submit("-ATTEDIT")
        assert win.tools.tool is not None and win.tools.tool.name == "-ATTEDIT"
        submit(""); submit(""); submit(""); submit("")
        win.tools.tool.on_point((0.0, 0.0))
        submit("")
        submit("V"); submit("R"); submit("END")
        assert ins.get_attrib("SHEET").dxf.text == "END"
        submit("N"); submit("N")
        assert win.tools.tool is None
    finally:
        win.document.dirty = False
        win.close()


def test_battman_moves_edits_removes_and_syncs(qapp, monkeypatch):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox

    from views import attdef_dialog
    from views.battman_dialog import BattmanDialog

    win = _window(qapp)
    try:
        dlg = BattmanDialog(win)
        block = win.document.doc.blocks.get("TB")
        assert [dlg.table.item(r, 0).text() for r in range(2)] == ["SHEET", "TITLE"]
        dlg.table.setCurrentCell(1, 0)
        dlg.move_up()
        assert [a.dxf.tag for a in att.attdefs_of(win.document.doc, "TB")] == [
            "TITLE", "SHEET"]
        assert [dlg.table.item(r, 0).text() for r in range(2)] == ["TITLE", "SHEET"]

        class Editing(attdef_dialog.AttDefDialog):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self.prompt_edit.setText("Enter the title")
                self.invisible.setChecked(True)
                QTimer.singleShot(0, self.accept)

        monkeypatch.setattr(attdef_dialog, "AttDefDialog", Editing)
        dlg.table.setCurrentCell(0, 0)
        dlg.edit()
        title = [a for a in block.attdefs() if a.dxf.tag == "TITLE"][0]
        assert title.dxf.prompt == "Enter the title" and title.is_invisible

        monkeypatch.setattr(QMessageBox, "question",
                            staticmethod(lambda *a, **k: QMessageBox.Yes))
        dlg.table.setCurrentCell(0, 0)
        dlg.remove()
        assert [a.dxf.tag for a in att.attdefs_of(win.document.doc, "TB")] == ["SHEET"]
        dlg.sync()
        ins = [e for e in win.document.modelspace() if e.dxftype() == "INSERT"][0]
        assert [a.dxf.tag for a in ins.attribs] == ["SHEET"]
        assert ins.get_attrib("SHEET").dxf.text == "A01"
        for _ in range(4):
            win.history.undo()
        assert [a.dxf.tag for a in att.attdefs_of(win.document.doc, "TB")] == [
            "SHEET", "TITLE"]
        assert {a.dxf.tag for a in ins.attribs} == {"SHEET", "TITLE"}
        dlg.close()
    finally:
        win.document.dirty = False
        win.close()


def test_attdef_dialog_values_and_align_below(qapp):
    from views.attdef_dialog import AttDefDialog, below

    win = _window(qapp)
    try:
        previous = att.attdefs_of(win.document.doc, "TB")[0]
        dlg = AttDefDialog(win, win.document, previous=previous)
        dlg.tag.setText("scale")
        dlg.prompt_edit.setText("Enter scale")
        dlg.default.setText("1:100")
        dlg.preset.setChecked(True)
        dlg.align_below.setChecked(True)
        v = dlg.values()
        assert v["tag"] == "SCALE" and v["mode"].preset
        assert v["align_below"] and v["below"] == below(previous)
        assert v["below"] == pytest.approx((5.0, 15.0 - 2.5 * 5 / 3))
        assert not v["on_screen"]
        dlg.close()
    finally:
        win.document.dirty = False
        win.close()


# -- Rafael's flow (#88): define, edit the definition, BLOCK, INSERT ------------

def _rafaels_definition(win):
    from core import actions

    win.tools._execute(actions.add_line((200, 0), (220, 0)))
    win.tools._execute(att.add_attdef("nombre", "¿Nombre?", "Rafa",
                                      (200.0, 5.0), 2.5))
    return [e for e in win.document.modelspace() if e.dxftype() == "ATTDEF"][0]


def test_a_double_click_on_a_definition_edits_its_tag_prompt_and_default(
        qapp, monkeypatch):
    # Rafael (2026-10-12): the definition shows its tag, and the in-place
    # editor offered only the default -- "no encontré la forma de editar
    # el atributo una vez creado"
    from PySide6.QtCore import QTimer

    from views import attribute_dialogs

    win = _window(qapp)
    try:
        attdef = _rafaels_definition(win)

        class Editing(attribute_dialogs.EditAttDefDialog):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                assert (self.tag.text(), self.prompt.text(),
                        self.default.text()) == ("NOMBRE", "¿Nombre?", "Rafa")
                self.tag.setText("autor")
                self.prompt.setText("¿Autor del plano?")
                self.default.setText("Rafael")
                QTimer.singleShot(0, self._accept)

        monkeypatch.setattr(attribute_dialogs, "EditAttDefDialog", Editing)
        win.on_canvas_double_click(200.5, 5.5)
        qapp.processEvents()
        assert (attdef.dxf.tag, attdef.dxf.prompt, attdef.dxf.text) == (
            "AUTOR", "¿Autor del plano?", "Rafael")
        win._cmd_undo()                       # one step
        assert (attdef.dxf.tag, attdef.dxf.prompt, attdef.dxf.text) == (
            "NOMBRE", "¿Nombre?", "Rafa")
    finally:
        win.document.dirty = False
        win.close()


def test_properties_edit_a_definitions_prompt_and_an_attributes_value(qapp):
    from PySide6.QtWidgets import QLineEdit, QTreeWidgetItemIterator

    from core.i18n import tr

    def type_in(panel, label, text):
        editor = None
        it = QTreeWidgetItemIterator(panel.tree)
        while it.value():
            if it.value().text(0) == tr(label):
                editor = panel.tree.itemWidget(it.value(), 1)
            it += 1
        assert isinstance(editor, QLineEdit), label
        editor.setText(text)
        editor.editingFinished.emit()

    win = _window(qapp)
    try:
        attdef = _rafaels_definition(win)
        win.tools.selection = {attdef.dxf.handle}
        win.toggle_properties_panel()
        panel = win._properties_panel
        panel.refresh()
        type_in(panel, "Prompt", "¿Autor?")
        panel.refresh()
        type_in(panel, "Tag", "autor")
        assert (attdef.dxf.tag, attdef.dxf.prompt) == ("AUTOR", "¿Autor?")
        win._cmd_undo()
        win._cmd_undo()
        assert (attdef.dxf.tag, attdef.dxf.prompt) == ("NOMBRE", "¿Nombre?")
        # a reference's attribute: its value
        sheet = [e for e in win.document.modelspace()
                 if e.dxftype() == "INSERT"][0].get_attrib("SHEET")
        win.tools.selection = {sheet.dxf.handle}
        panel.refresh()
        type_in(panel, "Value", "A12")
        assert sheet.dxf.text == "A12"
    finally:
        win.document.dirty = False
        win.close()


def test_block_gives_the_converted_reference_its_attributes():
    from core import actions

    h = Harness()
    h.history.execute(actions.add_line((0, 0), (20, 0)))
    h.history.execute(att.add_attdef("nombre", "¿Nombre?", "Rafa", (0, 5), 2.5))
    h.history.execute(actions.create_block("PERSONA", (0, 0), list(h.msp)))
    (ref,) = list(h.msp)
    assert [(a.dxf.tag, a.dxf.text) for a in ref.attribs] == [("NOMBRE", "Rafa")]
    h.history.undo()
    assert sorted(e.dxftype() for e in h.msp) == ["ATTDEF", "LINE"]
    # and INSERT then asks the definition's prompt, proposing its default
    h.history.redo()
    tool = InsertTool(h.ctx)
    tool.start()
    tool.on_point((50.0, 50.0))
    assert h.prompts[-1] == "¿Nombre? <Rafa>:"


def test_eattedit_on_a_definition_says_where_it_is_edited():
    from tools.attributes import EattEditTool

    h = Harness()
    h.history.execute(att.add_attdef("nombre", "¿Nombre?", "Rafa", (0, 5), 2.5))
    attdef = list(h.msp)[0]
    h.services.pick_entity = lambda point: attdef
    tool = EattEditTool(h.ctx)
    tool.start()
    tool.on_point((0.0, 5.0))
    assert h.echoed[-2] == "That object is not a block."
    assert "DDEDIT" in h.echoed[-1]
