# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Annotative scaling, read as AutoCAD stores it and drawn per space.

Rafael (review 4): texts and arrows must measure the same ON PAPER in every
viewport, whatever its scale. That is AutoCAD's annotative scaling: the
object carries one representation per annotation scale, model space shows
CANNOSCALE's, each viewport shows its own scale's. These tests build the
data with core.annotative's writer (checked separately against ODA) and
measure what build_scene actually draws.
"""
from __future__ import annotations

import ezdxf
import numpy as np
import pytest

from core import annotative as A


def _drawing(cannoscale: str = "1:50"):
    doc = ezdxf.new("R2018")
    s50 = A.ensure_scale(doc, "1:50", 1.0, 50.0)
    s100 = A.ensure_scale(doc, "1:100", 1.0, 100.0)
    text = doc.modelspace().add_text(
        "LOTE 7", dxfattribs={"insert": (10.0, 20.0), "height": 125.0})
    A.add_representation(text, s50, default=True)
    A.add_representation(text, s100, default=False,
                         layout={10: 400.0, 11: 400.0})
    A.set_current_scale(doc, s50 if cannoscale == "1:50" else s100)
    return doc, text, s50, s100


# -- the model, read back --------------------------------------------------------

def test_reader_finds_scales_flag_and_representations(tmp_path):
    doc, text, s50, s100 = _drawing("1:100")
    doc.saveas(tmp_path / "a.dxf")
    back = ezdxf.readfile(tmp_path / "a.dxf")
    t = back.modelspace().query("TEXT")[0]
    assert A.is_annotative(t)
    assert [s.name for s in A.scale_list(back)] == ["1:50", "1:100"]
    assert A.current_scale(back).name == "1:100"
    reps = {r.scale.name: r for r in A.representations(t)}
    assert reps["1:50"].is_default and not reps["1:100"].is_default
    assert A.scale_list(back)[1].factor == 100.0


def test_the_flag_is_the_value_not_the_presence():
    doc, text, *_ = _drawing()
    A.set_annotative(text, False)
    assert not A.is_annotative(text)
    assert A.representation_for(text, A.find_scale(doc, "1:100")) is None


def test_picking_the_representation():
    doc, text, s50, s100 = _drawing()
    assert A.representation_for(text, s50) is None           # the default
    rep = A.representation_for(text, s100)
    assert rep.scale.name == "1:100"
    s200 = A.ensure_scale(doc, "1:200", 1.0, 200.0)
    assert A.representation_for(text, s200, show_all=True) is None
    assert A.representation_for(text, s200, show_all=False) is A.HIDDEN


def test_a_representation_is_the_entity_at_that_scale():
    doc, text, s50, s100 = _drawing()
    virtual = A.virtual_representation(text, A.representation_for(text, s100))
    assert virtual.dxf.height == pytest.approx(250.0)   # 125 x 100/50
    assert tuple(virtual.dxf.insert)[:2] == (400.0, 20.0)
    assert virtual.dxf.handle == text.dxf.handle        # picking follows
    assert virtual.doc is doc and text.dxf.height == 125.0


# -- what is drawn ---------------------------------------------------------------

def _points(scene, handle, x_min=-np.inf, x_max=np.inf):
    """Every vertex the scene draws for ``handle`` (world or sheet units),
    optionally only those between x_min and x_max -- one viewport's copy."""
    parts = [getattr(scene, batch).data["pos"][first:first + count].astype(float)
             for batch, first, count in scene.handle_ranges.get(handle, [])]
    if not parts:
        return np.empty((0, 2))
    pos = np.concatenate(parts) + np.array(scene.origin)
    return pos[(pos[:, 0] >= x_min) & (pos[:, 0] <= x_max)]


def _box(scene, handle, x_min=-np.inf, x_max=np.inf):
    pos = _points(scene, handle, x_min, x_max)
    if not len(pos):
        return None
    return (pos[:, 0].min(), pos[:, 1].min(), pos[:, 0].max(), pos[:, 1].max())


def test_model_space_shows_cannoscales_representation():
    from core.document import Document
    from render.backend import build_scene

    doc, text, *_ = _drawing("1:50")
    at50 = _box(build_scene(Document(doc), "Model"), text.dxf.handle)
    A.set_current_scale(doc, A.find_scale(doc, "1:100"))
    at100 = _box(build_scene(Document(doc), "Model"), text.dxf.handle)
    h50, h100 = at50[3] - at50[1], at100[3] - at100[1]
    assert h100 == pytest.approx(2 * h50, rel=0.02)
    # each at its own position (the first glyph starts a side bearing in)
    assert 10.0 <= at50[0] < 10.0 + 0.2 * 125
    assert 400.0 <= at100[0] < 400.0 + 0.2 * 250


