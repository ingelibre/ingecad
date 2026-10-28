# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The editing commands and their prompts: STRETCH, BREAK, JOIN, CHAMFER,
ARRAY, MATCHPROP, CHPROP, PEDIT.

Wording follows the AutoCAD Command Reference (STRETCH p.1851, BREAK p.269,
JOIN p.1013, CHAMFER p.313, -ARRAY p.155, MATCHPROP p.1080, PEDIT p.1434).
The geometry is in ``core.modify``, so every flow is testable without a GUI.

Deliberate deviations, each a smaller menu rather than a different one:

* ARRAY runs the classic ``-ARRAY`` prompts and produces plain copies. The
  modern associative array is a parametric object a colleague's AutoCAD
  would have to understand coming back; the round trip matters more here.
* PEDIT offers Close/Open, Join, Width, Reverse and Undo. Fit, Spline, Decurve,
  Ltype gen and Edit vertex are not listed, because a prompt that accepts a
  keyword and does nothing with it is worse than one that never offered it.
"""
from __future__ import annotations

import math

from core import actions, editmath, modify, trimmode
from core.i18n import tr
from tools.base import Point, Tool
from tools.edit import _DisplacementTool


class StretchTool(_DisplacementTool):
    """STRETCH: what the crossing window caught moves, the rest holds."""

    def start(self) -> None:
        super().start()
        self.name = "STRETCH"
        self._rects: list = []
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
        self._ask_base()

    def on_point(self, point: Point) -> None:
        super().on_point(point)
        self.ghost_entities = None          # STRETCH draws its own preview

    def _apply(self, dx: float, dy: float, last: bool) -> None:
        self._commit(dx, dy)

    def _commit(self, dx: float, dy: float) -> None:
        self.ctx.execute(
            modify.stretch_entities(self._entities, self._rects, dx, dy))
        self.ctx.echo(tr("{count} stretched.", count=len(self._entities)))
        self.ctx.finish()

    def preview_segments(self, cursor: Point):
        """The rubber band from the base point, and the objects as the
        click would leave them, stretched live (AutoCAD drags them)."""
        if not self._base:
            return []
        dx, dy = cursor[0] - self._base[0], cursor[1] - self._base[1]
        segments = [(self._base, cursor)]
        if dx or dy:
            segments.extend(modify.stretch_preview(
                self._entities, self._rects, dx, dy, self._tolerance()))
        return segments

    def _tolerance(self) -> float:
        """Chord tolerance for curves: a thousandth of the selection."""
        cached = getattr(self, "_tol", None)
        if cached is None:
            from ezdxf import bbox

            try:
                box = bbox.extents(self._entities, fast=True)
                size = max(box.size.x, box.size.y) if box.has_data else 1.0
            except Exception:
                size = 1.0
            cached = self._tol = max(size * 1e-3, 1e-9)
        return cached


class BreakTool(Tool):
    """BREAK: two points, and what lies between them goes."""

    entity_picker = True

    def start(self) -> None:
        self.name = "BREAK"
        self._entity = None
        self._first: Point | None = None
        self._await_first = False
        self.prompt("Select object:")

    def on_option(self, text: str) -> bool:
        # The resolver first: it turns the localized keyword, or
        # AutoCAD's _global form, into the English key the
        # branches below have always compared against.
        token = self.option(text) or text.strip().upper()
        if self._entity is not None and token in ("F", "FIRST"):
            self._await_first = True
            self.entity_picker = False       # a real point now, so snap it
            self.prompt("Specify first break point:")
            return True
        return False

    def on_point(self, point: Point) -> None:
        if self._entity is None:
            services = self.ctx.services
            entity = services.pick_entity(point) if services else None
            if entity is None:
                self.prompt("Nothing selected. Select object:")
                return
            if entity.dxftype() not in modify.BREAKABLE:
                self.ctx.echo(
                    tr("{kind} cannot be broken.", kind=entity.dxftype()))
                self.ctx.finish()
                return
            self._entity = entity
            # Picking the object also sets the first break point (BREAK,
            # p.269) — until the user says First point.
            self._first = point
            self.last_point = point          # what "@" answers next
            self.entity_picker = False
            self.prompt("Specify second break point or [First point]:")
            return

        if self._await_first:
            self._first = point
            self.last_point = point
            self._await_first = False
            self.prompt("Specify second break point:")
            return

        try:
            command = modify.break_entity(self._entity, self._first, point)
        except modify.ClosedAtOnePoint:
            self.ctx.echo(tr("Closed objects cannot be broken at a single "
                             "point."))
            self.ctx.finish()
            return
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


class ChamferTool(Tool):
    """CHAMFER (reference p. 313): bevel the corner two lines or polyline
    segments make, by two distances or by a length and an angle.

    The options are AutoCAD's: Undo, Polyline (every corner of one),
    Distance, Angle, Trim, mEthod, Multiple, and Shift on the second pick
    for a sharp corner. Each edge keeps the side it was picked on and its
    own properties. GeoCad Yaguarete had to add most of it (lines only, no
    layer kept, a zero-length line at distance 0, two options).
    """

    entity_picker = True
    dist1 = 0.0        # session-sticky, like AutoCAD's CHAMFERA/CHAMFERB
    dist2 = 0.0
    length = 0.0       # CHAMFERC
    angle = 0.0        # CHAMFERD, degrees
    method = "D"       # CHAMMODE: D(istance) or A(ngle)

    OPTIONS = ("Select first line or "
               "[Undo/Polyline/Distance/Angle/Trim/mEthod/Multiple]:")

    def start(self) -> None:
        self.name = "CHAMFER"
        self._first = None
        self._first_pick = None
        self._await = None
        self._multiple = False
        self._done = 0
        self._announce()

    def _announce(self) -> None:
        cls = type(self)
        mode = tr("TRIM") if trimmode.trimmode() else tr("NOTRIM")
        if cls.method == "A":
            self.ctx.echo(tr("({mode} mode) Current chamfer Length = {l}, "
                             "Angle = {a}", mode=mode, l=f"{cls.length:g}",
                             a=f"{cls.angle:g}"))
        else:
            self.ctx.echo(tr("({mode} mode) Current chamfer Dist1 = {d1}, "
                             "Dist2 = {d2}", mode=mode,
                             d1=f"{cls.dist1:g}", d2=f"{cls.dist2:g}"))
        self._first_prompt()

    def _first_prompt(self) -> None:
        self._first = None
        self._first_pick = None
        self.entity_picker = True
        self.prompt(self.OPTIONS)

    def _after(self) -> None:
        self._done += 1
        if self._multiple:
            self._first_prompt()
        else:
            self.ctx.finish()

    def _value(self, text: str, default: float):
        if not text.strip():
            return default
        value = _number(text)
        if value is None or value < 0:
            self.ctx.echo(tr("Requires a positive number."))
            return None
        return value

    def on_option(self, text: str) -> bool:
        # The resolver first: it turns the localized keyword, or
        # AutoCAD's _global form, into the English key the
        # branches below have always compared against.
        token = self.option(text) or text.strip().upper()
        cls = type(self)
        if self._await == "d1":
            value = self._value(text, cls.dist1)
            if value is None:
                return True
            cls.dist1 = value
            self._await = "d2"
            self.prompt("Specify second chamfer distance <{d}>:",
                        d=f"{cls.dist1:g}")
            return True
        if self._await == "d2":
            value = self._value(text, cls.dist1)
            if value is None:
                return True
            cls.dist2 = value
            cls.method = "D"
            self._await = None
            self._first_prompt()
            return True
        if self._await == "length":
            value = self._value(text, cls.length)
            if value is None:
                return True
            cls.length = value
            self._await = "angle"
            self.prompt("Specify chamfer angle from the first line <{a}>:",
                        a=f"{cls.angle:g}")
            return True
        if self._await == "angle":
            value = self._value(text, cls.angle)
            if value is None:
                return True
            cls.angle = value
            cls.method = "A"
            self._await = None
            self._first_prompt()
            return True
        if self._await == "method":
            if token in ("D", "DISTANCE"):
                cls.method = "D"
            elif token in ("A", "ANGLE"):
                cls.method = "A"
            elif text.strip():
                self.ctx.echo(tr("Requires Distance or Angle."))
                return True
            self._await = None
            self._first_prompt()
            return True
        if self._await == "trim":
            if token.startswith("T"):
                trimmode.set_trimmode(True)
            elif token.startswith("N"):
                trimmode.set_trimmode(False)
            elif text.strip():
                self.ctx.echo(tr("Requires Trim or No trim."))
                return True
            self._await = None
            self._first_prompt()
            return True
        if self._first is not None:
            return False
        if token in ("D", "DISTANCE"):
            self._await = "d1"
            self.prompt("Specify first chamfer distance <{d}>:",
                        d=f"{cls.dist1:g}")
            return True
        if token in ("A", "ANGLE"):
            self._await = "length"
            self.prompt("Specify chamfer length on the first line <{d}>:",
                        d=f"{cls.length:g}")
            return True
        if token in ("E", "METHOD"):
            self._await = "method"
            self.prompt("Enter trim method [Distance/Angle] <{m}>:",
                        m=tr("Angle") if cls.method == "A" else tr("Distance"))
            return True
        if token in ("T", "TRIM"):
            self._await = "trim"
            self.prompt("Enter Trim mode option [Trim/No trim] "
                        "<{mode}>:",
                        mode=tr("Trim") if trimmode.trimmode() else tr("No trim"))
            return True
        if token in ("M", "MULTIPLE"):
            self._multiple = True
            self._first_prompt()
            return True
        if token in ("P", "POLYLINE"):
            self._await = "polyline"
            self.prompt("Select 2D polyline:")
            return True
        if token in ("U", "UNDO"):
            if self._done:
                self.ctx.undo_last()
                self._done -= 1
            else:
                self.ctx.echo(tr("Command has been completely undone."))
            self._first_prompt()
            return True
        return False

    def on_enter(self) -> None:
        if self._await in ("d1", "d2", "length", "angle", "method", "trim"):
            self.on_option("")
            return
        self.ctx.finish()

    def on_point(self, point: Point) -> None:
        services = self.ctx.services
        entity = services.pick_entity(point) if services else None
        if self._await == "polyline":
            self._chamfer_polyline(entity)
            return
        if entity is None or entity.dxftype() not in ("LINE", "LWPOLYLINE"):
            self.ctx.echo(tr("CHAMFER works on lines and polyline segments."))
            return
        if self._first is None:
            self._first = entity
            self._first_pick = point
            self.prompt("Select second line or shift-select to apply corner:")
            return
        if entity is self._first and entity.dxftype() == "LINE":
            self.ctx.echo(tr("Pick a different line."))
            return
        distances = self._distances(entity, point)
        if distances is None:
            self.ctx.echo(tr("The chamfer does not fit those lines."))
            self._first_prompt() if self._multiple else self.ctx.finish()
            return
        d1, d2 = distances
        command, reason = modify.chamfer_with_polylines(
            self._first, self._first_pick, entity, point, d1, d2,
            trim=trimmode.trimmode())
        if command is None:
            if reason in ("too large", "nothing"):
                self.ctx.echo(tr("The chamfer does not fit those lines."))
            else:
                self.ctx.echo(tr(_CHAMFER_REASONS.get(
                    reason, "The chamfer does not fit those lines.")))
            self._first_prompt() if self._multiple else self.ctx.finish()
            return
        self.ctx.execute(command)
        self._after()

    def _distances(self, entity, point):
        """(d1, d2) for this pair: Shift = a sharp corner; the Angle
        method turns its length and angle into the second distance."""
        cls = type(self)
        if getattr(self, "shift", False):
            return 0.0, 0.0
        if cls.method != "A":
            return cls.dist1, cls.dist2
        s1 = _straight(self._first, self._first_pick)
        s2 = _straight(entity, point)
        if s1 is None or s2 is None:
            return None
        d2 = editmath.chamfer_angle_distance(
            s1, self._first_pick, s2, point, cls.length, cls.angle)
        return None if d2 is None else (cls.length, d2)

    def _chamfer_polyline(self, entity) -> None:
        """Polyline: every corner of one 2D polyline (p. 315)."""
        self._await = None
        if entity is None or entity.dxftype() != "LWPOLYLINE":
            self.ctx.echo(tr("Object selected is not a 2D polyline."))
            self._first_prompt()
            return
        cls = type(self)
        d1, d2 = (cls.dist1, cls.dist2) if cls.method != "A" else (
            cls.length, cls.length * math.tan(math.radians(cls.angle)))
        rows, done, short = editmath.chamfer_polyline(
            entity.get_points("xyseb"), entity.closed, d1, d2)
        if done:
            def factory(msp, e=entity, rows=rows):
                clone = e.copy()
                clone.set_points(rows, format="xyseb")
                msp.add_entity(clone)
                return clone

            self.ctx.execute(actions.ReplaceEntitiesCommand(
                "CHAMFER", [entity], [factory]))
        message = tr("{n} lines were chamfered", n=done)
        if short:
            message += ", " + tr("{n} were too short", n=short)
        self.ctx.echo(message)
        if done:
            self._after()
        else:
            self._first_prompt() if self._multiple else self.ctx.finish()


_CHAMFER_REASONS = {
    "arc": "CHAMFER takes the straight segments of a polyline.",
    "tilted": "The polyline is not in the drawing's plane.",
    "not adjacent": "The segments must be adjacent or separated by "
                    "one segment.",
    "not an end": "A line joins a polyline at one of its end segments.",
    "closed": "A line cannot join a closed polyline.",
    "parallel": "Lines are parallel.",
    "short": "The polyline has no segment there.",
}


def _straight(entity, pick):
    """The straight edge picked: a LINE, or a polyline's segment."""
    if entity.dxftype() == "LINE":
        return _seg(entity)
    found = modify.polyline_pick(entity, pick)
    return None if isinstance(found, str) else found[1]


