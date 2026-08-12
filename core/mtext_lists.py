# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Bullets and numbered lists for MTEXT — which are just text plus indents.

AutoCAD has no list object: a "numbered list" is the literal marker
(``1.`` + a tab) at the start of each paragraph, plus a hanging indent in
the paragraph codes (``\\pxi-2,l2,t2;`` here). That is why a list written
by AutoCAD survives every DXF round trip — and why ours reads correctly
there: it is the same plain construction.

This module is the headless arithmetic: recognizing a marker, producing
the next one, renumbering a run of items. The editor supplies the typing
behavior (Enter continues, an empty item ends the list, Tab after ``1.``
starts one).
"""
from __future__ import annotations

import re
from typing import Optional

# Our hanging indent for list items, in char_height multiples. The marker
# column is `left + indent` = 0, the text column is `left`.
LIST_INDENT = -2.0
LIST_LEFT = 2.0
LIST_TABS = (2.0,)

BULLET = "•"

# marker text -> (style, ordinal). Styles: "number", "letter", "bullet".
_NUMBER = re.compile(r"^(\d+)\.$")
_LETTER = re.compile(r"^([a-z])\.$")


def detect_marker(paragraph_text: str):
    """(style, ordinal, rest_of_text) when the paragraph is a list item.

    The marker is everything before the first tab; ``rest`` keeps no tab.
    """
    head, tab, rest = paragraph_text.partition("\t")
    if not tab:
        return None
    head = head.strip()
    if head == BULLET:
        return ("bullet", 0, rest)
    match = _NUMBER.match(head)
    if match:
        return ("number", int(match.group(1)), rest)
    match = _LETTER.match(head)
    if match:
        return ("letter", ord(match.group(1)) - ord("a") + 1, rest)
    return None


def marker_for(style: str, ordinal: int) -> str:
    """The literal marker text (without the tab)."""
    if style == "bullet":
        return BULLET
    if style == "letter":
        # a..z then aa, ab… — AutoCAD wraps the same way.
        ordinal = max(ordinal, 1)
        letters = ""
        while ordinal:
            ordinal, remainder = divmod(ordinal - 1, 26)
            letters = chr(ord("a") + remainder) + letters
        return letters + "."
    return f"{max(ordinal, 1)}."


def next_marker(paragraph_text: str) -> Optional[str]:
    """The marker the NEXT item takes after this paragraph, or None."""
    found = detect_marker(paragraph_text)
    if found is None:
        return None
    style, ordinal, _rest = found
    return marker_for(style, ordinal + 1)


def is_empty_item(paragraph_text: str) -> bool:
    """A marker with nothing after it: Enter here ENDS the list."""
    found = detect_marker(paragraph_text)
    return found is not None and not found[2].strip()


AUTOLIST_STARTERS = {
    "-": "bullet",
    "*": "bullet",
    BULLET: "bullet",
}


def autolist_style(head: str) -> Optional[tuple[str, int]]:
    """(style, ordinal) when ``head`` typed before Tab should start a list.

    The documented trigger: type ``1.`` (or a dash, or a letter) and press
    Tab — the paragraph becomes a list item.
    """
    head = head.strip()
    if head in AUTOLIST_STARTERS:
        return (AUTOLIST_STARTERS[head], 1)
    match = _NUMBER.match(head)
    if match:
        return ("number", int(match.group(1)))
    match = _LETTER.match(head)
    if match:
        return ("letter", ord(match.group(1)) - ord("a") + 1)
    return None


def renumber(texts: list[str], style: str, start: int = 1) -> list[str]:
    """Rewrite a run of paragraphs as items 1..n of ``style``.

    Existing markers are replaced, missing ones added; the text keeps its
    own words. Bullets all share the one marker.
    """
    out = []
    ordinal = start
    for text in texts:
        found = detect_marker(text)
        rest = found[2] if found else text
        out.append(marker_for(style, ordinal) + "\t" + rest)
        ordinal += 1
    return out


def strip_marker(paragraph_text: str) -> str:
    found = detect_marker(paragraph_text)
    return found[2] if found else paragraph_text
