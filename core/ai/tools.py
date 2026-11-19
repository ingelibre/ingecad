# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The one catalogue of what an AI may do in IngeCAD.

Both the assistant panel and the MCP bridge read this table and call
:func:`call`; neither has tools of its own (one question, one place).

Every tool works on the window that hosts it -- the same ``host`` an
APPLOAD script gets (core.scripting): ``host.document``, ``host.history``,
``host.tools._execute`` for Commands, ``host._on_command_submitted`` for
what the command line already does well (U, REDO, ZOOM), and
``host.command_line.echo``. So:

* every change is a Command, undoable like the keyboard's, and each tool
  that runs is echoed to the command history (``AI: draw_line``);
* :class:`Turn` folds what one AI turn did into ONE undo step;
* a change may name the ``expected_revision`` it was planned on: if the
  drawing moved since, it is refused rather than applied to the wrong
  thing (an idea of PR #59);
* what cannot be taken back with U -- writing a file over another, erasing
  a large selection -- needs the user's yes (``confirm``). A drawing from
  someone else can carry a text that says "erase everything"; the model
  may believe it, the user decides.

Coordinates are world (WCS) drawing units, angles degrees counter-clockwise
from +X, colours AutoCAD Color Index (1 red ... 7 white/black, 256 ByLayer).
"""
from __future__ import annotations

import base64
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

#: The most entities one query hands back; the model asks again, narrower.
QUERY_LIMIT = 500
#: Erasing more than this many entities in one call asks the user first.
ERASE_CONFIRM_ABOVE = 25
#: The most vertices of one polyline a description lists.
VERTEX_LIMIT = 100


class ToolError(Exception):
    """A call that cannot be done; its text goes back to the model."""


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict                     # JSON Schema of the arguments
    handler: Callable[..., Any]          # handler(host, **args) -> result
    mutates: bool = False
    #: confirm_text(host, args) -> None, or the question to ask the user
    confirm_text: Optional[Callable[..., Optional[str]]] = None


@dataclass
class Image:
    """A tool result that is a picture (capture_view)."""

    png: bytes
    note: str = ""

    def base64(self) -> str:
        return base64.b64encode(self.png).decode("ascii")


TOOLS: dict[str, Tool] = {}


def _tool(name, description, properties=None, required=(), *, mutates=False,
          confirm_text=None):
    """Register ``handler`` under ``name`` with a JSON Schema built from
    ``properties``."""
    properties = dict(properties or {})
    if mutates:
        properties["expected_revision"] = {
            "type": "integer",
            "description": "The drawing revision this change was planned on "
                           "(every result reports the current one). If the "
                           "drawing changed since, the call is refused.",
        }
    schema = {"type": "object", "properties": properties,
              "required": list(required), "additionalProperties": False}

    def register(handler):
        TOOLS[name] = Tool(name, description, schema, handler, mutates,
                           confirm_text)
        return handler
    return register


# -- schema pieces ---------------------------------------------------------------

POINT = {"type": "array", "items": {"type": "number"}, "minItems": 2,
         "maxItems": 3, "description": "[x, y] in drawing units"}
HANDLES = {"type": "array", "items": {"type": "string"}, "minItems": 1,
           "description": "Entity handles, as query_entities reports them"}
COLOR = {"type": "integer", "minimum": 1, "maximum": 256,
         "description": "AutoCAD Color Index; 256 = ByLayer"}


# -- calling -------------------------------------------------------------------------

def call(host, name: str, args: Optional[dict] = None,
         confirm: Optional[Callable[[str], bool]] = None):
    """Run tool ``name`` with ``args`` on ``host``.

    Returns the tool's result: a dict (always with the drawing's
    ``revision``) or an :class:`Image`. A call that cannot be done returns
    ``{"error": ...}`` -- the model reads it and tries something else; it
    never raises. ``confirm(question)`` asks the user; without it, a call
    that needs a yes is refused.
    """
    from core.i18n import tr

    tool = TOOLS.get(name)
    if tool is None:
        return {"error": f"unknown tool {name!r}"}
    args = dict(args or {})
    document = getattr(host, "document", None)
    if document is None:
        return {"error": "no drawing is open"}
    try:
        expected = args.pop("expected_revision", None)
        if tool.mutates and expected is not None \
                and int(expected) != document.revision:
            raise ToolError(
                f"the drawing changed since revision {expected} (it is "
                f"{document.revision} now): read it again before changing it")
        if tool.confirm_text is not None:
            question = tool.confirm_text(host, args)
            if question and (confirm is None or not confirm(question)):
                raise ToolError("the user declined: " + question)
        host.command_line.echo(tr("AI: {tool}", tool=name))
        result = tool.handler(host, **args)
    except ToolError as exc:
        return {"error": str(exc), "revision": document.revision}
    except TypeError as exc:                 # arguments the schema refuses
        return {"error": f"bad arguments for {name}: {exc}",
                "revision": document.revision}
    if isinstance(result, Image):
        return result
    result = dict(result or {})
    result["revision"] = host.document.revision
    return result


class Turn:
    """One turn of the assistant: whatever its tools change is ONE undo
    step called "AI", as an APPLOAD script is.

    with Turn(host):
        call(host, "draw_line", ...)
        call(host, "draw_circle", ...)
    """

    def __init__(self, host, name: str = "AI") -> None:
        self.host = host
        self.name = name
        self._since = 0

    def __enter__(self) -> "Turn":
        self._since = len(self.host.history._undo)
        return self

    def __exit__(self, *exc) -> None:
        history = self.host.history
        # an undo inside the turn may have taken the stack below the start
        self.host.history.fold(min(self._since, len(history._undo)), self.name)
        changed = getattr(getattr(self.host, "tools", None), "changed", None)
        if changed is not None:
            changed.emit()


# -- plugins' tools (PluginSpec.ai_tools, plugin contract level 3) -------------

#: owner -> [names, activation count]: a plugin is activated once per window
#: and the catalogue is one per process, as the reactors are.
_PLUGIN_TOOLS: dict[str, list] = {}


def register_plugin_tools(owner: str, tools) -> None:
    """Add a plugin's tools (core.plugins.AiTool) to the catalogue, for the
    in-app assistant and for MCP alike.

    Each name must start with ``<owner>_`` -- a model sees one flat list,
    and the prefix says whose tool it is -- use lowercase letters, digits
    and underscores (what every MCP client accepts) and not exist yet. The
    handler receives a PluginContext, never the window; a tool that
    ``mutates`` gets ``expected_revision`` and runs inside the assistant's
    single undo step like the core's own."""
    import re

    entry = _PLUGIN_TOOLS.get(owner)
    if entry is not None:
        entry[1] += 1
        return
    names = []
    for tool in tools:
        name = tool.name
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name) \
                or not name.startswith(owner.lower() + "_"):
            raise ValueError(f"AI tool {name!r} must be lowercase and start "
                             f"with {owner.lower() + '_'!r}")
        if name in TOOLS or name in names:
            raise ValueError(f"AI tool {name!r} already exists")
        names.append(name)
    for tool in tools:
        _tool(tool.name, tool.description, tool.properties, tool.required,
              mutates=tool.mutates,
              confirm_text=_plugin_confirm(tool.confirm_text))(
                  _plugin_handler(tool.handler))
    _PLUGIN_TOOLS[owner] = [names, 1]


