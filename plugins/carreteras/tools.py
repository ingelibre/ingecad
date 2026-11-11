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

        category = RoadCheckTool.last_category.get(self._norm.id, next(iter(self._norm.categories)))
        try:
            report = norms.check(actions.alignment_of(self._entity), self._norm, category,
                                 RoadCheckTool.last_lanes)
            for valign in actions.verticals_of_axis(_document(self.ctx), self._entity):
                norms.check_vertical(valign, self._norm, category, report)
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


# ======================================================================
# C3: vertical curves; superelevation; C4: mass haul
# ======================================================================

def _topo_tools():
    import importlib
    import sys

    module = sys.modules.get("ingecad_plugin_topografia.tools")
    if module is not None:
        return module
    try:
        return importlib.import_module("plugins.topografia.tools")
    except ImportError:
        return None


class VerticalCurvesTool(Tool):
    """VCURVES: a grade line registered with GRADELINE (its vertices are
    the sommets) becomes a design line with a parabolic curve at each
    sommet -- one radius for all, or one per sommet."""

    wants_selection = True
    last_radius = 3000.0

    def start(self) -> None:
        self.name = "VCURVES"
        self._entity = None
        self._sommets = None
        self._radii = []
        self._each = False

    def selection_prompt(self) -> str:
        return tr("Select the grade line:")

    def on_selection(self, entities: list) -> None:
        document = _document(self.ctx)
        topo = actions.topography()
        for entity in entities:
            if topo is not None and topo.is_grade(entity) and actions.vertical_of(entity) is None:
                try:
                    self._sommets, _anchor, _frame = actions.grade_sommets(document, entity)
                except ValueError as exc:
                    self.ctx.echo(tr("Cannot do it: {error}", error=exc))
                    self.ctx.finish()
                    return
                self._entity = entity
                break
        if self._entity is None:
            self.ctx.echo(tr("Select a grade line registered with GRADELINE."))
            self.ctx.finish()
            return
        if len(self._sommets) < 3:
            self.ctx.echo(tr("The grade line has no sommet between its ends."))
            self.ctx.finish()
            return
        self.ctx.echo(tr("{n} sommets.", n=len(self._sommets) - 2))
        self.prompt("Vertical radius for every sommet <{r:g}> or [Each]:", r=VerticalCurvesTool.last_radius)

    def _next(self) -> None:
        i = len(self._radii)
        if i == len(self._sommets) - 2:
            self._build()
            return
        (s0, z0), (s1, z1), (s2, z2) = self._sommets[i:i + 3]
        p1, p2 = (z1 - z0) / (s1 - s0), (z2 - z1) / (s2 - s1)
        kind = tr("crest") if p2 < p1 else tr("sag")
        self.prompt("Vertical radius at S{n} ({kind}, {p1:+.2f} % to {p2:+.2f} %) <{r:g}>:", n=i + 1,
                    kind=kind, p1=p1 * 100, p2=p2 * 100, r=VerticalCurvesTool.last_radius)

    def on_option(self, text: str) -> bool:
        if self._sommets is None:
            return False
        if not self._each and self.option(text) == "E":
            self._each = True
            self._next()
            return True
        try:
            radius = _number(text)
            if radius < 0:
                raise ValueError(text)
        except ValueError:
            self.ctx.echo(tr("Invalid radius: {text}", text=text))
            return True
        self._take(radius)
        return True

    def on_enter(self) -> None:
        if self._sommets is None:
            self.ctx.finish()
            return
        self._take(VerticalCurvesTool.last_radius)

    def _take(self, radius: float) -> None:
        if radius > 0:
            VerticalCurvesTool.last_radius = radius
        if self._each:
            self._radii.append(radius)
            self._next()
        else:
            self._radii = [radius] * (len(self._sommets) - 2)
            self._build()

    def _build(self) -> None:
        try:
            command = actions.vertical_curves(_document(self.ctx), self._entity, self._radii)
        except ValueError as exc:
            self.ctx.echo(tr("Cannot fit the vertical curves: {error}. Use smaller radii.", error=exc))
            self.ctx.finish()
            return
        self.ctx.execute(command)
        for c in command.vertical.curves():
            if c.radius > 0:
                self.ctx.echo(tr("S{n}: {kind} R = {r:.0f} m, T = {t:.2f} m, f = {f:.3f} m.", n=c.number,
                                 kind=tr("crest") if c.crest else tr("sag"), r=c.radius, t=c.tangent, f=c.flech))
        self.ctx.finish()


