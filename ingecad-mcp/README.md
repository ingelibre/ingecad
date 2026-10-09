# IngeCAD AI + MCP 0.3.2

รุ่น 0.3.2 แก้ตัวอ่าน error จากบริการ AI ที่ส่ง JSON เป็น array ซึ่งเดิมแสดง
`'list' object has no attribute 'get'` แทน HTTP status และข้อความต้นเหตุ
และปรับ Google Gemini ให้ตัด `models/` จากชื่อโมเดลก่อนส่งคำขอ
ผ่าน 28 unit tests และ GUI/CAD protocol fixtures; ยังไม่ได้ยืนยันคำขอจริงของเครื่องที่แจ้งปัญหา
ผู้ใช้ชุดติดตั้ง Windows 0.3.1 ใช้แพตช์ใน Release 0.3.2 ได้ โดยปิดโปรแกรมก่อนรัน UPDATE.cmd

ปลั๊กอินเชื่อม IngeCAD 0.6.5 กับ AI client ที่รองรับ Model Context Protocol (MCP)
มี MCP server แยกจากโปรแกรม และปลั๊กอินใน IngeCAD สำหรับทำงานบน GUI thread
พัฒนาและทดสอบบน Windows เครื่องนี้

## แท็บ AI ในโปรแกรม

ตั้งแต่รุ่น 0.3.0 มีแท็บ **AI** ใน sidebar และเมนู **IngeCAD AI + MCP → AI Assistant**
พิมพ์คำสั่ง `AI` เพื่อเปิดแท็บและขยาย sidebar; กดหัวข้อ connection เพื่อพับ/ขยายการตั้งค่า
ปุ่ม Send/Stop และ MCP อยู่ด้านล่างและมองเห็นตลอด แม้ส่วนตั้งค่าต้องเลื่อนบนจอเล็ก

1. เลือก Provider: Groq, OpenAI, Google Gemini, Anthropic Claude, OpenRouter, Ollama หรือ Custom
2. กรอก API Key ในช่องของโปรแกรม (Ollama ในเครื่องไม่ต้องใช้คีย์)
3. กด **Models** เพื่ออ่านรายการจริงจาก provider แล้วเลือกโมเดลที่รองรับ tool calling
4. กด **Test connection** เพื่อขอคำตอบสั้น ๆ จากโมเดลที่เลือก
5. พิมพ์คำสั่ง แล้วกด **Send** หรือ Enter; Shift+Enter ขึ้นบรรทัดใหม่

API Key แสดงเป็นจุดปิดบัง; เมื่อเลือกจำคีย์ จะเก็บใน **Windows Credential Manager**
ระบบไม่เก็บคีย์ใน QSettings, JSON config, log หรือ ZIP ใช้ปุ่มลบคีย์เพื่อลบของ provider/endpoint ปัจจุบัน
หากไม่เลือกจำคีย์ ใช้คีย์ในหน่วยความจำเฉพาะหน้าต่างนั้นและลบคีย์ที่เคยเก็บของ endpoint นั้น
การเปลี่ยน Provider หรือโมเดลเริ่มบทสนทนาใหม่ ข้อความ/ภาพของ provider ก่อนจะไม่ถูกส่งต่อไปอีกค่าย

**Photo…** แนบได้ 4 ภาพต่อข้อความ (ต้นฉบับไม่เกิน 20 MB/ภาพ) ย่อภาพไม่เกิน 1600 px ก่อนส่ง
เลือก **ส่งภาพ viewport** เมื่อต้องการให้ AI เห็นมุมมอง CAD ของข้อความนั้น
ภาพต้องใช้โมเดลที่รองรับ vision; โมเดลที่ไม่รองรับจะรายงานข้อผิดพลาดจาก API
เมื่อกด Send จะส่งข้อความ บริบทแบบ และผลคำสั่ง CAD ไปยัง provider ที่เลือก; ภาพส่งเฉพาะเมื่อแนบหรือเปิดตัวเลือก

AI ในโปรแกรมมีเครื่องมือ CAD 16 รายการจาก schema ของ MCP ตัวเดียวกัน
การสั่งงานทำบน GUI thread ผ่าน bridge; HTTP ทำใน worker thread เพื่อให้หน้าต่างตอบสนองได้
ไม่มีการรัน Python/shell ที่โมเดลแต่งขึ้นเอง AI ไม่ได้คำนวณออกแบบโครงสร้างหรือรับรองขนาดฐานราก
ปุ่ม **Stop** ยกเลิกการเรียก CAD เพิ่ม; คำขอเครือข่ายปัจจุบันอาจใช้เวลาจนหมด timeout 60 วินาที
งาน CAD ที่ทำแล้วคงอยู่และใช้ Undo ได้; หลังเกิดข้อผิดพลาดกลางงาน ให้ตรวจแบบก่อนส่งคำสั่งซ้ำ
ปิดหน้าต่างระหว่างงานจะสั่งหยุดและรอ worker จบก่อนปิดอย่างปลอดภัย