def unregister_plugin_tools(owner: str) -> None:
    entry = _PLUGIN_TOOLS.get(owner)
    if entry is None:
        return
    entry[1] -= 1
    if entry[1] <= 0:
        for name in entry[0]:
            TOOLS.pop(name, None)
        del _PLUGIN_TOOLS[owner]


def _plugin_context(host):
    from core.plugins import PluginContext

    line = getattr(host, "command_line", None)
    return PluginContext(host=host, echo=getattr(line, "echo", None)
                         or (lambda text: None))


def _plugin_handler(handler):
    def run(host, **args):
        return handler(_plugin_context(host), **args)
    return run


def _plugin_confirm(confirm_text):
    if confirm_text is None:
        return None

    def ask(host, args):
        return confirm_text(_plugin_context(host), args)
    return ask


def tool_list() -> list[dict]:
    """Every tool as name, description and JSON Schema -- the shape both
    the providers (function calling) and MCP (tools/list) start from."""
    return [{"name": t.name, "description": t.description,
             "parameters": t.parameters} for t in TOOLS.values()]


# -- helpers ---------------------------------------------------------------------------

def _xy(point) -> tuple[float, float]:
    try:
        return float(point[0]), float(point[1])
    except (TypeError, ValueError, IndexError):
        raise ToolError(f"not a point: {point!r}") from None


