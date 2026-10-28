# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Block attribute tools: ATTDEF / -ATTDEF, EATTEDIT, -ATTEDIT, ATTSYNC,
ATTDISP, and the ATTDIA / ATTREQ system variables.

Prompts follow the AutoCAD Command Reference (ATTDEF p. 163, -ATTDEF p. 167,
ATTDISP p. 170, -ATTEDIT p. 173, EATTEDIT p. 715, ATTSYNC p. 183): the same
words, options and order, so a user coming from AutoCAD types what their
hands already know. BATTMAN is a dialog (views.battman_dialog).
"""
from __future__ import annotations

import math
from typing import Optional

from core import attributes as att
from core.i18n import tr
from tools.base import Point, Tool

#: ACI names -ATTEDIT's Color option accepts besides a number (AutoCAD's
#: seven standard colours and the two logical ones).
COLOR_NAMES = {"RED": 1, "YELLOW": 2, "GREEN": 3, "CYAN": 4, "BLUE": 5,
               "MAGENTA": 6, "WHITE": 7, "BYLAYER": 256, "BYBLOCK": 0}

JUSTIFY_KEYS = {
    "L": "LEFT", "LEFT": "LEFT", "C": "CENTER", "CENTER": "CENTER",
    "R": "RIGHT", "RIGHT": "RIGHT", "A": "ALIGNED", "ALIGN": "ALIGNED",
    "M": "MIDDLE", "MIDDLE": "MIDDLE", "F": "FIT", "FIT": "FIT",
    "TL": "TOP_LEFT", "TC": "TOP_CENTER", "TR": "TOP_RIGHT",
    "ML": "MIDDLE_LEFT", "MC": "MIDDLE_CENTER", "MR": "MIDDLE_RIGHT",
    "BL": "BOTTOM_LEFT", "BC": "BOTTOM_CENTER", "BR": "BOTTOM_RIGHT",
}


def _document(tool: Tool):
    services = tool.ctx.services
    window = getattr(services, "window", None) if services else None
    document = getattr(window, "document", None)
    if document is None:
        document = getattr(services, "document", None)
    return document


def _window(tool: Tool):
    services = tool.ctx.services
    return getattr(services, "window", None) if services else None


def parse_color(text: str) -> Optional[int]:
    """An ACI from what the user typed: a number 1-255, a colour name,
    BYLAYER or BYBLOCK. None when it is none of those."""
    t = text.strip().upper()
    if t in COLOR_NAMES:
        return COLOR_NAMES[t]
    try:
        value = int(t)
    except ValueError:
        return None
    return value if 0 <= value <= 256 else None


class _TextPrompts:
    """Mixin: a prompt that takes literal text (a tag, a value) instead of a
    point or option. While it is up, Space inserts a space and no object snap
    keyword is read out of the answer."""

    _text_state: Optional[str] = None

    def _ask(self, state: str, source: str, **kwargs) -> None:
        self._text_state = state
        self.entity_picker = True        # no osnap keywords eaten (END, CEN)
        self.prompt(source, **kwargs)

    def _end_text(self) -> None:
        self._text_state = None
        self.entity_picker = type(self).entity_picker

    def wants_raw_text(self) -> bool:
        return self._text_state is not None


def _remember(tool: Tool, command) -> None:
    """The definition just made: the dialog's "Align below previous"."""
    document = _document(tool)
    entity = getattr(command, "entity", None)
    if document is None or entity is None:
        return
    from views import attdef_dialog

    attdef_dialog.remember_definition(document, entity)


# -- -ATTDEF -------------------------------------------------------------------

