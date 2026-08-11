# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""STRETCH, BREAK and JOIN — the prompts.

Wording follows the AutoCAD Command Reference (STRETCH p.1851, BREAK p.269,
JOIN p.1013). The geometry is in ``core.modify``, so the whole flow is
testable without a GUI.
"""
from __future__ import annotations

from core import modify
from core.i18n import tr
from tools.base import Point, Tool


class StretchTool(Tool):
    """STRETCH: what the crossing window caught moves, the rest holds."""

    wants_selection = True

    def start(self) -> None:
        self.name = "STRETCH"
        self._entities: list = []
        self._rects: list = []
        self._base: Point | None = None
        self.ctx.echo(tr("Select objects to stretch by crossing-window or "
                         "crossing-polygon..."))

    def selection_prompt(self) -> str:
        return tr("Select objects (Enter when done):")

    def on_selection(self, entities: list) -> None:
        if not entities:
            self.ctx.finish()
            return
        self._entities = entities
        services = self.ctx.services
        getter = getattr(services, "crossing_rects", None)
        self._rects = list(getter()) if getter else []
        if not self._rects:
            # Picked one by one: AutoCAD moves those rather than stretching
            # them, which is what an all-covering rectangle produces here.
            self._rects = [(-1e18, -1e18, 1e18, 1e18)]
        self.ctx.prompt(tr("Specify base point or [Displacement] "
                           "<Displacement>:"))

    def on_point(self, point: Point) -> None:
        if self._base is None:
            self._base = point
            self.last_point = point
            self.ctx.prompt(
                tr("Specify second point or <use first point as displacement>:"))
            return
        self._commit(point[0] - self._base[0], point[1] - self._base[1])

    def on_enter(self) -> None:
        if self._base is not None:
            # Enter at the second prompt: the first point IS the displacement.
            self._commit(self._base[0], self._base[1])
            return
        self.ctx.finish()

    def _commit(self, dx: float, dy: float) -> None:
        self.ctx.execute(
            modify.stretch_entities(self._entities, self._rects, dx, dy))
        self.ctx.echo(tr("{count} stretched.", count=len(self._entities)))
        self.ctx.finish()

    def preview_segments(self, cursor: Point):
        return [(self._base, cursor)] if self._base else []


class BreakTool(Tool):
    """BREAK: two points, and what lies between them goes."""

    entity_picker = True

    def start(self) -> None:
        self.name = "BREAK"
        self._entity = None
        self._first: Point | None = None
        self._await_first = False
        self.ctx.prompt(tr("Select object:"))

    def on_option(self, text: str) -> bool:
        token = text.strip().upper()
        if self._entity is not None and token in ("F", "FIRST"):
            self._await_first = True
            self.entity_picker = False       # a real point now, so snap it
            self.ctx.prompt(tr("Specify first break point:"))
            return True
        return False

    def on_point(self, point: Point) -> None:
        if self._entity is None:
            services = self.ctx.services
            entity = services.pick_entity(point) if services else None
            if entity is None:
                self.ctx.prompt(tr("Nothing selected. Select object:"))
                return
            if modify.break_pieces(entity, point, point) is None:
                self.ctx.echo(
                    tr("{kind} cannot be broken.", kind=entity.dxftype()))
                self.ctx.finish()
                return
            self._entity = entity
            # Picking the object also sets the first break point (BREAK,
            # p.269) — until the user says First point.
            self._first = point
            self.entity_picker = False
            self.ctx.prompt(
                tr("Specify second break point or [First point]:"))
            return

        if self._await_first:
            self._first = point
            self._await_first = False
            self.ctx.prompt(tr("Specify second break point:"))
            return

        command = modify.break_entity(self._entity, self._first, point)
        if command is None:
            self.ctx.echo(tr("{kind} cannot be broken.",
                             kind=self._entity.dxftype()))
        else:
            self.ctx.execute(command)
        self.ctx.finish()


class JoinTool(Tool):
    """JOIN: collinear lines, arcs of one circle, or a contiguous chain."""

    wants_selection = True

    _REASONS = {
        "need": "JOIN needs at least two objects.",
        "collinear": "The lines are not collinear — JOIN needs them on the "
                     "same infinite line.",
        "same circle": "The arcs do not lie on the same circle.",
        "contiguous": "The objects are not contiguous — JOIN needs them "
                      "end to end.",
        "type": "Those objects cannot be joined to each other.",
    }

    def start(self) -> None:
        self.name = "JOIN"

    def selection_prompt(self) -> str:
        return tr("Select source object or multiple objects to join at once:")

    def on_selection(self, entities: list) -> None:
        if not entities:
            self.ctx.finish()
            return
        command, reason = modify.join_entities(entities)
        if command is None:
            self.ctx.echo(tr(self._REASONS.get(reason, self._REASONS["type"])))
        else:
            self.ctx.execute(command)
            self.ctx.echo(tr("{count} objects joined into one.",
                             count=len(entities)))
        self.ctx.finish()


MODIFY_TOOL_CLASSES = {
    "STRETCH": StretchTool,
    "BREAK": BreakTool,
    "JOIN": JoinTool,
}
