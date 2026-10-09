IngeCAD AI/MCP 0.3.2 — แพตช์สำหรับ IngeCAD AI Bundle 0.3.1

แก้ตัวอ่าน error ของบริการ AI ที่ส่ง JSON เป็น list ทำให้แสดง "'list' object has no attribute 'get'"
ปรับให้เห็น HTTP status และข้อความ error เดิม พร้อมปิดบังคีย์
ปรับ Google Gemini: ตัด models/ จากชื่อโมเดลก่อนส่งคำขอ
แพตช์นี้ไม่ได้รับรองว่าคีย์ โควตา โมเดล หรือ schema ของคำขอจริงจะผ่านทุกกรณี
หากบริการยังปฏิเสธคำขอ จะเห็นข้อความที่ใช้วิเคราะห์สาเหตุได้

วิธีอัปเดตเครื่องที่ติดตั้งแล้ว
1. ปิด IngeCAD และ AI client ที่เชื่อม MCP
2. แตก ZIP ทั้งโฟลเดอร์
3. ดับเบิลคลิก UPDATE.cmd แล้วอ่านผลว่าขึ้น Updated
4. เปิด IngeCAD ใหม่ กดแชทใหม่ และ Test connection แล้วลองคำสั่งวาดอีกครั้ง
ไม่ต้องส่ง API Key ในแชท

ตัวอัปเดตค้นหาเส้นทางจากรายการติดตั้งของ Windows และเปลี่ยนเฉพาะไฟล์ปลั๊กอิน
ไม่ได้ลบแบบ CAD, API Key, การตั้งค่า Provider หรือ connection.json ของเครื่อง
ถ้าติดตั้งไว้ที่อื่นและตัวอัปเดตหาไม่พบ:
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Update-IngeCAD.ps1 -IngeCADDirectory "D:\Your IngeCAD-AI"

ผ่าน 28 unit tests รวม HTTP error แบบ array และ Gemini model prefix
ผ่าน Qt/CAD และการเรียก HTTP fixtures ในหน้าต่างจริง
ยังไม่ได้ทดสอบด้วยคีย์ Gemini ของเครื่องที่รายงานปัญหา
License: GPL-3.0-or-later. LICENSE included.
