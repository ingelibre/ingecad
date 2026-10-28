# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Linetypes: the standard library, and loading one into a drawing.

How AutoCAD works with linetypes, and what this module mirrors (LINETYPE,
reference p. 1043):

* A drawing can only use the linetypes **loaded into it**. The standard
  definitions live in a library file -- ``acadiso.lin`` for a metric drawing
  (MEASUREMENT=1), ``acad.lin`` for an imperial one -- and the *Load or
  Reload Linetypes* dialog copies the ones you pick into the drawing.
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

import re
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


def _metric_library() -> dict[str, tuple[str, list[float]]]:
    """acadiso.lin: the same definitions, the classic families in
    millimetres -- every number of a non-ISO pattern times 25.4 (acadiso's
    CENTER is 31.75,-6.35,6.35,-6.35 where acad's is 1.25,-0.25,0.25,-0.25).
    The ISO ones are millimetres in both files."""
    return {name: (description, pattern if name.startswith("ACAD_ISO")
                   else [round(v * 25.4, 6) for v in pattern])
            for name, (description, pattern) in STANDARD.items()}


METRIC = _metric_library()


def is_metric(document) -> bool:
    """MEASUREMENT=1: AutoCAD loads linetypes (and hatch patterns) from the
    ISO files. DXF's default when the header lacks it is 0, imperial."""
    if document is None:
        return False
    try:
        return int(document.doc.header.get("$MEASUREMENT", 0)) == 1
    except (TypeError, ValueError):
        return False


def library(document=None) -> dict[str, tuple[str, list[float]]]:
    """{NAME: (description, dashes)} of everything that can be loaded into
    ``document``: acadiso.lin's values for a metric drawing, acad.lin's for
    an imperial one -- AutoCAD's choice by MEASUREMENT. Without a document,
    acad.lin's."""
    return METRIC if is_metric(document) else STANDARD


def library_names() -> list[str]:
    """The loadable linetypes, CONTINUOUS first then alphabetical -- the
    order the Load dialog shows them in."""
    names = [n for n in STANDARD if n != "CONTINUOUS"]
    names.sort()
    return ["CONTINUOUS"] + names


def parse_lin(text: str) -> dict[str, tuple[str, list[float] | str]]:
    """Read a LIN file: ``{NAME: (description, definition)}``.

    A simple definition is its dash list, as :data:`STANDARD` holds them. A
    complex one -- a line carrying text or shapes in brackets, GAS_LINE's
    ``["GAS",STANDARD,S=2.54,...]`` -- is kept as the LIN pattern line itself
    (``"A,12.7,-5.08,[...],-2.54"``), which is what ezdxf builds it from.
    Comments start with ``;;``; a pattern may continue on the next line after
    a trailing comma, as AutoCAD's own files do for the long ones.
    """
    entries: dict[str, tuple[str, list[float] | str]] = {}
    name = description = None
    pattern = ""
    for raw in text.splitlines():
        line = raw.split(";;", 1)[0].strip()
        if not line:
            continue
        if line.startswith("*"):
            head, _, desc = line[1:].partition(",")
            name, description, pattern = head.strip(), desc.strip(), ""
            continue
        if name is None:
            continue
        pattern += line
        if pattern.endswith(","):
            continue                     # the definition goes on below
        body = pattern
        if body[:2].upper() == "A,":
            body = body[2:]
        if "[" in body:
            entries[name.upper()] = (description, "A," + body)
        else:
            try:
                dashes = [float(v) for v in body.split(",") if v.strip()]
            except ValueError:
                dashes = None            # a line we cannot read: skip it
            if dashes is not None:
                entries[name.upper()] = (description, dashes)
        name, pattern = None, ""
    return entries


def read_lin_file(path) -> dict[str, tuple[str, list[float] | str]]:
    """``parse_lin`` of a file on disk. LIN files from AutoCAD are ANSI
    (cp1252); one that is valid UTF-8 is read as such."""
    from pathlib import Path

    data = Path(path).read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    return parse_lin(text)


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
    found = library(document).get(name.upper())
    return found[0] if found else ""


