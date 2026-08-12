# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""List arithmetic: markers, continuation, renumbering."""
from __future__ import annotations

from core.mtext_lists import (BULLET, autolist_style, detect_marker,
                              is_empty_item, marker_for, next_marker,
                              renumber, strip_marker)


def test_markers_are_recognized_with_their_ordinal():
    assert detect_marker("3.\tAcero fy=4200") == ("number", 3, "Acero fy=4200")
    assert detect_marker("b.\tsegundo") == ("letter", 2, "segundo")
    assert detect_marker(BULLET + "\tpunto") == ("bullet", 0, "punto")
    # No tab, no list: a plain "1. " sentence is not an item.
    assert detect_marker("1. sin tabulador") is None


def test_the_next_marker_continues_the_sequence():
    assert next_marker("1.\tprimero") == "2."
    assert next_marker("9.\tnoveno") == "10."
    assert next_marker("a.\tuno") == "b."
    assert next_marker("z.\tultimo") == "aa."
    assert next_marker(BULLET + "\talgo") == BULLET
    assert next_marker("texto normal") is None


def test_an_item_with_no_text_is_the_end_of_the_list():
    assert is_empty_item("4.\t")
    assert is_empty_item(BULLET + "\t  ")
    assert not is_empty_item("4.\talgo")


def test_the_autolist_trigger_matches_the_documented_starters():
    assert autolist_style("1.") == ("number", 1)
    assert autolist_style("7.") == ("number", 7)
    assert autolist_style("a.") == ("letter", 1)
    assert autolist_style("-") == ("bullet", 1)
    assert autolist_style("*") == ("bullet", 1)
    assert autolist_style("hola") is None


def test_renumber_rewrites_a_run_and_keeps_the_words():
    texts = ["2.\tuno", "viejo sin marca", "9.\ttres"]
    assert renumber(texts, "number") == ["1.\tuno", "2.\tviejo sin marca",
                                         "3.\ttres"]
    assert renumber(["x", "y"], "letter") == ["a.\tx", "b.\ty"]
    assert renumber(["x"], "bullet") == [BULLET + "\tx"]


def test_strip_marker_returns_the_words():
    assert strip_marker("3.\tAcero") == "Acero"
    assert strip_marker("sin marca") == "sin marca"
