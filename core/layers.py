# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Layer state and operations, AutoCAD/BricsCAD semantics.

The current layer is where new entities land. Layer 0 is the special base
layer (cannot be renamed or deleted). Standard states: on/off, freeze/thaw,
lock/unlock, plus color and linetype. Everything routes through ezdxf's
layer table so the round-trip stays conservative.

Layer edits go through Commands (undoable), except selecting the current
layer, which is view state, not a document mutation.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.commands import Command
from core.i18n import tr


# Standard AutoCAD lineweights, hundredths of a millimetre. -3 = Default
# (uses the drawing's default weight), -1 = ByLayer (not valid on a layer).
LINEWEIGHTS = [-3, 0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70,
               80, 90, 100, 106, 120, 140, 158, 200, 211]


def lineweight_label(value: int) -> str:
    if value == -3:
        return "Default"
    if value == -2:
        return "ByBlock"
    if value == -1:
        return "ByLayer"
    return f"{value / 100:.2f} mm"


@dataclass
class LayerInfo:
    name: str
    color: int          # ACI (AutoCAD Color Index)
    linetype: str
    lineweight: int     # hundredths of mm, or -3 Default
    is_on: bool
    is_frozen: bool
    is_locked: bool
    is_current: bool
    plot: bool = True           # no-plot layers still display (official)
    description: str = ""
    in_use: bool = False        # any entity anywhere references it


def layers_in_use(document) -> set[str]:
    """Layer names referenced by any entity — every layout AND every block
    definition (AutoCAD's delete guard counts those as referenced too)."""
    from ezdxf.entities import DXFGraphic

    used: set[str] = set()
    for e in document.doc.entitydb.values():
        if e.is_alive and isinstance(e, DXFGraphic):
            name = e.dxf.get("layer", None)
            if name:
                used.add(name)
    return used


def layer_list(document) -> list[LayerInfo]:
    """Snapshot of all layers, layer 0 first then alphabetical."""
    current = current_layer_name(document)
    used = layers_in_use(document)
    infos = []
    for layer in document.doc.layers:
        infos.append(LayerInfo(
            name=layer.dxf.name,
            color=abs(layer.dxf.color),      # negative color = layer off
            linetype=layer.dxf.linetype,
            lineweight=layer.dxf.get("lineweight", -3),
            is_on=layer.is_on(),
            is_frozen=layer.is_frozen(),
            is_locked=layer.is_locked(),
            is_current=(layer.dxf.name == current),
            plot=bool(layer.dxf.get("plot", 1)),
            description=layer.description,
            in_use=layer.dxf.name in used,
        ))
    infos.sort(key=lambda i: (i.name != "0", i.name.lower()))
    return infos


def available_linetypes(document) -> list[str]:
    """Linetype names loaded in the document (Continuous always first)."""
    names = [lt.dxf.name for lt in document.doc.linetypes
             if lt.dxf.name not in ("ByBlock", "ByLayer")]
    names.sort(key=lambda n: (n != "Continuous", n.lower()))
    return names


def current_layer_name(document) -> str:
    return document.doc.header.get("$CLAYER", "0")


def set_current_layer(document, name: str) -> None:
    if name in document.doc.layers:
        document.doc.header["$CLAYER"] = name


def unique_layer_name(document, base: str = tr("Layer")) -> str:
    existing = {layer.dxf.name for layer in document.doc.layers}
    i = 1
    while f"{base}{i}" in existing:
        i += 1
    return f"{base}{i}"


# -- commands ------------------------------------------------------------------

class NewLayerCommand(Command):
    """Create a layer. The panel passes the SELECTED layer's properties so
    the new one inherits them (official New Layer behavior)."""

    name = "new layer"

    def __init__(self, layer_name: str, color: int = 7,
                 linetype: str = "Continuous", lineweight: int = -3) -> None:
        self.layer_name = layer_name
        self.color = color
        self.linetype = linetype
        self.lineweight = lineweight

    def do(self, document) -> None:
        if self.layer_name not in document.doc.layers:
            document.doc.layers.add(
                self.layer_name, color=self.color, linetype=self.linetype,
                lineweight=self.lineweight)
        document.dirty = True

    def undo(self, document) -> None:
        if self.layer_name in document.doc.layers:
            document.doc.layers.remove(self.layer_name)
        document.dirty = True


