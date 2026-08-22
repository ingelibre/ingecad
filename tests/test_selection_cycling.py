# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Clicking the same spot again offers the next overlapping object.

Marco hit this on a cadastral plan: he drew a dimension right where the plan
already had a hand-typed number, and picking always answered with the same
one, so the other was simply unreachable -- "there is no way to select it".
AutoCAD calls this selection cycling (SELECTIONCYCLING, p. 2505); this is its
value 1, the one without the list dialog.

The rule that keeps it safe: **the first answer never changes.**
``pick_all`` orders candidates exactly as ``pick`` chose its winner, so a
single click selects what it always did, and cycling only ever reaches what
that click was already skipping.
"""
from __future__ import annotations

import sys
from pathlib import Path

import ezdxf
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def stacked(qapp):
    """A window whose drawing has a LINE and a TEXT on the same spot."""
    from views.main_window import MainWindow

    from core import actions

    win = MainWindow()
    win.new_document()
    # Through Commands, the way the application draws. Adding straight to the
    # modelspace leaves document.revision untouched, so the background index
    # warmer -- which snapshots the document when it starts -- decides its
    # empty index is still current and adopts it over the real one. Every
    # pick then answers None and these tests would pass proving nothing.
    win.tools._execute(actions.add_line((0, 0), (10, 0)))
    win.tools._execute(actions.add_text((4, -0.4), "4.35", 1.0))
    win.tools._execute(actions.add_circle((50, 50), 3))   # never a candidate
    win.regen_in_memory()
    while win._regen_worker is not None:
        qapp.processEvents()
    win.tools._pick_tolerance = 0.6
    win.tools.reset_pick_cycle()
    return win


def test_pick_all_agrees_with_pick_on_the_winner(stacked) -> None:
    """The invariant: cycling may not change what one click selects."""
    index = stacked.tools.index
    for point in ((5.0, 0.0), (4.5, -0.2), (0.0, 0.0), (99.0, 99.0)):
        winner = index.pick(point, 0.6)
        candidates = index.pick_all(point, 0.6)
        assert (candidates[0] if candidates else None) == winner, point


def test_clicking_again_offers_the_next_object(stacked) -> None:
    point = (4.5, -0.15)
    seen = [stacked.tools.pick_entity(point) for _ in range(4)]
    kinds = [e.dxftype() if e is not None else None for e in seen]
    assert len(set(kinds[:2])) == 2, f"no cycling happened: {kinds}"
    assert kinds[2] == kinds[0] and kinds[3] == kinds[1], f"does not wrap: {kinds}"


def test_a_click_somewhere_else_starts_over(stacked) -> None:
    near = (4.5, -0.15)
    first = stacked.tools.pick_entity(near)
    stacked.tools.pick_entity((0.2, 0.0))        # a different spot
    again = stacked.tools.pick_entity(near)
    assert again is first, "the cycle survived a click elsewhere"


def test_cycling_swaps_the_selection_instead_of_adding(stacked) -> None:
    """"I meant the other object", not "both"."""
    point = (4.5, -0.15)
    stacked.tools.on_click(*point)
    assert len(stacked.tools.selection) == 1
    first = set(stacked.tools.selection)
    stacked.tools.on_click(*point)
    assert len(stacked.tools.selection) == 1, "cycling added instead of swapping"
    assert set(stacked.tools.selection) != first


def test_shift_click_never_cycles(stacked) -> None:
    """Shift removes from the selection; cycling there would fight the user."""
    point = (4.5, -0.15)
    stacked.tools.on_click(*point)
    chosen = set(stacked.tools.selection)
    stacked.tools.on_click(*point, shift=True)
    assert not (stacked.tools.selection & chosen)


def test_an_edit_resets_the_cycle(stacked) -> None:
    """Candidates captured before a change must never be offered after it."""
    from core import actions

    point = (4.5, -0.15)
    stacked.tools.pick_entity(point)
    stacked.tools._execute(actions.add_line((20, 20), (30, 30)))
    assert stacked.tools._cycle is None


def test_a_lone_object_is_returned_every_time(stacked) -> None:
    """Nothing to cycle through: the click must not start alternating."""
    point = (9.5, 0.0)                        # only the LINE reaches here
    picks = [stacked.tools.pick_entity(point) for _ in range(3)]
    assert all(p is picks[0] and p is not None for p in picks)
