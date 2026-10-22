"""Verify the configured Codex server using standard MCP, then open the user's DXF."""
import asyncio
import json
import os
import tomllib
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path(os.environ.get("CODEX_HOME", str(Path.home()/".codex")))/"config.toml"
settings = tomllib.loads(CONFIG.read_text(encoding="utf-8"))["mcp_servers"]["ingecad"]


async def main():
    params = StdioServerParameters(command=settings["command"], args=settings.get("args", []))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            reply = await client.call_tool("list_sessions", {})
            data = reply.structuredContent or json.loads(reply.content[0].text)
            entries = data if isinstance(data, list) else data.get("result", [])
            assert entries
            source = ROOT.parent/"output"/"foundation_plan"/"foundation_plan_A3.dxf"
            reply = await client.call_tool("open_drawing", {"session_id": entries[0]["session_id"], "path": str(source)})
            assert not reply.isError, reply
            opened = reply.structuredContent or json.loads(reply.content[0].text)
            sid = opened["result"]["session_id"]
            reply = await client.call_tool("get_status", {"session_id": sid})
            status = (reply.structuredContent or json.loads(reply.content[0].text))["result"]
            assert "S-01_A3" in status["layouts"]
            dimensions = await client.call_tool("query_entities", {"session_id": sid, "type": "DIMENSION"})
            assert (dimensions.structuredContent or json.loads(dimensions.content[0].text))["result"]["total"] == 8
            await client.call_tool("switch_layout", {"session_id": sid, "name": "S-01_A3"})
            await client.call_tool("zoom_extents", {"session_id": sid})
            report = {"passed": True, "configured_server": "ingecad", "tools": len((await client.list_tools()).tools),
                      "document": str(source), "layout": "S-01_A3", "dimensions": 8, "session_id": sid}
    (ROOT/"test-output"/"registered-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))


asyncio.run(main())
