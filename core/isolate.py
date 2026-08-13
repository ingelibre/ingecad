# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Object isolation — ISOLATEOBJECTS, HIDEOBJECTS, UNISOLATEOBJECTS.

Three commands from the reference, all of them display-only:

* **ISOLATEOBJECTS** (p. 956) "displays selected objects in the current view.
  All other objects are temporarily hidden."
* **HIDEOBJECTS** (p. 912) "temporarily hides selected objects in the current
  view. All other objects are visible."
* **UNISOLATEOBJECTS** (p. 1999) "displays objects previously hidden with the
  ISOLATEOBJECTS or HIDEOBJECTS command."

Note the word AutoCAD keeps repeating: *temporarily*. This is not the layer
tools — nothing about the drawing changes, no layer is frozen, and the file
on disk is untouched. The hidden set therefore lives on the Document as
session state and is never written out, which is what AutoCAD does by
default too (OBJECTISOLATIONMODE 0: isolation does not persist after save).

Because it edits nothing, it does not go on the undo stack; UNISOLATEOBJECTS
is how you undo it, exactly as in AutoCAD.
"""
from __future__ import annotations


def hidden_handles(document) -> set[str]:
    """The handles currently hidden, creating the set on first use."""
    hidden = getattr(document, "_isolated_hidden", None)
    if hidden is None:
        hidden = set()
        document._isolated_hidden = hidden
    return hidden


def is_isolating(document) -> bool:
    return bool(hidden_handles(document))


def hide_objects(document, entities) -> int:
    """HIDEOBJECTS: hide the given entities. Returns how many are hidden."""
    hidden = hidden_handles(document)
    for entity in entities:
        handle = getattr(entity.dxf, "handle", None)
        if handle:
            hidden.add(handle)
    return len(hidden)


def isolate_objects(document, entities) -> int:
    """ISOLATEOBJECTS: hide everything in the drawing except these.

    Every layout is swept, not just the model space: the command speaks of
    "all other objects", and a plan's title block lives on a sheet.
    """
    keep = {getattr(e.dxf, "handle", None) for e in entities}
    hidden = hidden_handles(document)
    for layout in document.doc.layouts:
        for entity in layout:
            handle = getattr(entity.dxf, "handle", None)
            if handle and handle not in keep:
                hidden.add(handle)
    return len(hidden)


def unisolate(document) -> int:
    """UNISOLATEOBJECTS: show everything again. Returns how many came back."""
    hidden = hidden_handles(document)
    count = len(hidden)
    hidden.clear()
    return count