#: The words of the library descriptions, as the interface shows them. A
#: Spanish AutoCAD loads its own acadiso.lin ("Trazos __ __ __"); here the
#: drawing keeps what it says and only the display is translated, so the
#: same file reads the same in every language and nothing is rewritten.
_LABELS = {
    "Solid line": "linetype|Solid line",
    "Border": "linetype|Border",
    "Center": "linetype|Center",
    "Dash dot": "linetype|Dash dot",
    "Dashed": "linetype|Dashed",
    "Divide": "linetype|Divide",
    "Dot": "linetype|Dot",
    "Hidden": "linetype|Hidden",
    "Phantom": "linetype|Phantom",
    "ISO dash": "linetype|ISO dash",
    "ISO dash space": "linetype|ISO dash space",
    "ISO long-dash dot": "linetype|ISO long-dash dot",
    "ISO long-dash double-dot": "linetype|ISO long-dash double-dot",
    "ISO long-dash triple-dot": "linetype|ISO long-dash triple-dot",
    "ISO dot": "linetype|ISO dot",
    "ISO long-dash short-dash": "linetype|ISO long-dash short-dash",
    "ISO long-dash double-short-dash":
        "linetype|ISO long-dash double-short-dash",
    "ISO dash dot": "linetype|ISO dash dot",
    "ISO double-dash dot": "linetype|ISO double-dash dot",
    "ISO dash double-dot": "linetype|ISO dash double-dot",
    "ISO double-dash double-dot": "linetype|ISO double-dash double-dot",
    "ISO dash triple-dot": "linetype|ISO dash triple-dot",
    "ISO double-dash triple-dot": "linetype|ISO double-dash triple-dot",
}
#: "Dashed (.5x) _ _ _": the words, the size, the drawn sample.
_DESCRIPTION = re.compile(r"^(.*?)( \((?:\.5|2)x\))?( +[_.].*)?$")
_LIBRARY_TEXTS = {description for description, _ in STANDARD.values()}


def shown_description(text: str) -> str:
    """A library description in the interface language ("Trazos __ __"
    for "Dashed __ __"); anything else -- the user's own wording -- as is."""
    if text not in _LIBRARY_TEXTS:
        return text
    match = _DESCRIPTION.match(text)
    key = _LABELS.get(match.group(1)) if match else None
    if key is None:
        return text
    from core.i18n import tr_context

    return tr_context(key) + (match.group(2) or "") + (match.group(3) or "")


def pattern_of(document, name: str) -> list[float]:
    """The dash pattern of a linetype AS THE DRAWING HAS IT.

    ``[]`` means a solid line -- CONTINUOUS, or a definition with no dashes.
    Negative numbers are gaps, positive ones dashes and 0.0 a dot, which is
    exactly how a LIN file writes them.
    """
    try:
        entry = document.doc.linetypes.get(name)
    except Exception:
        found = library(document).get(name.upper())
        return list(found[1]) if found else []
    try:
        return [tag.value for tag in entry.pattern_tags.tags if tag.code == 49]
    except Exception:
        return []


