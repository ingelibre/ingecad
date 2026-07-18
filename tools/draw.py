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


class LineTool(Tool):
    def start(self) -> None:
        self.name = "LINE"
        self._points: list[Point] = []
        self.ctx.prompt(tr("LINE Specify first point:"))

    def on_point(self, point: Point) -> None:
        if self._points:
            self.ctx.execute(actions.add_line(self._points[-1], point))
        self._points.append(point)
        self.last_point = point
        self.ctx.prompt(tr("Specify next point or [Close/Undo] <Enter ends>:"))

    def on_option(self, text: str) -> bool:
        t = text.upper()
        if t in ("C", "CLOSE") and len(self._points) >= 3:
            self.ctx.execute(actions.add_line(self._points[-1], self._points[0]))
            self.ctx.finish()
            return True
        if t in ("U", "UNDO") and self._points:
            # AutoCAD: U inside LINE backs up one segment.
            self._points.pop()
            self.last_point = self._points[-1] if self._points else None
            self.ctx.echo(tr("*segment removed — undo the entity with U after the command*"))
            return True
        return False

    def preview_segments(self, cursor: Point):
        return [(self._points[-1], cursor)] if self._points else []


class CircleTool(Tool):
    def start(self) -> None:
        self.name = "CIRCLE"
        self._mode = "CR"
        self._pts: list[Point] = []
        self.ctx.prompt(tr("CIRCLE Specify center point or [2P/3P]:"))

    def on_option(self, text: str) -> bool:
        t = text.upper()
        if t == "2P" and not self._pts:
            self._mode = "2P"
            self.ctx.prompt(tr("Specify first end point of diameter:"))
            return True
        if t == "3P" and not self._pts:
            self._mode = "3P"
            self.ctx.prompt(tr("Specify first point on circle:"))
            return True
        # center-radius mode accepts a typed radius after the center
        if self._mode == "CR" and self._pts:
            try:
                radius = float(text)
            except ValueError:
                return False
            if radius > 0:
                self.ctx.execute(actions.add_circle(self._pts[0], radius))
                self.ctx.finish()
                return True
        return False

    def on_point(self, point: Point) -> None:
        self._pts.append(point)
        self.last_point = point
        if self._mode == "CR":
            if len(self._pts) == 1:
                self.ctx.prompt(tr("Specify radius:"))
            else:
                radius = math.dist(self._pts[0], self._pts[1])
                if radius > 0:
                    self.ctx.execute(actions.add_circle(self._pts[0], radius))
                self.ctx.finish()
        elif self._mode == "2P":
            if len(self._pts) == 1:
                self.ctx.prompt(tr("Specify second end point of diameter:"))
            else:
                center, radius = actions.circle_from_2p(*self._pts)
                if radius > 0:
                    self.ctx.execute(actions.add_circle(center, radius))
                self.ctx.finish()
        else:  # 3P
            if len(self._pts) < 3:
                self.ctx.prompt(tr("Specify next point on circle:"))
            else:
                try:
                    center, radius = actions.circle_from_3p(*self._pts)
                except ValueError:
                    self.ctx.echo(tr("Collinear points — no circle."))
                else:
                    self.ctx.execute(actions.add_circle(center, radius))
                self.ctx.finish()

    def preview_segments(self, cursor: Point):
        if self._mode == "CR" and self._pts:
            r = math.dist(self._pts[0], cursor)
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
    def start(self) -> None:
        self.name = "ARC"
        self._mode = "3P"
        self._pts: list[Point] = []
        self.ctx.prompt(tr("ARC Specify start point or [Center]:"))

    def on_option(self, text: str) -> bool:
        t = text.upper()
        if t in ("C", "CENTER") and len(self._pts) <= 1:
            # Start already given, or center-first: AutoCAD lets both.
            self._mode = "SCE"
            self.ctx.prompt(tr("Specify center point of arc:"))
            return True
        return False

    def on_point(self, point: Point) -> None:
        self._pts.append(point)
        self.last_point = point
        if self._mode == "3P":
            if len(self._pts) == 1:
                self.ctx.prompt(tr("Specify second point on arc or [Center]:"))
            elif len(self._pts) == 2:
                self.ctx.prompt(tr("Specify end point of arc:"))
            else:
                try:
                    self.ctx.execute(actions.add_arc_3p(*self._pts))
                except ValueError:
                    self.ctx.echo(tr("Collinear points — no arc."))
                self.ctx.finish()
        else:  # SCE: start, center, end
            if len(self._pts) == 1:
                self.ctx.prompt(tr("Specify center point of arc:"))
            elif len(self._pts) == 2:
                self.ctx.prompt(tr("Specify end point of arc:"))
            else:
                self.ctx.execute(actions.add_arc_sce(*self._pts))
                self.ctx.finish()

    def preview_segments(self, cursor: Point):
        if self._mode == "3P" and len(self._pts) == 2:
            try:
                center, r = actions.circle_from_3p(self._pts[0], self._pts[1], cursor)
            except ValueError:
                return [(self._pts[0], self._pts[1]), (self._pts[1], cursor)]
            return _circle_preview(center, r)
        if self._mode == "SCE" and len(self._pts) == 2:
            center = self._pts[1]
            r = math.dist(self._pts[0], center)
            return _circle_preview(center, r)
        if self._pts:
            return [(self._pts[-1], cursor)]
        return []


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
    def start(self) -> None:
        self.name = "PLINE"
        self._pts: list[Point] = []
        self.ctx.prompt(tr("PLINE Specify start point:"))

    def on_point(self, point: Point) -> None:
        self._pts.append(point)
        self.last_point = point
        self.ctx.prompt(tr("Specify next point or [Close] <Enter ends>:"))

    def on_option(self, text: str) -> bool:
        if text.upper() in ("C", "CLOSE") and len(self._pts) >= 3:
            self.ctx.execute(actions.add_polyline(self._pts, closed=True))
            self._pts = []
            self.ctx.finish()
            return True
        return False

    def on_enter(self) -> None:
        if len(self._pts) >= 2:
            self.ctx.execute(actions.add_polyline(self._pts))
        self._pts = []
        self.ctx.finish()

    def on_cancel(self) -> None:
        # AutoCAD keeps what was drawn on Esc too (segments are committed);
        # our PLINE builds one entity, so Esc keeps the collected ones.
        self.on_enter()

    def preview_segments(self, cursor: Point):
        segs = list(zip(self._pts, self._pts[1:]))
        if self._pts:
            segs.append((self._pts[-1], cursor))
        return segs


