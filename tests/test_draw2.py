# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Phase 6 draw tools: ellipse, point, text, mtext, arc SCE."""
from __future__ import annotations

import math
from pathlib import Path

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
        assert [r.bold for r in runs[0].runs] == [False, True]
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


# -- the ruler (step 3) --------------------------------------------------------

def _open_new_editor(win, qapp):
    win.dispatcher.submit("MTEXT")
    win.tools.tool.on_point((10.0, 40.0))
    win.tools.tool.on_point((90.0, 10.0))
    qapp.processEvents()
    return win.tools._mtext_editor


def test_the_ruler_writes_real_paragraph_codes(qapp):
    from PySide6.QtTest import QTest

    win = _editor_window(qapp)
    try:
        editor = _open_new_editor(win, qapp)
        assert editor.ruler.isVisible()
        QTest.keyClicks(editor.edit, "parrafo con sangria")
        editor.apply_paragraph_props(indent=2.0, left=1.0,
                                     tab_stops=(4.0, "c8"))
        editor.commit()
        qapp.processEvents()
        made = [e for e in win.document.modelspace()
                if e.dxftype() == "MTEXT"][0]
        assert made.text == "\\pxi2,l1,r0,t4,c8;parrafo con sangria"
    finally:
        win.close()


def test_a_text_with_paragraph_codes_reopens_rich_with_the_ruler(qapp):
    win = _editor_window(qapp)
    try:
        mtext = win.document.modelspace().add_mtext(
            "\\pxi-2,l2;colgante", dxfattribs={"char_height": 2.5,
                                               "width": 60.0})
        mtext.set_location((10.0, 40.0))
        win.tools.index.invalidate()
        win.tools.index._build()
        win.on_canvas_double_click(11.0, 39.0)
        qapp.processEvents()
        editor = win.tools._mtext_editor
        assert editor.rich, "paragraph codes must not force raw mode anymore"
        props = editor.current_props()
        assert props.indent == -2.0 and props.left == 2.0
        editor.cancel(ask=False)
    finally:
        win.close()


