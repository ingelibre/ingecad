# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Construction/utility tools: XLINE, RAY, DIVIDE, MEASURE, REVCLOUD.

Prompt trees mirror AutoCAD's (docs/reference/draw/); every mutation is a
Command, and multi-entity results (DIVIDE's points, REVCLOUD Object's
replace) are ONE CompositeCommand so U takes them back in one step.
"""
from __future__ import annotations

import math

from core import actions
from core.commands import CompositeCommand
from core.i18n import tr
from tools.base import Point, Tool


def _dir_deg(a: Point, b: Point) -> float:
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


class XlineTool(Tool):
    """XLINE: two-point default plus Hor/Ver/Ang (with Reference)/Bisect/
    Offset — each mode loops placing construction lines until Enter."""

    def start(self) -> None:
        self.name = "XLINE"
        self._mode = "point"
        self._root: Point | None = None
        self._angle = 0.0
        self._pending = {}
        self._await = None
        self.prompt("Specify a point or [Hor/Ver/Ang/Bisect/Offset]:")

    def _emit(self, point: Point, angle_deg: float) -> None:
        self.ctx.execute(actions.add_xline(point, angle_deg))

    def on_option(self, text: str) -> bool:
        # The resolver first: it turns the localized keyword, or
        # AutoCAD's _global form, into the English key the
        # branches below have always compared against.
        t = self.option(text) or text.strip().upper()
        value = None
        try:
            value = float(text)
        except ValueError:
            pass
        if self._await == "angle":
            if t in ("R", "REFERENCE"):
                self._await = "ref_pick"
                self.entity_picker = True
                self.prompt("Select a line object:")
                return True
            if value is None:
                return False
            self._angle = value
            self._await = None
            self._mode = "angled"
            self.prompt("Specify through point:")
            return True
        if self._await == "ref_angle":
            if value is None:
                return False
            self._angle = self._pending["ref"] + value
            self._await = None
            self._mode = "angled"
            self.entity_picker = False
            self.prompt("Specify through point:")
            return True
        if self._await == "offset_dist":
            if t in ("T", "THROUGH"):
                self._pending["through"] = True
                self._await = "offset_pick"
                self.entity_picker = True
                self.prompt("Select a line object:")
                return True
            if value is None or value <= 0:
                return False
            type(self)._offset = value
            self._pending["through"] = False
            self._await = "offset_pick"
            self.entity_picker = True
            self.prompt("Select a line object:")
            return True
        if self._await is not None:
            return False
        if self._mode == "point" and self._root is None:
            if t in ("H", "HOR", "HORIZONTAL"):
                self._mode = "hor"
                self.prompt("Specify through point:")
                return True
            if t in ("V", "VER", "VERTICAL"):
                self._mode = "ver"
                self.prompt("Specify through point:")
                return True
            if t in ("A", "ANG", "ANGLE"):
                self._await = "angle"
                self.prompt("Enter angle of xline (0) or [Reference]:")
                return True
            if t in ("B", "BISECT"):
                self._mode = "bisect"
                self.prompt("Specify angle vertex point:")
                return True
            if t in ("O", "OFFSET"):
                self._await = "offset_dist"
                self.prompt(
                    "Specify offset distance or [Through] <{d:g}>:",
                    d=getattr(type(self), "_offset", 1.0))
                return True
        return False

    _offset = 1.0

    def _line_of(self, entity):
        if entity is None or entity.dxftype() != "LINE":
            self.ctx.echo(tr("Select a line."))
            return None
        s, e = entity.dxf.start, entity.dxf.end
        return (s.x, s.y), (e.x, e.y)

    def on_point(self, point: Point) -> None:
        services = self.ctx.services
        if self._await == "ref_pick":
            ends = self._line_of(services.pick_entity(point) if services else None)
            if ends is None:
                return
            self._pending["ref"] = _dir_deg(*ends)
            self._await = "ref_angle"
            self.entity_picker = False
            self.prompt("Enter angle of xline <0>:")
            return
        if self._await == "offset_pick":
            ends = self._line_of(services.pick_entity(point) if services else None)
            if ends is None:
                return
            self._pending["line"] = ends
            self._await = "offset_side"
            if self._pending.get("through"):
                self.entity_picker = False
                self.prompt("Specify through point:")
            else:
                self.prompt("Specify side to offset:")
            return
        if self._await == "offset_side":
            (a, b) = self._pending["line"]
            angle = _dir_deg(a, b)
            if self._pending.get("through"):
                self._emit(point, angle)
            else:
                # offset toward the picked side by the stored distance
                ux, uy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
                nx, ny = -uy, ux
                side = (point[0] - a[0]) * nx + (point[1] - a[1]) * ny
                s = 1.0 if side >= 0 else -1.0
                d = type(self)._offset
                self._emit((a[0] + s * d * nx, a[1] + s * d * ny), angle)
            # keep looping on the same line-select prompt
            self._await = "offset_pick"
            self.entity_picker = True
            self.prompt("Select a line object:")
            return
        if self._mode == "point":
            if self._root is None:
                self._root = point
                self.last_point = point
                self.prompt("Specify through point:")
            else:
                if math.dist(self._root, point) > 1e-9:
                    self._emit(self._root, _dir_deg(self._root, point))
                self.prompt("Specify through point:")
            return
        if self._mode == "hor":
            self._emit(point, 0.0)
            self.prompt("Specify through point:")
            return
        if self._mode == "ver":
            self._emit(point, 90.0)
            self.prompt("Specify through point:")
            return
        if self._mode == "angled":
            self._emit(point, self._angle)
            self.prompt("Specify through point:")
            return
        if self._mode == "bisect":
            if self._root is None:
                self._root = point
                self.last_point = point
                self.prompt("Specify angle start point:")
            elif "start" not in self._pending:
                self._pending["start"] = point
                self.prompt("Specify angle end point:")
            else:
                a1 = _dir_deg(self._root, self._pending["start"])
                a2 = _dir_deg(self._root, point)
                half = a1 + (((a2 - a1) % 360.0) / 2.0)
                self._emit(self._root, half)
                self.prompt("Specify angle end point:")

    def preview_segments(self, cursor: Point):
        span = 1e5
        def seg(p, ang):
            r = math.radians(ang)
            return [((p[0] - span * math.cos(r), p[1] - span * math.sin(r)),
                     (p[0] + span * math.cos(r), p[1] + span * math.sin(r)))]
        if self._mode == "point" and self._root is not None:
            if math.dist(self._root, cursor) < 1e-9:
                return []
            return seg(self._root, _dir_deg(self._root, cursor))
        if self._mode == "hor":
            return seg(cursor, 0.0)
        if self._mode == "ver":
            return seg(cursor, 90.0)
        if self._mode == "angled":
            return seg(cursor, self._angle)
        return []


class RayTool(Tool):
    def start(self) -> None:
        self.name = "RAY"
        self._start: Point | None = None
        self.prompt("Specify start point:")

    def on_point(self, point: Point) -> None:
        if self._start is None:
            self._start = point
            self.last_point = point
            self.prompt("Specify through point:")
        else:
            if math.dist(self._start, point) > 1e-9:
                self.ctx.execute(actions.add_ray(
                    self._start, _dir_deg(self._start, point)))
            self.prompt("Specify through point:")

    def preview_segments(self, cursor: Point):
        if self._start is None or math.dist(self._start, cursor) < 1e-9:
            return []
        ang = math.radians(_dir_deg(self._start, cursor))
        far = (self._start[0] + 1e5 * math.cos(ang),
               self._start[1] + 1e5 * math.sin(ang))
        return [(self._start, far)]


class _DivideMeasure(Tool):
    """Shared flow: pick object -> value (or Block sub-flow) -> composite."""

    entity_picker = True
    value_prompt = ""
    align_default = True

    def start(self) -> None:
        self._entity = None
        self._pick: Point | None = None
        self._block = None
        self._align = True
        self._await = None
        self.prompt(self._select_prompt())

    def _select_prompt(self) -> str:
        raise NotImplementedError

    def _samples(self, value: float):
        raise NotImplementedError

    def _parse_value(self, text: str):
        raise NotImplementedError

    def on_point(self, point: Point) -> None:
        if self._entity is None:
            services = self.ctx.services
            e = services.pick_entity(point) if services else None
            if e is None or e.dxftype() not in (
                    "LINE", "ARC", "CIRCLE", "ELLIPSE", "LWPOLYLINE",
                    "POLYLINE", "SPLINE"):
                self.ctx.echo(tr("Select a line, arc, circle, ellipse, "
                                 "polyline or spline."))
                return
            self._entity = e
            self._pick = point
            self.prompt(self.value_prompt)

    def on_option(self, text: str) -> bool:
        # The resolver first: it turns the localized keyword, or
        # AutoCAD's _global form, into the English key the
        # branches below have always compared against.
        t = self.option(text) or text.strip().upper()
        if self._entity is None:
            return False
        if self._await == "block_name":
            name = text.strip()
            if t == "?":
                services = self.ctx.services
                names = services.block_names() if services else []
                self.ctx.echo(", ".join(names) if names
                              else tr("No blocks defined."))
                self.prompt("Enter name of block to insert:")
                return True
            if not name:
                return False
            services = self.ctx.services
            if services is not None and name not in services.block_names():
                self.ctx.echo(tr('Unknown block "{name}".', name=name))
                self.prompt("Enter name of block to insert:")
                return True
            self._block = name
            self._await = "block_align"
            self.prompt("Align block with object? [Yes/No] <Y>:")
            return True
        if self._await == "block_align":
            if t in ("", "Y", "YES"):
                self._align = True
            elif t in ("N", "NO"):
                self._align = False
            else:
                return False
            self._await = None
            self.prompt(self.value_prompt)
            return True
        if t in ("B", "BLOCK") and self._await is None:
            self._await = "block_name"
            self.prompt("Enter name of block to insert:")
            return True
        value = self._parse_value(text)
        if value is None:
            return False
        try:
            samples = self._samples(value)
        except ValueError as exc:
            self.ctx.echo(tr("Cannot divide: {error}", error=str(exc)))
            self.ctx.finish()
            return True
        if not samples:
            self.ctx.echo(tr("Nothing to place."))
            self.ctx.finish()
            return True
        commands = []
        for x, y, tangent in samples:
            if self._block:
                commands.append(actions.insert_block(
                    self._block, (x, y),
                    rotation=tangent if self._align else 0.0))
            else:
                commands.append(actions.add_point((x, y)))
        self.ctx.execute(CompositeCommand(self.name, commands))
        self.ctx.echo(tr("{n} placed.", n=len(samples)))
        self.ctx.finish()
        return True

    def on_enter(self) -> None:
        if self._await == "block_align":
            self.on_option("")
            return
        self.ctx.finish()


class DivideTool(_DivideMeasure):
    def start(self) -> None:
        self.name = "DIVIDE"
        self.value_prompt = "Enter the number of segments or [Block]:"
        super().start()

    def _select_prompt(self) -> str:
        return "Select object to divide:"

    def _parse_value(self, text: str):
        try:
            return int(text)
        except ValueError:
            return None

    def _samples(self, value):
        return actions.divide_samples(self._entity, value)


class MeasureTool(_DivideMeasure):
    def start(self) -> None:
        self.name = "MEASURE"
        self.value_prompt = "Specify length of segment or [Block]:"
        super().start()

    def _select_prompt(self) -> str:
        return "Select object to measure:"

    def _parse_value(self, text: str):
        try:
            v = float(text)
        except ValueError:
            return None
        return v if v > 0 else None

    def _samples(self, value):
        return actions.measure_samples(self._entity, value, self._pick)


class RevcloudTool(Tool):
    """REVCLOUD: Rectangular / Polygonal / Freehand / Object (+Reverse),
    sticky arc length and style. The cloud is a closed bulged LWPOLYLINE."""

    arc_length = None            # sticky; None = derive from the view once
    style = "Normal"
    last_mode = "Freehand"

    def start(self) -> None:
        self.name = "REVCLOUD"
        self._mode = None
        self._pts: list[Point] = []
        self._await = None
        self._freehand = False
        self._object = None
        cls = type(self)
        if cls.arc_length is None:
            cls.arc_length = self._auto_arc_length()
        self.ctx.echo(tr(
            "Minimum arc length: {a:g}   Style: {s}", a=cls.arc_length,
            s=tr(cls.style)))
        self.prompt(
            "Specify first point or [Arc length/Object/Rectangular/"
            "Polygonal/Freehand/Style] <{m}>:", m=tr(cls.last_mode))

    def _auto_arc_length(self) -> float:
        # AutoCAD derives the first default from the view size
        services = self.ctx.services
        try:
            rect = services.window.viewport._view_world_rect()
            return max(math.hypot(rect[2] - rect[0], rect[3] - rect[1]) / 60.0,
                       1e-6)
        except Exception:
            return 5.0

    def _finish_cloud(self, loop, reverse: bool = False,
                      replaced=None) -> None:
        cls = type(self)
        try:
            verts = actions.revcloud_vertices(
                loop, cls.arc_length, reverse=reverse,
                calligraphy=(cls.style == "Calligraphy"))
        except ValueError as exc:
            self.ctx.echo(tr("Cannot build the cloud: {error}", error=str(exc)))
            self.ctx.finish()
            return
        add = actions.add_polyline_ex(verts, closed=True, name="REVCLOUD")
        if replaced is not None:
            self.ctx.execute(CompositeCommand(
                "REVCLOUD", [actions.EraseCommand([replaced]), add]))
        else:
            self.ctx.execute(add)
        self.ctx.echo(tr("Revision cloud finished."))
        self.ctx.finish()

    # -- input -----------------------------------------------------------------
    def on_option(self, text: str) -> bool:
        # The resolver first: it turns the localized keyword, or
        # AutoCAD's _global form, into the English key the
        # branches below have always compared against.
        t = self.option(text) or text.strip().upper()
        cls = type(self)
        value = None
        try:
            value = float(text)
        except ValueError:
            pass
        if self._await == "arc":
            if value is None or value <= 0:
                return False
            cls.arc_length = value
            self._await = None
            self.prompt(
                "Specify first point or [Arc length/Object/Rectangular/"
                "Polygonal/Freehand/Style] <{m}>:", m=tr(cls.last_mode))
            return True
        if self._await == "style":
            if t in ("N", "NORMAL"):
                cls.style = "Normal"
            elif t in ("C", "CALLIGRAPHY"):
                cls.style = "Calligraphy"
            elif t != "":
                return False
            self._await = None
            self.prompt(
                "Specify first point or [Arc length/Object/Rectangular/"
                "Polygonal/Freehand/Style] <{m}>:", m=tr(cls.last_mode))
            return True
        if self._await == "reverse":
            if t in ("", "N", "NO"):
                self._finish_cloud(self._pts, reverse=False,
                                   replaced=self._object)
            elif t in ("Y", "YES"):
                self._finish_cloud(self._pts, reverse=True,
                                   replaced=self._object)
            else:
                return False
            return True
        if self._mode is None:
            if t in ("A", "ARC"):
                self._await = "arc"
                self.prompt("Specify minimum length of arc <{a:g}>:",
                            a=cls.arc_length)
                return True
            if t in ("S", "STYLE"):
                self._await = "style"
                self.prompt(
                    "Select arc style [Normal/Calligraphy] <{s}>:",
                    s=tr(cls.style))
                return True
            if t in ("O", "OBJECT"):
                self._mode = "Object"
                cls.last_mode = "Object"
                self.entity_picker = True
                self.prompt("Select object:")
                return True
            if t in ("R", "RECTANGULAR"):
                self._mode = "Rectangular"
                cls.last_mode = "Rectangular"
                self.prompt("Specify first corner point:")
                return True
            if t in ("P", "POLYGONAL"):
                self._mode = "Polygonal"
                cls.last_mode = "Polygonal"
                self.prompt("Specify start point:")
                return True
            if t in ("F", "FREEHAND"):
                self._mode = "Freehand"
                cls.last_mode = "Freehand"
                self.prompt("Specify first point:")
                return True
        return False

    def on_enter(self) -> None:
        if self._await == "reverse":
            self.on_option("")
            return
        if self._await == "style":
            self.on_option("")
            return
        if self._mode == "Polygonal" and len(self._pts) >= 3:
            self._finish_cloud(self._pts)
            return
        if self._mode == "Freehand" and self._freehand and len(self._pts) >= 3:
            self._finish_cloud(self._pts)
            return
        if self._mode is None:
            # Enter takes the <last mode> default
            self.on_option({"Object": "O", "Rectangular": "R",
                            "Polygonal": "P", "Freehand": "F"}[
                                type(self).last_mode])
            return
        self.ctx.finish()

    def on_point(self, point: Point) -> None:
        if self._mode is None:
            # a bare first point starts the default (last) mode
            self.on_option({"Object": "O", "Rectangular": "R",
                            "Polygonal": "P", "Freehand": "F"}[
                                type(self).last_mode])
            if self._mode not in (None, "Object"):
                self.on_point(point)
            return
        if self._mode == "Object":
            services = self.ctx.services
            e = services.pick_entity(point) if services else None
            if e is None or e.dxftype() not in (
                    "CIRCLE", "ELLIPSE", "LWPOLYLINE", "POLYLINE", "SPLINE"):
                self.ctx.echo(tr("Select a circle, ellipse, polyline or "
                                 "spline."))
                return
            try:
                pts, closed = actions._entity_polyline(e)
            except ValueError:
                self.ctx.echo(tr("Cannot build the cloud from that object."))
                return
            self._pts = pts
            self._object = e
            self._await = "reverse"
            self.entity_picker = False
            self.prompt("Reverse direction [Yes/No] <No>:")
            return
        if self._mode == "Rectangular":
            if not self._pts:
                self._pts = [point]
                self.last_point = point
                self.prompt("Specify opposite corner:")
            else:
                a, b = self._pts[0], point
                self._finish_cloud([(a[0], a[1]), (b[0], a[1]),
                                    (b[0], b[1]), (a[0], b[1])])
            return
        if self._mode == "Polygonal":
            self._pts.append(point)
            self.last_point = point
            self.prompt("Specify next point or [Enter to close]:")
            return
        if self._mode == "Freehand":
            if not self._freehand:
                self._freehand = True
                self._pts = [point]
                self.last_point = point
                self.prompt(
                    "Guide crosshairs along cloud path; click to close.")
            else:
                self._pts.append(point)
                self._finish_cloud(self._pts)
            return

    def preview_segments(self, cursor: Point):
        cls = type(self)
        if self._mode == "Freehand" and self._freehand:
            # the hover pipeline calls this on every mouse move: collect the
            # path (click-move-click freehand), spaced at half a chord
            if not self._pts or math.dist(self._pts[-1], cursor) \
                    >= cls.arc_length / 2.0:
                self._pts.append(cursor)
            return list(zip(self._pts, self._pts[1:]))
        if self._mode == "Rectangular" and self._pts:
            a, b = self._pts[0], cursor
            ring = [(a[0], a[1]), (b[0], a[1]), (b[0], b[1]), (a[0], b[1])]
            return list(zip(ring, ring[1:] + ring[:1]))
        if self._mode == "Polygonal" and self._pts:
            segs = list(zip(self._pts, self._pts[1:]))
            segs.append((self._pts[-1], cursor))
            return segs
        return []


CONSTRUCT_TOOL_CLASSES = {
    "XLINE": XlineTool,
    "RAY": RayTool,
    "DIVIDE": DivideTool,
    "MEASURE": MeasureTool,
    "REVCLOUD": RevcloudTool,
}