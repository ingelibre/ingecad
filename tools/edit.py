# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Editing tools: ERASE, MOVE, COPY, ROTATE, SCALE, MIRROR, OFFSET,
TRIM, EXTEND, FILLET.

Noun-verb (preselect then command) and verb-noun (command then "Select
objects:") both work — the controller feeds selections through
``on_selection``. TRIM/EXTEND honor Shift as the modern AutoCAD toggle.
"""
from __future__ import annotations

import math

from core import actions, editmath, modify, ocs, polyoffset
from core.i18n import tr
from tools.base import Point, Tool


class EraseTool(Tool):
    wants_selection = True

    def start(self) -> None:
        self.name = "ERASE"

    def on_selection(self, entities: list) -> None:
        if entities:
            self.ctx.execute(actions.EraseCommand(entities))
            self.ctx.echo(tr("{count} erased.", count=len(entities)))
        self.ctx.finish()


class _DisplacementTool(Tool):
    """The base-point dialogue MOVE, COPY and STRETCH share (MOVE, p.1211):
    a base point, or Displacement -- typed D, or Enter, its default -- for a
    vector; and Enter at the second point takes the first point as the
    displacement ("2,3 then Enter moves 2 in X and 3 in Y")."""

    wants_selection = True

    def start(self) -> None:
        self._entities: list = []
        self._base: Point | None = None
        self._asking_displacement = False

    def _ask_base(self) -> None:
        self.prompt("Specify base point or [Displacement] <Displacement>:")

    def _ask_displacement(self) -> None:
        self._asking_displacement = True
        self.prompt("Specify displacement <0,0,0>:")

    def on_selection(self, entities: list) -> None:
        if not entities:
            self.ctx.finish()
            return
        self._entities = entities
        self._ask_base()

    def on_option(self, text: str) -> bool:
        if self._entities and self._base is None \
                and not self._asking_displacement \
                and self.option(text) == "D":
            self._ask_displacement()
            return True
        return False

    def on_point(self, point: Point) -> None:
        if self._asking_displacement:
            # the typed coordinates ARE the vector, not a place
            self._asking_displacement = False
            self._apply(point[0], point[1], last=True)
            return
        if self._base is None:
            self._base = point
            self.last_point = point
            # the dragged geometry follows the cursor (ghost preview)
            self.ghost_entities = self._entities
            self.ghost_base = point
            self._ask_second(first=True)
            return
        self._apply(point[0] - self._base[0], point[1] - self._base[1],
                    last=False)

    def on_enter(self) -> None:
        if self._asking_displacement:
            self.ctx.finish()                 # <0,0,0>: nothing moves
            return
        if self._entities and self._base is None:
            self._ask_displacement()          # <Displacement> is the default
            return
        if self._base is not None and self._first_second:
            # Enter at the second point: the first point is the vector
            self._apply(self._base[0], self._base[1], last=True)
            return
        self.ctx.finish()

    _first_second = True

    def _ask_second(self, first: bool) -> None:
        self._first_second = first
        self.prompt("Specify second point or <use first point as displacement>:")

    def _apply(self, dx: float, dy: float, last: bool) -> None:
        raise NotImplementedError

    def preview_segments(self, cursor: Point):
        return [(self._base, cursor)] if self._base else []


class MoveTool(_DisplacementTool):
    def start(self) -> None:
        super().start()
        self.name = "MOVE"

    def _apply(self, dx: float, dy: float, last: bool) -> None:
        self.ctx.execute(actions.move_entities(self._entities, dx, dy))
        self.ctx.finish()


class CopyTool(_DisplacementTool):
    """COPY repeats (COPYMODE 0): after the first copy the prompt offers
    Exit and Undo, the copies made so far going back one by one."""

    def start(self) -> None:
        super().start()
        self.name = "COPY"
        self._copies = 0

    def on_option(self, text: str) -> bool:
        if super().on_option(text):
            return True
        key = self.option(text)
        if self._base is not None and not self._first_second:
            if key == "E":
                self.ctx.finish()
                return True
            if key == "U":
                if self._copies and self.ctx.undo_last is not None:
                    self.ctx.undo_last()
                    self._copies -= 1
                if not self._copies:
                    self._ask_second(first=True)
                else:
                    self._ask_more()
                return True
        return False

    def _ask_more(self) -> None:
        self._first_second = False
        self.prompt("Specify second point or [Exit/Undo] <Exit>:")

    def _apply(self, dx: float, dy: float, last: bool) -> None:
        self.ctx.execute(actions.copy_entities(self._entities, dx, dy))
        self._copies += 1
        if last:
            self.ctx.finish()
            return
        self._ask_more()


class RotateTool(Tool):
    wants_selection = True

    def start(self) -> None:
        self.name = "ROTATE"
        self._entities: list = []
        self._base: Point | None = None
        self._reference: float | None = None
        self._ref_first: Point | None = None
        self._copy = False

    def on_selection(self, entities: list) -> None:
        if not entities:
            self.ctx.finish()
            return
        self._entities = entities
        self.prompt("Specify base point:")

    def on_option(self, text: str) -> bool:
        # The resolver first: it turns the localized keyword, or
        # AutoCAD's _global form, into the English key the
        # branches below have always compared against.
        t = self.option(text) or text.upper()
        if t == "C" and self._base is not None and self._reference is None:
            # Copy: the originals stay, a rotated copy is made (p.1588)
            self._copy = True
            self.ctx.echo(tr("Rotating a copy of the selected objects."))
            self.prompt("Specify rotation angle or [Copy/Reference]:")
            return True
        if t in ("R", "REFERENCE") and self._base is not None:
            self._reference = -1.0  # waiting for reference angle
            self.prompt("Specify reference angle (two points or typed):")
            return True
        # typed angle
        if self._base is not None:
            try:
                angle = float(text)
            except ValueError:
                return False
            if self._reference == -1.0:
                self._reference = angle
                self.prompt("Specify new angle:")
            elif self._reference is not None:
                self.ctx.execute(actions.rotate_entities(
                    self._entities, self._base, angle - self._reference,
                    copy=self._copy))
                self.ctx.finish()
            else:
                self.ctx.execute(actions.rotate_entities(
                    self._entities, self._base, angle, copy=self._copy))
                self.ctx.finish()
            return True
        return False

    def on_point(self, point: Point) -> None:
        if self._base is None:
            self._base = point
            self.last_point = point
            # From here the selection turns with the cursor about this point,
            # which is what AutoCAD shows and what makes the angle obvious.
            self.ghost_entities = self._entities
            self.ghost_base = point
            self.prompt("Specify rotation angle or [Copy/Reference]:")
            return
        ang = math.degrees(math.atan2(point[1] - self._base[1],
                                      point[0] - self._base[0]))
        if self._reference == -1.0:
            if self._ref_first is None:
                self._ref_first = point
                self.prompt("Specify second point of reference angle:")
                return
            self._reference = math.degrees(math.atan2(
                point[1] - self._ref_first[1], point[0] - self._ref_first[0]))
            self.prompt("Specify new angle:")
            return
        if self._reference is not None:
            ang -= self._reference
        self.ctx.execute(actions.rotate_entities(self._entities, self._base, ang,
                                                 copy=self._copy))
        self.ctx.finish()

    def preview_segments(self, cursor: Point):
        return [(self._base, cursor)] if self._base else []

    def ghost_placement(self, cursor: Point):
        """The angle the cursor is asking for, live."""
        if self._base is None or self._reference == -1.0:
            return None
        angle = math.degrees(math.atan2(cursor[1] - self._base[1],
                                        cursor[0] - self._base[0]))
        if self._reference is not None:
            angle -= self._reference
        return angle, 1.0


class ScaleTool(Tool):
    wants_selection = True

    def start(self) -> None:
        self.name = "SCALE"
        self._entities: list = []
        self._base: Point | None = None
        self._ref_length: float | None = None
        self._copy = False

    def on_selection(self, entities: list) -> None:
        if not entities:
            self.ctx.finish()
            return
        self._entities = entities
        self.prompt("Specify base point:")

    def on_option(self, text: str) -> bool:
        # The resolver first: it turns the localized keyword, or
        # AutoCAD's _global form, into the English key the
        # branches below have always compared against.
        t = self.option(text) or text.upper()
        if t == "C" and self._base is not None and self._ref_length is None:
            # Copy: the originals stay, a scaled copy is made (p.1652)
            self._copy = True
            self.ctx.echo(tr("Scaling a copy of the selected objects."))
            self.prompt("Specify scale factor or [Copy/Reference]:")
            return True
        if t in ("R", "REFERENCE") and self._base is not None:
            self._ref_length = -1.0
            self.prompt("Specify reference length:")
            return True
        if self._base is not None:
            try:
                value = float(text)
            except ValueError:
                return False
            if value <= 0:
                self.ctx.echo(tr("Value must be positive."))
                return True
            if self._ref_length == -1.0:
                self._ref_length = value
                self.prompt("Specify new length:")
            elif self._ref_length is not None:
                self.ctx.execute(actions.scale_entities(
                    self._entities, self._base, value / self._ref_length,
                    copy=self._copy))
                self.ctx.finish()
            else:
                self.ctx.execute(actions.scale_entities(
                    self._entities, self._base, value, copy=self._copy))
                self.ctx.finish()
            return True
        return False

    def on_point(self, point: Point) -> None:
        if self._base is None:
            self._base = point
            self.last_point = point
            self.ghost_entities = self._entities
            self.ghost_base = point
            self.prompt("Specify scale factor or [Copy/Reference]:")
            return
        # AutoCAD takes the factor from the distance to the base point, and
        # shows it growing as you go.
        factor = math.dist(self._base, point)
        if factor <= 0:
            self.ctx.echo(tr("Value must be positive."))
            return
        if self._ref_length == -1.0:
            self._ref_length = factor
            self.prompt("Specify new length:")
            return
        if self._ref_length is not None:
            factor = factor / self._ref_length
        self.ctx.execute(actions.scale_entities(
            self._entities, self._base, factor, copy=self._copy))
        self.ctx.finish()

    def preview_segments(self, cursor: Point):
        return [(self._base, cursor)] if self._base else []

    def ghost_placement(self, cursor: Point):
        if self._base is None or self._ref_length == -1.0:
            return None
        factor = math.dist(self._base, cursor)
        if self._ref_length is not None and self._ref_length > 0:
            factor /= self._ref_length
        return 0.0, max(factor, 1e-6)


class MirrorTool(Tool):
    wants_selection = True

    def start(self) -> None:
        self.name = "MIRROR"
        self._entities: list = []
        self._p1: Point | None = None
        self._p2: Point | None = None

    def on_selection(self, entities: list) -> None:
        if not entities:
            self.ctx.finish()
            return
        self._entities = entities
        self.prompt("Specify first point of mirror line:")

    def on_point(self, point: Point) -> None:
        if self._p1 is None:
            self._p1 = point
            self.last_point = point
            self.prompt("Specify second point of mirror line:")
        elif self._p2 is None:
            self._p2 = point
            self.prompt("Erase source objects? [Yes/No] <N>:")

    def on_option(self, text: str) -> bool:
        if self._p2 is None:
            return False
        # The resolver first: it turns the localized keyword, or
        # AutoCAD's _global form, into the English key the
        # branches below have always compared against.
        t = self.option(text) or text.upper()
        if t in ("Y", "YES", "S", "SI"):
            self.ctx.execute(actions.mirror_entities(
                self._entities, self._p1, self._p2, keep_source=False))
            self.ctx.finish()
            return True
        if t in ("N", "NO", ""):
            self.ctx.execute(actions.mirror_entities(
                self._entities, self._p1, self._p2, keep_source=True))
            self.ctx.finish()
            return True
        return False

    def on_enter(self) -> None:
        if self._p2 is not None:
            self.on_option("N")
        else:
            self.ctx.finish()

    def preview_segments(self, cursor: Point):
        return [(self._p1, cursor)] if self._p1 and self._p2 is None else []


class OffsetTool(Tool):
    """OFFSET, with the whole prompt tree (OFFSET, p.1286).

    The distance can be TYPED or picked as two points — AutoCAD accepts
    either at that prompt, and picking it off the drawing is how you offset
    a wall by the thickness of another one without doing arithmetic.
    """

    #: sticky through the session, like AutoCAD's OFFSETDIST; None is
    #: Through, the value it starts with (-1: "<Through>", OFFSET p.1286)
    distance: float | None = None
    erase_source = False
    layer_mode = "source"  # or "current"

    def start(self) -> None:
        self.name = "OFFSET"
        self._phase = "distance"
        self._first: Point | None = None
        self._entity = None
        self._through = False
        self._await = None
        self._done_any = False
        self.entity_picker = False      # a distance is points, not objects
        self._announce()

    # -- prompts ---------------------------------------------------------------
    def _announce(self) -> None:
        cls = type(self)
        self.ctx.echo(tr("Current settings: Erase source = {erase}  "
                         "Layer = {layer}",
                         erase=tr("Yes") if cls.erase_source else tr("No"),
                         layer=tr("Current") if cls.layer_mode == "current"
                         else tr("Source")))
        self.prompt("Specify offset distance or [Through/Erase/Layer] <{d}>:",
                    d=tr("Through") if cls.distance is None
                    else f"{cls.distance:g}")

    def _ask_object(self) -> None:
        self._phase = "object"
        self.entity_picker = True
        self.prompt("Select object to offset or [Exit/Undo] <Exit>:")

    def _ask_side(self) -> None:
        self._phase = "side"
        self.entity_picker = False
        if self._through:
            self.prompt("Specify through point or [Exit/Multiple/Undo] <Exit>:")
        else:
            self.prompt("Specify point on side to offset or "
                        "[Exit/Multiple/Undo] <Exit>:")

    # -- keywords --------------------------------------------------------------
    def on_option(self, text: str) -> bool:
        # The resolver first: it turns the localized keyword, or
        # AutoCAD's _global form, into the English key the
        # branches below have always compared against.
        token = self.option(text) or text.strip().upper()
        cls = type(self)
        if self._await == "erase":
            cls.erase_source = token.startswith("Y")
            self._await = None
            self._announce()
            return True
        if self._await == "layer":
            cls.layer_mode = "current" if token.startswith("C") else "source"
            self._await = None
            self._announce()
            return True

        if self._phase == "distance":
            if token in ("T", "THROUGH"):
                self._through = True
                cls.distance = None           # remembered, as OFFSETDIST -1
                self._ask_object()
                return True
            if token in ("E", "ERASE"):
                self._await = "erase"
                self.prompt("Erase source object after offsetting? "
                            "[Yes/No] <{cur}>:",
                            cur=tr("Yes") if cls.erase_source
                            else tr("No"))
                return True
            if token in ("L", "LAYER"):
                self._await = "layer"
                self.prompt("Enter layer option for offset objects "
                            "[Current/Source] <{cur}>:",
                            cur=tr("Current") if cls.layer_mode
                            == "current" else tr("Source"))
                return True
            value = _number(text)
            if value is None:
                return False
            if value <= 0:
                self.ctx.echo(tr("Value must be positive."))
                return True
            cls.distance = value
            self._ask_object()
            return True

        if self._phase in ("object", "side"):
            # The prompt reads [Exit/...], so E is the key AutoCAD documents;
            # X stayed accepted because it is what this tool took before.
            if token in ("E", "X", "EXIT", ""):
                self.ctx.finish()
                return True
            if token in ("U", "UNDO"):
                if self._done_any:
                    self.ctx.undo_last()
                self._ask_object()
                return True
            if token in ("M", "MULTIPLE") and self._phase == "side":
                return True     # already the behaviour: the side prompt loops
        return False

    def on_enter(self) -> None:
        if self._await:
            self.on_option("")
            return
        if self._phase == "distance":
            # Enter takes the <current> distance -- or Through
            self._through = type(self).distance is None
            self._ask_object()
            return
        self.ctx.finish()

    # -- points ----------------------------------------------------------------
    def on_point(self, point: Point) -> None:
        if self._phase == "distance":
            # Two clicks measure the distance off the drawing.
            if self._first is None:
                self._first = point
                self.last_point = point
                self.prompt("Specify second point:")
                return
            distance = math.dist(self._first, point)
            self._first = None
            if distance <= 0:
                self.ctx.echo(tr("Value must be positive."))
                return
            type(self).distance = distance
            self.ctx.echo(tr("Offset distance = {d}", d=f"{distance:g}"))
            self._ask_object()
            return

        if self._phase == "object":
            entity = self.ctx.services.pick_entity(point)
            if entity is None:
                self.ctx.echo(tr("Nothing there."))
                return
            if entity.dxftype() not in _OFFSETTABLE:
                self.ctx.echo(tr("{kind} cannot be offset.",
                                 kind=entity.dxftype()))
                return
            self._entity = entity
            self._ask_side()
            return

        if self._phase == "side" and self._entity is not None:
            self._emit(self._entity, point)
            self._entity = None
            self._ask_object()

    # -- the offset itself -----------------------------------------------------
    def _distance_for(self, entity, side: Point) -> float | None:
        """Through mode measures the distance to the picked point."""
        if not self._through:
            return type(self).distance
        if entity.dxftype() in ("LWPOLYLINE", "POLYLINE"):
            return _distance_to_polyline(entity, side) or None
        if entity.dxftype() == "LINE":
            seg = (entity.dxf.start.x, entity.dxf.start.y,
                   entity.dxf.end.x, entity.dxf.end.y)
            closest = editmath._dist_point_segment(seg, side) \
                if hasattr(editmath, "_dist_point_segment") else None
            if closest is None:
                dx, dy = seg[2] - seg[0], seg[3] - seg[1]
                length = math.hypot(dx, dy)
                if length == 0:
                    return None
                closest = abs((side[0] - seg[0]) * dy
                              - (side[1] - seg[1]) * dx) / length
            return closest or None
        cx, cy, r = ocs.circle_wcs(entity)
        return abs(math.dist((cx, cy), side) - r) or None

    def _emit(self, entity, side: Point) -> None:
        from core.modify import carry_body

        distance = self._distance_for(entity, side)
        if not distance:
            self.ctx.echo(tr("Value must be positive."))
            return
        attribs = self._attribs(entity)
        layer = attribs.pop("layer", None)
        kind = entity.dxftype()
        if kind in ("LWPOLYLINE", "POLYLINE"):
            pieces = polyoffset.offset_polylines(
                _polyline_rows(entity), _polyline_closed(entity),
                distance, side)
            if not pieces:
                self.ctx.echo(tr("The offset does not fit that polyline."))
                return
            # a shape the offset splits into islands gives one polyline per
            # island, as AutoCAD's OFFSET does (#58)
            adds = [actions.AddEntityCommand(
                "OFFSET",
                lambda msp, r=rows, c=closed, a=attribs: carry_body(
                    _add_polyline(msp, r, c, a), entity),
                layer=layer) for rows, closed in pieces]
            if len(adds) == 1:
                self.ctx.execute(adds[0])
            else:
                from core.commands import CompositeCommand

                self.ctx.execute(CompositeCommand("OFFSET", adds))
            self._done_any = True
            if type(self).erase_source:
                self.ctx.execute(actions.EraseCommand([entity]))
            return
        if kind == "LINE":
            seg = (entity.dxf.start.x, entity.dxf.start.y,
                   entity.dxf.end.x, entity.dxf.end.y)
            n = editmath.offset_line(seg, distance, side)
            command = actions.AddEntityCommand(
                "OFFSET",
                lambda msp, p=n, a=attribs: carry_body(msp.add_line(
                    (p[0], p[1]), (p[2], p[3]), dxfattribs=dict(a)), entity),
                layer=layer)
        else:
            cx, cy, radius = ocs.circle_wcs(entity)
            center = (cx, cy)
            new_r = editmath.offset_circle_radius(
                radius, distance, center, side)
            if new_r is None:
                self.ctx.echo(tr("Radius would vanish."))
                return
            if kind == "CIRCLE":
                command = actions.AddEntityCommand(
                    "OFFSET",
                    lambda msp, c=center, r=new_r, a=attribs: carry_body(
                        msp.add_circle(c, r, dxfattribs=dict(a)), entity),
                    layer=layer)
            else:
                a0, a1 = ocs.arc_wcs(entity)[3:]
                command = actions.AddEntityCommand(
                    "OFFSET",
                    lambda msp, c=center, r=new_r, s=a0, en=a1, a=attribs:
                        carry_body(msp.add_arc(c, r, s, en, dxfattribs=dict(a)),
                                   entity),
                    layer=layer)
        self.ctx.execute(command)
        self._done_any = True
        if type(self).erase_source:
            self.ctx.execute(actions.EraseCommand([entity]))

    def _attribs(self, entity) -> dict:
        """Source layer, or the current one — the Layer option."""
        if type(self).layer_mode == "current":
            return {}
        keep = {}
        for name in ("layer", "color", "linetype", "lineweight", "ltscale"):
            try:
                value = entity.dxf.get(name)
            except Exception:
                continue
            if value is not None:
                keep[name] = value
        return keep


_OFFSETTABLE = ("LINE", "CIRCLE", "ARC", "LWPOLYLINE", "POLYLINE")


def _polyline_rows(entity):
    """(x, y, start_width, end_width, bulge) rows, for either polyline type."""
    if entity.dxftype() == "LWPOLYLINE":
        return ocs.rows_wcs(entity, entity.get_points("xyseb"))
    rows = [(v.dxf.location.x, v.dxf.location.y, 0.0, 0.0,
             getattr(v.dxf, "bulge", 0.0) or 0.0) for v in entity.vertices]
    return ocs.rows_wcs(entity, rows) if entity.get_mode() == "AcDb2dPolyline" \
        else rows


def _polyline_closed(entity) -> bool:
    if entity.dxftype() == "LWPOLYLINE":
        return bool(entity.closed)
    return bool(entity.is_closed)


def _distance_to_polyline(entity, point) -> float:
    """Shortest distance from a point to the polyline's own geometry."""
    elements = polyoffset.elements_of(
        _polyline_rows(entity), _polyline_closed(entity))
    if not elements:
        return 0.0
    return min(polyoffset.distance_to(point, e) for e in elements)


def _add_polyline(msp, rows, closed: bool, attribs: dict):
    poly = msp.add_lwpolyline(rows, format="xyseb", dxfattribs=dict(attribs))
    poly.closed = closed
    return poly


def _number(text: str):
    try:
        return float(text.strip())
    except (TypeError, ValueError):
        return None


def _mode_word(quick: bool) -> str:
    """TRIMEXTENDMODE's two words, in their own context: "Standard" alone
    is also the name of a style, which is never translated."""
    from core.i18n import tr_context

    return tr_context("Trim mode|Quick") if quick \
        else tr_context("Trim mode|Standard")


class _TrimExtendBase(Tool):
    wants_selection = True   # the cutting/boundary edges
    modifies_selection = False   # reads the set; locked layers count
    entity_picker = True
    accepts_target_windows = True
    trim_mode = True

    def start(self) -> None:
        from core import trimmode

        self._edges_handles: list[str] | None = None
        self._asking_mode = False
        #: Fence points while one is drawn, the first Crossing corner, and
        #: the edge list before each change, for Undo
        self._fence: list | None = None
        self._cross_anchor: Point | None = None
        self._crossing = False
        self._history: list = []
        self.quick = trimmode.trimextendmode() == 1
        self.ctx.echo(tr("Current settings: Projection=UCS, Edge=None, "
                         "Mode={mode}", mode=_mode_word(self.quick)))
        # Quick: every object is an edge, nothing to pick first
        self.wants_selection = not self.quick
        if self.quick:
            self._object_prompt()

    def selection_prompt(self) -> str:
        return (tr("Select cutting edges <Enter selects all>:") if self.trim_mode
                else tr("Select boundary edges <Enter selects all>:"))

    def on_selection(self, entities: list) -> None:
        # Enter with empty selection = all entities are edges (modern AutoCAD)
        self._edges_handles = [e.dxf.handle for e in entities] or None
        self._object_prompt()

    def _object_prompt(self) -> None:
        """AutoCAD 2021's object prompt, per command and mode."""
        self._fence = None
        self._crossing = False
        self._picking_points(False)
        if self.trim_mode:
            self.prompt(
                "Select object to trim or shift-select to extend or "
                "[cuTting edges/Fence/Crossing/mOde/Undo]:" if self.quick else
                "Select object to trim or shift-select to extend or "
                "[Fence/Crossing/mOde/Undo]:")
        else:
            self.prompt(
                "Select object to extend or shift-select to trim or "
                "[Boundary edges/Fence/Crossing/mOde/Undo]:" if self.quick else
                "Select object to extend or shift-select to trim or "
                "[Fence/Crossing/mOde/Undo]:")

    def _picking_points(self, on: bool) -> None:
        """Fence and Crossing take plain points: no object pick, no target
        window, osnap on."""
        self.entity_picker = not on
        self.accepts_target_windows = not on

    def on_option(self, text: str) -> bool:
        from core import trimmode

        if self._asking_mode:
            key = self.option(text) if text.strip() else \
                ("Q" if self.quick else "S")
            if key not in ("Q", "S"):
                return False
            self._asking_mode = False
            trimmode.set_trimextendmode(1 if key == "Q" else 0)
            self.quick = key == "Q"
            if self.quick:
                self._edges_handles = None        # every object, as Quick is
                self._object_prompt()
            else:
                self.ctx.services.request_selection()
            return True
        key = self.option(text)
        if self._fence is not None and key == "U":
            if self._fence:
                self._fence.pop()
            self._fence_prompt()
            return True
        if self._fence is None and not self._crossing:
            if key == "F":
                # Fence: every object the line crosses (TRIM, p.1951)
                self._fence = []
                self._picking_points(True)
                self.prompt("Specify first fence point:")
                return True
            if key == "C":
                self._crossing = True
                self._cross_anchor = None
                self._picking_points(True)
                self.prompt("Specify first corner:")
                return True
            if key == "U":
                self._undo_one()
                return True
        if key == "O":
            self._asking_mode = True
            source = ("Enter a trim mode option [Quick/Standard] <{mode}>:"
                      if self.trim_mode else
                      "Enter an extend mode option [Quick/Standard] <{mode}>:")
            self.prompt(source, mode=_mode_word(self.quick))
            return True
        if self.quick and key in ("T", "B"):
            # cuTting edges / Boundary edges: pick them, then trim as Standard
            self.ctx.services.request_selection()
            return True
        return False

    def on_point(self, point: Point) -> None:
        if self._fence is not None:
            self._fence.append(point)
            self.last_point = point
            self._fence_prompt()
            return
        if self._crossing:
            if self._cross_anchor is None:
                self._cross_anchor = point
                self.prompt("Specify opposite corner:")
                return
            ax, ay = self._cross_anchor
            rect = (min(ax, point[0]), min(ay, point[1]),
                    max(ax, point[0]), max(ay, point[1]))
            index = getattr(self.ctx.services, "index", None)
            entities = []
            if index is not None:
                entities = [e for h in index.crossing(rect)
                            if (e := index.entity(h)) is not None and e.is_alive]
            self.on_target_entities(entities, rect)
            self._object_prompt()
            return
        entity = self.ctx.services.pick_entity(point)
        if entity is None:
            self.ctx.echo(tr("Nothing there."))
            return
        self.apply_to_entity(entity, point)

    def _fence_prompt(self) -> None:
        if not self._fence:
            self.prompt("Specify first fence point:")
        else:
            self.prompt("Specify next fence point or [Undo]:")

    def on_enter(self) -> None:
        if self._fence is not None:
            fence, self._fence = self._fence, None
            if len(fence) >= 2:
                self._apply_fence(fence)
            self._object_prompt()
            return
        if self._crossing:
            self._object_prompt()
            return
        self.ctx.finish()

    def _apply_fence(self, fence: list) -> None:
        """Trim (or extend) every object the fence crosses, at the first
        point where it crosses it."""
        index = getattr(self.ctx.services, "index", None)
        if index is None:
            return
        done = set()
        self._grouping = [None if self._edges_handles is None
                          else list(self._edges_handles), 0]
        try:
            self._fence_pass(index, fence, done)
        finally:
            group, self._grouping = self._grouping, None
            if group[1]:
                self._history.append(group)

    def _fence_pass(self, index, fence, done) -> None:
        for a, b in zip(fence, fence[1:]):
            rect = (min(a[0], b[0]), min(a[1], b[1]),
                    max(a[0], b[0]), max(a[1], b[1]))
            for handle in index.crossing(rect):
                entity = index.entity(handle)
                if entity is None or not entity.is_alive or handle in done:
                    continue
                point = _fence_crossing(entity, a, b)
                if point is not None:
                    done.add(handle)
                    self.apply_to_entity(entity, point)

    def _undo_one(self) -> None:
        """Undo inside the command: the last change, and the edge list as it
        was before it (a trimmed edge keeps cutting through its pieces)."""
        if not self._history:
            self.ctx.echo(tr("Command has been completely undone."))
            self._object_prompt()
            return
        edges, count = self._history.pop()
        for _ in range(count):
            self.ctx.undo_last()
        self._edges_handles = edges
        self._object_prompt()

    def preview_segments(self, cursor: Point):
        if self._fence:
            points = list(self._fence) + [cursor]
            return list(zip(points, points[1:]))
        return []

    def on_target_entities(self, entities: list, rect) -> None:
        """Window/crossing over targets: trim each near the rect center."""
        cx = (rect[0] + rect[2]) / 2.0
        cy = (rect[1] + rect[3]) / 2.0
        for entity in entities:
            point = _point_on_entity_near(entity, (cx, cy))
            if point is not None:
                self.apply_to_entity(entity, point)

    def apply_to_entity(self, entity, point: Point) -> None:
        if not entity.is_alive:
            return
        trim = self.trim_mode != self.shift  # Shift flips the mode
        # TRIM cutters must intersect the target: filtering edges to the
        # target's bbox keeps big drawings interactive. EXTEND boundaries
        # can be arbitrarily far — no filter there.
        near = _entity_bbox(entity) if trim else None
        segs, circles = self.ctx.services.edges_geometry(
            self._edges_handles, exclude=entity.dxf.handle, near=near)
        if trim:
            self._trim(entity, point, segs, circles)
        else:
            self._extend(entity, point, segs, circles)

    def _replace(self, name: str, entity, factories) -> None:
        """Execute the swap and keep the edge list alive across it.

        A trimmed cutting edge keeps cutting in AutoCAD: when the replaced
        entity was one of our edges, its surviving pieces take its place.

        Every piece inherits the properties of what it came from — a trimmed
        line is that line, shortened. Wrapping the factories here rather than
        at each of them means no future one can forget.
        """
        from core.modify import inherit_style

        cmd = actions.ReplaceEntitiesCommand(
            name, [entity],
            [(lambda msp, f=f: inherit_style(f(msp), entity))
             for f in factories])
        edges = None if self._edges_handles is None else list(self._edges_handles)
        if getattr(self, "_grouping", None) is not None:
            self._grouping[1] += 1           # one fence, one Undo
        else:
            self._history.append([edges, 1])
        self.ctx.execute(cmd)
        if self._edges_handles is not None:
            handle = None
            for e in cmd.old_entities:
                handle = e.dxf.handle
                if handle in self._edges_handles:
                    self._edges_handles.remove(handle)
                    self._edges_handles.extend(
                        n.dxf.handle for n in cmd.new_entities)

    def _trim(self, entity, point, segs, circles) -> None:
        t = entity.dxftype()
        if t == "LINE":
            seg = (entity.dxf.start.x, entity.dxf.start.y,
                   entity.dxf.end.x, entity.dxf.end.y)
            pick_t = _param_on_segment(seg, point)
            pieces = editmath.trim_segment(seg, segs, circles, pick_t)
            if pieces is None:
                self._nothing_crosses(entity)
                return
            factories = [
                (lambda msp, p=p: msp.add_line((p[0], p[1]), (p[2], p[3])))
                for p in pieces
            ]
            self._replace("TRIM", entity, factories)
        elif t == "CIRCLE":
            cx, cy, radius = ocs.circle_wcs(entity)
            center = (cx, cy)
            pick_ang = math.atan2(point[1] - center[1], point[0] - center[0])
            arc = editmath.trim_circle(center, radius, segs, pick_ang,
                                       cutter_circles=circles)
            if arc is None:
                if self.quick and not editmath.circle_crossings(
                        center, radius, segs, circles):
                    self._nothing_crosses(entity)
                else:
                    self.ctx.echo(tr("A circle needs two crossings to trim."))
                return
            a0, a1 = arc
            self._replace("TRIM", entity,
                          [lambda msp, c=center, r=radius,
                                  s=a0, e=a1: msp.add_arc(c, r, s, e)])
        elif t == "ARC":
            cx, cy, radius, start, end = ocs.arc_wcs(entity)
            center = (cx, cy)
            pick_ang = math.atan2(point[1] - center[1], point[0] - center[0])
            spans = editmath.trim_arc(
                center, radius, start, end, segs, pick_ang,
                cutter_circles=circles)
            if spans is None:
                self._nothing_crosses(entity)
                return
            factories = [
                (lambda msp, c=center, r=radius, s=s0, e=e0:
                     msp.add_arc(c, r, s, e))
                for s0, e0 in spans
            ]
            self._replace("TRIM", entity, factories)
        elif t == "LWPOLYLINE":
            pts = ocs.bulge_vertices_wcs(entity, entity.get_points("xyb"))
            if any(abs(p[2]) > 1e-12 for p in pts):
                self.ctx.echo(tr("Curved polyline segments not supported yet."))
                return
            chains = editmath.trim_polyline(
                [(p[0], p[1]) for p in pts], entity.closed, point,
                segs, circles)
            if chains is None:
                self._nothing_crosses(entity)
                return
            factories = [
                (lambda msp, c=chain: msp.add_lwpolyline(c))
                for chain in chains
            ]
            self._replace("TRIM", entity, factories)
        else:
            self.ctx.echo(tr("TRIM supports LINE, PLINE, CIRCLE and ARC for now."))

    def _nothing_crosses(self, entity) -> None:
        """No cutting edge crosses the picked object. Standard says so;
        Quick erases it, as AutoCAD 2021's Quick TRIM does with an object
        that has no intersections (Rafael erased such stubs by hand)."""
        if getattr(self, "quick", False):
            self.ctx.execute(actions.EraseCommand([entity]))
            return
        self.ctx.echo(tr("No cutting edge crosses it."))

    def _extend(self, entity, point, segs, circles) -> None:
        t = entity.dxftype()
        if t == "LINE":
            seg = (entity.dxf.start.x, entity.dxf.start.y,
                   entity.dxf.end.x, entity.dxf.end.y)
            pick_t = _param_on_segment(seg, point)
            new_seg = editmath.extend_segment(seg, segs, circles, pick_t)
            if new_seg is None:
                self.ctx.echo(tr("No boundary edge to extend to."))
                return
            self._replace("EXTEND", entity,
                          [lambda msp, p=new_seg:
                               msp.add_line((p[0], p[1]), (p[2], p[3]))])
        elif t == "LWPOLYLINE":
            pts = ocs.bulge_vertices_wcs(entity, entity.get_points("xyb"))
            if any(abs(p[2]) > 1e-12 for p in pts):
                self.ctx.echo(tr("Curved polyline segments not supported yet."))
                return
            if entity.closed:
                self.ctx.echo(tr("A closed polyline cannot be extended."))
                return
            new_pts = editmath.extend_polyline(
                [(p[0], p[1]) for p in pts], False, point, segs, circles)
            if new_pts is None:
                self.ctx.echo(tr("No boundary edge to extend to."))
                return
            self._replace("EXTEND", entity,
                          [lambda msp, c=new_pts: msp.add_lwpolyline(c)])
        elif t == "ARC":
            cx, cy, radius, start, end = ocs.arc_wcs(entity)
            center = (cx, cy)
            pick_ang = math.atan2(point[1] - cy, point[0] - cx)
            arc = editmath.extend_arc(center, radius, start, end, pick_ang,
                                      segs, circles)
            if arc is None:
                self.ctx.echo(tr("No boundary edge to extend to."))
                return
            self._replace("EXTEND", entity,
                          [lambda msp, c=center, r=radius, a=arc:
                               msp.add_arc(c, r, a[0], a[1])])
        else:
            self.ctx.echo(tr("EXTEND supports LINE, ARC and PLINE for now."))


class TrimTool(_TrimExtendBase):
    trim_mode = True

    def start(self) -> None:
        super().start()
        self.name = "TRIM"


class ExtendTool(_TrimExtendBase):
    trim_mode = False

    def start(self) -> None:
        super().start()
        self.name = "EXTEND"


class FilletTool(Tool):
    """FILLET, with AutoCAD's prompts and options (Command Reference,
    FILLET): Undo, Polyline, Radius, Trim, Multiple, and Shift on the
    second pick for a sharp corner."""

    entity_picker = True
    radius = 0.0  # session-sticky, AutoCAD-style

    OPTIONS = "Select first object or [Undo/Polyline/Radius/Trim/Multiple]:"

    def start(self) -> None:
        self.name = "FILLET"
        self._first = None
        self._first_pick = None
        self._await = None             # "radius", "trim", "polyline"
        self._multiple = False
        self._done = 0                 # fillets made by this command (Undo)
        self._announce()

    def _fmt(self, value: float) -> str:
        from core import units as units_mod

        services = self.ctx.services
        try:
            u = services.units()
            return units_mod.format_length(value, u.lunits, u.luprec)
        except Exception:  # noqa: BLE001 -- no drawing units: AutoCAD's default
            return f"{value:.4f}"

    def _announce(self) -> None:
        from core import trimmode

        self.ctx.echo(tr("Current settings: Mode = {mode}, Radius = {radius}",
                         mode=tr("TRIM") if trimmode.trimmode() else tr("NOTRIM"),
                         radius=self._fmt(type(self).radius)))
        self.prompt(self.OPTIONS)

    def _first_prompt(self) -> None:
        self._first = None
        self._first_pick = None
        self.prompt(self.OPTIONS)

    def _after_fillet(self) -> None:
        """One pair done: Multiple asks again, otherwise the command ends."""
        self._done += 1
        if self._multiple:
            self._first_prompt()
        else:
            self.ctx.finish()

    def on_option(self, text: str) -> bool:
        from core import trimmode

        t = self.option(text) or text.strip().upper()
        if self._await == "radius":
            if not text.strip():
                self._await = None
                self._first_prompt()
                return True
            try:
                r = float(text)
            except ValueError:
                self.ctx.echo(tr("Requires a positive number."))
                return True
            if r < 0:
                self.ctx.echo(tr("Value must be positive."))
                return True
            type(self).radius = r
            self._await = None
            self._first_prompt()
            return True
        if self._await == "trim":
            if t.startswith("T"):
                trimmode.set_trimmode(True)
            elif t.startswith("N"):
                trimmode.set_trimmode(False)
            elif text.strip():
                self.ctx.echo(tr("Requires Trim or No trim."))
                return True
            self._await = None
            self._first_prompt()
            return True
        if self._first is not None:
            return False
        if t in ("R", "RADIUS"):
            self._await = "radius"
            self.prompt("Specify fillet radius <{r}>:",
                        r=self._fmt(type(self).radius))
            return True
        if t in ("T", "TRIM"):
            self._await = "trim"
            self.prompt("Enter Trim mode option [Trim/No trim] <{mode}>:",
                        mode=tr("Trim") if trimmode.trimmode() else tr("No trim"))
            return True
        if t in ("M", "MULTIPLE"):
            self._multiple = True
            self._first_prompt()
            return True
        if t in ("P", "POLYLINE"):
            self._await = "polyline"
            self.prompt("Select 2D polyline:")
            return True
        if t in ("U", "UNDO"):
            if self._done:
                self.ctx.undo_last()
                self._done -= 1
            else:
                self.ctx.echo(tr("Command has been completely undone."))
            self._first_prompt()
            return True
        return False

    def on_enter(self) -> None:
        if self._await == "radius":
            self.on_option("")
            return
        self.ctx.finish()

    def on_point(self, point: Point) -> None:
        entity = self.ctx.services.pick_entity(point)
        if self._await == "polyline":
            self._fillet_polyline(entity)
            return
        if entity is None or entity.dxftype() not in (
                "LINE", "ARC", "CIRCLE", "LWPOLYLINE"):
            self.ctx.echo(tr("FILLET joins lines, arcs, circles and "
                             "polyline segments."))
            return
        if self._first is None:
            self._first = entity
            self._first_pick = point
            self.prompt("Select second object or shift-select to apply corner:")
            return
        if entity is self._first and entity.dxftype() != "LWPOLYLINE":
            self.ctx.echo(tr("Pick a different object."))
            return
        # Shift on the second pick: a sharp corner, radius 0 this once
        radius = 0.0 if getattr(self, "shift", False) else type(self).radius
        kinds = {entity.dxftype(), self._first.dxftype()}
        if "LWPOLYLINE" in kinds:
            done = self._fillet_segments(entity, point, radius)
        elif "LINE" == entity.dxftype() == self._first.dxftype():
            done = self._fillet_lines(entity, point, radius)
        else:
            done = self._fillet_curves(entity, point, radius)
        if done:
            self._after_fillet()
        else:
            self._first_prompt() if self._multiple else self.ctx.finish()

    # -- the pieces -------------------------------------------------------
    def _run(self, olds, pieces, arc) -> None:
        """Replace ``olds`` by the trimmed ``pieces`` plus the fillet ``arc``
        (a factory or None). With TRIMMODE off the originals stay and only
        the arc is added."""
        from core import trimmode

        if trimmode.trimmode():
            factories = pieces + ([arc] if arc else [])
        else:
            olds, factories = [], ([arc] if arc else [])
        if factories:
            self.ctx.execute(actions.ReplaceEntitiesCommand(
                "FILLET", olds, factories))

    def _fillet_lines(self, entity, point, radius) -> bool:
        from core.modify import common_style_source, inherit_style

        first = self._first
        s1 = (first.dxf.start.x, first.dxf.start.y,
              first.dxf.end.x, first.dxf.end.y)
        s2 = (entity.dxf.start.x, entity.dxf.start.y,
              entity.dxf.end.x, entity.dxf.end.y)
        source = common_style_source([first, entity])
        parallel = editmath.fillet_parallel(s1, self._first_pick, s2)
        if parallel is not None:
            # The first line stays; the second is trimmed to the semicircle
            # (the radius is half the distance, whatever it is set to).
            new_s2, (center, r, a0, a1) = parallel
            self._run([entity],
                      [lambda msp, p=new_s2: inherit_style(
                          msp.add_line((p[0], p[1]), (p[2], p[3])), entity)],
                      lambda msp: inherit_style(
                          msp.add_arc(center, r, a0, a1), source))
            return True
        # Each line keeps the side it was picked on, measured from where
        # they cross -- on crossing lines the end farther from the corner
        # is often the other side (GeoCad Yaguarete had to patch it).
        result = editmath.sided_fillet(s1, self._first_pick, s2, point, radius)
        if result == "parallel":
            self.ctx.echo(tr("Lines are parallel."))
            return False
        if result == "too large":
            self.ctx.echo(tr("Radius does not fit."))
            return False
        _corner, t1, t2, center, far1, far2, _sweep = result
        def kept(seg, far, tangent):
            # the line keeps its own direction: start stays the start
            if math.dist((seg[0], seg[1]), far) < 1e-12:
                return (far[0], far[1], tangent[0], tangent[1])
            return (tangent[0], tangent[1], far[0], far[1])

        n1, n2 = kept(s1, far1, t1), kept(s2, far2, t2)
        if center is None:
            arc = None
        else:
            r = math.dist(center, t1)
            a0 = math.degrees(math.atan2(t1[1] - center[1], t1[0] - center[0]))
            a1 = math.degrees(math.atan2(t2[1] - center[1], t2[0] - center[0]))
            if (a1 - a0) % 360.0 > 180.0:       # the short way round
                a0, a1 = a1, a0
            arc = (lambda msp, c=center, rr=r, s=a0, e=a1:
                   inherit_style(msp.add_arc(c, rr, s, e), source))
        # The two trimmed pieces keep their own object's properties; the
        # new arc has no object of its own, so it takes them only when both
        # edges agree — otherwise the current settings decide.
        self._run([first, entity],
                  [lambda msp, p=n1: inherit_style(
                      msp.add_line((p[0], p[1]), (p[2], p[3])), first),
                   lambda msp, p=n2: inherit_style(
                      msp.add_line((p[0], p[1]), (p[2], p[3])), entity)],
                  arc)
        return True

    _SEGMENT_REASONS = {
        "arc": "FILLET takes the straight segments of a polyline.",
        "tilted": "The polyline is not in the drawing's plane.",
        "not adjacent": "The segments must be adjacent or separated by "
                        "one segment.",
        "not an end": "A line joins a polyline at one of its end segments.",
        "closed": "A line cannot join a closed polyline.",
        "parallel": "Lines are parallel.",
        "too large": "Radius is too large.",
        "short": "The polyline has no segment there.",
        "nothing": "Radius is too large.",
    }

    def _fillet_segments(self, entity, point, radius) -> bool:
        """A polyline segment in the pair (FILLET, p. 801)."""
        from core import trimmode

        if entity.dxftype() == self._first.dxftype() == "LWPOLYLINE" \
                and entity is not self._first and (
                    entity.closed or self._first.closed):
            self.ctx.echo(tr(self._SEGMENT_REASONS["closed"]))
            return False
        if not {entity.dxftype(), self._first.dxftype()} <= {
                "LINE", "LWPOLYLINE"}:
            self.ctx.echo(tr("FILLET joins a polyline segment with a line "
                             "or another polyline segment."))
            return False
        command, reason = modify.fillet_with_polylines(
            self._first, self._first_pick, entity, point, radius,
            trim=trimmode.trimmode())
        if command is None:
            self.ctx.echo(tr(self._SEGMENT_REASONS.get(
                reason, "Radius is too large.")))
            return False
        self.ctx.execute(command)
        return True

    def _fillet_curves(self, entity, pick, radius) -> bool:
        """An arc or a circle in the pair: the fillet arc is tangent to both,
        the one whose ends are nearest the picks ("select the objects close
        to where you want the endpoints of the fillet"); lines and arcs are
        trimmed or extended to it, circles are left whole ("FILLET does not
        trim circles")."""
        from core.modify import common_style_source, inherit_style

        pairs = [(self._first, self._first_pick), (entity, pick)]
        objs = [_tangent_obj(e) for e, _p in pairs]
        try:
            center, t1, t2 = actions.tangent_circle(
                objs[0], pairs[0][1], objs[1], pairs[1][1], radius)
        except ValueError:
            self.ctx.echo(tr("Radius does not fit.") if radius > 0
                          else tr("The objects do not meet."))
            return False
        olds, pieces = [], []
        for (e, p), t in zip(pairs, (t1, t2)):
            kind = e.dxftype()
            if kind == "LINE":
                seg = (e.dxf.start.x, e.dxf.start.y, e.dxf.end.x, e.dxf.end.y)
                n = editmath.trim_line_to(seg, t, p)
                pieces.append(lambda msp, n=n, e=e: inherit_style(
                    msp.add_line((n[0], n[1]), (n[2], n[3])), e))
            elif kind == "ARC":
                cx, cy, r, a0, a1 = ocs.arc_wcs(e)
                b0, b1 = editmath.trim_arc_to((cx, cy), a0, a1, t, p)
                pieces.append(lambda msp, c=(cx, cy), r=r, b0=b0, b1=b1,
                              e=e: inherit_style(msp.add_arc(c, r, b0, b1), e))
            else:
                continue                      # a circle stays whole
            olds.append(e)
        arc = None
        if radius > 0:
            a0, a1 = editmath.arc_between(center, t1, t2)
            source = common_style_source([self._first, entity])
            arc = (lambda msp: inherit_style(
                msp.add_arc(center, radius, a0, a1), source))
        self._run(olds, pieces, arc)
        return True

    def _fillet_polyline(self, entity) -> None:
        """Polyline option: round every corner where two lines meet."""
        self._await = None
        if entity is None or entity.dxftype() != "LWPOLYLINE":
            self.ctx.echo(tr("Object selected is not a 2D polyline."))
            self._first_prompt()
            return
        rows, done, short = editmath.fillet_polyline(
            entity.get_points("xyseb"), entity.closed, type(self).radius)
        if done:
            def factory(msp, e=entity, rows=rows):
                clone = e.copy()
                clone.set_points(rows, format="xyseb")
                msp.add_entity(clone)
                return clone

            self.ctx.execute(actions.ReplaceEntitiesCommand(
                "FILLET", [entity], [factory]))
        message = tr("{n} lines were filleted", n=done)
        if short:
            message += ", " + tr("{n} were too short", n=short)
        self.ctx.echo(message)
        if done:
            self._after_fillet()
        else:
            self._first_prompt() if self._multiple else self.ctx.finish()


def _tangent_obj(entity):
    """A LINE, ARC or CIRCLE as the tangent solver's object (WCS)."""
    if entity.dxftype() == "LINE":
        s, e = entity.dxf.start, entity.dxf.end
        return ("line", (s.x, s.y), (e.x, e.y))
    cx, cy, r = ocs.circle_wcs(entity)
    return ("circle", (cx, cy), r)


def _entity_bbox(entity):
    """World bbox of a trim target, or None for unsupported types."""
    t = entity.dxftype()
    if t == "LINE":
        s, e = entity.dxf.start, entity.dxf.end
        return (min(s.x, e.x), min(s.y, e.y), max(s.x, e.x), max(s.y, e.y))
    if t in ("CIRCLE", "ARC"):
        cx, cy, r = ocs.circle_wcs(entity)
        return (cx - r, cy - r, cx + r, cy + r)
    if t == "LWPOLYLINE":
        pts = ocs.points_wcs(entity, entity.get_points("xy"))
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))
    return None