class AttDefCliTool(_TextPrompts, Tool):
    """-ATTDEF (p. 167): modes, tag, prompt, default, then TEXT's prompts."""

    #: AFLAGS: the modes persist for the session, as AutoCAD's do.
    mode = att.AttMode()
    #: what the previous ATTDEF used, so the next one starts there
    _last = None    # (height, rotation)

    def start(self) -> None:
        self.name = "-ATTDEF"
        self._mode = type(self).mode
        self._tag = ""
        self._prompt_text = ""
        self._default = ""
        self._insert = None
        self._align = "LEFT"
        self._p2 = None
        self._style = None
        self._height = None
        self._rotation = None
        self._await = None
        self.ctx.echo(tr("Current attribute modes: {modes}",
                         modes=self._mode.line()))
        self._modes_prompt()

    def _modes_prompt(self) -> None:
        self._text_state = None
        self._await = "modes"
        self.prompt("Enter an option to change [Invisible/Constant/Verify/"
                    "Preset/Lock position/Annotative/Multiple lines] <done>:")

    # -- text answers -------------------------------------------------------------
    def on_option(self, text: str) -> bool:
        state = self._text_state
        if state == "tag":
            tag = att.normal_tag(text)
            if not tag or "!" in tag:
                self.ctx.echo(tr("Invalid tag name."))
                self._ask("tag", "Enter attribute tag name:")
                return True
            self._tag = tag
            if self._mode.constant:
                self._ask("value", "Enter attribute value:")
            else:
                self._ask("prompt", "Enter attribute prompt:")
            return True
        if state == "value":
            self._default = text
            self._end_text()
            self._text_prompts()
            return True
        if state == "prompt":
            self._prompt_text = text
            self._ask("default", "Enter default attribute value:")
            return True
        if state == "default":
            self._default = text
            self._end_text()
            self._text_prompts()
            return True
        if state == "style":
            name = text.strip()
            document = _document(self)
            if document is not None and name and name in document.doc.styles:
                self._style = name
            elif name:
                self.ctx.echo(tr("Unknown text style \"{name}\".", name=name))
            self._end_text()
            self._start_prompt()
            return True
        t = self.option(text) or text.strip().upper()
        if self._await == "modes":
            if t in ("A", "ANNOTATIVE"):
                self.ctx.echo(tr("Annotative attributes are not supported "
                                 "yet — the mode stays off."))
                self._modes_prompt()
                return True
            if t in ("M", "MULTIPLE", "MULTIPLE LINES"):
                self.ctx.echo(tr("Multiple-line attributes are not supported "
                                 "yet — the mode stays off."))
                self._modes_prompt()
                return True
            for letter, _field in att.AttMode.LETTERS:
                if t == letter or t.startswith(letter) and len(t) > 1:
                    self._mode = self._mode.toggled(letter)
                    type(self).mode = self._mode
                    self.ctx.echo(tr("Current attribute modes: {modes}",
                                     modes=self._mode.line()))
                    self._modes_prompt()
                    return True
            return False
        if self._await == "start":
            if t in ("J", "JUSTIFY"):
                self._await = "justify"
                self.prompt("Enter an option [Left/Center/Right/Align/Middle/"
                            "Fit/TL/TC/TR/ML/MC/MR/BL/BC/BR] <Left>:")
                return True
            if t in ("S", "STYLE"):
                self._ask("style", "Enter style name or [?] <{s}>:",
                          s=self._style_name())
                return True
            return False
        if self._await == "justify":
            key = JUSTIFY_KEYS.get(t)
            if key is None:
                return False
            self._align = key
            self._start_prompt()
            return True
        if self._await == "height":
            try:
                value = float(text)
            except ValueError:
                return False
            if value <= 0:
                return False
            self._height = value
            self._rotation_prompt()
            return True
        if self._await == "rotation":
            try:
                value = float(text)
            except ValueError:
                return False
            self._rotation = value + self.ucs().degrees   # from the UCS's X
            self._create()
            return True
        return False

    def on_enter(self) -> None:
        state = self._text_state
        if state == "tag":
            self.ctx.echo(tr("Invalid tag name."))
            self._ask("tag", "Enter attribute tag name:")
            return
        if state in ("value", "prompt", "default", "style"):
            self.on_option("")
            return
        if self._await == "modes":
            self._ask("tag", "Enter attribute tag name:")
            return
        if self._await == "justify":
            self._align = "LEFT"
            self._start_prompt()
            return
        if self._await == "height":
            self._height = self._default_height()
            self._rotation_prompt()
            return
        if self._await == "rotation":
            self._rotation = self._default_rotation() + self.ucs().degrees
            self._create()
            return
        self.ctx.finish()

    # -- TEXT-like placement -----------------------------------------------------
    def _style_name(self) -> str:
        document = _document(self)
        if self._style:
            return self._style
        if document is not None:
            return str(document.doc.header.get("$TEXTSTYLE", "Standard"))
        return "Standard"

    def _fixed_height(self) -> float:
        document = _document(self)
        if document is None:
            return 0.0
        name = self._style_name()
        try:
            return float(document.doc.styles.get(name).dxf.height or 0.0)
        except Exception:  # noqa: BLE001 - a style the table lacks
            return 0.0

    def _default_height(self) -> float:
        from tools.draw import TextTool

        last = type(self)._last
        return last[0] if last else TextTool.default_height

    def _default_rotation(self) -> float:
        from tools.draw import TextTool

        last = type(self)._last
        return last[1] if last else TextTool.last_rotation

    def _text_prompts(self) -> None:
        self.ctx.echo(tr('Current text style: "{s}"  Text height: {h:g}',
                         s=self._style_name(),
                         h=self._fixed_height() or self._default_height()))
        self._start_prompt()

    def _start_prompt(self) -> None:
        self._await = "start"
        self.prompt("Specify start point of text or [Justify/Style]:")

    def _rotation_prompt(self) -> None:
        self._await = "rotation"
        self.prompt("Specify rotation angle of text <{r:g}>:",
                    r=self._default_rotation())

    def on_point(self, point: Point) -> None:
        if self._await == "start":
            self._insert = point
            self.last_point = point
            if self._align in ("ALIGNED", "FIT"):
                self._await = "p2"
                self.prompt("Specify second endpoint of text baseline:")
                return
            fixed = self._fixed_height()
            if fixed > 0:
                self._height = fixed
                self._rotation_prompt()
            else:
                self._await = "height"
                self.prompt("Specify height <{h:g}>:", h=self._default_height())
            return
        if self._await == "p2":
            self._p2 = point
            self._rotation = math.degrees(math.atan2(
                point[1] - self._insert[1], point[0] - self._insert[0]))
            if self._align == "FIT":
                self._await = "height"
                self.prompt("Specify height <{h:g}>:", h=self._default_height())
                return
            span = max(math.dist(self._insert, self._p2), 1e-9)
            self._height = span / 4.0
            self._create()
            return
        if self._await == "height":
            # a point: the height is its distance from the start point
            self._height = max(math.dist(self._insert, point), 1e-9)
            self._rotation_prompt()
            return
        if self._await == "rotation":
            self._rotation = math.degrees(math.atan2(
                point[1] - self._insert[1], point[0] - self._insert[0]))
            self._create()

    def _create(self) -> None:
        try:
            command = att.add_attdef(
                self._tag, self._prompt_text, self._default, self._insert,
                self._height, self._rotation or 0.0, self._mode,
                align=self._align, style=self._style, p2=self._p2)
        except ValueError as exc:
            self.ctx.echo(str(exc))
            self.ctx.finish()
            return
        self.ctx.execute(command)
        # the default offered next time is read in the UCS, as typed
        type(self)._last = (self._height,
                            (self._rotation or 0.0) - self.ucs().degrees)
        _remember(self, command)
        self.ctx.finish()

    def preview_segments(self, cursor: Point):
        if self._await in ("p2", "height", "rotation") and self._insert:
            return [(self._insert, cursor)]
        return []


