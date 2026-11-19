# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Derived geometry: what a plugin draws from data of its own, and the user
edits only together with the object it comes from.

A plugin that keeps a model of its own (a wall, a road, a survey) draws its
plan from it: the outline of a wall, the jambs of a door, the symbol of a
grid line. Those lines are ordinary DXF -- any CAD opens and shows them --
but a grip dragged on one of them, or MOVE given that line alone, changes
the drawing and not the model, and the plugin's next rebuild silently puts
the line back: the user's work is lost and, until then, plan and model
disagree.

So a plugin may mark an entity as **derived**:

* ``mark_owner(entity, key)`` on the object the data lives in, and
  ``mark_derived(entity, key)`` on each line drawn from it. A derived
  entity is modified only **together with an owner of the same key**: a
  window or a pick that takes the whole set (a selectable GROUP does it) can
  MOVE, COPY, ROTATE or ERASE it; the line alone is refused, as an object on
  a locked layer is. A derived entity never shows grips.
* ``mark_derived(entity)`` without a key makes display-only geometry (a
  preview, a symbol nobody should touch): it is not picked, not taken by a
  window and never modified by the user.

The owner is found by a key the plugin chooses, not by handle: COPY, ARRAY
and paste copy the marks with the entities, so a copied set keeps its owner
and its lines together without translating handles. The plugin itself is
never restricted -- its commands run through ``ctx.execute``.

The marks are XDATA under their own APPID, so they travel with the DWG and
mean nothing to another CAD; nothing else about the entity changes.
"""
from __future__ import annotations

from typing import Iterable, Optional

from core.commands import Command

#: The APPID of the marks. Not ``INGECAD``: ``set_xdata`` replaces all the
#: XDATA of an APPID, and the plugins' own data lives under theirs.
APPID = "INGECAD_DERIVED"
OWNER = "OWNER"
DERIVED = "DERIVED"


def _ensure_appid(doc) -> None:
    if doc is not None and APPID not in doc.appids:
        doc.appids.add(APPID)


def _mark(entity, role: str, key: Optional[str]) -> None:
    tags = [(1000, role)]
    if key:
        tags.append((1000, str(key)))
    _ensure_appid(entity.doc)
    entity.set_xdata(APPID, tags)


def mark_owner(entity, key: str) -> None:
    """Make ``entity`` the owner of the derived entities sharing ``key``.

    Writes XDATA, so call it inside a Command (a plugin's own, or
    :class:`MarkCommand`) for undo to take it back."""
    if not key:
        raise ValueError("an owner needs a key")
    _mark(entity, OWNER, key)


def mark_derived(entity, key: Optional[str] = None) -> None:
    """Make ``entity`` derived from the owner sharing ``key``; without a key
    it is display-only. Same undo rule as :func:`mark_owner`."""
    _mark(entity, DERIVED, key)


def unmark(entity) -> None:
    if entity.has_xdata(APPID):
        entity.discard_xdata(APPID)


def mark_of(entity) -> tuple[Optional[str], Optional[str]]:
    """(role, key) of ``entity``: (None, None) when it carries no mark, and a
    key of None for display-only geometry. A mark that does not read as one
    (another program wrote it) counts as none."""
    try:
        if not entity.has_xdata(APPID):
            return None, None
        tags = [value for code, value in entity.get_xdata(APPID) if code == 1000]
    except Exception:                       # entities without XDATA support
        return None, None
    if not tags or tags[0] not in (OWNER, DERIVED):
        return None, None
    key = tags[1] if len(tags) > 1 and tags[1] else None
    if tags[0] == OWNER and key is None:
        return None, None
    return tags[0], key


def is_derived(entity) -> bool:
    return mark_of(entity)[0] == DERIVED


def is_display_only(entity) -> bool:
    """Derived without a key: never picked, never modified by the user."""
    role, key = mark_of(entity)
    return role == DERIVED and key is None


def user_editable(entities: Iterable) -> tuple[list, list]:
    """Split ``entities`` into (kept, refused) for a command the user gives:
    a derived entity stays only when an owner of its key is in the same
    set; display-only geometry never stays."""
    entities = list(entities)
    owners = set()
    for entity in entities:
        role, key = mark_of(entity)
        if role == OWNER:
            owners.add(key)
    kept, refused = [], []
    for entity in entities:
        role, key = mark_of(entity)
        if role == DERIVED and (key is None or key not in owners):
            refused.append(entity)
        else:
            kept.append(entity)
    return kept, refused


class MarkCommand(Command):
    """Mark entities that already exist as owner, derived or display-only
    (``role`` OWNER or DERIVED, ``key`` as above), or clear their mark
    (``role`` None), with exact undo. A plugin that creates its lines in a
    command of its own marks them there instead."""

    name = "derived geometry"

    def __init__(self, entities, role: Optional[str], key: Optional[str] = None):
        if role not in (OWNER, DERIVED, None):
            raise ValueError(f"unknown role {role!r}")
        if role == OWNER and not key:
            raise ValueError("an owner needs a key")
        self.entities = list(entities)
        self.role = role
        self.key = key
        self._before = []

    def do(self, document) -> None:
        self._before = []
        for entity in self.entities:
            had = entity.has_xdata(APPID)
            self._before.append(list(entity.get_xdata(APPID)) if had else None)
            if self.role is None:
                unmark(entity)
            else:
                _mark(entity, self.role, self.key)
        document.dirty = True

    def undo(self, document) -> None:
        for entity, before in zip(self.entities, self._before):
            if before is None:
                unmark(entity)
            else:
                entity.set_xdata(APPID, before)
        document.dirty = True