class ArrayTool(Tool):
    """ARRAY: the command-line flow of -ARRAY, producing plain copies."""

    wants_selection = True

    def start(self) -> None:
        self.name = "ARRAY"
        self._entities: list = []
        self._mode = None
        self._await = None
        self._rows = 1
        self._cols = 1
        self._row_spacing = 0.0
        self._center: Point | None = None
        self._count = 4
        self._fill = 360.0

    def on_selection(self, entities: list) -> None:
        if not entities:
            self.ctx.finish()
            return
        self._entities = entities
        self.prompt("Enter the type of array [Rectangular/Polar] <R>:")

    def on_option(self, text: str) -> bool:
        # The resolver first: it turns the localized keyword, or
        # AutoCAD's _global form, into the English key the
        # branches below have always compared against.
        token = self.option(text) or text.strip().upper()
        if self._mode is None:
            if token in ("", "R", "RECTANGULAR"):
                self._mode = "rect"
                self._await = "rows"
                self.prompt("Enter the number of rows (---) <1>:")
                return True
            if token in ("P", "POLAR"):
                self._mode = "polar"
                self.prompt("Specify center point of array:")
                return True
            return False
        handler = getattr(self, f"_take_{self._await}", None)
        return handler(text) if handler else False

    def on_enter(self) -> None:
        if self._mode is None:
            self.on_option("R")
            return
        if self._await:
            self.on_option("")
            return
        self.ctx.finish()

    # -- rectangular
    def _read_count(self, text: str):
        """A count typed at a <1> prompt: Enter is 1; anything but a
        positive whole number is refused, as AutoCAD refuses it (a typed
        "COU" became one row)."""
        if not text.strip():
            return 1
        value = _number(text)
        if value is None or value < 1 or int(value) != value:
            self.ctx.echo(tr("Requires a positive integer."))
            return None
        return int(value)

    def _take_rows(self, text: str) -> bool:
        rows = self._read_count(text)
        if rows is None:
            self.prompt("Enter the number of rows (---) <1>:")
            return True
        self._rows = rows
        self._await = "cols"
        self.prompt("Enter the number of columns (|||) <1>:")
        return True

    def _take_cols(self, text: str) -> bool:
        cols = self._read_count(text)
        if cols is None:
            self.prompt("Enter the number of columns (|||) <1>:")
            return True
        self._cols = cols
        if self._rows <= 1 and self._cols <= 1:
            self.ctx.echo(tr("One row and one column is the object itself."))
            self.ctx.finish()
            return True
        if self._rows > 1:
            self._await = "row_spacing"
            self.prompt("Enter the distance between rows (---):")
        else:
            # one row: there is no distance between rows to ask (-ARRAY);
            # asking it put the column spacing typed next into rows
            self._await = "col_spacing"
            self.prompt("Specify the distance between columns (|||):")
        return True

    def _spacing(self, text: str):
        value = _number(text)
        if value is None or value == 0:
            # Enter is no spacing at all: the copies stacked on the original
            self.ctx.echo(tr("Requires a nonzero value."))
            return None
        return value

    def _take_row_spacing(self, text: str) -> bool:
        spacing = self._spacing(text)
        if spacing is None:
            self.prompt("Enter the distance between rows (---):")
            return True
        self._row_spacing = spacing
        if self._cols <= 1:
            return self._place(0.0)
        self._await = "col_spacing"
        self.prompt("Specify the distance between columns (|||):")
        return True

    def _take_col_spacing(self, text: str) -> bool:
        spacing = self._spacing(text)
        if spacing is None:
            self.prompt("Specify the distance between columns (|||):")
            return True
        return self._place(spacing)

    def _place(self, col_spacing: float) -> bool:
        self.ctx.execute(modify.array_rect(
            self._entities, self._rows, self._cols,
            self._row_spacing, col_spacing, self.ucs().angle))
        self.ctx.echo(tr("{count} copies placed.",
                         count=(self._rows * self._cols - 1)
                         * len(self._entities)))
        self.ctx.finish()
        return True

    # -- polar
    def _take_count(self, text: str) -> bool:
        self._count = int(_number(text) or 0)
        if self._count < 2:
            self.ctx.echo(tr("An array needs at least two items."))
            self.ctx.finish()
            return True
        self._await = "fill"
        self.prompt("Specify the angle to fill (+=ccw, -=cw) <360>:")
        return True

    def _take_fill(self, text: str) -> bool:
        self._fill = _number(text) if text.strip() else 360.0
        self._await = "rotate"
        self.prompt("Rotate arrayed objects? [Yes/No] <Y>:")
        return True

    def _take_rotate(self, text: str) -> bool:
        # "No", "N" and "_N" all decline; anything else (including Enter,
        # which takes the <Y> default) rotates.
        rotate = not (self.option(text) or text.strip().upper()).startswith("N")
        self.ctx.execute(modify.array_polar(
            self._entities, self._center, self._count, self._fill, rotate))
        self.ctx.echo(tr("{count} copies placed.",
                         count=(self._count - 1) * len(self._entities)))
        self.ctx.finish()
        return True

    def on_point(self, point: Point) -> None:
        if self._mode == "polar" and self._center is None:
            self._center = point
            self._await = "count"
            self.prompt("Enter the number of items in the array:")