# -- ATTDEF (dialog) ------------------------------------------------------------

class AttDefTool(Tool):
    """ATTDEF (p. 163): the Attribute Definition dialog, then -- with
    "Specify on-screen" ticked -- the start point on the canvas."""

    def start(self) -> None:
        self.name = "ATTDEF"
        self._values = None
        window = _window(self)
        document = _document(self)
        if window is None or document is None:
            self.ctx.finish()
            return
        from views import attdef_dialog

        dialog = attdef_dialog.AttDefDialog(
            window, document, previous=attdef_dialog.last_definition(document))
        if not dialog.exec():
            self.ctx.echo(tr("*Cancel*"))
            self.ctx.finish()
            return
        self._values = dialog.values()
        if self._values.get("align_below") and self._values.get("below") is not None:
            self._create(self._values["below"])
            return
        if self._values.get("on_screen"):
            self.prompt("Specify start point:")
            return
        self._create((self._values["x"], self._values["y"]))

    def on_point(self, point: Point) -> None:
        if self._values is not None:
            self._create(point)

    def _create(self, point) -> None:
        v = self._values
        try:
            command = att.add_attdef(
                v["tag"], v["prompt"], v["default"], point, v["height"],
                v["rotation"], v["mode"], align=v.get("align", "LEFT"),
                style=v.get("style"))
        except ValueError as exc:
            self.ctx.echo(str(exc))
            self.ctx.finish()
            return
        self.ctx.execute(command)
        AttDefCliTool.mode = v["mode"]
        AttDefCliTool._last = (v["height"], v["rotation"])
        _remember(self, command)
        self.ctx.finish()


