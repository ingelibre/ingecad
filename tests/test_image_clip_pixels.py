# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A clipped image shows only what its clip boundary keeps.

A third-party plugin cut a clipped image's pixels itself, on the belief
(from a stale docstring) that the render showed the whole picture. It
does not: ezdxf's pipeline turns the removed pixels transparent and the
blend hides them. Pinned here through the open path, so an ezdxf update
or a change in how pixels are captured cannot lose it unseen.
"""
from __future__ import annotations

import numpy as np
import pytest

from tests.test_clipboard import _open


def _plan(tmp_path, boundary=None, inverted=False):
    import ezdxf
    from PIL import Image as PILImage

    png = tmp_path / "scan.png"
    PILImage.fromarray(np.full((50, 100, 3), 200, np.uint8)).save(png)
    doc = ezdxf.new("R2010")
    image_def = doc.add_image_def(filename=str(png), size_in_pixel=(100, 50))
    image = doc.modelspace().add_image(image_def, (0, 0), (10, 5))
    if boundary is not None:
        image.set_boundary_path(boundary)
        if inverted:
            image.dxf.clip_mode = 1
    path = tmp_path / "plano.dxf"
    doc.saveas(path)
    return path


@pytest.fixture
def opened(qapp, tmp_path):
    from views.main_window import MainWindow

    windows = []

    def open_plan(**kwargs):
        win = MainWindow()
        win.maybe_save_changes = lambda: True
        win.show()
        windows.append(win)
        _open(qapp, win, _plan(tmp_path, **kwargs))
        (image,) = win.viewport._scene.images
        return np.asarray(image.pixels)

    yield open_plan
    for win in windows:
        win.document.dirty = False
        win.close()


def _alpha(pixels, x, y):
    return 255 if pixels.shape[2] == 3 else int(pixels[y, x, 3])


TRIANGLE = [(20, 10), (80, 10), (50, 40)]


def test_outside_the_clip_is_transparent(opened):
    pixels = opened(boundary=TRIANGLE)
    assert _alpha(pixels, 50, 15) == 255           # inside the triangle
    assert _alpha(pixels, 5, 45) == 0              # a corner left out
    assert _alpha(pixels, 90, 5) == 0


def test_an_unclipped_image_keeps_every_pixel(opened):
    pixels = opened()
    assert _alpha(pixels, 5, 45) == 255 and _alpha(pixels, 90, 5) == 255


def test_an_inverted_clip_hides_the_inside(opened):
    pixels = opened(boundary=TRIANGLE, inverted=True)
    assert _alpha(pixels, 50, 15) == 0
    assert _alpha(pixels, 5, 45) == 255
