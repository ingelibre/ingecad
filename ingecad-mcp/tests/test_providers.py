import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest

path = Path(__file__).resolve().parents[1]/"plugin"/"providers.py"
spec = importlib.util.spec_from_file_location("ingecad_provider_tests", path)
providers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(providers)


@pytest.fixture
def endpoint():
    state = {"requests": []}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            state["requests"].append(self.path)
            if self.path.startswith("/redirect"):
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/leak")
                self.end_headers()
                return
            if self.path.startswith("/array-error"):
                status, value = 400, [{"error":{"code":400,"message":"Invalid model fixture-secret","status":"INVALID_ARGUMENT"}}]
            elif self.path.startswith("/array-success"):
                status, value = 200, [{"error":{"message":"Unexpected fixture-secret"}}]
            elif self.path.startswith("/gemini"):
                status, value = 200, {"data":[{"id":"models/gemini-fixture"}]}
            else:
                status, value = (401, {"error": {"message": "invalid key fixture-secret"}}) if self.path.startswith("/error") else (200, {"data":[{"id":"b"},{"id":"a"},{"id":"a"}]})
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["payload"] = payload
            state["headers"] = dict(self.headers)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"choices":[{"message":{"content":"OK", "reasoning_details":[{"opaque":"signature"}], "tool_calls":[]}}]}).encode())
    server = ThreadingHTTPServer(("127.0.0.1",0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", state
    server.shutdown()
    server.server_close()


@pytest.mark.parametrize("url", ["http://outside.example/v1", "https://user:password@example.com/v1", "https://example.com/v1?key=x", "https://example.com/v1#secret", "file:///tmp/key", ""])
def test_unsafe_endpoints_rejected(url):
    with pytest.raises(ValueError):
        providers.valid_url(url)


def test_models_and_http_auth_error_redaction(endpoint):
    base, _ = endpoint
    assert providers.Provider("Groq",base,"fixture-secret").models() == ["a","b"]
    with pytest.raises(RuntimeError) as error:
        providers.Provider("Groq",base+"/error","fixture-secret").models()
    assert "401" in str(error.value) and "[redacted]" in str(error.value)
    assert "fixture-secret" not in str(error.value)


def test_redirect_does_not_forward_key(endpoint):
    base, state = endpoint
    with pytest.raises(RuntimeError, match="302"):
        providers.Provider("Groq",base+"/redirect","fixture-secret").models()
    assert state["requests"] == ["/redirect/models"]


def test_google_array_http_error_reports_original_status_and_message(endpoint):
    base, _ = endpoint
    with pytest.raises(RuntimeError) as caught:
        providers.Provider("Google Gemini", base+"/array-error", "fixture-secret").models()
    message = str(caught.value)
    assert "HTTP 400" in message and "Invalid model" in message
    assert "fixture-secret" not in message and "[redacted]" in message
    assert "has no attribute" not in message


def test_nonobject_success_response_has_readable_error(endpoint):
    base, _ = endpoint
    with pytest.raises(RuntimeError, match="unexpected response"):
        providers.Provider("Google Gemini", base+"/array-success").models()


def test_gemini_models_prefix_removed_from_discovery_and_chat(endpoint):
    base, state = endpoint
    provider = providers.Provider("Google Gemini", base+"/gemini", "fixture-secret")
    assert provider.models() == ["gemini-fixture"]
    provider.chat("models/gemini-fixture", [{"role":"user","content":"test"}], [])
    assert state["payload"]["model"] == "gemini-fixture"


@pytest.mark.parametrize("key", ["secret\nleak", "secret value", "秘密", "a"*2561])
def test_invalid_header_keys_do_not_appear_in_errors(key):
    with pytest.raises(ValueError) as error:
        providers.Provider("Groq","https://example.com/v1",key)
    assert key not in str(error.value)


def test_reasoning_details_preserved_and_private_fields_not_transmitted(endpoint):
    base, state = endpoint
    result = providers.Provider("OpenRouter",base,"fixture-secret").chat("fixture",[{"role":"assistant","content":"Hello","tool_calls":[],"_private":"not-wire"}],[])
    assert result["reasoning_details"] == [{"opaque":"signature"}]
    assert "_private" not in state["payload"]["messages"][0]
    assert "tool_calls" not in state["payload"]["messages"][0]
    assert state["headers"]["Authorization"] == "Bearer fixture-secret"


@pytest.mark.parametrize("protocol, reply", [
    ("responses", {"status":"incomplete","incomplete_details":{"reason":"max_output_tokens"}}),
    ("responses", {"status":"completed","output":[]}),
    ("anthropic", {"stop_reason":"max_tokens", "content":[]}),
    ("chat", {"choices":[{"finish_reason":"length","message":{"content":"partial","tool_calls":[]}}]}),
])
def test_incomplete_responses_fail_without_claiming_completion(protocol, reply):
    provider = providers.Provider("Groq","https://example.com/v1","",protocol=protocol)
    provider.request = lambda *args: reply
    with pytest.raises(RuntimeError):
        provider.chat("test",[{"role":"user","content":"draw"}],[])