class MatchPropTool(Tool):
    """MATCHPROP: one source, then every destination you click."""

    entity_picker = True

    def start(self) -> None:
        self.name = "MATCHPROP"
        self._source = None
        self.prompt("Select source object:")

    def on_point(self, point: Point) -> None:
        services = self.ctx.services
        entity = services.pick_entity(point) if services else None
        if entity is None:
            self.prompt("Nothing selected. Select source object:")
            return
        if self._source is None:
            self._source = entity
            self.ctx.echo(tr("Current active settings: Color Layer Ltype "
                             "Ltscale Lineweight Thickness"))
            self.prompt("Select destination object(s):")
            return
        if entity is self._source:
            return
        self.ctx.execute(modify.match_properties(self._source, [entity]))
        # AutoCAD keeps painting until Enter.


class PeditTool(Tool):
    """PEDIT, with the options that exist here.

    Fit, Spline, Decurve, Ltype gen and Edit vertex are not offered — the
    prompt lists only what it can do, rather than accepting a keyword and
    doing nothing with it.
    """

    entity_picker = True

    def start(self) -> None:
        self.name = "PEDIT"
        self._entity = None
        self._await = None
        self.prompt("Select polyline:")

    def _menu(self) -> None:
        closed = bool(getattr(self._entity, "closed", False))
        first = tr("Open") if closed else tr("Close")
        self.prompt("Enter an option [{first}/Join/Width/Reverse/Undo/eXit] "
                    "<eXit>:", first=first)

    def selection_prompt(self) -> str:
        return tr("Select objects:")

    def on_selection(self, entities: list) -> None:
        """Join: the objects picked after the J option."""
        self._await = None
        command, added = modify.pedit_join(self._entity, entities)
        if command is not None:
            self.ctx.execute(command)
            self._entity = command.new_entities[0]
        self.ctx.echo(tr("{count} segments added to polyline", count=added))
        self._menu()

    def on_point(self, point: Point) -> None:
        if self._entity is not None:
            return
        services = self.ctx.services
        entity = services.pick_entity(point) if services else None
        if entity is None:
            self.prompt("Nothing selected. Select polyline:")
            return
        if entity.dxftype() in ("LINE", "ARC"):
            self._await = "convert"
            self._candidate = entity
            self.prompt("Object selected is not a polyline. Do you "
                        "want it to turn into one? <Y>:")
            return
        if entity.dxftype() != "LWPOLYLINE":
            self.ctx.echo(tr("PEDIT works on polylines, lines and arcs."))
            self.ctx.finish()
            return
        self._entity = entity
        self.entity_picker = False
        self._menu()

    def on_enter(self) -> None:
        if self._await == "convert":
            self._convert()
            return
        if self._await == "width":
            self.ctx.echo(tr("Requires a number."))
            return
        self.ctx.finish()

    def _convert(self) -> None:
        command = modify.to_polyline(self._candidate)
        if command is None:
            self.ctx.finish()
            return
        self.ctx.execute(command)
        self._entity = command.new_entities[0]
        self._await = None
        self.entity_picker = False
        self._menu()

    def on_option(self, text: str) -> bool:
        # The resolver first: it turns the localized keyword, or
        # AutoCAD's _global form, into the English key the
        # branches below have always compared against.
        token = self.option(text) or text.strip().upper()
        if self._await == "convert":
            if token.startswith("N"):
                self.ctx.finish()
            else:
                self._convert()
            return True
        if self._await == "width":
            value = _number(text)
            if value is None or value < 0:
                self.ctx.echo(tr("Requires a positive number."))
                return True
            self._await = None
            self.ctx.execute(modify.polyline_edit(self._entity, "width", value))
            self._menu()
            return True
        if self._entity is None:
            return False
        if token in ("C", "CLOSE"):
            self.ctx.execute(modify.polyline_edit(self._entity, "close"))
            self._menu()
            return True
        if token in ("O", "OPEN"):
            self.ctx.execute(modify.polyline_edit(self._entity, "open"))
            self._menu()
            return True
        if token in ("J", "JOIN"):
            if self._entity.closed:
                self.ctx.echo(tr("Cannot join to a closed polyline."))
                self._menu()
                return True
            self._await = "join"
            self.ctx.services.request_selection()
            return True
        if token in ("W", "WIDTH"):
            self._await = "width"
            self.prompt("Specify new width for all segments:")
            return True
        if token in ("R", "REVERSE"):
            self.ctx.execute(modify.polyline_edit(self._entity, "reverse"))
            self.ctx.echo(tr("Polyline direction reversed."))
            self._menu()
            return True
        if token in ("U", "UNDO"):
            self.ctx.undo_last()
            self._menu()
            return True
        if token in ("X", "EXIT"):
            self.ctx.finish()
            return True
        return False


