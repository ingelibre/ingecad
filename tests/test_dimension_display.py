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


def test_matchprop_between_dimensions_shows_at_once(qapp) -> None:
    """MA from one dimension to another used to wait for a full regen.

    The style transferred correctly all along -- but on a real plan the
    screen took ~2.7 s to show it, and seconds of nothing after clicking the
    destination read as "it did not select that dimension". Reported by
    Marco right after the creation fix landed.
    """
    from views.main_window import MainWindow
    from core import actions, modify

    win = MainWindow()
    win.new_document()
    doc = win.document
    doc.doc.dimstyles.add("PLANO", dxfattribs={"dimtxt": 2.5, "dimasz": 1.8,
                                               "dimscale": 3.0})
    for i in range(30):
        doc.doc.modelspace().add_line((i, 0), (i, 5))
    win.regen_in_memory()
    _wait_regen(qapp, win)

    source = actions.dim_linear((0, 20), (40, 20), (20, 26), dimstyle="PLANO")
    win.tools._execute(source)
    target = actions.dim_linear((0, 40), (40, 40), (20, 46))
    win.tools._execute(target)
    qapp.processEvents()

    def text_height(dim):
        block = dim.dxf.get("geometry", None)
        for entity in doc.doc.blocks.get(block):
            if entity.dxftype() in ("TEXT", "MTEXT"):
                return round(float(getattr(entity.dxf, "char_height", None)
                                   or getattr(entity.dxf, "height", 0)), 2)
        return None

    assert text_height(source.dim) != text_height(target.dim)

    win.tools._execute(modify.match_properties(source.dim, [target.dim]))
    qapp.processEvents()

    # the style really travelled -- and the screen already shows it
    assert target.dim.dxf.dimstyle == "PLANO"
    assert text_height(target.dim) == text_height(source.dim)
    assert win._regen_worker is None, "MATCHPROP still queued a full regen"
    overlay = win.viewport._overlay_scene
    assert target.dim.dxf.handle in overlay.handle_ranges


def test_matchprop_does_not_queue_an_entity_twice(qapp) -> None:
    """Restyling something already on the overlay must not draw it twice."""
    from views.main_window import MainWindow
    from core import actions, modify

    win = MainWindow()
    win.new_document()
    doc = win.document
    doc.doc.layers.add("ROJO", color=1)
    source = doc.doc.modelspace().add_line((0, 50), (10, 50),
                                           dxfattribs={"layer": "ROJO"})
    win.regen_in_memory()
    _wait_regen(qapp, win)

    drawn = actions.dim_linear((0, 20), (40, 20), (20, 26))
    win.tools._execute(drawn)
    win.tools._execute(modify.match_properties(source, [drawn.dim]))
    qapp.processEvents()

    queued = [e.dxf.handle for e in win.tools._pending_render if e.is_alive]
    assert queued.count(drawn.dim.dxf.handle) == 1, queued


# -- a dimension's block is drawn in the dimension's own dress ------------------

def _dim_colours(doc, dim) -> set:
    """Every RGB the scene paints the dimension with (lines, arrowheads,
    text glyphs), through the same frontend the canvas uses."""
    import numpy as np

    from render.backend import build_scene

    scene = build_scene(doc, "Model")
    colours = set()
    for batch, first, count in scene.handle_ranges[dim.dxf.handle]:
        rgba = getattr(scene, batch).data["rgba"][first:first + count]
        colours |= {tuple(int(v) for v in c)
                    for c in np.unique(rgba[:, :3], axis=0)}
    return colours


def test_a_dimension_moved_to_a_layer_takes_that_layers_colour() -> None:
    """Rafael, 0.6.2: a layer "cotas" in red, the dimensions moved onto
    it -- and they stayed white. ISO-25 colours its lines, arrows and text
    ByBlock (AutoCAD's default), which for a dimension's block means "the
    dimension's own colour"; the frontend resolved it against the canvas
    instead. Now the *D block is drawn as the block reference it is, and
    the block content follows the dimension onto its layer in the file, as
    AutoCAD writes it (3991 of 3991 block entities in three real plans)."""
    from core import actions, styles
    from core.commands import History
    from core.document import Document

    doc = Document.new()
    doc.doc.layers.add("cotas", color=1)
    history = History(doc)
    history.execute(actions.dim_linear((10, 10), (60, 10), (35, 20)))
    dim = doc.modelspace().query("DIMENSION")[0]
    white, red, green = (255, 255, 255), (255, 0, 0), (0, 255, 0)
    assert _dim_colours(doc, dim) == {white}          # control: layer 0

    # the Properties bar gesture: layer, and colour back to ByLayer
    history.execute(actions.SetPropertyCommand([dim], "layer", "cotas"))
    history.execute(actions.SetPropertyCommand([dim], "color", 256))
    assert _dim_colours(doc, dim) == {red}
    block = doc.doc.blocks.get(dim.dxf.geometry)
    assert all(e.dxf.layer == "cotas" for e in block
               if e.dxftype() != "POINT")

    history.undo()
    history.undo()
    assert _dim_colours(doc, dim) == {white}
    assert all(e.dxf.layer == "0" for e in block if e.dxftype() != "POINT")
    history.redo()
    history.redo()
    assert _dim_colours(doc, dim) == {red}

    # the style's second half of his report: with every colour set ByLayer
    # the text and arrows turned red but the lines stayed white -- the
    # re-render had left them on layer 0
    history.execute(styles.SetDimStylePropsCommand(
        "ISO-25", {"dimclrd": 256, "dimclre": 256, "dimclrt": 256}))
    assert _dim_colours(doc, dim) == {red}

    # an explicit colour in the style still wins over the dimension's
    history.execute(styles.SetDimStylePropsCommand("ISO-25", {"dimclrd": 3}))
    assert _dim_colours(doc, dim) == {red, green}

    # and ByBlock -- acadiso's ISO-25, and 1100 of the 3052 block entities
    # in a colleague's plan -- means the dimension's OWN colour: the layer's,
    # or an override set on the dimension itself
    history.execute(styles.SetDimStylePropsCommand(
        "ISO-25", {"dimclrd": 0, "dimclre": 0, "dimclrt": 0}))
    assert _dim_colours(doc, dim) == {red}
    history.execute(actions.SetPropertyCommand([dim], "color", 3))
    assert _dim_colours(doc, dim) == {green}