# -- EATTEDIT -------------------------------------------------------------------

class EattEditTool(Tool):
    """EATTEDIT (p. 715): "Select a block:", then the Enhanced Attribute
    Editor for that reference. The double-click on a reference with
    attributes lands here too."""

    entity_picker = True

    def start(self) -> None:
        self.name = "EATTEDIT"
        self.prompt("Select a block:")

    def on_point(self, point: Point) -> None:
        services = self.ctx.services
        entity = services.pick_entity(point) if services else None
        if entity is None or entity.dxftype() != "INSERT":
            self.ctx.echo(tr("That object is not a block."))
            if entity is not None and entity.dxftype() == "ATTDEF":
                # Rafael picked his loose definition here and found no way
                # to edit it (#88): say where that is done
                self.ctx.echo(tr("An attribute definition is edited with a "
                                 "double-click (DDEDIT); its values, once the "
                                 "block is inserted."))
            self.prompt("Select a block:")
            return
        if not entity.attribs:
            self.ctx.echo(tr("That block has no attributes."))
            self.prompt("Select a block:")
            return
        edit_attributes_of(self, entity)
        self.ctx.finish()


def edit_attributes_of(tool: Tool, insert) -> bool:
    """Open the Enhanced Attribute Editor on ``insert`` and apply what the
    user changed as one undoable ATTEDIT. True when the dialog ran."""
    window = _window(tool)
    if window is None:
        return False
    from views import attribute_dialogs

    dialog = attribute_dialogs.EnhancedAttributeEditor(window, insert)
    if not dialog.exec():
        return True
    changes = dialog.changes()
    if changes:
        tool.ctx.execute(att.EditAttribsCommand(changes))
    return True


# -- -ATTEDIT -------------------------------------------------------------------

