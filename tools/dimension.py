# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Dimension tools: DIMLINEAR, DIMALIGNED, DIMRADIUS, DIMDIAMETER.

Each follows AutoCAD's prompt sequence and creates the dimension with the
current dimension style ($DIMSTYLE). All of them offer AutoCAD's Mtext/Text/
Angle options at the location prompt (Text: ``<>`` stands for the measured
value, a space suppresses the text; Angle rotates the text only). DIMLINEAR
adds Horizontal/Vertical/Rotated, and its select-object mode handles lines,
arcs, circles (quadrant rule) and polyline segments.
"""
from __future__ import annotations

import math

from core import actions
from core.i18n import tr
from tools.base import Point, Tool


def _segment_distance(p: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy or 1.0
    u = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
    return math.dist(p, (a[0] + u * dx, a[1] + u * dy))


def _entity_endpoints(entity, pick: Point, quadrant_rule: bool = False):
    """The two extension-line origins for a selected object, or None.

    ``quadrant_rule`` is DIMLINEAR's official circle behavior: a pick near
    the N/S quadrant gives a horizontal dimension (W-E diameter endpoints),
    near E/W a vertical one. Without it (DIMALIGNED) the diameter through
    the pick point is used.
    """
    t = entity.dxftype()
    if t == "LINE":
        s, e = entity.dxf.start, entity.dxf.end
        return (s.x, s.y), (e.x, e.y)
    if t == "ARC":
        c, r = entity.dxf.center, entity.dxf.radius
        a0 = math.radians(entity.dxf.start_angle)
        a1 = math.radians(entity.dxf.end_angle)
        return ((c.x + r * math.cos(a0), c.y + r * math.sin(a0)),
                (c.x + r * math.cos(a1), c.y + r * math.sin(a1)))
    if t == "CIRCLE":
        c, r = entity.dxf.center, entity.dxf.radius
        vx, vy = pick[0] - c.x, pick[1] - c.y
        if quadrant_rule:
            if abs(vy) >= abs(vx):          # near N/S -> horizontal dimension
                return (c.x - r, c.y), (c.x + r, c.y)
            return (c.x, c.y - r), (c.x, c.y + r)
        d = math.hypot(vx, vy) or 1.0
        ux, uy = vx / d, vy / d
        return (c.x - r * ux, c.y - r * uy), (c.x + r * ux, c.y + r * uy)
    if t == "LWPOLYLINE":
        pts = [(p[0], p[1]) for p in entity.get_points("xy")]
        if len(pts) < 2:
            return None
        segs = list(zip(pts, pts[1:]))
        if entity.closed:
            segs.append((pts[-1], pts[0]))
        a, b = min(segs, key=lambda s: _segment_distance(pick, s[0], s[1]))
        return a, b
    return None


class _DimTextMixin:
    """AutoCAD's Mtext/Text/Angle options, shared by every dimension tool."""

    def _reset_text_state(self) -> None:
        self._text = "<>"
        self._text_rotation: float | None = None
        self._pending: str | None = None

    def _location_prompt(self) -> str:
        return tr("Specify dimension line location or [Mtext/Text/Angle]:")

    def _measured(self) -> float:
        """Representative measurement for the ``<measured>`` default."""
        raise NotImplementedError

    def _preview_text(self, measurement: float) -> str:
        if self._text == " ":                # a space suppresses the text
            return ""
        formatted = f"{measurement:.2f}"
        if self._text and self._text != "<>":
            return self._text.replace("<>", formatted, 1)
        return formatted

    def _text_options(self, raw: str, ready: bool) -> bool:
        """Handle option keys and their follow-up input. True if consumed."""
        if self._pending == "text":
            self._text = raw if raw else "<>"
            self._pending = None
            self.ctx.prompt(self._location_prompt())
            return True
        if self._pending == "textangle":
            try:
                self._text_rotation = float(raw)
            except ValueError:
                self.ctx.echo(tr("Requires a numeric angle."))
                return True
            self._pending = None
            self.ctx.prompt(self._location_prompt())
            return True
        if not ready:
            return False
        key = raw.upper()
        # Mtext falls back to the same single-line prompt (honest v0.2).
        if key in ("M", "MTEXT", "T", "TEXT"):
            self._pending = "text"
            self.ctx.prompt(tr("Enter dimension text <{measured}>:",
                               measured=f"{self._measured():.2f}"))
            return True
        if key in ("A", "ANGLE"):
            self._pending = "textangle"
            self.ctx.prompt(tr("Specify angle of dimension text:"))
            return True
        return False

    def _text_enter(self) -> bool:
        """Enter during a pending Text/Angle prompt keeps the default."""
        if self._pending == "text":
            self._text = "<>"
            self._pending = None
            self.ctx.prompt(self._location_prompt())
            return True
        if self._pending == "textangle":
            self._pending = None
            self.ctx.prompt(self._location_prompt())
            return True
        return False