class VerticalTableTool(_TableTool):
    """VCURVETABLE: the table of the vertical curves of a design line."""

    def start(self) -> None:
        super().start()
        self.name = "VCURVETABLE"

    def selection_prompt(self) -> str:
        return tr("Select the design line drawn by VCURVES:")

    def on_selection(self, entities: list) -> None:
        self._entity = next((e for e in entities if actions.vertical_of(e) is not None), None)
        if self._entity is None:
            self.ctx.echo(tr("Select a design line drawn by VCURVES."))
            self.ctx.finish()
            return
        self._ask()

    def table(self, document, point):
        return actions.vertical_table(document, self._entity, point, self._height)


class SuperelevationTool(RoadCheckTool):
    """SUPERELEV: the table of dévers (and widening) along the axis, from a
    design standard and category."""

    def start(self) -> None:
        super().start()
        self.name = "SUPERELEV"

    def _run(self) -> None:
        self._stage = "point"
        self.prompt("Specify insertion point (top-left):")

    def on_point(self, point) -> None:
        if self._stage != "point":
            return
        category = RoadCheckTool.last_category.get(self._norm.id, next(iter(self._norm.categories)))
        try:
            command = actions.superelevation_table(_document(self.ctx), self._entity, point, self._norm,
                                                   category, RoadCheckTool.last_lanes,
                                                   (actions.axis_params(self._entity) or actions.AxisParams()).height)
        except ValueError as exc:
            self.ctx.echo(tr("Cannot do it: {error}", error=exc))
            self.ctx.finish()
            return
        self.ctx.execute(command)
        if not self._norm.verified:
            self.ctx.echo(tr("Values to check against the guide: {note}", note=self._norm.note))
        self.ctx.finish()

    def on_enter(self) -> None:
        if self._stage == "point":
            self.ctx.finish()
            return
        super().on_enter()


