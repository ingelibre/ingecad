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


# DIMCONTINUE/DIMBASELINE chain from the last linear/aligned dimension of
# the session (official behavior); creation registers it here.
_LAST_DIM: list = [None]


def set_last_dimension(dim) -> None:
    _LAST_DIM[0] = dim


def last_dimension():
    """The session's last linear-family dimension, if it still exists."""
    d = _LAST_DIM[0]
    if d is not None and d.is_alive and (d.dxf.dimtype & 15) in (0, 1):
        return d
    return None


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
        return "Specify dimension line location or [Mtext/Text/Angle]:"

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
            self.prompt(self._location_prompt())
            return True
        if self._pending == "textangle":
            try:
                self._text_rotation = float(raw)
            except ValueError:
                self.ctx.echo(tr("Requires a numeric angle."))
                return True
            self._pending = None
            self.prompt(self._location_prompt())
            return True
        if not ready:
            return False
        # The resolver first, so the localized keyword and _global form reach
        # the same branches as the English key.
        key = self.option(raw) or raw.upper()
        # Mtext falls back to the same single-line prompt (honest v0.2).
        if key in ("M", "MTEXT", "T", "TEXT"):
            self._pending = "text"
            self.prompt("Enter dimension text <{measured}>:",
                        measured=f"{self._measured():.2f}")
            return True
        if key in ("A", "ANGLE"):
            self._pending = "textangle"
            self.prompt("Specify angle of dimension text:")
            return True
        return False

    def wants_raw_text(self) -> bool:
        # "Enter dimension text <>:" takes literal text — "<> m" carries a
        # space, so Space must not execute there (AutoCAD behaves the same).
        return self._pending == "text"

    def _text_enter(self) -> bool:
        """Enter during a pending Text/Angle prompt keeps the default."""
        if self._pending == "text":
            self._text = "<>"
            self._pending = None
            self.prompt(self._location_prompt())
            return True
        if self._pending == "textangle":
            self._pending = None
            self.prompt(self._location_prompt())
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
        self.prompt("Specify first extension line origin or <select object>:")

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
        cursor = self._adjust_location(cursor)
        d1, d2 = self._frame(cursor)
        return {"p1": self._p1, "p2": self._p2, "d1": d1, "d2": d2,
                "text": self._preview_text(self._measurement(cursor))}

    # -- dimension-line alignment (the green square) ---------------------------
    align_marker: Point | None = None

    def _adjust_location(self, point: Point) -> Point:
        """AutoCAD's chained-dimension aid: placing the line NEAR an
        existing parallel dimension's line snaps to the same offset, so
        adjacent dimensions align — announced by a green square marker.
        One source of truth: the preview and the placing click both come
        through here, so what the marker promises is what the click does."""
        self.align_marker = None
        threshold = self._align_threshold()
        if threshold is None:
            return point
        angle = self._align_angle(point)
        if angle is None:
            return point
        axis = 1 if angle == 0.0 else 0     # horizontal dims share a Y
        best = None
        for dim in self._existing_dims():
            if abs((dim.dxf.get("angle", 0.0) % 180.0) - angle) > 0.01:
                continue
            defpoint = dim.dxf.get("defpoint", None)
            if defpoint is None:
                continue
            coord = (defpoint.x, defpoint.y)[axis]
            distance = abs(point[axis] - coord)
            if distance <= threshold and (best is None or distance < best[0]):
                best = (distance, coord)
        if best is None:
            return point
        adjusted = list(point)
        adjusted[axis] = best[1]
        self.align_marker = (adjusted[0], adjusted[1])
        return tuple(adjusted)

    def _align_threshold(self) -> float | None:
        """SNAP_PX in world units, or None when no view is around."""
        services = self.ctx.services
        window = getattr(services, "window", None)
        view = getattr(getattr(window, "viewport", None), "view", None)
        if view is None or not getattr(view, "scale", 0):
            return None
        return 12.0 / view.scale

    def _align_angle(self, point: Point):
        """0/90 when this tool draws an axis-parallel dimension line."""
        angle = getattr(self, "_forced_angle", None)
        if angle is None and hasattr(self, "_angle_for"):
            angle = self._angle_for(point)
        if angle in (0.0, 90.0):
            return angle
        return None

    def _existing_dims(self):
        window = getattr(self.ctx.services, "window", None)
        document = getattr(window, "document", None)
        if document is None:
            return []
        return [e for e in document.modelspace().query("DIMENSION")
                if (e.dxf.dimtype & 7) in (0, 1)]

    def on_enter(self) -> None:
        if self._text_enter():
            return
        # Enter on the first prompt switches to AutoCAD's select-object mode.
        if self._p1 is None and not self._select_mode:
            self._select_mode = True
            self.entity_picker = True   # raw cursor for object picking
            self.prompt("Select object to dimension:")
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
            self.prompt(self._location_prompt())
            return
        if self._p1 is None:
            self._p1 = point
            self.last_point = point
            self.prompt("Specify second extension line origin:")
        elif self._p2 is None:
            self._p2 = point
            self.last_point = point
            self.prompt(self._location_prompt())
        else:
            point = self._adjust_location(point)
            cmd = self._make(point)
            self.ctx.execute(cmd)
            if cmd.dim is not None and (cmd.dim.dxf.dimtype & 15) in (0, 1):
                set_last_dimension(cmd.dim)
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
        return ("Specify dimension line location or "
                "[Mtext/Text/Angle/Horizontal/Vertical/Rotated]:")

    def on_option(self, text: str) -> bool:
        if self._pending == "dimangle":
            try:
                self._forced_angle = float(text)
            except ValueError:
                self.ctx.echo(tr("Requires a numeric angle."))
                return True
            self._pending = None
            self.prompt(self._location_prompt())
            return True
        if super().on_option(text):
            return True
        if self._p2 is None:
            return False
        # The resolver first: it turns the localized keyword, or
        # AutoCAD's _global form, into the English key the
        # branches below have always compared against.
        key = self.option(text) or text.upper()
        if key in ("H", "HORIZONTAL"):
            self._forced_angle = 0.0
            self.prompt(self._location_prompt())
            return True
        if key in ("V", "VERTICAL"):
            self._forced_angle = 90.0
            self.prompt(self._location_prompt())
            return True
        if key in ("R", "ROTATED"):
            self._pending = "dimangle"
            self.prompt("Specify angle of dimension line <0>:")
            return True
        return False

    def on_enter(self) -> None:
        if self._pending == "dimangle":
            self._forced_angle = 0.0
            self._pending = None
            self.prompt(self._location_prompt())
            return
        super().on_enter()

    def _angle_for(self, cursor: Point) -> float:
        if self._forced_angle is not None:
            return self._forced_angle
        return actions.linear_dim_angle(self._p1, self._p2, cursor)

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
        self.prompt("Select arc or circle:")

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
            self.prompt(self._location_prompt())
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


