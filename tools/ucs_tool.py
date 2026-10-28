# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""UCS (Command Reference p.1974): move and turn the user's coordinates.

    Specify origin of UCS or [NAmed/OBject/Previous/View/World/Z] <World>:

A tester asked for it to set "the origin and orientation of the X/Y axes"
for a while (#91): typed coordinates, the readout, ORTHO, POLAR and the
grid then follow the UCS, and World or Previous puts things back.

Offered: an origin with an optional point on the X axis and one on the XY
plane (the three-point UCS), NAmed (Restore/Save/Delete/?), OBject,
Previous, View, World and Z. Face, X, Y and ZAxis tilt the plane out of
the plan, which this program does not edit (see core/ucs.py), so they are
not listed -- the PEDIT rule: a prompt lists only what it can do.
"""
from __future__ import annotations

import math

from core import ucs as ucs_mod
from core.i18n import tr
from tools.base import Point, Tool


def _number(text: str):
    try:
        return float(text.strip())
    except (TypeError, ValueError):
        return None


class UcsTool(Tool):
    MAIN = ("Specify origin of UCS or "
            "[NAmed/OBject/Previous/View/World/Z] <World>:")

    def start(self) -> None:
        self.name = "UCS"
        self._await = None
        self._origin = None
        self._angle = None
        self.prompt(self.MAIN)

    # -- helpers ---------------------------------------------------------------
    def _document(self):
        services = self.ctx.services
        return services.document if services is not None else None

    def _current(self):
        return ucs_mod.current(self._document())

    def _apply(self, ucs, name: str = "", remember: bool = True) -> None:
        document = self._document()
        if document is None or not ucs_mod._in_model(document):
            self.ctx.echo(tr("UCS works in the Model tab here; sheets keep "
                             "the world coordinates."))
            self.ctx.finish()
            return
        self.ctx.execute(ucs_mod.SetUcsCommand(ucs, name, remember))
        self.ctx.finish()

    # -- input -----------------------------------------------------------------
    def on_point(self, point: Point) -> None:
        if self._await == "origin":
            current = self._current()
            self._apply(ucs_mod.Ucs(point[0], point[1], current.angle))
            return
        if self._await == "object":
            self._pick_object(point)
            return
        if self._await is None:
            self._origin = point
            self.last_point = point
            self._await = "xaxis"
            self.prompt("Specify point on X-axis or <Accept>:")
            return
        if self._await == "xaxis":
            dx, dy = point[0] - self._origin[0], point[1] - self._origin[1]
            if math.hypot(dx, dy) < 1e-12:
                self.prompt("Specify point on X-axis or <Accept>:")
                return
            self._angle = math.atan2(dy, dx)
            self._await = "plane"
            self.prompt("Specify point on the XY plane or <Accept>:")
            return
        if self._await == "plane":
            # In the plan the third point only tells which side Y is on;
            # a UCS seen from below is not one this program makes.
            self._finish_points()

    def _finish_points(self) -> None:
        angle = self._angle if self._angle is not None else self._current().angle
        self._apply(ucs_mod.Ucs(self._origin[0], self._origin[1], angle))

    def on_enter(self) -> None:
        if self._await is None:
            self._apply(ucs_mod.WORLD)                    # <World>
        elif self._await in ("xaxis", "plane"):
            self._finish_points()                         # <Accept>
        elif self._await == "z":
            self._rotate(90.0)
        elif self._await == "origin":
            self._apply(self._current())     # <0,0>: the UCS's own origin
        else:
            self.ctx.finish()

    def on_option(self, text: str) -> bool:
        if self._await == "z":
            value = _number(text)
            if value is None:
                self.ctx.echo(tr("Requires a number."))
                return True
            self._rotate(value)
            return True
        if self._await == "named":
            return self._named_option(text)
        if self._await in ("restore", "save", "delete"):
            self._named_name(text.strip())
            return True
        if self._await is not None:
            return False
        key = self.option(text)
        document = self._document()
        if key == "W":
            self._apply(ucs_mod.WORLD)
            return True
        if key == "V":
            current = self._current()
            self._apply(ucs_mod.Ucs(current.ox, current.oy, 0.0))
            return True
        if key == "Z":
            self._await = "z"
            self.prompt("Specify rotation angle about Z axis <90>:")
            return True
        if key == "P":
            stack = ucs_mod.previous_stack(document) if document else []
            if not stack:
                self.ctx.echo(tr("There is no previous UCS."))
                self.ctx.finish()
                return True
            ucs, name = stack.pop()
            self._apply(ucs, name, remember=False)
            return True
        if not key and text.strip().upper().lstrip("_") in ("O", "ORIGIN"):
            # not listed, but AutoCAD takes it (its Tools > New UCS > Origin
            # runs "_ucs _o"): a new origin, the axes as they are
            self._await = "origin"
            self.prompt("Specify new origin point <0,0>:")
            return True
        if key == "OB":
            self._await = "object"
            self.entity_picker = True
            self.prompt("Select object to align UCS:")
            return True
        if key == "NA":
            self._await = "named"
            self.prompt("Enter an option [Restore/Save/Delete/?]:")
            return True
        return False

    def _rotate(self, degrees: float) -> None:
        current = self._current()
        self._apply(ucs_mod.Ucs(current.ox, current.oy,
                                current.angle + math.radians(degrees)))

    def _pick_object(self, point: Point) -> None:
        services = self.ctx.services
        entity = services.pick_entity(point) if services else None
        if entity is None:
            self.prompt("Nothing selected. Select object to align UCS:")
            return
        ucs = ucs_mod.object_ucs(entity, point)
        if ucs is None:
            self.ctx.echo(tr("Cannot align the UCS to that object."))
            self.prompt("Select object to align UCS:")
            return
        self._apply(ucs)

    # -- NAmed ---------------------------------------------------------------
    def _named_option(self, text: str) -> bool:
        key = "?" if text.strip() == "?" else self.option(text)
        if key == "?":
            self._list()
            self.prompt("Enter an option [Restore/Save/Delete/?]:")
            return True
        if key == "R":
            self._await = "restore"
            self.prompt("Enter name of UCS to restore or [?]:")
            return True
        if key == "S":
            self._await = "save"
            self.prompt("Enter name to save current UCS or [?]:")
            return True
        if key == "D":
            self._await = "delete"
            self.prompt("Enter UCS name to delete:")
            return True
        return False

    def _named_name(self, name: str) -> None:
        document = self._document()
        if document is None:
            self.ctx.finish()
            return
        if name == "?":
            self._list()
            return
        if not name:
            self.ctx.finish()
            return
        doc = document.doc
        if self._await == "restore":
            found = ucs_mod.find_named(doc, name)
            if found is None:
                self.ctx.echo(tr("Cannot find UCS {name}.", name=name))
                self.ctx.finish()
                return
            self._apply(found[1], found[0])
            return
        if self._await == "save":
            if not _valid_name(name):
                self.ctx.echo(tr("Invalid name."))
                return
            self.ctx.execute(ucs_mod.SaveNamedUcsCommand(name, self._current()))
            self.ctx.finish()
            return
        found = ucs_mod.find_named(doc, name)
        if found is None:
            self.ctx.echo(tr("Cannot find UCS {name}.", name=name))
        else:
            self.ctx.execute(ucs_mod.DeleteNamedUcsCommand(found[0]))
            self.ctx.echo(tr("Deleted UCS {name}.", name=found[0]))
        self.ctx.finish()

    def _list(self) -> None:
        document = self._document()
        if document is None:
            return
        doc = document.doc
        current = ucs_mod.current(document)
        name = ucs_mod.current_name(doc) or (
            "WORLD" if current.is_world else "UNNAMED")
        self.ctx.echo(tr("Current UCS: {name}", name=name))
        saved = ucs_mod.named(doc)
        if not saved:
            self.ctx.echo(tr("No saved UCSs."))
        for key in sorted(saved, key=str.upper):
            u = saved[key]
            self.ctx.echo(f'"{key}"  {u.ox:g},{u.oy:g}  <{u.degrees % 360:g}°')


def _valid_name(name: str) -> bool:
    return bool(name) and len(name) <= 255 and not any(
        c in name for c in '<>/\\":;?*|,=`')


UCS_TOOL_CLASSES = {"UCS": UcsTool}
