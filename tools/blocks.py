# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Block and hatch tools: BLOCK, INSERT, EXPLODE, HATCH.

BLOCK converts a selection into a named block reference in place (AutoCAD's
"Convert to block" default). INSERT places an existing block with X scale and
rotation. EXPLODE breaks a reference (or polyline) into its parts. HATCH fills
closed boundary objects with SOLID or a named pattern at a scale/angle.
"""
from __future__ import annotations

from core import actions
from core.i18n import tr
from tools.base import Point, Tool


class BlockTool(Tool):
    """BLOCK: name the selection, pick a base point, convert to a reference."""

    wants_selection = True

    def start(self) -> None:
        self.name = "BLOCK"
        self._entities: list = []
        self._block_name: str | None = None

    def on_selection(self, entities: list) -> None:
        if not entities:
            self.ctx.finish()
            return
        self._entities = entities
        name = self.ctx.ask_text(tr("Block name:"), "")
        if not name or not name.strip():
            self.ctx.echo(tr("*Cancel*"))
            self.ctx.finish()
            return
        self._block_name = name.strip()
        self.ctx.prompt(tr("Specify insertion base point:"))

    def on_point(self, point: Point) -> None:
        if self._block_name and self._entities:
            self.ctx.execute(
                actions.create_block(self._block_name, point, self._entities))
            self.ctx.echo(tr("Block '{name}' created.", name=self._block_name))
        self.ctx.finish()


class InsertTool(Tool):
    """INSERT: choose a defined block, then place it (Scale/Rotate options)."""

    def start(self) -> None:
        self.name = "INSERT"
        self._block_name: str | None = None
        self._xscale = 1.0
        self._rotation = 0.0
        self._await: str | None = None
        names = self.ctx.services.block_names() if self.ctx.services else []
        if not names:
            self.ctx.echo(tr("No blocks defined."))
            self.ctx.finish()
            return
        chosen = self.ctx.ask_choice(tr("Insert block:"), names, names[0])
        if not chosen:
            self.ctx.finish()
            return
        self._block_name = chosen
        self.ctx.prompt(tr("Specify insertion point [Scale/Rotate]:"))

    def on_option(self, text: str) -> bool:
        t = text.strip().upper()
        if self._await is None and t in ("S", "SCALE"):
            self._await = "scale"
            self.ctx.prompt(tr("Specify scale factor <{v}>:", v=self._xscale))
            return True
        if self._await is None and t in ("R", "ROTATE"):
            self._await = "rotate"
            self.ctx.prompt(tr("Specify rotation angle <{v}>:", v=self._rotation))
            return True
        if self._await is not None:
            try:
                value = float(text)
            except ValueError:
                return False
            if self._await == "scale":
                self._xscale = value
            else:
                self._rotation = value
            self._await = None
            self.ctx.prompt(tr("Specify insertion point [Scale/Rotate]:"))
            return True
        return False

    def on_point(self, point: Point) -> None:
        if self._block_name:
            self.ctx.execute(actions.insert_block(
                self._block_name, point, self._xscale, self._xscale,
                self._rotation))
        self.ctx.finish()


class ExplodeTool(Tool):
    """EXPLODE: break block references and polylines into their components."""

    wants_selection = True
    _EXPLODABLE = ("INSERT", "LWPOLYLINE", "POLYLINE")

    def start(self) -> None:
        self.name = "EXPLODE"

    def on_selection(self, entities: list) -> None:
        targets = [e for e in entities if e.dxftype() in self._EXPLODABLE]
        if targets:
            self.ctx.execute(actions.explode_entities(targets))
            self.ctx.echo(tr("{n} exploded.", n=len(targets)))
        else:
            self.ctx.echo(tr("Nothing that can be exploded was selected."))
        self.ctx.finish()


def _is_boundary(e) -> bool:
    t = e.dxftype()
    if t == "LWPOLYLINE":
        return bool(e.closed)
    if t == "POLYLINE":
        return bool(getattr(e, "is_closed", False))
    return t in ("CIRCLE", "ELLIPSE")


class HatchTool(Tool):
    """HATCH: choose a style, then pick internal points (or select objects).

    Mirrors AutoCAD: the style/pattern dialog comes first (SOLID among the
    predefined patterns), then the ``Pick internal point or [Select objects/
    seTtings]`` prompt — click inside closed areas, Enter to apply. Islands
    (closed loops inside the picked region) become holes.
    """

    # Last-used settings persist for the session (AutoCAD remembers them).
    _last = {"pattern": "SOLID", "scale": 1.0, "angle": 0.0, "color": 256}
    # Set by the Palette to launch HATCH straight into point-picking with the
    # already-chosen pattern (skips the style dialog). One-shot.
    _skip_dialog = False

    def start(self) -> None:
        self.name = "HATCH"
        self.mode = "pick"
        self.outer: list = []      # picked outer boundaries (point lists)
        self.islands: list = []    # island loops (holes)
        self.selected: list = []   # boundary entities from Select objects
        self.settings = dict(HatchTool._last)
        if HatchTool._skip_dialog:
            HatchTool._skip_dialog = False   # already have a pattern; go draw
            self._prompt()
            return
        chosen = self.ctx.ask_hatch(self.settings)
        if chosen is None:
            self.ctx.finish()
            return
        self.settings = chosen
        HatchTool._last = dict(chosen)
        self._prompt()

    def _prompt(self) -> None:
        self.ctx.prompt(tr(
            "Pick internal point or [Select objects/seTtings], Enter to apply:"))

    def on_option(self, text: str) -> bool:
        t = text.strip().upper()
        if t in ("S", "SELECT"):
            self.mode = "select"
            self.ctx.prompt(tr("Select boundary objects, Enter to apply:"))
            return True
        if t in ("T", "SETTINGS", "K"):
            chosen = self.ctx.ask_hatch(self.settings)
            if chosen is not None:
                self.settings = chosen
                HatchTool._last = dict(chosen)
            self._prompt()
            return True
        return False

    def on_point(self, point) -> None:
        if self.mode == "select":
            e = self.ctx.services.pick_entity(point) if self.ctx.services else None
            if e is not None and _is_boundary(e):
                if e not in self.selected:
                    self.selected.append(e)
                    self.ctx.echo(tr("1 boundary added."))
            else:
                self.ctx.echo(tr("No closed boundary at that point."))
            return
        region = self.ctx.services.hatch_region_at(point) \
            if self.ctx.services else None
        if region is None:
            self.ctx.echo(tr("No closed boundary found at that point."))
            return
        outer, islands = region
        self.outer.append(outer)
        self.islands.extend(islands)
        self.ctx.echo(tr("Boundary found."))

    def on_enter(self) -> None:
        boundaries = list(self.selected) + list(self.outer)
        if not boundaries:
            self.ctx.echo(tr("No boundaries picked."))
            self.ctx.finish()
            return
        s = self.settings
        self.ctx.execute(actions.add_hatch(
            boundaries, s["pattern"], s["scale"], s["angle"],
            color=s.get("color", 256), islands=self.islands))
        self.ctx.echo(tr("Hatch created."))
        self.ctx.finish()


class HatchCliTool(HatchTool):
    """-HATCH: AutoCAD's command-line hatch. Same boundary machinery as the
    dialog HATCH, driven entirely from the prompt: Properties (pattern name
    with the ,N/,O/,I style suffix, ?, Solid, User defined), Select objects,
    draW boundary (point-defined loops, optionally retained as a polyline),
    Advanced (island Style) and hatch COlor. Settings persist per session
    like the HP* sysvars."""

    _style = actions.HATCH_STYLE_NORMAL      # island style, session-sticky
    _user = (0.0, 1.0, False)                # User-defined angle/spacing/double
    _retain = False

    def start(self) -> None:
        self.name = "-HATCH"
        self.mode = "pick"
        self.outer = []
        self.islands = []
        self.selected = []
        self.settings = dict(HatchTool._last)
        self._user_def = None                # active only when U was chosen
        self._await = None
        self._pending = {}
        self._loop: list = []                # draW boundary points
        self.ctx.echo(tr("Current hatch pattern:  {name}",
                         name=self.settings["pattern"]))
        self._prompt()

    def _prompt(self) -> None:
        self.ctx.prompt(tr(
            "Specify internal point or [Properties/Select objects/"
            "draW boundary/Advanced/hatch COlor]:"))

    # -- option flows ----------------------------------------------------------
    def on_option(self, text: str) -> bool:
        t = text.strip().upper()
        value = None
        try:
            value = float(text)
        except ValueError:
            pass
        cls = type(self)
        if self._await == "pattern":
            return self._on_pattern_name(text)
        if self._await == "scale":
            if text == "":
                value = self.settings["scale"]
            if value is None or value <= 0:
                return False
            self.settings["scale"] = value
            self._await = "angle"
            self.ctx.prompt(tr("Specify an angle for the pattern <{a:g}>:",
                               a=self.settings["angle"]))
            return True
        if self._await == "angle":
            if text == "":
                value = self.settings["angle"]
            if value is None:
                return False
            self.settings["angle"] = value
            self._await = None
            HatchTool._last = dict(self.settings)
            self._prompt()
            return True
        if self._await == "user_angle":
            if text == "":
                value = cls._user[0]
            if value is None:
                return False
            self._pending["ua"] = value
            self._await = "user_spacing"
            self.ctx.prompt(tr("Specify spacing between the lines <{s:g}>:",
                               s=cls._user[1]))
            return True
        if self._await == "user_spacing":
            if text == "":
                value = cls._user[1]
            if value is None or value <= 0:
                return False
            self._pending["us"] = value
            self._await = "user_double"
            self.ctx.prompt(tr("Double hatch area? [Yes/No] <N>:"))
            return True
        if self._await == "user_double":
            if t in ("Y", "YES"):
                double = True
            elif t in ("", "N", "NO"):
                double = False
            else:
                return False
            cls._user = (self._pending["ua"], self._pending["us"], double)
            self._user_def = cls._user
            self.settings["pattern"] = "U"
            HatchTool._last = dict(self.settings)
            self._await = None
            self._prompt()
            return True
        if self._await == "style":
            if t in ("N", "NORMAL"):
                cls._style = actions.HATCH_STYLE_NORMAL
            elif t in ("O", "OUTER"):
                cls._style = actions.HATCH_STYLE_OUTER
            elif t in ("I", "IGNORE"):
                cls._style = actions.HATCH_STYLE_IGNORE
            elif t != "":
                return False
            self._await = None
            self._prompt()
            return True
        if self._await == "color":
            if t in (".", "", "BYLAYER"):
                self.settings["color"] = 256
            else:
                try:
                    aci = int(text)
                except ValueError:
                    return False
                if not 1 <= aci <= 255:
                    return False
                self.settings["color"] = aci
            HatchTool._last = dict(self.settings)
            self._await = None
            self._prompt()
            return True
        if self._await == "retain":
            if t in ("Y", "YES"):
                cls._retain = True
            elif t in ("", "N", "NO"):
                cls._retain = False
            else:
                return False
            self._await = "loop"
            self._loop = []
            self.ctx.prompt(tr("Specify start point:"))
            return True
        if self._await == "loop":
            if t in ("C", "CLOSE") and len(self._loop) >= 3:
                self._close_loop()
                return True
            if t in ("U", "UNDO") and self._loop:
                self._loop.pop()
                return True
            return False
        # main prompt keywords
        if t in ("P", "PROPERTIES"):
            self._await = "pattern"
            self.ctx.prompt(tr(
                "Enter a pattern name or [?/Solid/User defined] <{name}>:",
                name=self.settings["pattern"]))
            return True
        if t in ("S", "SELECT"):
            self.mode = "select"
            self.ctx.prompt(tr("Select boundary objects, Enter to apply:"))
            return True
        if t in ("W", "DRAW"):
            self._await = "retain"
            self.ctx.prompt(tr("Retain polyline boundary? [Yes/No] <N>:"))
            return True
        if t in ("A", "ADVANCED"):
            self._await = "style"
            names = {actions.HATCH_STYLE_NORMAL: "N",
                     actions.HATCH_STYLE_OUTER: "O",
                     actions.HATCH_STYLE_IGNORE: "I"}
            self.ctx.prompt(tr("Enter hatch style [Normal/Outer/Ignore] <{s}>:",
                               s=names[cls._style]))
            return True
        if t == "CO":
            self._await = "color"
            current = self.settings.get("color", 256)
            self.ctx.prompt(tr(
                "New hatch color (ACI 1-255, . = ByLayer) <{c}>:",
                c="ByLayer" if current == 256 else current))
            return True
        return False

    def _on_pattern_name(self, text: str) -> bool:
        t = text.strip()
        if t == "":
            t = self.settings["pattern"]
        upper = t.upper()
        if upper == "?":
            names = actions.hatch_pattern_names()
            self.ctx.echo(", ".join(names))
            self.ctx.prompt(tr(
                "Enter a pattern name or [?/Solid/User defined] <{name}>:",
                name=self.settings["pattern"]))
            return True
        if upper in ("S", "SOLID"):
            self.settings["pattern"] = "SOLID"
            self._user_def = None
            HatchTool._last = dict(self.settings)
            self._await = None
            self._prompt()
            return True
        if upper in ("U", "USER", "USER DEFINED"):
            self._await = "user_angle"
            self.ctx.prompt(tr("Specify angle for crosshatch lines <{a:g}>:",
                               a=type(self)._user[0]))
            return True
        # optional island-style suffix: NAME,N / NAME,O / NAME,I
        name = upper
        if "," in name:
            name, _sep, suffix = name.partition(",")
            styles = {"N": actions.HATCH_STYLE_NORMAL,
                      "O": actions.HATCH_STYLE_OUTER,
                      "I": actions.HATCH_STYLE_IGNORE}
            if suffix.strip() in styles:
                type(self)._style = styles[suffix.strip()]
        if name != "SOLID" and name not in actions._std_patterns():
            self.ctx.echo(tr('Unknown pattern "{name}".', name=name))
            self.ctx.prompt(tr(
                "Enter a pattern name or [?/Solid/User defined] <{name}>:",
                name=self.settings["pattern"]))
            return True
        self.settings["pattern"] = name
        self._user_def = None
        if name == "SOLID":
            HatchTool._last = dict(self.settings)
            self._await = None
            self._prompt()
            return True
        self._await = "scale"
        self.ctx.prompt(tr("Specify a scale for the pattern <{s:g}>:",
                           s=self.settings["scale"]))
        return True

    # -- draW boundary ---------------------------------------------------------
    def _close_loop(self) -> None:
        loop = list(self._loop)
        self._loop = []
        self.outer.append(loop)
        if type(self)._retain:
            self.ctx.execute(actions.add_polyline(loop, closed=True))
        self._await = None
        self.ctx.echo(tr("Boundary found."))
        self._prompt()

    def on_point(self, point) -> None:
        if self._await == "loop":
            self._loop.append(point)
            self.last_point = point
            self.ctx.prompt(tr("Specify next point or [Close/Undo]:"))
            return
        if self._await is not None:
            return
        super().on_point(point)

    def on_enter(self) -> None:
        if self._await == "loop":
            if len(self._loop) >= 3:
                self._close_loop()
            else:
                self._await = None
                self._loop = []
                self._prompt()
            return
        if self._await in ("scale", "angle", "user_angle", "user_spacing",
                           "user_double", "style", "color", "retain",
                           "pattern"):
            self.on_option("")
            return
        # apply with the CLI extras (island style + user-defined pattern)
        boundaries = list(self.selected) + list(self.outer)
        if not boundaries:
            self.ctx.echo(tr("No boundaries picked."))
            self.ctx.finish()
            return
        s = self.settings
        self.ctx.execute(actions.add_hatch(
            boundaries, s["pattern"], s["scale"], s["angle"],
            color=s.get("color", 256), islands=self.islands,
            style=type(self)._style, user_def=self._user_def))
        self.ctx.echo(tr("Hatch created."))
        self.ctx.finish()

    def preview_segments(self, cursor):
        if self._await == "loop" and self._loop:
            segs = list(zip(self._loop, self._loop[1:]))
            segs.append((self._loop[-1], cursor))
            return segs
        return []


BLOCK_TOOL_CLASSES = {
    "BLOCK": BlockTool,
    "INSERT": InsertTool,
    "EXPLODE": ExplodeTool,
    "HATCH": HatchTool,
    "-HATCH": HatchCliTool,
}
