"""Verify request expiry, duplicate IDs and document-session replacement in native GUI."""
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/"test-output"
sys.path.insert(0, str(ROOT))
from bridge_client import ROOT as IPC_ROOT
SID = (OUT/"host-ready.txt").read_text().strip()


async def main():
    async with stdio_client(StdioServerParameters(command=sys.executable, args=[str(ROOT/"server.py")])) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()

            async def query(sid=SID):
                reply = await client.call_tool("query_entities", {"session_id": sid})
                assert not reply.isError, reply
                return (reply.structuredContent or json.loads(reply.content[0].text))["result"]

            before = (await query())["total"]
            folder = IPC_ROOT/SID

            async def raw(rid, deadline):
                path = folder/f"{rid}.request.json"
                temp = path.with_suffix(".tmp")
                temp.write_text(json.dumps({"id": rid, "deadline": deadline, "operation": "create_entities",
                    "arguments": {"entities": [{"type": "LINE", "start": [0,0], "end": [1,1]}]}}))
                os.replace(temp, path)
                response = folder/f"{rid}.response.json"
                end = time.monotonic()+5
                while time.monotonic() < end:
                    if response.exists() and not path.exists():
                        return json.loads(response.read_text(encoding="utf-8"))
                    await asyncio.sleep(.05)
                raise AssertionError("No native IPC response")

            expired = await raw(str(uuid.uuid4()), time.time()-10)
            assert not expired["ok"] and "expired" in expired["error"]
            assert (await query())["total"] == before
            rid = str(uuid.uuid4())
            assert (await raw(rid, time.time()+5))["ok"]
            assert (await query())["total"] == before+1
            assert (await raw(rid, time.time()+5))["ok"]
            assert (await query())["total"] == before+1
            await client.call_tool("undo", {"session_id": SID})
            assert (await query())["total"] == before
            (OUT/"replace-document.txt").write_text("replace dedicated test drawing")
            end = time.monotonic()+10
            while time.monotonic() < end and not (OUT/"replacement-session.txt").exists():
                await asyncio.sleep(.1)
            new_id = (OUT/"replacement-session.txt").read_text().strip()
            assert new_id != SID
            assert not (folder/"session.json").exists()
            stale = await client.call_tool("create_entities", {"session_id": SID, "entities": [{"type": "LINE", "start": [0,0], "end": [100,100]}]})
            assert stale.isError
            assert (await query(new_id))["total"] == 0
    report = {"passed": True, "checks": ["expired mutation never executes", "duplicate request ID executes once", "document replacement rotates session", "old session mutation rejected; replacement remains empty"]}
    (OUT/"boundaries-verification.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


asyncio.run(main())