class _TwoPointDim(_DimTextMixin, Tool):
    """origin, second origin (or Enter -> select an object), then location."""

    # DIMLINEAR's circle rule; DIMALIGNED dimensions the pick-point diameter.
    select_quadrant_rule = False

    def start(self) -> None:
        self._p1: Point | None = None
        self._p2: Point | None = None
        self._select_mode = False
        self._reset_text_state()
        self.ctx.prompt(
            tr("Specify first extension line origin or <select object>:"))

    def _make(self, location: Point):
        raise NotImplementedError

    def _frame(self, cursor: Point):
        """(d1, d2): the dimension-line endpoints for the current cursor."""
        raise NotImplementedError

    def _measurement(self, cursor: Point) -> float:
        raise NotImplementedError

    def preview_dimension(self, cursor: Point):
        """A real-looking dimension preview (frame + measurement) or None."""
        if self._p1 is None or self._p2 is None:
            return None
        d1, d2 = self._frame(cursor)
        return {"p1": self._p1, "p2": self._p2, "d1": d1, "d2": d2,
                "text": self._preview_text(self._measurement(cursor))}

    def on_enter(self) -> None:
        if self._text_enter():
            return
        # Enter on the first prompt switches to AutoCAD's select-object mode.
        if self._p1 is None and not self._select_mode:
            self._select_mode = True
            self.entity_picker = True   # raw cursor for object picking
            self.ctx.prompt(tr("Select object to dimension:"))
            return
        self.ctx.finish()

    def on_option(self, text: str) -> bool:
        return self._text_options(text, ready=self._p2 is not None)

    def on_point(self, point: Point) -> None:
        if self._pending is not None:
            return                       # a text/angle prompt is waiting
        if self._select_mode and self._p1 is None:
            e = self.ctx.services.pick_entity(point) if self.ctx.services else None
            ends = (_entity_endpoints(e, point, self.select_quadrant_rule)
                    if e is not None else None)
            if ends is None:
                self.ctx.echo(
                    tr("Select a line, arc, circle, or polyline segment."))
                return
            self._p1, self._p2 = ends
            self.entity_picker = False   # snap returns for the line location
            self.ctx.prompt(self._location_prompt())
            return
        if self._p1 is None:
            self._p1 = point
            self.last_point = point
            self.ctx.prompt(tr("Specify second extension line origin:"))
        elif self._p2 is None:
            self._p2 = point
            self.last_point = point
            self.ctx.prompt(self._location_prompt())
        else:
            self.ctx.execute(self._make(point))
            self.ctx.finish()

    def preview_segments(self, cursor: Point):
        # Only the phase-1 rubber band; the location phase draws a rich
        # dimension preview via preview_dimension instead.
        if self._p1 is not None and self._p2 is None:
            return [(self._p1, cursor)]
        return []


class DimLinearTool(_TwoPointDim):
    select_quadrant_rule = True

    def start(self) -> None:
        self.name = "DIMLINEAR"
        self._forced_angle: float | None = None
        super().start()

    def _location_prompt(self) -> str:
        return tr("Specify dimension line location or "
                  "[Mtext/Text/Angle/Horizontal/Vertical/Rotated]:")

    def on_option(self, text: str) -> bool:
        if self._pending == "dimangle":
            try:
                self._forced_angle = float(text)
            except ValueError:
                self.ctx.echo(tr("Requires a numeric angle."))
                return True
            self._pending = None
            self.ctx.prompt(self._location_prompt())
            return True
        if super().on_option(text):
            return True
        if self._p2 is None:
            return False
        key = text.upper()
        if key in ("H", "HORIZONTAL"):
            self._forced_angle = 0.0
            self.ctx.prompt(self._location_prompt())
            return True
        if key in ("V", "VERTICAL"):
            self._forced_angle = 90.0
            self.ctx.prompt(self._location_prompt())
            return True
        if key in ("R", "ROTATED"):
            self._pending = "dimangle"
            self.ctx.prompt(tr("Specify angle of dimension line <0>:"))
            return True
        return False

    def on_enter(self) -> None:
        if self._pending == "dimangle":
            self._forced_angle = 0.0
            self._pending = None
            self.ctx.prompt(self._location_prompt())
            return
        super().on_enter()

    def _angle_for(self, cursor: Point) -> float:
        if self._forced_angle is not None:
            return self._forced_angle
        mid = ((self._p1[0] + self._p2[0]) / 2.0,
               (self._p1[1] + self._p2[1]) / 2.0)
        horizontal = abs(cursor[1] - mid[1]) >= abs(cursor[0] - mid[0])
        return 0.0 if horizontal else 90.0

    def _make(self, location: Point):
        return actions.dim_linear(self._p1, self._p2, location,
                                  angle=self._forced_angle, text=self._text,
                                  text_rotation=self._text_rotation)

    def _frame(self, cursor: Point):
        a = math.radians(self._angle_for(cursor))
        dx, dy = math.cos(a), math.sin(a)

        def proj(p: Point) -> Point:
            t = (p[0] - cursor[0]) * dx + (p[1] - cursor[1]) * dy
            return (cursor[0] + t * dx, cursor[1] + t * dy)
        return proj(self._p1), proj(self._p2)

    def _measurement(self, cursor: Point) -> float:
        a = math.radians(self._angle_for(cursor))
        return abs((self._p2[0] - self._p1[0]) * math.cos(a)
                   + (self._p2[1] - self._p1[1]) * math.sin(a))

    def _measured(self) -> float:
        dx = abs(self._p2[0] - self._p1[0])
        dy = abs(self._p2[1] - self._p1[1])
        if self._forced_angle is not None:
            a = math.radians(self._forced_angle)
            return abs((self._p2[0] - self._p1[0]) * math.cos(a)
                       + (self._p2[1] - self._p1[1]) * math.sin(a))
        return dx if dx >= dy else dy