เลือก **อนุญาตเขียนทับไฟล์** เฉพาะเมื่อผู้ใช้ต้องการให้บันทึก/ส่งออกทับไฟล์เดิม
ระบบจำกัด 12 รอบ AI และ 60 tool calls ต่อข้อความ ไม่มีการ retry HTTP/คำสั่งแก้ไขอัตโนมัติ
API ใช้ HTTPS; HTTP ใช้ได้เฉพาะ localhost และไม่ส่งคีย์ตาม redirect

**สถานะการทดสอบ:** ทดสอบกับ IngeCAD/Qt จริงและ HTTP fixture ในเครื่องครบ 7 provider presets,
เก็บ/อ่าน/ลบคีย์ทดสอบใน Windows Credential Manager จริง, แนบภาพ/viewport, tool loop,
สร้างวัตถุและ A3/Title Block พร้อม DXF/PDF, Stop, revision/document guard และปุ่ม MCP
ยังไม่มี API Key ของผู้ใช้ จึง **ยังไม่ได้ทดสอบตอบกลับจากบริการ AI บนคลาวด์จริง**
ไฟล์ `test-ai/ai-verification.json` ระบุความต่างนี้ไว้ชัดเจน

OpenAI ใช้ Responses API; Anthropic ใช้ Messages API; provider อื่นใช้ Chat Completions ที่เข้ากันได้
เก็บ reasoning/thought-signature context ที่ API คืนไว้สำหรับวงจร tool calling โดยไม่แสดงในหน้าจอ
Custom รองรับ OpenAI-compatible Chat Completions; ตั้ง API Base URL เช่น `https://example.com/v1`
Ollama ใช้ `http://127.0.0.1:11434/v1` ต้องเปิดบริการและมีโมเดล tool/vision ที่ต้องการก่อน

