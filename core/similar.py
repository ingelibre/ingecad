# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""SELECTSIMILAR — "adds similar objects to the selection set based on
selected objects" (p. 1726).

Similar means, in the reference's words, "objects of the same type based on
specified matching properties, such as the color or block name". Which
properties count is the Select Similar Settings dialog: Color, Layer,
Linetype, Linetype scale, Lineweight, Plot style, Object style and Name.

Two of those are not offered here, for the same reason the command prompts
never offer what the app cannot do: IngeCAD has no plot styles, and object
style is the per-type style (text style, dimension style) which **is**
offered under its own name. The default matches AutoCAD's: Layer and Name.
"""
from __future__ import annotations

#: What the Select Similar Settings dialog can tick, and how to read it off
#: an entity. Name is the block name of an INSERT — the example the
#: reference itself gives.
PROPERTIES = (
    ("color", "Color", lambda e: e.dxf.get("color", 256)),
    ("layer", "Layer", lambda e: e.dxf.get("layer", "0")),
    ("linetype", "Linetype", lambda e: str(e.dxf.get("linetype", "ByLayer")).upper()),
    ("ltscale", "Linetype scale", lambda e: round(float(e.dxf.get("ltscale", 1.0)), 6)),
    ("lineweight", "Lineweight", lambda e: e.dxf.get("lineweight", -1)),
    ("style", "Object style", lambda e: _style_of(e)),
    ("name", "Name", lambda e: str(e.dxf.get("name", "")).upper()),
)

#: AutoCAD ticks Layer and Name by default.
DEFAULT_KEYS = frozenset(("layer", "name"))


def _style_of(entity):
    """The style that draws this object: text style, or dimension style."""
    for attr in ("style", "dimstyle"):
        value = entity.dxf.get(attr, None)
        if value is not None:
            return str(value).upper()
    return ""


def signature(entity, keys) -> tuple:
    """What must match for two objects to count as similar."""
    values = [entity.dxftype()]
    for key, _label, read in PROPERTIES:
        if key not in keys:
            continue
        try:
            values.append(read(entity))
        except Exception:
            values.append(None)
    return tuple(values)


def find_similar(document, entities, keys=DEFAULT_KEYS, layout=None) -> list:
    """Every object in the layout similar to one of ``entities``.

    The seeds are included, as AutoCAD includes them: the command *adds* to
    the selection set rather than replacing it.
    """
    wanted = {signature(e, keys) for e in entities}
    if not wanted:
        return []
    space = layout if layout is not None else document.modelspace()
    return [e for e in space if signature(e, keys) in wanted]
