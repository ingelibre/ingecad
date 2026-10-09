"""File IPC is local to the current OS user; never run drawing work off the Qt thread."""
from __future__ import annotations
import base64
import json
import math
import os
import time
import uuid
import weakref
from pathlib import Path

from PySide6.QtCore import QTimer, QBuffer, QIODevice
from core.commands import Command
from core import actions

ROOT = Path(os.environ.get("INGECAD_MCP_ROOT") or str(Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".cache"))) / "IngeCAD-MCP"))
LIMIT = 4 * 1024 * 1024
WINDOWS = []  # Keep MCP-opened Qt windows alive until the user closes them.


def atomic(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    os.replace(temp, path)


def point(value):
    if not isinstance(value, (list, tuple)) or len(value) not in (2, 3):
        raise ValueError("A point requires 2 or 3 finite coordinates")
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in value):
        raise ValueError("Coordinates must be finite numbers")
    return tuple(value)


def positive(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError("Value must be positive and finite")
    return value


class Batch(Command):
    name = "MCP create entities"
    needs_regen = True

    def __init__(self, commands):
        self.commands = commands

    def do(self, document):
        done = []
        try:
            for command in self.commands:
                command.do(document)
                done.append(command)
        except Exception:
            for command in reversed(done):
                command.undo(document)
            raise

    def undo(self, document):
        for command in reversed(self.commands):
            command.undo(document)


class Attributes(Command):
    name = "MCP update entities"
    needs_regen = True

    def __init__(self, entities, values):
        self.entities, self.values = entities, values
        self.old = [{key: e.dxf.get(key) for key in values} for e in entities]

    def do(self, document):
        for e in self.entities:
            e.dxf.update(self.values)
        document.dirty = True

    def undo(self, document):
        for e, old in zip(self.entities, self.old):
            for key, value in old.items():
                if value is None:
                    e.dxf.discard(key)
                else:
                    setattr(e.dxf, key, value)
        document.dirty = True


class TableEntry(Command):
    name = "MCP create drawing table entry"
    needs_regen = True

    def __init__(self, table, entry, attributes):
        self.table, self.entry, self.attributes = table, entry, attributes

    def do(self, document):
        getattr(document.doc, self.table).new(self.entry, dxfattribs=self.attributes)
        document.dirty = True

    def undo(self, document):
        getattr(document.doc, self.table).remove(self.entry)
        document.dirty = True


class Layout(Command):
    name = "MCP create paper layout"
    needs_regen = True

    def __init__(self, args):
        self.args = args

    def do(self, document):
        a = self.args
        doc = document.doc
        layout = doc.layouts.new(a["name"])
        style = "MCP_" + a["name"]
        created_style = style not in doc.styles
        try:
            if created_style:
                doc.styles.new(style, dxfattribs={"font": "tahoma.ttf"})
            w, h = a["width_mm"], a["height_mm"]
            layout.page_setup(size=(w, h), margins=(0, 0, 0, 0), units="mm")
            margin, block = 10, 35
            layout.add_lwpolyline([(margin, margin), (w-margin, margin), (w-margin, h-margin), (margin, h-margin)], close=True)
            layout.add_line((margin, margin+block), (w-margin, margin+block))
            layout.add_text(a.get("project", ""), dxfattribs={"height": 4, "insert": (15, 34), "style": style, "color": 7})
            layout.add_text(a.get("title", "Plan"), dxfattribs={"height": 4, "insert": (15, 24), "style": style, "color": 7})
            layout.add_text(f'{a.get("sheet", "S-01")}  |  1:{a["scale"]:g}', dxfattribs={"height": 3, "insert": (15, 15), "style": style, "color": 7})
            vw, vh = w-30, h-65
            vp = layout.add_viewport(center=(w/2, 45+vh/2), size=(vw, vh),
                view_center_point=a["center"], view_height=vh*a["scale"]/a["model_unit_mm"])
            vp.dxf.flags = vp.dxf.flags | 16384  # lock viewport scale
            document.dirty = True
            self.created_style = created_style
        except Exception:
            doc.layouts.delete(a["name"])
            if created_style and style in doc.styles:
                doc.styles.remove(style)
            raise

    def undo(self, document):
        document.doc.layouts.delete(self.args["name"])
        if self.created_style:
            document.doc.styles.remove("MCP_" + self.args["name"])
        document.dirty = True


class Bridge:
    def __init__(self, ctx):
        self.ctx = ctx
        self.document = ctx.document
        self.id = str(uuid.uuid4())
        self.folder = ROOT / self.id
        self.folder.mkdir(parents=True, exist_ok=True)
        self.timer = QTimer(ctx.host)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)
        self.last_heartbeat = 0
        self.closed = False
        self.timer.start()
        reference = weakref.ref(self)
        def on_destroyed(*_):
            bridge = reference()
            if bridge is not None:
                bridge.close(destroying=True)
        self.destroy_hook = on_destroyed
        ctx.host.destroyed.connect(self.destroy_hook)
        self.tick()

    def close(self, *args, destroying=False):
        if self.closed:
            return
        self.closed = True
        self.timer.stop()
        self.timer.deleteLater()
        if not destroying:  # During QObject destruction Qt already disconnects the signal.
            try:
                self.ctx.host.destroyed.disconnect(self.destroy_hook)
            except RuntimeError:
                pass
        (self.folder / "session.json").unlink(missing_ok=True)

    def status(self):
        d, h = self.ctx.document, self.ctx.host
        return {"session_id": self.id, "pid": os.getpid(), "title": h.windowTitle(),
            "path": str(d.path) if d.path else None, "revision": d.revision,
            "dirty": d.dirty, "space": d.space_name, "units": d.doc.units,
            "layouts": list(d.doc.layouts.names()), "can_undo": h.history.can_undo,
            "can_redo": h.history.can_redo, "busy": bool(getattr(h, "_open_thread", None)),
            "heartbeat": time.time(), "bridge_version": "0.3.2"}

    def tick(self):
        if not self.ctx.host.plugins.is_active("ingecad_mcp"):
            self.close()
            return
        if self.ctx.document is not self.document:
            self.close()
            start(self.ctx)
            return
        if time.time() - self.last_heartbeat > 1:
            atomic(self.folder / "session.json", self.status())
            self.last_heartbeat = time.time()
        for path in sorted(self.folder.glob("*.request.json"))[:4]:
            claimed = path.with_suffix(".working")
            try:
                os.replace(path, claimed)
            except OSError:
                continue
            response_path = self.folder / path.name.replace(".request.json", ".response.json")
            try:
                if response_path.exists():
                    continue  # request ID already completed; never execute a retry twice
                if claimed.stat().st_size > LIMIT:
                    raise ValueError("Request exceeds 4 MiB")
                req = json.loads(claimed.read_text(encoding="utf-8"))
                if req["deadline"] < time.time():
                    raise TimeoutError("Request expired before execution")
                value = self.dispatch(req["operation"], req.get("arguments", {}))
                response = {"ok": True, "result": value, "revision": self.ctx.document.revision}
            except Exception as exc:
                response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            finally:
                claimed.unlink(missing_ok=True)
            atomic(response_path, response)
        # Responses expire after 24 hours, well beyond all client deadlines.
        for path in self.folder.glob("*.response.json"):
            if time.time() - path.stat().st_mtime > 86400:
                path.unlink(missing_ok=True)

    def space(self, name):
        d = self.ctx.document
        if name == "Model":
            return d.doc.modelspace()
        if name is None:
            return d.current_space()
        return d.doc.layouts.get(name)

    def dispatch(self, op, a):
        ctx, h, d = self.ctx, self.ctx.host, self.ctx.document
        read_only = op in {"status", "query_entities", "get_drawing_tables", "screenshot"}
        if not read_only:
            if d.edit_block is not None or getattr(h, "_block_session", None):
                raise ValueError("Exit Block Editor before MCP mutations")
            if getattr(h, "_open_thread", None):
                raise ValueError("Document loading; retry when ready")
            if h.tools.tool is not None:
                raise ValueError("Finish or cancel the active drawing tool before MCP mutations")
            if a.get("expected_revision") is not None and a["expected_revision"] != d.revision:
                raise ValueError("Document changed: expected_revision does not match")
        if op == "status":
            return self.status()
        if op == "get_drawing_tables":
            return {"layers": [e.dxf.all_existing_dxf_attribs() for e in d.doc.layers],
                    "text_styles": [e.dxf.all_existing_dxf_attribs() for e in d.doc.styles],
                    "dimension_styles": [e.dxf.all_existing_dxf_attribs() for e in d.doc.dimstyles],
                    "current_text_style": d.doc.header.get("$TEXTSTYLE", "Standard"),
                    "current_dimension_style": d.doc.header.get("$DIMSTYLE", "Standard")}
        if op == "open_drawing":
            path = Path(a["path"])
            if not path.is_absolute() or not path.is_file() or path.suffix.lower() not in {".dxf", ".dwg"}:
                raise ValueError("Provide an existing absolute DXF/DWG path")
            # Parse before opening a window: errors return through MCP, not modal UI dialogs.
            from core.document import Document
            from formats.dwg_bridge import load_dwg
            from render.backend import build_scene
            document = load_dwg(path) if path.suffix.lower() == ".dwg" else Document.load(path)
            scene = build_scene(document)
            from views.main_window import MainWindow
            from PySide6.QtCore import Qt
            window = MainWindow()
            window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            WINDOWS.append(window)
            try:
                window._on_open_done(document, scene)
                window.show()
            except Exception:
                WINDOWS.remove(window)
                window.deleteLater()
                raise
            window.destroyed.connect(lambda *_: WINDOWS.remove(window) if window in WINDOWS else None)
            return {"session_id": window._mcp_bridge.id, "path": str(path), "opened_in_new_window": True}
        if op == "query_entities":
            space = self.space(a.get("space", "Model"))
            limit = max(1, min(int(a.get("limit", 100)), 1000))
            offset = max(0, int(a.get("offset", 0)))
            entities = [e for e in space if (not a.get("type") or e.dxftype() == a["type"].upper())
                and (not a.get("layer") or e.dxf.layer == a["layer"])]
            return {"total": len(entities), "offset": offset, "entities": [
                {"handle": e.dxf.handle, "type": e.dxftype(), "attributes": json.loads(json.dumps(e.dxf.all_existing_dxf_attribs(), default=lambda v: list(v) if hasattr(v, "__iter__") else str(v)))}
                for e in entities[offset:offset+limit]]}
        if op in {"create_layer", "create_text_style", "create_dimension_style"}:
            table = {"create_layer": "layers", "create_text_style": "styles", "create_dimension_style": "dimstyles"}[op]
            name = a["name"]
            if not name or name in getattr(d.doc, table) or any(c in name for c in '<>/\\":;?*|='):
                raise ValueError("Entry name must be valid, new and nonempty")
            if op == "create_layer":
                color = a.get("color", 7)
                if type(color) is not int or not 1 <= color <= 255:
                    raise ValueError("Layer color must be 1..255")
                attrs = {"color": color}
            elif op == "create_text_style":
                font = a.get("font", "tahoma.ttf")
                if not isinstance(font, str) or Path(font).name != font or not font.lower().endswith(".ttf"):
                    raise ValueError("Font must be a local TTF basename")
                attrs = {"font": font}
            else:
                if a["text_style"] not in d.doc.styles:
                    raise ValueError("Text style does not exist")
                attrs = {"dimtxt": positive(a["text_height"]), "dimasz": positive(a["arrow_size"]),
                         "dimlfac": positive(a.get("measurement_factor", 1)), "dimtxsty": a["text_style"],
                         "dimgap": a["text_height"]*.3, "dimexo": a["text_height"]*.4,
                         "dimexe": a["text_height"]*.6, "dimdec": 2, "dimclrd": 7, "dimclre": 7, "dimclrt": 7}
            ctx.execute(TableEntry(table, name, attrs))
            return {"name": name, "table": table}
        if op == "create_entities":
            specs = a["entities"]
            if not 1 <= len(specs) <= 1000:
                raise ValueError("Batch requires 1 to 1000 entities")
            space = self.space(a.get("space", "Model"))
            commands = []
            for s in specs:
                kind = s["type"].upper()
                layer = s.get("layer", "0")
                if layer not in d.doc.layers:
                    raise ValueError(f"Layer does not exist: {layer}")
                if kind == "LINE":
                    cmd = actions.add_line(point(s["start"]), point(s["end"]))
                elif kind == "CIRCLE":
                    cmd = actions.add_circle(point(s["center"]), positive(s["radius"]))
                elif kind == "LWPOLYLINE":
                    points = [point(p)[:2] for p in s["points"]]
                    if len(points) < 2:
                        raise ValueError("Polyline requires at least two points")
                    cmd = actions.add_polyline(points, closed=bool(s.get("closed", False)))
                elif kind == "TEXT":
                    text = str(s["text"])
                    if len(text) > 10000:
                        raise ValueError("Text is too long")
                    if s.get("style") and s["style"] not in d.doc.styles:
                        raise ValueError("Text style does not exist")
                    cmd = actions.add_text(point(s["position"]), text, positive(s.get("height", 2.5)), rotation=s.get("rotation", 0), style=s.get("style"))
                elif kind == "DIMENSION":
                    if s.get("dimstyle") and s["dimstyle"] not in d.doc.dimstyles:
                        raise ValueError("Dimension style does not exist")
                    cmd = actions.dim_linear(point(s["start"]), point(s["end"]), point(s["location"]), angle=s.get("angle"), text=s.get("text", "<>"), dimstyle=s.get("dimstyle"))
                else:
                    raise ValueError(f"Unsupported type: {kind}")
                cmd._space, cmd.layer = space, layer
                commands.append(cmd)
            ctx.execute(Batch(commands))
            return {"handles": [getattr(c, "entity", None).dxf.handle if getattr(c, "entity", None) is not None else c.dim.dxf.handle for c in commands]}
        if op in {"delete_entities", "update_entities"}:
            space = self.space(a.get("space", "Model"))
            handles = a["handles"]
            if not 1 <= len(handles) <= 1000 or len(set(handles)) != len(handles):
                raise ValueError("Provide 1 to 1000 unique handles")
            index = {e.dxf.handle: e for e in space}
            entities = [index[x] for x in handles]  # wrong-space handles fail before changes
            if op == "delete_entities":
                cmd = actions.EraseCommand(entities)
                cmd._space = space
            else:
                values = a["attributes"]
                allowed = {"layer", "color", "linetype", "lineweight", "text", "height", "rotation", "radius", "start", "end", "center", "insert"}
                if not values or set(values) - allowed:
                    raise ValueError("Unsupported or empty attributes")
                for key, value in list(values.items()):
                    if key in {"start", "end", "center", "insert"}:
                        values[key] = point(value)
                    elif key in {"height", "radius"}:
                        positive(value)
                    elif key == "layer" and value not in d.doc.layers:
                        raise ValueError("Layer does not exist")
                    elif key == "color" and (type(value) is not int or not 0 <= value <= 256):
                        raise ValueError("Color must be ACI 0..256")
                    if any(not e.dxf.is_supported(key) for e in entities):
                        raise ValueError(f"Attribute {key} is unsupported by an entity")
                # Validate dxf conversion against disposable copies before mutating originals.
                for e in entities:
                    e.copy().dxf.update(values)
                cmd = Attributes(entities, values)
            ctx.execute(cmd)
            return {"handles": handles}
        if op == "create_layout":
            name = a.get("name", "A3")
            if not name or name in d.doc.layouts:
                raise ValueError("Layout name must be new and nonempty")
            for key, default in {"width_mm": 420, "height_mm": 297, "scale": 75}.items():
                a[key] = positive(a.get(key, default))
            if a["width_mm"] < 100 or a["height_mm"] < 100:
                raise ValueError("Sheet dimensions must be at least 100 mm")
            unit_mm = {4: 1, 5: 10, 6: 1000}.get(d.doc.units)
            a["model_unit_mm"] = positive(a.get("model_unit_mm") or unit_mm or 0)
            a["center"] = point(a.get("center", [0, 0]))[:2]
            a["name"] = name
            ctx.execute(Layout(a))
            h._sync_layout_tabs()
            return {"layout": name, "scale": a["scale"], "width_mm": a["width_mm"], "height_mm": a["height_mm"]}
        if op == "switch_layout":
            name = a["name"]
            if name not in d.doc.layouts:
                raise ValueError("Unknown layout")
            h.switch_layout(name)
            return {"space": d.space_name}
        if op in {"undo", "redo"}:
            getattr(h, "_cmd_" + op)()
            return self.status()
        if op == "zoom_extents":
            h.viewport.zoom_extents()
            return {"space": d.space_name}
        if op == "screenshot":
            buf = QBuffer()
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            h.viewport.grab().save(buf, "PNG")
            return {"png_base64": base64.b64encode(bytes(buf.data())).decode("ascii")}
        if op in {"save", "export_pdf"}:
            path = Path(a["path"])
            if not path.is_absolute():
                raise ValueError("Output path must be absolute")
            if path.exists() and not a.get("overwrite", False):
                raise FileExistsError("Output exists; set overwrite=true explicitly")
            if not path.parent.is_dir():
                raise ValueError("Output directory does not exist")
            if op == "save":
                if path.suffix.lower() not in {".dxf", ".dwg"}:
                    raise ValueError("Save requires .dxf or .dwg")
                encoding = d.doc.encoding
                try:
                    if path.suffix.lower() == ".dwg":
                        # This Windows LibreDWG build round-trips Thai with ANSI_874.
                        for e in d.doc.entitydb.values():
                            if e.is_alive and e.dxftype() in {"TEXT", "MTEXT"}:
                                str(e.dxf.get("text", "")).encode("cp874")
                        d.doc.encoding = "cp874"
                    engine, warnings = d.save_as(path)
                finally:
                    d.doc.encoding = encoding
                return {"path": str(path), "engine": engine, "warnings": warnings, "bytes": path.stat().st_size}
            if path.suffix.lower() != ".pdf":
                raise ValueError("PDF output requires .pdf")
            from formats.pdf_out import make_pdf_printer_mm, plot_layout
            name = a["layout"]
            layout = d.doc.layouts.get(name)
            if name == "Model":
                raise ValueError("PDF export requires a paper layout")
            printer = make_pdf_printer_mm(str(path), layout.dxf.paper_width, layout.dxf.paper_height)
            plot_layout(d, printer, name)
            del printer
            return {"path": str(path), "bytes": path.stat().st_size}
        raise ValueError(f"Unknown operation: {op}")


def start(ctx, *args):
    existing = getattr(ctx.host, "_mcp_bridge", None)
    if existing is not None and existing.document is not ctx.document:
        existing.close()
    if existing is None or existing.closed:
        ctx.host._mcp_bridge = Bridge(ctx)
    ctx.echo(f"IngeCAD MCP session: {ctx.host._mcp_bridge.id}")


def stop(ctx, *args):
    if getattr(ctx.host, "_mcp_bridge", None):
        ctx.host._mcp_bridge.close()
    ctx.echo("IngeCAD MCP bridge stopped")
