# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Block attributes, headless: ATTDEF, the ATTRIBs an INSERT carries, ATTEDIT,
ATTSYNC and ATTDISP as Commands.

A title block is a block with attribute definitions (ATTDEF: tag, prompt,
default, modes); every insertion carries one ATTRIB per definition with the
value the user typed. AutoCAD's rules, kept here because a colleague's title
block has to round-trip and behave the same way:

* a **Constant** definition gets no ATTRIB -- the reference shows the
  definition's own text (the renderer draws those, see render.backend);
* a **Preset** definition takes its default without asking;
* a **Verify** definition is asked twice at insertion;
* an **Invisible** definition's ATTRIB is not drawn unless ATTDISP is ON;
  ATTDISP OFF hides every attribute ($ATTMODE: 0 off, 1 normal, 2 on).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from fnmatch import fnmatchcase
from typing import Iterable, Optional

from core.actions import AddEntityCommand
from core.commands import Command

ATTMODE_OFF, ATTMODE_NORMAL, ATTMODE_ON = 0, 1, 2

#: Property names an attribute or a definition may be edited by, in the order
#: -ATTEDIT offers them; ``text`` is the value (ATTRIB) or default (ATTDEF).
EDITABLE_PROPS = ("text", "insert", "height", "rotation", "style", "layer",
                  "color", "tag", "prompt", "flags", "lock_position")


@dataclass(frozen=True)
class AttMode:
    """The -ATTDEF mode line: Invisible/Constant/Verify/Preset/Lock position.

    Annotative and Multiple lines exist in the prompt and are refused
    (single-line attributes only, for now); Lock position defaults to Y, as
    AutoCAD's AFLAGS does.
    """

    invisible: bool = False
    constant: bool = False
    verify: bool = False
    preset: bool = False
    lock_position: bool = True
    multiline: bool = False
    annotative: bool = False

    #: prompt letter -> field, in AutoCAD's order
    LETTERS = (("I", "invisible"), ("C", "constant"), ("V", "verify"),
               ("P", "preset"), ("L", "lock_position"), ("A", "annotative"),
               ("M", "multiline"))

    def line(self) -> str:
        """``Invisible=N Constant=N Verify=N Preset=N Lock position=Y
        Annotative=N Multiple lines=N`` -- the current-modes echo."""
        def yn(v: bool) -> str:
            return "Y" if v else "N"
        return (f"Invisible={yn(self.invisible)} Constant={yn(self.constant)} "
                f"Verify={yn(self.verify)} Preset={yn(self.preset)} "
                f"Lock position={yn(self.lock_position)} "
                f"Annotative={yn(self.annotative)} "
                f"Multiple lines={yn(self.multiline)}")

    def toggled(self, letter: str) -> "AttMode":
        for key, field_name in self.LETTERS:
            if key == letter.upper():
                return replace(self, **{field_name: not getattr(self, field_name)})
        return self

    @classmethod
    def of(cls, attdef) -> "AttMode":
        """The modes an existing ATTDEF entity carries."""
        return cls(invisible=bool(attdef.is_invisible),
                   constant=bool(attdef.is_const),
                   verify=bool(attdef.is_verify),
                   preset=bool(attdef.is_preset),
                   lock_position=bool(attdef.dxf.get("lock_position", 0)),
                   multiline=bool(attdef.has_embedded_mtext_entity))

    def flags(self) -> int:
        """DXF group 70 of ATTDEF/ATTRIB."""
        return ((1 if self.invisible else 0) | (2 if self.constant else 0)
                | (4 if self.verify else 0) | (8 if self.preset else 0))

    def label(self) -> str:
        """Short mode letters for a table (BATTMAN's Mode column): ``ICVPL``."""
        return "".join(letter for letter, field_name in self.LETTERS
                       if getattr(self, field_name))


# -- reading ------------------------------------------------------------------

def attdefs_of(doc, block_name: str) -> list:
    """The block's attribute definitions in prompt order (block order)."""
    if block_name not in doc.blocks:
        return []
    return [e for e in doc.blocks.get(block_name) if e.dxftype() == "ATTDEF"]


