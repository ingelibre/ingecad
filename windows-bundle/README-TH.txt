IngeCAD AI Bundle — Windows x64 — 0.6.5 + AI/MCP 0.3.2

ชุดติดตั้ง Windows ที่จัดทำจาก IngeCAD source ไม่ใช่ตัวติดตั้ง Windows ทางการของผู้พัฒนา IngeCAD
รองรับเป้าหมาย Windows 10/11 64-bit มีกราฟิกที่รองรับ OpenGL

ติดตั้ง: เปิด IngeCAD-AI-Setup-0.6.5-0.3.2-x64.exe แล้วเลือกโฟลเดอร์
ค่าเริ่มต้น: %LOCALAPPDATA%\Programs\IngeCAD-AI
ติดตั้งสำหรับบัญชีผู้ใช้ปัจจุบัน ไม่ต้องติดตั้ง Python แยก ไม่ต้องใช้อินเทอร์เน็ตขณะติดตั้ง
มี Shortcut ที่ Desktop และ Start Menu และรายการถอนการติดตั้งใน Windows Apps

รวม IngeCAD 0.6.5, Python 3.12.10 embeddable, ไลบรารี Python/Qt,
LibreDWG 0.14.8597 ที่มีแพตช์ IngeCAD และ AI/MCP 0.3.2 พร้อมคู่มือในแท็บ AI
Python และตัวแปลง DWG อยู่ภายในโฟลเดอร์โปรแกรม เส้นทางตั้งใหม่อัตโนมัติเมื่อเปิดโปรแกรม

เริ่มใช้: เปิด Shortcut IngeCAD AI Bundle แล้วสร้าง/เปิดเอกสาร เข้าแท็บ AI
แชทในโปรแกรม: เลือก Provider กรอก API Key และเลือก Model ภายหลังได้
MCP: เปิด Bridge แล้วกด Copy คู่มือ MCP เพื่อนำคำสั่งไปเพิ่มใน AI client
ตัวติดตั้งสร้าง MCP-config\client-config.json, vscode-mcp.json, codex-config.toml และ commands.txt
ไฟล์เหล่านี้เป็นตัวอย่างเฉพาะเส้นทางเครื่องนี้ ให้นำ server ingecad ไปเพิ่มใน config ของ client
ไม่ได้เขียนทับ config เดิมของ Claude/Cursor/Codex หรือเก็บ API Key ในชุดแจก

สำหรับแจก: ส่งไฟล์ Setup EXE เดียวได้เลย พร้อม SHA256SUMS.txt สำหรับตรวจสอบ
ตัว Setup ยังไม่มีลายเซ็นดิจิทัล Windows อาจแสดง Unknown publisher
แพ็กเกจทดสอบบน Windows เครื่องนี้และโฟลเดอร์ชื่อไทย/มีช่องว่าง
ยังไม่ได้ยืนยันบนเครื่อง Windows ใหม่จริงทุกแบบ ควรลองเครื่องปลายทางหนึ่งเครื่องก่อนแจกวงกว้าง

ตรวจหลังติดตั้ง: install-check.json อยู่ในโฟลเดอร์โปรแกรม
บันทึกข้อผิดพลาดการเปิด: %LOCALAPPDATA%\IngeCAD-AI\launch-error.log
ถอน: Windows Settings → Apps → IngeCAD AI Bundle หรือ Uninstall.exe ในโฟลเดอร์โปรแกรม
ตัวถอนลบเฉพาะไฟล์ที่ชุดนี้ติดตั้ง ไม่ลบแบบ CAD ที่ผู้ใช้เพิ่มไว้หรือข้อมูล/คีย์ในบัญชีผู้ใช้

DWG ใช้ LibreDWG: ต้องตรวจแบบจริงหลังแปลง เพราะความเที่ยงตรงขึ้นกับวัตถุและรุ่น DWG
ซอร์ส IngeCAD และ AI/MCP อยู่ในชุดติดตั้ง; LibreDWG patched source อยู่ใน sources
รายละเอียดใบอนุญาตและแหล่งซอร์สเพิ่มเติมอยู่ใน THIRD-PARTY-NOTICES.txt และ runtime/site-packages

หากติดตั้งทับรุ่นของ bundle เดิมให้ปิด IngeCAD AI Bundle ก่อน
แพ็กเกจนี้ติดตั้งแยกจากโปรแกรม IngeCAD รุ่นที่คุณเคยลงเอง
