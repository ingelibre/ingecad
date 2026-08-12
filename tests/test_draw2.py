# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Phase 6 draw tools: ellipse, point, text, mtext, arc SCE."""
from __future__ import annotations

import math

import ezdxf
import pytest

from core.commands import History
from core.document import Document
from tools.base import ToolContext
from tools.draw import ArcTool, EllipseTool, MTextTool, PointTool, TextTool


@pytest.fixture(autouse=True)
def _fresh_text_state():
    # TEXT's height/rotation defaults are session-sticky like AutoCAD's
    # TEXTSIZE / last rotation — reset them per test.
    TextTool.default_height = 2.5
    TextTool.last_rotation = 0.0
    TextTool._last_final = None
    yield


class Harness:
    def __init__(self, text_answer="Hola"):
        self.document = Document(ezdxf.new("R2018", setup=True))
        self.history = History(self.document)
        self.finished = False
        self.ctx = ToolContext(
            execute=self.history.execute,
            prompt=lambda *_a: None,
            echo=lambda *_a: None,
            finish=lambda: setattr(self, "finished", True),
            ask_text=lambda *_a: text_answer,
        )

    @property
    def msp(self):
        return self.document.modelspace()


def test_ellipse_axis_mode():
    h = Harness()
    tool = EllipseTool(h.ctx)
    tool.start()
    tool.on_point((-10, 0))     # axis endpoint 1
    tool.on_point((10, 0))      # axis endpoint 2 -> major length 10, center 0
    tool.on_point((0, 4))       # distance to other axis: 4 -> ratio 0.4
    e = h.msp.query("ELLIPSE")[0]
    assert e.dxf.center.x == pytest.approx(0.0)
    assert e.dxf.ratio == pytest.approx(0.4)
    assert math.hypot(e.dxf.major_axis.x, e.dxf.major_axis.y) == pytest.approx(10.0)


def test_ellipse_center_mode():
    h = Harness()
    tool = EllipseTool(h.ctx)
    tool.start()
    assert tool.on_option("C")
    tool.on_point((0, 0))       # center
    tool.on_point((10, 0))      # major axis endpoint -> length 10
    tool.on_point((0, 5))       # distance to other axis 5 -> ratio 0.5
    e = h.msp.query("ELLIPSE")[0]
    assert e.dxf.ratio == pytest.approx(0.5)


def test_point_repeats():
    h = Harness()
    tool = PointTool(h.ctx)
    tool.start()
    tool.on_point((1, 1))
    tool.on_point((2, 2))
    tool.on_point((3, 3))
    assert len(h.msp.query("POINT")) == 3
    assert not h.finished          # stays active until Enter/Esc


def _type(tool, s):
    for ch in s:
        tool.on_char(ch)


def test_text_tool_in_place_typing():
    # DTEXT: point -> height -> rotation -> type in place; Esc finishes.
    h = Harness()
    tool = TextTool(h.ctx)
    tool.start()
    tool.on_point((5, 5))
    tool.on_option("3")            # height 3
    tool.on_option("45")           # rotation 45
    assert tool.typing
    _type(tool, "PLANO")
    tool.on_backspace()            # -> PLAN
    _type(tool, "O")               # -> PLANO
    tool.finish_typing()           # Esc keeps the text
    t = h.msp.query("TEXT")[0]
    assert t.dxf.text == "PLANO"
    assert t.dxf.height == pytest.approx(3.0)
    assert t.dxf.rotation == pytest.approx(45.0)
    assert h.finished


def test_text_tool_multiple_lines():
    # Enter commits a line and drops to a new one below (separate TEXT each).
    h = Harness()
    tool = TextTool(h.ctx)
    tool.start()
    tool.on_point((0, 0))
    tool.on_enter()               # default height
    tool.on_enter()               # rotation 0 -> begin typing
    _type(tool, "linea uno")
    tool.on_enter()               # commit, new line below
    _type(tool, "linea dos")
    tool.finish_typing()
    texts = sorted(t.dxf.text for t in h.msp.query("TEXT"))
    assert texts == ["linea dos", "linea uno"]
    # second line sits 1.5*height below the first
    ys = sorted(t.dxf.insert.y for t in h.msp.query("TEXT"))
    assert ys[0] == pytest.approx(-1.5 * TextTool.default_height)


