import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bridge_client import request, sessions
from server import BearerAuth


def session(root, heartbeat=None):
    sid = str(uuid.uuid4())
    folder = root/sid
    folder.mkdir()
    (folder/"session.json").write_text(json.dumps({"session_id": sid, "heartbeat": heartbeat or time.time()}))
    return sid, folder


def test_zero_and_multiple_sessions_require_explicit_target(tmp_path):
    with pytest.raises(RuntimeError, match="found 0"):
        asyncio.run(request("status", root=tmp_path))
    session(tmp_path)
    session(tmp_path)
    with pytest.raises(RuntimeError, match="found 2"):
        asyncio.run(request("status", root=tmp_path))


def test_dead_sessions_and_corrupt_descriptors_ignored(tmp_path):
    session(tmp_path, time.time()-20)
    _, folder = session(tmp_path)
    (folder/"session.json").write_text("{corrupt")
    assert sessions(tmp_path) == []


def test_timeout_cancels_queue_and_explains_unknown_outcome(tmp_path):
    sid, folder = session(tmp_path)
    with pytest.raises(TimeoutError, match="Outcome may be unknown"):
        asyncio.run(request("create_entities", {}, sid, timeout=.1, root=tmp_path))
    assert not list(folder.glob("*.request.json"))


def test_response_and_gui_error_propagate(tmp_path):
    sid, folder = session(tmp_path)

    async def run(ok):
        async def respond():
            while not list(folder.glob("*.request.json")):
                await asyncio.sleep(.01)
            p = next(folder.glob("*.request.json"))
            assert json.loads(p.read_text(encoding="utf-8"))["operation"] == "status"
            response = {"ok": True, "result": {"text": "บ้าน"}, "revision": 12} if ok else {"ok": False, "error": "Wrong space"}
            p.with_name(p.name.replace(".request.json", ".response.json")).write_text(json.dumps(response))
            p.unlink()
        task = asyncio.create_task(respond())
        try:
            return await request("status", session_id=sid, root=tmp_path, timeout=1)
        finally:
            await task
    assert asyncio.run(run(True))["result"]["text"] == "บ้าน"
    with pytest.raises(RuntimeError, match="Wrong space"):
        asyncio.run(run(False))


def test_nonfinite_json_rejected_before_enqueue(tmp_path):
    sid, folder = session(tmp_path)
    with pytest.raises(ValueError):
        asyncio.run(request("create_entities", {"coordinate": float("nan")}, sid, root=tmp_path))
    assert not list(folder.glob("*.request.json"))


def test_http_authentication(tmp_path):
    token = "a"*40
    async def run(authorization):
        out = []
        async def app(scope, receive, send):
            out.append("accepted")
        async def send(message):
            out.append(message)
        headers = [] if authorization is None else [(b"authorization", authorization)]
        await BearerAuth(app, token)({"type": "http", "headers": headers}, None, send)
        return out
    assert asyncio.run(run(("Bearer "+token).encode())) == ["accepted"]
    for value in [None, b"Bearer wrong"]:
        assert asyncio.run(run(value))[0]["status"] == 401
