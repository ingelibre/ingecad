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


def test_attaching_through_the_tool_path_triggers_a_regen(qapp, image_file,
                                                          monkeypatch):
    """The incremental overlay cannot show pixels; without a regen the
    attached image never appeared on screen (the reported bug)."""
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        win.new_document("mm")
        regens = []
        monkeypatch.setattr(win, "regen_in_memory",
                            lambda *a, **k: regens.append(1))
        command = actions.attach_image(str(image_file), (60, 40),
                                       (0.0, 0.0), 1.0)
        win.tools._execute(command)
        assert regens, "attach_image must schedule a real regen"
    finally:
        win.close()