class DeleteLayerCommand(Command):
    name = "delete layer"

    def __init__(self, layer_name: str) -> None:
        self.layer_name = layer_name
        self._color = 7
        self._linetype = "Continuous"

    def do(self, document) -> None:
        layer = document.doc.layers.get(self.layer_name)
        self._color = layer.dxf.color
        self._linetype = layer.dxf.linetype
        document.doc.layers.remove(self.layer_name)
        document.dirty = True

    def undo(self, document) -> None:
        layer = document.doc.layers.add(self.layer_name)
        layer.dxf.color = self._color
        layer.dxf.linetype = self._linetype
        document.dirty = True


class RenameLayerCommand(Command):
    name = "rename layer"

    def __init__(self, old_name: str, new_name: str) -> None:
        self.old_name = old_name
        self.new_name = new_name

    def do(self, document) -> None:
        document.doc.layers.get(self.old_name).rename(self.new_name)
        if current_layer_name(document) == self.old_name:
            set_current_layer(document, self.new_name)
        document.dirty = True

    def undo(self, document) -> None:
        document.doc.layers.get(self.new_name).rename(self.old_name)
        if current_layer_name(document) == self.new_name:
            set_current_layer(document, self.old_name)
        document.dirty = True


class LayerPropertyCommand(Command):
    """Set one property (color/linetype/on/frozen/locked) with exact undo."""

    name = "layer property"

    def __init__(self, layer_name: str, prop: str, value) -> None:
        self.layer_name = layer_name
        self.prop = prop
        self.value = value
        self._old = None

    def _apply(self, document, value):
        layer = document.doc.layers.get(self.layer_name)
        if self.prop == "color":
            old = abs(layer.dxf.color)
            layer.color = value          # keeps on/off sign via ezdxf
            return old
        if self.prop == "linetype":
            old = layer.dxf.linetype
            layer.dxf.linetype = value
            return old
        if self.prop == "lineweight":
            old = layer.dxf.get("lineweight", -3)
            layer.dxf.lineweight = value
            return old
        if self.prop == "on":
            old = layer.is_on()
            layer.on() if value else layer.off()
            return old
        if self.prop == "frozen":
            old = layer.is_frozen()
            layer.freeze() if value else layer.thaw()
            return old
        if self.prop == "locked":
            old = layer.is_locked()
            layer.lock() if value else layer.unlock()
            return old
        if self.prop == "plot":
            old = bool(layer.dxf.get("plot", 1))
            layer.dxf.plot = 1 if value else 0
            return old
        if self.prop == "description":
            old = layer.description
            layer.description = value or ""
            return old
        return None

    def do(self, document) -> None:
        self._old = self._apply(document, self.value)
        document.dirty = True

    def undo(self, document) -> None:
        self._apply(document, self._old)
        document.dirty = True


# -- the -LAYER command-line variant (official option set, v0.2 subset) --------

# Accepted spellings per keyword, AutoCAD's capitalization rules
# (Ltype = L, LWeight = LW, LOck = LO, Unlock = U, Description = D).
_LAYER_KEYWORDS = {
    "?": "?",
    "M": "make", "MAKE": "make",
    "S": "set", "SET": "set",
    "N": "new", "NEW": "new",
    "R": "rename", "RENAME": "rename",
    "ON": "on", "OFF": "off",
    "C": "color", "COLOR": "color", "COLOUR": "color",
    "L": "ltype", "LT": "ltype", "LTYPE": "ltype",
    "LW": "lweight", "LWEIGHT": "lweight",
    "P": "plot", "PLOT": "plot",
    "F": "freeze", "FREEZE": "freeze",
    "T": "thaw", "THAW": "thaw",
    "LO": "lock", "LOCK": "lock",
    "U": "unlock", "UNLOCK": "unlock",
    "D": "description", "DESCRIPTION": "description",
}

_COLOR_NAMES = {"RED": 1, "YELLOW": 2, "GREEN": 3, "CYAN": 4, "BLUE": 5,
                "MAGENTA": 6, "WHITE": 7}


def match_layers(document, spec: str) -> list[str]:
    """Resolve an AutoCAD name list: comma-separated, ``*``/``?`` wildcards,
    case-insensitive. Empty spec -> the current layer (the official default)."""
    import fnmatch

    all_names = [layer.dxf.name for layer in document.doc.layers]
    patterns = [p.strip() for p in spec.split(",") if p.strip()]
    if not patterns:
        return [current_layer_name(document)]
    result: list[str] = []
    for pattern in patterns:
        low = pattern.lower()
        hits = [n for n in all_names
                if fnmatch.fnmatchcase(n.lower(), low)]
        for n in hits:
            if n not in result:
                result.append(n)
    return result