class DimAngularTool(_DimTextMixin, Tool):
    """DIMANGULAR: arc / circle / two lines / Enter-for-vertex, then the
    dimension arc location (which picks the dimensioned angle region)."""

    entity_picker = True

    def start(self) -> None:
        self.name = "DIMANGULAR"
        self._reset_text_state()
        self._mode = "select"
        self._vertex: Point | None = None
        self._p1: Point | None = None
        self._p2: Point | None = None
        self._line1 = None
        self._line2 = None
        self._region_free = True    # arc path keeps its own included angle
        self._quadrant: Point | None = None
        self.prompt("Select arc, circle, line, or <specify vertex>:")

    def _location_prompt(self) -> str:
        return ("Specify dimension arc line location or "
                "[Mtext/Text/Angle/Quadrant]:")

    def _measured(self) -> float:
        if self._line1 and self._line2:
            region = self._quadrant
            if region is not None:
                res = actions.angular_from_lines(self._line1, self._line2,
                                                 region)
                if res is not None:
                    return actions.angular_measurement(*res)
            a1 = math.atan2(self._line1[1][1] - self._line1[0][1],
                            self._line1[1][0] - self._line1[0][0])
            a2 = math.atan2(self._line2[1][1] - self._line2[0][1],
                            self._line2[1][0] - self._line2[0][0])
            return abs(math.degrees(a2 - a1)) % 180.0
        if self._vertex and self._p1 and self._p2:
            p1, p2 = self._p1, self._p2
            if self._region_free and self._quadrant is not None:
                p1, p2 = actions.angular_points(self._vertex, p1, p2,
                                                self._quadrant)
            return actions.angular_measurement(self._vertex, p1, p2)
        return 0.0

    def on_enter(self) -> None:
        if self._text_enter():
            return
        if self._mode == "select":
            self._mode = "vertex"
            self.entity_picker = False
            self.prompt("Specify angle vertex:")
            return
        self.ctx.finish()

    def on_option(self, text: str) -> bool:
        if self._text_options(text, ready=self._mode == "locate"):
            return True
        if self._mode == "locate" and self.option(text) == "Q":
            self._pending = "quadrant"
            self.prompt("Specify quadrant:")
            return True
        return False

    def on_point(self, point: Point) -> None:
        if self._pending == "quadrant":
            self._quadrant = point
            self._pending = None
            self.prompt(self._location_prompt())
            return
        if self._pending is not None:
            return
        mode = self._mode
        if mode == "select":
            e = self.ctx.services.pick_entity(point) if self.ctx.services else None
            t = e.dxftype() if e is not None else None
            if t == "ARC":
                c, r = e.dxf.center, e.dxf.radius
                a0 = math.radians(e.dxf.start_angle)
                a1 = math.radians(e.dxf.end_angle)
                self._vertex = (c.x, c.y)
                self._p1 = (c.x + r * math.cos(a0), c.y + r * math.sin(a0))
                self._p2 = (c.x + r * math.cos(a1), c.y + r * math.sin(a1))
                self._region_free = False
                self._to_locate()
            elif t == "CIRCLE":
                c, r = e.dxf.center, e.dxf.radius
                a = math.atan2(point[1] - c.y, point[0] - c.x)
                self._vertex = (c.x, c.y)
                self._p1 = (c.x + r * math.cos(a), c.y + r * math.sin(a))
                self._mode = "circle2"
                self.entity_picker = False
                self.prompt("Specify second angle endpoint:")
            elif t == "LINE":
                s, w = e.dxf.start, e.dxf.end
                self._line1 = ((s.x, s.y), (w.x, w.y))
                self._mode = "line2"
                self.prompt("Select second line:")
            else:
                self.ctx.echo(tr("Select an arc, circle, or line."))
        elif mode == "line2":
            e = self.ctx.services.pick_entity(point) if self.ctx.services else None
            if e is None or e.dxftype() != "LINE":
                self.ctx.echo(tr("Select second line:"))
                return
            s, w = e.dxf.start, e.dxf.end
            line2 = ((s.x, s.y), (w.x, w.y))
            if actions.line_intersection(self._line1, line2) is None:
                self.ctx.echo(tr("Lines are parallel."))
                return
            self._line2 = line2
            self._to_locate()
        elif mode == "vertex":
            self._vertex = point
            self.last_point = point
            self._mode = "vp1"
            self.prompt("Specify first angle endpoint:")
        elif mode == "vp1":
            self._p1 = point
            self._mode = "vp2"
            self.prompt("Specify second angle endpoint:")
        elif mode == "vp2":
            self._p2 = point
            self._to_locate()
        else:   # locate
            region = self._quadrant if self._quadrant is not None else point
            if self._line2 is not None:
                res = actions.angular_from_lines(self._line1, self._line2,
                                                 region)
                if res is None:
                    self.ctx.echo(tr("Lines are parallel."))
                    return
                vertex, p1, p2 = res
                cmd = actions.dim_angular(vertex, p1, p2, point,
                                          text=self._text,
                                          text_rotation=self._text_rotation)
            else:
                cmd = actions.dim_angular(
                    self._vertex, self._p1, self._p2, point,
                    region=region if self._region_free else None,
                    text=self._text, text_rotation=self._text_rotation)
            self.ctx.execute(cmd)
            self.ctx.finish()

    def _to_locate(self) -> None:
        self._mode = "locate"
        self.entity_picker = False
        self.prompt(self._location_prompt())

    def preview_segments(self, cursor: Point):
        if self._mode == "locate" and self._vertex is not None:
            return [(self._vertex, cursor)]
        if self._mode == "vp1" and self._vertex is not None:
            return [(self._vertex, cursor)]
        if self._mode == "vp2" and self._vertex is not None:
            return [(self._vertex, self._p1), (self._vertex, cursor)]
        return []