def _fence_crossing(entity, a: Point, b: Point):
    """Where the fence segment a-b first crosses ``entity``, or None."""
    from ezdxf import path as ezpath
    from ezdxf.math import Vec2, intersection_line_line_2d

    try:
        vertices = [Vec2(v) for v in ezpath.make_path(entity).flattening(
            max(math.dist(a, b) * 1e-4, 1e-9))]
    except Exception:  # noqa: BLE001 -- an object the fence cannot read
        return None
    start, end = Vec2(a), Vec2(b)
    best = None
    for p, q in zip(vertices, vertices[1:]):
        hit = intersection_line_line_2d((start, end), (p, q), virtual=False)
        if hit is not None:
            d = start.distance(hit)
            if best is None or d < best[0]:
                best = (d, (hit.x, hit.y))
    return best[1] if best else None


def _point_on_entity_near(entity, target: Point):
    """Closest point ON the entity to a target point (window-trim picks)."""
    t = entity.dxftype()
    if t == "LINE":
        seg = (entity.dxf.start.x, entity.dxf.start.y,
               entity.dxf.end.x, entity.dxf.end.y)
        u = _param_on_segment(seg, target)
        return (seg[0] + u * (seg[2] - seg[0]), seg[1] + u * (seg[3] - seg[1]))
    if t in ("CIRCLE", "ARC"):
        cx, cy, r = ocs.circle_wcs(entity)
        ang = math.atan2(target[1] - cy, target[0] - cx)
        if t == "ARC":
            _cx, _cy, _r, d0, d1 = ocs.arc_wcs(entity)
            a0 = math.radians(d0) % math.tau
            a1 = math.radians(d1) % math.tau
            if a1 <= a0:
                a1 += math.tau
            rel = (ang - a0) % math.tau
            if rel > (a1 - a0):
                # clamp to the nearest arc end
                ang = a0 if rel - (a1 - a0) > (math.tau - rel) else a1
        return (cx + r * math.cos(ang), cy + r * math.sin(ang))
    if t == "LWPOLYLINE":
        pts = ocs.points_wcs(entity, entity.get_points("xy"))
        pairs = list(zip(pts, pts[1:]))
        if entity.closed and len(pts) > 2:
            pairs.append((pts[-1], pts[0]))
        best = None
        for a, b in pairs:
            seg = (a[0], a[1], b[0], b[1])
            u = _param_on_segment(seg, target)
            q = (seg[0] + u * (seg[2] - seg[0]), seg[1] + u * (seg[3] - seg[1]))
            d = math.hypot(q[0] - target[0], q[1] - target[1])
            if best is None or d < best[0]:
                best = (d, q)
        return best[1] if best else None
    return None


