"""Use the bundled interpreter to exercise GUI/CAD and a real bundled stdio server."""
import asyncio
import hashlib
import json
import os
import site
import sys
import threading
import time
import traceback
from pathlib import Path

root = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve()
out.mkdir(parents=True, exist_ok=True)
sys.dont_write_bytecode = True
site.addsitedir(str(root/"runtime"/"site-packages"))
sys.path.insert(0, str(root))
os.chdir(root)
os.environ["PATH"] = str(root/"vendor"/"libredwg"/"bin")+os.pathsep+os.environ.get("PATH", "")
os.environ["XDG_CONFIG_HOME"] = str(out/"user-config")
os.environ["INGECAD_MCP_ROOT"] = str(out/"ipc")
os.environ["INGECAD_SHOW_AI"] = "1"
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(out/"qt-settings"))
from configure import configure
connection = configure(root)
import main
main._configure_surface_format()
app = QApplication(["IngeCAD bundle verification"])
main._apply_dark_theme(app)
main._init_language()
from views.main_window import MainWindow
window = MainWindow()
window.show()
window.new_document()
window.document.doc.units = 4
assert Path(sys.executable).resolve().parent == root/"runtime"
assert Path(sys.prefix).resolve() == root/"runtime"
assert all(Path(entry).resolve().is_relative_to(root) for entry in sys.path if entry)
panel = window._ingecad_ai_panel
assert panel is not None and root.name in panel.bridge_help.toPlainText()
assert set(window.plugins._active) >= {"ingecad_mcp", "terreno", "topografia"}
STATE = {"done":False, "passed":False}


async def verify():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    parameters = StdioServerParameters(command=connection["command"], args=connection["args"], env=dict(os.environ))
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert len(tools.tools) == 19
            async def call(name, args):
                reply = await session.call_tool(name, args)
                assert not reply.isError, (name, reply)
                result = reply.structuredContent
                if result is None:
                    result = json.loads(next(c.text for c in reply.content if c.type == "text"))
                if "result" in result:
                    result = result["result"]
                return result
            listed = await call("list_sessions", {})
            candidates = listed.get("sessions", []) if isinstance(listed, dict) else listed
            assert len(candidates) == 1, listed
            sid = candidates[0]["session_id"]
            async def cad(name, args):
                value = await call(name, {"session_id":sid, **args})
                assert value.get("ok", True), (name, value)
                return value
            status = await cad("get_status", {})
            manifest = json.loads((root/"bundle-manifest.json").read_text(encoding="utf-8"))
            assert status["bridge_version"] == manifest["bundle_version"]
            provider_path = "plugins/ingecad_mcp/providers.py"
            assert hashlib.sha256((root/provider_path).read_bytes()).hexdigest() == manifest["files"][provider_path]
            await cad("create_text_style", {"name":"BUNDLE_THAI"})
            await cad("create_entities", {"entities":[
                {"type":"LINE", "start":[0,0], "end":[8000,0]},
                {"type":"TEXT", "text":"บ้าน 2 ชั้น กทม", "position":[0,1000], "height":250, "style":"BUNDLE_THAI"}]})
            await cad("create_layout", {"name":"BUNDLE_A3", "project":"บ้าน 2 ชั้น กทม", "title":"Bundle verification", "center":[4000,500], "scale":50})
            await cad("save_drawing", {"path":str(out/"แบบทดสอบ ชื่อไทย.dxf"), "overwrite":True})
            dwg = await cad("save_drawing", {"path":str(out/"แบบทดสอบ ชื่อไทย.dwg"), "overwrite":True})
            await cad("export_pdf", {"path":str(out/"แบบทดสอบ A3.pdf"), "layout":"BUNDLE_A3", "overwrite":True})
            await cad("switch_layout", {"name":"BUNDLE_A3"})
            await cad("zoom_extents", {})
            import ezdxf
            from formats.dwg_bridge import dwg_to_dxf, _discard_temp_dxf
            converted = dwg_to_dxf(out/"แบบทดสอบ ชื่อไทย.dwg")
            try:
                drawing = ezdxf.readfile(converted)
            finally:
                _discard_temp_dxf(converted)
            assert any(e.dxftype()=="TEXT" and e.dxf.text=="บ้าน 2 ชั้น กทม" for e in drawing.modelspace())
            assert "BUNDLE_A3" in drawing.layouts
            STATE.update({"passed":True, "tools":len(tools.tools), "dwg_result":dwg, "status":status, "checks":[
                "bundled runtime and dependencies", "3 native plugins and AI/MCP guide", "real stdio MCP initialization and 19 tools",
                "native GUI-thread CAD calls", "A3 title block and PDF export", "Thai-path DWG save/reopen with Thai text and layout"]})


def run_tests():
    try:
        asyncio.run(verify())
    except Exception:
        STATE["error"] = traceback.format_exc()
    finally:
        STATE["done"] = True


thread = threading.Thread(target=run_tests, daemon=True)
thread.start()
deadline = time.monotonic()+180
while not STATE["done"] and time.monotonic()<deadline:
    app.processEvents()
    time.sleep(.01)
if not STATE["done"]:
    STATE["error"] = "verification timeout"
if STATE["passed"]:
    panel.connection_button.setChecked(False)
    app.processEvents()
    window.grab().save(str(out/"bundle-native-window.png"))
(out/"verification.json").write_text(json.dumps(STATE, ensure_ascii=False, indent=2), encoding="utf-8")
panel.shutdown()
window.document.dirty = False
window.close()
app.processEvents()
print(json.dumps(STATE, ensure_ascii=True))
sys.exit(0 if STATE["passed"] else 1)
