# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Drawing tools: LINE, CIRCLE, ARC, PLINE, RECTANG, POLYGON.

Prompt wording mirrors AutoCAD so the muscle memory transfers; every
mutation goes through core.actions Commands (exact undo).
"""
from __future__ import annotations

import math

from core import actions
from core.i18n import tr
from tools.base import Point, Tool


def _circle_preview(center: Point, radius: float, n: int = 48):
    pts = [
        (center[0] + radius * math.cos(i * math.tau / n),
         center[1] + radius * math.sin(i * math.tau / n))
        for i in range(n + 1)
    ]
    return list(zip(pts, pts[1:]))


# -- Continue chain (LINE/ARC/PLINE Enter-at-first-prompt) ----------------------
#
# AutoCAD: Enter at the first prompt continues from the endpoint of the most
# recently created line, polyline or arc; when that end belongs to an arc,
# the new segment is tangent to it (direction locked). Session state, like
# AutoCAD's — not persisted.
_CHAIN = {"point": None, "dir": None, "kind": None}


def set_chain(point, direction, kind: str) -> None:
    _CHAIN.update(point=point, dir=direction, kind=kind)


def chain_end():
    return _CHAIN["point"], _CHAIN["dir"], _CHAIN["kind"]


def reset_chain() -> None:
    _CHAIN.update(point=None, dir=None, kind=None)


def _arc_preview(geom, n: int = 48):
    """Segment list along an arc geometry tuple (ccw a1 -> a2)."""
    center, radius, a1, a2 = geom[0], geom[1], geom[2], geom[3]
    sweep = (a2 - a1) % 360.0 or 360.0
    steps = max(2, int(n * sweep / 360.0) + 1)
    pts = []
    for i in range(steps + 1):
        a = math.radians(a1 + sweep * i / steps)
        pts.append((center[0] + radius * math.cos(a),
                    center[1] + radius * math.sin(a)))
    return list(zip(pts, pts[1:]))


def _parse_number(text: str):
    try:
        return float(text)
    except ValueError:
        return None


class LineTool(Tool):
    def start(self) -> None:
        self.name = "LINE"
        self._points: list[Point] = []
        self._locked_dir = None       # tangent lock after Continue-from-arc
        self.ctx.prompt(tr("Specify first point:"))

    def _segment(self, a: Point, b: Point) -> None:
        self.ctx.execute(actions.add_line(a, b))
        set_chain(b, math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])), "line")

    def _next_prompt(self) -> None:
        if len(self._points) >= 3:
            self.ctx.prompt(tr("Specify next point or [Close/Undo]:"))
        else:
            self.ctx.prompt(tr("Specify next point or [Undo]:"))

    def on_point(self, point: Point) -> None:
        if self._locked_dir is not None and self._points:
            # tangent continuation from an arc: direction is locked, the
            # pick only supplies the length (projection onto the tangent)
            a = self._points[-1]
            d = math.radians(self._locked_dir)
            length = ((point[0] - a[0]) * math.cos(d)
                      + (point[1] - a[1]) * math.sin(d))
            point = (a[0] + length * math.cos(d), a[1] + length * math.sin(d))
            self._locked_dir = None
        if self._points:
            self._segment(self._points[-1], point)
        self._points.append(point)
        self.last_point = point
        self._next_prompt()

    def on_enter(self) -> None:
        if not self._points:
            # Continue: chain from the last line/polyline/arc endpoint;
            # an arc end locks the direction to its tangent (length only)
            point, direction, kind = chain_end()
            if point is None:
                self.ctx.finish()
                return
            self._points.append(point)
            self.last_point = point
            if kind == "arc" and direction is not None:
                self._locked_dir = direction
                self.ctx.prompt(tr("Length of line:"))
            else:
                self._next_prompt()
            return
        self.ctx.finish()

    def on_option(self, text: str) -> bool:
        t = text.upper()
        if t in ("C", "CLOSE") and len(self._points) >= 3:
            self._segment(self._points[-1], self._points[0])
            self.ctx.finish()
            return True
        if t in ("U", "UNDO") and self._points:
            # AutoCAD: U inside LINE erases the last segment for real.
            if len(self._points) >= 2:
                self.ctx.undo_last()
            self._points.pop()
            self.last_point = self._points[-1] if self._points else None
            self.ctx.prompt(self._points and tr("Specify next point or [Undo]:")
                            or tr("Specify first point:"))
            return True
        if self._locked_dir is not None and self._points:
            # tangent continuation accepts a typed length
            length = _parse_number(text)
            if length is None:
                return False
            a = self._points[-1]
            d = math.radians(self._locked_dir)
            self.on_point((a[0] + length * math.cos(d),
                           a[1] + length * math.sin(d)))
            return True
        return False

    def preview_segments(self, cursor: Point):
        if not self._points:
            return []
        if self._locked_dir is not None:
            a = self._points[-1]
            d = math.radians(self._locked_dir)
            length = ((cursor[0] - a[0]) * math.cos(d)
                      + (cursor[1] - a[1]) * math.sin(d))
            return [(a, (a[0] + length * math.cos(d),
                         a[1] + length * math.sin(d)))]
        return [(self._points[-1], cursor)]


class CircleTool(Tool):
    # AutoCAD's CIRCLERAD: the last radius used, session-only. None = no
    # default shown in the prompt.
    last_radius = None

    def start(self) -> None:
        self.name = "CIRCLE"
        self._mode = "CR"
        self._pts: list[Point] = []
        self._tangents: list = []      # TTR: [(object, pick_point), ...]
        self.ctx.prompt(
            tr("Specify center point for circle or [3P/2P/Ttr (tan tan radius)]:"))

    def _radius_prompt(self) -> None:
        r = type(self).last_radius
        if r is not None:
            self.ctx.prompt(tr("Specify radius of circle or [Diameter] <{r:g}>:", r=r))
        else:
            self.ctx.prompt(tr("Specify radius of circle or [Diameter]:"))

    def _make(self, center: Point, radius: float) -> None:
        if radius > 0:
            self.ctx.execute(actions.add_circle(center, radius))
            type(self).last_radius = radius
        self.ctx.finish()

    def on_option(self, text: str) -> bool:
        t = text.upper()
        if not self._pts and not self._tangents:
            if t == "2P":
                self._mode = "2P"
                self.ctx.prompt(tr("Specify first end point of circle's diameter:"))
                return True
            if t == "3P":
                self._mode = "3P"
                self.ctx.prompt(tr("Specify first point on circle:"))
                return True
            if t in ("T", "TTR"):
                self._mode = "TTR"
                self.entity_picker = True   # raw picks: tangency is deferred
                self.ctx.prompt(
                    tr("Specify point on object for first tangent of circle:"))
                return True
        if self._mode == "CR" and self._pts:
            if t in ("D", "DIAMETER"):
                self._mode = "CD"
                r = type(self).last_radius
                if r is not None:
                    self.ctx.prompt(
                        tr("Specify diameter of circle <{d:g}>:", d=2 * r))
                else:
                    self.ctx.prompt(tr("Specify diameter of circle:"))
                return True
            radius = _parse_number(text)
            if radius is not None and radius > 0:
                self._make(self._pts[0], radius)
                return True
        if self._mode == "CD" and self._pts:
            diameter = _parse_number(text)
            if diameter is not None and diameter > 0:
                self._make(self._pts[0], diameter / 2.0)
                return True
        if self._mode == "TTR" and len(self._tangents) == 2:
            radius = _parse_number(text)
            if radius is not None and radius > 0:
                self._ttr_build(radius)
                return True
        return False

    def on_enter(self) -> None:
        # Enter accepts the <last> radius/diameter default (CIRCLERAD).
        r = type(self).last_radius
        if r is not None:
            if self._mode == "CR" and self._pts:
                self._make(self._pts[0], r)
                return
            if self._mode == "CD" and self._pts:
                self._make(self._pts[0], r)      # <2r> default = same circle
                return
            if self._mode == "TTR" and len(self._tangents) == 2:
                self._ttr_build(r)
                return
        self.ctx.finish()

    # -- TTR ------------------------------------------------------------------
    def _pick_tangent_object(self, point: Point):
        services = self.ctx.services
        entity = services.pick_entity(point) if services is not None else None
        if entity is None:
            self.ctx.echo(tr("No object under the pick."))
            return None
        kind = entity.dxftype()
        if kind == "LINE":
            s, e = entity.dxf.start, entity.dxf.end
            return ("line", (s.x, s.y), (e.x, e.y))
        if kind in ("CIRCLE", "ARC"):
            c = entity.dxf.center
            return ("circle", (c.x, c.y), float(entity.dxf.radius))
        self.ctx.echo(tr("Tangent picks support lines, circles and arcs."))
        return None

    def _ttr_build(self, radius: float) -> None:
        (o1, p1), (o2, p2) = self._tangents
        try:
            center = actions.ttr_center(o1, p1, o2, p2, radius)
        except ValueError:
            self.ctx.echo(tr("Circle does not exist."))
            self.ctx.finish()
            return
        self._make(center, radius)

    def on_point(self, point: Point) -> None:
        if self._mode == "TTR":
            obj = self._pick_tangent_object(point)
            if obj is None:
                return
            self._tangents.append((obj, point))
            if len(self._tangents) == 1:
                self.ctx.prompt(
                    tr("Specify point on object for second tangent of circle:"))
            else:
                r = type(self).last_radius
                self.ctx.prompt(
                    tr("Specify radius of circle <{r:g}>:", r=r) if r is not None
                    else tr("Specify radius of circle:"))
            return
        self._pts.append(point)
        self.last_point = point
        if self._mode == "CR":
            if len(self._pts) == 1:
                self._radius_prompt()
            else:
                self._make(self._pts[0], math.dist(self._pts[0], self._pts[1]))
        elif self._mode == "CD":
            # a picked point measures the DIAMETER (AutoCAD)
            self._make(self._pts[0], math.dist(self._pts[0], point) / 2.0)
        elif self._mode == "2P":
            if len(self._pts) == 1:
                self.ctx.prompt(tr("Specify second end point of circle's diameter:"))
            else:
                center, radius = actions.circle_from_2p(*self._pts)
                self._make(center, radius)
        else:  # 3P
            if len(self._pts) < 3:
                self.ctx.prompt(tr("Specify second point on circle:")
                                if len(self._pts) == 1
                                else tr("Specify third point on circle:"))
            else:
                try:
                    center, radius = actions.circle_from_3p(*self._pts)
                except ValueError:
                    self.ctx.echo(tr("Collinear points — no circle."))
                    self.ctx.finish()
                else:
                    self._make(center, radius)

    def preview_segments(self, cursor: Point):
        if self._mode == "CR" and self._pts:
            r = math.dist(self._pts[0], cursor)
            return _circle_preview(self._pts[0], r) + [(self._pts[0], cursor)]
        if self._mode == "CD" and self._pts:
            r = math.dist(self._pts[0], cursor) / 2.0
            return _circle_preview(self._pts[0], r) + [(self._pts[0], cursor)]
        if self._mode == "2P" and self._pts:
            center, r = actions.circle_from_2p(self._pts[0], cursor)
            return _circle_preview(center, r)
        if self._mode == "3P" and len(self._pts) == 2:
            try:
                center, r = actions.circle_from_3p(self._pts[0], self._pts[1], cursor)
            except ValueError:
                return []
            return _circle_preview(center, r)
        return []


class ArcTool(Tool):
    """ARC with AutoCAD's full method tree (11 methods + Continue).

    State names mirror the official prompt tree: S0 (start or Center or
    Enter=Continue), SECOND (second point or Center/End), SC_END (end or
    Angle/chord Length), SE_KEY (center or Angle/Direction/Radius), and the
    numeric sub-states awaiting one typed value.
    """

    def start(self) -> None:
        self.name = "ARC"
        self._state = "S0"
        self._start: Point | None = None
        self._center: Point | None = None
        self._end: Point | None = None
        self._continue_dir = None
        self.ctx.prompt(tr("Specify start point of arc or [Center]:"))

    # -- building --------------------------------------------------------------
    def _emit(self, geom) -> None:
        self.ctx.execute(actions.add_arc_geom(geom))
        set_chain(geom[4], actions.arc_end_tangent(geom), "arc")
        self.ctx.finish()

    def _try(self, build) -> None:
        try:
            geom = build()
        except ValueError:
            self.ctx.echo(tr("Invalid arc geometry."))
            self.ctx.finish()
            return
        self._emit(geom)

    def _sce_geom(self, end: Point):
        # end pick fixes the end ANGLE only (ray rule); sweep is CCW
        a1 = math.degrees(math.atan2(self._start[1] - self._center[1],
                                     self._start[0] - self._center[0]))
        a2 = math.degrees(math.atan2(end[1] - self._center[1],
                                     end[0] - self._center[0]))
        return actions.arc_sca(self._start, self._center, (a2 - a1) % 360.0)

    # -- input -----------------------------------------------------------------
    def on_point(self, point: Point) -> None:
        self.last_point = point
        state = self._state
        if state == "S0":
            self._start = point
            self._state = "SECOND"
            self.ctx.prompt(tr("Specify second point of arc or [Center/End]:"))
        elif state == "CONTINUE":
            self._try(lambda: actions.arc_sed(
                self._start, point, self._continue_dir))
        elif state == "SECOND":
            self._second = point
            self._state = "THIRD"
            self.ctx.prompt(tr("Specify end point of arc:"))
        elif state == "THIRD":
            try:
                geom_cmd = actions.add_arc_3p(self._start, self._second, point)
            except ValueError:
                self.ctx.echo(tr("Collinear points — no arc."))
                self.ctx.finish()
                return
            self.ctx.execute(geom_cmd)
            # chain: travel direction at the user's end of the 3-point arc
            center, radius = actions.circle_from_3p(
                self._start, self._second, point)
            a_end = math.degrees(math.atan2(point[1] - center[1],
                                            point[0] - center[0]))
            a1 = math.degrees(math.atan2(self._start[1] - center[1],
                                         self._start[0] - center[0]))
            a2 = math.degrees(math.atan2(self._second[1] - center[1],
                                         self._second[0] - center[0]))
            ccw = ((a2 - a1) % 360.0) <= ((a_end - a1) % 360.0)
            set_chain(point, a_end + (90.0 if ccw else -90.0), "arc")
            self.ctx.finish()
        elif state == "C_FIRST":
            self._center = point
            self._state = "C_START"
            self.ctx.prompt(tr("Specify start point of arc:"))
        elif state == "C_START":
            self._start = point
            self._state = "SC_END"
            self.ctx.prompt(
                tr("Specify end point of arc or [Angle/chord Length]:"))
        elif state == "S_CENTER":
            self._center = point
            self._state = "SC_END"
            self.ctx.prompt(
                tr("Specify end point of arc or [Angle/chord Length]:"))
        elif state == "SC_END":
            self._try(lambda: self._sce_geom(point))
        elif state == "S_END":
            self._end = point
            self._state = "SE_KEY"
            self.ctx.prompt(
                tr("Specify center point of arc or [Angle/Direction/Radius]:"))
        elif state == "SE_KEY":
            # Start, End, Center: same ray rule, inputs reordered
            self._center = point
            self._try(lambda: self._sce_geom(self._end))
        elif state == "SE_DIR":
            # direction picked as a point: direction = start -> point
            direction = math.degrees(math.atan2(point[1] - self._start[1],
                                                point[0] - self._start[0]))
            self._try(lambda: actions.arc_sed(self._start, self._end, direction))

    def on_option(self, text: str) -> bool:
        t = text.upper()
        state = self._state
        if state == "S0" and t in ("C", "CENTER"):
            self._state = "C_FIRST"
            self.ctx.prompt(tr("Specify center point of arc:"))
            return True
        if state == "SECOND":
            if t in ("C", "CENTER"):
                self._state = "S_CENTER"
                self.ctx.prompt(tr("Specify center point of arc:"))
                return True
            if t in ("E", "END"):
                self._state = "S_END"
                self.ctx.prompt(tr("Specify end point of arc:"))
                return True
        if state == "SC_END":
            if t in ("A", "ANGLE"):
                self._state = "SC_ANGLE"
                self.ctx.prompt(tr("Specify included angle:"))
                return True
            if t in ("L", "LENGTH"):
                self._state = "SC_LENGTH"
                self.ctx.prompt(tr("Specify length of chord:"))
                return True
        if state == "SC_ANGLE":
            angle = _parse_number(text)
            if angle is not None:
                self._try(lambda: actions.arc_sca(self._start, self._center, angle))
                return True
        if state == "SC_LENGTH":
            chord = _parse_number(text)
            if chord is not None:
                self._try(lambda: actions.arc_scl(self._start, self._center, chord))
                return True
        if state == "SE_KEY":
            if t in ("A", "ANGLE"):
                self._state = "SE_ANGLE"
                self.ctx.prompt(tr("Specify included angle:"))
                return True
            if t in ("D", "DIRECTION"):
                self._state = "SE_DIR"
                self.ctx.prompt(
                    tr("Specify tangent direction for the start point of arc:"))
                return True
            if t in ("R", "RADIUS"):
                self._state = "SE_RADIUS"
                self.ctx.prompt(tr("Specify radius of arc:"))
                return True
        if state == "SE_ANGLE":
            angle = _parse_number(text)
            if angle is not None:
                self._try(lambda: actions.arc_sea(self._start, self._end, angle))
                return True
        if state == "SE_RADIUS":
            radius = _parse_number(text)
            if radius is not None:
                self._try(lambda: actions.arc_ser(self._start, self._end, radius))
                return True
        if state == "SE_DIR":
            direction = _parse_number(text)
            if direction is not None:
                self._try(lambda: actions.arc_sed(self._start, self._end, direction))
                return True
        return False

    def on_enter(self) -> None:
        if self._state == "S0":
            # Continue: tangent from the last line/polyline/arc endpoint
            point, direction, _kind = chain_end()
            if point is None or direction is None:
                self.ctx.finish()
                return
            self._start = point
            self._continue_dir = direction
            self._state = "CONTINUE"
            self.ctx.prompt(tr("Specify end point of arc:"))
            return
        self.ctx.finish()

    def preview_segments(self, cursor: Point):
        state = self._state
        try:
            if state == "THIRD":
                try:
                    center, r = actions.circle_from_3p(
                        self._start, self._second, cursor)
                except ValueError:
                    return [(self._start, self._second), (self._second, cursor)]
                return _circle_preview(center, r)
            if state == "SC_END":
                return _arc_preview(self._sce_geom(cursor))
            if state == "CONTINUE":
                return _arc_preview(actions.arc_sed(
                    self._start, cursor, self._continue_dir))
            if state == "SE_DIR":
                direction = math.degrees(math.atan2(
                    cursor[1] - self._start[1], cursor[0] - self._start[0]))
                return _arc_preview(actions.arc_sed(
                    self._start, self._end, direction))
            if state == "SE_KEY":
                return _arc_preview(self._sce_geom_from(cursor, self._end))
        except ValueError:
            pass
        anchor = self._start or self._center
        return [(anchor, cursor)] if anchor is not None else []

    def _sce_geom_from(self, center: Point, end: Point):
        a1 = math.degrees(math.atan2(self._start[1] - center[1],
                                     self._start[0] - center[0]))
        a2 = math.degrees(math.atan2(end[1] - center[1], end[0] - center[0]))
        return actions.arc_sca(self._start, center, (a2 - a1) % 360.0)


class EllipseTool(Tool):
    def start(self) -> None:
        self.name = "ELLIPSE"
        self._mode = "AXIS"
        self._pts: list[Point] = []
        self.ctx.prompt(tr("ELLIPSE Specify axis endpoint or [Center]:"))

    def on_option(self, text: str) -> bool:
        if text.upper() in ("C", "CENTER") and not self._pts:
            self._mode = "CENTER"
            self.ctx.prompt(tr("Specify center of ellipse:"))
            return True
        return False

    def on_point(self, point: Point) -> None:
        self._pts.append(point)
        self.last_point = point
        need = 3
        if len(self._pts) < 2:
            self.ctx.prompt(tr("Specify other endpoint of axis:")
                            if self._mode == "AXIS"
                            else tr("Specify endpoint of axis:"))
        elif len(self._pts) < need:
            self.ctx.prompt(tr("Specify distance to other axis:"))
        else:
            self._build()

    def _build(self) -> None:
        p1, p2, p3 = self._pts
        if self._mode == "AXIS":
            center = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
            other = math.dist(center, p3)
            center, major, ratio = actions.ellipse_from_axis(p1, p2, other)
        else:  # CENTER: p1=center, p2=axis endpoint, p3=distance
            other = math.dist(p1, p3)
            center, major, ratio = actions.ellipse_from_center(p1, p2, other)
        if ratio > 1e-9:
            self.ctx.execute(actions.add_ellipse(center, major, ratio))
        self.ctx.finish()

    def preview_segments(self, cursor: Point):
        if len(self._pts) == 2:
            if self._mode == "AXIS":
                center = ((self._pts[0][0] + self._pts[1][0]) / 2.0,
                          (self._pts[0][1] + self._pts[1][1]) / 2.0)
            else:
                center = self._pts[0]
            other = math.dist(center, cursor)
            major = math.dist(center, self._pts[1] if self._mode == "AXIS"
                              else self._pts[1])
            return _ellipse_preview(self._pts[0], self._pts[1], other, self._mode)
        if self._pts:
            return [(self._pts[0], cursor)]
        return []


class PointTool(Tool):
    def start(self) -> None:
        self.name = "POINT"
        self.ctx.prompt(tr("POINT Specify a point (Enter ends):"))

    def on_point(self, point: Point) -> None:
        self.ctx.execute(actions.add_point(point))
        self.last_point = point
        # POINT repeats until Enter/Esc (AutoCAD behavior).
        self.ctx.prompt(tr("Specify a point (Enter ends):"))


class TextTool(Tool):
    """Single-line TEXT (DTEXT): type in place on the canvas, AutoCAD-style.

    After start point / height / rotation, a caret appears at the point and
    the typed characters show live. Enter commits the line and starts a new
    one below; clicking a new point commits and restarts there; Esc finishes,
    keeping every completed line.
    """

    default_height = 2.5   # session-sticky, like AutoCAD's last height

    def start(self) -> None:
        self.name = "TEXT"
        self._pos = None
        self._height = None
        self.typing = False
        self._buffer = ""
        self._rotation = 0.0
        self.ctx.prompt(tr("TEXT Specify start point:"))

    def on_point(self, point: Point) -> None:
        if self.typing:
            self._commit_line()      # picking a new point restarts text there
            self._pos = point
            self._buffer = ""
            return
        self._pos = point
        self.last_point = point
        self.ctx.prompt(tr("Specify height <{h}>:", h=type(self).default_height))

    def on_option(self, text: str) -> bool:
        if self._pos is None or self.typing:
            return False
        if self._height is None:
            try:
                self._height = float(text) if text else type(self).default_height
            except ValueError:
                return False
            type(self).default_height = self._height
            self.ctx.prompt(tr("Specify rotation angle <0>:"))
            return True
        try:
            self._rotation = float(text) if text else 0.0
        except ValueError:
            return False
        self._begin_typing()
        return True

    def on_enter(self) -> None:
        if self.typing:
            self._commit_line()      # Enter: commit and drop to a new line
            self._pos = self._next_line_pos()
            self._buffer = ""
            return
        if self._pos is None:
            self.ctx.finish()
        elif self._height is None:
            self._height = type(self).default_height
            self.ctx.prompt(tr("Specify rotation angle <0>:"))
        else:
            self._begin_typing()

    def _begin_typing(self) -> None:
        self.typing = True
        self._buffer = ""
        self.ctx.prompt(tr("Enter text (Enter for new line, Esc to finish):"))

    # -- live in-place typing --------------------------------------------------
    def on_char(self, ch: str) -> None:
        self._buffer += ch

    def on_backspace(self) -> None:
        self._buffer = self._buffer[:-1]

    def finish_typing(self) -> None:
        self._commit_line()
        self.typing = False
        self.ctx.finish()

    def live_text(self):
        if self.typing and self._pos is not None:
            return (self._pos, self._buffer, self._height, self._rotation)
        return None

    def _commit_line(self) -> None:
        if self._buffer.strip():
            self.ctx.execute(actions.add_text(
                self._pos, self._buffer, self._height, self._rotation))

    def _next_line_pos(self) -> Point:
        # baseline drops by 1.5x the height, in the text's local -Y direction
        d = 1.5 * self._height
        r = math.radians(self._rotation)
        return (self._pos[0] + d * math.sin(r), self._pos[1] - d * math.cos(r))


class MTextTool(Tool):
    default_height = 2.5

    def start(self) -> None:
        self.name = "MTEXT"
        self._first = None
        self.ctx.prompt(tr("MTEXT Specify first corner:"))

    def on_point(self, point: Point) -> None:
        if self._first is None:
            self._first = point
            self.last_point = point
            self.ctx.prompt(tr("Specify opposite corner:"))
        else:
            content = self.ctx.ask_text(tr("Enter text:"), "")
            if content:
                self.ctx.execute(actions.add_mtext(
                    self._first, point, content, type(self).default_height))
            self.ctx.finish()

    def preview_segments(self, cursor: Point):
        if self._first is None:
            return []
        p1, p2 = self._first, cursor
        c = [(p1[0], p1[1]), (p2[0], p1[1]), (p2[0], p2[1]), (p1[0], p2[1])]
        return list(zip(c, c[1:] + c[:1]))


def _ellipse_preview(p1: Point, p2: Point, other: float, mode: str, n: int = 64):
    if mode == "AXIS":
        center = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
        ax = ((p2[0] - p1[0]) / 2.0, (p2[1] - p1[1]) / 2.0)
    else:
        center = p1
        ax = (p2[0] - p1[0], p2[1] - p1[1])
    major = math.hypot(*ax)
    if major < 1e-9:
        return []
    ang = math.atan2(ax[1], ax[0])
    ca, sa = math.cos(ang), math.sin(ang)
    pts = []
    for i in range(n + 1):
        t = i * math.tau / n
        ex, ey = major * math.cos(t), other * math.sin(t)
        pts.append((center[0] + ex * ca - ey * sa,
                    center[1] + ex * sa + ey * ca))
    return list(zip(pts, pts[1:]))


class PlineTool(Tool):
    """PLINE with AutoCAD's two-mode state machine: line mode
    [Arc/Close/Halfwidth/Length/Undo/Width] and arc mode
    [Angle/CEnter/CLose/Direction/Line/Radius/Second pt/...]. One
    LWPOLYLINE with per-segment widths and bulges comes out at the end.
    """

    # PLINEWID: the current width persists across PLINE invocations.
    current_width = 0.0

    def start(self) -> None:
        self.name = "PLINE"
        self._verts: list[Point] = []       # committed vertices
        self._segs: list[dict] = []         # {"bulge","sw","ew"} per segment
        self._arc_mode = False
        self._await = None                  # pending numeric sub-prompt
        self._pending = {}                  # partial data for arc sub-flows
        self._sw = type(self).current_width
        self._ew = type(self).current_width
        self.ctx.prompt(tr("Specify start point:"))

    # -- prompts ---------------------------------------------------------------
    def _line_prompt(self) -> None:
        if self._segs:
            self.ctx.prompt(tr(
                "Specify next point or [Arc/Close/Halfwidth/Length/Undo/Width]:"))
        else:
            self.ctx.prompt(tr(
                "Specify next point or [Arc/Halfwidth/Length/Undo/Width]:"))

    def _arc_prompt(self) -> None:
        self.ctx.prompt(tr(
            "Specify endpoint of arc or "
            "[Angle/CEnter/CLose/Direction/Halfwidth/Line/Radius/Second pt/Undo/Width]:"))

    def _mode_prompt(self) -> None:
        self._arc_prompt() if self._arc_mode else self._line_prompt()

    # -- geometry helpers ------------------------------------------------------
    def _prev_dir(self):
        """Tangent direction (deg) at the current vertex, from the previous
        segment — the arc-mode tangent-continuation rule."""
        if not self._segs:
            _p, direction, _k = chain_end()
            return direction
        seg = self._segs[-1]
        a, b = self._verts[-2], self._verts[-1]
        if seg["bulge"] == 0.0:
            return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        # tangent at b: chord direction turned by the half included angle
        included = 4.0 * math.degrees(math.atan(seg["bulge"]))
        chord = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        return chord + included / 2.0

    def _push(self, point: Point, bulge: float) -> None:
        self._verts.append(point)
        self._segs.append({"bulge": bulge, "sw": self._sw, "ew": self._ew})
        self._sw = self._ew                 # ending width becomes uniform
        type(self).current_width = self._ew
        self.last_point = point

    def _bulge_from_geom(self, geom, start: Point, end: Point) -> float:
        # entity angles are stored CCW, so the entity sweep equals the user's
        # travel magnitude; the travel direction gives the bulge its sign
        sweep = (geom[3] - geom[2]) % 360.0
        bulge = math.tan(math.radians(sweep) / 4.0)
        return bulge if geom[5] else -bulge

    def _add_arc_to(self, point: Point, geom) -> None:
        self._push(point, self._bulge_from_geom(geom, self._verts[-1], point))
        self._arc_prompt()

    def _tangent_arc(self, point: Point):
        direction = self._prev_dir()
        if direction is None:
            # no previous segment: AutoCAD uses the last known direction;
            # fall back to the chord (a straight-ish arc pick)
            raise ValueError("no tangent direction")
        return actions.arc_sed(self._verts[-1], point, direction)

    def _arc_from_angle_radius(self, angle: float, radius: float) -> None:
        """Included angle + radius: the chord direction defaults to the
        tangent continuation (AutoCAD asks and offers it as <current>)."""
        direction = self._prev_dir() or 0.0
        chord_dir = direction + angle / 2.0
        chord = 2.0 * abs(radius) * math.sin(math.radians(abs(angle)) / 2.0)
        a = self._verts[-1]
        d = math.radians(chord_dir)
        end = (a[0] + chord * math.cos(d), a[1] + chord * math.sin(d))
        try:
            geom = actions.arc_sea(a, end, angle)
        except ValueError:
            self.ctx.echo(tr("Invalid arc geometry."))
            self._await = None
            self._arc_prompt()
            return
        self._await = None
        self._add_arc_to(end, geom)

    # -- finishing -------------------------------------------------------------
    def _vertices_xyseb(self):
        out = []
        for i, v in enumerate(self._verts):
            seg = self._segs[i] if i < len(self._segs) else \
                {"bulge": 0.0, "sw": 0.0, "ew": 0.0}
            out.append((v[0], v[1], seg["sw"], seg["ew"], seg["bulge"]))
        return out

    def _build(self, closed: bool) -> None:
        if self._segs:
            self.ctx.execute(actions.add_polyline(
                self._vertices_xyseb(), closed=closed))
            direction = self._prev_dir()
            last_arc = self._segs[-1]["bulge"] != 0.0
            if direction is not None:
                set_chain(self._verts[0] if closed else self._verts[-1],
                          direction, "arc" if last_arc else "line")
        self._verts, self._segs = [], []
        self.ctx.finish()

    def on_enter(self) -> None:
        if self._await in ("width_start", "width_end",
                           "halfwidth_start", "halfwidth_end"):
            self.on_option("")              # Enter accepts the <default>
            return
        if self._await is not None:
            self._await = None              # abandon the sub-prompt
            self._mode_prompt()
            return
        if self._verts and not self._segs:
            self._verts = []                # start point only: nothing made
        self._build(False)

    def on_cancel(self) -> None:
        # AutoCAD keeps the committed segments on Esc too.
        self._build(False)

    # -- input -----------------------------------------------------------------
    def on_point(self, point: Point) -> None:
        if not self._verts:
            self._verts.append(point)
            self.last_point = point
            self.ctx.echo(tr("Current line-width is {w:g}",
                             w=type(self).current_width))
            self._line_prompt()
            return
        if self._await == "arc_second":
            self._pending["second"] = point
            self._await = "arc_second_end"
            self.ctx.prompt(tr("Specify end point of arc:"))
            return
        if self._await == "arc_second_end":
            start = self._verts[-1]
            try:
                geom_cmd_center, radius = actions.circle_from_3p(
                    start, self._pending["second"], point)
            except ValueError:
                self.ctx.echo(tr("Collinear points — no arc."))
                self._await = None
                self._arc_prompt()
                return
            # 3-point arc as bulge: direction from the middle point side
            a1 = math.degrees(math.atan2(start[1] - geom_cmd_center[1],
                                         start[0] - geom_cmd_center[0]))
            am = math.degrees(math.atan2(
                self._pending["second"][1] - geom_cmd_center[1],
                self._pending["second"][0] - geom_cmd_center[0]))
            a2 = math.degrees(math.atan2(point[1] - geom_cmd_center[1],
                                         point[0] - geom_cmd_center[0]))
            ccw = ((am - a1) % 360.0) <= ((a2 - a1) % 360.0)
            sweep = ((a2 - a1) % 360.0) if ccw else ((a1 - a2) % 360.0)
            bulge = math.tan(math.radians(sweep) / 4.0)
            self._await = None
            self._push(point, bulge if ccw else -bulge)
            self._arc_prompt()
            return
        if self._await == "arc_center":
            self._pending["center"] = point
            self._await = "arc_center_end"
            self.ctx.prompt(tr("Specify endpoint of arc or [Angle/Length]:"))
            return
        if self._await == "arc_center_end":
            start, center = self._verts[-1], self._pending["center"]
            a1 = math.degrees(math.atan2(start[1] - center[1], start[0] - center[0]))
            a2 = math.degrees(math.atan2(point[1] - center[1], point[0] - center[0]))
            try:
                geom = actions.arc_sca(start, center, (a2 - a1) % 360.0)
            except ValueError:
                self.ctx.echo(tr("Invalid arc geometry."))
                self._await = None
                self._arc_prompt()
                return
            self._await = None
            self._add_arc_to(geom[4], geom)
            return
        if self._await == "arc_angle_center":
            start = self._verts[-1]
            try:
                geom = actions.arc_sca(start, point, self._pending["angle"])
            except ValueError:
                self.ctx.echo(tr("Invalid arc geometry."))
                self._await = None
                self._arc_prompt()
                return
            self._await = None
            self._add_arc_to(geom[4], geom)
            return
        if self._await == "arc_direction":
            direction = math.degrees(math.atan2(point[1] - self._verts[-1][1],
                                                point[0] - self._verts[-1][0]))
            self._pending["direction"] = direction
            self._await = "arc_direction_end"
            self.ctx.prompt(tr("Specify endpoint of arc:"))
            return
        if self._await == "arc_direction_end":
            try:
                geom = actions.arc_sed(self._verts[-1], point,
                                       self._pending["direction"])
            except ValueError:
                self.ctx.echo(tr("Invalid arc geometry."))
                self._await = None
                self._arc_prompt()
                return
            self._await = None
            self._add_arc_to(point, geom)
            return
        if self._await == "arc_radius_end":
            try:
                geom = actions.arc_ser(self._verts[-1], point,
                                       self._pending["radius"])
            except ValueError:
                self.ctx.echo(tr("Invalid arc geometry."))
                self._await = None
                self._arc_prompt()
                return
            self._await = None
            self._add_arc_to(point, geom)
            return
        if self._await == "arc_angle_end":
            try:
                geom = actions.arc_sea(self._verts[-1], point,
                                       self._pending["angle"])
            except ValueError:
                self.ctx.echo(tr("Invalid arc geometry."))
                self._await = None
                self._arc_prompt()
                return
            self._await = None
            self._add_arc_to(point, geom)
            return
        if self._await is not None:
            return                          # numeric sub-prompt: ignore picks
        if self._arc_mode:
            try:
                geom = self._tangent_arc(point)
            except ValueError:
                # no tangent known yet: fall back to a straight segment
                self._push(point, 0.0)
                self._arc_prompt()
                return
            self._add_arc_to(point, geom)
            return
        self._push(point, 0.0)
        self._line_prompt()

    def on_option(self, text: str) -> bool:
        t = text.upper()
        # numeric sub-prompts first
        if self._await in ("width_start", "halfwidth_start"):
            value = _parse_number(text) if text else self._sw
            if value is None or value < 0:
                return False
            factor = 2.0 if self._await == "halfwidth_start" else 1.0
            self._pending["sw"] = value * factor
            key = "halfwidth_end" if factor == 2.0 else "width_end"
            self._await = key
            if factor == 2.0:
                self.ctx.prompt(tr("Specify ending half-width <{w:g}>:",
                                   w=self._pending["sw"] / 2.0))
            else:
                self.ctx.prompt(tr("Specify ending width <{w:g}>:",
                                   w=self._pending["sw"]))
            return True
        if self._await in ("width_end", "halfwidth_end"):
            factor = 2.0 if self._await == "halfwidth_end" else 1.0
            value = _parse_number(text) if text else self._pending["sw"] / factor
            if value is None or value < 0:
                return False
            self._sw = self._pending["sw"]
            self._ew = value * factor
            self._await = None
            self._mode_prompt()
            return True
        if self._await == "length":
            value = _parse_number(text)
            if value is None:
                return False
            direction = self._prev_dir()
            if direction is None:
                self.ctx.echo(tr("No previous segment to continue."))
            else:
                a = self._verts[-1]
                d = math.radians(direction)
                self._push((a[0] + value * math.cos(d),
                            a[1] + value * math.sin(d)), 0.0)
            self._await = None
            self._line_prompt()
            return True
        if self._await == "arc_angle":
            value = _parse_number(text)
            if value is None:
                return False
            self._pending["angle"] = value
            self._await = "arc_angle_end"
            self.ctx.prompt(tr("Specify endpoint of arc or [CEnter/Radius]:"))
            return True
        if self._await == "arc_angle_end" and t in ("CE", "CENTER"):
            # angle + center: sweep the stored angle around the picked center
            self._await = "arc_angle_center"
            self.ctx.prompt(tr("Specify center point of arc:"))
            return True
        if self._await == "arc_angle_end" and t in ("R", "RADIUS"):
            self._await = "arc_angle_radius"
            self.ctx.prompt(tr("Specify radius of arc:"))
            return True
        if self._await == "arc_angle_radius":
            value = _parse_number(text)
            if value is None:
                return False
            self._arc_from_angle_radius(self._pending["angle"], value)
            return True
        if self._await == "arc_center_end" and t in ("A", "ANGLE"):
            self._await = "arc_center_angle"
            self.ctx.prompt(tr("Specify included angle:"))
            return True
        if self._await == "arc_center_end" and t in ("L", "LENGTH"):
            self._await = "arc_center_length"
            self.ctx.prompt(tr("Specify length of chord:"))
            return True
        if self._await == "arc_center_angle":
            value = _parse_number(text)
            if value is None:
                return False
            try:
                geom = actions.arc_sca(self._verts[-1],
                                       self._pending["center"], value)
            except ValueError:
                self.ctx.echo(tr("Invalid arc geometry."))
                self._await = None
                self._arc_prompt()
                return True
            self._await = None
            self._add_arc_to(geom[4], geom)
            return True
        if self._await == "arc_center_length":
            value = _parse_number(text)
            if value is None:
                return False
            try:
                geom = actions.arc_scl(self._verts[-1],
                                       self._pending["center"], value)
            except ValueError:
                self.ctx.echo(tr("Invalid arc geometry."))
                self._await = None
                self._arc_prompt()
                return True
            self._await = None
            self._add_arc_to(geom[4], geom)
            return True
        if self._await == "arc_direction":
            value = _parse_number(text)
            if value is not None:
                self._pending["direction"] = value
                self._await = "arc_direction_end"
                self.ctx.prompt(tr("Specify endpoint of arc:"))
                return True
            return False
        if self._await == "arc_radius":
            value = _parse_number(text)
            if value is None:
                return False
            self._pending["radius"] = value
            self._await = "arc_radius_end"
            self.ctx.prompt(tr("Specify endpoint of arc or [Angle]:"))
            return True
        if self._await == "arc_radius_end" and t in ("A", "ANGLE"):
            self._await = "arc_radius_angle"
            self.ctx.prompt(tr("Specify included angle:"))
            return True
        if self._await == "arc_radius_angle":
            value = _parse_number(text)
            if value is None:
                return False
            self._arc_from_angle_radius(value, self._pending["radius"])
            return True
        if self._await == "arc_angle_center":
            return False                    # awaiting a point, not text
        if self._await is not None:
            return False
        if not self._verts:
            return False

        # -- mode keywords ----------------------------------------------------
        if not self._arc_mode:
            if t in ("A", "ARC"):
                self._arc_mode = True
                self._arc_prompt()
                return True
            if t in ("C", "CLOSE") and len(self._segs) >= 1 and len(self._verts) >= 2:
                self._push(self._verts[0], 0.0)
                self._verts.pop()           # closing flag supplies the segment
                self._build(True)
                return True
            if t in ("W", "WIDTH"):
                self._await = "width_start"
                self.ctx.prompt(tr("Specify starting width <{w:g}>:", w=self._sw))
                return True
            if t in ("H", "HALFWIDTH"):
                self._await = "halfwidth_start"
                self.ctx.prompt(tr("Specify starting half-width <{w:g}>:",
                                   w=self._sw / 2.0))
                return True
            if t in ("L", "LENGTH"):
                self._await = "length"
                self.ctx.prompt(tr("Specify length of line:"))
                return True
            if t in ("U", "UNDO") and self._segs:
                self._segs.pop()
                self._verts.pop()
                self.last_point = self._verts[-1]
                self._line_prompt()
                return True
            return False
        # arc mode
        if t in ("L", "LINE"):
            self._arc_mode = False
            self._line_prompt()
            return True
        if t in ("CL", "CLOSE"):
            if len(self._segs) >= 1:
                direction = self._prev_dir()
                try:
                    geom = actions.arc_sed(self._verts[-1], self._verts[0],
                                           direction if direction is not None else 0.0)
                    bulge = self._bulge_from_geom(geom, self._verts[-1],
                                                  self._verts[0])
                except ValueError:
                    # start point dead behind the tangent: no tangent arc
                    # exists — AutoCAD closes with a semicircle (bulge 1)
                    bulge = 1.0
                self._segs.append({"bulge": bulge, "sw": self._sw,
                                   "ew": self._ew})
                self._build(True)
                return True
            return False
        if t in ("A", "ANGLE"):
            self._await = "arc_angle"
            self.ctx.prompt(tr("Specify included angle:"))
            return True
        if t == "CE":
            self._await = "arc_center"
            self.ctx.prompt(tr("Specify center point of arc:"))
            return True
        if t in ("D", "DIRECTION"):
            self._await = "arc_direction"
            self.ctx.prompt(
                tr("Specify the tangent direction from the start point of arc:"))
            return True
        if t in ("R", "RADIUS"):
            self._await = "arc_radius"
            self.ctx.prompt(tr("Specify radius of arc:"))
            return True
        if t in ("S", "SECOND"):
            self._await = "arc_second"
            self.ctx.prompt(tr("Specify second point on arc:"))
            return True
        if t in ("W", "WIDTH"):
            self._await = "width_start"
            self.ctx.prompt(tr("Specify starting width <{w:g}>:", w=self._sw))
            return True
        if t in ("H", "HALFWIDTH"):
            self._await = "halfwidth_start"
            self.ctx.prompt(tr("Specify starting half-width <{w:g}>:",
                               w=self._sw / 2.0))
            return True
        if t in ("U", "UNDO") and self._segs:
            self._segs.pop()
            self._verts.pop()
            self.last_point = self._verts[-1]
            self._arc_prompt()
            return True
        return False

    def preview_segments(self, cursor: Point):
        segs = []
        for i, seg in enumerate(self._segs):
            a, b = self._verts[i], self._verts[i + 1]
            if seg["bulge"] == 0.0:
                segs.append((a, b))
            else:
                included = 4.0 * math.atan(seg["bulge"])
                chord = math.dist(a, b)
                if chord > 1e-12:
                    radius = abs(chord / (2.0 * math.sin(included / 2.0)))
                    try:
                        geom = actions.arc_sea(a, b, math.degrees(included))
                        segs.extend(_arc_preview(geom, n=24))
                        continue
                    except ValueError:
                        pass
                segs.append((a, b))
        if self._verts and self._await is None:
            if self._arc_mode:
                try:
                    segs.extend(_arc_preview(self._tangent_arc(cursor), n=24))
                except ValueError:
                    segs.append((self._verts[-1], cursor))
            else:
                segs.append((self._verts[-1], cursor))
        return segs


class RectangTool(Tool):
    """RECTANG with AutoCAD's sticky corner settings and placement options:
    [Chamfer/Elevation/Fillet/Thickness/Width] before the first corner,
    [Area/Dimensions/Rotation] after it. All settings persist per session
    and the non-default state is announced at command start."""

    chamfer = (0.0, 0.0)
    fillet = 0.0
    elevation = 0.0
    thickness = 0.0
    pl_width = 0.0
    rotation = 0.0
    last_area = 100.0
    last_length = 10.0
    last_width = 10.0

    def start(self) -> None:
        self.name = "RECTANG"
        self._first: Point | None = None
        self._await = None
        self._pending = {}
        self._dims = None            # (length, width) from Dimensions
        cls = type(self)
        if (cls.chamfer != (0.0, 0.0) or cls.fillet or cls.elevation
                or cls.thickness or cls.pl_width or cls.rotation):
            self.ctx.echo(tr(
                "Current rectangle modes: Chamfer={c1:g} x {c2:g} "
                "Elevation={e:g} Fillet={f:g} Thickness={t:g} Width={w:g} "
                "Rotation={r:g}",
                c1=cls.chamfer[0], c2=cls.chamfer[1], e=cls.elevation,
                f=cls.fillet, t=cls.thickness, w=cls.pl_width,
                r=cls.rotation))
        self._first_prompt()

    def _first_prompt(self) -> None:
        self.ctx.prompt(tr(
            "Specify first corner point or "
            "[Chamfer/Elevation/Fillet/Thickness/Width]:"))

    def _corner_prompt(self) -> None:
        self.ctx.prompt(tr(
            "Specify other corner point or [Area/Dimensions/Rotation]:"))

    # -- geometry --------------------------------------------------------------
    def _to_local(self, point: Point) -> tuple[float, float]:
        rot = math.radians(type(self).rotation)
        dx, dy = point[0] - self._first[0], point[1] - self._first[1]
        return (dx * math.cos(rot) + dy * math.sin(rot),
                -dx * math.sin(rot) + dy * math.cos(rot))

    def _build(self, length: float, width: float) -> None:
        cls = type(self)
        try:
            points = actions.rect_vertices(
                self._first, length, width, rotation_deg=cls.rotation,
                chamfer=cls.chamfer, fillet=cls.fillet,
                pl_width=cls.pl_width)
        except ValueError:
            self.ctx.echo(tr("Zero-size rectangle — nothing created."))
            self.ctx.finish()
            return
        attribs = {}
        if cls.elevation:
            attribs["elevation"] = cls.elevation
        if cls.thickness:
            attribs["thickness"] = cls.thickness
        self.ctx.execute(actions.add_polyline_ex(
            points, closed=True, name="RECTANG", dxfattribs=attribs))
        self.ctx.finish()

    def _corner_loss(self) -> float:
        """Area removed by the active chamfers or fillets (4 corners)."""
        cls = type(self)
        if cls.fillet > 0.0:
            return (4.0 - math.pi) * cls.fillet * cls.fillet
        d1, d2 = cls.chamfer
        return 2.0 * d1 * d2

    # -- input -----------------------------------------------------------------
    def on_point(self, point: Point) -> None:
        if self._await in ("rot_p1", "rot_p2"):
            if self._await == "rot_p1":
                self._pending["rp1"] = point
                self._await = "rot_p2"
                self.ctx.prompt(tr("Specify second point:"))
            else:
                p1 = self._pending["rp1"]
                type(self).rotation = math.degrees(
                    math.atan2(point[1] - p1[1], point[0] - p1[0]))
                self._await = None
                self._first_prompt() if self._first is None \
                    else self._corner_prompt()
            return
        if self._await is not None:
            return                    # numeric sub-prompt: ignore picks
        if self._first is None:
            self._first = point
            self.last_point = point
            self._corner_prompt()
            return
        if self._dims is not None:
            # Dimensions placement: the pick chooses the quadrant
            lx, ly = self._to_local(point)
            length = self._dims[0] if lx >= 0 else -self._dims[0]
            width = self._dims[1] if ly >= 0 else -self._dims[1]
            self._build(length, width)
            return
        lx, ly = self._to_local(point)
        self._build(lx, ly)

    def on_enter(self) -> None:
        defaults = {
            "chamfer1": type(self).chamfer[0],
            "chamfer2": None,        # filled when reached (defaults to d1)
            "elevation": type(self).elevation,
            "fillet": type(self).fillet,
            "thickness": type(self).thickness,
            "plwidth": type(self).pl_width,
            "area": type(self).last_area,
            "area_len": type(self).last_length,
            "area_wid": type(self).last_width,
            "dim_len": type(self).last_length,
            "dim_wid": type(self).last_width,
            "rot": type(self).rotation,
        }
        if self._await == "area_lw":
            self.on_option("L")
            return
        if self._await in defaults:
            value = defaults[self._await]
            if value is None:
                value = self._pending.get("d1", 0.0)
            self.on_option(f"{value:g}")
            return
        self.ctx.finish()

    def on_option(self, text: str) -> bool:
        t = text.upper()
        value = _parse_number(text)
        cls = type(self)
        # numeric sub-prompts
        if self._await == "chamfer1":
            if value is None or value < 0:
                return False
            self._pending["d1"] = value
            self._await = "chamfer2"
            self.ctx.prompt(tr(
                "Specify second chamfer distance for rectangles <{d:g}>:",
                d=value))
            return True
        if self._await == "chamfer2":
            if value is None or value < 0:
                return False
            cls.chamfer = (self._pending["d1"], value)
            cls.fillet = 0.0          # chamfer and fillet are exclusive
            self._await = None
            self._first_prompt()
            return True
        if self._await == "fillet":
            if value is None or value < 0:
                return False
            cls.fillet = value
            cls.chamfer = (0.0, 0.0)
            self._await = None
            self._first_prompt()
            return True
        if self._await in ("elevation", "thickness", "plwidth"):
            if value is None:
                return False
            setattr(cls, {"elevation": "elevation", "thickness": "thickness",
                          "plwidth": "pl_width"}[self._await], value)
            self._await = None
            self._first_prompt()
            return True
        if self._await == "area":
            if value is None or value <= 0:
                return False
            cls.last_area = value
            self._await = "area_lw"
            self.ctx.prompt(tr(
                "Calculate rectangle dimensions based on [Length/Width] "
                "<Length>:"))
            return True
        if self._await == "area_lw":
            if t in ("L", "LENGTH"):
                self._await = "area_len"
                self.ctx.prompt(tr("Enter rectangle length <{v:g}>:",
                                   v=cls.last_length))
                return True
            if t in ("W", "WIDTH"):
                self._await = "area_wid"
                self.ctx.prompt(tr("Enter rectangle width <{v:g}>:",
                                   v=cls.last_width))
                return True
            return False
        if self._await in ("area_len", "area_wid"):
            if value is None or value <= 0:
                return False
            # the target area includes the corner cut (official rule)
            total = cls.last_area + self._corner_loss()
            other = total / value
            if self._await == "area_len":
                cls.last_length = value
                self._build(value, other)
            else:
                cls.last_width = value
                self._build(other, value)
            self._await = None
            return True
        if self._await == "dim_len":
            if value is None or value <= 0:
                return False
            cls.last_length = value
            self._await = "dim_wid"
            self.ctx.prompt(tr("Specify width for rectangles <{v:g}>:",
                               v=cls.last_width))
            return True
        if self._await == "dim_wid":
            if value is None or value <= 0:
                return False
            cls.last_width = value
            self._dims = (cls.last_length, value)
            self._await = None
            self._corner_prompt()     # the next pick places the quadrant
            return True
        if self._await == "rot":
            if t in ("P", "PICK", "POINTS"):
                self._await = "rot_p1"
                self.ctx.prompt(tr("Specify first point:"))
                return True
            if value is None:
                return False
            cls.rotation = value
            self._await = None
            self._first_prompt() if self._first is None \
                else self._corner_prompt()
            return True
        if self._await is not None:
            return False
        # keywords
        if self._first is None:
            if t in ("C", "CHAMFER"):
                self._await = "chamfer1"
                self.ctx.prompt(tr(
                    "Specify first chamfer distance for rectangles <{d:g}>:",
                    d=cls.chamfer[0]))
                return True
            if t in ("E", "ELEVATION"):
                self._await = "elevation"
                self.ctx.prompt(tr(
                    "Specify the elevation for rectangles <{v:g}>:",
                    v=cls.elevation))
                return True
            if t in ("F", "FILLET"):
                self._await = "fillet"
                self.ctx.prompt(tr(
                    "Specify fillet radius for rectangles <{v:g}>:",
                    v=cls.fillet))
                return True
            if t in ("T", "THICKNESS"):
                self._await = "thickness"
                self.ctx.prompt(tr(
                    "Specify thickness for rectangles <{v:g}>:",
                    v=cls.thickness))
                return True
            if t in ("W", "WIDTH"):
                self._await = "plwidth"
                self.ctx.prompt(tr(
                    "Specify line width for rectangles <{v:g}>:",
                    v=cls.pl_width))
                return True
            return False
        if t in ("A", "AREA"):
            self._await = "area"
            self.ctx.prompt(tr(
                "Enter area of rectangle in current units <{v:g}>:",
                v=cls.last_area))
            return True
        if t in ("D", "DIMENSIONS"):
            self._await = "dim_len"
            self.ctx.prompt(tr("Specify length for rectangles <{v:g}>:",
                               v=cls.last_length))
            return True
        if t in ("R", "ROTATION"):
            self._await = "rot"
            self.ctx.prompt(tr(
                "Specify rotation angle or [Pick points] <{v:g}>:",
                v=cls.rotation))
            return True
        return False

    def preview_segments(self, cursor: Point):
        if self._first is None or self._await is not None:
            return []
        try:
            if self._dims is not None:
                lx, ly = self._to_local(cursor)
                length = self._dims[0] if lx >= 0 else -self._dims[0]
                width = self._dims[1] if ly >= 0 else -self._dims[1]
                points = actions.rect_vertices(
                    self._first, length, width,
                    rotation_deg=type(self).rotation)
            else:
                lx, ly = self._to_local(cursor)
                points = actions.rect_vertices(
                    self._first, lx, ly, rotation_deg=type(self).rotation)
        except ValueError:
            return []
        ring = [(p[0], p[1]) for p in points]
        return list(zip(ring, ring[1:] + ring[:1]))


class PolygonTool(Tool):
    """POLYGON with AutoCAD's full flow: sides (POLYSIDES session default),
    Edge, Inscribed/Circumscribed with sticky <I/C> default, and the
    orientation rules — a typed radius puts the bottom edge horizontal, a
    picked point is a vertex (I) or an edge midpoint (C)."""

    last_sides = 4        # POLYSIDES: session-only default
    last_mode = "I"

    def start(self) -> None:
        self.name = "POLYGON"
        self._sides = 0
        self._center: Point | None = None
        self._mode = None
        self._edge_first: Point | None = None
        self._stage = "sides"
        self.ctx.prompt(tr("Enter number of sides <{n}>:",
                           n=type(self).last_sides))

    def _mode_prompt(self) -> None:
        self._stage = "mode"
        self.ctx.prompt(tr(
            "Enter an option [Inscribed in circle/Circumscribed about "
            "circle] <{m}>:", m=type(self).last_mode))

    def _build_ring(self, ring) -> None:
        self.ctx.execute(actions.add_polyline(ring, closed=True))
        self.ctx.finish()

    def _typed_radius(self, radius: float) -> None:
        # bottom edge horizontal (snap angle 0): vertices straddle -90
        first = -90.0 + 180.0 / self._sides
        r = radius if self._mode == "I" \
            else radius / math.cos(math.pi / self._sides)
        self._build_ring(actions.polygon_ring(
            self._center, self._sides, r, first))

    def _dragged_radius(self, point: Point) -> None:
        theta = math.degrees(math.atan2(point[1] - self._center[1],
                                        point[0] - self._center[0]))
        dist = math.dist(self._center, point)
        if dist <= 0.0:
            return
        if self._mode == "I":
            first, r = theta, dist                 # the pick IS a vertex
        else:
            first = theta + 180.0 / self._sides    # the pick is a midpoint
            r = dist / math.cos(math.pi / self._sides)
        self._build_ring(actions.polygon_ring(
            self._center, self._sides, r, first))

    def on_option(self, text: str) -> bool:
        t = text.upper()
        if self._stage == "sides":
            try:
                sides = int(text)
            except ValueError:
                return False
            if 3 <= sides <= 1024:
                self._sides = sides
                type(self).last_sides = sides
                self._stage = "center"
                self.ctx.prompt(tr("Specify center of polygon or [Edge]:"))
                return True
            self.ctx.echo(tr("Between 3 and 1024 sides."))
            return True
        if self._stage == "center" and t in ("E", "EDGE"):
            self._stage = "edge1"
            self.ctx.prompt(tr("Specify first endpoint of edge:"))
            return True
        if self._stage == "mode":
            if t in ("I", "INSCRIBED"):
                self._mode = "I"
            elif t in ("C", "CIRCUMSCRIBED"):
                self._mode = "C"
            else:
                return False
            type(self).last_mode = self._mode
            self._stage = "radius"
            self.ctx.prompt(tr("Specify radius of circle:"))
            return True
        if self._stage == "radius":
            radius = _parse_number(text)
            if radius is None or radius <= 0:
                return False
            self._typed_radius(radius)
            return True
        return False

    def on_enter(self) -> None:
        if self._stage == "sides":
            self._sides = type(self).last_sides
            self._stage = "center"
            self.ctx.prompt(tr("Specify center of polygon or [Edge]:"))
            return
        if self._stage == "mode":
            self.on_option(type(self).last_mode)
            return
        self.ctx.finish()

    def on_point(self, point: Point) -> None:
        if self._stage == "center":
            self._center = point
            self.last_point = point
            self._mode_prompt()
            return
        if self._stage == "mode":
            # picking instead of answering: accept the default mode and
            # treat the pick as the dragged radius (AutoCAD flow shortcut)
            self._mode = type(self).last_mode
            self._stage = "radius"
            self._dragged_radius(point)
            return
        if self._stage == "radius":
            self._dragged_radius(point)
            return
        if self._stage == "edge1":
            self._edge_first = point
            self.last_point = point
            self._stage = "edge2"
            self.ctx.prompt(tr("Specify second endpoint of edge:"))
            return
        if self._stage == "edge2":
            try:
                ring = actions.polygon_from_edge(
                    self._edge_first, point, self._sides)
            except ValueError:
                self.ctx.echo(tr("Zero-length edge."))
                return
            self._build_ring(ring)

    def preview_segments(self, cursor: Point):
        if self._stage in ("mode", "radius") and self._center is not None:
            mode = self._mode or type(self).last_mode
            theta = math.degrees(math.atan2(cursor[1] - self._center[1],
                                            cursor[0] - self._center[0]))
            dist = math.dist(self._center, cursor)
            if dist <= 0.0:
                return []
            if mode == "I":
                first, r = theta, dist
            else:
                first = theta + 180.0 / self._sides
                r = dist / math.cos(math.pi / self._sides)
            pts = actions.polygon_ring(self._center, self._sides, r, first)
            return list(zip(pts, pts[1:] + pts[:1]))
        if self._stage == "edge2" and self._edge_first is not None:
            try:
                pts = actions.polygon_from_edge(
                    self._edge_first, cursor, self._sides)
            except ValueError:
                return []
            return list(zip(pts, pts[1:] + pts[:1]))
        return []


TOOL_CLASSES = {
    "LINE": LineTool,
    "CIRCLE": CircleTool,
    "ARC": ArcTool,
    "PLINE": PlineTool,
    "RECTANG": RectangTool,
    "POLYGON": PolygonTool,
    "ELLIPSE": EllipseTool,
    "POINT": PointTool,
    "TEXT": TextTool,
    "MTEXT": MTextTool,
}