def _space(host):
    return host.document.current_space()


def _entities(host, handles) -> list:
    """The live entities of the current space with these handles; an
    unknown handle, one on a locked layer or a plugin's derived geometry
    without its owner (core/derived.py) is an error, not a skip -- the
    model must know its change did not happen."""
    space = _space(host)
    doc = host.document.doc
    found, missing, locked = [], [], []
    for handle in handles:
        entity = doc.entitydb.get(str(handle).upper())
        if (entity is None or not entity.is_alive
                or entity.dxf.get("owner") != space.layout_key):
            missing.append(handle)
            continue
        layer = doc.layers.get(entity.dxf.get("layer", "0")) \
            if entity.dxf.get("layer", "0") in doc.layers else None
        if layer is not None and layer.is_locked():
            locked.append(handle)
            continue
        found.append(entity)
    if missing:
        raise ToolError("no such entity in the current space: "
                        + ", ".join(map(str, missing)))
    if locked:
        raise ToolError("on a locked layer: " + ", ".join(map(str, locked)))
    from core import derived

    found, refused = derived.user_editable(found)
    if refused:
        raise ToolError("derived geometry, modified only with the object it "
                        "comes from: "
                        + ", ".join(e.dxf.handle for e in refused))
    return found


def _execute(host, command) -> list[str]:
    """Run a Command as the keyboard would; the handles it created."""
    host.tools._execute(command)
    created = []
    for attr in ("entity", "dim", "copies"):
        value = getattr(command, attr, None)
        if value is None:
            continue
        for e in (value if isinstance(value, (list, tuple)) else [value]):
            handle = getattr(getattr(e, "dxf", None), "handle", None)
            if handle and handle not in created:
                created.append(handle)
    return created


def _r(value: float) -> float:
    return round(float(value), 6)


def _pt(vec) -> list[float]:
    return [_r(vec[0]), _r(vec[1])]


def describe(entity) -> dict:
    """What the model needs to know about one entity: type, handle, layer,
    colour and its defining geometry."""
    dxf = entity.dxf
    kind = entity.dxftype()
    out = {"handle": dxf.handle, "type": kind, "layer": dxf.get("layer", "0"),
           "color": dxf.get("color", 256)}
    try:
        if kind == "LINE":
            out.update(start=_pt(dxf.start), end=_pt(dxf.end),
                       length=_r(math.hypot(dxf.end.x - dxf.start.x,
                                            dxf.end.y - dxf.start.y)))
        elif kind in ("CIRCLE", "ARC"):
            from core import ocs

            cx, cy, r = ocs.circle_wcs(entity)
            out.update(center=[_r(cx), _r(cy)], radius=_r(r))
            if kind == "ARC":
                out.update(start_angle=_r(dxf.start_angle),
                           end_angle=_r(dxf.end_angle))
        elif kind == "LWPOLYLINE":
            pts = [_pt(p) for p in entity.get_points("xy")]
            out.update(closed=bool(entity.closed), vertex_count=len(pts),
                       vertices=pts[:VERTEX_LIMIT])
        elif kind in ("TEXT", "MTEXT"):
            text = entity.plain_text() if kind == "MTEXT" else dxf.text
            out.update(text=text, insert=_pt(dxf.insert),
                       height=_r(dxf.get("height" if kind == "TEXT"
                                         else "char_height", 0.0)))
        elif kind == "INSERT":
            out.update(block=dxf.name, insert=_pt(dxf.insert),
                       rotation=_r(dxf.get("rotation", 0.0)),
                       scale=[_r(dxf.get("xscale", 1.0)),
                              _r(dxf.get("yscale", 1.0))])
        elif kind == "POINT":
            out.update(location=_pt(dxf.location))
        elif kind == "DIMENSION":
            out.update(measurement=_r(entity.get_measurement()),
                       text=dxf.get("text", "<>"))
    except Exception:                    # noqa: BLE001 -- describe what we can
        pass
    return out


