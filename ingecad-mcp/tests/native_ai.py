"""Real Qt UI + real CAD + local HTTP protocol fixtures. No commercial AI credentials used."""
import base64
import json
import os
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/"test-ai"
OUT.mkdir(exist_ok=True)
APP = Path(os.environ["LOCALAPPDATA"])/"Programs"/"IngeCAD"
sys.path.insert(0, str(APP))
os.chdir(APP)
os.environ["PATH"] = str(APP/"vendor"/"libredwg")+os.pathsep+os.environ["PATH"]
from PySide6.QtCore import QCoreApplication, QSettings, QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor
QCoreApplication.setApplicationName("IngeCAD AI fixture tests")
QCoreApplication.setOrganizationName("IngeCAD AI fixture tests")
QSettings().setValue("plugins/ingecad_mcp/enabled", True)
import main
main._configure_surface_format()
app = QApplication(["IngeCAD AI native tests"])
main._apply_dark_theme(app)
main._init_language()
from views.main_window import MainWindow
window = MainWindow()
window.show()
window.new_document()
window.document.doc.units = 4
panel = window._ingecad_ai_panel
from ingecad_plugin_ingecad_mcp import credentials
from ingecad_plugin_ingecad_mcp.ai_panel import show_panel
show_panel(window.plugins.context())

