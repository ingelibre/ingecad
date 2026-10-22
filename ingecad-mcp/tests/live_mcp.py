"""End-to-end MCP protocol test against the dedicated native GUI window."""
import asyncio
import json
import os
import sys
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/"test-output"
SID = (OUT/"host-ready.txt").read_text().strip()


async def verify(session, full):
    await session.initialize()
    names = {t.name for t in (await session.list_tools()).tools}
    assert {"list_sessions", "create_entities", "create_layout", "screenshot", "save_drawing"} <= names
    checks = ["MCP initialize", f"{len(names)} tools discovered"]

    async def call(tool_name, **kwargs):
        result = await session.call_tool(tool_name, {"session_id": SID, **kwargs})
        assert not result.isError, (tool_name, result)
        if result.structuredContent:
            data = result.structuredContent
        else:
            data = json.loads(result.content[0].text)
        return data

    status = (await call("get_status"))["result"]
    assert status["session_id"] == SID
    checks.append("native window status")
    if not full:
        assert (await call("query_entities"))["result"]["total"] == 4
        checks.append("HTTP reads real drawing")
        return checks
    await call("create_text_style", name="MCP_THAI")
    await call("create_layer", name="MCP_DRAWING")
    await call("create_dimension_style", name="MCP_DIM", text_style="MCP_THAI", text_height=180, arrow_size=120, measurement_factor=.001)
    tables = (await call("get_drawing_tables"))["result"]
    assert "MCP_DRAWING" in [e["name"] for e in tables["layers"]]
    assert "MCP_THAI" in [e["name"] for e in tables["text_styles"]]
    status = (await call("get_status"))["result"]
    created = await call("create_entities", expected_revision=status["revision"], entities=[
        {"type": "LINE", "start": [0,0], "end": [8000,0]},
        {"type": "CIRCLE", "center": [4000,4000], "radius": 500},
        {"type": "TEXT", "position": [0,5000], "text": "บ้าน 2 ชั้น กทม", "height": 250, "style": "MCP_THAI"},
        {"type": "DIMENSION", "start": [0,0], "end": [8000,0], "location": [0,-800], "angle": 0, "dimstyle": "MCP_DIM"}])
    handles = created["result"]["handles"]
    assert len(handles) == 4
    assert (await call("query_entities"))["result"]["total"] == 4
    checks.append("line/circle/Thai text/dimension batch")
    failed = await session.call_tool("create_entities", {"session_id": SID, "entities": [{"type":"LINE","start":[0,0],"end":[1,1]}], "expected_revision": status["revision"]})
    assert failed.isError
    failed = await session.call_tool("create_entities", {"session_id": SID, "entities": [{"type":"LINE","start":[0,0],"end":[1,1]}, {"type":"CIRCLE","center":[0,0],"radius":-1}]})
    assert failed.isError
    assert (await call("query_entities"))["result"]["total"] == 4
    checks.append("stale revision and invalid batch rejected without extra entities")
    await call("update_entities", handles=[handles[1]], attributes={"radius": 700})
    assert (await call("query_entities", type="CIRCLE"))["result"]["entities"][0]["attributes"]["radius"] == 700
    await call("undo")
    assert (await call("query_entities", type="CIRCLE"))["result"]["entities"][0]["attributes"]["radius"] == 500
    await call("redo")
    await call("delete_entities", handles=[handles[0]])
    assert (await call("query_entities"))["result"]["total"] == 3
    await call("undo")
    assert handles[0] in [e["handle"] for e in (await call("query_entities"))["result"]["entities"]]
    checks.append("update/delete/undo/redo and handle restoration")
    await call("create_layout", name="MCP_A3", project="บ้าน 2 ชั้น กทม", title="MCP verification", center=[4000,2500])
    await call("undo")
    assert "MCP_A3" not in (await call("get_status"))["result"]["layouts"]
    await call("redo")
    await call("switch_layout", name="MCP_A3")
    await call("zoom_extents")
    shot = await session.call_tool("screenshot", {"session_id": SID})
    assert not shot.isError and shot.content[0].type == "image"
    import base64
    (OUT/"native-layout.png").write_bytes(base64.b64decode(shot.content[0].data))
    await call("export_pdf", path=str(OUT/"MCP_A3.pdf"), layout="MCP_A3", overwrite=True)
    await call("save_drawing", path=str(OUT/"MCP_A3.dxf"), overwrite=True)
    blocked = await session.call_tool("save_drawing", {"session_id": SID, "path": str(OUT/"MCP_A3.dxf")})
    assert blocked.isError
    checks.append("A3 layout/title block, layout undo/redo, screenshot, vector PDF and DXF; overwrite guard")
    dwg = await call("save_drawing", path=str(OUT/"MCP_A3.dwg"), overwrite=True)
    checks.append("DWG saved using IngeCAD converter; warnings: " + str(dwg["result"]["warnings"]))
    for extension in ["dxf", "dwg"]:
        opened = await call("open_drawing", path=str(OUT/f"MCP_A3.{extension}"))
        new_id = opened["result"]["session_id"]
        query = await session.call_tool("query_entities", {"session_id": new_id, "type": "TEXT"})
        assert not query.isError
        data = query.structuredContent or json.loads(query.content[0].text)
        assert data["result"]["entities"][0]["attributes"]["text"] == "บ้าน 2 ชั้น กทม"
        layout = await session.call_tool("query_entities", {"session_id": new_id, "space": "MCP_A3", "type": "VIEWPORT"})
        assert not layout.isError
        data = layout.structuredContent or json.loads(layout.content[0].text)
        assert data["result"]["entities"]
    ambiguous = await session.call_tool("get_status", {})
    assert ambiguous.isError
    checks.append("DXF/DWG reopened in new windows; Thai text and viewport read through MCP; ambiguous target rejected")
    return checks


async def main():
    if "--http" in sys.argv:
        import httpx
        async with httpx.AsyncClient(headers={"Authorization": "Bearer "+os.environ["INGECAD_MCP_TOKEN"]}) as client:
            async with streamable_http_client("http://127.0.0.1:4765/mcp", http_client=client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    checks = await verify(session, False)
        async with httpx.AsyncClient() as client:
            denied = await client.post("http://127.0.0.1:4765/mcp", json={})
            assert denied.status_code == 401
        checks.append("missing bearer token rejected with 401")
        name = "http-verification.json"
    else:
        args = StdioServerParameters(command=sys.executable, args=[str(ROOT/"server.py")])
        async with stdio_client(args) as (read, write):
            async with ClientSession(read, write) as session:
                checks = await verify(session, True)
        name = "stdio-verification.json"
    report = {"passed": True, "session_id": SID, "checks": checks}
    (OUT/name).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


asyncio.run(main())