class AttEditCliTool(_TextPrompts, Tool):
    """-ATTEDIT (p. 173): one at a time (Value/Position/Height/Angle/Style/
    Layer/Color/Next on each attribute) or global (one string replaced in
    every matching value)."""

    entity_picker = True

    def start(self) -> None:
        self.name = "-ATTEDIT"
        self._one = True
        self._visible_only = True
        self._specs = ["*", "*", "*"]
        self._inserts: list = []
        self._attribs: list = []
        self._index = 0
        self._await = "one"
        self._pending = None
        self.prompt("Edit attributes one at a time? [Yes/No] <Y>:")

    # -- flow ---------------------------------------------------------------------
    def _current(self):
        if 0 <= self._index < len(self._attribs):
            return self._attribs[self._index]
        return None

    def _menu(self) -> None:
        attrib = self._current()
        if attrib is None:
            self.ctx.finish()
            return
        self._end_text()
        self._await = "menu"
        self.ctx.echo(tr("Attribute {tag} = \"{value}\"",
                         tag=attrib.dxf.tag, value=attrib.dxf.text))
        self.prompt("Enter an option [Value/Position/Height/Angle/Style/"
                    "Layer/Color/Next] <N>:")

    def _next(self) -> None:
        self._index += 1
        if self._index >= len(self._attribs):
            self.ctx.finish()
            return
        self._menu()

    def _apply(self, prop: str, value) -> None:
        attrib = self._current()
        if attrib is not None:
            self.ctx.execute(att.EditAttribsCommand([(attrib, prop, value)]))
        self._menu()

    def _specs_prompts(self) -> None:
        self._ask("spec_block", "Enter block name specification <*>:")

    def _select_prompt(self) -> None:
        self._end_text()
        self._await = "select"
        self.prompt("Select Attributes:")

    def _collect(self) -> None:
        self._attribs = att.attribs_matching(
            self._inserts, *self._specs, visible_only=self._visible_only)
        self.ctx.echo(tr("{n} attributes selected.", n=len(self._attribs)))
        if not self._attribs:
            self.ctx.finish()
            return
        if self._one:
            self._index = 0
            self._menu()
        else:
            self._ask("g_old", "Enter string to change:")

    # -- answers --------------------------------------------------------------------
    def on_option(self, text: str) -> bool:
        state = self._text_state
        if state == "spec_block":
            self._specs[0] = text.strip() or "*"
            self._ask("spec_tag", "Enter attribute tag specification <*>:")
            return True
        if state == "spec_tag":
            self._specs[1] = text.strip() or "*"
            self._ask("spec_value", "Enter attribute value specification <*>:")
            return True
        if state == "spec_value":
            self._specs[2] = text.strip() or "*"
            self._select_prompt()
            return True
        if state == "v_new":
            self._apply("text", text)
            return True
        if state == "v_old":
            self._pending = text
            self._ask("v_change_new", "Enter new string:")
            return True
        if state == "v_change_new":
            attrib = self._current()
            if attrib is not None:
                old = str(attrib.dxf.text or "")
                self._apply("text", old.replace(self._pending or "", text, 1)
                            if self._pending else text + old)
            return True
        if state == "g_old":
            self._pending = text
            self._ask("g_new", "Enter new string:")
            return True
        if state == "g_new":
            changes = []
            for attrib in self._attribs:
                old = str(attrib.dxf.text or "")
                new = old.replace(self._pending, text) if self._pending \
                    else text + old
                if new != old:
                    changes.append((attrib, "text", new))
            if changes:
                self.ctx.execute(att.EditAttribsCommand(changes))
            self.ctx.echo(tr("{n} attributes changed.", n=len(changes)))
            self.ctx.finish()
            return True
        if state == "style":
            name = text.strip()
            document = _document(self)
            if document is not None and name in document.doc.styles:
                self._apply("style", name)
            else:
                self.ctx.echo(tr("Unknown text style \"{name}\".", name=name))
                self._menu()
            return True
        if state == "layer":
            name = text.strip()
            document = _document(self)
            if document is not None and name in document.doc.layers:
                self._apply("layer", name)
            else:
                self.ctx.echo(tr("Unknown layer \"{name}\".", name=name))
                self._menu()
            return True
        if state == "color":
            aci = parse_color(text)
            if aci is None:
                self.ctx.echo(tr("Invalid color."))
                self._menu()
            else:
                self._apply("color", aci)
            return True
        t = self.option(text) or text.strip().upper()
        if self._await == "one":
            if t in ("Y", "YES"):
                self._one = True
                self._specs_prompts()
                return True
            if t in ("N", "NO"):
                self._one = False
                self.ctx.echo(tr("Performing global editing of attribute "
                                 "values."))
                self._await = "visible"
                self.prompt("Edit only attributes visible on screen? "
                            "[Yes/No] <Y>:")
                return True
            return False
        if self._await == "visible":
            if t in ("Y", "YES"):
                self._visible_only = True
            elif t in ("N", "NO"):
                self._visible_only = False
            else:
                return False
            self._specs_prompts()
            return True
        if self._await == "menu":
            attrib = self._current()
            if t in ("V", "VALUE"):
                self._await = "v_kind"
                self.prompt("Enter type of value modification "
                            "[Change/Replace] <R>:")
                return True
            if t in ("P", "POSITION"):
                self._await = "position"
                self.prompt("Specify new text insertion point:")
                return True
            if t in ("H", "HEIGHT"):
                self._await = "height"
                self.prompt("Specify new height <{h:g}>:",
                            h=float(attrib.dxf.height))
                return True
            if t in ("A", "ANGLE"):
                self._await = "angle"
                self.prompt("Specify new rotation angle <{r:g}>:",
                            r=float(attrib.dxf.get("rotation", 0.0)))
                return True
            if t in ("S", "STYLE"):
                self._ask("style", "Enter new text style <{s}>:",
                          s=attrib.dxf.get("style", "Standard"))
                return True
            if t in ("L", "LAYER"):
                self._ask("layer", "Enter new layer name <{l}>:",
                          l=attrib.dxf.layer)
                return True
            if t in ("C", "COLOR"):
                current = attrib.dxf.get("color", 256)
                self._ask("color", "Enter new color <{c}>:",
                          c="BYLAYER" if current == 256 else current)
                return True
            if t in ("N", "NEXT"):
                self._next()
                return True
            return False
        if self._await == "v_kind":
            if t in ("R", "REPLACE"):
                self._ask("v_new", "Enter new attribute value:")
                return True
            if t in ("C", "CHANGE"):
                self._ask("v_old", "Enter string to change:")
                return True
            return False
        if self._await == "height":
            try:
                value = float(text)
            except ValueError:
                return False
            if value <= 0:
                return False
            self._apply("height", value)
            return True
        if self._await == "angle":
            try:
                value = float(text)
            except ValueError:
                return False
            self._apply("rotation", value)
            return True
        return False

    def on_point(self, point: Point) -> None:
        if self._await == "select":
            services = self.ctx.services
            entity = services.pick_entity(point) if services else None
            if entity is not None and entity.dxftype() == "INSERT" \
                    and entity not in self._inserts:
                self._inserts.append(entity)
                self.ctx.echo(tr("1 found"))
            return
        attrib = self._current()
        if attrib is None:
            return
        if self._await == "position":
            self._apply("insert", point)
            return
        if self._await == "height":
            start = attrib.dxf.insert
            self._apply("height", max(math.dist((start.x, start.y), point),
                                      1e-9))
            return
        if self._await == "angle":
            start = attrib.dxf.insert
            self._apply("rotation", math.degrees(math.atan2(
                point[1] - start.y, point[0] - start.x)))

    def on_enter(self) -> None:
        state = self._text_state
        if state in ("spec_block", "spec_tag", "spec_value"):
            self.on_option("")
            return
        if state in ("v_new", "v_old", "v_change_new", "g_old", "g_new"):
            self.on_option("")
            return
        if state in ("style", "layer", "color"):
            self._menu()
            return
        if self._await == "one":
            self.on_option("Y")
            return
        if self._await == "visible":
            self.on_option("Y")
            return
        if self._await == "select":
            self._collect()
            return
        if self._await == "menu":
            self._next()
            return
        if self._await == "v_kind":
            self.on_option("R")
            return
        if self._await in ("height", "angle", "position"):
            self._menu()
            return
        self.ctx.finish()