STATE = {"stage": 0, "images": False, "requests": 0, "tool_results": [], "delay": False}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        assert self.path.endswith("/models")
        self.respond({"data": [{"id": "fixture-tool-vision"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        STATE["requests"] += 1
        if self.path.endswith("/messages"):
            assert self.headers.get("anthropic-version") == "2023-06-01"
            messages = body["messages"]
        elif self.path.endswith("/responses"):
            assert body["store"] is False
            messages = body["input"]
        else:
            messages = body["messages"]
        string = json.dumps(messages, ensure_ascii=False)
        text = "OK"
        calls = []
        if "Reply with OK only" not in string:
            if STATE["delay"]:
                time.sleep(.5)
            STATE["images"] |= "data:image/png;base64," in string or '"media_type": "image/png"' in string
            stage = STATE["stage"]
            plan = [
                [("get_status", {}), ("get_drawing_tables", {})],
                [("create_text_style", {"name": "AI_THAI"}), ("create_layer", {"name": "AI_FOUNDATION"}),
                 ("create_dimension_style", {"name": "AI_DIM", "text_style": "AI_THAI", "text_height": 180, "arrow_size": 120, "measurement_factor": .001})],
                [("create_entities", {"entities": [
                    {"type": "LWPOLYLINE", "points": [[0,0],[1000,0],[1000,1000],[0,1000]], "closed": True, "layer": "AI_FOUNDATION"},
                    {"type": "TEXT", "text": "บ้าน 2 ชั้น กทม", "position": [0,2000], "height": 180, "style": "AI_THAI"},
                    {"type": "DIMENSION", "start": [0,0], "end": [1000,0], "location": [0,-500], "dimstyle": "AI_DIM", "angle": 0}]})],
                [("create_layout", {"name": "AI_A3", "project": "บ้าน 2 ชั้น กทม", "title": "Foundation plan", "center": [500,700], "scale": 25})],
                [("save_drawing", {"path": str(OUT/"AI_A3.dxf"), "overwrite": True}),
                 ("export_pdf", {"path": str(OUT/"AI_A3.pdf"), "layout": "AI_A3", "overwrite": True}),
                 ("switch_layout", {"name": "AI_A3"}), ("zoom_extents", {})],
            ]
            if stage < len(plan):
                calls = [{"id": f"call_{stage}_{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}} for i, (name,args) in enumerate(plan[stage])]
            else:
                text = "สร้างแบบฐานรากตัวอย่างและ Layout A3 พร้อม Title Block แล้ว"
                STATE["tool_results"] = [m["content"] for m in messages if m.get("role") == "tool"]
            STATE["stage"] += 1
        if self.path.endswith("/messages"):
            content = [{"type": "tool_use", "id": c["id"], "name": c["function"]["name"], "input": json.loads(c["function"]["arguments"])} for c in calls] if calls else [{"type":"text","text":text}]
            self.respond({"content": content, "stop_reason": "tool_use" if calls else "end_turn"})
        elif self.path.endswith("/responses"):
            output = [{"type": "function_call", "call_id": c["id"], "name": c["function"]["name"], "arguments": c["function"]["arguments"]} for c in calls] if calls else [{"type":"message","role":"assistant","content":[{"type":"output_text","text":text}]}]
            self.respond({"status": "completed", "output": output})
        else:
            self.respond({"choices": [{"message": {"role":"assistant", "content": None if calls else text, "tool_calls":calls}}]})


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{server.server_port}/v1"


def pump(timeout=15):
    end = time.monotonic()+timeout
    while panel.worker is not None and time.monotonic() < end:
        app.processEvents()
        time.sleep(.01)
    assert panel.worker is None, "Native UI job did not terminate"
    app.processEvents()


checks = []
try:
    for name in ["Groq", "OpenAI", "Google Gemini", "Anthropic Claude", "OpenRouter", "Ollama (local)", "Custom (OpenAI-compatible)"]:
        panel.provider.setCurrentText(name)
        panel.base.setText(base)
        panel.key.setText("fixture-only-key")
        panel.remember.setChecked(False)
        panel.models_button.click()
        pump()
        assert panel.model.currentText() == "fixture-tool-vision", panel.status.text()
        panel.test_button.click()
        pump()
        assert "สำเร็จ" in panel.status.text(), (name,panel.status.text())
    checks.append("7 provider UI presets: Models + Test connection against local protocol fixtures")
    name = "IngeCAD/AI-Test/"+str(uuid.uuid4())
    secret = "temporary-test-"+str(uuid.uuid4())
    try:
        credentials.save(name, secret)
        assert credentials.load(name) == secret
        credentials.delete(name)
        assert credentials.load(name) == ""
    finally:
        credentials.delete(name)
    checks.append("real Windows Credential Manager save/read/delete; key masking")
    assert panel.key.echoMode() == panel.key.EchoMode.Password
    sample = QImage(40,40,QImage.Format_RGB32)
    sample.fill(QColor("white"))
    sample.save(str(OUT/"attachment.png"))
    panel.attach_image(OUT/"attachment.png")
    panel.viewport_image.setChecked(True)
    panel.overwrite.setChecked(True)
    panel.prompt.setPlainText("สร้างฐานรากตัวอย่าง จัด A3 พร้อม Title Block บ้าน 2 ชั้น กทม และบันทึก/ส่งออกไฟล์ทดสอบที่ระบุ")
    panel.send_button.click()
    pump()
    assert "เสร็จแล้ว" in panel.status.text(), panel.chat.toPlainText()
    assert STATE["images"]
    assert len(window.document.doc.modelspace()) == 3
    assert "AI_A3" in window.document.doc.layouts
    assert (OUT/"AI_A3.pdf").stat().st_size > 1000
    assert all(json.loads(x)["ok"] for x in STATE["tool_results"])
    panel.connection_button.setChecked(False)
    app.processEvents()
    window.grab().save(str(OUT/"ai-panel.png"))
    panel.connection_button.setChecked(True)
    app.processEvents()
    window.grab().save(str(OUT/"ai-connection.png"))
    checks.append("native chat tool loop: style/layer/dimension, 3 CAD entities, A3 title block, DXF/PDF, viewport + photo payload")
    from ingecad_plugin_ingecad_mcp.providers import Provider, responses_payload, anthropic_payload
    # Exercise native provider tool-result conversions independently of the Qt chat loop.
    history = [{"role":"system","content":"CAD"}, {"role":"user","content":[{"type":"text","text":"plan"},{"type":"image_url","image_url":{"url":"data:image/png;base64,AA=="}}]},
        {"role":"assistant","content":"","_response_items":[{"type":"reasoning","encrypted_content":"opaque"},{"type":"function_call","call_id":"one","name":"get_status","arguments":"{}"}],
         "_anthropic_content":[{"type":"tool_use","id":"one","name":"get_status","input":{}}]},
        {"role":"tool","tool_call_id":"one","content":"{}"}]
    tools = [{"type":"function","function":{"name":"get_status","description":"status","parameters":{"type":"object","properties":{}}}}]
    rp = responses_payload("test", history, tools)
    assert any(i.get("type") == "reasoning" for i in rp["input"])
    assert rp["input"][-1]["type"] == "function_call_output"
    ap = anthropic_payload("test", history, tools)
    assert ap["messages"][-1]["content"][0]["type"] == "tool_result"
    assert ap["messages"][0]["content"][1]["source"]["type"] == "base64"
    checks.append("Responses reasoning/tool continuity; Anthropic image/tool-result mapping")
    before = len(window.document.doc.modelspace())
    panel.reset_chat()
    STATE["stage"], STATE["delay"] = 0, True
    panel.prompt.setPlainText("cancel test")
    panel.send_button.click()
    app.processEvents()
    panel.stop_button.click()
    pump()
    assert len(window.document.doc.modelspace()) == before
    assert "Stopped" in panel.status.text()
    checks.append("Stop prevents additional CAD tool execution")
    from types import SimpleNamespace
    original = (OUT/"AI_A3.dxf").read_bytes()
    fake = SimpleNamespace(config={"overwrite":False}, check=lambda:None, reply_ready=threading.Event(), tool_reply=None)
    panel.worker = fake
    panel.job_document = window.document
    panel.execute_tool("save_drawing", {"path":str(OUT/"AI_A3.dxf"), "overwrite":True})
    assert not fake.tool_reply["ok"]
    assert (OUT/"AI_A3.dxf").read_bytes() == original
    panel.job_document = object()
    panel.execute_tool("create_entities", {"entities":[{"type":"LINE","start":[0,0],"end":[1,1]}]})
    assert not fake.tool_reply["ok"] and len(window.document.doc.modelspace()) == before
    panel.worker = None
    panel.job_document = window.document
    checks.append("native executor rejects unapproved overwrite and stale document")
    panel.toggle_bridge()
    assert window._mcp_bridge.closed
    assert "ปิดอยู่" in panel.bridge_help.toPlainText()
    panel.toggle_bridge()
    assert not window._mcp_bridge.closed
    assert window._mcp_bridge.id in panel.bridge_help.toPlainText()
    assert "mcpServers" in panel.bridge_help.toPlainText()
    assert str(ROOT/"server.py") in panel.bridge_help.toPlainText()
    panel.copy_bridge.click()
    assert QApplication.clipboard().text() == panel.bridge_help.toPlainText()
    QApplication.clipboard().clear()
    panel.bridge_details.setChecked(False)
    assert panel.bridge_help.isHidden()
    panel.bridge_details.setChecked(True)
    assert not panel.bridge_help.isHidden()
    panel.bridge_help.verticalScrollBar().setValue(0)
    window.grab().save(str(OUT/"mcp-help-panel.png"))
    checks.append("MCP setup guide: installed paths, live session/Off state, clipboard Copy, collapse/expand")
    checks.append("native Start/Stop MCP bridge buttons")
    report = {"passed":True,"cloud_live_tested":False,"checks":checks}
    (OUT/"ai-verification.json").write_text(json.dumps(report, ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
finally:
    panel.shutdown()
    window.document.dirty = False
    window.close()
    app.processEvents()
    server.shutdown()
