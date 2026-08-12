# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""IMAGEATTACH: the IMAGE entity, its scene quad, and the undo path."""
from __future__ import annotations

import numpy as np
import PIL.Image
import pytest

from core import actions
from core.commands import History
from core.document import Document
from render.backend import build_scene


@pytest.fixture()
def image_file(tmp_path):
    path = tmp_path / "plano escaneado.png"   # accents/spaces on purpose
    arr = np.zeros((40, 60, 3), np.uint8)
    arr[:20, :, 0] = 255
    PIL.Image.fromarray(arr).save(path)
    return path


def test_attach_creates_a_referenced_image_with_scale(image_file):
    doc = Document.new()
    history = History(doc)
    history.execute(actions.attach_image(str(image_file), (60, 40),
                                         (100.0, 50.0), 2.0))
    image = doc.modelspace().query("IMAGE")[0]
    assert image.image_def.dxf.filename == str(image_file)
    history.undo()
    assert len(doc.modelspace().query("IMAGE")) == 0
    history.redo()
    assert len(doc.modelspace().query("IMAGE")) == 1


def test_the_scene_carries_the_pixels_and_the_quad(image_file):
    doc = Document.new()
    History(doc).execute(actions.attach_image(str(image_file), (60, 40),
                                              (100.0, 50.0), 2.0))
    scene = build_scene(doc)
    assert len(scene.images) == 1
    img = scene.images[0]
    assert img.pixels.shape == (40, 60, 4)
    # scale 2: 120 x 80 world units, and zoom-extents covers it
    xs = img.corners[:, 0]
    ys = img.corners[:, 1]
    assert float(xs.max() - xs.min()) == pytest.approx(120.0)
    assert float(ys.max() - ys.min()) == pytest.approx(80.0)
    assert scene.extents == pytest.approx((100.0, 50.0, 220.0, 130.0))
    # the frontend drew the frame, so pick/hide work through the batches
    handle = doc.modelspace().query("IMAGE")[0].dxf.handle
    assert handle in scene.handle_ranges
    assert img.handle == handle


def test_an_image_only_drawing_still_has_extents(image_file):
    """Empty vector scene + one image: origin and extents come from it."""
    doc = Document.new()
    History(doc).execute(actions.attach_image(str(image_file), (60, 40),
                                              (0.0, 0.0), 1.0))
    scene = build_scene(doc)
    assert scene.extents[2] > scene.extents[0]


def test_a_missing_file_shows_frame_and_name_not_a_crash(tmp_path):
    doc = Document.new()
    History(doc).execute(actions.attach_image(
        str(tmp_path / "no-existe.png"), (60, 40), (0.0, 0.0), 1.0))
    scene = build_scene(doc)
    assert scene.images == []          # nothing to texture...
    handle = doc.modelspace().query("IMAGE")[0].dxf.handle
    assert handle in scene.handle_ranges   # ...but the frame is there


def test_attach_image_demands_a_real_regen(image_file):
    """The incremental overlay cannot show pixels; without a regen the
    attached image never appeared on screen (the reported bug). The
    controller routes needs_regen commands to regen_in_memory, so the
    contract to pin is the flag itself."""
    command = actions.attach_image(str(image_file), (60, 40), (0.0, 0.0), 1.0)
    assert getattr(command, "needs_regen", False) is True


# -- grips, adjust, transparency ----------------------------------------------

def _attached(image_file, scale=1.0):
    doc = Document.new()
    history = History(doc)
    history.execute(actions.attach_image(str(image_file), (60, 40),
                                         (100.0, 50.0), scale))
    return doc, history, doc.modelspace().query("IMAGE")[0]


def test_an_image_has_four_corner_grips(image_file):
    from core.select import entity_grips

    _doc, _h, image = _attached(image_file)
    grips = entity_grips(image)
    assert len(grips) == 4
    assert all(role == "corner" for _x, _y, role in grips)
    xs = sorted({round(x, 6) for x, _y, _r in grips})
    ys = sorted({round(y, 6) for _x, y, _r in grips})
    assert xs == [100.0, 160.0] and ys == [50.0, 90.0]