def _bbox(entity):
    from ezdxf import bbox

    try:
        box = bbox.extents([entity], fast=True)
    except Exception:                    # noqa: BLE001
        return None
    return box if box.has_data else None


# -- reading ---------------------------------------------------------------------------

@_tool("get_drawing_info",
       "The open drawing: file, units, current layer and space, how many "
       "entities, its extents and its revision.")
def get_drawing_info(host):
    from core import layers as layer_ops

    document = host.document
    space = _space(host)
    extents = None
    try:
        x0, y0, x1, y1 = host.viewport.scene_bounds()
        extents = [[_r(x0), _r(y0)], [_r(x1), _r(y1)]]
    except Exception:                    # noqa: BLE001
        pass
    return {
        "file": str(document.path) if document.path else None,
        "name": document.name,
        "units": int(document.doc.header.get("$INSUNITS", 0)),
        "current_layer": layer_ops.current_layer_name(document),
        "space": space.name if hasattr(space, "name") else "Model",
        "entity_count": len(space),
        "extents": extents,
        "unsaved_changes": bool(document.dirty),
    }


@_tool("list_layers", "Every layer with its colour, linetype and state.")
def list_layers(host):
    layers = []
    for layer in host.document.doc.layers:
        layers.append({"name": layer.dxf.name, "color": abs(layer.color),
                       "linetype": layer.dxf.get("linetype", "Continuous"),
                       "on": layer.is_on(), "frozen": layer.is_frozen(),
                       "locked": layer.is_locked()})
    return {"layers": layers}


@_tool("list_styles", "The text and dimension styles, and which are current.")
def list_styles(host):
    doc = host.document.doc
    return {
        "text_styles": [s.dxf.name for s in doc.styles
                        if s.dxf.name and not s.dxf.name.startswith("*")],
        "dimension_styles": [s.dxf.name for s in doc.dimstyles],
        "current_text_style": doc.header.get("$TEXTSTYLE", "Standard"),
        "current_dimension_style": doc.header.get("$DIMSTYLE", "Standard"),
    }


@_tool("query_entities",
       "Find entities in the current space, by type, layer and/or a window "
       "(entities whose bounding box touches it). Returns each one's handle "
       "and geometry, up to `limit`.",
       {"types": {"type": "array", "items": {"type": "string"},
                  "description": "DXF types, e.g. [\"LINE\", \"CIRCLE\"]"},
        "layer": {"type": "string"},
        "window": {"type": "array", "items": POINT, "minItems": 2,
                   "maxItems": 2, "description": "[[x0, y0], [x1, y1]]"},
        "limit": {"type": "integer", "minimum": 1, "maximum": QUERY_LIMIT}})
def query_entities(host, types=None, layer=None, window=None, limit=100):
    limit = max(1, min(int(limit), QUERY_LIMIT))
    wanted = {t.upper() for t in types} if types else None
    rect = None
    if window:
        (ax, ay), (bx, by) = _xy(window[0]), _xy(window[1])
        rect = (min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))
    found, truncated = [], False
    for entity in _space(host):
        if wanted is not None and entity.dxftype() not in wanted:
            continue
        if layer is not None and entity.dxf.get("layer", "0") != layer:
            continue
        if rect is not None:
            box = _bbox(entity)
            if box is None or (box.extmax.x < rect[0] or box.extmin.x > rect[2]
                               or box.extmax.y < rect[1]
                               or box.extmin.y > rect[3]):
                continue
        if len(found) == limit:
            truncated = True
            break
        found.append(describe(entity))
    return {"entities": found, "truncated": truncated}