# -- ATTSYNC ----------------------------------------------------------------------

class AttSyncTool(_TextPrompts, Tool):
    """ATTSYNC (p. 183): "Enter an option [?/Name/Select] <Select>:", then the
    block, then the confirmation, then every reference updated."""

    entity_picker = True

    def start(self) -> None:
        self.name = "ATTSYNC"
        self._block = None
        self._await = "option"
        self.prompt("Enter an option [?/Name/Select] <Select>:")

    def _confirm(self, name: str) -> None:
        document = _document(self)
        if document is None or name not in document.doc.blocks:
            self.ctx.echo(tr("Block \"{name}\" not found.", name=name))
            self.ctx.finish()
            return
        if not att.attdefs_of(document.doc, name):
            self.ctx.echo(tr("Block \"{name}\" has no attribute definitions.",
                             name=name))
            self.ctx.finish()
            return
        self._block = name
        self._end_text()
        self._await = "confirm"
        self.prompt("ATTSYNC block {name}? [Yes/No] <Yes>:", name=name)

    def on_option(self, text: str) -> bool:
        if self._text_state == "name":
            name = text.strip()
            if name == "?":
                self._list()
                self._ask("name", "Enter name of block to sync or [?]:")
                return True
            self._confirm(name)
            return True
        t = self.option(text) or text.strip().upper()
        if self._await == "option":
            if t == "?":
                self._list()
                self.prompt("Enter an option [?/Name/Select] <Select>:")
                return True
            if t in ("N", "NAME"):
                self._ask("name", "Enter name of block to sync or [?]:")
                return True
            if t in ("S", "SELECT"):
                self._await = "select"
                self.prompt("Select a block:")
                return True
            return False
        if self._await == "confirm":
            if t in ("Y", "YES"):
                self._run()
                return True
            if t in ("N", "NO"):
                self.ctx.finish()
                return True
        return False

    def _list(self) -> None:
        document = _document(self)
        names = att.blocks_with_attributes(document.doc) if document else []
        self.ctx.echo(tr("Blocks with attributes: {names}",
                         names=", ".join(names)) if names
                      else tr("No blocks with attributes."))

    def on_point(self, point: Point) -> None:
        if self._await != "select":
            return
        services = self.ctx.services
        entity = services.pick_entity(point) if services else None
        if entity is None or entity.dxftype() != "INSERT":
            self.ctx.echo(tr("That object is not a block."))
            self.prompt("Select a block:")
            return
        self._confirm(str(entity.dxf.name))

    def on_enter(self) -> None:
        if self._text_state == "name":
            self._ask("name", "Enter name of block to sync or [?]:")
            return
        if self._await == "option":
            self.on_option("S")
            return
        if self._await == "confirm":
            self._run()
            return
        self.ctx.finish()

    def _run(self) -> None:
        document = _document(self)
        command = att.SyncAttribsCommand(document, self._block)
        self.ctx.execute(command)
        self.ctx.echo(tr("ATTSYNC complete: {n} reference(s) of \"{name}\" "
                         "updated.", n=len(command.inserts), name=self._block))
        self.ctx.finish()


