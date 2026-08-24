# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Drawing Window Colors: the model background is the user's choice.

Colleagues want a white or cream model canvas. AutoCAD does this in
Options ▸ Display ▸ Colors (the Drawing Window Colors dialog), and the
choice is more than a clear colour: ACI-7 entities flip to black over a
light canvas and text background masks fill with the canvas colour, both
resolved at tessellation time — so a background change needs a regen and
must reach the render context.
"""
from __future__ import annotations

import ezdxf
import pytest

from core import window_colors
from core.document import Document
from render.backend import build_scene


@pytest.fixture(autouse=True)
def _clean_settings():
    window_colors.restore_all()
    yield
    window_colors.restore_all()


def _doc_with_white_line_and_masked_text():
    doc = ezdxf.new("R2018", setup=True)
    msp = doc.modelspace()
    msp.add_line((0, 0), (100, 50), dxfattribs={"color": 7})
    msp.add_mtext("A\\PB", dxfattribs={"char_height": 5.0, "bg_fill": 3,
                                       "insert": (10.0, 10.0), "color": 7})
    return Document(doc)


def _line_color(scene):
    rng = scene.lines.ranges[0]
    return tuple(int(v) for v in
                 scene.lines.data[rng.first:rng.first + rng.count]["rgba"][0])


def _mask_color(scene):
    for rng, is_t in zip(scene.triangles.ranges, scene.triangles.is_text):
        if not is_t:
            run = scene.triangles.data[rng.first:rng.first + rng.count]
            return tuple(int(v) for v in run["rgba"][0])
    return None


def test_default_canvas_keeps_todays_look():
    scene = build_scene(_doc_with_white_line_and_masked_text())
    assert scene.background == pytest.approx(window_colors.rgba("model"))
    assert _line_color(scene) == (255, 255, 255, 255), (
        "ACI 7 must stay white over the dark default canvas")


def test_white_canvas_flips_aci7_and_masks():
    """The whole point: a colleague's white background, like AutoCAD."""
    window_colors.set_background("model", "#FFFFFF")
    scene = build_scene(_doc_with_white_line_and_masked_text())
    assert scene.background == (1.0, 1.0, 1.0, 1.0)
    assert _line_color(scene) == (0, 0, 0, 255), (
        "ACI 7 must flip to black over a white canvas")
    assert _mask_color(scene) == (255, 255, 255, 255), (
        "the text background mask must fill with the canvas colour")


def test_cream_canvas_counts_as_light():
    window_colors.set_background("model", "#F5F0DC")   # crema
    assert window_colors.is_light("model")
    scene = build_scene(_doc_with_white_line_and_masked_text())
    assert _line_color(scene) == (0, 0, 0, 255)


def test_restore_classic_is_black_model():
    window_colors.set_background("model", "#FFFFFF")
    window_colors.restore_classic()
    assert window_colors.background("model") == "#000000"
    scene = build_scene(_doc_with_white_line_and_masked_text())
    assert _line_color(scene) == (255, 255, 255, 255), (
        "classic black canvas draws ACI 7 white, like old AutoCAD")


def test_restore_all_returns_to_ingecad_defaults():
    window_colors.set_background("model", "#FFFFFF")
    window_colors.set_background("sheet", "#FF0000")
    window_colors.restore_all()
    assert window_colors.background("model") == window_colors.DEFAULTS["model"]
    assert window_colors.background("sheet") == window_colors.DEFAULTS["sheet"]


def test_garbage_in_settings_falls_back_to_default():
    from PySide6.QtCore import QSettings

    QSettings().setValue(window_colors.SETTINGS["model"], "not-a-color")
    assert window_colors.background("model") == window_colors.DEFAULTS["model"]


def test_sheet_desk_is_configurable():
    window_colors.set_background("sheet", "#EEDDCC")
    doc = ezdxf.new("R2018", setup=True)
    doc.layouts.new("Sheet")
    scene = build_scene(Document(doc), layout_name="Sheet")
    assert scene.background == pytest.approx(
        (0xEE / 255, 0xDD / 255, 0xCC / 255, 1.0))


def test_dialog_applies_on_ok_and_reports_changes(qapp):
    from views.window_colors_dialog import WindowColorsDialog

    dialog = WindowColorsDialog()
    dialog._edits[("model", "background")] = "#FFFFFF"
    assert dialog.changed_backgrounds()
    dialog.accept()
    assert window_colors.background("model") == "#FFFFFF"


def test_dialog_classic_button_stages_black(qapp):
    from views.window_colors_dialog import WindowColorsDialog

    dialog = WindowColorsDialog()
    dialog._restore_classic()
    assert dialog._edits[("model", "background")] == "#000000"
    dialog.reject()      # cancel must not write anything
    assert window_colors.background("model") == window_colors.DEFAULTS["model"]
