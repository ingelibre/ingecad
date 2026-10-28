# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""BOUNDARY / -BOUNDARY: a closed polyline from an enclosed area.

AutoCAD's BOUNDARY opens the Boundary Creation dialog; ``-boundary`` asks
at the prompt (p. 258): ``Specify internal point or [Advanced options]:``
and, under Advanced, ``Enter an option [Boundary set/Island detection/
Object type]:``. IngeCAD answers both spellings at the prompt, the way its
-HATCH does. Each pick traces the region around the point with the HATCH
tracer (core.hatch_boundary) and makes one closed LWPOLYLINE per loop:
the outer one, and each island when island detection is on. Regions are
not an object IngeCAD makes, so Object type stays Polyline and says so.
"""
from __future__ import annotations

from core import actions
from core.commands import CompositeCommand
from core.i18n import tr
from tools.base import Point, Tool

_PICK = "Specify internal point or [Advanced options]:"
_ADVANCED = "Enter an option [Boundary set/Island detection/Object type]:"


class BoundaryTool(Tool):
    entity_picker = True

    #: Session-sticky, like the dialog's settings.
    _islands = True
    _everything = True

    def start(self) -> None:
        self.name = "BOUNDARY"
        self._await: str | None = None      # advanced sub-prompt in progress
        self._candidates: list | None = None if type(self)._everything else []
        self._picking_set = False
        self._made = 0
        self.prompt(_PICK)

    # -- options -----------------------------------------------------------------
    def on_option(self, text: str) -> bool:
        token = self.option(text) or text.strip().upper()
        cls = type(self)
        if self._await is None:
            if token in ("A", "ADVANCED"):
                self._await = "advanced"
                self.prompt(_ADVANCED)
                return True
            return False
        if self._await == "advanced":
            if token in ("B", "BOUNDARY"):
                self._await = "set"
                self.prompt("Specify candidate set for boundary [New/Everything] "
                            "<Everything>:")
                return True
            if token in ("I", "ISLAND"):
                self._await = "islands"
                self.prompt("Do you want island detection? [Yes/No] <{d}>:",
                            d="Y" if cls._islands else "N")
                return True
            if token in ("O", "OBJECT"):
                self._await = "type"
                self.prompt("Enter type of boundary object [Region/Polyline] <Polyline>:")
                return True
            if token == "":
                self._await = None
                self.prompt(_PICK)
                return True
            return False
        if self._await == "set":
            if token in ("N", "NEW"):
                cls._everything = False
                self._candidates = []
                self._picking_set = True
                self._await = None
                self.prompt("Select objects (Enter when done):")
                return True
            if token in ("E", "EVERYTHING", ""):
                cls._everything = True
                self._candidates = None
                self._await = None
                self.prompt(_PICK)
                return True
            return False
        if self._await == "islands":
            if token in ("Y", "YES"):
                cls._islands = True
            elif token in ("N", "NO"):
                cls._islands = False
            elif token != "":
                return False
            self._await = None
            self.prompt(_PICK)
            return True
        if self._await == "type":
            if token in ("R", "REGION"):
                self.ctx.echo(tr("IngeCAD does not create regions: the boundary "
                                 "is made as a polyline."))
            elif token not in ("P", "POLYLINE", ""):
                return False
            self._await = None
            self.prompt(_PICK)
            return True
        return False

    def on_enter(self) -> None:
        if self._picking_set:
            self._picking_set = False
            if not self._candidates:
                type(self)._everything = True
                self._candidates = None
            self.prompt(_PICK)
            return
        if self._await is not None:
            self.on_option("")
            return
        if self._made:
            self.ctx.echo(tr("BOUNDARY created {n} polyline(s)", n=self._made))
        self.ctx.finish()

    # -- points ------------------------------------------------------------------
    def on_point(self, point: Point) -> None:
        services = self.ctx.services
        if self._await is not None:
            return
        if self._picking_set:
            entity = services.pick_entity(point) if services else None
            if entity is not None and entity not in self._candidates:
                self._candidates.append(entity)
                self.ctx.echo(tr("1 found"))
            self.prompt("Select objects (Enter when done):")
            return
        region = self._region(point)
        if region is None:
            self.ctx.echo(tr("No closed boundary found at that point."))
            self.prompt(_PICK)
            return
        outer, islands = region
        loops = [outer] + (list(islands) if type(self)._islands else [])
        # the curves come back as curved segments, not as the tracer's
        # chords (#83: the boundary drifted off an arc when zoomed in)
        from core.hatch_boundary import loop_with_bulges

        commands = [actions.add_polyline_ex(
                        [(x, y, 0.0, 0.0, b) for x, y, b
                         in loop_with_bulges(loop, self._source_entities(loop))],
                        closed=True, name="BOUNDARY")
                    for loop in loops if len(loop) >= 3]
        if not commands:
            self.ctx.echo(tr("No closed boundary found at that point."))
            self.prompt(_PICK)
            return
        self.ctx.execute(CompositeCommand("BOUNDARY", commands)
                         if len(commands) > 1 else commands[0])
        self._made += len(commands)
        self.ctx.echo(tr("{n} loop(s) extracted.", n=len(commands)))
        self.ctx.echo(tr("{n} Polyline(s) created", n=len(commands)))
        self.prompt(_PICK)

    def _source_entities(self, loop) -> list:
        """The objects a loop may run along: the boundary set, or what the
        pick index finds over the loop's extents."""
        if self._candidates is not None:
            return list(self._candidates)
        index = getattr(self.ctx.services, "index", None)
        if index is None:
            return []
        xs, ys = [p[0] for p in loop], [p[1] for p in loop]
        pad = max(max(xs) - min(xs), max(ys) - min(ys)) * 1e-6
        handles = index.crossing((min(xs) - pad, min(ys) - pad,
                                  max(xs) + pad, max(ys) + pad))
        return [e for h in handles if (e := index.entity(h)) is not None]

    def _region(self, point: Point):
        services = self.ctx.services
        if services is None:
            return None
        if self._candidates is not None:
            from core.hatch_boundary import region_at_point

            return region_at_point(self._candidates, point)
        return services.hatch_region_at(point)


BOUNDARY_TOOL_CLASSES = {"BOUNDARY": BoundaryTool, "-BOUNDARY": BoundaryTool}