def blocks_with_attributes(doc) -> list[str]:
    """User blocks that define at least one attribute, sorted."""
    return sorted(b.name for b in doc.blocks
                  if not b.name.startswith("*")
                  and any(e.dxftype() == "ATTDEF" for e in b))


def prompted_attdefs(doc, block_name: str) -> list:
    """The definitions an insertion asks about: not Constant. Preset ones are
    listed too (the caller fills their default silently)."""
    return [a for a in attdefs_of(doc, block_name) if not a.is_const]


def default_of(attdef) -> str:
    return str(attdef.dxf.get("text", "") or "")


def prompt_of(attdef) -> str:
    """The prompt line, or the tag when the definition has none (AutoCAD)."""
    return str(attdef.dxf.get("prompt", "") or "") or str(attdef.dxf.tag)


def attribs_matching(inserts: Iterable, block_spec: str = "*",
                     tag_spec: str = "*", value_spec: str = "*",
                     visible_only: bool = False) -> list:
    """-ATTEDIT's filters: the ATTRIBs of ``inserts`` whose block name, tag and
    value match the wildcard specifications (case-sensitive values, as
    AutoCAD's)."""
    out = []
    for insert in inserts:
        if insert.dxftype() != "INSERT":
            continue
        if not fnmatchcase(str(insert.dxf.name), block_spec or "*"):
            continue
        for attrib in insert.attribs:
            if visible_only and attrib.is_invisible:
                continue
            if not fnmatchcase(str(attrib.dxf.tag), tag_spec or "*"):
                continue
            if not fnmatchcase(str(attrib.dxf.text or ""), value_spec or "*"):
                continue
            out.append(attrib)
    return out


# -- ATTDEF -------------------------------------------------------------------

def normal_tag(tag: str) -> str:
    """A tag as AutoCAD stores it: upper case, no spaces."""
    return str(tag).strip().upper().replace(" ", "")


def add_attdef(tag: str, prompt: str, default: str, insert, height: float,
               rotation: float = 0.0, mode: AttMode = AttMode(),
               align: str = "LEFT", style: Optional[str] = None,
               p2=None) -> AddEntityCommand:
    """ATTDEF in the current space (the block being edited in BEDIT, or the
    space where the user is defining the block's content)."""
    tag = normal_tag(tag)
    if not tag:
        raise ValueError("An attribute tag is required.")

    def make(space):
        from ezdxf.enums import TextEntityAlignment

        from core.actions import _current_text_style

        doc = space.doc
        chosen = style if style and style in doc.styles \
            else _current_text_style(space)
        entity = space.add_attdef(
            tag, insert=(insert[0], insert[1]), text=default,
            dxfattribs={"prompt": prompt or "", "height": height,
                        "rotation": rotation, "style": chosen})
        entity.is_invisible = mode.invisible
        entity.is_const = mode.constant
        entity.is_verify = mode.verify
        entity.is_preset = mode.preset
        entity.dxf.lock_position = 1 if mode.lock_position else 0
        anchor = getattr(TextEntityAlignment, align, TextEntityAlignment.LEFT)
        if align in ("ALIGNED", "FIT") and p2 is not None:
            entity.set_placement((insert[0], insert[1]), (p2[0], p2[1]),
                                 align=anchor)
        elif align != "LEFT":
            entity.set_placement((insert[0], insert[1]), align=anchor)
        return entity
    return AddEntityCommand("ATTDEF", make)


# -- INSERT with attributes ----------------------------------------------------

def attach_attribs(insert, values: Optional[dict] = None) -> list:
    """Give ``insert`` one ATTRIB per non-constant definition of its block,
    placed by the reference's own matrix (scale, rotation, position), with
    ``values[tag]`` or the definition's default. Returns the new ATTRIBs."""
    block = insert.block()
    if block is None:
        return []
    values = values or {}
    matrix = insert.matrix44()
    made = []
    for attdef in block.attdefs():
        if attdef.is_const:
            continue        # AutoCAD: the definition itself shows
        dxfattribs = attdef.dxfattribs(
            drop={"prompt", "handle", "owner", "tag", "text", "insert",
                  "attribute_type"})
        tag = str(attdef.dxf.tag)
        text = values.get(tag)
        if text is None:
            text = default_of(attdef)
        attrib = insert.add_attrib(tag, text, attdef.dxf.insert, dxfattribs)
        attrib.transform(matrix)
        made.append(attrib)
    return made