def _seg(entity):
    return (entity.dxf.start.x, entity.dxf.start.y,
            entity.dxf.end.x, entity.dxf.end.y)


def _number(text: str):
    try:
        return float(text.strip())
    except (TypeError, ValueError):
        return None


class DrawOrderTool(Tool):
    """DRAWORDER: send the selection to back / bring it to front.

    Above/Under relative to reference objects are not offered — the canvas
    batches by layer/color and only honors the absolute groups, and the
    prompt lists only what it can do (the PEDIT rule).
    """

    wants_selection = True

    #: Set by the menu entries that already know which way to go (Tools >
    #: Draw Order > Bring to Front, and the canvas shortcut menu), so the
    #: user picks objects and it happens — no option to answer.
    mode: str | None = None

    def start(self) -> None:
        self.name = "DRAWORDER"
        self._entities: list = []

    def on_selection(self, entities: list) -> None:
        if not entities:
            self.ctx.finish()
            return
        self._entities = entities
        if self.mode:
            self._apply(self.mode)
            return
        self.prompt("Enter object ordering option [Front/Back] <Back>:")

    def _apply(self, mode: str) -> None:
        from core.draworder import DrawOrderCommand

        self.ctx.execute(DrawOrderCommand(self._entities, mode))
        self.ctx.echo(tr("{count} object(s) reordered.",
                         count=len(self._entities)))
        self.ctx.finish()

    def on_option(self, text: str) -> bool:
        if not self._entities:
            return False
        # The resolver first: it turns the localized keyword, or
        # AutoCAD's _global form, into the English key the
        # branches below have always compared against.
        word = self.option(text) or text.strip().upper()
        if word in ("F", "FRONT"):
            self._apply("front")
            return True
        if word in ("B", "BACK", ""):
            self._apply("back")
            return True
        return False

    def on_enter(self) -> None:
        if self._entities:
            self._apply("back")


