# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""GROUP — "creates and manages saved sets of objects called groups" (p. 861).

The behaviour that makes a group worth having is the Selectable flag: "when a
group is selectable, selecting one object in the group selects the whole
group" (p. 861), switched off wholesale by PICKSTYLE 0.

Groups live in the drawing's ACAD_GROUP dictionary, which ezdxf models
directly, so they round-trip to AutoCAD like any other named object — a
group made here is a group there.

Names, per the reference: "up to 31 characters long and can include letters,
numbers, and the special characters dollar sign ($), hyphen (-), and
underscore (_) but not spaces. The name is converted to uppercase."
"""
from __future__ import annotations

import re

from core.commands import Command
from core.i18n import tr

_NAME_RE = re.compile(r"^[A-Z0-9$_-]{1,31}$")


def valid_name(name: str) -> bool:
    return bool(_NAME_RE.match((name or "").strip().upper()))


def normalize(name: str) -> str:
    return (name or "").strip().upper()


def all_groups(document) -> list[tuple[str, object]]:
    """(name, group) for every named group, unnamed ones excluded."""
    try:
        return [(name, group) for name, group in document.doc.groups
                if not str(name).startswith("*")]
    except Exception:
        return []


def groups_of(document, entity) -> list[str]:
    """The groups an object belongs to — the reference's Find Name."""
    handle = getattr(entity.dxf, "handle", None)
    if not handle:
        return []
    out = []
    for name, group in all_groups(document):
        if any(getattr(e.dxf, "handle", None) == handle for e in group):
            out.append(name)
    return out


def is_selectable(document, name: str) -> bool:
    """Selectable groups pull their whole membership into a selection."""
    unselectable = getattr(document, "_unselectable_groups", None) or set()
    return normalize(name) not in unselectable


def set_selectable(document, name: str, value: bool) -> None:
    unselectable = getattr(document, "_unselectable_groups", None)
    if unselectable is None:
        unselectable = set()
        document._unselectable_groups = unselectable
    if value:
        unselectable.discard(normalize(name))
    else:
        unselectable.add(normalize(name))


def pickstyle(document) -> int:
    """PICKSTYLE: 0 disables group selection entirely (p. 861)."""
    return int(getattr(document, "_pickstyle", 1))


def set_pickstyle(document, value: int) -> None:
    document._pickstyle = int(value)


def expand(document, handles) -> set[str]:
    """Grow a set of picked handles to whole selectable groups.

    This is the selection behaviour of GROUP, and the only reason a drafter
    groups anything: click one wall, get the wall.
    """
    handles = set(handles)
    if not handles or pickstyle(document) == 0:
        return handles
    grown = set(handles)
    for name, group in all_groups(document):
        if not is_selectable(document, name):
            continue
        members = {getattr(e.dxf, "handle", None) for e in group}
        members.discard(None)
        if members & handles:
            grown |= members
    return grown


class CreateGroupCommand(Command):
    """GROUP: name a set of objects, with exact undo."""

    def __init__(self, name: str, entities, description: str = "") -> None:
        self.name = tr("group")
        self.group_name = normalize(name)
        self.entities = list(entities)
        self.description = description

    def do(self, document) -> None:
        group = document.doc.groups.new(self.group_name)
        with group.edit_data() as data:
            data.extend(self.entities)
        if self.description:
            group.dxf.description = self.description
        document.dirty = True

    def undo(self, document) -> None:
        try:
            document.doc.groups.delete(self.group_name)
        except Exception:
            pass
        document.dirty = True


class DeleteGroupCommand(Command):
    """Ungroup: remove the group, leaving its objects alone."""

    def __init__(self, name: str) -> None:
        self.name = tr("ungroup")
        self.group_name = normalize(name)
        self.entities: list = []
        self._description = ""

    def do(self, document) -> None:
        group = document.doc.groups.get(self.group_name)
        self.entities = list(group)
        self._description = group.dxf.get("description", "")
        document.doc.groups.delete(self.group_name)
        document.dirty = True

    def undo(self, document) -> None:
        group = document.doc.groups.new(self.group_name)
        with group.edit_data() as data:
            data.extend(self.entities)
        if self._description:
            group.dxf.description = self._description
        document.dirty = True
