# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""DIM, QDIM, DIMBREAK, DIMJOGGED and DIMSPACE (issue #39), with AutoCAD's
prompts (docs/reference/dim/autocad-dim-qdim-dimbreak.md).

DIM is the 2016+ unified command: a router over the dimension tools -- what
you point at decides the kind (a line gives a linear dimension, a circle a
diameter, an arc a radius, two bare points a linear one) and the command
keeps running until Enter. The headless work is in :mod:`core.dim_commands`.
"""
from __future__ import annotations

import math

from core import actions, dim_commands, ocs
from core.i18n import tr
from tools.base import Point, Tool
from tools.dimension import (DimLinearTool, _entity_endpoints,
                             set_last_dimension)

_MAIN_PROMPT = ("Select objects or specify first extension line origin or "
                "[Angular/Baseline/Continue/Ordinate/aliGn/Distribute/Layer/Undo]:")
_LAYER_PROMPT = ("Enter layer name or select object for layer "
                 "[Use current/eXit] <Use current>:")


class DimTool(DimLinearTool):
    """DIM: one command for every dimension, running until Enter."""

    def start(self) -> None:
        self.name = "DIM"
        self._layer: str | None = None
        self._stage = "main"
        self._radial = None          # the circle/arc picked, if any
        self._radial_kind = "radius"
        self._pending_layer = False
        self._count = 0
        super().start()
        self.name = "DIM"           # DimLinearTool.start named it
        self.entity_picker = True    # the first click may be an object
        self.prompt(_MAIN_PROMPT)

    def _location_prompt(self) -> str:
        if self._radial is not None:
            if self._radial_kind == "diameter":
                return ("Specify diameter dimension location or "
                        "[Radius/Mtext/Text/Angle/Undo]:")
            return ("Specify radius dimension location or "
                    "[Diameter/Mtext/Text/Angle/Undo]:")
        return "Specify dimension line location or [Mtext/Text/Angle/Undo]:"

    def _reset_round(self) -> None:
        self._p1 = self._p2 = None
        self._radial = None
        self._forced_angle = None
        self._select_mode = False
        self._reset_text_state()
        self._stage = "main"
        self.entity_picker = True
        self.prompt(_MAIN_PROMPT)

    # -- prompts -----------------------------------------------------------------
    def on_enter(self) -> None:
        if self._pending_layer:
            self._pending_layer = False
            self._layer = None                    # <Use current>
            self.prompt(_MAIN_PROMPT)
            return
        if self._text_enter():
            return
        if self._stage == "main":
            self.ctx.finish()
            return
        self._reset_round()                       # Enter mid-round: back

    def on_option(self, text: str) -> bool:
        if self._pending_layer:
            key = self.option(text) or text.upper()
            if key in ("U", "USE CURRENT", "USECURRENT"):
                self._layer = None
            elif key in ("X", "EXIT"):
                pass
            else:
                document = getattr(getattr(self.ctx.services, "window", None),
                                   "document", None) or getattr(
                                       self.ctx.services, "document", None)
                if document is not None and text not in document.doc.layers:
                    self.ctx.echo(tr("Layer \"{name}\" not found.", name=text))
                else:
                    self._layer = text
            self._pending_layer = False
            self.prompt(_MAIN_PROMPT)
            return True
        if self._stage == "main":
            key = self.option(text) or text.upper()
            if key in ("A", "ANGULAR", "B", "BASELINE", "C", "CONTINUE"):
                name = {"A": "DIMANGULAR", "ANGULAR": "DIMANGULAR",
                        "B": "DIMBASELINE", "BASELINE": "DIMBASELINE",
                        "C": "DIMCONTINUE", "CONTINUE": "DIMCONTINUE"}[key]
                self._hand_over(name)
                return True
            if key in ("O", "ORDINATE", "G", "ALIGN", "D", "DISTRIBUTE"):
                self.ctx.echo(tr("{option} is not available in DIM yet — "
                                 "use DIMORDINATE, DIMALIGNED or DIMSPACE.",
                                 option=key))
                return True
            if key in ("L", "LAYER"):
                self._pending_layer = True
                self.prompt(_LAYER_PROMPT)
                return True
            if key in ("U", "UNDO"):
                if self._count:
                    self.ctx.undo_last()
                    self._count -= 1
                else:
                    self.ctx.echo(tr("Nothing to undo."))
                return True
            return False
        # a round in progress
        if self._radial is not None:
            key = self.option(text) or text.upper()
            if key in ("R", "RADIUS"):
                self._radial_kind = "radius"
                self.prompt(self._location_prompt())
                return True
            if key in ("D", "DIAMETER"):
                self._radial_kind = "diameter"
                self.prompt(self._location_prompt())
                return True
            if key in ("U", "UNDO"):
                self._reset_round()
                return True
            return self._text_options(text, ready=True)
        key = self.option(text) or text.upper()
        if key in ("U", "UNDO") and self._pending is None:
            self._reset_round()
            return True
        return super().on_option(text)

    def _hand_over(self, name: str) -> None:
        """Angular/Baseline/Continue run their own command (AutoCAD returns
        to DIM afterwards; here DIM ends -- type DIM again)."""
        window = getattr(self.ctx.services, "window", None)
        tools = getattr(window, "tools", None)
        self.ctx.finish()
        if tools is not None:
            tools.start_tool(name)
        else:
            self.ctx.echo(tr("Use {name}.", name=name))

    # -- points ------------------------------------------------------------------
    def on_point(self, point: Point) -> None:
        if self._pending is not None or self._pending_layer:
            if self._pending_layer:
                e = self.ctx.services.pick_entity(point) if self.ctx.services else None
                if e is not None:
                    self._layer = e.dxf.layer
                self._pending_layer = False
                self.prompt(_MAIN_PROMPT)
            return
        if self._stage == "main":
            e = self.ctx.services.pick_entity(point) if self.ctx.services else None
            if e is not None and e.dxftype() in ("CIRCLE", "ARC"):
                self._radial = e
                self._radial_kind = "diameter" if e.dxftype() == "CIRCLE" else "radius"
                self._stage = "locate"
                self.entity_picker = False
                self.prompt(self._location_prompt())
                return
            ends = _entity_endpoints(e, point, True) if e is not None else None
            if ends is not None:
                self._p1, self._p2 = ends
                self._stage = "locate"
                self.entity_picker = False
                self.prompt(self._location_prompt())
                return
            self._p1 = point
            self.last_point = point
            self._stage = "second"
            self.entity_picker = False
            self.prompt("Specify second extension line origin:")
            return
        if self._stage == "second":
            self._p2 = point
            self.last_point = point
            self._stage = "locate"
            self.prompt(self._location_prompt())
            return
        # locate
        if self._radial is not None:
            c = ocs.center_wcs(self._radial)
            make = (actions.dim_diameter if self._radial_kind == "diameter"
                    else actions.dim_radius)
            cmd = make((c.x, c.y), float(self._radial.dxf.radius), point,
                       text=self._text, text_rotation=self._text_rotation)
        else:
            point = self._adjust_location(point)
            cmd = self._make(point)
        cmd.layer = self._layer
        self.ctx.execute(cmd)
        self._count += 1
        if cmd.dim is not None and (cmd.dim.dxf.dimtype & 15) in (0, 1):
            set_last_dimension(cmd.dim)
        self._reset_round()

    def preview_segments(self, cursor: Point):
        if self._radial is not None:
            c = ocs.center_wcs(self._radial)
            return [((c.x, c.y), cursor)]
        if self._stage == "second" and self._p1 is not None:
            return [(self._p1, cursor)]
        return []

    def preview_command(self, cursor: Point):
        if self._radial is not None or self._stage != "locate":
            return None
        return super().preview_command(cursor)

    def preview_dimension(self, cursor: Point):
        if self._radial is not None or self._stage != "locate":
            return None
        return super().preview_dimension(cursor)


class QDimTool(Tool):
    """QDIM: a series of dimensions from a selection, one undo step."""

    wants_selection = True
    modifies_selection = False   # reads the set; locked layers count

    _PROMPT = ("Specify dimension line position, or "
               "[Continuous/Staggered/Baseline/Ordinate/Radius/Diameter/"
               "datumPoint/Edit/seTtings] <{mode}>:")
    _MODES = {"C": "Continuous", "CONTINUOUS": "Continuous",
              "S": "Staggered", "STAGGERED": "Staggered",
              "B": "Baseline", "BASELINE": "Baseline",
              "O": "Ordinate", "ORDINATE": "Ordinate",
              "R": "Radius", "RADIUS": "Radius",
              "D": "Diameter", "DIAMETER": "Diameter"}
    mode = "Continuous"          # sticky for the session, as AutoCAD keeps it

    def start(self) -> None:
        self.name = "QDIM"
        self._entities: list = []
        self._datum: Point | None = None
        self._pending_datum = False
        self.ctx.echo(tr("Select geometry to dimension:"))

    def selection_prompt(self) -> str:
        return tr("Select geometry to dimension:")

    def on_selection(self, entities: list) -> None:
        self._entities = [e for e in entities if e.dxftype() in (
            "LINE", "LWPOLYLINE", "ARC", "CIRCLE")]
        if not self._entities:
            self.ctx.echo(tr("Nothing to dimension in the selection."))
            self.ctx.finish()
            return
        self.prompt(self._PROMPT, mode=QDimTool.mode)

    def on_option(self, text: str) -> bool:
        key = self.option(text) or text.upper()
        mode = self._MODES.get(key)
        if mode is not None:
            QDimTool.mode = mode
            self.prompt(self._PROMPT, mode=mode)
            return True
        if key in ("P", "DATUMPOINT"):
            self._pending_datum = True
            self.prompt("Select new datum point:")
            return True
        if key in ("E", "EDIT", "T", "SETTINGS"):
            self.ctx.echo(tr("{option} is not available in QDIM yet.",
                             option=key))
            return True
        return False

    def on_point(self, point: Point) -> None:
        if self._pending_datum:
            self._datum = point
            self._pending_datum = False
            self.prompt(self._PROMPT, mode=QDimTool.mode)
            return
        document = getattr(self.ctx.services, "document", None)
        window = getattr(self.ctx.services, "window", None)
        if document is None and window is not None:
            document = window.document
        cmd = dim_commands.qdim(document, self._entities, point, QDimTool.mode,
                                self._datum)
        if cmd is None:
            self.ctx.echo(tr("Nothing to dimension in the selection."))
        else:
            self.ctx.execute(cmd)
            for sub in cmd.commands:
                if sub.dim is not None and (sub.dim.dxf.dimtype & 15) in (0, 1):
                    set_last_dimension(sub.dim)
            self.ctx.echo(tr("{count} dimension(s) created.",
                             count=len(cmd.commands)))
        self.ctx.finish()

    def preview_segments(self, cursor: Point):
        return []


def _document(ctx):
    document = getattr(ctx.services, "document", None)
    if document is None:
        window = getattr(ctx.services, "window", None)
        document = getattr(window, "document", None)
    return document


class DimBreakTool(Tool):
    """DIMBREAK: gaps where other objects cross a dimension."""

    entity_picker = True

    def start(self) -> None:
        self.name = "DIMBREAK"
        self._dims: list = []
        self._multiple = False
        self._stage = "dim"
        self._manual: list[Point] = []
        self.prompt("Select dimension to add/remove break or [Multiple]:")

    def on_option(self, text: str) -> bool:
        key = self.option(text) or text.upper()
        if self._stage == "dim":
            if key in ("M", "MULTIPLE"):
                self._multiple = True
                self.prompt("Select dimensions:")
                return True
            return False
        if self._stage == "object":
            if key in ("A", "AUTO"):
                self._auto()
                return True
            if key in ("M", "MANUAL"):
                self._stage = "manual"
                self.prompt("Specify first break point:")
                return True
            if key in ("R", "REMOVE"):
                self._remove()
                return True
        return False

    def on_enter(self) -> None:
        if self._stage == "dim" and self._multiple and self._dims:
            self._stage = "object"
            self.prompt("Select object to break dimension or "
                        "[Auto/Manual/Remove] <Auto>:")
            return
        if self._stage == "object":
            self._auto()
            return
        self.ctx.finish()

    def _auto(self) -> None:
        document = _document(self.ctx)
        obstacles = [e for e in document.current_space()
                     if e.dxftype() in ("LINE", "LWPOLYLINE", "CIRCLE", "ARC",
                                        "ELLIPSE", "SPLINE", "POLYLINE")]
        total = 0
        for dim in self._dims:
            gaps = dim_commands.auto_gaps(document, dim, obstacles)
            if gaps:
                self.ctx.execute(dim_commands.DimBreakCommand(dim, gaps))
                total += len(gaps)
        self.ctx.echo(tr("{count} dimension break(s) created.", count=total))
        self.ctx.finish()

    def _remove(self) -> None:
        document = _document(self.ctx)
        removed = 0
        for dim in self._dims:
            if dim_commands.has_breaks(dim):
                self.ctx.execute(dim_commands.DimBreakRemoveCommand(dim))
                removed += 1
        self.ctx.echo(tr("Dimension breaks removed from {count} dimension(s).",
                         count=removed))
        self.ctx.finish()

    def on_point(self, point: Point) -> None:
        e = self.ctx.services.pick_entity(point) if self.ctx.services else None
        if self._stage == "dim":
            if e is None or e.dxftype() not in ("DIMENSION", "ARC_DIMENSION"):
                self.ctx.echo(tr("Select a dimension."))
                return
            if e not in self._dims:
                self._dims.append(e)
            if self._multiple:
                self.prompt("Select dimensions:")
                return
            self._stage = "object"
            self.prompt("Select object to break dimension or "
                        "[Auto/Manual/Remove] <Auto>:")
            return
        if self._stage == "object":
            if e is None or e in self._dims:
                self.ctx.echo(tr("Select an object that crosses the dimension."))
                return
            document = _document(self.ctx)
            total = 0
            for dim in self._dims:
                gaps = dim_commands.auto_gaps(document, dim, [e])
                if gaps:
                    self.ctx.execute(dim_commands.DimBreakCommand(dim, gaps))
                    total += len(gaps)
            if not total:
                self.ctx.echo(tr("The object does not cross the dimension."))
            else:
                self.ctx.echo(tr("{count} dimension break(s) created.", count=total))
            self.prompt("Select object to break dimension:")
            return
        if self._stage == "manual":
            self._manual.append(point)
            if len(self._manual) < 2:
                self.prompt("Specify second break point:")
                return
            document = _document(self.ctx)
            dim = self._dims[0]
            gaps = dim_commands.manual_gap(document, dim, *self._manual)
            if gaps:
                self.ctx.execute(dim_commands.DimBreakCommand(dim, gaps))
                self.ctx.echo(tr("{count} dimension break(s) created.", count=1))
            else:
                self.ctx.echo(tr("The two points do not span a dimension line."))
            self.ctx.finish()

    def preview_segments(self, cursor: Point):
        if self._stage == "manual" and self._manual:
            return [(self._manual[0], cursor)]
        return []


class DimJoggedTool(Tool):
    """DIMJOGGED: a radius dimension from a centre override, with a jog."""

    entity_picker = True

    def start(self) -> None:
        self.name = "DIMJOGGED"
        self._ent = None
        self._override: Point | None = None
        self._location: Point | None = None
        self._text = "<>"
        self._text_rotation: float | None = None
        self._pending: str | None = None
        self.prompt("Select arc or circle:")

    def _location_prompt(self) -> str:
        return "Specify dimension line location or [Mtext/Text/Angle]:"

    def wants_raw_text(self) -> bool:
        return self._pending == "text"

    def on_enter(self) -> None:
        if self._pending == "text":
            self._text, self._pending = "<>", None
            self.prompt(self._location_prompt())
            return
        if self._pending == "textangle":
            self._pending = None
            self.prompt(self._location_prompt())
            return
        self.ctx.finish()

    def on_option(self, text: str) -> bool:
        if self._pending == "text":
            self._text = text or "<>"
            self._pending = None
            self.prompt(self._location_prompt())
            return True
        if self._pending == "textangle":
            try:
                self._text_rotation = float(text)
            except ValueError:
                self.ctx.echo(tr("Requires a numeric angle."))
                return True
            self._pending = None
            self.prompt(self._location_prompt())
            return True
        if self._override is None or self._location is not None:
            return False
        key = self.option(text) or text.upper()
        if key in ("M", "MTEXT", "T", "TEXT"):
            self._pending = "text"
            self.prompt("Enter dimension text <{measured}>:",
                        measured=f"{float(self._ent.dxf.radius):.2f}")
            return True
        if key in ("A", "ANGLE"):
            self._pending = "textangle"
            self.prompt("Specify angle of dimension text:")
            return True
        return False

    def on_point(self, point: Point) -> None:
        if self._pending is not None:
            return
        if self._ent is None:
            e = self.ctx.services.pick_entity(point) if self.ctx.services else None
            if e is None or e.dxftype() not in ("CIRCLE", "ARC"):
                self.ctx.echo(tr("Select an arc or circle."))
                return
            self._ent = e
            self.entity_picker = False
            self.prompt("Specify center location override:")
            return
        if self._override is None:
            self._override = point
            self.last_point = point
            self.prompt(self._location_prompt())
            return
        if self._location is None:
            self._location = point
            self.prompt("Specify jog location:")
            return
        c = ocs.center_wcs(self._ent)
        cmd = dim_commands.dim_jogged((c.x, c.y), float(self._ent.dxf.radius),
                                      self._override, self._location, point,
                                      text=self._text,
                                      text_rotation=self._text_rotation)
        self.ctx.execute(cmd)
        self.ctx.finish()

    def preview_segments(self, cursor: Point):
        if self._ent is None:
            return []
        c = ocs.center_wcs(self._ent)
        if self._override is None:
            return [((c.x, c.y), cursor)]
        if self._location is None:
            return [(self._override, cursor)]
        r = float(self._ent.dxf.radius)
        dx, dy = self._location[0] - c.x, self._location[1] - c.y
        length = math.hypot(dx, dy) or 1.0
        on_arc = (c.x + r * dx / length, c.y + r * dy / length)
        pts = dim_commands.jog_points(self._override, on_arc, cursor, r * 0.1)
        return list(zip(pts, pts[1:]))


class DimSpaceTool(Tool):
    """DIMSPACE: equal spacing between parallel linear dimensions."""

    entity_picker = True

    def start(self) -> None:
        self.name = "DIMSPACE"
        self._base = None
        self._dims: list = []
        self._stage = "base"
        self.prompt("Select base dimension:")

    def on_option(self, text: str) -> bool:
        if self._stage != "value":
            return False
        key = self.option(text) or text.upper()
        if key in ("A", "AUTO"):
            self._apply(None)
            return True
        try:
            value = float(text)
        except ValueError:
            self.ctx.echo(tr("Requires a distance or Auto."))
            return True
        self._apply(value)
        return True

    def on_enter(self) -> None:
        if self._stage == "dims" and self._dims:
            self._stage = "value"
            self.prompt("Enter value or [Auto] <Auto>:")
            return
        if self._stage == "value":
            self._apply(None)
            return
        self.ctx.finish()

    def _apply(self, spacing) -> None:
        document = _document(self.ctx)
        plan = dim_commands.space_plan(document, self._base, self._dims, spacing)
        if not plan:
            self.ctx.echo(tr("No parallel linear dimensions to space."))
        else:
            self.ctx.execute(dim_commands.DimSpaceCommand(plan))
            self.ctx.echo(tr("{count} dimension(s) spaced.", count=len(plan)))
        self.ctx.finish()

    def on_point(self, point: Point) -> None:
        e = self.ctx.services.pick_entity(point) if self.ctx.services else None
        if e is None or not dim_commands.is_linear(e):
            self.ctx.echo(tr("Select a parallel linear dimension."))
            return
        if self._stage == "base":
            self._base = e
            self._stage = "dims"
            self.prompt("Select dimensions to space:")
            return
        if self._stage == "dims":
            if e is not self._base and e not in self._dims:
                self._dims.append(e)
            self.prompt("Select dimensions to space:")


DIMCMD_TOOL_CLASSES = {
    "DIM": DimTool,
    "QDIM": QDimTool,
    "DIMBREAK": DimBreakTool,
    "DIMJOGGED": DimJoggedTool,
    "DIMSPACE": DimSpaceTool,
}
