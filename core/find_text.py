# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""FIND — "finds the text that you specify, and can optionally replace it
with other text" (p. 808).

Find Where is the whole drawing, the current layout, or the current
selection; the results list shows "the location (model or paper space),
object type, and text" (p. 810); Replace and Replace All do the writing.

Where the text lives, per object: TEXT and ATTRIB/ATTDEF in ``text``, MTEXT
in its content (formatting codes and all, so a replacement never eats a
``\\P`` or a colour code), and a DIMENSION in its text override — the
measurement itself is computed and cannot be edited by search and replace.
"""
from __future__ import annotations

import fnmatch

from core.commands import Command
from core.i18n import tr

#: Object types FIND looks inside, and how their text is read and written.
TEXT_TYPES = ("TEXT", "MTEXT", "ATTRIB", "ATTDEF", "DIMENSION")


def read_text(entity) -> str:
    kind = entity.dxftype()
    if kind == "MTEXT":
        return entity.text or ""
    if kind == "DIMENSION":
        return entity.dxf.get("text", "") or ""
    return entity.dxf.get("text", "") or ""


def write_text(entity, value: str) -> None:
    if entity.dxftype() == "MTEXT":
        entity.text = value
    else:
        entity.dxf.text = value


def _hit(text: str, needle: str, match_case: bool, whole_word: bool) -> bool:
    if not needle:
        return False
    haystack = text if match_case else text.upper()
    wanted = needle if match_case else needle.upper()
    if any(ch in wanted for ch in "*?"):
        return fnmatch.fnmatchcase(haystack, wanted)
    if whole_word:
        return wanted in haystack.split()
    return wanted in haystack


def search(entities, needle: str, match_case: bool = False,
           whole_word: bool = False) -> list:
    """Every entity whose text contains the string."""
    return [e for e in entities
            if e.dxftype() in TEXT_TYPES
            and _hit(read_text(e), needle, match_case, whole_word)]


def replace_in(text: str, needle: str, replacement: str,
               match_case: bool) -> str:
    if match_case:
        return text.replace(needle, replacement)
    out = []
    low_text, low_needle = text.lower(), needle.lower()
    i = 0
    while True:
        j = low_text.find(low_needle, i)
        if j < 0:
            out.append(text[i:])
            return "".join(out)
        out.append(text[i:j])
        out.append(replacement)
        i = j + len(needle)


class ReplaceTextCommand(Command):
    """Replace found text, with exact undo."""

    def __init__(self, entities, needle: str, replacement: str,
                 match_case: bool = False) -> None:
        self.name = tr("find and replace")
        self.entities = list(entities)
        self._needle = needle
        self._replacement = replacement
        self._match_case = match_case
        self._before: list[str] = []
        self.needs_regen = True

    def do(self, document) -> None:
        self._before = []
        for entity in self.entities:
            old = read_text(entity)
            self._before.append(old)
            write_text(entity, replace_in(old, self._needle,
                                          self._replacement, self._match_case))
        document.dirty = True

    def undo(self, document) -> None:
        for entity, old in zip(self.entities, self._before):
            write_text(entity, old)
        document.dirty = True