class RectangTool(Tool):
    def start(self) -> None:
        self.name = "RECTANG"
        self._first: Point | None = None
        self.ctx.prompt(tr("RECTANG Specify first corner:"))

    def on_point(self, point: Point) -> None:
        if self._first is None:
            self._first = point
            self.last_point = point
            self.ctx.prompt(tr("Specify other corner:"))
        else:
            self.ctx.execute(actions.add_rectangle(self._first, point))
            self.ctx.finish()

    def preview_segments(self, cursor: Point):
        if self._first is None:
            return []
        p1, p2 = self._first, cursor
        c = [(p1[0], p1[1]), (p2[0], p1[1]), (p2[0], p2[1]), (p1[0], p2[1])]
        return list(zip(c, c[1:] + c[:1]))


class PolygonTool(Tool):
    def start(self) -> None:
        self.name = "POLYGON"
        self._sides = 0
        self._center: Point | None = None
        self.ctx.prompt(tr("POLYGON Enter number of sides <4>:"))

    def on_option(self, text: str) -> bool:
        if self._sides == 0:
            try:
                sides = int(text)
            except ValueError:
                return False
            if 3 <= sides <= 1024:
                self._sides = sides
                self.ctx.prompt(tr("Specify center of polygon:"))
                return True
            self.ctx.echo(tr("Between 3 and 1024 sides."))
            return True
        return False

    def on_enter(self) -> None:
        if self._sides == 0:
            self._sides = 4
            self.ctx.prompt(tr("Specify center of polygon:"))
        else:
            self.ctx.finish()

    def on_point(self, point: Point) -> None:
        if self._sides == 0:
            return  # still waiting for the side count
        if self._center is None:
            self._center = point
            self.last_point = point
            self.ctx.prompt(tr("Specify a vertex (inscribed):"))
        else:
            self.ctx.execute(actions.add_polygon(self._center, point, self._sides))
            self.ctx.finish()

    def preview_segments(self, cursor: Point):
        if self._center is None or self._sides == 0:
            return []
        pts = actions.polygon_points(self._center, cursor, self._sides)
        return list(zip(pts, pts[1:] + pts[:1]))


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