def _param_on_segment(seg, point) -> float:
    x1, y1, x2, y2 = seg
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return 0.0
    return max(0.0, min(1.0, ((point[0] - x1) * dx + (point[1] - y1) * dy) / L2))


class PasteTool(Tool):
    """PASTECLIP (Ctrl+V): place the clipboard entities from a picked point."""

    def start(self) -> None:
        self.name = "PASTECLIP"
        self._sources, self._base = (
            self.ctx.services.clipboard_data() if self.ctx.services
            else (None, None))
        if not self._sources:
            self.ctx.echo(tr("Clipboard is empty."))
            self.ctx.finish()
            return
        originals = getattr(self.ctx.services, "clipboard_originals", None)
        self._originals = originals() if callable(originals) else None
        # ghost: the actual clipboard geometry follows the cursor
        self.ghost_entities = self._sources
        self.ghost_base = self._base
        self.prompt("Specify insertion point:")

    def on_point(self, point: Point) -> None:
        dx, dy = point[0] - self._base[0], point[1] - self._base[1]
        self.ctx.execute(actions.PasteCommand(self._sources, dx, dy,
                                              originals=self._originals))
        self.ctx.finish()


class CopyBaseTool(Tool):
    """COPYBASE (Ctrl+Shift+C): copy the selection to the clipboard with a
    base point of your choosing -- Ctrl+C takes the lower-left corner."""

    wants_selection = True

    def start(self) -> None:
        self.name = "COPYBASE"

    def on_selection(self, entities: list) -> None:
        if not entities:
            self.ctx.finish()
            return
        self.prompt("Specify base point:")

    def on_point(self, point: Point) -> None:
        services = self.ctx.services
        if services is not None and services.copy_selection(base=(point[0], point[1])):
            self.ctx.echo(tr("Copied to clipboard with base point."))
        self.ctx.finish()