def test_annoallvisible_off_hides_what_the_scale_does_not_carry():
    from core.document import Document
    from render.backend import build_scene

    doc, text, *_ = _drawing()
    A.set_current_scale(doc, A.ensure_scale(doc, "1:200", 1.0, 200.0))
    assert _box(build_scene(Document(doc), "Model"), text.dxf.handle)
    A.set_all_visible(doc.modelspace(), False)
    assert _box(build_scene(Document(doc), "Model"), text.dxf.handle) is None


def test_the_same_paper_size_in_viewports_at_different_scales(tmp_path):
    """The whole point: 1:50 and 1:100 viewports, the text 2.5 mm in both."""
    from core.document import Document
    from render.backend import build_scene

    doc, text, s50, s100 = _drawing()
    sheet = doc.layouts.new("A1")
    # 1:50 on the left, looking at the 1:50 representation...
    left = sheet.add_viewport(center=(60, 50), size=(100, 60),
                              view_center_point=(150, 60), view_height=3000)
    A.set_viewport_scale(left, s50)
    # ...1:100 on the right, looking at the 1:100 one
    right = sheet.add_viewport(center=(200, 50), size=(100, 60),
                               view_center_point=(700, 60), view_height=6000)
    A.set_viewport_scale(right, s100)
    doc.saveas(tmp_path / "sheet.dxf")         # through the file, as it opens
    document = Document(ezdxf.readfile(tmp_path / "sheet.dxf"))
    scene = build_scene(document, "A1")
    in_left = _box(scene, text.dxf.handle, 10, 110)
    in_right = _box(scene, text.dxf.handle, 150, 250)
    assert in_left and in_right
    h_left = in_left[3] - in_left[1]
    h_right = in_right[3] - in_right[1]
    assert h_right == pytest.approx(h_left, rel=0.02)
    # and it is the paper size: 125 model units at 1:50 = 2.5 mm, of which
    # the capitals take most
    assert 1.5 < h_left < 2.6


def test_a_viewport_at_another_annotation_scale_keeps_the_bake(qapp):
    """The live pan tessellates the model once, at CANNOSCALE; a viewport
    showing annotations at another scale stays on the baked path, which
    draws each viewport's own representations."""
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        win.new_document("mm")
        doc = win.document.doc
        s50 = A.ensure_scale(doc, "1:50", 1.0, 50.0)
        s100 = A.ensure_scale(doc, "1:100", 1.0, 100.0)
        A.set_current_scale(doc, s50)
        psp = doc.layouts.get("Layout1")
        vp = psp.add_viewport(center=(100, 70), size=(160, 100),
                              view_center_point=(50, 25), view_height=60)
        win._active_layout = "Layout1"
        A.set_viewport_scale(vp, s100)
        assert win._vp_placement(vp) is not None     # nothing annotative yet

        text = doc.modelspace().add_text("P1", dxfattribs={"height": 125})
        A.add_representation(text, s50, default=True)
        win.document.revision += 1
        assert win._vp_placement(vp) is None
        A.set_viewport_scale(vp, s50)                 # CANNOSCALE's: live again
        assert win._vp_placement(vp) is not None
    finally:
        win.document.dirty = False
        win.close()


def test_save_as_dwg_warns_only_for_scales_it_cannot_keep(tmp_path):
    """The bundled LibreDWG keeps text and dimension scale representations
    since the vendor patch of 2026-10-10 (they come back from the DWG,
    checked in test_annotative_viewports): a save of those says nothing.
    Kinds not proven yet -- a colleague's annotative blocks, multileaders --
    still warn, and nothing is said when there is nothing to lose."""
    from core.document import Document, _survives_dwg
    from formats.dwg_bridge import find_dxf2dwg

    if find_dxf2dwg() is None:
        pytest.skip("LibreDWG not available")
    doc, *_ = _drawing()
    _engine, warnings = Document(doc).save_as(tmp_path / "multi.dwg")
    assert not any("annotative" in w for w in warnings), warnings

    plain = ezdxf.new("R2018")
    plain.modelspace().add_line((0, 0), (1, 1))
    _engine, warnings = Document(plain).save_as(tmp_path / "plain.dwg")
    assert not any("annotative" in w for w in warnings)

    block = plain.blocks.new("B")
    block.add_line((0, 0), (1, 0))
    insert = plain.modelspace().add_blockref("B", (0, 0))
    assert not _survives_dwg(insert)
    text = plain.modelspace().add_text("x")
    assert _survives_dwg(text)