class DimArcTool(_DimTextMixin, Tool):
    """DIMARC: arc-length dimension of an arc or polyline arc segment."""

    entity_picker = True

    def start(self) -> None:
        self.name = "DIMARC"
        self._reset_text_state()
        self._arc = None            # (center, radius, start_deg, end_deg)
        self._partial_first: float | None = None
        self.prompt("Select arc or polyline arc segment:")

    def _location_prompt(self) -> str:
        return ("Specify arc length dimension location or "
                "[Mtext/Text/Angle/Partial]:")

    def _measured(self) -> float:
        if self._arc is None:
            return 0.0
        _c, r, a0, a1 = self._arc
        return r * math.radians((a1 - a0) % 360.0 or 360.0)

    def on_option(self, text: str) -> bool:
        if self._text_options(text, ready=self._arc is not None):
            return True
        if self._arc is not None and self.option(text) == "P":
            self._pending = "partial1"
            self.prompt("Specify first point for arc length dimension:")
            return True
        return False

    def on_point(self, point: Point) -> None:
        if self._pending == "partial1":
            c, _r, a0, a1 = self._arc
            self._partial_first = actions.clamp_angle_to_arc(point, c, a0, a1)
            self._pending = "partial2"
            self.prompt("Specify second point for arc length dimension:")
            return
        if self._pending == "partial2":
            c, r, a0, a1 = self._arc
            first = self._partial_first
            second = actions.clamp_angle_to_arc(point, c, a0, a1)
            # order the two along the CCW sweep from the arc's start
            rel1 = (first - a0) % 360.0
            rel2 = (second - a0) % 360.0
            if rel1 > rel2:
                first, second = second, first
            self._arc = (c, r, first, second)
            self._pending = None
            self.prompt(self._location_prompt())
            return
        if self._pending is not None:
            return
        if self._arc is None:
            e = self.ctx.services.pick_entity(point) if self.ctx.services else None
            arc = self._arc_params(e, point) if e is not None else None
            if arc is None:
                self.ctx.echo(tr("Select arc or polyline arc segment:"))
                return
            self._arc = arc
            self.entity_picker = False
            self.prompt(self._location_prompt())
        else:
            c, r, a0, a1 = self._arc
            self.ctx.execute(actions.dim_arc(
                c, r, a0, a1, point,
                text=self._text, text_rotation=self._text_rotation))
            self.ctx.finish()

    @staticmethod
    def _arc_params(entity, pick: Point):
        t = entity.dxftype()
        if t == "ARC":
            c = entity.dxf.center
            return ((c.x, c.y), float(entity.dxf.radius),
                    float(entity.dxf.start_angle), float(entity.dxf.end_angle))
        if t == "LWPOLYLINE":
            from ezdxf.math import bulge_to_arc
            pts = list(entity.get_points("xyb"))
            segs = list(zip(pts, pts[1:]))
            if entity.closed and len(pts) > 1:
                segs.append((pts[-1], (*pts[0][:2], 0.0)))
            if not segs:
                return None
            a, b = min(segs, key=lambda s: _segment_distance(
                pick, (s[0][0], s[0][1]), (s[1][0], s[1][1])))
            if not a[2]:
                return None            # a straight segment, not an arc
            center, sa, ea, radius = bulge_to_arc(
                (a[0], a[1]), (b[0], b[1]), a[2])
            return ((center.x, center.y), float(radius),
                    math.degrees(sa) % 360.0, math.degrees(ea) % 360.0)
        return None

    def preview_segments(self, cursor: Point):
        if self._arc is None:
            return []
        return [(self._arc[0], cursor)]


