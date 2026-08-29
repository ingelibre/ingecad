# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Linetypes: the standard library, and loading one into a drawing.

How AutoCAD works with linetypes, and what this module mirrors (LINETYPE,
reference p. 1043):

* A drawing can only use the linetypes **loaded into it**. The standard
  definitions live in a library file (``acad.lin``), and the *Load or Reload
  Linetypes* dialog copies the ones you pick into the drawing.
* The Linetype Manager lists what is loaded in three columns -- **Linetype,
  Appearance, Description** -- where Appearance is a drawn sample of the
  pattern, which is how you tell CENTER from PHANTOM at a glance.
* CONTINUOUS, BYLAYER and BYBLOCK are always there and cannot be deleted.
* The dashes are drawing units, scaled on screen by LTSCALE (and by the
  object's own linetype scale).

Where the numbers come from, because inventing them would be worse than
useless: they were **read out of real drawings** -- 120 plans of the corpus,
keeping the definition several of them agree on (the counts are in the
comments below). Two things that harvest settled that memory could not:
a plan's ``HIDDEN2`` of ``[3.175, -1.5875]`` is the imperial pattern in
millimetres, so the file's own numbers are not automatically the standard;
and ezdxf's ``standards.linetypes()``, the obvious source, disagrees with
what every plan carries for several families.
"""
from __future__ import annotations

from typing import Iterable

from core.commands import Command

#: Names every drawing has and no one may load, rename or delete.
RESERVED = ("BYLAYER", "BYBLOCK", "CONTINUOUS")


#: The standard library, as REAL DRAWINGS carry it.
#:
#: Each entry is (description, [dashes]) in drawing units: positive is a
#: dash, negative a gap, 0.0 a dot -- a LIN file's own notation. The counts
#: in the comments are how many of the 120 harvested plans agree on that
#: definition; where a plan carried the same shape in millimetres (0.5 in ->
#: 12.7 mm) the imperial one is kept, which is what ``acad.lin`` defines and
#: what LTSCALE is there to adapt.
#:
#: ⚠️ These are NOT ezdxf's ``standards.linetypes()`` values, which was the
#: obvious source. Its DASHED is [0.5, -0.1] where 47 of 55 plans say
#: [0.5, -0.25], and its CENTERX2 doubles the dashes but not the gaps where
#: 16 of 16 plans double both. When a library and the drawings disagree
#: about what a drawing contains, the drawings win.
STANDARD: dict[str, tuple[str, list[float]]] = {
    "CONTINUOUS": ("Solid line", []),
    # -- the classic families, imperial, as acad.lin defines them ------------
    "BORDER": ("Border __ __ . __ __ . __ __ . __ __ . __ __ .",      # 7/8
               [0.5, -0.25, 0.5, -0.25, 0.0, -0.25]),
    "BORDER2": ("Border (.5x) __.__.__.__.__.__.__.__.__.__.__.",     # 1/1
                [0.25, -0.125, 0.25, -0.125, 0.0, -0.125]),
    "BORDERX2": ("Border (2x) ____  ____  .  ____  ____  .  ___",     # derived
                 [1.0, -0.5, 1.0, -0.5, 0.0, -0.5]),
    "CENTER": ("Center ____ _ ____ _ ____ _ ____ _ ____ _ ____",      # 35/51
               [1.25, -0.25, 0.25, -0.25]),
    "CENTER2": ("Center (.5x) ___ _ ___ _ ___ _ ___ _ ___ _ ___",     # 34/43
                [0.75, -0.125, 0.125, -0.125]),
    "CENTERX2": ("Center (2x) ________  __  ________  __  _____",     # 16/16
                 [2.5, -0.5, 0.5, -0.5]),
    "DASHDOT": ("Dash dot __ . __ . __ . __ . __ . __ . __ . __",     # 21/29
                [0.5, -0.25, 0.0, -0.25]),
    "DASHDOT2": ("Dash dot (.5x) _._._._._._._._._._._._._._._.",     # 14/18
                 [0.25, -0.125, 0.0, -0.125]),
    "DASHDOTX2": ("Dash dot (2x) ____  .  ____  .  ____  .  ___",     # 7/11
                  [1.0, -0.5, 0.0, -0.5]),
    "DASHED": ("Dashed __ __ __ __ __ __ __ __ __ __ __ __ __ _",     # 47/55
               [0.5, -0.25]),
    "DASHED2": ("Dashed (.5x) _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _",     # 80/90
                [0.25, -0.125]),
    "DASHEDX2": ("Dashed (2x) ____  ____  ____  ____  ____  ___",     # 2/2
                 [1.0, -0.5]),
    "DIVIDE": ("Divide ____ . . ____ . . ____ . . ____ . . ____",     # 2/2
               [0.5, -0.25, 0.0, -0.25, 0.0, -0.25]),
    "DIVIDE2": ("Divide (.5x) __..__..__..__..__..__..__..__.._",     # 3/5
                [0.25, -0.125, 0.0, -0.125, 0.0, -0.125]),
    "DIVIDEX2": ("Divide (2x) ________  .  .  ________  .  .  _",     # 3/3
                 [1.0, -0.5, 0.0, -0.5, 0.0, -0.5]),
    "DOT": ("Dot . . . . . . . . . . . . . . . . . . . . . . . .",    # 6/9
            [0.0, -0.25]),
    "DOT2": ("Dot (.5x) ........................................",    # 3/3
             [0.0, -0.125]),
    "DOTX2": ("Dot (2x) .    .    .    .    .    .    .    .   ",     # derived
              [0.0, -0.5]),
    "HIDDEN": ("Hidden __ __ __ __ __ __ __ __ __ __ __ __ __ _",     # 59/73
               [0.25, -0.125]),
    "HIDDEN2": ("Hidden (.5x) _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _",     # derived
                [0.125, -0.0625]),
    "HIDDENX2": ("Hidden (2x) ____ ____ ____ ____ ____ ____ ___",     # 5/5
                 [0.5, -0.25]),
    "PHANTOM": ("Phantom ______  __  __  ______  __  __  ______",     # 28/32
                [1.25, -0.25, 0.25, -0.25, 0.25, -0.25]),
    "PHANTOM2": ("Phantom (.5x) ___ _ _ ___ _ _ ___ _ _ ___ _ _",     # 24/24
                 [0.625, -0.125, 0.125, -0.125, 0.125, -0.125]),
    "PHANTOMX2": ("Phantom (2x) ____________    ____    ____   ",     # derived
                  [2.5, -0.5, 0.5, -0.5, 0.5, -0.5]),
    # -- the ISO family (acadiso.lin), millimetres ---------------------------
    "ACAD_ISO02W100": ("ISO dash __ __ __ __ __ __ __ __ __ __ _",    # 44/44
                       [12.0, -3.0]),
    "ACAD_ISO03W100": ("ISO dash space __    __    __    __    _",    # 23/23
                       [12.0, -18.0]),
    "ACAD_ISO04W100": ("ISO long-dash dot ____ . ____ . ____ . _",    # 17/19
                       [24.0, -3.0, 0.0, -3.0]),
    "ACAD_ISO05W100": ("ISO long-dash double-dot ____ .. ____ ..",    # derived
                       [24.0, -3.0, 0.0, -3.0, 0.0, -3.0]),
    "ACAD_ISO06W100": ("ISO long-dash triple-dot ____ ... ____ .",    # 1 plan
                       [24.0, -3.0, 0.0, -3.0, 0.0, -3.0, 0.0, -3.0]),
    "ACAD_ISO07W100": ("ISO dot . . . . . . . . . . . . . . . . .",   # 7/7
                       [0.0, -3.0]),
    "ACAD_ISO08W100": ("ISO long-dash short-dash ____ __ ____ __",    # derived
                       [24.0, -3.0, 6.0, -3.0]),
    "ACAD_ISO09W100": ("ISO long-dash double-short-dash ____ __ _",   # derived
                       [24.0, -3.0, 6.0, -3.0, 6.0, -3.0]),
    "ACAD_ISO10W100": ("ISO dash dot __ . __ . __ . __ . __ . __",    # 8/10
                       [12.0, -3.0, 0.0, -3.0]),
    "ACAD_ISO11W100": ("ISO double-dash dot __ __ . __ __ . __ _",    # derived
                       [12.0, -3.0, 12.0, -3.0, 0.0, -3.0]),
    "ACAD_ISO12W100": ("ISO dash double-dot __ . . __ . . __ . .",    # 7/9
                       [12.0, -3.0, 0.0, -3.0, 0.0, -3.0]),
    "ACAD_ISO13W100": ("ISO double-dash double-dot __ __ . . __ _",   # derived
                       [12.0, -3.0, 12.0, -3.0, 0.0, -3.0, 0.0, -3.0]),
    "ACAD_ISO14W100": ("ISO dash triple-dot __ . . . __ . . . __",    # 5/6
                       [12.0, -3.0, 0.0, -3.0, 0.0, -3.0, 0.0, -3.0]),
    "ACAD_ISO15W100": ("ISO double-dash triple-dot __ __ . . . _",    # 3/3
                       [12.0, -3.0, 12.0, -3.0,
                        0.0, -3.0, 0.0, -3.0, 0.0, -3.0]),
}

#: The nine marked "derived" are members of a family whose siblings WERE
#: measured, built by the rule the family itself shows: an X2 doubles every
#: number, a 2 halves it, and each ISO name says how many dashes and dots it
#: carries (ISO15, measured, is ISO13 plus a dot). None was written from
#: memory, and none contradicts a plan.


def library() -> dict[str, tuple[str, list[float]]]:
    """{NAME: (description, dashes)} of everything that can be loaded."""
    return STANDARD


def library_names() -> list[str]:
    """The loadable linetypes, CONTINUOUS first then alphabetical -- the
    order the Load dialog shows them in."""
    names = [n for n in library() if n != "CONTINUOUS"]
    names.sort()
    return ["CONTINUOUS"] + names


def description_of(document, name: str) -> str:
    """What the drawing says this linetype is, or the library's wording."""
    try:
        entry = document.doc.linetypes.get(name)
    except Exception:
        entry = None
    if entry is not None:
        text = entry.dxf.get("description", "") or ""
        if text:
            return text
    found = library().get(name.upper())
    return found[0] if found else ""


def pattern_of(document, name: str) -> list[float]:
    """The dash pattern of a linetype AS THE DRAWING HAS IT.

    ``[]`` means a solid line -- CONTINUOUS, or a definition with no dashes.
    Negative numbers are gaps, positive ones dashes and 0.0 a dot, which is
    exactly how a LIN file writes them.
    """
    try:
        entry = document.doc.linetypes.get(name)
    except Exception:
        found = library().get(name.upper())
        return list(found[1]) if found else []
    try:
        return [tag.value for tag in entry.pattern_tags.tags if tag.code == 49]
    except Exception:
        return []


def loaded_names(document) -> list[str]:
    """Linetypes the drawing carries, CONTINUOUS first then alphabetical."""
    names = [lt.dxf.name for lt in document.doc.linetypes
             if lt.dxf.name.upper() not in ("BYLAYER", "BYBLOCK")]
    names.sort(key=lambda n: (n.upper() != "CONTINUOUS", n.lower()))
    return names


def loadable_names(document) -> list[str]:
    """Library linetypes this drawing does NOT have yet."""
    have = {n.upper() for n in loaded_names(document)}
    return [n for n in library_names() if n.upper() not in have]


class LoadLinetypesCommand(Command):
    """Load linetype definitions into the drawing (AutoCAD's Load button).

    Undoable: loading writes LTYPE table entries, which is a change to the
    document like any other. Nothing is drawn differently until something
    uses them, so no regen is needed.
    """

    def __init__(self, names: Iterable[str]) -> None:
        self.names = [n for n in names]
        self.name = "LINETYPE Load"
        self._added: list[str] = []

    def do(self, document) -> None:
        self._added = []
        table = document.doc.linetypes
        for name in self.names:
            found = library().get(name.upper())
            if found is None or table.has_entry(name):
                continue
            description, pattern = found
            try:
                table.add(name=name, pattern=list(pattern),
                          description=description)
            except Exception:
                continue
            self._added.append(name)
        if self._added:
            document.dirty = True

    def undo(self, document) -> None:
        for name in self._added:
            try:
                document.doc.linetypes.remove(name)
            except Exception:
                pass
        if self._added:
            document.dirty = True