def _layer_names_of(entities: list) -> list[str]:
    seen: list[str] = []
    for entity in entities:
        name = entity.dxf.get("layer", "0")
        if name not in seen:
            seen.append(name)
    return seen


def _layers_off_command(document, keep: set[str], name: str):
    """One undo step turning off every layer not in ``keep``."""
    from core.commands import CompositeCommand
    from core.layers import LayerPropertyCommand

    commands = []
    for layer in document.doc.layers:
        lname = layer.dxf.name
        if lname not in keep and layer.is_on():
            commands.append(LayerPropertyCommand(lname, "on", False))
    return CompositeCommand(name, commands) if commands else None


class LayIsoTool(Tool):
    """LAYISO: hide every layer except those of the selected objects.

    AutoCAD's Off mode (Command Reference p. 1005). The previous on/off
    state is remembered on the document for LAYUNISO, session-scoped like
    AutoCAD's.
    """

    wants_selection = True

    def start(self) -> None:
        self.name = "LAYISO"

    def selection_prompt(self) -> str:
        return tr("Select objects on the layer(s) to be isolated:")

    def on_selection(self, entities: list) -> None:
        if not entities:
            self.ctx.finish()
            return
        document = self.ctx.services.window.document
        keep = set(_layer_names_of(entities))
        document._layiso_prev = {
            layer.dxf.name: layer.is_on() for layer in document.doc.layers}
        command = _layers_off_command(document, keep, tr("isolate layers"))
        if command is None:
            self.ctx.echo(tr("All layers were already isolated."))
        else:
            self.ctx.execute(command)
            self.ctx.echo(tr("Isolated: {names}.", names=", ".join(sorted(keep))))
        self.ctx.finish()


class LayOffTool(Tool):
    """LAYOFF: turn off the layer of each picked object, until Enter."""

    entity_picker = True

    def start(self) -> None:
        self.name = "LAYOFF"
        self.prompt("Select an object on the layer to be turned off or [Undo]:")

    def on_point(self, point: Point) -> None:
        services = self.ctx.services
        entity = services.pick_entity(point) if services else None
        if entity is None:
            return
        from core.layers import LayerPropertyCommand

        name = entity.dxf.get("layer", "0")
        self.ctx.execute(LayerPropertyCommand(name, "on", False))
        self.ctx.echo(tr('Layer "{name}" has been turned off.', name=name))

    def on_option(self, text: str) -> bool:
        if (self.option(text) or text.strip().upper()) in ("U", "UNDO"):
            self.ctx.undo_last()
            return True
        return False

    def on_enter(self) -> None:
        self.ctx.finish()


class LayFrzTool(Tool):
    """LAYFRZ: freeze the layer of each picked object, until Enter.

    AutoCAD's prompt, less the Settings branch (viewport and block
    nesting), as LAYOFF already does. The current layer cannot be frozen.
    """

    entity_picker = True

    def start(self) -> None:
        self.name = "LAYFRZ"
        self.prompt("Select an object on a layer to be frozen or [Undo]:")

    def on_point(self, point: Point) -> None:
        services = self.ctx.services
        entity = services.pick_entity(point) if services else None
        if entity is None:
            return
        from core.layers import LayerPropertyCommand

        name = entity.dxf.get("layer", "0")
        document = services.window.document
        if name == document.doc.header.get("$CLAYER", "0"):
            self.ctx.echo(tr('Cannot freeze layer "{name}". It is the current '
                             'layer.', name=name))
            return
        self.ctx.execute(LayerPropertyCommand(name, "frozen", True))
        self.ctx.echo(tr('Layer "{name}" has been frozen.', name=name))

    def on_option(self, text: str) -> bool:
        if (self.option(text) or text.strip().upper()) in ("U", "UNDO"):
            self.ctx.undo_last()
            return True
        return False

    def on_enter(self) -> None:
        self.ctx.finish()


class _LayerLockTool(Tool):
    """LAYLCK / LAYULK: lock or unlock the layer of ONE picked object."""

    entity_picker = True
    command = ""
    lock = True

    def start(self) -> None:
        self.name = self.command
        if self.lock:
            self.prompt("Select an object on the layer to be locked:")
        else:
            self.prompt("Select an object on the layer to be unlocked:")

    def on_point(self, point: Point) -> None:
        services = self.ctx.services
        entity = services.pick_entity(point) if services else None
        if entity is None:
            return
        from core.layers import LayerPropertyCommand

        name = entity.dxf.get("layer", "0")
        self.ctx.execute(LayerPropertyCommand(name, "locked", self.lock))
        if self.lock:
            self.ctx.echo(tr('Layer "{name}" has been locked.', name=name))
        else:
            self.ctx.echo(tr('Layer "{name}" has been unlocked.', name=name))
        self.ctx.finish()

    def on_enter(self) -> None:
        self.ctx.finish()