def test_mtext_tool():
    h = Harness(text_answer="línea 1\nlínea 2")
    tool = MTextTool(h.ctx)
    tool.start()
    tool.on_point((0, 10))
    tool.on_point((40, 0))
    m = h.msp.query("MTEXT")[0]
    assert "línea 1" in m.text
    assert m.dxf.width == pytest.approx(40.0)


def test_arc_start_center_end():
    h = Harness()
    tool = ArcTool(h.ctx)
    tool.start()
    tool.on_point((10, 0))        # start
    assert tool.on_option("C")    # switch to Start/Center/End
    tool.on_point((0, 0))         # center -> radius 10
    tool.on_point((0, 10))        # end direction (90 deg)
    arc = h.msp.query("ARC")[0]
    assert arc.dxf.radius == pytest.approx(10.0)
    assert arc.dxf.start_angle == pytest.approx(0.0)
    assert arc.dxf.end_angle == pytest.approx(90.0)


def test_arc_three_point_still_works():
    h = Harness()
    tool = ArcTool(h.ctx)
    tool.start()
    for p in ((0, 0), (5, 5), (10, 0)):
        tool.on_point(p)
    assert len(h.msp.query("ARC")) == 1


# -- the in-place MTEXT editor (step 1) ----------------------------------------

def _editor_window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document("mm")
    win.show()
    qapp.processEvents()
    return win


def test_mtext_opens_the_in_place_editor_not_a_dialog(qapp):
    win = _editor_window(qapp)
    try:
        win.dispatcher.submit("MTEXT")
        win.tools.tool.on_point((10.0, 40.0))
        win.tools.tool.on_point((90.0, 10.0))
        qapp.processEvents()
        editor = win.tools._mtext_editor
        assert editor is not None and editor.isVisible()
        # The tool itself is done: the editor outlives it.
        assert win.tools.tool is None
    finally:
        win.tools._mtext_editor.cancel(ask=False)
        win.close()


