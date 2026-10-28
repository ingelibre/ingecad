"""The dimension preview never enters the drawing's space.

The cache warmer and the background regen walk the current space from
their own threads; a preview dimension caught there stayed behind as a
ghost (pickable but invisible, or visible but unpickable)."""
from __future__ import annotations

import pytest

from core import actions


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    window = MainWindow()
    window.show()
    window.new_document()
    qapp.processEvents()
    yield window
    window.document.dirty = False
    window.close()


@pytest.mark.parametrize("command", [
    actions.dim_aligned((0, 0), (3.28, 0), (1.6, -2)),
    actions.dim_angular((0, 0), (10, 0), (10, 3), (8, 1)),
])
def test_the_preview_dimension_stays_out_of_the_space(win, monkeypatch, command):
    import render.backend as backend

    t = win.tools
    t._execute(actions.add_line((0, 0), (10, 0)))
    space = win.document.current_space()
    before = [e.dxf.handle for e in space]
    def anonymous():
        return sorted(b.name for b in win.document.doc.blocks
                      if b.name.startswith("*") and not b.name.lower().startswith(("*model", "*paper")))

    blocks = anonymous()
    seen = {}
    real = backend.build_scene_for_entities

    def spy(document, entities, *args, **kwargs):
        # what a background thread walking the space would find right now
        seen["space"] = [e.dxf.handle for e in space]
        seen["owner"] = entities[0].dxf.owner
        return real(document, entities, *args, **kwargs)

    monkeypatch.setattr(backend, "build_scene_for_entities", spy)
    assert t._preview_scene_for(command) is not None
    assert seen["space"] == before, "the preview dimension was in the space"
    assert seen["owner"] != space.layout_key
    assert [e.dxf.handle for e in space] == before
    assert anonymous() == blocks, "the preview left anonymous blocks behind"