def insert_block_with_attribs(name: str, point, xscale: float = 1.0,
                              yscale: Optional[float] = None,
                              rotation: float = 0.0,
                              values: Optional[dict] = None) -> AddEntityCommand:
    """INSERT that also carries its attribute values (``tag -> text``)."""
    ys = xscale if yscale is None else yscale
    values = dict(values or {})

    def make(space):
        insert = space.add_blockref(
            name, (point[0], point[1]),
            dxfattribs={"xscale": xscale, "yscale": ys, "rotation": rotation})
        attach_attribs(insert, values)
        return insert
    return AddEntityCommand("INSERT", make)


# -- editing --------------------------------------------------------------------

class EditAttribsCommand(Command):
    """Set DXF properties on ATTRIB/ATTDEF entities; undo restores each.

    ``changes`` is a list of ``(entity, prop, value)``. Attributes are drawn
    as part of their block reference (the overlay cannot patch them), so the
    command asks for a regen.
    """

    name = "ATTEDIT"
    needs_regen = True

    def __init__(self, changes, name: str = "ATTEDIT") -> None:
        self.changes = [(e, p, v) for e, p, v in changes]
        self.name = name
        self._old: list = []

    def do(self, document) -> None:
        self._old = []
        for entity, prop, value in self.changes:
            old = entity.dxf.get(prop, None) if entity.dxf.hasattr(prop) \
                else None
            self._old.append(old)
            if prop == "insert":
                # keep the alignment point with the insert point, or a
                # centred attribute would move only half-way
                shift = None
                if entity.dxf.hasattr("align_point"):
                    ap = entity.dxf.align_point
                    ip = entity.dxf.insert
                    shift = (ap.x - ip.x, ap.y - ip.y)
                entity.dxf.insert = (value[0], value[1], 0.0)
                if shift is not None:
                    entity.dxf.align_point = (value[0] + shift[0],
                                              value[1] + shift[1], 0.0)
            else:
                entity.dxf.set(prop, value)
        document.dirty = True

    def undo(self, document) -> None:
        for (entity, prop, _value), old in zip(self.changes, self._old):
            if old is None:
                entity.dxf.discard(prop)
            elif prop == "insert":
                shift = None
                if entity.dxf.hasattr("align_point"):
                    ap = entity.dxf.align_point
                    ip = entity.dxf.insert
                    shift = (ap.x - ip.x, ap.y - ip.y)
                entity.dxf.insert = old
                if shift is not None:
                    entity.dxf.align_point = (old.x + shift[0],
                                              old.y + shift[1], 0.0)
            else:
                entity.dxf.set(prop, old)
        document.dirty = True


def edit_definition(attdef, tag: str, prompt: str,
                    default: str) -> Optional[EditAttribsCommand]:
    """DDEDIT on an attribute definition (Edit Attribute Definition, p.
    523): its tag, prompt and default, as one undo step; None when nothing
    changed. A definition shows its TAG, so editing its default alone --
    all the double-click offered -- left the user unable to touch what they
    saw (#88, Rafael)."""
    tag = normal_tag(tag)
    if not tag:
        raise ValueError("An attribute tag is required.")
    changes = [(attdef, prop, value) for prop, value in
               (("tag", tag), ("prompt", prompt), ("text", default))
               if str(attdef.dxf.get(prop, "") or "") != value]
    return EditAttribsCommand(changes, name="DDEDIT") if changes else None


def set_attribute_value(attrib, value: str) -> EditAttribsCommand:
    return EditAttribsCommand([(attrib, "text", value)])


def set_mode(attdef, mode: AttMode) -> EditAttribsCommand:
    """BATTMAN's mode change on a definition."""
    return EditAttribsCommand(
        [(attdef, "flags", mode.flags()),
         (attdef, "lock_position", 1 if mode.lock_position else 0)],
        name="BATTMAN")


