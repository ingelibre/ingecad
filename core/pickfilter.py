# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The selection filter by object type: a standing filter on every pick.

Rafael's sixth review showed it in OpenCAD Studio and called it "brutal":
untick everything but Dimension, drag a window over the whole plan, and
only the dimensions are selected. QSELECT builds one set from criteria;
this one stays on and shapes every click, window, crossing and Select
All until it is switched off.

Types are offered by what the user calls them, so LWPOLYLINE and the
old POLYLINE are one "Polyline", as the Properties palette names them.
"""
from __future__ import annotations

from typing import Iterable, Optional

#: What the user calls each object type (the Properties palette's names).
TYPE_LABEL = {
    "LINE": "Line", "CIRCLE": "Circle", "ARC": "Arc", "ELLIPSE": "Ellipse",
    "LWPOLYLINE": "Polyline", "POLYLINE": "Polyline", "POINT": "Point",
    "TEXT": "Text", "MTEXT": "MText", "INSERT": "Block Reference",
    "HATCH": "Hatch", "DIMENSION": "Dimension", "ARC_DIMENSION": "Dimension",
    "LEADER": "Leader", "MULTILEADER": "Multileader", "SPLINE": "Spline",
    "IMAGE": "Raster Image", "VIEWPORT": "Viewport", "SOLID": "2D Solid",
    "WIPEOUT": "Wipeout", "XLINE": "Construction Line", "RAY": "Ray",
    "TABLE": "Table", "ACAD_TABLE": "Table", "ATTDEF": "Attribute Definition",
}


def type_label(dxftype: str) -> str:
    """The English name of an object type; :func:`display` shows it."""
    return TYPE_LABEL.get(dxftype, dxftype.title())


#: Type names whose translation differs from the same English word
#: elsewhere in the UI (core.i18n.tr_context keys).
_IN_CONTEXT = {"Dimension": "object|Dimension"}


def display(label: str) -> str:
    """A type name as the UI shows it, in the UI language."""
    from core.i18n import tr, tr_context

    key = _IN_CONTEXT.get(label)
    return tr_context(key) if key else tr(label)


def labels_in(entities: Iterable) -> list[str]:
    """The type names present, sorted: what the filter offers."""
    return sorted({type_label(e.dxftype()) for e in entities})


def passes(entity, allowed: Optional[frozenset]) -> bool:
    """Does the filter let this entity into the selection? ``None`` means
    the filter is off."""
    return allowed is None or type_label(entity.dxftype()) in allowed


def keep(handles: Iterable[str], entity_of, allowed: Optional[frozenset]) -> set:
    """The handles whose entity passes; ``entity_of(handle)`` finds it."""
    if allowed is None:
        return set(handles)
    out = set()
    for handle in handles:
        entity = entity_of(handle)
        if entity is not None and passes(entity, allowed):
            out.add(handle)
    return out