def ezdxf_pattern(dashes: Iterable[float]) -> list[float]:
    """The library's dash list in the shape ``ezdxf.linetypes.add`` expects.

    A LIN file lists only the dashes; ezdxf wants ``[total_length, dash,
    dash, ...]`` with the pattern length (group 40) in front. Handing it the
    bare dashes swallows the first one as that length -- ACAD_ISO02W100
    ``[12, -3]`` became a lone gap (an invisible line) and ISO04
    ``[24, -3, 0, -3]`` a dotted one -- which is the bug a tester saw as
    "picks an ISO linetype and it loads as something else".
    """
    dashes = [float(d) for d in dashes]
    return [sum(abs(d) for d in dashes)] + dashes


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

    ``catalog`` is where the definitions come from: the standard library by
    default, or a LIN file the user picked (``read_lin_file``). Names the
    drawing already has are skipped unless they are listed in ``reload`` --
    AutoCAD's "Linetype X is already loaded. Reload it?" answered Yes --
    which redefines them in place, keeping the entry (and its handle) and
    so every object that uses it.

    Undoable: loading writes LTYPE table entries, which is a change to the
    document like any other; undo removes what was added and puts the old
    definition back on what was reloaded.
    """

    needs_regen = True

    def __init__(self, names: Iterable[str], catalog=None,
                 reload: Iterable[str] = ()) -> None:
        self.names = [n for n in names]
        self.catalog = catalog
        self.reload = {n.upper() for n in reload}
        self.name = "LINETYPE Load"
        self._added: list[str] = []
        self._reloaded: list[tuple] = []

    def do(self, document) -> None:
        self._added = []
        self._reloaded = []
        table = document.doc.linetypes
        source = self.catalog if self.catalog is not None \
            else library(document)
        for name in self.names:
            found = source.get(name.upper())
            if found is None or name.upper() in RESERVED:
                continue
            description, pattern = found
            if table.has_entry(name):
                if name.upper() not in self.reload:
                    continue
                entry = table.get(name)
                old = (entry, entry.pattern_tags,
                       entry.dxf.get("description", ""))
                try:
                    _setup(entry, pattern, description)
                except Exception:
                    continue
                self._reloaded.append(old)
                continue
            try:
                if isinstance(pattern, str):
                    table.add(name=name, pattern=pattern,
                              description=description)
                else:
                    table.add(name=name, pattern=ezdxf_pattern(pattern),
                              description=description)
            except Exception:
                continue
            self._added.append(name)
        if self._added or self._reloaded:
            document.dirty = True

    def undo(self, document) -> None:
        for entry, tags, description in reversed(self._reloaded):
            entry.pattern_tags = tags      # carries the length (group 40)
            entry.dxf.description = description
        for name in self._added:
            try:
                document.doc.linetypes.remove(name)
            except Exception:
                pass
        if self._added or self._reloaded:
            document.dirty = True


def _setup(entry, pattern, description: str) -> None:
    """Redefine a loaded linetype in place (Reload)."""
    if isinstance(pattern, str):
        # a complex pattern names its text style, resolved through the doc
        entry.setup_pattern(pattern, 0.0)
    else:
        entry.setup_pattern(ezdxf_pattern(pattern))
    entry.dxf.description = description


def is_xref_dependent(name: str) -> bool:
    """``XREF|NAME``: a linetype that came in with an external reference.
    AutoCAD lists them but will not rename or delete them."""
    return "|" in name


def unused_names(document) -> list[str]:
    """Loaded linetypes no object, layer, style or setting uses -- the ones
    the Linetype Manager may Delete. Same answer PURGE gives."""
    from core.cleanup import used_linetypes

    used = used_linetypes(document.doc)
    return [n for n in loaded_names(document)
            if n.upper() not in used and not is_xref_dependent(n)]


class RenameLinetypeCommand(Command):
    """Rename a linetype and every reference to it by name: objects in all
    layouts and blocks, layers, dimension styles and $CELTYPE. AutoCAD
    renames in place in the manager's list; BYLAYER, BYBLOCK, CONTINUOUS and
    xref-dependent linetypes cannot be renamed."""

    name = "LINETYPE Rename"
    needs_regen = True

    def __init__(self, old_name: str, new_name: str) -> None:
        self.old_name = old_name
        self.new_name = new_name
        self._changed: list[tuple] = []

    @staticmethod
    def check(document, old_name: str, new_name: str) -> str | None:
        """Why this rename is refused, or None. Messages are translatable
        keys with ``{name}``."""
        new = new_name.strip()
        if old_name.upper() in RESERVED or is_xref_dependent(old_name):
            return "Linetype {name} cannot be renamed."
        if not new or any(c in new for c in '<>/\\":;?*|,=`'):
            return "Invalid linetype name."
        if new.upper() != old_name.upper() and \
                document.doc.linetypes.has_entry(new):
            return "Linetype {name} already exists."
        return None

    def _rename(self, document, old: str, new: str) -> list[tuple]:
        doc = document.doc
        changed = []
        up = old.upper()
        entry = doc.linetypes.get(old)
        changed.append(("entry", entry, entry.dxf.name))
        # the table is keyed by name: take the entry out under its old key
        doc.linetypes.discard(old)
        entry.dxf.name = new
        doc.linetypes.add_entry(entry)
        for layout in list(doc.layouts) + list(doc.blocks):
            for e in layout:
                if str(e.dxf.get("linetype", "")).upper() == up:
                    changed.append(("attr", e, "linetype", e.dxf.linetype))
                    e.dxf.linetype = new
        for layer in doc.layers:
            if str(layer.dxf.get("linetype", "")).upper() == up:
                changed.append(("attr", layer, "linetype", layer.dxf.linetype))
                layer.dxf.linetype = new
        for style in doc.dimstyles:
            for attr in ("dimltype", "dimltex1", "dimltex2"):
                if str(style.dxf.get(attr, "")).upper() == up:
                    changed.append(("attr", style, attr, style.dxf.get(attr)))
                    style.dxf.set(attr, new)
        if str(doc.header.get("$CELTYPE", "")).upper() == up:
            changed.append(("header", "$CELTYPE", doc.header["$CELTYPE"]))
            doc.header["$CELTYPE"] = new
        return changed

    def do(self, document) -> None:
        self._changed = self._rename(document, self.old_name, self.new_name)
        document.dirty = True

    def undo(self, document) -> None:
        doc = document.doc
        for record in reversed(self._changed):
            if record[0] == "attr":
                _k, obj, attr, value = record
                obj.dxf.set(attr, value)
            elif record[0] == "header":
                doc.header[record[1]] = record[2]
            else:
                _k, entry, name = record
                doc.linetypes.discard(entry.dxf.name)
                entry.dxf.name = name
                doc.linetypes.add_entry(entry)
        document.dirty = True


class LinetypeDescriptionCommand(Command):
    """Edit a linetype's description (the manager's Details > Description)."""

    name = "LINETYPE Description"

    def __init__(self, linetype: str, description: str) -> None:
        self.linetype = linetype
        self.description = description
        self._old = ""

    def do(self, document) -> None:
        entry = document.doc.linetypes.get(self.linetype)
        self._old = entry.dxf.get("description", "")
        entry.dxf.description = self.description
        document.dirty = True

    def undo(self, document) -> None:
        document.doc.linetypes.get(self.linetype).dxf.description = self._old
        document.dirty = True


#: ISO pen widths offered by the manager's Details, in millimetres. An
#: ACAD_ISOnnW100 linetype is defined for a 1.00 mm pen, so the scale it
#: takes is the width itself (reference p. 1046: "Sets the linetype scale
#: to one of a list of standard ISO values").
ISO_PEN_WIDTHS = (0.13, 0.18, 0.25, 0.35, 0.5, 0.7, 1.0, 1.4, 2.0)


# -- the standard library as a LIN file, and -LINETYPE ---------------------------

def lin_text(entries: dict) -> str:
    """``entries`` written as a LIN file, the way AutoCAD's own are."""
    lines = [";;", ";;  IngeCAD standard linetypes", ";;"]
    for name in sorted(n for n in entries if n not in RESERVED):
        description, pattern = entries[name]
        lines.append(f"*{name},{description}")
        if isinstance(pattern, str):
            lines.append(pattern)
        else:
            lines.append("A," + ",".join(f"{v:g}" for v in pattern))
    return "\n".join(lines) + "\n"