class DimAlignedTool(_TwoPointDim):
    def start(self) -> None:
        self.name = "DIMALIGNED"
        super().start()

    def _make(self, location: Point):
        return actions.dim_aligned(self._p1, self._p2, location,
                                   text=self._text,
                                   text_rotation=self._text_rotation)

    def _frame(self, cursor: Point):
        p1, p2 = self._p1, self._p2
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length
        dist = (cursor[0] - p1[0]) * nx + (cursor[1] - p1[1]) * ny
        return ((p1[0] + nx * dist, p1[1] + ny * dist),
                (p2[0] + nx * dist, p2[1] + ny * dist))

    def _measurement(self, cursor: Point) -> float:
        return math.dist(self._p1, self._p2)

    def _measured(self) -> float:
        return math.dist(self._p1, self._p2)


class _CurvedDim(_DimTextMixin, Tool):
    """Select an arc/circle, then the dimension-line location."""

    entity_picker = True   # object picking suppresses osnap, AutoCAD-style

    def start(self) -> None:
        self._ent = None
        self._reset_text_state()
        self.ctx.prompt(tr("Select arc or circle:"))

    def _make(self, center, radius, location):
        raise NotImplementedError

    def on_option(self, text: str) -> bool:
        return self._text_options(text, ready=self._ent is not None)

    def on_enter(self) -> None:
        if self._text_enter():
            return
        self.ctx.finish()

    def on_point(self, point: Point) -> None:
        if self._pending is not None:
            return
        if self._ent is None:
            e = self.ctx.services.pick_entity(point) if self.ctx.services else None
            if e is None or e.dxftype() not in ("CIRCLE", "ARC"):
                self.ctx.echo(tr("Select an arc or circle."))
                return
            self._ent = e
            self.ctx.prompt(self._location_prompt())
        else:
            c = self._ent.dxf.center
            self.ctx.execute(self._make((c.x, c.y), self._ent.dxf.radius, point))
            self.ctx.finish()

    def preview_segments(self, cursor: Point):
        if self._ent is None:
            return []
        c = self._ent.dxf.center
        return [((c.x, c.y), cursor)]


class DimRadiusTool(_CurvedDim):
    def start(self) -> None:
        self.name = "DIMRADIUS"
        super().start()

    def _measured(self) -> float:
        return float(self._ent.dxf.radius)

    def _make(self, center, radius, location):
        return actions.dim_radius(center, radius, location, text=self._text,
                                  text_rotation=self._text_rotation)


class DimDiameterTool(_CurvedDim):
    def start(self) -> None:
        self.name = "DIMDIAMETER"
        super().start()

    def _measured(self) -> float:
        return 2.0 * float(self._ent.dxf.radius)

    def _make(self, center, radius, location):
        return actions.dim_diameter(center, radius, location, text=self._text,
                                    text_rotation=self._text_rotation)


DIM_TOOL_CLASSES = {
    "DIMLINEAR": DimLinearTool,
    "DIMALIGNED": DimAlignedTool,
    "DIMRADIUS": DimRadiusTool,
    "DIMDIAMETER": DimDiameterTool,
}
