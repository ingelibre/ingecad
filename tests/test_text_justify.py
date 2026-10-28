# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Several texts at once from Properties (#57) and a text's justification
changed without moving it (#77) -- Arthur's two requests."""
from __future__ import annotations

import pytest

from core import actions, text_justify
from core.document import Document
from render.backend import build_scene


def _box(document):
    b = build_scene(document, "Model").triangles.bounds
    return (b[:, 0].min(), b[:, 1].min(), b[:, 2].max(), b[:, 3].max())


@pytest.mark.parametrize("label, name", text_justify.JUSTIFICATIONS)
def test_changing_the_justification_leaves_the_letters_in_place(label, name):
    document = Document.new()
    text = document.modelspace().add_text(
        "Hola gy", height=2.5, dxfattribs={"insert": (10, 5), "rotation": 30})
    before = _box(document)
    text_justify.set_justification(text, name)
    assert text_justify.justification(text) == name
    assert _box(document) == pytest.approx(before, abs=0.01)


@pytest.mark.parametrize("font", ["DejaVuSans.ttf", "LiberationSans-Regular.ttf"])
def test_middle_stays_put_whatever_font_the_style_has(font):
    """The CI box draws "txt" with DejaVu Sans, and MIDDLE moved 0.044 there
    while it held still here: it followed the cap and the descent, the
    renderer centres the lower-case height. Pinned here on named fonts."""
    document = Document.new()
    document.doc.styles.new("SANS", dxfattribs={"font": font})
    text = document.modelspace().add_text(
        "Hola gy", height=2.5,
        dxfattribs={"insert": (10, 5), "rotation": 30, "style": "SANS"})
    before = _box(document)
    text_justify.set_justification(text, "MIDDLE")
    assert _box(document) == pytest.approx(before, abs=0.01)


def _row_combo(panel, label):
    from core.i18n import tr

    tree = panel.tree
    for i in range(tree.topLevelItemCount()):
        section = tree.topLevelItem(i)
        for j in range(section.childCount()):
            item = section.child(j)
            if item.text(0) == tr(label):
                return tree.itemWidget(item, 1)
    raise AssertionError(f"no {label} row")


def test_one_style_and_one_justification_for_several_texts(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document()
    try:
        doc = win.document.doc
        for name in ("ROMANS", "ARIAL"):
            doc.styles.add(name, font="txt.shx")
        for i, style in enumerate(("Standard", "ROMANS", "ARIAL")):
            win.tools._execute(actions.add_text((0, i * 10), f"T{i}", 2.5))
            text = [e for e in doc.modelspace() if e.dxftype() == "TEXT"][-1]
            text.dxf.style = style
        texts = [e for e in doc.modelspace() if e.dxftype() == "TEXT"]
        win.tools.selection = {t.dxf.handle for t in texts}
        panel = win._properties_panel
        panel.refresh()

        style = _row_combo(panel, "Style")
        assert style.currentIndex() == -1                      # *VARIES*
        style.activated.emit(style.findData("ROMANS"))
        assert {t.dxf.style for t in texts} == {"ROMANS"}

        boxes = [_box_of(win.document, t) for t in texts]
        justify = _row_combo(panel, "Justify")
        justify.activated.emit(justify.findData("MIDDLE_CENTER"))
        assert {text_justify.justification(t) for t in texts} == {"MIDDLE_CENTER"}
        assert [c for t in texts for c in _box_of(win.document, t)] == pytest.approx(
            [c for box in boxes for c in box], abs=0.01)
        win._cmd_undo()
        assert {text_justify.justification(t) for t in texts} == {"LEFT"}
    finally:
        win.document.dirty = False
        win.close()


def _box_of(document, text):
    x, y = text_justify.baseline_start(text)
    return (round(x, 4), round(y, 4))