def standard_lin_file(document=None):
    """The standard library as a real LIN file, written where IngeCAD keeps
    its data -- what the Select Linetype File dialogs propose, as AutoCAD
    proposes acad.lin or acadiso.lin, so pressing Open loads the standard
    linetypes. ``ingecadiso.lin`` for a metric drawing, ``ingecad.lin``
    for an imperial one."""
    from pathlib import Path

    from PySide6.QtCore import QStandardPaths

    base = QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation)
    folder = Path(base or Path.home() / ".local" / "share") / "IngeCAD"
    metric = is_metric(document)
    path = folder / ("ingecadiso.lin" if metric else "ingecad.lin")
    text = lin_text(METRIC if metric else STANDARD)
    try:
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            folder.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    except OSError:
        pass
    return path


def _matching(entries: dict, spec: str) -> list[str]:
    """Names in ``entries`` matching a -LINETYPE list: comma-separated, with
    the * and ? wildcards, case-insensitive."""
    from fnmatch import fnmatchcase

    wanted = [p.strip().upper() for p in spec.split(",") if p.strip()]
    names = sorted(n for n in entries if n.upper() not in RESERVED)
    return [n for n in names if any(fnmatchcase(n.upper(), w) for w in wanted)]


def linetype_command(document, execute, echo, pick_file, args=()):
    """-LINETYPE (reference pp. 1047-1048), headless.

    ``pick_file(caption, save)`` stands for AutoCAD's Select Linetype File /
    Create or Append Linetype File dialogs and returns a path, or "" on
    Cancel. ``execute`` runs a Command undoably.
    """
    from pathlib import Path

    from core.actions import Prompt
    from core.attributes import SetHeaderCommand
    from core.i18n import keywords, tr

    queue = list(args)
    main_source = "Enter an option [?/Create/Load/Set]:"

    def step(text, handler):
        if queue:
            return handler(queue.pop(0))
        return Prompt(text, handler)

    def main():
        return step(tr(main_source), on_option)

    def on_option(text: str):
        text = text.strip()
        if not text:
            return None
        if text == "?":
            return list_file()
        key = keywords.match(text, main_source)
        if key == "C":
            return step(tr("Enter name of linetype to create:"), on_create_name)
        if key == "L":
            return step(tr("Enter linetype(s) to load:"), on_load_names)
        if key == "S":
            return ask_set()
        echo(tr("Invalid option keyword."))
        return main()

    # -- ? --------------------------------------------------------------------
    def list_file():
        path = pick_file(tr("Select Linetype File"), False)
        if path:
            try:
                entries = read_lin_file(path)
            except OSError:
                entries = {}
            echo(tr("Linetypes defined in file {file}:", file=path))
            echo(f"{tr('Name'):<20}{tr('Description')}")
            echo("-" * 60)
            for name in sorted(entries):
                echo(f"{name:<20}{entries[name][0]}")
        return main()

    # -- Load -------------------------------------------------------------------
    def on_load_names(spec: str):
        if not spec.strip():
            return main()
        path = pick_file(tr("Select Linetype File"), False)
        if not path:
            return main()
        try:
            entries = read_lin_file(path)
        except OSError:
            entries = {}
        names = _matching(entries, spec)
        if not names:
            echo(tr("No matching linetypes found in {file}.", file=path))
            return main()
        loaded = {n.upper() for n in loaded_names(document)}
        fresh = [n for n in names if n.upper() not in loaded]
        again = [n for n in names if n.upper() in loaded]
        reload: list[str] = []
        source = "Linetype {name} is already loaded. Reload it? [Yes/No] <Yes>:"

        def ask_reload():
            if not again:
                return finish()
            return step(tr(source, name=again[0]), on_reload)

        def on_reload(text: str):
            name = again.pop(0)
            if not text.strip() or keywords.match(text, source) == "Y":
                reload.append(name)
            return ask_reload()

        def finish():
            wanted = fresh + reload
            if wanted:
                execute(LoadLinetypesCommand(wanted, catalog=entries,
                                             reload=reload))
                for name in fresh:
                    echo(tr("Linetype {name} loaded.", name=name))
                for name in reload:
                    echo(tr("Linetype {name} reloaded.", name=name))
            return main()

        return ask_reload()

    # -- Set ----------------------------------------------------------------------
    def ask_set():
        current = str(document.doc.header.get("$CELTYPE", "ByLayer"))
        return step(tr("Specify linetype name or [?] <{current}>:",
                       current=current), on_set)

    def on_set(text: str):
        name = text.strip()
        if not name:
            return main()
        if name == "?":
            return step(tr("Enter linetype(s) to list <*>:"), on_list_loaded)
        if name.upper() in ("BYLAYER", "BYBLOCK"):
            value = "ByLayer" if name.upper() == "BYLAYER" else "ByBlock"
        else:
            table = document.doc.linetypes
            if table.has_entry(name):
                value = table.get(name).dxf.name
            elif name.upper() in library(document):
                # not loaded: AutoCAD looks it up in acad.lin and loads it
                execute(LoadLinetypesCommand([name.upper()]))
                value = name.upper()
            else:
                echo(tr("Linetype {name} not found. Use the Load option to "
                        "load it.", name=name))
                return None
        execute(SetHeaderCommand("$CELTYPE", value, "CELTYPE"))
        return main()

    def on_list_loaded(spec: str):
        spec = spec.strip() or "*"
        entries = {n: (description_of(document, n), None)
                   for n in loaded_names(document)}
        names = _matching(entries, spec)
        if spec == "*":
            names = ["ByLayer", "ByBlock"] + names
        echo(f"{tr('Linetype'):<20}{tr('Description')}")
        echo("-" * 60)
        for name in names:
            echo(f"{name:<20}"
                 f"{shown_description(entries.get(name, ('', None))[0])}")
        return ask_set()

    # -- Create ---------------------------------------------------------------------
    created: dict = {}

    def on_create_name(text: str):
        name = text.strip()
        if not name:
            return main()
        if any(c in name for c in '<>/\\":;?*|,=`') or name.upper() in RESERVED:
            echo(tr("Invalid linetype name."))
            return main()
        path = pick_file(tr("Create or Append Linetype File"), True)
        if not path:
            return main()
        created.update(name=name, path=path)
        existing = {}
        if Path(path).is_file():
            try:
                existing = read_lin_file(path)
            except OSError:
                existing = {}
        if name.upper() in existing:
            description, pattern = existing[name.upper()]
            echo(tr('"{name}" already exists in this file. Current definition is:',
                    name=name))
            echo(f"*{name},{description}")
            echo(pattern if isinstance(pattern, str)
                 else "A," + ",".join(f"{v:g}" for v in pattern))
            return step(tr("Overwrite? [Yes/No] <No>:"), on_overwrite)
        return ask_description()

    def on_overwrite(text: str):
        if keywords.match(text, "Overwrite? [Yes/No] <No>:") == "Y":
            created["overwrite"] = True
            return ask_description()
        return main()

    def ask_description():
        return step(tr("Descriptive text:"), on_description)

    def on_description(text: str):
        created["description"] = text.strip()[:47]      # AutoCAD's limit
        echo(tr("Enter linetype pattern (on next line):"))
        return step("A,", on_pattern)

    def on_pattern(text: str):
        body = text.strip()
        if body[:2].upper() == "A,":
            body = body[2:]
        try:
            dashes = [float(v) for v in body.split(",") if v.strip()]
        except ValueError:
            dashes = []
        if len(dashes) < 2 or "[" in body:
            # complex linetypes cannot be made with LINETYPE (the reference)
            echo(tr("Invalid linetype pattern."))
            return step("A,", on_pattern)
        _write_definition(created["path"], created["name"],
                          created["description"], dashes,
                          created.get("overwrite", False))
        echo(tr("New linetype definition saved to file."))
        return main()

    current = str(document.doc.header.get("$CELTYPE", "ByLayer"))
    echo(tr('Current line type: "{name}"', name=current))
    return main()


def _write_definition(path, name: str, description: str, dashes, overwrite):
    """Append a simple definition to a LIN file, or replace its old one."""
    from pathlib import Path

    target = Path(path)
    if target.suffix.lower() != ".lin":
        target = target.with_suffix(".lin")
    text = ""
    if target.is_file():
        data = target.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("cp1252", errors="replace")
    block = f"*{name},{description}\nA," + ",".join(f"{v:g}" for v in dashes) + "\n"
    if overwrite:
        out, skip = [], False
        for line in text.splitlines():
            if line.startswith("*"):
                skip = line[1:].split(",", 1)[0].strip().upper() == name.upper()
                if skip:
                    continue
            elif skip:
                if line.strip() and not line.strip().startswith(";;"):
                    # the pattern line(s) of the old definition
                    if not line.rstrip().endswith(","):
                        skip = False
                    continue
            out.append(line)
        text = "\n".join(out)
    if text and not text.endswith("\n"):
        text += "\n"
    target.write_text(text + block, encoding="utf-8")
