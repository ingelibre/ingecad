# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Dimension tools: DIMLINEAR, DIMALIGNED, DIMRADIUS, DIMDIAMETER.

Each follows AutoCAD's prompt sequence and creates the dimension with the
current dimension style ($DIMSTYLE). Linear picks two extension-line origins
then the dimension-line location (which also chooses horizontal vs vertical);
aligned is parallel to the two points; radius/diameter select an arc or circle.
"""
from __future__ import annotations

from core import actions
from core.i18n import tr
from tools.base import Point, Tool


class _TwoPointDim(Tool):
    """Shared flow: origin, second origin, then dimension-line location."""

    def start(self) -> None:
        self._p1: Point | None = None
        self._p2: Point | None = None
        self.ctx.prompt(tr("Specify first extension line origin:"))

    def _make(self, location: Point):
        raise NotImplementedError

    def on_point(self, point: Point) -> None:
        if self._p1 is None:
            self._p1 = point
            self.last_point = point
            self.ctx.prompt(tr("Specify second extension line origin:"))
        elif self._p2 is None:
            self._p2 = point
            self.last_point = point
            self.ctx.prompt(tr("Specify dimension line location:"))
        else:
            self.ctx.execute(self._make(point))
            self.ctx.finish()

    def preview_segments(self, cursor: Point):
        if self._p1 is not None and self._p2 is None:
            return [(self._p1, cursor)]
        if self._p2 is not None:
            return [(self._p1, self._p2)]
        return []


class DimLinearTool(_TwoPointDim):
    def start(self) -> None:
        self.name = "DIMLINEAR"
        super().start()

    def _make(self, location: Point):
        return actions.dim_linear(self._p1, self._p2, location)


class DimAlignedTool(_TwoPointDim):
    def start(self) -> None:
        self.name = "DIMALIGNED"
        super().start()

    def _make(self, location: Point):
        return actions.dim_aligned(self._p1, self._p2, location)


class _CurvedDim(Tool):
    """Shared flow: select an arc/circle, then the dimension-line location."""

    entity_picker = True   # object picking suppresses osnap, AutoCAD-style

    def start(self) -> None:
        self._ent = None
        self.ctx.prompt(tr("Select arc or circle:"))

    def _make(self, center, radius, location):
        raise NotImplementedError

    def on_point(self, point: Point) -> None:
        if self._ent is None:
            e = self.ctx.services.pick_entity(point) if self.ctx.services else None
            if e is None or e.dxftype() not in ("CIRCLE", "ARC"):
                self.ctx.echo(tr("Select an arc or circle."))
                return
            self._ent = e
            self.ctx.prompt(tr("Specify dimension line location:"))
        else:
            c = self._ent.dxf.center
            self.ctx.execute(self._make((c.x, c.y), self._ent.dxf.radius, point))
            self.ctx.finish()


class DimRadiusTool(_CurvedDim):
    def start(self) -> None:
        self.name = "DIMRADIUS"
        super().start()

    def _make(self, center, radius, location):
        return actions.dim_radius(center, radius, location)


class DimDiameterTool(_CurvedDim):
    def start(self) -> None:
        self.name = "DIMDIAMETER"
        super().start()

    def _make(self, center, radius, location):
        return actions.dim_diameter(center, radius, location)


DIM_TOOL_CLASSES = {
    "DIMLINEAR": DimLinearTool,
    "DIMALIGNED": DimAlignedTool,
    "DIMRADIUS": DimRadiusTool,
    "DIMDIAMETER": DimDiameterTool,
}