@_tool("capture_view", "A picture of the drawing as the window shows it now.")
def capture_view(host):
    from PySide6.QtCore import QBuffer, QIODevice

    image = host.viewport.grabFramebuffer()
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    view = host.viewport.view
    x0, y1 = view.screen_to_world(0, 0)
    x1, y0 = view.screen_to_world(view.width, view.height)
    return Image(bytes(buffer.data()),
                 f"view from ({x0:.3f}, {y0:.3f}) to ({x1:.3f}, {y1:.3f})")


# -- drawing ---------------------------------------------------------------------------

@_tool("draw_line",
       "Lines through two or more points, one LINE per segment (as LINE "
       "does).", {"points": {"type": "array", "items": POINT, "minItems": 2}},
       ["points"], mutates=True)
def draw_line(host, points):
    from core import actions

    pts = [_xy(p) for p in points]
    if len(pts) < 2:
        raise ToolError("a line needs two points")
    handles = []
    for a, b in zip(pts, pts[1:]):
        handles += _execute(host, actions.add_line(a, b))
    return {"created": handles}


@_tool("draw_polyline", "One polyline through the points.",
       {"points": {"type": "array", "items": POINT, "minItems": 2},
        "closed": {"type": "boolean"}}, ["points"], mutates=True)
def draw_polyline(host, points, closed=False):
    from core import actions

    pts = [_xy(p) for p in points]
    return {"created": _execute(host, actions.add_polyline(pts, bool(closed)))}


@_tool("draw_rectangle", "A closed rectangular polyline from two corners.",
       {"corner1": POINT, "corner2": POINT}, ["corner1", "corner2"],
       mutates=True)
def draw_rectangle(host, corner1, corner2):
    from core import actions

    (ax, ay), (bx, by) = _xy(corner1), _xy(corner2)
    if ax == bx or ay == by:
        raise ToolError("the corners make no rectangle")
    pts = [(ax, ay), (bx, ay), (bx, by), (ax, by)]
    return {"created": _execute(host, actions.add_polyline(pts, True))}


@_tool("draw_circle", "A circle.", {"center": POINT, "radius": {
       "type": "number", "exclusiveMinimum": 0}}, ["center", "radius"],
       mutates=True)
def draw_circle(host, center, radius):
    from core import actions

    if float(radius) <= 0:
        raise ToolError("the radius must be positive")
    return {"created": _execute(host, actions.add_circle(_xy(center),
                                                         float(radius)))}


@_tool("draw_arc", "An arc, counter-clockwise from start to end angle.",
       {"center": POINT, "radius": {"type": "number", "exclusiveMinimum": 0},
        "start_angle": {"type": "number"}, "end_angle": {"type": "number"}},
       ["center", "radius", "start_angle", "end_angle"], mutates=True)
def draw_arc(host, center, radius, start_angle, end_angle):
    from core import actions

    if float(radius) <= 0:
        raise ToolError("the radius must be positive")
    geom = (_xy(center), float(radius), float(start_angle), float(end_angle))
    return {"created": _execute(host, actions.add_arc_geom(geom))}


@_tool("draw_text", "A single-line text in the current text style.",
       {"insert": POINT, "text": {"type": "string", "minLength": 1},
        "height": {"type": "number", "exclusiveMinimum": 0},
        "rotation": {"type": "number"}},
       ["insert", "text", "height"], mutates=True)
def draw_text(host, insert, text, height, rotation=0.0):
    from core import actions

    return {"created": _execute(host, actions.add_text(
        _xy(insert), str(text), float(height), float(rotation)))}


@_tool("draw_linear_dimension",
       "A horizontal or vertical dimension between two points, its "
       "dimension line through `line_point` (as DIMLINEAR picks it); "
       "`angle` forces a rotated one.",
       {"point1": POINT, "point2": POINT, "line_point": POINT,
        "angle": {"type": "number"}},
       ["point1", "point2", "line_point"], mutates=True)
