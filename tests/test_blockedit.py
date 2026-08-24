# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Block Editor: BEDIT / BSAVE / BCLOSE, matched against the reference.

The behaviour replicated (AutoCAD Command Reference): BEDIT opens a
definition "in a separate environment" showing only the block, base point at
the origin (pp. 222-224); a new name creates a new definition (p. 224);
BCLOSE prompts to save or discard when the definition changed (p. 215);
BSAVE saves it (p. 273), and every insert shows the change because
references point at the definition by name. BricsCAD's BCLOSE offers the
same Save / Discard pair.

The design under test: the editor is a change of current space, not a copy.
``Document.modelspace()`` answers with the block's layout during a session,
so drawing, editing and undo run through the paths they always use -- and
"discard" is literally History.undo back to the session's save point.
"""
from __future__ import annotations

import sys
from pathlib import Path

import ezdxf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import actions, blockedit  # noqa: E402
from core.commands import History  # noqa: E402
from core.document import Document  # noqa: E402


@pytest.fixture
def doc():
    document = Document(ezdxf.new(setup=True))
    chair = document.doc.blocks.new("SILLA")
    chair.add_line((0, 0), (10, 0))
    document.doc.modelspace().add_blockref("SILLA", (50, 50))
    document.doc.modelspace().add_blockref("SILLA", (80, 20))
    return document


def _block_len(document, name):
    return len(list(document.doc.blocks.get(name)))


def test_modelspace_answers_with_the_block_during_a_session(doc) -> None:
    history = History(doc)
    before = doc.modelspace()
    session = blockedit.BlockEditSession.begin(doc, history, "SILLA")
    assert doc.modelspace().name == "SILLA"
    session.close(save=True)
    assert doc.modelspace() is not None
    assert doc.modelspace().name == before.name


def test_drawing_inside_the_editor_lands_in_the_definition(doc) -> None:
    """The whole point: LINE inside the editor edits every chair at once."""
    history = History(doc)
    session = blockedit.BlockEditSession.begin(doc, history, "SILLA")
    history.execute(actions.add_line((0, 0), (0, 10)))
    assert _block_len(doc, "SILLA") == 2
    session.close(save=True)
    assert _block_len(doc, "SILLA") == 2
    # both inserts reference the same definition: nothing else to update
    inserts = doc.doc.modelspace().query("INSERT")
    assert all(i.dxf.name == "SILLA" for i in inserts)


def test_discard_is_an_exact_rollback(doc) -> None:
    history = History(doc)
    session = blockedit.BlockEditSession.begin(doc, history, "SILLA")
    history.execute(actions.add_line((0, 0), (0, 10)))
    history.execute(actions.add_circle((5, 5), 1))
    assert session.dirty
    session.close(save=False)
    assert _block_len(doc, "SILLA") == 1          # only the original line
    assert not history._redo, "a redo after closing would replay the edits"


def test_bsave_moves_the_rollback_point(doc) -> None:
    """Discard after a save keeps what was saved -- the reference's exact
    wording is "since it was last saved" (BCLOSE, p. 215)."""
    history = History(doc)
    session = blockedit.BlockEditSession.begin(doc, history, "SILLA")
    history.execute(actions.add_line((0, 0), (0, 10)))
    session.save()
    assert not session.dirty
    history.execute(actions.add_circle((5, 5), 1))
    assert session.dirty
    session.close(save=False)
    assert _block_len(doc, "SILLA") == 2          # line kept, circle gone


def test_a_new_name_creates_a_definition(doc) -> None:
    history = History(doc)
    session = blockedit.BlockEditSession.begin(doc, history, "MESA")
    assert session.created_new
    assert "MESA" in doc.doc.blocks
    history.execute(actions.add_line((0, 0), (5, 0)))
    session.close(save=True)
    assert _block_len(doc, "MESA") == 1


def test_a_discarded_new_block_leaves_no_empty_definition(doc) -> None:
    history = History(doc)
    session = blockedit.BlockEditSession.begin(doc, history, "MESA")
    history.execute(actions.add_line((0, 0), (5, 0)))
    session.close(save=False)
    assert "MESA" not in doc.doc.blocks


def test_undo_never_crosses_the_session_floor(doc) -> None:
    history = History(doc)
    history.execute(actions.add_line((0, 0), (1, 1)))     # a DRAWING edit
    session = blockedit.BlockEditSession.begin(doc, history, "SILLA")
    assert session.undo_blocked(), "nothing done yet: U must be refused"
    history.execute(actions.add_circle((5, 5), 1))
    assert not session.undo_blocked()
    history.undo()
    assert session.undo_blocked(), "back at the floor: U must stop here"


def test_editable_blocks_hides_anonymous_layout_and_xref(doc) -> None:
    """Real definitions only. The ``_ARCHTICK`` arrowheads ezdxf's setup
    creates DO appear -- AutoCAD's dialog lists underscore blocks too."""
    doc.doc.blocks.new("*D7")                              # anonymous
    names = blockedit.editable_blocks(doc)
    assert "SILLA" in names
    assert not any(n.startswith("*") for n in names)
    assert "*Model_Space" not in names and "*D7" not in names


def test_recursion_is_detected_directly_and_transitively(doc) -> None:
    table = doc.doc.blocks.new("MESA")
    table.add_blockref("SILLA", (0, 0))                    # MESA contains SILLA
    assert blockedit.would_recurse(doc, "SILLA", "SILLA")
    assert blockedit.would_recurse(doc, "MESA", "SILLA")   # MESA -> SILLA loop
    assert not blockedit.would_recurse(doc, "SILLA", "MESA") is True or True
    # inserting SILLA into MESA is fine (no cycle back to MESA)
    assert blockedit.would_recurse(doc, "SILLA", "MESA") is False
    assert blockedit.would_recurse(doc, "SILLA", None) is False


def test_names_that_cannot_open(doc) -> None:
    history = History(doc)
    with pytest.raises(ValueError):
        blockedit.BlockEditSession.begin(doc, history, "")
    with pytest.raises(ValueError):
        blockedit.BlockEditSession.begin(doc, history, "*D9")


def test_the_editor_scene_shows_the_block_alone(doc) -> None:
    from core import window_colors
    from render.backend import build_scene

    history = History(doc)
    session = blockedit.BlockEditSession.begin(doc, history, "SILLA")
    scene = build_scene(doc)
    total = sum(len(getattr(scene, b).data)
                for b in ("lines", "thick", "triangles", "points"))
    assert total == 2                       # ONE line: not the two inserts
    assert scene.background == window_colors.rgba("block_editor")
    session.close(save=True)
    after = build_scene(doc)
    # back in the model's own room (which now always names its colour)
    assert after.background == window_colors.rgba("model")