def test_dragging_a_corner_scales_about_the_opposite_one(image_file):
    from core.select import apply_grip_edit, entity_grips

    _doc, _h, image = _attached(image_file)
    grips = entity_grips(image)
    # find the corner at (160, 90); its opposite is (100, 50)
    index = next(i for i, (x, y, _r) in enumerate(grips)
                 if round(x) == 160 and round(y) == 90)
    # drag outward along the diagonal to double the size
    assert apply_grip_edit(image, index, "corner", (220.0, 130.0))
    grips = entity_grips(image)
    xs = sorted({round(x, 4) for x, _y, _r in grips})
    ys = sorted({round(y, 4) for _x, y, _r in grips})
    assert xs == [100.0, 220.0] and ys == [50.0, 130.0]   # fixed corner held


def test_a_collapsing_drag_is_refused(image_file):
    from core.select import apply_grip_edit, entity_grips

    _doc, _h, image = _attached(image_file)
    grips_before = entity_grips(image)
    assert not apply_grip_edit(image, 0, "corner",
                               entity_grips(image)[2][:2])   # onto opposite
    assert entity_grips(image) == grips_before


def test_imageadjust_writes_values_with_undo(image_file):
    from core.image_ops import ImageAdjustCommand

    doc, history, image = _attached(image_file)
    history.execute(ImageAdjustCommand([image], fade=80))
    assert image.dxf.fade == 80
    assert getattr(ImageAdjustCommand([image]), "needs_regen") is True
    history.undo()
    assert image.dxf.fade == 0
    history.redo()
    assert image.dxf.fade == 80


def test_transparency_toggles_the_flag_with_undo(image_file):
    from ezdxf.entities.image import Image

    from core.image_ops import ImageTransparencyCommand

    doc, history, image = _attached(image_file)
    before = int(image.dxf.flags)
    history.execute(ImageTransparencyCommand([image], True))
    assert image.dxf.flags & Image.USE_TRANSPARENCY
    history.undo()
    assert int(image.dxf.flags) == before


def test_the_properties_panel_exposes_image_display_rows(qapp, image_file):
    """BricsCAD sets image transparency from the Properties panel; ours
    lists the same block: position, size, brightness/contrast/fade,
    transparency, show, file."""
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        win.new_document("mm")
        win.history.execute(actions.attach_image(str(image_file), (60, 40),
                                                 (0.0, 0.0), 1.0))
        image = win.document.modelspace().query("IMAGE")[0]
        win.tools.selection = {image.dxf.handle}
        panel = win._properties_panel
        panel.refresh()                        # adopt the selection
        sections = panel._schema([image])
        titles = [t for t, _rows in sections]
        assert any("Image" in t for t in titles)
        image_rows = next(rows for t, rows in sections if "Image" in t)
        labels = [r.label for r in image_rows]
        for wanted in ("Brightness", "Contrast", "Fade", "Transparency",
                       "Width", "Height"):
            assert any(wanted in l for l in labels), wanted
        # the transparency DEGREE reaches the alpha channel (0-90 %)
        degree = next(r for r in image_rows if r.label == "Transparency %")
        degree.apply(60)
        assert image.transparency == pytest.approx(0.6)
        from render.backend import build_scene
        assert build_scene(win.document).images[0].pixels[0, 0, 3] == 102
        degree.apply(120)                       # clamps to AutoCAD's 90
        assert image.transparency == pytest.approx(0.9, abs=0.005)
        # and the bitonal flag round-trips too
        transparency = next(r for r in image_rows
                            if "Transparent background" in r.label)
        assert transparency.get(image) is False
        transparency.apply(True)
        from ezdxf.entities.image import Image
        assert image.dxf.flags & Image.USE_TRANSPARENCY
        assert getattr(win.history._undo[-1], "needs_regen", False) is True
        win._cmd_undo()
        assert not (image.dxf.flags & Image.USE_TRANSPARENCY)
    finally:
        win.document.dirty = False
        win.close()
