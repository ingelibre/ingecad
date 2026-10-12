"""Human-readable stdio setup, generated from the installed connector paths."""
import json
from pathlib import Path


def load_connection():
    try:
        value = json.loads(Path(__file__).with_name("connection.json").read_text(encoding="utf-8"))
        command, args = value["command"], value["args"]
        if not isinstance(command, str) or not isinstance(args, list) or len(args) != 1 or not isinstance(args[0], str):
            raise ValueError("Invalid connector configuration")
        return {"command": command, "args": args}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def connection_ready(connection):
    return bool(connection and Path(connection["command"]).is_file() and Path(connection["args"][0]).is_file())


def build_help(connection, running, session_id=""):
    state = ("เปิดแล้ว · session_id: " + session_id) if running else "ปิดอยู่ · กด Start bridge ก่อนเรียกเครื่องมือ"
    intro = f"""IngeCAD AI + MCP — คู่มือเชื่อมต่อ
สถานะ Bridge: {state}

MCP คือมาตรฐานให้โปรแกรม AI เรียกเครื่องมือ CAD: อ่านแบบ วาด/แก้ไขวัตถุ จัด Layout และส่งออกไฟล์
เชื่อมได้กับ AI client ที่รองรับ local stdio MCP และเรียกโปรแกรมบนเครื่องนี้ได้
ส่วนนี้ใช้ตัวกลาง Python (stdio) เชื่อม IngeCAD ภายในเครื่อง ไม่ต้องกรอก API Key ในแท็บ AI เพื่อใช้ MCP
บัญชี/โมเดล AI ให้ตั้งค่าที่ client ของคุณ ส่วนแชทในแท็บ AI ใช้ Provider และ API Key แยกกัน

เริ่มใช้งาน
1. เปิด IngeCAD พร้อมเอกสาร แล้วเปิด Bridge
2. เพิ่ม server ชื่อ ingecad ใน AI client ด้วยตัวอย่างด้านล่าง
3. โหลดการตั้งค่าใหม่/เปิด client ใหม่ แล้วให้ AI เรียก list_sessions
4. เลือก session_id ของหน้าต่างที่ต้องการ และใช้ค่านั้นกับคำสั่งถัดไป
ถ้ามีหลายหน้าต่าง ต้องเลือกให้ชัดเจน; เมื่อเปลี่ยนเอกสาร session_id จะเปลี่ยน

"""
    if not connection:
        return intro + "ยังไม่พบเส้นทางตัวกลาง MCP: รัน install.py จากโฟลเดอร์แพ็กเกจ แล้วเปิด IngeCAD ใหม่\n"
    command, script = connection["command"], connection["args"][0]
    quote = lambda s: '"' + s + '"'
    block = json.dumps({"mcpServers": {"ingecad": connection}}, ensure_ascii=False, indent=2)
    vscode = json.dumps({"servers": {"ingecad": {"type": "stdio", **connection}}}, ensure_ascii=False, indent=2)
    toml = "[mcp_servers.ingecad]\ncommand = " + json.dumps(command, ensure_ascii=False) + "\nargs = " + json.dumps([script], ensure_ascii=False)
    missing = "" if connection_ready(connection) else "⚠ ไม่พบ python.exe หรือ server.py ตามเส้นทางนี้ ให้ติดตั้งตัวกลางใหม่ด้วย install.py\n\n"
    return intro + missing + f"""Claude Code — รันใน Terminal
claude mcp add --transport stdio --scope user ingecad -- {quote(command)} {quote(script)}

Codex CLI — รันใน Terminal
codex mcp add ingecad -- {quote(command)} {quote(script)}

Claude Desktop — รวม server นี้ใน %APPDATA%\\Claude\\claude_desktop_config.json แล้วเปิด Claude Desktop ใหม่
Cursor — %USERPROFILE%\\.cursor\\mcp.json (หรือ .cursor/mcp.json ในโครงการ)
Antigravity — MCP Servers → Manage MCP Servers → View raw config
ใช้ JSON นี้ โดยเพิ่ม ingecad ลงใน mcpServers เดิม เพื่อเก็บ server อื่นไว้
{block}

VS Code — .vscode/mcp.json ใช้คีย์ servers (ต่างจาก mcpServers)
{vscode}

Codex — %USERPROFILE%\\.codex\\config.toml
เพิ่มบล็อกนี้ถ้ายังไม่มี ingecad; หากมีแล้วให้แก้บล็อกเดิม
{toml}

Windsurf/Cascade — เปิดเมนู MCP → View raw config แล้วเพิ่ม ingecad ใน mcpServers
ใช้ command/args เดียวกับ JSON ด้านบน ตำแหน่งไฟล์ขึ้นกับรุ่นของโปรแกรม
AI client อื่น — เลือก Local/stdio แล้วใช้ command และ args ด้านบน

ตัวอย่างสั่ง AI
“เรียก list_sessions แล้วอ่าน get_status ของหน้าต่างแบบที่ฉันเลือก”
“อ่านหน่วยและเลเยอร์ก่อน แล้ววาดสี่เหลี่ยมขนาดที่ฉันระบุในเลเยอร์ใหม่”

เมื่อเชื่อมไม่ได้
• ไม่พบ session: เปิดเอกสารใน IngeCAD และกด Start bridge
• ไม่พบเครื่องมือ: ตรวจ command/args แล้วโหลด MCP ใหม่ใน AI client
• หลายหน้าต่าง: เรียก list_sessions ใหม่และเลือก session_id ให้ถูกต้อง
• ย้าย/ลบโฟลเดอร์ตัวกลาง: รัน install.py ใหม่ แล้วอัปเดตการตั้งค่าของ client

เปิด IngeCAD และ Bridge ค้างไว้ระหว่างใช้งาน เครื่องมือ CAD ตอบได้เมื่อโปรแกรมกำลังทำงาน
Stop bridge หยุดการเชื่อมต่อ MCP ของหน้าต่างนี้; แชทในแท็บ AI ยังเป็นอีกช่องทางหนึ่ง
การเชื่อมต่อนี้ไม่เปิดพอร์ต TCP และไม่ใช้ 127.0.0.1:4763 ของ IngeTrazo
AI client บนคลาวด์เข้าถึงตัวกลาง local stdio นี้โดยตรงไม่ได้
ตัวอย่างการตั้งค่าไม่ใช่การยืนยันว่าทดสอบ UI ของทุก client แล้ว

เอกสารอ้างอิงการตั้งค่า
Claude Code: https://code.claude.com/docs/en/mcp
Codex: https://developers.openai.com/codex/mcp
Cursor: https://prod.cursor.com/help/customization/mcp
VS Code: https://code.visualstudio.com/docs/agents/reference/mcp-configuration
Antigravity: https://antigravity.google/docs/mcp
Windsurf/Cascade: https://docs.windsurf.com/windsurf/cascade/mcp
"""