class DimOrdinateTool(_DimTextMixin, Tool):
    """DIMORDINATE: X/Y datum of a feature, leader drag picks the axis."""

    def start(self) -> None:
        self.name = "DIMORDINATE"
        self._reset_text_state()
        self._feature: Point | None = None
        self._dtype: str | None = None
        self.prompt("Specify feature location:")

    def _location_prompt(self) -> str:
        return ("Specify leader endpoint or "
                "[Xdatum/Ydatum/Mtext/Text/Angle]:")

    def _measured(self) -> float:
        if self._feature is None:
            return 0.0
        return self._feature[1] if self._dtype == "Y" else self._feature[0]

    def on_option(self, text: str) -> bool:
        if self._text_options(text, ready=self._feature is not None):
            return True
        if self._feature is None:
            return False
        # The resolver first: it turns the localized keyword, or
        # AutoCAD's _global form, into the English key the
        # branches below have always compared against.
        key = self.option(text) or text.upper()
        if key in ("X", "XDATUM"):
            self._dtype = "X"
            self.prompt(self._location_prompt())
            return True
        if key in ("Y", "YDATUM"):
            self._dtype = "Y"
            self.prompt(self._location_prompt())
            return True
        return False

    def on_enter(self) -> None:
        if self._text_enter():
            return
        self.ctx.finish()

    def on_point(self, point: Point) -> None:
        if self._pending is not None:
            return
        if self._feature is None:
            self._feature = point
            self.last_point = point
            self.prompt(self._location_prompt())
            return
        self.ctx.execute(actions.dim_ordinate(
            self._feature, point, dtype=self._dtype,
            text=self._text, text_rotation=self._text_rotation))
        self.ctx.finish()

    def preview_segments(self, cursor: Point):
        if self._feature is None:
            return []
        return [(self._feature, cursor)]