class LayLckTool(_LayerLockTool):
    command = "LAYLCK"
    lock = True


class LayUlkTool(_LayerLockTool):
    command = "LAYULK"
    lock = False


class ImageAdjustTool(Tool):
    """-IMAGEADJUST: option, then a 0-100 value, applied to the selection.

    The reference's tree: Contrast/Fade/Brightness, defaults 50/50/0;
    fade 100 blends the image into the background (the tracing setup).
    """

    wants_selection = True

    def start(self) -> None:
        self.name = "IMAGEADJUST"
        self._images: list = []
        self._attr = None

    def selection_prompt(self) -> str:
        return tr("Select image(s):")

    def on_selection(self, entities: list) -> None:
        self._images = [e for e in entities if e.dxftype() == "IMAGE"]
        if not self._images:
            self.ctx.echo(tr("No images selected."))
            self.ctx.finish()
            return
        self.prompt(
            "Enter image option [Contrast/Fade/Brightness] <Brightness>:")

    def wants_raw_text(self) -> bool:
        return bool(self._images)

    def _current(self, attr: str) -> int:
        return int(self._images[0].dxf.get(attr, 0 if attr == "fade" else 50))

    def on_option(self, text: str) -> bool:
        if not self._images:
            return False
        # The resolver first: it turns the localized keyword, or
        # AutoCAD's _global form, into the English key the
        # branches below have always compared against.
        word = self.option(text) or text.strip().upper()
        if self._attr is None:
            named = {"C": "contrast", "CONTRAST": "contrast",
                     "F": "fade", "FADE": "fade",
                     "B": "brightness", "BRIGHTNESS": "brightness",
                     "": "brightness"}
            if word not in named:
                return False
            self._attr = named[word]
            self.prompt("Enter {name} value (0-100) <{value}>:",
                        name=self._attr, value=self._current(self._attr))
            return True
        try:
            value = int(float(text)) if text.strip() else self._current(self._attr)
        except ValueError:
            return False
        if not 0 <= value <= 100:
            self.ctx.echo(tr("Value must be between 0 and 100."))
            return True
        from core.image_ops import ImageAdjustCommand

        self.ctx.execute(ImageAdjustCommand(self._images,
                                            **{self._attr: value}))
        self.ctx.finish()
        return True

    def on_enter(self) -> None:
        if not self._images:
            self.ctx.finish()
        elif self._attr is None:
            self.on_option("")
        else:
            self.on_option(" ")


class ImageTransparencyTool(Tool):
    """TRANSPARENCY: background pixels of the selected images ON/OFF."""

    wants_selection = True

    def start(self) -> None:
        self.name = "TRANSPARENCY"
        self._images: list = []

    def selection_prompt(self) -> str:
        return tr("Select image(s):")

    def on_selection(self, entities: list) -> None:
        self._images = [e for e in entities if e.dxftype() == "IMAGE"]
        if not self._images:
            self.ctx.echo(tr("No images selected."))
            self.ctx.finish()
            return
        from ezdxf.entities.image import Image

        current = "ON" if (self._images[0].dxf.flags
                           & Image.USE_TRANSPARENCY) else "OFF"
        self.prompt("Enter transparency mode [ON/OFF] <{current}>:",
                    current=current)

    def _apply(self, on: bool) -> None:
        from core.image_ops import ImageTransparencyCommand

        self.ctx.execute(ImageTransparencyCommand(self._images, on))
        self.ctx.finish()

    def on_option(self, text: str) -> bool:
        if not self._images:
            return False
        # The resolver first: it turns the localized keyword, or
        # AutoCAD's _global form, into the English key the
        # branches below have always compared against.
        word = self.option(text) or text.strip().upper()
        if word in ("ON",):
            self._apply(True)
            return True
        if word in ("OFF",):
            self._apply(False)
            return True
        return False

    def on_enter(self) -> None:
        if self._images:
            from ezdxf.entities.image import Image

            self._apply(not (self._images[0].dxf.flags
                             & Image.USE_TRANSPARENCY) == 0)


class _IsolationTool(Tool):
    """Shared body of ISOLATEOBJECTS and HIDEOBJECTS.

    Both take a selection and both are display-only, so neither touches the
    undo stack: UNISOLATEOBJECTS is how AutoCAD undoes them.
    """

    wants_selection = True
    isolate = False          # True: keep these, hide the rest

    def start(self) -> None:
        self.name = "ISOLATEOBJECTS" if self.isolate else "HIDEOBJECTS"

    def selection_prompt(self) -> str:
        return tr("Select objects:")

    def on_selection(self, entities: list) -> None:
        if not entities:
            self.ctx.finish()
            return
        from core import isolate as isolation

        window = self.ctx.services.window
        document = window.document
        if self.isolate:
            isolation.isolate_objects(document, entities)
            self.ctx.echo(tr("{count} object(s) isolated.",
                             count=len(entities)))
        else:
            isolation.hide_objects(document, entities)
            self.ctx.echo(tr("{count} object(s) hidden.", count=len(entities)))
        window.after_isolation_change()
        self.ctx.finish()


class IsolateObjectsTool(_IsolationTool):
    """ISOLATEOBJECTS (p. 956): show these, hide everything else."""

    isolate = True


class HideObjectsTool(_IsolationTool):
    """HIDEOBJECTS (p. 912): hide these, leave everything else visible."""

    isolate = False


