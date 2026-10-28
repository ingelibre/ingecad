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
        self.prompt("Specify insertion base point:")

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
        self._point = None
        self._attdefs = []
        self._values = {}
        self._queue = []
        self._verify_pass = False
        self._text_state = False
        names = self.ctx.services.block_names() if self.ctx.services else []
        # AutoCAD's Insert dialog: the defined blocks, or Browse... for a
        # drawing file (#70: with no block defined there was no way on)
        browse = tr("Browse...")
        chosen = self.ctx.ask_choice(tr("Insert block:"), names + [browse],
                                     names[0] if names else browse)
        if chosen == browse:
            chosen = self._block_from_file()
            if self._await == "redefine":
                return                    # the answer comes first
        if not chosen:
            self.ctx.finish()
            return
        self._block_name = chosen
        self.prompt("Specify insertion point [Scale/Rotate]:")

    def _block_from_file(self) -> str | None:
        """Browse...: define the chosen drawing as a block named after it, or
        or -- asked first -- redefine the block of that name."""
        from pathlib import Path

        pick = getattr(self.ctx.services, "pick_drawing_file", None)
        filename = pick() if callable(pick) else ""
        if not filename:
            return None
        path = Path(filename)
        document = getattr(self.ctx.services, "document", None)
        if document is None:
            document = getattr(getattr(self.ctx.services, "window", None),
                               "document", None)
        name = path.stem
        if document is not None and name in document.doc.blocks:
            # AutoCAD asks before touching a definition every reference
            # shares (Rafael's sixth review: ours inserted the old one
            # without a word, and the edited file never arrived).
            self._redefine = (name, path)
            self._await = "redefine"
            self.entity_picker = True
            self.prompt(self.REDEFINE, name=name)
            return name
        source = self._read(path)
        if source is None:
            return None
        self.ctx.execute(actions.DefineBlockFromFileCommand(name, source))
        return name

    REDEFINE = 'Block "{name}" already exists. Redefine it? [Yes/No] <No>:'

    def _read(self, path):
        from core import xrefs

        try:
            return xrefs.read_drawing(path)
        except Exception as exc:          # noqa: BLE001 - unreadable file
            self.ctx.echo(tr("Cannot read {file}: {error}",
                             file=path.name, error=exc))
            return None

    def _answer_redefine(self, text: str) -> None:
        name, path = self._redefine
        self._await = None
        self.entity_picker = False
        if self.option(text) == "Y":
            source = self._read(path)
            if source is None:
                self.ctx.finish()
                return
            self.ctx.execute(actions.RedefineBlockFromFileCommand(name, source))
            self.ctx.echo(tr("Block {name} redefined.", name=name))
        self._block_name = name
        self.prompt("Specify insertion point [Scale/Rotate]:")

    def on_option(self, text: str) -> bool:
        # The resolver first: it turns the localized keyword, or
        # AutoCAD's _global form, into the English key the
        # branches below have always compared against.
        if self._await == "redefine":
            self._answer_redefine(text)
            return True
        if self._text_state:
            # an attribute value: Enter keeps the default shown
            from core import attributes as att

            attdef = self._queue.pop(0)
            tag = str(attdef.dxf.tag)
            if text != "":
                self._values[tag] = text
            elif tag not in self._values:
                self._values[tag] = att.default_of(attdef)
            self._ask_next()
            return True
        t = self.option(text) or text.strip().upper()
        if self._await is None and t in ("S", "SCALE"):
            self._await = "scale"
            self.prompt("Specify scale factor <{v}>:", v=self._xscale)
            return True
        if self._await is None and t in ("R", "ROTATE"):
            self._await = "rotate"
            self.prompt("Specify rotation angle <{v}>:", v=self._rotation)
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
            self.prompt("Specify insertion point [Scale/Rotate]:")
            return True
        return False

    def on_point(self, point: Point) -> None:
        if self._await is not None:
            return                    # a scale/rotation answer is pending
        if not self._block_name:
            self.ctx.finish()
            return
        if self._point is None:
            self._point = point
            if self._begin_attributes():
                return                # the values come first (AutoCAD)
        self._insert()

    # -- attribute values ------------------------------------------------------
    # AutoCAD asks for every non-constant attribute of the block right after
    # the insertion point: on the command line ("Enter attribute values",
    # each definition's prompt with its default) when ATTDIA is 0, in the Edit
    # Attributes dialog when it is 1; ATTREQ 0 takes every default; a Preset
    # definition never asks; a Verify definition is asked twice.
    _point = None
    _attdefs: list = []
    _values: dict = {}
    _queue: list = []
    _verify_pass = False
    _text_state = False

    def _document(self):
        services = self.ctx.services
        window = getattr(services, "window", None) if services else None
        return getattr(window, "document", None) or \
            getattr(services, "document", None)

    def _begin_attributes(self) -> bool:
        from core import attributes as att
        from tools.attributes import AttDiaTool, AttReqTool

        document = self._document()
        if document is None:
            return False
        self._attdefs = att.prompted_attdefs(document.doc, self._block_name)
        self._values = {}
        if not self._attdefs or AttReqTool.value() == 0:
            return False
        asked = [a for a in self._attdefs if not a.is_preset]
        for a in self._attdefs:
            if a.is_preset:
                self._values[str(a.dxf.tag)] = att.default_of(a)
        if not asked:
            return False
        if AttDiaTool.value() == 1:
            window = getattr(self.ctx.services, "window", None)
            if window is not None:
                from views import attribute_dialogs

                dialog = attribute_dialogs.InsertAttributesDialog(
                    window, self._block_name, asked)
                if not dialog.exec():
                    self.ctx.echo(tr("*Cancel*"))
                    self.ctx.finish()
                    return True
                self._values.update(dialog.values())
                return False
        self.ctx.echo(tr("Enter attribute values"))
        self._queue = list(asked)
        self._verify_pass = False
        self._ask_next()
        return True

    def _ask_next(self) -> None:
        from core import attributes as att

        if not self._queue:
            if not self._verify_pass:
                verify = [a for a in self._attdefs if a.is_verify]
                if verify:
                    self._verify_pass = True
                    self.ctx.echo(tr("Verify attribute values"))
                    self._queue = verify
                    self._ask_next()
                    return
            self._text_state = False
            self.entity_picker = False
            self._insert()
            return
        attdef = self._queue[0]
        tag = str(attdef.dxf.tag)
        default = self._values.get(tag, att.default_of(attdef))
        self._text_state = True
        self.entity_picker = True     # no osnap keyword read out of a value
        self.prompt("{prompt} <{default}>:", prompt=att.prompt_of(attdef),
                    default=default)

    def wants_raw_text(self) -> bool:
        return bool(self._text_state)

    def on_enter(self) -> None:
        if self._await == "redefine":
            self._answer_redefine("")     # <No>: the drawing's own block
            return
        if self._text_state:
            self.on_option("")
            return
        self.ctx.finish()

    def _insert(self) -> None:
        from core import attributes as att

        # the rotation is measured from the UCS's X, as AutoCAD's (#91)
        rotation = self._rotation + self.ucs().degrees
        if self._attdefs:
            command = att.insert_block_with_attribs(
                self._block_name, self._point, self._xscale, self._xscale,
                rotation, self._values)
        else:
            command = actions.insert_block(
                self._block_name, self._point, self._xscale, self._xscale,
                rotation)
        self.ctx.execute(command)
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

    def _world_angle(self, angle: float) -> float:
        """The pattern angle is measured from the UCS's X (#91)."""
        return float(angle) + self.ucs().degrees
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
        self.prompt(
            "Pick internal point or [Select objects/seTtings], Enter to apply:")

    def on_option(self, text: str) -> bool:
        # The resolver first: it turns the localized keyword, or
        # AutoCAD's _global form, into the English key the
        # branches below have always compared against.
        t = self.option(text) or text.strip().upper()
        if t in ("S", "SELECT"):
            self.mode = "select"
            self.prompt("Select boundary objects, Enter to apply:")
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
            boundaries, s["pattern"], s["scale"], self._world_angle(s["angle"]),
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
        self.prompt(
            "Specify internal point or [Properties/Select objects/"
            "draW boundary/Advanced/hatch COlor]:")

    # -- option flows ----------------------------------------------------------
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
            self.prompt("Specify an angle for the pattern <{a:g}>:",
                        a=self.settings["angle"])
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
            self.prompt("Specify spacing between the lines <{s:g}>:",
                        s=cls._user[1])
            return True
        if self._await == "user_spacing":
            if text == "":
                value = cls._user[1]
            if value is None or value <= 0:
                return False
            self._pending["us"] = value
            self._await = "user_double"
            self.prompt("Double hatch area? [Yes/No] <N>:")
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
            self.prompt("Specify start point:")
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
            self.prompt(
                "Enter a pattern name or [?/Solid/User defined] <{name}>:",
                name=self.settings["pattern"])
            return True
        if t in ("S", "SELECT"):
            self.mode = "select"
            self.prompt("Select boundary objects, Enter to apply:")
            return True
        if t in ("W", "DRAW"):
            self._await = "retain"
            self.prompt("Retain polyline boundary? [Yes/No] <N>:")
            return True
        if t in ("A", "ADVANCED"):
            self._await = "style"
            names = {actions.HATCH_STYLE_NORMAL: "N",
                     actions.HATCH_STYLE_OUTER: "O",
                     actions.HATCH_STYLE_IGNORE: "I"}
            self.prompt("Enter hatch style [Normal/Outer/Ignore] <{s}>:",
                        s=names[cls._style])
            return True
        if t == "CO":
            self._await = "color"
            current = self.settings.get("color", 256)
            self.prompt(
                "New hatch color (ACI 1-255, . = ByLayer) <{c}>:",
                c="ByLayer" if current == 256 else current)
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
            self.prompt(
                "Enter a pattern name or [?/Solid/User defined] <{name}>:",
                name=self.settings["pattern"])
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
            self.prompt("Specify angle for crosshatch lines <{a:g}>:",
                        a=type(self)._user[0])
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
            self.prompt(
                "Enter a pattern name or [?/Solid/User defined] <{name}>:",
                name=self.settings["pattern"])
            return True
        self.settings["pattern"] = name
        self._user_def = None
        if name == "SOLID":
            HatchTool._last = dict(self.settings)
            self._await = None
            self._prompt()
            return True
        self._await = "scale"
        self.prompt("Specify a scale for the pattern <{s:g}>:",
                    s=self.settings["scale"])
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
            self.prompt("Specify next point or [Close/Undo]:")
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
        user_def = self._user_def
        if user_def is not None:
            user_def = (self._world_angle(user_def[0]),) + tuple(user_def[1:])
        self.ctx.execute(actions.add_hatch(
            boundaries, s["pattern"], s["scale"], self._world_angle(s["angle"]),
            color=s.get("color", 256), islands=self.islands,
            style=type(self)._style, user_def=user_def))
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