class PasteBlockTool(PasteTool):
    """PASTEBLOCK (Ctrl+Shift+V): paste the clipboard as one block, named
    the way AutoCAD names them (A$C plus eight hex digits)."""

    def start(self) -> None:
        super().start()
        self.name = "PASTEBLOCK"

    def on_point(self, point: Point) -> None:
        import secrets

        from core.commands import CompositeCommand, DeferredCommand

        dx, dy = point[0] - self._base[0], point[1] - self._base[1]
        paste = actions.PasteCommand(self._sources, dx, dy,
                                     originals=self._originals)

        def block(document):
            doc = document.doc
            name = "A$C" + secrets.token_hex(4).upper()
            while name in doc.blocks:
                name = "A$C" + secrets.token_hex(4).upper()
            return actions.create_block(name, (point[0], point[1]), list(paste.copies))

        command = CompositeCommand("PASTEBLOCK", [paste, DeferredCommand("block", block)])
        self.ctx.execute(command)
        self.ctx.finish()


EDIT_TOOL_CLASSES = {
    "ERASE": EraseTool,
    "PASTECLIP": PasteTool,
    "COPYBASE": CopyBaseTool,
    "PASTEBLOCK": PasteBlockTool,
    "MOVE": MoveTool,
    "COPY": CopyTool,
    "ROTATE": RotateTool,
    "SCALE": ScaleTool,
    "MIRROR": MirrorTool,
    "OFFSET": OffsetTool,
    "TRIM": TrimTool,
    "EXTEND": ExtendTool,
    "FILLET": FilletTool,
}