class DimCenterTool(Tool):
    """DIMCENTER: center mark / center lines per DIMCEN. Plain LINEs."""

    entity_picker = True

    def start(self) -> None:
        self.name = "DIMCENTER"
        self.prompt("Select arc or circle:")

    def on_point(self, point: Point) -> None:
        e = self.ctx.services.pick_entity(point) if self.ctx.services else None
        if e is None or e.dxftype() not in ("CIRCLE", "ARC"):
            self.ctx.echo(tr("Select an arc or circle."))
            return
        cmd = actions.center_mark(e)
        if cmd is None:
            self.ctx.echo(tr("DIMCEN is 0 — no center mark drawn."))
        else:
            self.ctx.execute(cmd)
        self.ctx.finish()


class _ChainDim(Tool):
    """DIMCONTINUE/DIMBASELINE: chain new dimensions from a base linear or
    aligned dimension. The session's last one is picked up automatically;
    otherwise (or via the Select option) the user picks the base. Undo drops
    the last chained dimension without leaving the command."""

    BASELINE = False

    def start(self) -> None:
        self._base = last_dimension()
        self._prev_location: Point | None = None
        self._stack: list = []       # (base, prev_location) before each add
        if self._base is None:
            self._enter_select()
        else:
            self._prev_location = self._base_location(self._base)
            self.prompt(self._chain_prompt())

    def _chain_prompt(self) -> str:
        return ("Specify a second extension line origin or "
                "[Undo/Select] <Select>:")

    def _select_prompt(self) -> str:
        if self.BASELINE:
            return "Select base dimension:"
        return "Select continued dimension:"

    def _enter_select(self) -> None:
        self._selecting = True
        self.entity_picker = True
        self.prompt(self._select_prompt())

    @staticmethod
    def _base_location(base) -> Point:
        p = base.dxf.defpoint
        return (p.x, p.y)

    def on_enter(self) -> None:
        # Enter -> <Select> a new base; Enter at the select prompt ends.
        if getattr(self, "_selecting", False):
            self.ctx.finish()
            return
        self._enter_select()

    def on_option(self, text: str) -> bool:
        if getattr(self, "_selecting", False):
            return False
        # The resolver first: it turns the localized keyword, or
        # AutoCAD's _global form, into the English key the
        # branches below have always compared against.
        key = self.option(text) or text.upper()
        if key in ("U", "UNDO"):
            if not self._stack:
                self.ctx.echo(tr("Nothing to undo."))
                return True
            self.ctx.undo_last()
            self._base, self._prev_location = self._stack.pop()
            self.prompt(self._chain_prompt())
            return True
        if key in ("S", "SELECT"):
            self._enter_select()
            return True
        return False

    def on_point(self, point: Point) -> None:
        if getattr(self, "_selecting", False):
            e = self.ctx.services.pick_entity(point) if self.ctx.services else None
            if e is None or e.dxftype() != "DIMENSION" \
                    or (e.dxf.dimtype & 15) not in (0, 1):
                self.ctx.echo(tr("Select a linear or aligned dimension."))
                return
            self._base = e
            self._prev_location = self._base_location(e)
            self._selecting = False
            self.entity_picker = False
            self._stack.clear()
            self.prompt(self._chain_prompt())
            return
        base = self._base
        if base is None or not base.is_alive:
            self._enter_select()
            return
        aligned = (base.dxf.dimtype & 15) == 1
        b1 = base.dxf.defpoint2
        b2 = base.dxf.defpoint3
        p1 = (b1.x, b1.y) if self.BASELINE else (b2.x, b2.y)
        style = base.dxf.get("dimstyle", None)
        if self.BASELINE:
            location = self._baseline_location(p1, point)
        else:
            location = self._prev_location
        if aligned:
            cmd = actions.dim_aligned(p1, point, location, dimstyle=style)
        else:
            cmd = actions.dim_linear(p1, point, location,
                                     angle=base.dxf.get("angle", 0.0),
                                     dimstyle=style)
        self._stack.append((self._base, self._prev_location))
        self.ctx.execute(cmd)
        set_last_dimension(cmd.dim)
        if self.BASELINE:
            self._prev_location = location
        else:
            # the new dimension becomes the base: successive continuation
            self._base = cmd.dim
            self._prev_location = self._base_location(cmd.dim)
        self.prompt(self._chain_prompt())

    def _baseline_location(self, p1: Point, p2: Point) -> Point:
        """The previous dimension line shifted DIMDLI away from the points."""
        base = self._base
        dli = 3.75
        doc = base.doc
        style = base.dxf.get("dimstyle", None)
        if doc is not None and style and style in doc.dimstyles:
            dli = doc.dimstyles.get(style).dxf.get("dimdli", 3.75) or 3.75
        if (base.dxf.dimtype & 15) == 1:
            dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        else:
            a = math.radians(base.dxf.get("angle", 0.0))
            dx, dy = math.cos(a), math.sin(a)
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length
        prev = self._prev_location
        side = (prev[0] - p1[0]) * nx + (prev[1] - p1[1]) * ny
        if side < 0:
            nx, ny = -nx, -ny
        return (prev[0] + nx * dli, prev[1] + ny * dli)

    def preview_segments(self, cursor: Point):
        if getattr(self, "_selecting", False) or self._base is None:
            return []
        b = self._base.dxf.defpoint2 if self.BASELINE \
            else self._base.dxf.defpoint3
        return [((b.x, b.y), cursor)]