def test_each_paragraph_keeps_its_own_indents(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    win = _editor_window(qapp)
    try:
        editor = _open_new_editor(win, qapp)
        QTest.keyClicks(editor.edit, "primero")
        editor.apply_paragraph_props(left=2.0)
        QTest.keyClick(editor.edit, Qt.Key_Return)
        QTest.keyClicks(editor.edit, "segundo")
        editor.apply_paragraph_props(left=0.0)   # back to the margin
        editor.commit()
        qapp.processEvents()
        made = [e for e in win.document.modelspace()
                if e.dxftype() == "MTEXT"][0]
        from core.mtext_format import parse_runs

        paragraphs = parse_runs(made.text, 2.5)
        assert paragraphs[0].resolved().left == 2.0
        assert paragraphs[1].resolved().left == 0.0
    finally:
        win.close()


def test_the_width_arrow_changes_the_box_of_a_new_text(qapp):
    from PySide6.QtTest import QTest

    win = _editor_window(qapp)
    try:
        editor = _open_new_editor(win, qapp)
        QTest.keyClicks(editor.edit, "ancho nuevo")
        scale = editor._scale()
        editor.set_width_px(40.0 * scale)        # drag to 40 units
        editor.commit()
        qapp.processEvents()
        made = [e for e in win.document.modelspace()
                if e.dxftype() == "MTEXT"][0]
        assert made.dxf.width == pytest.approx(40.0, rel=1e-6)
    finally:
        win.close()


def test_the_width_arrow_resizes_an_existing_text(qapp):
    win = _editor_window(qapp)
    try:
        mtext = win.document.modelspace().add_mtext(
            "nota para angostar", dxfattribs={"char_height": 2.5,
                                              "width": 80.0})
        mtext.set_location((10.0, 40.0))
        win.tools.index.invalidate()
        win.tools.index._build()
        win.on_canvas_double_click(11.0, 39.0)
        qapp.processEvents()
        editor = win.tools._mtext_editor
        editor.set_width_px(30.0 * editor._scale())
        editor.commit()
        qapp.processEvents()
        assert mtext.dxf.width == pytest.approx(30.0, rel=1e-6)
        win.history.undo()
        assert mtext.dxf.width == pytest.approx(80.0)
    finally:
        win.close()


def test_double_click_on_the_width_arrow_fits_the_box(qapp):
    from PySide6.QtTest import QTest

    win = _editor_window(qapp)
    try:
        editor = _open_new_editor(win, qapp)
        QTest.keyClicks(editor.edit, "corto")
        editor.fit_width()
        editor.commit()
        qapp.processEvents()
        made = [e for e in win.document.modelspace()
                if e.dxftype() == "MTEXT"][0]
        # The 80-unit drag box shrank to hug the word.
        assert made.dxf.width < 30.0
    finally:
        win.close()


def test_tab_characters_round_trip_through_the_stream(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    win = _editor_window(qapp)
    try:
        editor = _open_new_editor(win, qapp)
        editor.apply_paragraph_props(tab_stops=(4.0,))
        QTest.keyClicks(editor.edit, "N")
        QTest.keyClick(editor.edit, Qt.Key_Tab)
        QTest.keyClicks(editor.edit, "1050")
        editor.commit()
        qapp.processEvents()
        made = [e for e in win.document.modelspace()
                if e.dxftype() == "MTEXT"][0]
        assert made.text == "\\pxi0,l0,r0,t4;N\t1050"
    finally:
        win.close()


# -- line spacing and lists (the last of the editor plan) ----------------------

def test_line_spacing_reaches_the_entity_and_comes_back(qapp):
    from PySide6.QtTest import QTest

    win = _editor_window(qapp)
    try:
        editor = _open_new_editor(win, qapp)
        QTest.keyClicks(editor.edit, "espaciado")
        editor._set_line_spacing(1.5)
        editor.commit()
        qapp.processEvents()
        made = [e for e in win.document.modelspace()
                if e.dxftype() == "MTEXT"][0]
        assert made.dxf.line_spacing_factor == pytest.approx(1.5)
        assert made.dxf.line_spacing_style == 1        # "At least"

        # Reopening shows the factor, and leaving it alone changes nothing.
        win.tools.index.invalidate()
        win.tools.index._build()
        win.on_canvas_double_click(11.0, 39.0)
        qapp.processEvents()
        second = win.tools._mtext_editor
        assert second._line_spacing == pytest.approx(1.5)
        assert second.spacing.text() == "1.5x"
        assert second._extras()["line_spacing"] is None
        second.cancel(ask=False)
    finally:
        win.close()


def test_the_lists_menu_writes_literal_markers_and_hanging_indents(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    win = _editor_window(qapp)
    try:
        editor = _open_new_editor(win, qapp)
        QTest.keyClicks(editor.edit, "concreto")
        QTest.keyClick(editor.edit, Qt.Key_Return)
        QTest.keyClicks(editor.edit, "acero")
        cursor = editor.edit.textCursor()
        cursor.select(cursor.SelectionType.Document)
        editor.edit.setTextCursor(cursor)
        editor._apply_list("number")
        editor.commit()
        qapp.processEvents()
        made = [e for e in win.document.modelspace()
                if e.dxftype() == "MTEXT"][0]
        # Literal markers + the hanging indent codes: AutoCAD's construction.
        assert made.text == ("\\pxi-2,l2,r0,t2;1.\tconcreto\\P2.\tacero")
    finally:
        win.close()


def test_enter_continues_the_numbering(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    win = _editor_window(qapp)
    try:
        editor = _open_new_editor(win, qapp)
        QTest.keyClicks(editor.edit, "1.")
        QTest.keyClick(editor.edit, Qt.Key_Tab)       # autolist trigger
        QTest.keyClicks(editor.edit, "primero")
        QTest.keyClick(editor.edit, Qt.Key_Return)    # continues as 2.
        QTest.keyClicks(editor.edit, "segundo")
        QTest.keyClick(editor.edit, Qt.Key_Return)
        QTest.keyClick(editor.edit, Qt.Key_Return)    # empty item: list ends
        QTest.keyClicks(editor.edit, "parrafo normal")
        editor.commit()
        qapp.processEvents()
        made = [e for e in win.document.modelspace()
                if e.dxftype() == "MTEXT"][0]
        from core.mtext_format import parse_runs

        paragraphs = parse_runs(made.text, 2.5)
        texts = ["".join(r.text for r in p.runs) for p in paragraphs]
        assert texts[0] == "1.\tprimero"
        assert texts[1] == "2.\tsegundo"
        assert texts[2] == "parrafo normal"
        # And the closing paragraph went back to the margin.
        assert paragraphs[2].resolved().left == 0.0
        assert paragraphs[0].resolved().left == 2.0
    finally:
        win.close()


def test_a_dash_and_tab_starts_a_bulleted_list(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from core.mtext_lists import BULLET

    win = _editor_window(qapp)
    try:
        editor = _open_new_editor(win, qapp)
        QTest.keyClicks(editor.edit, "-")
        QTest.keyClick(editor.edit, Qt.Key_Tab)
        QTest.keyClicks(editor.edit, "punto uno")
        editor.commit()
        qapp.processEvents()
        made = [e for e in win.document.modelspace()
                if e.dxftype() == "MTEXT"][0]
        assert BULLET + "\tpunto uno" in made.text
    finally:
        win.close()


def test_lists_off_strips_markers_and_indents(qapp):
    from PySide6.QtTest import QTest

    win = _editor_window(qapp)
    try:
        mtext = win.document.modelspace().add_mtext(
            "\\pxi-2,l2,t2;1.\tuno\\P2.\tdos",
            dxfattribs={"char_height": 2.5, "width": 60.0})
        mtext.set_location((10.0, 40.0))
        win.tools.index.invalidate()
        win.tools.index._build()
        win.on_canvas_double_click(11.0, 39.0)
        qapp.processEvents()
        editor = win.tools._mtext_editor
        assert editor.rich
        cursor = editor.edit.textCursor()
        cursor.select(cursor.SelectionType.Document)
        editor.edit.setTextCursor(cursor)
        editor._apply_list(None)
        editor.commit()
        qapp.processEvents()
        assert mtext.text == "uno\\Pdos"
    finally:
        win.close()


# -- background mask and static columns ----------------------------------------

def test_the_mask_lands_on_the_entity_with_its_scale(qapp):
    from PySide6.QtTest import QTest

    win = _editor_window(qapp)
    try:
        editor = _open_new_editor(win, qapp)
        QTest.keyClicks(editor.edit, "NOTA IMPORTANTE")
        editor._bg = (2, 1.8)                    # yellow, factor 1.8
        editor.commit()
        qapp.processEvents()
        made = [e for e in win.document.modelspace()
                if e.dxftype() == "MTEXT"][0]
        assert made.dxf.bg_fill == 1
        assert made.dxf.bg_fill_color == 2
        assert made.dxf.box_fill_scale == pytest.approx(1.8)
    finally:
        win.close()


def test_the_canvas_colour_mask_and_its_removal(qapp):
    win = _editor_window(qapp)
    try:
        mtext = win.document.modelspace().add_mtext(
            "tapado", dxfattribs={"char_height": 2.5, "width": 40.0})
        mtext.set_location((10.0, 40.0))
        mtext.set_bg_color("canvas", scale=2.0)
        win.tools.index.invalidate()
        win.tools.index._build()
        win.on_canvas_double_click(11.0, 39.0)
        qapp.processEvents()
        editor = win.tools._mtext_editor
        # The editor reads the existing mask...
        assert editor._current_bg() == ("canvas", 2.0)
        # ...and turning it off removes the attributes.
        editor._bg = ("off",)
        editor.commit()
        qapp.processEvents()
        assert not mtext.dxf.hasattr("bg_fill")
        win.history.undo()
        assert mtext.dxf.bg_fill == 3            # canvas = bits 0+1
    finally:
        win.close()


def test_static_columns_land_and_round_trip(qapp):
    from PySide6.QtTest import QTest

    win = _editor_window(qapp)
    try:
        editor = _open_new_editor(win, qapp)
        QTest.keyClicks(editor.edit, "texto largo " * 20)
        editor._set_columns((3, 60.0, 12.5))
        editor.commit()
        qapp.processEvents()
        made = [e for e in win.document.modelspace()
                if e.dxftype() == "MTEXT"][0]
        assert made.has_columns
        assert made.columns.count == 3
        assert made.columns.gutter_width == pytest.approx(12.5)

        # Reopen: the editor knows the layout; removing it clears the entity.
        win.tools.index.invalidate()
        win.tools.index._build()
        win.on_canvas_double_click(11.0, 39.0)
        qapp.processEvents()
        second = win.tools._mtext_editor
        assert getattr(second, "_initial_columns", None) is not None
        second._set_columns(None)
        second.commit()
        qapp.processEvents()
        assert not made.has_columns
        win.history.undo()
        assert made.has_columns and made.columns.count == 3
    finally:
        win.close()


def test_columns_survive_the_dxf_round_trip(qapp, tmp_path):
    import ezdxf

    win = _editor_window(qapp)
    try:
        from core import actions

        win.history.execute(actions.add_mtext(
            (0, 40), (40, 0), "flujo " * 30, 2.5, columns=(3, 60.0, 12.5)))
        path = tmp_path / "columnas.dxf"
        win.document.save_as(path)
        again = ezdxf.readfile(path)
        mtext = [e for e in again.modelspace() if e.dxftype() == "MTEXT"][0]
        assert mtext.has_columns and mtext.columns.count == 3
    finally:
        win.close()


def test_a_masked_plain_mtext_renders_its_fill(qapp):
    """The ezdxf frontend only draws the mask via its complex renderer; the
    patch routes bg_fill there. Without it the mask shows in AutoCAD and
    not on our canvas — the silent kind of wrong."""
    from core.document import Document
    from render.backend import build_scene

    document = Document.new()
    mtext = document.modelspace().add_mtext(
        "NOTA", dxfattribs={"char_height": 2.5, "width": 20})
    mtext.set_location((0, 0))
    bare = len(build_scene(document).triangles.data)
    mtext.set_bg_color(2, scale=1.5)
    masked = len(build_scene(document).triangles.data)
    assert masked > bare, "the mask fill did not reach the canvas"


def test_column_width_divides_the_box_not_multiplies_it(qapp):
    """3 columns of an 80-wide box must fit in 80, not become 240."""
    win = _editor_window(qapp)
    try:
        from core import actions

        win.history.execute(actions.add_mtext(
            (0, 40), (80, 0), "flujo " * 30, 2.5, columns=(3, 30.0, 4.0)))
        made = [e for e in win.document.modelspace()
                if e.dxftype() == "MTEXT"][0]
        columns = made.columns
        total = columns.count * columns.width \
            + (columns.count - 1) * columns.gutter_width
        assert total == pytest.approx(80.0, rel=1e-6)
    finally:
        win.close()


def test_a_masked_text_survives_the_lod_cull(qapp):
    """The mask quad carries no glyph-height metric; culling only where the
    metric exists — otherwise the mask vanished at EVERY zoom while its
    text drew, the silent kind of wrong."""
    import numpy as np

    from core.document import Document
    from render.backend import build_scene
    from views.viewport import MIN_TEXT_PX

    document = Document.new()
    mtext = document.modelspace().add_mtext(
        "NOTA", dxfattribs={"char_height": 2.5, "width": 20})
    mtext.set_location((0, 0))
    mtext.set_bg_color(2, scale=1.5)
    scene = build_scene(document)
    batch = scene.triangles
    runs = batch.visible_runs((-100, -100, 100, 100), 10.0, MIN_TEXT_PX)
    drawn = sum(count for _first, count in runs)
    assert drawn == len(batch.data), "some triangles were culled at a zoom " \
        "where everything is legible"
    # And the yellow quad is among what draws (first range starts at 0).
    assert runs[0][0] == 0


def test_the_caret_is_visible_the_moment_the_editor_opens(qapp):
    """The empty editor opened one line short: the first geometry pass ran
    with the pre-zoom font and the caret sat below the visible area —
    typing worked and showed nothing until the anchor timer's next tick."""
    win = _editor_window(qapp)
    try:
        for zoom in (1.0, 2.0, 4.0):
            win.viewport.view.scale = 5.0 * zoom
            win.dispatcher.submit("MTEXT")
            win.tools.tool.on_point((10.0, 40.0))
            win.tools.tool.on_point((90.0, 10.0))
            qapp.processEvents()
            editor = win.tools._mtext_editor
            caret = editor.edit.cursorRect()
            viewport = editor.edit.viewport().rect()
            assert viewport.contains(caret.topLeft()) \
                and viewport.contains(caret.bottomLeft()), \
                f"caret {caret.top()}..{caret.bottom()} clipped in " \
                f"0..{viewport.height()} at zoom {zoom}"
            editor.cancel(ask=False)
            qapp.processEvents()
    finally:
        win.close()


def test_the_editor_shows_a_pointer_over_its_chrome(qapp):
    """The viewport blanks the OS cursor (the crosshair is the cursor), and
    child widgets inherit that: the toolbar and ruler were operated with an
    invisible pointer."""
    from PySide6.QtCore import Qt

    win = _editor_window(qapp)
    try:
        editor = _open_new_editor(win, qapp)
        assert editor.cursor().shape() == Qt.ArrowCursor
        assert editor.ruler.cursor().shape() == Qt.SizeHorCursor
        # And the canvas itself keeps its blank cursor for the crosshair.
        assert win.viewport.cursor().shape() == Qt.BlankCursor
        editor.cancel(ask=False)
    finally:
        win.close()


# -- the unsaved-changes prompt (AutoCAD's CLOSE rule) -------------------------

def test_a_clean_drawing_closes_without_asking(qapp, monkeypatch):
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox

    win = _editor_window(qapp)
    try:
        monkeypatch.setattr(QMessageBox, "warning",
                            lambda *a, **k: pytest.fail("asked on a clean doc"))
        event = QCloseEvent()
        win.closeEvent(event)
        assert event.isAccepted()
    finally:
        win.close()


def test_a_dirty_drawing_asks_and_cancel_keeps_it_open(qapp, monkeypatch):
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox

    win = _editor_window(qapp)
    try:
        win.document.dirty = True
        monkeypatch.setattr(QMessageBox, "warning",
                            lambda *a, **k: QMessageBox.Cancel)
        event = QCloseEvent()
        win.closeEvent(event)
        assert not event.isAccepted()
        assert win.document.dirty
    finally:
        win.document.dirty = False
        win.close()


def test_discard_closes_without_saving(qapp, monkeypatch):
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox

    win = _editor_window(qapp)
    try:
        win.document.dirty = True
        monkeypatch.setattr(QMessageBox, "warning",
                            lambda *a, **k: QMessageBox.Discard)
        event = QCloseEvent()
        win.closeEvent(event)
        assert event.isAccepted()
    finally:
        win.document.dirty = False
        win.close()


def test_save_writes_the_file_and_then_closes(qapp, monkeypatch, tmp_path):
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox

    win = _editor_window(qapp)
    try:
        target = tmp_path / "obra.dxf"
        win.document.save_as(target)          # give it a home first
        win.document.dirty = True
        monkeypatch.setattr(QMessageBox, "warning",
                            lambda *a, **k: QMessageBox.Save)
        event = QCloseEvent()
        win.closeEvent(event)
        assert event.isAccepted()
        assert target.exists() and not win.document.dirty
    finally:
        win.close()


def test_a_cancelled_save_as_keeps_the_window_open(qapp, monkeypatch):
    """Save on an unnamed drawing opens Save As; cancelling THAT must also
    cancel the close — otherwise the work is lost through the back door."""
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    win = _editor_window(qapp)
    try:
        win.document.dirty = True
        monkeypatch.setattr(QMessageBox, "warning",
                            lambda *a, **k: QMessageBox.Save)
        monkeypatch.setattr(QFileDialog, "getSaveFileName",
                            lambda *a, **k: ("", ""))
        event = QCloseEvent()
        win.closeEvent(event)
        assert not event.isAccepted()
    finally:
        win.document.dirty = False
        win.close()


def test_open_and_new_are_guarded_too(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    win = _editor_window(qapp)
    try:
        win.document.dirty = True
        doc = win.document
        monkeypatch.setattr(QMessageBox, "warning",
                            lambda *a, **k: QMessageBox.Cancel)
        win.new_document("mm")
        assert win.document is doc            # Cancel kept the drawing
        win.open_path(Path("no-importa.dxf"))
        assert win.document is doc
    finally:
        win.document.dirty = False
        win.close()


# -- SPLINE (the Fit method) ---------------------------------------------------

def test_spline_places_fit_points_until_enter(qapp):
    win = _editor_window(qapp)
    try:
        win.dispatcher.submit("SPLINE")
        for p in ((0.0, 0.0), (10.0, 6.0), (20.0, -4.0), (30.0, 3.0)):
            win.tools.tool.on_point(p)
        win.tools.tool.on_enter()
        splines = win.document.modelspace().query("SPLINE")
        assert len(splines) == 1
        assert len(splines[0].fit_points) == 4
        win._cmd_undo()
        assert len(win.document.modelspace().query("SPLINE")) == 0
    finally:
        win.document.dirty = False
        win.close()


def test_spline_close_and_undo_options(qapp):
    win = _editor_window(qapp)
    try:
        win.dispatcher.submit("SPLINE")
        tool = win.tools.tool
        for p in ((0.0, 0.0), (10.0, 6.0), (20.0, -4.0), (99.0, 99.0)):
            tool.on_point(p)
        assert tool.on_option("U")            # drop the stray point
        assert tool.on_option("C")            # close with 3 left
        spline = win.document.modelspace().query("SPLINE")[0]
        fit = spline.fit_points
        assert len(fit) == 4                  # first point appended
        assert tuple(fit[-1])[:2] == tuple(fit[0])[:2]
    finally:
        win.document.dirty = False
        win.close()


def test_spline_preview_is_a_smooth_polyline(qapp):
    win = _editor_window(qapp)
    try:
        win.dispatcher.submit("SPLINE")
        tool = win.tools.tool
        tool.on_point((0.0, 0.0))
        tool.on_point((10.0, 8.0))
        segments = tool.preview_segments((20.0, 0.0))
        assert len(segments) > 5              # flattened curve, not 2 chords
    finally:
        win.tools.cancel()
        win.document.dirty = False
        win.close()
