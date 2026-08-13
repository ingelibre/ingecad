# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""QSELECT — "creates a selection set based on filtering criteria" (p. 1584).

The dialog's five controls, in the reference's order: **Apply to** (the whole
drawing or the current selection), **Object type**, **Property**, **Operator**
(Equals, Not Equal To, Greater Than, Less Than, *Wildcard Match) and
**Value**; then **How to apply** (include or exclude the matches) and
**Append to current selection set**.

Wildcard Match is "available only for text fields", and Greater/Less Than
only make sense for numbers, so :func:`operators_for` reports which ones a
given property accepts and the dialog offers no more than that.
"""
from __future__ import annotations

import fnmatch

#: The properties a filter can test, per object type. The general ones are
#: on every object; the rest are added when the chosen type has them.
GENERAL = (
    ("color", "Color", "int"),
    ("layer", "Layer", "text"),
    ("linetype", "Linetype", "text"),
    ("ltscale", "Linetype scale", "float"),
    ("lineweight", "Lineweight", "int"),
)

BY_TYPE = {
    "CIRCLE": (("radius", "Radius", "float"),),
    "ARC": (("radius", "Radius", "float"),),
    "TEXT": (("text", "Contents", "text"), ("height", "Height", "float"),
             ("style", "Style", "text"), ("rotation", "Rotation", "float")),
    "MTEXT": (("char_height", "Text height", "float"),
              ("style", "Style", "text")),
    "INSERT": (("name", "Name", "text"),),
    "DIMENSION": (("dimstyle", "Dim style", "text"),),
    "LWPOLYLINE": (("const_width", "Global width", "float"),),
    "HATCH": (("pattern_name", "Pattern name", "text"),),
    "IMAGE": (("fade", "Fade", "int"), ("contrast", "Contrast", "int")),
}

EQUALS = "="
NOT_EQUAL = "!="
GREATER = ">"
LESS = "<"
WILDCARD = "*"
SELECT_ALL = "all"

_LABELS = {
    EQUALS: "Equals",
    NOT_EQUAL: "Not Equal To",
    GREATER: "Greater Than",
    LESS: "Less Than",
    WILDCARD: "*Wildcard Match",
    SELECT_ALL: "Select All",
}


def operator_label(op: str) -> str:
    return _LABELS.get(op, op)


def operators_for(kind: str) -> tuple:
    """Which operators this property kind accepts (p. 1586)."""
    if kind in ("int", "float"):
        return (EQUALS, NOT_EQUAL, GREATER, LESS, SELECT_ALL)
    return (EQUALS, NOT_EQUAL, WILDCARD, SELECT_ALL)


def properties_for(kind: str | None) -> tuple:
    """The property list for an object type, general ones first."""
    return GENERAL + tuple(BY_TYPE.get(kind or "", ()))


def object_types(entities) -> list[str]:
    return sorted({e.dxftype() for e in entities})


def _read(entity, prop: str):
    if prop == "text" and entity.dxftype() == "MTEXT":
        return entity.text
    value = entity.dxf.get(prop, None)
    return value


def matches(entity, prop: str, operator: str, value: str, kind: str) -> bool:
    """Does this entity pass the filter?"""
    if operator == SELECT_ALL:
        return True
    actual = _read(entity, prop)
    if actual is None:
        return False
    if kind in ("int", "float"):
        try:
            wanted = float(value)
            actual = float(actual)
        except (TypeError, ValueError):
            return False
        if operator == EQUALS:
            return abs(actual - wanted) < 1e-9
        if operator == NOT_EQUAL:
            return abs(actual - wanted) >= 1e-9
        if operator == GREATER:
            return actual > wanted
        if operator == LESS:
            return actual < wanted
        return False
    text = str(actual)
    if operator == WILDCARD:
        return fnmatch.fnmatch(text.upper(), str(value).upper())
    same = text.upper() == str(value).upper()
    return same if operator == EQUALS else not same


def select(entities, kind, prop, operator, value, prop_kind,
           exclude: bool = False) -> list:
    """The filtered set: the reference's Include / Exclude in New Selection."""
    out = []
    for entity in entities:
        if kind and entity.dxftype() != kind:
            continue
        hit = matches(entity, prop, operator, value, prop_kind)
        if hit != exclude:
            out.append(entity)
    return out