class ReorderAttdefsCommand(Command):
    """BATTMAN's Move up / Move down: the prompt order IS the block order."""

    name = "BATTMAN"
    needs_regen = False

    def __init__(self, block, ordered_attdefs) -> None:
        self.block = block
        self.order = list(ordered_attdefs)
        self._before: list = []

    def _apply(self, attdefs_in_order) -> None:
        entities = self.block.entity_space.entities
        slots = [i for i, e in enumerate(entities) if e.dxftype() == "ATTDEF"]
        if len(slots) != len(attdefs_in_order):
            return
        for slot, attdef in zip(slots, attdefs_in_order):
            entities[slot] = attdef

    def do(self, document) -> None:
        self._before = [e for e in self.block.entity_space.entities
                        if e.dxftype() == "ATTDEF"]
        self._apply(self.order)
        document.dirty = True

    def undo(self, document) -> None:
        self._apply(self._before)
        document.dirty = True


class UnlinkEntitiesCommand(Command):
    """Remove entities from a GIVEN layout (a block definition), keeping them
    alive for an exact undo. ERASE asks the current space; BATTMAN removes
    a definition from a block the user is not inside."""

    name = "BATTMAN"
    needs_regen = True

    def __init__(self, layout, entities) -> None:
        self.layout = layout
        self.entities = list(entities)

    def do(self, document) -> None:
        self.removed_handles = [e.dxf.handle for e in self.entities]
        for e in self.entities:
            self.layout.unlink_entity(e)
        document.dirty = True

    def undo(self, document) -> None:
        for e in self.entities:
            self.layout.add_entity(e)
        document.dirty = True


class SyncAttribsCommand(Command):
    """ATTSYNC: every reference of the block gets the definitions' current
    attributes -- missing ones added with their default, orphans removed,
    positions/heights/styles refreshed -- and keeps the VALUES it had."""

    name = "ATTSYNC"
    needs_regen = True

    def __init__(self, document, block_name: str) -> None:
        self.block_name = block_name
        from core.blockedit import references_of

        self.inserts = references_of(document, block_name)
        self._before: list = []     # per insert: its old attrib list
        self._after: list = []      # per insert: the attribs made

    def do(self, document) -> None:
        self._before = []
        self._after = []
        for insert in self.inserts:
            old = list(insert.attribs)
            values = {str(a.dxf.tag): str(a.dxf.text or "") for a in old}
            insert.attribs.clear()          # the list IS the storage
            made = attach_attribs(insert, values)
            self._before.append(old)
            self._after.append(made)
        document.dirty = True

    def undo(self, document) -> None:
        for insert, old, made in zip(self.inserts, self._before, self._after):
            for a in made:
                a.destroy()
            insert.attribs.clear()
            insert.attribs.extend(old)
        document.dirty = True

    def redo_count(self) -> int:
        return len(self.inserts)


class SetHeaderCommand(Command):
    """A system variable stored in the header ($ATTMODE), undoable."""

    needs_regen = True

    def __init__(self, key: str, value, name: str = "SETVAR") -> None:
        self.key = key
        self.value = value
        self.name = name
        self._old = None

    def do(self, document) -> None:
        self._old = document.doc.header.get(self.key, None)
        document.doc.header[self.key] = self.value
        document.dirty = True

    def undo(self, document) -> None:
        if self._old is None:
            try:
                del document.doc.header[self.key]
            except Exception:  # noqa: BLE001 - a header key that never was
                pass
        else:
            document.doc.header[self.key] = self._old
        document.dirty = True


def attmode(doc) -> int:
    try:
        value = int(doc.header.get("$ATTMODE", ATTMODE_NORMAL))
    except Exception:  # noqa: BLE001
        return ATTMODE_NORMAL
    return value if value in (ATTMODE_OFF, ATTMODE_NORMAL, ATTMODE_ON) \
        else ATTMODE_NORMAL


def set_attmode(value: int) -> SetHeaderCommand:
    return SetHeaderCommand("$ATTMODE", int(value), name="ATTDISP")


def attribute_visible(entity, mode: int) -> bool:
    """ATTDISP's rule for one ATTRIB/ATTDEF: OFF hides all, ON shows all,
    Normal honours the entity's own Invisible flag."""
    if mode == ATTMODE_OFF:
        return False
    if mode == ATTMODE_ON:
        return True
    return not bool(getattr(entity, "is_invisible", False))
