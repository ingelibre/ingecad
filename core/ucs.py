# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The user coordinate system (UCS, Command Reference p.1974).

A UCS here is a plan UCS: an origin and the direction of the X axis in
the world's XY plane. The Y axis is X turned 90 degrees counter-clockwise
-- the plan is always seen from above (principle 5) -- so a UCS tilted out
of the plane, or flipped to look from below, is not one this program
makes. One that comes in a colleague's drawing is kept as it is, and read
here by its projection on the plan.

The current UCS of the model is the drawing's: $UCSORG, $UCSXDIR and
$UCSYDIR in the header, named ones in the UCS table, so it travels in the
DXF and the DWG as AutoCAD keeps it. Sheets and the block editor work in
the world: their UCS ($PUCS*) is not edited here.

Everything typed, shown or constrained in "the user's coordinates" goes
through :func:`current` and the two conversions, :meth:`Ucs.to_world` and
:meth:`Ucs.to_ucs`. Nothing else knows a UCS exists.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from core.commands import Command

#: AutoCAD keeps the last ten UCSs of each space for UCS Previous.
PREVIOUS_DEPTH = 10


@dataclass(frozen=True)
class Ucs:
    """An origin and the angle of the X axis (radians, counter-clockwise
    from the world's X)."""

    ox: float = 0.0
    oy: float = 0.0
    angle: float = 0.0

    @property
    def is_world(self) -> bool:
        return self.ox == 0.0 and self.oy == 0.0 and self.angle == 0.0

    def to_world(self, x: float, y: float) -> tuple[float, float]:
        if self.is_world:
            return (x, y)
        c, s = math.cos(self.angle), math.sin(self.angle)
        return (self.ox + x * c - y * s, self.oy + x * s + y * c)

    def to_ucs(self, x: float, y: float) -> tuple[float, float]:
        if self.is_world:
            return (x, y)
        c, s = math.cos(self.angle), math.sin(self.angle)
        dx, dy = x - self.ox, y - self.oy
        return (dx * c + dy * s, -dx * s + dy * c)

    def vector_to_world(self, dx: float, dy: float) -> tuple[float, float]:
        c, s = math.cos(self.angle), math.sin(self.angle)
        return (dx * c - dy * s, dx * s + dy * c)

    @property
    def degrees(self) -> float:
        return math.degrees(self.angle)


WORLD = Ucs()


def _clean(value: float) -> float:
    """An axis computed with cos/sin of 90 degrees is 6e-17, not 0: round
    the noise away so a UCS turned a right angle reads as one."""
    return 0.0 if abs(value) < 1e-12 else value


def from_axes(origin, xaxis) -> Ucs:
    """The plan UCS of an origin and an X direction (3D tuples welcome:
    Z is dropped, the plan is what this program edits)."""
    angle = math.atan2(float(xaxis[1]), float(xaxis[0])) \
        if math.hypot(float(xaxis[0]), float(xaxis[1])) > 1e-12 else 0.0
    return Ucs(float(origin[0]), float(origin[1]), angle)


def _in_model(document) -> bool:
    if document is None:
        return False
    if getattr(document, "edit_block", None):
        return False
    try:
        return bool(document.current_space().is_modelspace)
    except Exception:
        return True


def stored(doc) -> Ucs:
    """The model's UCS as the drawing's header keeps it."""
    header = doc.header
    try:
        return from_axes(header.get("$UCSORG", (0, 0, 0)),
                         header.get("$UCSXDIR", (1, 0, 0)))
    except (TypeError, ValueError, IndexError):
        return WORLD


def current(document) -> Ucs:
    """The UCS points are typed and shown in: the model's, or the world on
    a sheet and in the block editor."""
    if not _in_model(document):
        return WORLD
    return stored(document.doc)


def current_name(doc) -> str:
    return str(doc.header.get("$UCSNAME", "") or "")