class SelectSimilarTool(Tool):
    """SELECTSIMILAR (p. 1726): add every object of the same type and
    matching properties to the selection.

    Its one documented option is SEttings, which opens the Select Similar
    Settings dialog — so that is the only option the prompt offers.
    """

    wants_selection = True

    def start(self) -> None:
        self.name = "SELECTSIMILAR"
        self._entities: list = []

    def selection_prompt(self) -> str:
        return tr("Select objects or [SEttings]:")

    def on_selection(self, entities: list) -> None:
        if not entities:
            self.ctx.finish()
            return
        self._entities = entities
        self._apply()

    def _apply(self) -> None:
        from core import similar
        from views.similar_dialog import saved_keys

        services = self.ctx.services
        document = services.window.document
        found = similar.find_similar(document, self._entities, saved_keys())
        # finish() clears the selection (a command that ends drops its
        # highlight), so the result is set after it — this command's whole
        # output IS a selection.
        self.ctx.finish()
        services.selection = {e.dxf.handle for e in found}
        services.changed.emit()
        self.ctx.echo(tr("{count} object(s) selected.", count=len(found)))

    def on_option(self, text: str) -> bool:
        # The resolver first: it turns the localized keyword, or
        # AutoCAD's _global form, into the English key the
        # branches below have always compared against.
        word = self.option(text) or text.strip().upper()
        if word in ("SE", "SETTINGS"):
            from views.similar_dialog import (SelectSimilarSettingsDialog,
                                              save_keys)

            window = self.ctx.services.window
            dialog = SelectSimilarSettingsDialog(window)
            if dialog.exec():
                save_keys(dialog.keys())
            if self._entities:
                self._apply()
            return True
        return False


#: What command draws each kind of object, for ADDSELECTED.
_ADDSELECTED_COMMANDS = {
    "LINE": "LINE", "CIRCLE": "CIRCLE", "ARC": "ARC",
    "LWPOLYLINE": "PLINE", "POLYLINE": "PLINE", "ELLIPSE": "ELLIPSE",
    "POINT": "POINT", "TEXT": "TEXT", "MTEXT": "MTEXT", "HATCH": "HATCH",
    "INSERT": "INSERT", "XLINE": "XLINE", "RAY": "RAY", "SPLINE": "SPLINE",
    "IMAGE": "IMAGEATTACH", "DIMENSION": "DIMLINEAR", "LEADER": "LEADER",
}


class AddSelectedTool(Tool):
    """ADDSELECTED (p. 103): "creates a new object based on the object type
    and general properties of a selected object".

    The reference is precise about the difference from COPY: it duplicates
    only the *general* properties — colour, layer, linetype, lineweight —
    and then prompts for the new object's own geometry. Text, MText and
    Attribute Definition additionally carry their text style and height,
    which the manual lists as their special properties.
    """

    entity_picker = True

    def start(self) -> None:
        self.name = "ADDSELECTED"
        services = self.ctx.services
        picked = services._selection_entities() if services else []
        if len(picked) == 1:
            self._use(picked[0])
            return
        self.prompt("Select object:")

    def on_point(self, point) -> None:
        services = self.ctx.services
        entity = services.pick_entity(point) if services else None
        if entity is not None:
            self._use(entity)

    def _use(self, entity) -> None:
        from core import layers as layer_ops

        command = _ADDSELECTED_COMMANDS.get(entity.dxftype())
        if command is None:
            self.ctx.echo(tr("No command creates a {kind}.",
                             kind=entity.dxftype()))
            self.ctx.finish()
            return
        window = self.ctx.services.window
        document = window.document
        # The general properties become the current ones, so whatever the
        # command draws next inherits them — which is exactly what AutoCAD
        # means by "adopts the general properties of the circle".
        layer = entity.dxf.get("layer", None)
        if layer and layer in document.doc.layers:
            document.doc.header["$CLAYER"] = layer
        for prop, attr in (("color", "color"), ("linetype", "linetype"),
                           ("lineweight", "lineweight")):
            value = entity.dxf.get(attr, None)
            if value is not None:
                layer_ops.set_current_property(document, prop, value)
        # Text, MText and Attribute Definition also carry style and height
        # (the reference's table of special properties).
        if entity.dxftype() in ("TEXT", "MTEXT", "ATTDEF"):
            style = entity.dxf.get("style", None)
            if style:
                document.doc.header["$TEXTSTYLE"] = style
            height = entity.dxf.get("height", None) or entity.dxf.get(
                "char_height", None)
            if height:
                document.doc.header["$TEXTSIZE"] = float(height)
                # TEXT/MTEXT keep their own session-sticky default; set that
                # too, or the height the reference promises would be ignored.
                from tools.draw import TextTool

                TextTool.default_height = float(height)
        self.ctx.finish()
        window._refresh_props_toolbar()
        window._invoke_command(command)