class MassHaulTool(Tool):
    """MASSHAUL: the mass-haul diagram (épure de Lalanne / Brückner) of the
    earthworks between the ground and a grade line -- with the coefficient
    that turns a cubic metre dug into the fill it makes."""

    wants_selection = True
    last_coefficient = 1.0

    def start(self) -> None:
        self.name = "MASSHAUL"
        topo_tools = _topo_tools()
        self._topo = actions.topography()
        self._tin = topo_tools._surface(self.ctx) if topo_tools is not None else None
        self._grade = None
        self._frame = None
        self._axis = None
        self._haul = None
        if self._topo is None or self._tin is None:
            self.ctx.echo(tr("The mass diagram needs the Topography plugin and a surface (TIN)."))
            self.ctx.finish()
            return
        self._template = self._topo._profile.template_from_settings()
        self._stage = "select"

    def selection_prompt(self) -> str:
        return tr("Select the grade line:")

    def on_selection(self, entities: list) -> None:
        document = _document(self.ctx)
        grade = next((e for e in entities if self._topo.is_grade(e)), None)
        anchor = self._topo.grade_profile_anchor(document, grade) if grade is not None else None
        if anchor is None:
            self.ctx.echo(tr("Select a grade line registered with GRADELINE."))
            self.ctx.finish()
            return
        self._frame = self._topo.ProfileFrame.from_entity(anchor)
        valign = actions.vertical_of(grade)
        if valign is not None:
            self._grade = valign.sample(1.0)
        else:
            self._grade = self._topo.grade_of(grade, self._frame)
        self._axis = next((e for e in document.current_space() if e.dxf.handle == self._frame.axis_handle), None)
        if self._axis is None:
            self.ctx.echo(tr("The profile's axis is no longer in the drawing."))
            self.ctx.finish()
            return
        self._stage = "platform"
        self.prompt("Platform width <{w:g}>:", w=self._template.width)

    def _ask(self) -> None:
        if self._stage == "cut":
            self.prompt("Cut slope H:V <{v:g}>:", v=self._template.cut_hv)
        elif self._stage == "fill":
            self.prompt("Fill slope H:V <{v:g}>:", v=self._template.fill_hv)
        elif self._stage == "coefficient":
            self.prompt("Coefficient applied to the cut (swell, reuse) <{k:g}>:", k=MassHaulTool.last_coefficient)
        elif self._stage == "point":
            self.prompt("Specify the bottom-left corner of the diagram:")

    def on_option(self, text: str) -> bool:
        if self._stage in ("select", "point"):
            return False
        try:
            value = _number(text)
            if value <= 0:
                raise ValueError(text)
        except ValueError:
            self.ctx.echo(tr("Invalid number: {text}", text=text))
            return True
        if self._stage == "platform":
            self._template.width = value
            self._stage = "cut"
        elif self._stage == "cut":
            self._template.cut_hv = value
            self._stage = "fill"
        elif self._stage == "fill":
            self._template.fill_hv = value
            self._stage = "coefficient"
        elif self._stage == "coefficient":
            MassHaulTool.last_coefficient = value
            self._compute()
            return True
        self._ask()
        return True

    def on_enter(self) -> None:
        order = ["platform", "cut", "fill", "coefficient"]
        if self._stage in order:
            if self._stage == "coefficient":
                self._compute()
                return
            self._stage = order[order.index(self._stage) + 1]
            self._ask()
        else:
            self.ctx.finish()

    def _compute(self) -> None:
        rows = self._topo.earthworks_rows(self._tin, self._axis, self._grade, self._frame.step, self._template)
        self._haul = actions.mass_haul(rows, MassHaulTool.last_coefficient)
        last = rows[-1] if rows else None
        if last is not None:
            self.ctx.echo(tr("Cut {c:.0f} m³ (x {k:g}), fill {f:.0f} m³.", c=last.cut_total,
                             k=MassHaulTool.last_coefficient, f=last.fill_total))
        for n, seg in enumerate(self._haul.segments, 1):
            self.ctx.echo(tr("Segment {n}: {a} to {b}, {v:.0f} m³ carried {dir}, mean distance {d:.0f} m.",
                             n=n, a=format_station(seg.start), b=format_station(seg.end), v=seg.volume,
                             dir=tr("forward") if seg.forward else tr("backward"), d=seg.distance))
        surplus = self._haul.surplus
        self.ctx.echo(tr("Surplus to spoil: {v:.0f} m³", v=surplus) if surplus > 0
                      else tr("Deficit to borrow: {v:.0f} m³", v=-surplus))
        self._stage = "point"
        self._ask()

    def on_point(self, point) -> None:
        if self._stage != "point":
            return
        try:
            command = actions.mass_haul_diagram(_document(self.ctx), self._haul, point,
                                                self._frame.hscale, name=self._frame.name)
        except ValueError as exc:
            self.ctx.echo(tr("Cannot do it: {error}", error=exc))
            self.ctx.finish()
            return
        self.ctx.execute(command)
        self.ctx.finish()


TOOL_CLASSES.update({
    "VCURVES": VerticalCurvesTool,
    "VCURVETABLE": VerticalTableTool,
    "SUPERELEV": SuperelevationTool,
    "MASSHAUL": MassHaulTool,
})