def _active_viewports(doc) -> list:
    try:
        found = doc.viewports.get("*Active")
    except Exception:
        return []
    if found is None:
        return []
    return list(found) if isinstance(found, (list, tuple)) else [found]


def _write(doc, ucs: Ucs, name: str) -> None:
    """The header AND the *Active viewport: AutoCAD reads the model's
    current UCS from the viewport (ODA File Converter as the judge: with
    the header alone a DWG came back in the world)."""
    c, s = _clean(math.cos(ucs.angle)), _clean(math.sin(ucs.angle))
    doc.header["$UCSORG"] = (ucs.ox, ucs.oy, 0.0)
    doc.header["$UCSXDIR"] = (c, s, 0.0)
    doc.header["$UCSYDIR"] = (-s, c, 0.0)
    doc.header["$UCSNAME"] = name
    record = find_named(doc, name) if name else None
    handle = doc.ucs.get(record[0]).dxf.handle if record is not None else None
    for vport in _active_viewports(doc):
        vport.dxf.ucs_origin = (ucs.ox, ucs.oy, 0.0)
        vport.dxf.ucs_xaxis = (c, s, 0.0)
        vport.dxf.ucs_yaxis = (-s, c, 0.0)
        if handle is not None:
            vport.dxf.ucs_handle = handle
        else:
            vport.dxf.discard("ucs_handle")


def previous_stack(document) -> list:
    stack = getattr(document, "_ucs_previous", None)
    if stack is None:
        stack = []
        document._ucs_previous = stack
    return stack


class SetUcsCommand(Command):
    """Make ``ucs`` the model's current UCS (undoable, as in AutoCAD).

    ``remember`` pushes the UCS it replaces onto the Previous list; UCS
    Previous itself pops instead."""

    name = "UCS"

    def __init__(self, ucs: Ucs, name: str = "", remember: bool = True) -> None:
        self.ucs = ucs
        self.ucs_name = name
        self.remember = remember
        self._before = None

    def do(self, document) -> None:
        doc = document.doc
        self._before = (stored(doc), current_name(doc))
        if self.remember:
            stack = previous_stack(document)
            stack.append(self._before)
            del stack[:-PREVIOUS_DEPTH]
        _write(doc, self.ucs, self.ucs_name)
        document.dirty = True

    def undo(self, document) -> None:
        if self._before is None:
            return
        ucs, name = self._before
        _write(document.doc, ucs, name)
        if self.remember:
            stack = previous_stack(document)
            if stack and stack[-1] == self._before:
                stack.pop()
        document.dirty = True


def named(doc) -> dict:
    """The saved UCSs, by name (case kept as written)."""
    out = {}
    for record in doc.ucs:
        out[record.dxf.name] = from_axes(record.dxf.origin, record.dxf.xaxis)
    return out


def find_named(doc, name: str):
    """(stored name, Ucs) of a saved UCS, matched without case, or None."""
    for key, ucs in named(doc).items():
        if key.upper() == name.upper():
            return key, ucs
    return None


class SaveNamedUcsCommand(Command):
    """UCS NAmed Save: the current UCS under a name (replacing one)."""

    name = "UCS"

    def __init__(self, ucs_name: str, ucs: Ucs) -> None:
        self.ucs_name = ucs_name
        self.ucs = ucs
        self._replaced = None
        self._name_before = ""

    def do(self, document) -> None:
        doc = document.doc
        self._name_before = current_name(doc)
        found = find_named(doc, self.ucs_name)
        if found is not None:
            self._replaced = found
            doc.ucs.remove(found[0])
        c, s = _clean(math.cos(self.ucs.angle)), _clean(math.sin(self.ucs.angle))
        doc.ucs.new(self.ucs_name, dxfattribs={
            "origin": (self.ucs.ox, self.ucs.oy, 0.0),
            "xaxis": (c, s, 0.0), "yaxis": (-s, c, 0.0)})
        _write(doc, stored(doc), self.ucs_name)    # the current one is it now
        document.dirty = True

    def undo(self, document) -> None:
        doc = document.doc
        if doc.ucs.has_entry(self.ucs_name):
            doc.ucs.remove(self.ucs_name)
        if self._replaced is not None:
            name, ucs = self._replaced
            c, s = _clean(math.cos(ucs.angle)), _clean(math.sin(ucs.angle))
            doc.ucs.new(name, dxfattribs={
                "origin": (ucs.ox, ucs.oy, 0.0),
                "xaxis": (c, s, 0.0), "yaxis": (-s, c, 0.0)})
        _write(doc, stored(doc), self._name_before)
        document.dirty = True