class DimContinueTool(_ChainDim):
    def start(self) -> None:
        self.name = "DIMCONTINUE"
        super().start()


class DimBaselineTool(_ChainDim):
    BASELINE = True

    def start(self) -> None:
        self.name = "DIMBASELINE"
        super().start()


class DimTextEditTool(Tool):
    """DIMTEDIT: move or realign an existing dimension's text."""

    entity_picker = True

    def start(self) -> None:
        self.name = "DIMTEDIT"
        self._dim = None
        self._pending_angle = False
        self.prompt("Select dimension:")

    def on_option(self, text: str) -> bool:
        if self._pending_angle:
            try:
                angle = float(text)
            except ValueError:
                self.ctx.echo(tr("Requires a numeric angle."))
                return True
            self.ctx.execute(actions.dim_text_edit(self._dim, angle=angle))
            self.ctx.finish()
            return True
        if self._dim is None:
            return False
        # The resolver first: it turns the localized keyword, or
        # AutoCAD's _global form, into the English key the
        # branches below have always compared against.
        key = self.option(text) or text.upper()
        halign = {"L": "left", "LEFT": "left", "R": "right", "RIGHT": "right",
                  "C": "center", "CENTER": "center"}.get(key)
        if halign:
            self.ctx.execute(actions.dim_text_edit(self._dim, halign=halign))
            self.ctx.finish()
            return True
        if key in ("H", "HOME"):
            self.ctx.execute(actions.dim_text_edit(self._dim, home=True))
            self.ctx.finish()
            return True
        if key in ("A", "ANGLE"):
            self._pending_angle = True
            self.prompt("Specify angle for dimension text:")
            return True
        return False

    def on_point(self, point: Point) -> None:
        if self._pending_angle:
            return
        if self._dim is None:
            e = self.ctx.services.pick_entity(point) if self.ctx.services else None
            if e is None or e.dxftype() not in ("DIMENSION", "ARC_DIMENSION"):
                self.ctx.echo(tr("Select dimension:"))
                return
            self._dim = e
            self.entity_picker = False
            self.prompt("Specify new location for dimension text or "
                        "[Left/Right/Center/Home/Angle]:")
            return
        self.ctx.execute(actions.dim_text_edit(self._dim, location=point))
        self.ctx.finish()


DIM_TOOL_CLASSES = {
    "DIMLINEAR": DimLinearTool,
    "DIMALIGNED": DimAlignedTool,
    "DIMRADIUS": DimRadiusTool,
    "DIMDIAMETER": DimDiameterTool,
    "DIMANGULAR": DimAngularTool,
    "DIMARC": DimArcTool,
    "DIMORDINATE": DimOrdinateTool,
    "DIMCENTER": DimCenterTool,
    "DIMCONTINUE": DimContinueTool,
    "DIMBASELINE": DimBaselineTool,
    "DIMTEDIT": DimTextEditTool,
}
