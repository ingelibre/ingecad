# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The interactive side of Roads: thin shells over ``actions``, prompting
the way AutoCAD prompts (English keys, translated through the pack)."""
from __future__ import annotations

import math
from dataclasses import replace

from core.i18n import tr
from core.surveying import format_station
from tools.base import Tool

from . import actions, geometry


def _document(ctx):
    document = getattr(ctx.services, "document", None)
    if document is None:
        document = getattr(getattr(ctx.services, "window", None), "document", None)
    return document


def _number(text: str) -> float:
    return float(text.strip().replace(",", "."))


def _polyline_in(entities, axis_first: bool = True):
    """The axis among ``entities`` (or, failing one, the first open
    LWPOLYLINE)."""
    polylines = [e for e in entities if e.dxftype() == "LWPOLYLINE" and not e.closed]
    if axis_first:
        for entity in polylines:
            if actions.is_axis(entity):
                return entity
    return polylines[0] if polylines else None


class _AxisTool(Tool):
    """Select one polyline, then ask; subclasses say what to ask."""

    wants_selection = True

    def start(self) -> None:
        self._entity = None

    def selection_prompt(self) -> str:
        return tr("Select the axis polyline:")

    def on_selection(self, entities: list) -> None:
        self._entity = _polyline_in(entities)
        if self._entity is None:
            self.ctx.echo(tr("The selection has no open polyline."))
            self.ctx.finish()
            return
        self.picked()

    def picked(self) -> None: ...

    def run(self, command) -> None:
        """Execute, or say why not, and finish the command either way."""
        try:
            built = command()
        except ValueError as exc:
            self.ctx.echo(tr("Cannot do it: {error}", error=exc))
            self.ctx.finish()
            return
        self.ctx.execute(built)
        self.ctx.finish()


class RoadAxisTool(_AxisTool):
    """ROADAXIS: a polyline of tangents and arcs becomes a road axis with
    its start station and direction."""

    def start(self) -> None:
        super().start()
        self.name = "ROADAXIS"

    def picked(self) -> None:
        self._params = actions.axis_params(self._entity) or actions.AxisParams()
        self._ask()

    def _ask(self) -> None:
        self.prompt("Start station <{s}> or [Reverse]:", s=format_station(self._params.start))

    def wants_raw_text(self) -> bool:
        # "1+250.50" is a station, not arithmetic: the command line would
        # otherwise hand over 251.5
        return self._entity is not None

    def on_option(self, text: str) -> bool:
        if self._entity is None:
            return False
        if self.option(text) == "R":
            self._params = replace(self._params, reverse=not self._params.reverse)
            self.ctx.echo(tr("Stationing runs from the last vertex.") if self._params.reverse
                          else tr("Stationing runs from the first vertex."))
            self._ask()
            return True
        try:
            start = geometry.parse_station(text)
        except ValueError:
            self.ctx.echo(tr("Invalid station: {text}", text=text))
            return True
        self._params = replace(self._params, start=start)
        self._finish()
        return True

    def on_enter(self) -> None:
        if self._entity is None:
            self.ctx.finish()
            return
        self._finish()

    def _finish(self) -> None:
        def build():
            command = actions.define_axis(_document(self.ctx), self._entity, self._params)
            length = actions.alignment_of(self._entity, self._params).length
            self.ctx.echo(tr("Axis from {a} to {b} ({n:.3f} m).",
                             a=format_station(self._params.start),
                             b=format_station(self._params.start + length), n=length))
            return command
        self.run(build)


class StationingTool(_AxisTool):
    """STATIONING: ticks and station labels along the axis every N metres,
    replacing the ones drawn before."""

    def start(self) -> None:
        super().start()
        self.name = "STATIONING"
        self._stage = ""

    def picked(self) -> None:
        self._params = actions.axis_params(self._entity) or actions.AxisParams()
        self._stage = "interval"
        self.prompt("Station interval <{v:g}>:", v=self._params.interval)

    def on_option(self, text: str) -> bool:
        if not self._stage:
            return False
        try:
            value = _number(text)
            if value <= 0:
                raise ValueError(text)
        except ValueError:
            self.ctx.echo(tr("Invalid number: {text}", text=text))
            return True
        self._take(value)
        return True

    def on_enter(self) -> None:
        if not self._stage:
            self.ctx.finish()
            return
        self._take(None)

    def _take(self, value) -> None:
        if self._stage == "interval":
            if value is not None:
                self._params = replace(self._params, interval=value)
            self._stage = "tick"
            self.prompt("Tick length <{v:g}>:", v=self._params.tick)
        elif self._stage == "tick":
            if value is not None:
                self._params = replace(self._params, tick=value)
            self._stage = "height"
            self.prompt("Text height <{v:g}>:", v=self._params.height)
        elif self._stage == "height":
            if value is not None:
                self._params = replace(self._params, height=value)
            self._stage = ""
            self.run(lambda: actions.draw_stationing(_document(self.ctx), self._entity,
                                                     self._params))


class RestationTool(Tool):
    """RESTATION: redraw the stationing of the selected axes from their
    current shape and the settings each one remembers."""

    wants_selection = True

    def start(self) -> None:
        self.name = "RESTATION"

    def selection_prompt(self) -> str:
        return tr("Select the axes to restation:")

    def on_selection(self, entities: list) -> None:
        axes = actions.axes_in(entities)
        if not axes:
            self.ctx.echo(tr("The selection has no road axis."))
            self.ctx.finish()
            return
        try:
            command = actions.regenerate(_document(self.ctx), axes)
        except ValueError as exc:
            self.ctx.echo(tr("Cannot do it: {error}", error=exc))
            self.ctx.finish()
            return
        self.ctx.execute(command)
        self.ctx.echo(tr("{n} axes restationed.", n=len(axes)))
        self.ctx.finish()


class AxisReverseTool(_AxisTool):
    """AXISREVERSE: the stationing of the axis runs the other way."""

    def start(self) -> None:
        super().start()
        self.name = "AXISREVERSE"

    def picked(self) -> None:
        self.run(lambda: actions.reverse_axis(_document(self.ctx), self._entity))


class _TableTool(_AxisTool):
    """Select the axis, click the top-left corner of the table."""

    def start(self) -> None:
        super().start()
        self._height = 2.0
        self._await_height = False

    def picked(self) -> None:
        params = actions.axis_params(self._entity)
        if params is not None:
            self._height = params.height
        self._ask()

    def _ask(self) -> None:
        self._await_height = False
        self.prompt("Specify insertion point (top-left) or [Height/Angles]:")

    def on_option(self, text: str) -> bool:
        if self._entity is None:
            return False
        if self._await_height:
            try:
                self._height = _number(text)
                if self._height <= 0:
                    raise ValueError(text)
            except ValueError:
                self.ctx.echo(tr("Invalid number: {text}", text=text))
                return True
            self._ask()
            return True
        key = self.option(text)
        if key == "H":
            self._await_height = True
            self.prompt("Text height <{v:g}>:", v=self._height)
            return True
        if key == "A":
            unit = "deg" if actions.angle_unit() == "grad" else "grad"
            actions.set_angle_unit(unit)
            self.ctx.echo(tr("Angles in grads (gisements).") if unit == "grad"
                          else tr("Angles in degrees (bearings)."))
            self._ask()
            return True
        return False

    def on_enter(self) -> None:
        if self._await_height:
            self._ask()
            return
        self.ctx.finish()

    def on_point(self, point) -> None:
        if self._entity is None or self._await_height:
            return
        self.run(lambda: self.table(_document(self.ctx), point))

    def table(self, document, point): ...


class AxisTableTool(_TableTool):
    """AXISTABLE: the cuadro del eje -- PIs, stations, coordinates, bearings
    and distances."""

    def start(self) -> None:
        super().start()
        self.name = "AXISTABLE"

    def table(self, document, point):
        return actions.axis_table(document, self._entity, point, self._height)


class CurveTableTool(_TableTool):
    """CURVETABLE: the cuadro de elementos de curva, one row per curve."""

    def start(self) -> None:
        super().start()
        self.name = "CURVETABLE"

    def table(self, document, point):
        return actions.curve_table(document, self._entity, point, self._height)


class ElementTableTool(_TableTool):
    """AXISELEMENTS: the tableau des éléments -- every straight, arc and
    clothoid of the axis with its stations, length, radius and A."""

    def start(self) -> None:
        super().start()
        self.name = "AXISELEMENTS"

    def table(self, document, point):
        return actions.element_table(document, self._entity, point, self._height)


class HorizontalCurvesTool(_AxisTool):
    """HCURVES: a chain of tangents (its vertices are the PIs) becomes an
    axis with a simple circular curve at every PI: one radius for all, or
    one typed per PI."""

    #: the last radius typed, offered again as the default
    last_radius = 100.0
    #: the last clothoid length (0: plain circles)
    last_spiral = 0.0
    #: whether HCURVES asks for clothoids after the radius ([Clothoid]
    #: switches it, and it is remembered)
    with_spirals = False

    def start(self) -> None:
        super().start()
        self.name = "HCURVES"
        self._points = None
        self._turns = []
        self._radii = []
        self._spirals = []
        self._each = False
        self._stage = "radius"
        self._as_parameter = False

    def selection_prompt(self) -> str:
        return tr("Select the polyline of tangents:")

    def picked(self) -> None:
        try:
            self._points = actions.tangent_points(self._entity)
        except ValueError as exc:
            self.ctx.echo(tr("Cannot do it: {error}", error=exc))
            self.ctx.finish()
            return
        self._turns = geometry.deflections(self._points)
        self.ctx.echo(tr("{n} PIs.", n=len(self._turns)))
        self._ask_all()

    def _ask_all(self) -> None:
        self._each = False
        self._stage = "radius"
        self.prompt("Radius for every PI <{r:g}> or [Each/Clothoid]:", r=HorizontalCurvesTool.last_radius)

    def _ask_spiral(self) -> None:
        """The clothoid after the radius: a length, or A with [Parameter]."""
        self._stage = "spiral"
        if self._as_parameter:
            a = math.sqrt(HorizontalCurvesTool.last_spiral * self._current_radius())
            self.prompt("Clothoid parameter A (0 = none) <{a:g}>:", a=round(a, 3))
        elif self._each:
            self.prompt("Clothoid length at PI-{n} (0 = none) <{l:g}> or [Parameter]:",
                        n=len(self._radii), l=HorizontalCurvesTool.last_spiral)
        else:
            self.prompt("Clothoid length for every PI (0 = none) <{l:g}> or [Parameter]:",
                        l=HorizontalCurvesTool.last_spiral)

    def _current_radius(self) -> float:
        return self._radii[-1] if self._radii else HorizontalCurvesTool.last_radius

    def _next_pi(self) -> None:
        """Ask the radius of the next PI that turns; build after the last."""
        while len(self._radii) < len(self._turns) and abs(self._turns[len(self._radii)]) < 1e-7:
            self._radii.append(0.0)                 # aligned tangents: no curve
            self._spirals.append(0.0)
        if len(self._radii) == len(self._turns):
            self._build()
            return
        i = len(self._radii)
        self._stage = "radius"
        self.prompt("Radius at PI-{n} (deflection {d}) <{r:g}>:", n=i + 1,
                    d=actions.format_angle(abs(self._turns[i]), actions.angle_unit()),
                    r=HorizontalCurvesTool.last_radius)

    def on_option(self, text: str) -> bool:
        if self._points is None:
            return False
        if self._stage == "spiral":
            return self._on_spiral(text)
        if not self._each and self.option(text) == "C":
            HorizontalCurvesTool.with_spirals = not HorizontalCurvesTool.with_spirals
            self.ctx.echo(tr("Curves with clothoids.") if HorizontalCurvesTool.with_spirals
                          else tr("Curves without clothoids."))
            self._ask_all()
            return True
        if not self._each and self.option(text) == "E":
            self._each = True
            self._radii = []
            self._spirals = []
            self._next_pi()
            return True
        try:
            radius = _number(text)
            if radius <= 0:
                raise ValueError(text)
        except ValueError:
            self.ctx.echo(tr("Invalid radius: {text}", text=text))
            return True
        HorizontalCurvesTool.last_radius = radius
        self._take(radius)
        return True

    def on_enter(self) -> None:
        if self._points is None:
            self.ctx.finish()
            return
        if self._stage == "spiral":
            self._take_spiral(HorizontalCurvesTool.last_spiral)
            return
        self._take(HorizontalCurvesTool.last_radius)

    def _take(self, radius: float) -> None:
        if self._each:
            self._radii.append(radius)
        else:
            self._radii = [radius] * len(self._turns)
        self._as_parameter = False
        if HorizontalCurvesTool.with_spirals:
            self._ask_spiral()
        elif self._each:
            self._spirals.append(0.0)
            self._next_pi()
        else:
            self._spirals = [0.0] * len(self._turns)
            self._build()

    def _on_spiral(self, text: str) -> bool:
        if not self._as_parameter and self.option(text) == "P":
            self._as_parameter = True
            self._ask_spiral()
            return True
        try:
            value = _number(text)
            if value < 0:
                raise ValueError(text)
        except ValueError:
            self.ctx.echo(tr("Invalid number: {text}", text=text))
            return True
        if self._as_parameter:
            value = value * value / self._current_radius() if value > 0 else 0.0
        self._take_spiral(value)
        return True

    def _take_spiral(self, length: float) -> None:
        HorizontalCurvesTool.last_spiral = length
        self._as_parameter = False
        if self._each:
            self._spirals.append(length)
            self._next_pi()
        else:
            self._spirals = [length if r > 0 else 0.0 for r in self._radii]
            self._build()

    def _build(self) -> None:
        try:
            command = actions.fit_axis(_document(self.ctx), self._entity, self._radii,
                                       spirals=self._spirals)
        except geometry.TangentOverlap as exc:
            where = (f"PI-{exc.first}" if exc.first == exc.second
                     else f"PI-{exc.first} / PI-{exc.second}")
            self.ctx.echo(tr("Cannot fit the curves: the tangents overlap at {where} "
                             "(T1 + T2 = {need:.3f} m > {have:.3f} m). Use smaller radii.",
                             where=where, need=exc.needed, have=exc.available))
            self.ctx.finish()
            return
        except geometry.SpiralTooLong as exc:
            self.ctx.echo(tr("Cannot fit the clothoids: {error}. Use shorter clothoids or a larger "
                             "radius.", error=exc))
            self.ctx.finish()
            return
        except ValueError as exc:
            self.ctx.echo(tr("Cannot do it: {error}", error=exc))
            self.ctx.finish()
            return
        self.ctx.execute(command)
        alignment = actions.alignment_of(command.axis_command.entity)
        n = sum(1 for pi in geometry.points_of_intersection(alignment) if pi.curve)
        self.ctx.echo(tr("{n} curves fitted; axis from {a} to {b}.", n=n,
                         a=format_station(alignment.start_station),
                         b=format_station(alignment.end_station)))
        self.ctx.finish()


class RoadCheckTool(_AxisTool):
    """ROADCHECK: every curve of the axis against a design standard (ARP,
    ICTAAL, ICTAVRU... from the norms folder) -- minimum radius,
    superelevation, clothoids, chaining of the radii."""

    last_norm = "ARP1994"
    last_category: dict = {}
    last_lanes = 2

    def start(self) -> None:
        super().start()
        self.name = "ROADCHECK"
        from . import norms

        self._norms = norms.available()
        self._norm = None
        self._stage = "select"

    def picked(self) -> None:
        if not self._norms:
            self.ctx.echo(tr("No design standard found in the norms folder."))
            self.ctx.finish()
            return
        if RoadCheckTool.last_norm not in self._norms:
            RoadCheckTool.last_norm = next(iter(self._norms))
        self._ask_norm()

    def _ask_norm(self) -> None:
        self._stage = "norm"
        self.prompt("Design standard ({ids}) <{d}>:", ids=", ".join(self._norms), d=RoadCheckTool.last_norm)

    def _ask_category(self) -> None:
        self._stage = "category"
        cats = list(self._norm.categories)
        default = RoadCheckTool.last_category.get(self._norm.id, cats[0])
        self.prompt("Category ({cats}) <{d}>:", cats=", ".join(cats), d=default)

    def _ask_lanes(self) -> None:
        self._stage = "lanes"
        self.prompt("Lanes in the cross-section (2, 3 or 4) <{n}>:", n=RoadCheckTool.last_lanes)

    def on_option(self, text: str) -> bool:
        if self._entity is None:
            return False
        value = text.strip()
        if self._stage == "norm":
            match = next((k for k in self._norms if k.lower() == value.lower()), None)
            if match is None:
                self.ctx.echo(tr("Unknown standard: {text}", text=value))
                return True
            RoadCheckTool.last_norm = match
            self._norm = self._norms[match]
            self._ask_category()
            return True
        if self._stage == "category":
            try:
                name = self._norm.category_name(value)
            except KeyError:
                self.ctx.echo(tr("Unknown category: {text}", text=value))
                return True
            RoadCheckTool.last_category[self._norm.id] = name
            self._ask_lanes()
            return True
        if self._stage == "lanes":
            if value not in ("2", "3", "4"):
                self.ctx.echo(tr("Invalid number: {text}", text=value))
                return True
            RoadCheckTool.last_lanes = int(value)
            self._run()
            return True
        return False

    def on_enter(self) -> None:
        if self._stage == "norm":
            self.on_option(RoadCheckTool.last_norm)
        elif self._stage == "category":
            self.on_option(RoadCheckTool.last_category.get(self._norm.id, next(iter(self._norm.categories))))
        elif self._stage == "lanes":
            self._run()
        else:
            self.ctx.finish()

    def _run(self) -> None:
        from . import norms

        try:
            report = norms.check(actions.alignment_of(self._entity), self._norm,
                                 RoadCheckTool.last_category.get(self._norm.id, next(iter(self._norm.categories))),
                                 RoadCheckTool.last_lanes)
        except ValueError as exc:
            self.ctx.echo(tr("Cannot do it: {error}", error=exc))
            self.ctx.finish()
            return
        self.ctx.echo(tr("{name}, category {cat}.", name=report.norm.name, cat=report.category))
        if not report.norm.verified:
            self.ctx.echo(tr("Values to check against the guide: {note}", note=report.norm.note))
        marks = {"error": tr("ERROR"), "warning": tr("WARNING"), "info": "-"}
        for f in report.findings:
            self.ctx.echo(f"{marks[f.level]} {f.text}")
        if not report.findings:
            self.ctx.echo(tr("The axis has no curves."))
        self.ctx.echo(tr("{e} error(s), {w} warning(s). Source: {source}", e=report.errors,
                         w=report.warnings, source=report.norm.source))
        self.ctx.finish()


TOOL_CLASSES = {
    "AXISELEMENTS": ElementTableTool,
    "ROADCHECK": RoadCheckTool,
    "ROADAXIS": RoadAxisTool,
    "STATIONING": StationingTool,
    "RESTATION": RestationTool,
    "AXISREVERSE": AxisReverseTool,
    "AXISTABLE": AxisTableTool,
    "HCURVES": HorizontalCurvesTool,
    "CURVETABLE": CurveTableTool,
}