class DeleteNamedUcsCommand(Command):
    """UCS NAmed Delete. Deleting the current one leaves it unnamed."""

    name = "UCS"

    def __init__(self, ucs_name: str) -> None:
        self.ucs_name = ucs_name
        self._removed = None
        self._was_current = False

    def do(self, document) -> None:
        doc = document.doc
        found = find_named(doc, self.ucs_name)
        if found is None:
            return
        self._removed = found
        doc.ucs.remove(found[0])
        self._was_current = current_name(doc).upper() == found[0].upper()
        if self._was_current:
            _write(doc, stored(doc), "")
        document.dirty = True

    def undo(self, document) -> None:
        if self._removed is None:
            return
        doc = document.doc
        name, ucs = self._removed
        c, s = _clean(math.cos(ucs.angle)), _clean(math.sin(ucs.angle))
        doc.ucs.new(name, dxfattribs={
            "origin": (ucs.ox, ucs.oy, 0.0),
            "xaxis": (c, s, 0.0), "yaxis": (-s, c, 0.0)})
        if self._was_current:
            _write(doc, stored(doc), name)
        document.dirty = True


def object_ucs(entity, pick) -> Ucs | None:
    """UCS OBject (reference p.1977): the UCS a picked object defines, or
    None for an object it does not handle here."""
    from core import ocs

    kind = entity.dxftype()
    px, py = pick
    if kind == "LINE":
        s, e = entity.dxf.start, entity.dxf.end
        if math.hypot(px - s.x, py - s.y) > math.hypot(px - e.x, py - e.y):
            s, e = e, s
        if math.hypot(e.x - s.x, e.y - s.y) < 1e-12:
            return Ucs(s.x, s.y, 0.0)
        return Ucs(s.x, s.y, math.atan2(e.y - s.y, e.x - s.x))
    if kind == "ARC":
        cx, cy, r, a0, a1 = ocs.arc_wcs(entity)
        ends = [(cx + r * math.cos(math.radians(a)),
                 cy + r * math.sin(math.radians(a))) for a in (a0, a1)]
        near = min(ends, key=lambda p: math.hypot(px - p[0], py - p[1]))
        return Ucs(cx, cy, math.atan2(near[1] - cy, near[0] - cx))
    if kind == "CIRCLE":
        cx, cy = entity.dxf.center.x, entity.dxf.center.y
        if math.hypot(px - cx, py - cy) < 1e-12:
            return Ucs(cx, cy, 0.0)
        return Ucs(cx, cy, math.atan2(py - cy, px - cx))
    if kind == "LWPOLYLINE":
        rows = list(ocs.rows_wcs(entity, entity.get_points("xyseb")))
        if len(rows) < 2:
            return None
        (x0, y0), (x1, y1) = rows[0][:2], rows[1][:2]
        return Ucs(x0, y0, math.atan2(y1 - y0, x1 - x0))
    if kind == "POINT":
        return Ucs(entity.dxf.location.x, entity.dxf.location.y, 0.0)
    if kind in ("TEXT", "INSERT", "ATTDEF", "MTEXT"):
        where = entity.dxf.insert
        angle = float(entity.dxf.get("rotation", 0.0) or 0.0)
        return Ucs(where.x, where.y, math.radians(angle))
    return None