def snap_lineweight(value_mm: float) -> int:
    """Invalid lineweights snap to the nearest fixed value (official)."""
    target = value_mm * 100.0
    return min((w for w in LINEWEIGHTS if w >= 0),
               key=lambda w: abs(w - target))


def layer_command(document, history, *, echo, refresh, args=()):
    """The -LAYER command: official keywords and prompt loop.

    ``refresh`` is the UI callback after edits (panel + viewport). Typed
    arguments ("-LA OFF muros") are consumed as answers to the prompts.
    """
    from core.actions import Prompt
    from core.commands import CompositeCommand

    queue = list(args)

    def step(text, handler):
        if queue:
            return handler(queue.pop(0))
        return Prompt(text, handler)

    def execute(commands) -> None:
        commands = [c for c in commands if c is not None]
        if not commands:
            return
        if len(commands) == 1:
            history.execute(commands[0])
        else:
            history.execute(CompositeCommand("LAYER", commands))
        refresh()

    option_text = tr(
        "Enter an option "
        "[?/Make/Set/New/Rename/ON/OFF/Color/Ltype/LWeight/Plot/"
        "Freeze/Thaw/LOck/Unlock/Description]:")

    def loop():
        return step(option_text, on_option)

    def list_layers(_text: str = "") -> None:
        for info in layer_list(document):
            states = []
            states.append(tr("On") if info.is_on else tr("Off"))
            if info.is_frozen:
                states.append(tr("Frozen"))
            if info.is_locked:
                states.append(tr("Locked"))
            echo(f'  "{info.name}"  {"/".join(states)}  '
                 f"{tr('color')} {info.color}  {info.linetype}  "
                 f"{lineweight_label(info.lineweight)}")

    def on_make(text: str):
        name = text.strip()
        if not name:
            return loop()
        if name in document.doc.layers:
            layer = document.doc.layers.get(name)
            if not layer.is_on():
                execute([LayerPropertyCommand(name, "on", True)])
        else:
            execute([NewLayerCommand(name)])
        set_current_layer(document, name)
        refresh()
        return loop()

    def on_set(text: str):
        name = text.strip() or current_layer_name(document)
        if name not in document.doc.layers:
            echo(tr('Cannot find layer "{name}".', name=name))
            return loop()
        layer = document.doc.layers.get(name)
        if layer.is_frozen():
            echo(tr("Cannot make a frozen layer current."))
            return loop()
        if not layer.is_on():
            execute([LayerPropertyCommand(name, "on", True)])
        set_current_layer(document, name)
        refresh()
        return loop()

    def on_new(text: str):
        names = [n.strip() for n in text.split(",") if n.strip()]
        execute([NewLayerCommand(n) for n in names
                 if n not in document.doc.layers])
        return loop()

    def on_rename_old(text: str):
        old = text.strip()
        if old not in document.doc.layers:
            echo(tr('Cannot find layer "{name}".', name=old))
            return loop()
        if old == "0":
            echo(tr("Layer 0 cannot be renamed."))
            return loop()

        def on_rename_new(text2: str):
            new = text2.strip()
            if not new or new == old:
                return loop()
            if new in document.doc.layers:
                echo(tr("Layer {name} already exists.", name=new))
                return loop()
            history.execute(RenameLayerCommand(old, new))
            refresh()
            return loop()
        return step(tr("Enter new layer name:"), on_rename_new)

    def state_setter(prop, value, verbing):
        def on_names(text: str):
            commands = []
            for name in match_layers(document, text):
                if name not in document.doc.layers:
                    echo(tr('Cannot find layer "{name}".', name=name))
                    continue
                if prop == "frozen" and value \
                        and name == current_layer_name(document):
                    echo(tr("Cannot freeze the current layer."))
                    continue
                if prop == "on" and not value \
                        and name == current_layer_name(document):
                    echo(tr("The current layer is now off."))
                commands.append(LayerPropertyCommand(name, prop, value))
            execute(commands)
            return loop()
        return step(tr("Enter name list of layer(s) to {verb} <current>:",
                       verb=verbing), on_names)

    def on_color(text: str):
        raw = text.strip()
        if not raw:
            return loop()
        turn_off = raw.startswith("-")
        if turn_off:
            raw = raw[1:].strip()
        aci = _COLOR_NAMES.get(raw.upper())
        if aci is None:
            try:
                aci = int(raw)
            except ValueError:
                aci = None
        if aci is None or not 1 <= aci <= 255:
            echo(tr("Invalid color."))
            return loop()

        def on_names(text2: str):
            commands = []
            for name in match_layers(document, text2):
                if name not in document.doc.layers:
                    echo(tr('Cannot find layer "{name}".', name=name))
                    continue
                commands.append(LayerPropertyCommand(name, "color", aci))
                if turn_off:
                    commands.append(LayerPropertyCommand(name, "on", False))
            execute(commands)
            return loop()
        return step(
            tr("Enter name list of layer(s) for color {n} <current>:", n=aci),
            on_names)

    def on_ltype(text: str):
        lt = text.strip() or "Continuous"
        real = next((n for n in available_linetypes(document)
                     if n.lower() == lt.lower()), None)
        if real is None:
            echo(tr('Linetype "{name}" is not loaded.', name=lt))
            return loop()

        def on_names(text2: str):
            execute([LayerPropertyCommand(n, "linetype", real)
                     for n in match_layers(document, text2)
                     if n in document.doc.layers])
            return loop()
        return step(
            tr("Enter name list of layer(s) for linetype {lt} <current>:",
               lt=real), on_names)

    def on_lweight(text: str):
        raw = text.strip()
        try:
            weight = -3 if not raw else snap_lineweight(float(raw))
        except ValueError:
            echo(tr("Invalid lineweight."))
            return loop()

        def on_names(text2: str):
            execute([LayerPropertyCommand(n, "lineweight", weight)
                     for n in match_layers(document, text2)
                     if n in document.doc.layers])
            return loop()
        return step(
            tr("Enter name list of layer(s) for lineweight {lw} <current>:",
               lw=lineweight_label(weight)), on_names)

    def on_plot(text: str):
        key = text.strip().upper()
        plot = not (key in ("N", "NO", "NO PLOT", "NOPLOT"))

        def on_names(text2: str):
            execute([LayerPropertyCommand(n, "plot", plot)
                     for n in match_layers(document, text2)
                     if n in document.doc.layers])
            return loop()
        return step(tr("Enter name list of layer(s) <current>:"), on_names)

    def on_description(text: str):
        description = text

        def on_names(text2: str):
            execute([LayerPropertyCommand(n, "description", description)
                     for n in match_layers(document, text2)
                     if n in document.doc.layers])
            return loop()
        return step(tr("Enter name list of layer(s) <current>:"), on_names)

    def on_option(text: str):
        key = text.strip()
        if not key:
            return None                     # Enter exits (official)
        option = _LAYER_KEYWORDS.get(key.upper())
        if option is None:
            echo(tr("Invalid option keyword."))
            return loop()
        if option == "?":
            list_layers()
            return loop()
        if option == "make":
            return step(tr("Enter name for new layer (becomes the current "
                           "layer):"), on_make)
        if option == "set":
            return step(tr("Enter layer name to make current <{name}>:",
                           name=current_layer_name(document)), on_set)
        if option == "new":
            return step(tr("Enter name list for new layer(s):"), on_new)
        if option == "rename":
            return step(tr("Enter layer name to rename:"), on_rename_old)
        if option == "on":
            return state_setter("on", True, tr("turn on"))
        if option == "off":
            return state_setter("on", False, tr("turn off"))
        if option == "freeze":
            return state_setter("frozen", True, tr("freeze"))
        if option == "thaw":
            return state_setter("frozen", False, tr("thaw"))
        if option == "lock":
            return state_setter("locked", True, tr("lock"))
        if option == "unlock":
            return state_setter("locked", False, tr("unlock"))
        if option == "color":
            return step(tr("Enter color name or number (1-255):"), on_color)
        if option == "ltype":
            return step(tr("Enter loaded linetype name <Continuous>:"),
                        on_ltype)
        if option == "lweight":
            return step(tr("Enter lineweight in mm (0.00 - 2.11):"),
                        on_lweight)
        if option == "plot":
            return step(tr("Enter a plotting preference [Plot/No plot] "
                           "<Plot>:"), on_plot)
        if option == "description":
            return step(tr("Enter description for the layer(s):"),
                        on_description)
        return loop()

    echo(tr('Current layer: "{name}"', name=current_layer_name(document)))
    return loop()
