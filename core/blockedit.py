# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Block Editor session: BEDIT / BSAVE / BCLOSE, headless.

AutoCAD's Block Editor (BEDIT, reference p. 222) opens a definition in "a
separate environment for creating and changing block definitions": only the
block's geometry is shown, its base point sits at the origin, and every
ordinary draw/edit command works. BSAVE (p. 273) saves the definition --
every insert updates, since references point at the definition by name --
and BCLOSE (p. 215) closes, asking to save or discard if it changed.
BricsCAD's editor behaves the same way (its BCLOSE offers Save / Discard).

IngeCAD's twist, and why this file is small: **the editor is a change of
current space, not a copy**. ``Document.modelspace()`` answers with the
block's own layout while a session is open, so drawing, TRIM, dimensions,
snap, picking and undo all operate on the definition through the exact code
paths they always use. Edits therefore land in the definition immediately;
what BSAVE/BCLOSE really manage is the *rollback point*:

- discard = undo every command executed since the last save, through the
  same History the user's own U uses -- exact by construction;
- while the session is open, U is not allowed to cross the session's start
  (AutoCAD refuses that too), or "discard" could roll back into edits that
  belong to the drawing.

Deliberately not here, per the roadmap: dynamic blocks (parameters, actions,
visibility states) and REFEDIT's in-place working sets.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.i18n import tr


def editable_blocks(document) -> list[str]:
    """Names BEDIT offers: real definitions, no anonymous/layout/xref blocks.

    AutoCAD's Edit Block Definition dialog lists exactly these (anonymous
    ``*D...``/``*U...`` blocks and layout blocks never appear in it).
    """
    names = []
    for block in document.doc.blocks:
        name = block.name
        if name.startswith("*"):
            continue                      # anonymous / layout spaces
        if block.block_record.is_xref:
            continue                      # xrefs are REFEDIT's territory
        names.append(name)
    return sorted(names, key=str.casefold)


def references_of(document, name: str) -> list:
    """Every INSERT of ``name`` anywhere in the drawing (for counts/guards)."""
    out = []
    for layout in document.doc.layouts:
        out.extend(e for e in layout if e.dxftype() == "INSERT"
                   and e.dxf.name == name)
    for block in document.doc.blocks:
        if not block.name.startswith("*"):
            out.extend(e for e in block if e.dxftype() == "INSERT"
                       and e.dxf.name == name)
    return out


def would_recurse(document, inserted: str, into: Optional[str]) -> bool:
    """True if inserting ``inserted`` into block ``into`` loops.

    Direct self-insertion and transitive cycles both: AutoCAD refuses with
    "Block references itself". ``into`` is None when drawing in modelspace,
    which can never recurse.
    """
    if into is None:
        return False
    seen = set()
    stack = [inserted]
    while stack:
        name = stack.pop()
        if name == into:
            return True
        if name in seen or name not in document.doc.blocks:
            continue
        seen.add(name)
        stack.extend(e.dxf.name for e in document.doc.blocks.get(name)
                     if e.dxftype() == "INSERT")
    return False


@dataclass
class BlockEditSession:
    """One open Block Editor: which block, and where its rollback point is."""

    document: object
    history: object
    name: str
    created_new: bool = False
    #: History depth at the last save point. Discard undoes back to here.
    saved_depth: int = field(default=0)

    @classmethod
    def begin(cls, document, history, name: str) -> "BlockEditSession":
        """Open ``name`` in the editor, creating the definition if new.

        The manual's dialog does both: "If you entered a name for a new
        block definition, the Block Editor is displayed, and you can start
        adding objects" (p. 224).
        """
        name = name.strip()
        if not name:
            raise ValueError(tr("A block name is required."))
        if name.startswith("*"):
            raise ValueError(
                tr("Anonymous blocks cannot be edited: {name}", name=name))
        created = name not in document.doc.blocks
        if created:
            document.doc.blocks.new(name)
            document.dirty = True
        session = cls(document=document, history=history, name=name,
                      created_new=created,
                      saved_depth=len(history._undo))
        document.edit_block = name
        return session

    @property
    def dirty(self) -> bool:
        """Changed since the last save point? Undo/redo move this honestly."""
        return len(self.history._undo) != self.saved_depth

    def undo_blocked(self) -> bool:
        """U at the session's floor: AutoCAD refuses to undo past BEDIT."""
        return len(self.history._undo) <= self.saved_depth

    def save(self) -> None:
        """BSAVE: the definition is already edited in place; move the
        rollback point here so a later discard keeps what was saved."""
        self.saved_depth = len(self.history._undo)
        self.created_new = False          # it exists on its own now
        self.document.dirty = True

    def close(self, save: bool) -> None:
        """BCLOSE. With ``save=False``, undo everything since the last save.

        The rollback runs through History itself, so it is exactly the
        inverse of what the user did -- and the redo stack is cleared, or a
        Ctrl+Y after closing would replay definition edits with no editor
        open to see them.
        """
        if save:
            self.save()
        else:
            while len(self.history._undo) > self.saved_depth:
                self.history.undo()
            self.history._redo.clear()
            if self.created_new:
                # A brand-new definition whose whole life was discarded --
                # and by definition nothing references it yet.
                try:
                    self.document.doc.blocks.delete_block(self.name,
                                                          safe=True)
                except Exception:
                    pass
        self.document.edit_block = None
