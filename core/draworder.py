# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""DRAWORDER: the SORTENTSTABLE, written for AutoCAD and honored on canvas.

AutoCAD's rule (DRAWORDER, Command Reference p. 662): entities draw in
ascending sort-handle order; the table maps entity handle → sort handle and
absentees use their own handle. Front therefore means "a sort handle above
every natural handle", Back "below every natural handle" — that is exactly
what this module writes, so AutoCAD and every other CAD replay it.

Our canvas batches primitives by (layer, color) and cannot replay arbitrary
per-entity order without giving up batching. What it CAN honor exactly is
the part the drafting flow needs: send-to-Back draws under everything,
bring-to-Front over everything (the packer sorts buckets by this group
first). Above/Under relative to picked reference objects are not offered —
the prompt lists only what the canvas honors (the PEDIT rule).
"""
from __future__ import annotations

from core.commands import Command
from core.i18n import tr

# Front sort-handles start this far above the highest natural handle, so
# entities drawn afterwards (which take fresh, higher handles) stay below
# the fronted ones for a long while, like AutoCAD keeps them.
_FRONT_GAP = 0x1000000


def _natural_bounds(layout) -> tuple[int, int]:
    """Lowest and highest real entity handle in the layout."""
    handles = [int(e.dxf.handle, 16) for e in layout if e.dxf.handle]
    if not handles:
        return (1, 1)
    return (min(handles), max(handles))


def order_groups(layout) -> dict[str, int]:
    """handle -> -1 (sent to back) or +1 (brought to front), for the packer.

    Entities without a SORTENTS entry — or with one inside the natural
    handle range (written by another CAD's Above/Under) — stay in group 0
    and draw in the default bucket order.
    """
    try:
        mapping = list(layout.get_redraw_order())
    except Exception:
        return {}
    if not mapping:
        return {}
    lo, hi = _natural_bounds(layout)
    groups: dict[str, int] = {}
    for handle, sort_handle in mapping:
        try:
            s = int(sort_handle, 16)
        except (TypeError, ValueError):
            continue
        if s < lo:
            groups[handle] = -1
        elif s > hi:
            groups[handle] = 1
    return groups


class DrawOrderCommand(Command):
    """Send the selection to back / bring it to front, with exact undo."""

    def __init__(self, entities: list, mode: str) -> None:
        assert mode in ("front", "back")
        self.name = tr("draw order")
        self._handles = [e.dxf.handle for e in entities if e.dxf.handle]
        self._layout_key = entities[0].dxf.owner if entities else None
        self._mode = mode
        self._old: list | None = None

    def _layout(self, document):
        # Resolve through the first selected handle: works for model and
        # paper space alike.
        entity = document.doc.entitydb.get(self._handles[0])
        return entity.get_layout()

    def do(self, document) -> None:
        layout = self._layout(document)
        self._old = list(layout.get_redraw_order())
        mapping = dict(self._old)
        lo, hi = _natural_bounds(layout)
        if self._mode == "back":
            base = lo - len(self._handles)
            if base < 1:
                base = 1
            for i, handle in enumerate(self._handles):
                mapping[handle] = f"{base + i:X}"
        else:
            base = hi + _FRONT_GAP
            for i, handle in enumerate(self._handles):
                mapping[handle] = f"{base + i:X}"
        layout.set_redraw_order(mapping)
        document.dirty = True

    def undo(self, document) -> None:
        layout = self._layout(document)
        layout.set_redraw_order(dict(self._old or []))
        document.dirty = True