def draw_linear_dimension(host, point1, point2, line_point, angle=None):
    from core import actions

    return {"created": _execute(host, actions.dim_linear(
        _xy(point1), _xy(point2), _xy(line_point),
        angle=None if angle is None else float(angle)))}


@_tool("draw_aligned_dimension",
       "A dimension parallel to the two points, its line through "
       "`line_point`.",
       {"point1": POINT, "point2": POINT, "line_point": POINT},
       ["point1", "point2", "line_point"], mutates=True)
def draw_aligned_dimension(host, point1, point2, line_point):
    from core import actions

    return {"created": _execute(host, actions.dim_aligned(
        _xy(point1), _xy(point2), _xy(line_point)))}


# -- layers ------------------------------------------------------------------------------

@_tool("create_layer", "A new layer.",
       {"name": {"type": "string", "minLength": 1}, "color": COLOR,
        "linetype": {"type": "string"}}, ["name"], mutates=True)
def create_layer(host, name, color=7, linetype="Continuous"):
    from core import layers as layer_ops

    doc = host.document.doc
    if name in doc.layers:
        raise ToolError(f"layer {name!r} already exists")
    if linetype not in doc.linetypes:
        raise ToolError(f"linetype {linetype!r} is not loaded in this drawing")
    host.tools._execute(layer_ops.NewLayerCommand(
        name, color=min(int(color), 255), linetype=linetype))
    return {"created_layer": name}


@_tool("set_current_layer", "Make a layer current: new entities go on it.",
       {"name": {"type": "string"}}, ["name"], mutates=True)
def set_current_layer(host, name):
    from core import layers as layer_ops

    said = []
    ok = layer_ops.make_current(
        host.document, name,
        execute=lambda commands: [host.tools._execute(c) for c in commands],
        echo=said.append)
    if not ok:
        raise ToolError(" ".join(said) or f"cannot make {name!r} current")
    return {"current_layer": name}


# -- modifying ---------------------------------------------------------------------------

@_tool("move_entities", "Move entities by a displacement.",
       {"handles": HANDLES, "dx": {"type": "number"}, "dy": {"type": "number"}},
       ["handles", "dx", "dy"], mutates=True)
def move_entities(host, handles, dx, dy):
    from core import actions

    host.tools._execute(actions.move_entities(_entities(host, handles),
                                              float(dx), float(dy)))
    return {"moved": list(handles)}


@_tool("copy_entities", "Copy entities by a displacement.",
       {"handles": HANDLES, "dx": {"type": "number"}, "dy": {"type": "number"}},
       ["handles", "dx", "dy"], mutates=True)
def copy_entities(host, handles, dx, dy):
    from core import actions

    command = actions.copy_entities(_entities(host, handles),
                                    float(dx), float(dy))
    return {"created": _execute(host, command)}


@_tool("rotate_entities", "Rotate entities about a base point.",
       {"handles": HANDLES, "base": POINT, "angle": {"type": "number"}},
       ["handles", "base", "angle"], mutates=True)
def rotate_entities(host, handles, base, angle):
    from core import actions

    host.tools._execute(actions.rotate_entities(
        _entities(host, handles), _xy(base), float(angle)))
    return {"rotated": list(handles)}


@_tool("scale_entities", "Scale entities about a base point.",
       {"handles": HANDLES, "base": POINT,
        "factor": {"type": "number", "exclusiveMinimum": 0}},
       ["handles", "base", "factor"], mutates=True)
def scale_entities(host, handles, base, factor):
    from core import actions

    if float(factor) <= 0:
        raise ToolError("the scale factor must be positive")
    host.tools._execute(actions.scale_entities(
        _entities(host, handles), _xy(base), float(factor)))
    return {"scaled": list(handles)}


def _erase_question(host, args) -> Optional[str]:
    from core.i18n import tr

    count = len(args.get("handles") or ())
    if count > ERASE_CONFIRM_ABOVE:
        return tr("The assistant wants to erase {count} objects.", count=count)
    return None


@_tool("erase_entities", "Erase entities.", {"handles": HANDLES},
       ["handles"], mutates=True, confirm_text=_erase_question)