def test_file_new_forgets_the_overlay_of_the_previous_drawing(qapp) -> None:
    """Marco: dimensions drawn on a plan, then File > New -- and their lines
    showed on the empty canvas. The overlay queue (entities drawn since the
    last full regen) survived attach_document and was rebuilt against the
    new document, whose block table knows nothing of those dimensions."""
    from core import actions
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        win.new_document()
        win.maybe_save_changes = lambda *a, **k: True
        t = win.tools
        t._execute(actions.add_line((0, 0), (50, 0)))
        t._execute(actions.dim_linear((0, 0), (50, 0), (25, 10)))
        qapp.processEvents()
        assert t._pending_render                     # queued for the overlay
        assert win.viewport._overlay_scene is not None
        win.new_document()
        qapp.processEvents()
        assert t._pending_render == []
        assert win.viewport._overlay_scene is None
    finally:
        win.close()


def test_the_dimension_preview_is_the_dimension_the_click_leaves(qapp) -> None:
    """Marco: while placing a linear dimension the preview showed the text
    centred on the line, unlike the finished dimension (ISO-25: above).
    The preview is now the rendered dimension itself, built from the same
    command the click runs, and the document is untouched by it."""
    import numpy as np

    from core import actions
    from render.backend import build_scene_for_entities
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        win.new_document()
        win.maybe_save_changes = lambda *a, **k: True
        t = win.tools
        t._execute(actions.add_line((0, 0), (50, 0)))
        doc = win.document.doc
        revision = win.document.revision
        win.dispatcher.submit("DIMLINEAR")
        t.on_hover(0, 0, threshold_world=1.0)
        t.on_click(0, 0)
        t.on_hover(50, 0, threshold_world=1.0)
        t.on_click(50, 0)
        # the click itself builds the preview: nothing else shows meanwhile
        assert win.viewport._preview_scene is not None
        t.on_hover(25, 10, threshold_world=1.0)
        preview = win.viewport._preview_scene
        assert preview is not None and preview.lines.vertex_count > 0
        assert preview.triangles.vertex_count > 0          # arrows and glyphs
        # the document is as it was: no dimension, no *D block, no revision
        # (the standard arrowhead block the renderer materialises stays, as
        # it would after the first real dimension)
        assert not doc.modelspace().query("DIMENSION")
        assert not [b.name for b in doc.blocks if b.name.startswith("*D")]
        assert win.document.revision == revision
        # the click leaves exactly what was previewed
        t.on_click(25, 10)
        dim = doc.modelspace().query("DIMENSION")[0]
        final = build_scene_for_entities(win.document, [dim], t._flatten,
                                         t.canvas_space())
        assert win.viewport._preview_scene is None              # tool ended
        assert np.array_equal(preview.lines.data, final.lines.data)
        assert preview.triangles.vertex_count == final.triangles.vertex_count
    finally:
        win.close()


def test_an_option_that_leaves_no_preview_clears_the_old_one(qapp):
    """GeoCad Yaguareté had to patch this: _preview_now forgot the preview
    key BEFORE asking _clear_preview, which only clears when it has a key
    -- so a step with nothing to preview left the last picture on screen."""
    from core import actions
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        win.new_document()
        t = win.tools
        t._execute(actions.add_line((0, 0), (50, 0)))
        win.dispatcher.submit("DIMLINEAR")
        t.on_hover(0, 0, threshold_world=1.0)
        t.on_click(0, 0)
        t.on_hover(50, 0, threshold_world=1.0)
        t.on_click(50, 0)
        t.on_hover(25, 10, threshold_world=1.0)
        assert win.viewport._preview_scene is not None
        t.tool.preview_command = lambda point: None   # this step: nothing
        t.on_text("H")                                 # an option re-previews
        assert win.viewport._preview_scene is None, "the old preview stayed"
        t.cancel()
    finally:
        win.document.dirty = False
        win.close()
