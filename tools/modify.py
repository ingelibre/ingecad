# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The editing commands and their prompts: STRETCH, BREAK, JOIN, CHAMFER,
ARRAY, MATCHPROP, PEDIT.

Wording follows the AutoCAD Command Reference (STRETCH p.1851, BREAK p.269,
JOIN p.1013, CHAMFER p.313, -ARRAY p.155, MATCHPROP p.1080, PEDIT p.1434).
The geometry is in ``core.modify``, so every flow is testable without a GUI.

Deliberate deviations, each a smaller menu rather than a different one:

* ARRAY runs the classic ``-ARRAY`` prompts and produces plain copies. The
  modern associative array is a parametric object a colleague's AutoCAD
  would have to understand coming back; the round trip matters more here.
* PEDIT offers Close/Open, Width, Reverse and Undo. Fit, Spline, Decurve,
  Ltype gen and Edit vertex are not listed, because a prompt that accepts a
  keyword and does nothing with it is worse than one that never offered it.
"""
from __future__ import annotations

from core import actions, editmath, modify
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
        self.prompt("Specify base point or [Displacement] "
                    "<Displacement>:")

    def on_point(self, point: Point) -> None:
        if self._base is None:
            self._base = point
            self.last_point = point
            self.prompt("Specify second point or <use first point as displacement>:")
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
            self.prompt("Specify second break point or [First point]:")
            return

        if self._await_first:
            self._first = point
            self._await_first = False
            self.prompt("Specify second break point:")
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


class ChamferTool(Tool):
    """CHAMFER: bevel the corner two lines make, by two distances."""

    entity_picker = True
    dist1 = 0.0        # session-sticky, like AutoCAD's
    dist2 = 0.0
    trim = True

    def start(self) -> None:
        self.name = "CHAMFER"
        self._first = None
        self._await = None
        self._announce()

    def _announce(self) -> None:
        cls = type(self)
        mode = tr("TRIM") if cls.trim else tr("NOTRIM")
        self.ctx.echo(tr("({mode} mode) Current chamfer Dist1 = {d1}, "
                         "Dist2 = {d2}", mode=mode,
                         d1=f"{cls.dist1:g}", d2=f"{cls.dist2:g}"))
        self.prompt("Select first line or [Distance/Trim]:")

    def on_option(self, text: str) -> bool:
        # The resolver first: it turns the localized keyword, or
        # AutoCAD's _global form, into the English key the
        # branches below have always compared against.
        token = self.option(text) or text.strip().upper()
        cls = type(self)
        if self._await == "d1":
            value = _number(text)
            if value is None or value < 0:
                self.ctx.echo(tr("Requires a positive number."))
                return True
            cls.dist1 = value
            self._await = "d2"
            self.prompt("Specify second chamfer distance <{d}>:",
                        d=f"{cls.dist1:g}")
            return True
        if self._await == "d2":
            value = _number(text) if text.strip() else cls.dist1
            if value is None or value < 0:
                self.ctx.echo(tr("Requires a positive number."))
                return True
            cls.dist2 = value
            self._await = None
            self._announce()
            return True
        if self._await == "trim":
            if token.startswith("T"):
                cls.trim = True
            elif token.startswith("N"):
                cls.trim = False
            else:
                self.ctx.echo(tr("Requires Trim or No trim."))
                return True
            self._await = None
            self._announce()
            return True
        if token in ("D", "DISTANCE"):
            self._await = "d1"
            self.prompt("Specify first chamfer distance <{d}>:",
                        d=f"{cls.dist1:g}")
            return True
        if token in ("T", "TRIM"):
            self._await = "trim"
            self.prompt("Enter Trim mode option [Trim/No trim] "
                        "<{mode}>:",
                        mode=tr("Trim") if cls.trim else tr("No trim"))
            return True
        return False

    def on_enter(self) -> None:
        if self._await == "d2":
            self.on_option("")
            return
        self.ctx.finish()

    def on_point(self, point: Point) -> None:
        services = self.ctx.services
        entity = services.pick_entity(point) if services else None
        if entity is None or entity.dxftype() != "LINE":
            self.ctx.echo(tr("CHAMFER works on pairs of lines."))
            return
        if self._first is None:
            self._first = entity
            self.prompt("Select second line:")
            return
        if entity is self._first:
            self.ctx.echo(tr("Pick a different line."))
            return
        cls = type(self)
        s1 = _seg(self._first)
        s2 = _seg(entity)
        pieces = editmath.chamfer_pieces(s1, s2, cls.dist1, cls.dist2)
        if pieces is None:
            self.ctx.echo(tr("The chamfer does not fit those lines."))
            self.ctx.finish()
            return
        new1, new2, bevel = pieces
        factories = [lambda msp, p=bevel: msp.add_line((p[0], p[1]),
                                                       (p[2], p[3]))]
        if cls.trim:
            factories = [
                lambda msp, p=new1: msp.add_line((p[0], p[1]), (p[2], p[3])),
                lambda msp, p=new2: msp.add_line((p[0], p[1]), (p[2], p[3])),
            ] + factories
            old = [self._first, entity]
        else:
            old = []
        self.ctx.execute(actions.ReplaceEntitiesCommand(
            "CHAMFER", old, factories))
        self.ctx.finish()


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
    def _take_rows(self, text: str) -> bool:
        self._rows = int(_number(text) or 1)
        self._await = "cols"
        self.prompt("Enter the number of columns (|||) <1>:")
        return True

    def _take_cols(self, text: str) -> bool:
        self._cols = int(_number(text) or 1)
        if self._rows <= 1 and self._cols <= 1:
            self.ctx.echo(tr("One row and one column is the object itself."))
            self.ctx.finish()
            return True
        self._await = "row_spacing"
        self.prompt("Enter the distance between rows (---):")
        return True

    def _take_row_spacing(self, text: str) -> bool:
        self._row_spacing = _number(text) or 0.0
        self._await = "col_spacing"
        self.prompt("Specify the distance between columns (|||):")
        return True

    def _take_col_spacing(self, text: str) -> bool:
        spacing = _number(text) or 0.0
        self.ctx.execute(modify.array_rect(
            self._entities, self._rows, self._cols,
            self._row_spacing, spacing))
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
        self.prompt("Enter an option [{first}/Width/Reverse/Undo/eXit] <eXit>:",
               first=first)

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


MODIFY_TOOL_CLASSES = {
    "STRETCH": StretchTool,
    "BREAK": BreakTool,
    "JOIN": JoinTool,
    "CHAMFER": ChamferTool,
    "ARRAY": ArrayTool,
    "MATCHPROP": MatchPropTool,
    "PEDIT": PeditTool,
    "DRAWORDER": DrawOrderTool,
    "LAYISO": LayIsoTool,
    "LAYOFF": LayOffTool,
    "IMAGEADJUST": ImageAdjustTool,
    "TRANSPARENCY": ImageTransparencyTool,
    "ISOLATEOBJECTS": IsolateObjectsTool,
    "HIDEOBJECTS": HideObjectsTool,
    "SELECTSIMILAR": SelectSimilarTool,
    "ADDSELECTED": AddSelectedTool,
}
