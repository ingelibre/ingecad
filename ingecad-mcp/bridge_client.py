"""Dependency-free asynchronous local bridge client."""
import asyncio
import json
import os
import time
import uuid
from pathlib import Path

ROOT = Path(os.environ.get("INGECAD_MCP_ROOT") or str(Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".cache"))) / "IngeCAD-MCP"))


def sessions(root=ROOT):
    result = []
    for path in root.glob("*/session.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("session_id") == path.parent.name and time.time() - data["heartbeat"] < 10:
                result.append(data)
        except (OSError, ValueError, KeyError):
            pass
    return sorted(result, key=lambda s: s["session_id"])


async def request(operation, arguments=None, session_id=None, timeout=45, root=ROOT):
    available = sessions(root)
    if session_id is None:
        if len(available) != 1:
            raise RuntimeError(f"Expected exactly one live IngeCAD session, found {len(available)}. Call list_sessions and pass session_id; open IngeCAD and run MCPSTART if none.")
        session_id = available[0]["session_id"]
    if session_id not in {s["session_id"] for s in available}:
        raise RuntimeError("Session unavailable or heartbeat expired")
    # Never accept arbitrary filesystem traversal through a session identifier.
    if str(uuid.UUID(session_id)) != session_id:
        raise ValueError("Invalid session identifier")
    rid = str(uuid.uuid4())
    folder = root / session_id
    path = folder / f"{rid}.request.json"
    response = folder / f"{rid}.response.json"
    payload = json.dumps({"id": rid, "deadline": time.time()+timeout,
                          "operation": operation, "arguments": arguments or {}}, ensure_ascii=False, allow_nan=False)
    if len(payload.encode("utf-8")) > 4*1024*1024:
        raise ValueError("Request exceeds 4 MiB")
    temp = path.with_suffix(".tmp")
    temp.write_text(payload, encoding="utf-8")
    os.replace(temp, path)
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        if response.exists():
            data = json.loads(response.read_text(encoding="utf-8"))
            if not data["ok"]:
                raise RuntimeError(data["error"])
            return data
        await asyncio.sleep(0.05)
    # Cancel only queued work. Executing work may have completed; never retry a mutation blindly.
    path.unlink(missing_ok=True)
    raise TimeoutError(f"IngeCAD request {rid} timed out. Outcome may be unknown; query the drawing before retrying a mutation. Retained response: {response}")
