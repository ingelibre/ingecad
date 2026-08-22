# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A new dimension must appear at once, not after a full scene rebuild.

Marco hit this dogfooding: on a real 5406-entity plan, DIMLINEAR drew the
right dimension but it took **2.3 to 2.9 seconds to show up**. Creating it
costs 1-2 ms; all the rest was `regen_in_memory()` re-tessellating the whole
drawing to display one new entity.

The controller forced that regen on purpose, with the comment that "a
dimension renders into an anonymous block ... the overlay can't show it". That
stopped being true when block content started being attributed to the
outermost entity carrying a handle (v0.1.3): the overlay draws a DIMENSION
through the same ezdxf frontend the base scene uses.

These tests pin the two halves of that: the overlay really can draw one, and
the controller really lets it.
"""
from __future__ import annotations

import time

import ezdxf

BATCHES = ("lines", "thick", "triangles", "points")


def _vertices(scene) -> int:
    return 0 if scene is None else sum(len(getattr(scene, b).data)
                                       for b in BATCHES)


def _wait_regen(qapp, win, timeout_s=20.0):
    t0 = time.monotonic()
    while win._regen_worker is not None and time.monotonic() - t0 < timeout_s:
        qapp.processEvents()


def test_the_overlay_can_draw_a_dimension() -> None:
    """The property the whole fix rests on, at the lowest level.

    If ezdxf or the backend ever stops rendering a DIMENSION through
    ``draw_entities``, this fails here rather than as a mysterious blank
    dimension in the application.
    """
    from core import actions
    from core.commands import History
    from core.document import Document
    from render.backend import build_scene_for_entities

    document = Document(ezdxf.new(setup=True))
    command = actions.dim_linear((0, 0), (100, 0), (50, 25))
    History(document).execute(command)

    scene = build_scene_for_entities(document, [command.dim], 0.01)
    assert _vertices(scene) > 100, "the overlay drew nothing for the dimension"
    # ...and every vertex is attributed to the dimension, so hide/undo can
    # find it: the anonymous *D block content must not be ownerless.
    assert set(scene.handle_ranges) == {command.dim.dxf.handle}


def test_creating_a_dimension_does_not_force_a_full_regen(qapp) -> None:
    from views.main_window import MainWindow
    from core import actions

    win = MainWindow()
    win.new_document()
    doc = win.document
    for i in range(40):                      # a base scene worth rebuilding
        doc.doc.modelspace().add_line((i, 0), (i, 10))
    win.regen_in_memory()
    _wait_regen(qapp, win)

    regens = []
    original = win.regen_in_memory
    win.regen_in_memory = lambda *a, **k: (regens.append(1), original(*a, **k))[1]
    try:
        command = actions.dim_linear((0, 0), (100, 0), (50, 25))
        win.tools._execute(command)
        qapp.processEvents()

        assert not regens, "creating a dimension still forces a full regen"
        overlay = win.viewport._overlay_scene
        assert _vertices(overlay) > 100, "the dimension is not on the overlay"
        assert command.dim.dxf.handle in overlay.handle_ranges
    finally:
        win.regen_in_memory = original


def test_a_new_dimension_is_pickable_at_once(qapp) -> None:
    """Riding the overlay must not cost selection: the pick index knows it."""
    from views.main_window import MainWindow
    from core import actions

    win = MainWindow()
    win.new_document()
    win.document.doc.modelspace().add_line((0, 0), (10, 0))
    win.regen_in_memory()
    _wait_regen(qapp, win)

    command = actions.dim_linear((0, 0), (100, 0), (50, 25))
    win.tools._execute(command)
    qapp.processEvents()

    index = win.tools.index
    assert index is not None
    assert index.entity(command.dim.dxf.handle) is command.dim


def test_undoing_a_dimension_takes_it_off_the_screen_at_once(qapp) -> None:
    """The other half: if it rides the overlay, undo must drop it there."""
    from views.main_window import MainWindow
    from core import actions

    win = MainWindow()
    win.new_document()
    win.document.doc.modelspace().add_line((0, 0), (10, 0))
    win.regen_in_memory()
    _wait_regen(qapp, win)

    command = actions.dim_linear((0, 0), (100, 0), (50, 25))
    win.tools._execute(command)
    qapp.processEvents()
    with_dim = _vertices(win.viewport._overlay_scene)
    assert with_dim > 100

    win.history.undo()
    win.tools.after_history_change(command)
    qapp.processEvents()

    after = _vertices(win.viewport._overlay_scene)
    assert after < with_dim, (
        f"the undone dimension is still drawn ({after} vertices of {with_dim})")