# -- ATTDISP and the system variables ------------------------------------------

class AttDispTool(Tool):
    """ATTDISP (p. 170): "Enter attribute visibility setting [Normal/ON/OFF]
    <current>:" -- stored in $ATTMODE, undoable, regenerates."""

    def start(self) -> None:
        self.name = "ATTDISP"
        document = _document(self)
        current = att.attmode(document.doc) if document else att.ATTMODE_NORMAL
        self._current = {att.ATTMODE_OFF: "OFF", att.ATTMODE_NORMAL: "Normal",
                         att.ATTMODE_ON: "ON"}[current]
        self.prompt("Enter attribute visibility setting [Normal/ON/OFF] "
                    "<{current}>:", current=self._current)

    def on_option(self, text: str) -> bool:
        t = self.option(text) or text.strip().upper()
        values = {"N": att.ATTMODE_NORMAL, "NORMAL": att.ATTMODE_NORMAL,
                  "ON": att.ATTMODE_ON, "OFF": att.ATTMODE_OFF}
        if t not in values:
            return False
        self.ctx.execute(att.set_attmode(values[t]))
        self.ctx.finish()
        return True

    def on_enter(self) -> None:
        self.ctx.finish()


class _SysVarTool(Tool):
    """A 0/1 system variable kept in the settings: ATTDIA, ATTREQ."""

    key = ""
    default = 0

    @classmethod
    def value(cls) -> int:
        from core.prefs import int_pref

        return int_pref(cls.key, cls.default, 0, 1)

    def start(self) -> None:
        self.name = self.key
        self.prompt("Enter new value for {name} <{v}>:", name=self.key,
                    v=self.value())

    def on_option(self, text: str) -> bool:
        try:
            value = int(text)
        except ValueError:
            return False
        if value not in (0, 1):
            self.ctx.echo(tr("Requires an integer between 0 and 1."))
            self.prompt("Enter new value for {name} <{v}>:", name=self.key,
                        v=self.value())
            return True
        try:
            from PySide6.QtCore import QSettings

            QSettings().setValue(self.key, value)
        except Exception:  # noqa: BLE001 - headless: nothing to keep it in
            pass
        self.ctx.finish()
        return True

    def on_enter(self) -> None:
        self.ctx.finish()


class AttDiaTool(_SysVarTool):
    """ATTDIA: 1 = a dialog asks the attribute values at INSERT, 0 = the
    command line does (AutoCAD's default is 1; IngeCAD's is 0 because its
    thesis is the command line)."""

    key = "ATTDIA"
    default = 0


class AttReqTool(_SysVarTool):
    """ATTREQ: 0 = INSERT takes every default without asking."""

    key = "ATTREQ"
    default = 1


ATTRIBUTE_TOOL_CLASSES = {
    "ATTDEF": AttDefTool,
    "-ATTDEF": AttDefCliTool,
    "EATTEDIT": EattEditTool,
    "ATTEDIT": EattEditTool,          # the dialog form, as AutoCAD 2010+
    "-ATTEDIT": AttEditCliTool,
    "ATTSYNC": AttSyncTool,
    "ATTDISP": AttDispTool,
    "ATTDIA": AttDiaTool,
    "ATTREQ": AttReqTool,
}