def test_enter_is_a_paragraph_break_and_ctrl_enter_commits(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    win = _editor_window(qapp)
    try:
        win.dispatcher.submit("MTEXT")
        win.tools.tool.on_point((10.0, 40.0))
        win.tools.tool.on_point((90.0, 10.0))
        qapp.processEvents()
        editor = win.tools._mtext_editor
        QTest.keyClicks(editor.edit, "linea 1")
        QTest.keyClick(editor.edit, Qt.Key_Return)
        assert editor.isVisible(), "plain Enter must NOT commit"
        QTest.keyClicks(editor.edit, "linea 2")
        QTest.keyClick(editor.edit, Qt.Key_Return, Qt.ControlModifier)
        qapp.processEvents()
        made = [e for e in win.document.modelspace()
                if e.dxftype() == "MTEXT"]
        assert len(made) == 1
        assert made[0].text == "linea 1\\Plinea 2"   # real MTEXT paragraphs
        # It undoes like everything else.
        win.history.undo()
        assert not [e for e in win.document.modelspace()
                    if e.dxftype() == "MTEXT"]
    finally:
        win.close()


def test_an_empty_editor_commits_nothing(qapp):
    win = _editor_window(qapp)
    try:
        win.dispatcher.submit("MTEXT")
        win.tools.tool.on_point((0.0, 10.0))
        win.tools.tool.on_point((50.0, 0.0))
        qapp.processEvents()
        win.tools._mtext_editor.commit()
        qapp.processEvents()
        assert not [e for e in win.document.modelspace()
                    if e.dxftype() == "MTEXT"]
    finally:
        win.close()


def test_escape_on_an_untouched_editor_closes_without_asking(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    win = _editor_window(qapp)
    try:
        win.dispatcher.submit("MTEXT")
        win.tools.tool.on_point((0.0, 10.0))
        win.tools.tool.on_point((50.0, 0.0))
        qapp.processEvents()
        editor = win.tools._mtext_editor
        QTest.keyClick(editor.edit, Qt.Key_Escape)
        qapp.processEvents()
        assert not editor.isVisible()
        assert not [e for e in win.document.modelspace()
                    if e.dxftype() == "MTEXT"]
    finally:
        win.close()


def test_double_click_edits_the_mtext_where_it_stands(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    win = _editor_window(qapp)
    try:
        mtext = win.document.modelspace().add_mtext(
            "NOTA:\\Pver detalle", dxfattribs={"char_height": 2.5,
                                               "width": 60.0})
        mtext.set_location((10.0, 40.0))
        win.tools.index.invalidate()
        win.tools.index._build()

        win.on_canvas_double_click(11.0, 39.0)
        qapp.processEvents()
        editor = win.tools._mtext_editor
        assert editor.isVisible()
        # \P came in as a real line break for editing.
        assert editor.edit.toPlainText() == "NOTA:\nver detalle"
        editor.edit.setPlainText("NOTA:\nver plano A-02")
        editor.commit()
        qapp.processEvents()
        assert mtext.text == "NOTA:\\Pver plano A-02"
        win.history.undo()
        assert mtext.text == "NOTA:\\Pver detalle"
    finally:
        win.close()


def test_inline_codes_survive_an_edit_that_does_not_touch_them(qapp):
    """Codes OUTSIDE the rich subset stay raw and round-trip untouched.

    Bold and height moved INTO the subset with the toolbar, so this now
    uses a stacked fraction and an oblique code — the kind parse_runs
    refuses, which is what forces raw mode.
    """
    win = _editor_window(qapp)
    try:
        raw = "\\Q15;inclinado \\S1/2; resto"
        mtext = win.document.modelspace().add_mtext(
            raw, dxfattribs={"char_height": 2.5, "width": 60.0})
        mtext.set_location((10.0, 40.0))
        win.tools.index.invalidate()
        win.tools.index._build()
        win.on_canvas_double_click(11.0, 39.0)
        qapp.processEvents()
        editor = win.tools._mtext_editor
        editor.edit.setPlainText(editor.edit.toPlainText() + " (rev B)")
        editor.commit()
        qapp.processEvents()
        assert mtext.text == raw + " (rev B)"
    finally:
        win.close()


def test_the_editor_stays_anchored_through_zoom(qapp):
    win = _editor_window(qapp)
    try:
        win.dispatcher.submit("MTEXT")
        win.tools.tool.on_point((10.0, 40.0))
        win.tools.tool.on_point((90.0, 10.0))
        qapp.processEvents()
        editor = win.tools._mtext_editor
        before = (editor.geometry().topLeft(), editor.edit.font().pixelSize())
        win.viewport.view.zoom_at(200, 200, 2.0)
        editor._sync_geometry()
        after = (editor.geometry().topLeft(), editor.edit.font().pixelSize())
        assert before[0] != after[0], "the editor did not follow the text"
        assert after[1] > before[1], "the text did not grow with the zoom"
    finally:
        win.tools._mtext_editor.cancel(ask=False)
        win.close()


# -- the Text Formatting toolbar (step 2) --------------------------------------

def test_typing_with_bold_writes_a_real_mtext_code(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    win = _editor_window(qapp)
    try:
        win.dispatcher.submit("MTEXT")
        win.tools.tool.on_point((10.0, 40.0))
        win.tools.tool.on_point((90.0, 10.0))
        qapp.processEvents()
        editor = win.tools._mtext_editor
        assert editor.rich
        QTest.keyClicks(editor.edit, "normal ")
        editor.bold.setChecked(True)
        QTest.keyClicks(editor.edit, "NEGRITA")
        editor.commit()
        qapp.processEvents()
        made = [e for e in win.document.modelspace()
                if e.dxftype() == "MTEXT"][0]
        assert made.text == "normal {\\fArial|b1|i0;NEGRITA}"
        # And ezdxf's own parser agrees on what that means.
        from core.mtext_format import parse_runs

        runs = parse_runs(made.text, 2.5)
        assert [r.bold for r in runs[0]] == [False, True]
    finally:
        win.close()


def test_colour_and_height_reach_the_stream(qapp):
    from PySide6.QtTest import QTest

    win = _editor_window(qapp)
    try:
        win.dispatcher.submit("MTEXT")
        win.tools.tool.on_point((10.0, 40.0))
        win.tools.tool.on_point((90.0, 10.0))
        qapp.processEvents()
        editor = win.tools._mtext_editor
        index = editor.color_combo.findData(1)          # red
        editor.color_combo.setCurrentIndex(index)
        editor._apply_color(index)
        editor.height_spin.setValue(5.0)                # 2x the char height
        editor._apply_height()
        QTest.keyClicks(editor.edit, "ROJO GRANDE")
        editor.commit()
        qapp.processEvents()
        made = [e for e in win.document.modelspace()
                if e.dxftype() == "MTEXT"][0]
        assert "\\C1;" in made.text
        assert "\\H2x;" in made.text
    finally:
        win.close()


def test_editing_a_formatted_text_opens_rich_and_keeps_the_formatting(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    win = _editor_window(qapp)
    try:
        raw = "{\\fArial|b1|i0;TITULO} resto"
        mtext = win.document.modelspace().add_mtext(
            raw, dxfattribs={"char_height": 2.5, "width": 60.0})
        mtext.set_location((10.0, 40.0))
        win.tools.index.invalidate()
        win.tools.index._build()
        win.on_canvas_double_click(11.0, 39.0)
        qapp.processEvents()
        editor = win.tools._mtext_editor
        assert editor.rich
        # Typing at the end (plain) and committing keeps the bold TITLE.
        QTest.keyClicks(editor.edit, " y firma")
        editor.commit()
        qapp.processEvents()
        assert mtext.text.startswith("{\\fArial|b1|i0;TITULO}")
        assert mtext.text.endswith("y firma")
    finally:
        win.close()


def test_raw_mode_disables_the_formatting_controls(qapp):
    win = _editor_window(qapp)
    try:
        mtext = win.document.modelspace().add_mtext(
            "antes \\S1/2; despues", dxfattribs={"char_height": 2.5,
                                                 "width": 60.0})
        mtext.set_location((10.0, 40.0))
        win.tools.index.invalidate()
        win.tools.index._build()
        win.on_canvas_double_click(11.0, 39.0)
        qapp.processEvents()
        editor = win.tools._mtext_editor
        assert not editor.rich
        assert not editor.bold.isEnabled()
        assert not editor.color_combo.isEnabled()
        assert editor.stack.isEnabled()       # Stack lives in raw mode
        editor.cancel(ask=False)
    finally:
        win.close()


def test_stack_wraps_the_selection_in_the_code(qapp):
    win = _editor_window(qapp)
    try:
        mtext = win.document.modelspace().add_mtext(
            "\\Q15;pendiente 1/2 aqui", dxfattribs={"char_height": 2.5,
                                                    "width": 60.0})
        mtext.set_location((10.0, 40.0))
        win.tools.index.invalidate()
        win.tools.index._build()
        win.on_canvas_double_click(11.0, 39.0)
        qapp.processEvents()
        editor = win.tools._mtext_editor
        cursor = editor.edit.textCursor()
        start = editor.edit.toPlainText().index("1/2")
        cursor.setPosition(start)
        cursor.setPosition(start + 3, cursor.MoveMode.KeepAnchor)
        editor.edit.setTextCursor(cursor)
        editor._apply_stack()
        editor.commit()
        qapp.processEvents()
        assert "\\S1/2;" in mtext.text
    finally:
        win.close()


def test_justify_places_the_new_text_by_the_box_corner(qapp):
    win = _editor_window(qapp)
    try:
        win.dispatcher.submit("MTEXT")
        win.tools.tool.on_point((10.0, 40.0))
        win.tools.tool.on_point((90.0, 10.0))
        qapp.processEvents()
        editor = win.tools._mtext_editor
        assert editor.justify.isEnabled()
        editor._set_attachment(5)               # Middle Center
        editor.edit.setPlainText("centrado")
        editor.commit()
        qapp.processEvents()
        made = [e for e in win.document.modelspace()
                if e.dxftype() == "MTEXT"][0]
        assert made.dxf.attachment_point == 5
        assert (made.dxf.insert.x, made.dxf.insert.y) == (50.0, 25.0)
    finally:
        win.close()


def test_style_change_applies_to_the_whole_entity(qapp):
    win = _editor_window(qapp)
    try:
        win.document.doc.styles.add("TITULOS", font="arial.ttf")
        mtext = win.document.modelspace().add_mtext(
            "nota", dxfattribs={"char_height": 2.5, "width": 60.0})
        mtext.set_location((10.0, 40.0))
        win.tools.index.invalidate()
        win.tools.index._build()
        win.on_canvas_double_click(11.0, 39.0)
        qapp.processEvents()
        editor = win.tools._mtext_editor
        index = editor.style_combo.findText("TITULOS")
        assert index >= 0
        editor.style_combo.setCurrentIndex(index)
        editor.commit()
        qapp.processEvents()
        assert mtext.dxf.style == "TITULOS"
        win.history.undo()
        assert mtext.dxf.style == "Standard"
    finally:
        win.close()