def erase_entities(host, handles):
    from core import actions

    host.tools._execute(actions.EraseCommand(_entities(host, handles)))
    return {"erased": list(handles)}


@_tool("set_entity_properties",
       "Change the layer and/or colour of entities.",
       {"handles": HANDLES, "layer": {"type": "string"}, "color": COLOR},
       ["handles"], mutates=True)
def set_entity_properties(host, handles, layer=None, color=None):
    from core import actions

    entities = _entities(host, handles)
    if layer is None and color is None:
        raise ToolError("say a layer, a colour or both")
    if layer is not None:
        if layer not in host.document.doc.layers:
            raise ToolError(f"no layer {layer!r}: create_layer first")
        host.tools._execute(actions.SetPropertyCommand(entities, "layer", layer))
    if color is not None:
        host.tools._execute(actions.SetPropertyCommand(entities, "color",
                                                       int(color)))
    return {"changed": list(handles)}


# -- history and view --------------------------------------------------------------------

@_tool("undo", "Undo the last change (U).", mutates=True)
def undo(host):
    host._on_command_submitted("U")
    return {}


@_tool("redo", "Redo what undo took back (REDO).", mutates=True)
def redo(host):
    host._on_command_submitted("REDO")
    return {}


@_tool("zoom", "Zoom to the whole drawing, or to a window.",
       {"window": {"type": "array", "items": POINT, "minItems": 2,
                   "maxItems": 2, "description": "[[x0, y0], [x1, y1]]; "
                   "omitted: the drawing's extents"}})
def zoom(host, window=None):
    viewport = host.viewport
    if window:
        (ax, ay), (bx, by) = _xy(window[0]), _xy(window[1])
        if ax == bx or ay == by:
            raise ToolError("the window has no area")
        viewport.push_view()
        viewport.view.zoom_extents(min(ax, bx), min(ay, by),
                                   max(ax, bx), max(ay, by), margin=0.0)
        viewport.update()
    else:
        viewport.zoom_extents()
    return {}


# -- files -------------------------------------------------------------------------------

def _absolute(path: str) -> Path:
    target = Path(path).expanduser()
    if not target.is_absolute():
        # a relative path resolves somewhere the user did not mean (in the
        # Flatpak, against /app): never guess
        raise ToolError("give an absolute path")
    return target


def _overwrite_question(host, args) -> Optional[str]:
    from core.i18n import tr

    path = args.get("path")
    if not path:
        return None
    target = Path(path).expanduser()
    current = host.document.path
    if target.exists() and (current is None
                            or target.resolve() != Path(current).resolve()):
        return tr("The assistant wants to write over {path}.", path=str(target))
    return None


@_tool("save_drawing",
       "Save the drawing: over its own file, or to `path` (.dxf or .dwg).",
       {"path": {"type": "string"}}, confirm_text=_overwrite_question)
def save_drawing(host, path=None):
    document = host.document
    if path:
        target = _absolute(path)
        if target.suffix.lower() not in (".dxf", ".dwg"):
            raise ToolError("save as .dxf or .dwg")
    elif document.path is None:
        raise ToolError("the drawing was never saved: give a path")
    else:
        target = Path(document.path)
    if not host._write_document(target):
        raise ToolError(f"could not save {target}")
    return {"saved": str(target)}


@_tool("export_pdf",
       "Plot the drawing's extents to a PDF file, fitted to the paper.",
       {"path": {"type": "string"},
        "paper": {"type": "string", "enum": ["A4", "A3", "A2", "A1", "A0",
                                             "Letter"]},
        "landscape": {"type": "boolean"}},
       ["path"], confirm_text=_overwrite_question)
def export_pdf(host, path, paper="A4", landscape=True):
    from formats import pdf_out

    target = _absolute(path)
    if target.suffix.lower() != ".pdf":
        raise ToolError("the file must end in .pdf")
    printer = pdf_out.make_pdf_printer(str(target), paper, bool(landscape))
    pdf_out.plot(host.document, printer)
    return {"exported": str(target)}