อ้างอิง API: [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling),
[Groq API](https://console.groq.com/docs/api-reference), [Gemini compatibility](https://ai.google.dev/gemini-api/docs/openai),
[Claude Messages](https://platform.claude.com/docs/en/api/messages/create),
[OpenRouter](https://openrouter.ai/docs/api_reference/overview), [Ollama](https://docs.ollama.com/api/openai-compatibility)

## เริ่มใช้ในเครื่องนี้

ตัวติดตั้งเพิ่มปลั๊กอินที่ `%USERPROFILE%\.config\IngeCAD\plugins\ingecad_mcp` และสร้างไฟล์ตั้งค่า MCP ชื่อ `ingecad`
เปิด IngeCAD ใหม่เพื่อโหลดปลั๊กอิน และเริ่มแชท Codex ใหม่เพื่อโหลดรายการเครื่องมือ
ปลั๊กอินเริ่มอัตโนมัติเมื่อเปิด/สร้างเอกสาร พิมพ์ `MCPSTART` เพื่อเปิด หรือ `MCPSTOP` เพื่อหยุด
เมนู IngeCAD AI + MCP และส่วน AI bridge มีคำสั่ง Start/Stop เดียวกัน

ให้ AI เรียก `list_sessions` ก่อน แล้วใช้ `session_id` ของหน้าต่างที่ต้องการทุกครั้ง
เมื่อเปลี่ยนเอกสาร session_id จะเปลี่ยนเพื่อไม่ให้คำสั่งเก่าแก้ไขแบบใหม่
หากมีหลายหน้าต่าง ระบบไม่เลือกหน้าต่างให้เอง

## เชื่อม AI ค่ายอื่น

รุ่น 0.3.1 เพิ่มช่อง **วิธีเชื่อมต่อ MCP / ตั้งค่า AI client** ในแท็บ AI พร้อมปุ่ม **Copy คู่มือ MCP**
คู่มือแสดงสถานะ Bridge และ session_id ของหน้าต่างปัจจุบัน รวมทั้งคำสั่ง Claude Code/Codex,
JSON สำหรับ Claude Desktop/Cursor/Antigravity และ JSON/TOML แยกสำหรับ VS Code/Codex
เลื่อนอ่าน เลือกคัดลอกข้อความ หรือพับช่องคู่มือได้ ปุ่ม Copy คัดลอกคู่มือทั้งหมด
เส้นทางตัวกลางสร้างโดย `install.py` และเก็บในปลั๊กอินเป็น `connection.json` โดยไม่มี API Key
หากย้ายโฟลเดอร์แพ็กเกจ ให้รัน `install.py` ใหม่และปรับ MCP config ของ client
รูปแบบการตั้งค่าอ้างอิง [Claude Code](https://code.claude.com/docs/en/mcp),
[OpenAI Docs / Codex](https://developers.openai.com/codex/mcp),
[Cursor](https://prod.cursor.com/help/customization/mcp),
[VS Code](https://code.visualstudio.com/docs/agents/reference/mcp-configuration),
[Antigravity](https://antigravity.google/docs/mcp) และ
[Windsurf/Cascade](https://docs.windsurf.com/windsurf/cascade/mcp)
ตำแหน่งไฟล์ของ Windsurf/Cascade ขึ้นกับรุ่น จึงให้เปิด View raw config ภายใน client

นำค่า command/args จาก `client-config.json` ไปใส่ในหน้าตั้งค่า MCP ของ AI client
ไฟล์นี้ใช้รูปแบบ `mcpServers` ทั่วไป แต่ตำแหน่งไฟล์และชื่อคีย์ขึ้นกับ client
ตัว server ใช้มาตรฐาน MCP ไม่ผูกกับ API หรือ API key ของผู้ให้บริการ AI
ตรวจสอบ protocol จริงแล้วด้วย MCP Python client ทั้ง stdio และ Streamable HTTP
ยังไม่ได้ทดสอบ UI ของ AI client ทุกค่าย จึงรับรองเฉพาะ client ที่รองรับ MCP และเรียกกระบวนการนี้ได้

ChatGPT/AI ที่รันบนคลาวด์จะเข้าถึง localhost ของเครื่องนี้ไม่ได้โดยตรง
ยังไม่ได้ติดตั้ง tunnel หรือเผยแพร่ server บนอินเทอร์เน็ต

## เครื่องมือ 19 รายการ

| เครื่องมือ | งาน |
|---|---|
| list_sessions / get_status | อ่านหน้าต่าง เอกสาร หน่วย revision และประวัติ |
| get_drawing_tables | อ่านเลเยอร์ Text Style และ Dimension Style ที่มีในแบบ |
| open_drawing | เปิด DXF/DWG ในหน้าต่างใหม่และคืน session_id ใหม่ |
| query_entities | อ่านวัตถุพร้อม handle และ DXF attributes แบบแบ่งหน้า |
| create_layer | สร้างเลเยอร์และกำหนดสี ACI |
| create_text_style | สร้าง Text Style เช่น Tahoma สำหรับภาษาไทย |
| create_dimension_style | กำหนดขนาดข้อความ ลูกศร และตัวคูณการแสดงระยะ |
| create_entities | เส้น วงกลม polyline ข้อความ และ linear dimension |
| update_entities / delete_entities | แก้ไขหรือลบ handle ที่ระบุใน space ที่ระบุ |
| create_layout | A3/ขนาดอื่น กรอบ Title Block และ viewport ล็อกมาตราส่วน |
| switch_layout / zoom_extents | เลือก Model/Layout และปรับมุมมอง |
| undo / redo | ย้อนกลับ/ทำซ้ำรายการล่าสุดในประวัติของโปรแกรม |
| screenshot | ภาพ viewport เป็น MCP image content |
| save_drawing / export_pdf | DXF/DWG หรือ vector PDF ของ paper layout |

การวาด/แก้ไข/ลบ/สร้างตารางและ Layout ใช้ประวัติ Undo ของ IngeCAD
Undo อาจย้อนงานที่ผู้ใช้ทำเองล่าสุดด้วย ให้ตรวจสถานะก่อนใช้
ใช้ `expected_revision` กับคำสั่งแก้ไขเมื่อจำเป็นเพื่อปฏิเสธคำสั่งที่อ้างอิงแบบเก่า
พิกัดและขนาดวัตถุเป็นหน่วยของแบบ ส่วนขนาดกระดาษเป็น mm
Layout ตรวจหน่วย mm/cm/m ได้ หากแบบไม่มีหน่วย ต้องระบุ `model_unit_mm`
ตัวอย่างแบบ mm แสดงระยะเป็นเมตร: dimension style ใช้ `measurement_factor=0.001`
Text specs ระบุ `style`; dimension specs ระบุ `dimstyle` ที่สร้างไว้

## ติดตั้งซ้ำ / เครื่องใหม่

ต้องติดตั้ง IngeCAD พร้อม runtime Python/PySide6/ezdxf ของโปรแกรมก่อน

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe install.py --ingecad "$env:LOCALAPPDATA\Programs\IngeCAD"
```

ตัวติดตั้งเพิ่ม/อัปเดตเฉพาะปลั๊กอินผู้ใช้และเปิด enabled flag ไม่แก้ source ของ IngeCAD
สร้าง `client-config.json` ตามตำแหน่งติดตั้งปัจจุบัน จากนั้นโหลด config ใน AI client ที่ต้องการ
เครื่องนี้ใช้ venv Python 3.12 และ MCP SDK 1.30.0; `requirements-lock.txt` บันทึกรุ่นที่ทดสอบ
ไม่ได้ทดสอบ macOS/Linux หรือ IngeCAD รุ่นอื่น

## Streamable HTTP ในเครื่อง

```powershell
$env:INGECAD_MCP_TOKEN = 'สร้างโทเคนสุ่มความยาวอย่างน้อย32ตัวอักษรของคุณเอง'
.\.venv\Scripts\python.exe server.py --transport http --port 4765
```

URL `http://127.0.0.1:4765/mcp` และ header `Authorization: Bearer <token>`
ผูกเฉพาะ loopback ตรวจ Host/Origin ด้วย SDK และบังคับโทเคนทุก HTTP route
stdio ไม่ต้องใช้โทเคน กระบวนการและ file IPC เป็นสิทธิ์ของผู้ใช้ Windows คนเดียวกัน
โปรแกรมอื่นที่รันด้วยบัญชีเดียวกันเข้าถึง IPC ได้ ไม่ใช่ขอบเขตแยกสิทธิ์ระหว่างโปรแกรม
ไม่เก็บโทเคนจริงไว้ใน package

## การตรวจสอบและข้อจำกัด

`tests/live_mcp.py` เรียก MCP SDK จริงไปยังหน้าต่าง IngeCAD แยกสำหรับทดสอบ
ครอบคลุมการสร้าง/แก้ไข/ลบ/Undo/Redo, ภาษาไทย, dimension, A3, screenshot, PDF, DXF,
revision guard และป้องกันเขียนทับโดยไม่ได้ระบุ overwrite
`tests/test_client.py` ตรวจหลาย session, heartbeat, timeout, JSON และ HTTP auth
`tests/test_providers.py` ตรวจ endpoint, HTTP errors, redaction, redirect และ reasoning metadata
`tests/native_ai.py` ใช้ Python ของ IngeCAD ทดสอบแท็บ AI กับ Qt/CAD จริงและ HTTP fixtures
`tests/live_boundaries.py` ตรวจคำสั่งหมดอายุ คำสั่ง ID ซ้ำ และ session ที่เปลี่ยนเมื่อเปิดเอกสารใหม่
การเปิด DXF/DWG กลับในหน้าต่างใหม่ตรวจข้อความไทยและ paper viewport ผ่าน MCP แล้ว
ผลทดสอบและไฟล์ทดสอบอยู่ใน `test-output` บนเครื่องนี้

สำหรับทดสอบซ้ำ: เปิด `tests/native_host.py` ด้วย Python ของ IngeCAD พร้อม argument เป็น
absolute path ของ `test-output`; จากนั้นใช้ Python ของ MCP venv รัน `tests/live_mcp.py`
และ HTTP mode ด้วย `--http` เมื่อเปิด HTTP server ไว้ สุดท้ายรัน `tests/live_boundaries.py`
ใช้ไฟล์ `stop-host.txt` ใน `test-output` เพื่อปิดเฉพาะหน้าต่างของ test host
ก่อนเริ่มรอบใหม่ให้เอา stop-host.txt และ replacement-session.txt ของรอบก่อนออก
ทดสอบ unit tests ด้วย `python -m pytest tests/test_client.py -q` (ต้องมี pytest)
ใช้ `python generate_catalog.py` หลังเปลี่ยน schema ของ MCP แล้ว `python package.py` เพื่อสร้าง
`ingecad-ai-mcp-0.3.1.zip` โดยไม่รวม venv, IPC, โทเคนและผลทดสอบ

ไม่มีคำสั่งรัน Python/คำสั่ง shell อิสระจาก AI และไม่รองรับการคำนวณออกแบบโครงสร้าง
DWG ใช้ LibreDWG ของ IngeCAD คืน warnings จาก converter; text encoding ใน build นี้ใช้ cp874
เพื่อรองรับไทย อักษรที่เข้ารหัส cp874 ไม่ได้จะหยุดก่อนเขียน DWG ให้ใช้ DXF
DWG ยังมีข้อจำกัดของ converter เช่น alignment ของ TEXT บางแบบ ต้องตรวจไฟล์หลังแปลง
การเปิดไฟล์ บันทึกและ PDF ทำบน GUI thread จึงอาจหยุดตอบสนองชั่วคราวเมื่อแบบใหญ่
คำสั่งที่ timeout อาจสำเร็จไปแล้ว ระบบไม่ retry mutation เอง ให้ query แบบก่อนสั่งซ้ำ

หยุด/ถอนการใช้งาน: `MCPSTOP` หรือปิด IngeCAD MCP ใน Plugin Manager;
ลบการลงทะเบียน Codex ด้วย `codex mcp remove ingecad` หากต้องการ

อ้างอิง: [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk),
[MCP transport specification](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports),
[OpenAI MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)

License: GPL-3.0-or-later (IngeCAD plugin and connector sources).