class ChpropTool(Tool):
    """CHPROP (reference p. 323): the properties of a selection, typed.

    Offers Color, LAyer, LType, ltScale, LWeight and Thickness. Transparency,
    Material and Annotative are not listed: the prompt names only what this
    command changes (the PEDIT rule). Each answer is one undoable
    ``SetPropertyCommand`` and the menu comes back until Enter, as in
    AutoCAD.
    """

    wants_selection = True

    MENU = ("Enter property to change "
            "[Color/LAyer/LType/ltScale/LWeight/Thickness]:")
    #: option key -> (DXF attribute, prompt, what an entity without one has)
    PROPERTIES = {
        "C": ("color", "Enter new color <{current}>:", 256),
        "LA": ("layer", "Enter new layer name <{current}>:", "0"),
        "LT": ("linetype", "Enter new linetype name <{current}>:", "ByLayer"),
        "S": ("ltscale", "Specify new linetype scale <{current}>:", 1.0),
        "LW": ("lineweight", "Enter new lineweight <{current}>:", -1),
        "T": ("thickness", "Specify new thickness <{current}>:", 0.0),
    }

    def start(self) -> None:
        self.name = "CHPROP"
        self._entities: list = []
        self._property = None

    def on_selection(self, entities: list) -> None:
        if not entities:
            self.ctx.finish()
            return
        self._entities = list(entities)
        # From here on what is typed is a word or a name, never a snap.
        self.entity_picker = True
        self._menu()

    def _menu(self) -> None:
        self._property = None
        self.prompt(self.MENU)

    def wants_raw_text(self) -> bool:
        # A layer or linetype name may carry spaces.
        return self._property in ("LA", "LT")

    def _supporting(self, attribute: str) -> list:
        return [e for e in self._entities
                if e.is_alive and e.dxf.is_supported(attribute)]

    def _current(self, key: str) -> str:
        attribute, _prompt, default = self.PROPERTIES[key]
        values = {e.dxf.get(attribute, default)
                  for e in self._supporting(attribute)}
        if len(values) != 1:
            return tr("varies")
        value = values.pop()
        if key == "C":
            return {256: "BYLAYER", 0: "BYBLOCK"}.get(value, str(value))
        if key == "LW":
            from core.layers import lineweight_label

            return lineweight_label(value)
        if key in ("S", "T"):
            return f"{float(value):.4f}"
        return str(value)

    def on_option(self, text: str) -> bool:
        if self._property is None:
            key = self.option(text) or text.strip().upper()
            if key not in self.PROPERTIES:
                self.ctx.echo(tr("Invalid option keyword."))
                self._menu()
                return True
            self._property = key
            _attribute, source, _default = self.PROPERTIES[key]
            self.prompt(source, current=self._current(key))
            return True
        value = self._value(self._property, text.strip())
        if value is not None:
            self._apply(self._property, value)
        self._menu()
        return True

    def on_enter(self) -> None:
        if self._property is not None:
            self._menu()               # Enter keeps the current value
            return
        self.ctx.finish()

    def _document(self):
        services = self.ctx.services
        return getattr(services, "document", None) if services else None

    def _value(self, key: str, raw: str):
        """What was typed as the new value, or None (already explained)."""
        from core import layers, linetypes
        from tools.attributes import parse_color

        document = self._document()
        if key == "C":
            value = parse_color(raw)
            if value is None:
                self.ctx.echo(tr("Invalid color."))
            return value
        if key == "LA":
            if document is not None and raw not in document.doc.layers:
                self.ctx.echo(tr('Cannot find layer "{name}".', name=raw))
                return None
            return raw
        if key == "LT":
            if raw.upper() in ("BYLAYER", "BYBLOCK"):
                return "ByLayer" if raw.upper() == "BYLAYER" else "ByBlock"
            if document is None:
                return raw
            loaded = {n.upper(): n
                      for n in layers.available_linetypes(document)}
            if raw.upper() in loaded:
                return loaded[raw.upper()]
            # AutoCAD tries acad.lin before giving up.
            if raw.upper() in linetypes.library(document):
                self.ctx.execute(linetypes.LoadLinetypesCommand([raw]))
                return raw
            self.ctx.echo(tr('Linetype "{name}" is not loaded.', name=raw))
            return None
        if key == "LW":
            word = {"BYLAYER": -1, "BYBLOCK": -2, "DEFAULT": -3}
            if raw.upper() in word:
                return word[raw.upper()]
            try:
                return layers.snap_lineweight(float(raw))
            except ValueError:
                self.ctx.echo(tr("Invalid lineweight."))
                return None
        try:
            value = float(raw)
        except ValueError:
            self.ctx.echo(tr("Requires a number."))
            return None
        if key == "S" and value <= 0:
            self.ctx.echo(tr("Requires a positive number."))
            return None
        return value

    def _apply(self, key: str, value) -> None:
        attribute = self.PROPERTIES[key][0]
        targets = self._supporting(attribute)
        if targets:
            self.ctx.execute(
                actions.SetPropertyCommand(targets, attribute, value))


class HatchEditTool(Tool):
    """HATCHEDIT — "Modifies an existing hatch or fill" (reference p. 896).

    Access, as the manual lists it: the command, Modify > Object > Hatch,
    the shortcut menu on a selected hatch, and -- the way anyone actually
    reaches it -- a double-click on the hatch.
    """

    entity_picker = True

    def start(self) -> None:
        self.name = "HATCHEDIT"
        services = self.ctx.services
        selection = services._selection_entities() if services else []
        hatches = [e for e in selection if e.dxftype() == "HATCH"]
        if len(hatches) == 1:
            # noun-verb: a hatch was already selected, edit that one
            self._edit(hatches[0])
            return
        self.prompt("Select hatch object:")

    def _edit(self, entity) -> None:
        services = self.ctx.services
        if services is not None:
            services.edit_hatch(entity)
        self.ctx.finish()

    def on_point(self, point: Point) -> None:
        services = self.ctx.services
        entity = services.pick_entity(point) if services else None
        if entity is None or entity.dxftype() != "HATCH":
            self.ctx.echo(tr("That is not a hatch."))
            self.prompt("Select hatch object:")
            return
        self._edit(entity)


class TextEditTool(Tool):
    """TEXTEDIT (DDEDIT, ED): pick an annotation and edit it in place, one
    after another until Enter -- the editor a double-click opens. It was an
    unknown command."""

    entity_picker = True

    def start(self) -> None:
        self.name = "TEXTEDIT"
        self.prompt("Select an annotation object:")

    def on_point(self, point: Point) -> None:
        services = self.ctx.services
        entity = services.pick_entity(point) if services else None
        opener = getattr(services, "open_text_editor_for", None)
        if entity is None or opener is None or not opener(entity):
            self.ctx.echo(tr("That is not an annotation object."))
            self.prompt("Select an annotation object:")
            return
        self.ctx.finish()


MODIFY_TOOL_CLASSES = {
    "TEXTEDIT": TextEditTool,
    "HATCHEDIT": HatchEditTool,
    "STRETCH": StretchTool,
    "BREAK": BreakTool,
    "JOIN": JoinTool,
    "CHAMFER": ChamferTool,
    "ARRAY": ArrayTool,
    "MATCHPROP": MatchPropTool,
    "CHPROP": ChpropTool,
    "PEDIT": PeditTool,
    "DRAWORDER": DrawOrderTool,
    "LAYISO": LayIsoTool,
    "LAYOFF": LayOffTool,
    "LAYFRZ": LayFrzTool,
    "LAYLCK": LayLckTool,
    "LAYULK": LayUlkTool,
    "IMAGEADJUST": ImageAdjustTool,
    "TRANSPARENCY": ImageTransparencyTool,
    "ISOLATEOBJECTS": IsolateObjectsTool,
    "HIDEOBJECTS": HideObjectsTool,
    "SELECTSIMILAR": SelectSimilarTool,
    "ADDSELECTED": AddSelectedTool,
}
