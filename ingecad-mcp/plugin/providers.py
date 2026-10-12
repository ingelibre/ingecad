"""Provider adapters using stdlib HTTP. No logging or implicit retries of API calls."""
from __future__ import annotations
import json
import urllib.error
import urllib.parse
import urllib.request

PROVIDERS = {
    "Groq": ("https://api.groq.com/openai/v1", "chat", "https://console.groq.com/keys"),
    "OpenAI": ("https://api.openai.com/v1", "responses", "https://platform.openai.com/api-keys"),
    "Google Gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "chat", "https://aistudio.google.com/api-keys"),
    "Anthropic Claude": ("https://api.anthropic.com/v1", "anthropic", "https://platform.claude.com/settings/keys"),
    "OpenRouter": ("https://openrouter.ai/api/v1", "chat", "https://openrouter.ai/keys"),
    "Ollama (local)": ("http://127.0.0.1:11434/v1", "chat", "https://ollama.com"),
    "Custom (OpenAI-compatible)": ("", "chat", ""),
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Do not forward API credentials to redirected endpoints.


def valid_url(base):
    url = urllib.parse.urlsplit(base)
    if not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError("Base URL must be an absolute API endpoint without credentials, query or fragment")
    if url.scheme != "https" and not (url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost", "::1"}):
        raise ValueError("Use HTTPS, or HTTP only for a local endpoint")
    return base.rstrip("/")


def error_message(value):
    """Google gateways may wrap HTTP errors in an array, not an object."""
    if isinstance(value, list):
        return "; ".join(error_message(item) for item in value)
    if isinstance(value, dict):
        if "error" in value:
            return error_message(value["error"])
        if "message" in value:
            return str(value["message"])
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def gemini_model(model):
    return model.removeprefix("models/")


class Provider:
    def __init__(self, name, base, key="", protocol=None):
        if len(key) > 2560 or any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise ValueError("API key must be a single ASCII token without spaces or line breaks")
        self.name, self.base, self.key = name, valid_url(base), key
        self.protocol = protocol or PROVIDERS[name][1]

    def request(self, path, payload=None):
        headers = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "IngeCAD-AI/0.3.2"}
        if self.protocol == "anthropic":
            headers.update({"x-api-key": self.key, "anthropic-version": "2023-06-01"})
        elif self.key:
            headers["Authorization"] = "Bearer " + self.key
        data = None if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if data is not None and len(data) > 32*1024*1024:
            raise ValueError("Conversation exceeds 32 MiB. Start a new chat or send fewer images.")
        req = urllib.request.Request(self.base+path, data=data, headers=headers)
        try:
            with urllib.request.build_opener(NoRedirect).open(req, timeout=60) as reply:
                raw = reply.read(16*1024*1024+1)
                if len(raw) > 16*1024*1024:
                    raise ValueError("Provider response exceeds 16 MiB")
                try:
                    result = json.loads(raw)
                except ValueError:
                    raise RuntimeError("Provider returned invalid JSON") from None
                if not isinstance(result, dict):
                    message = error_message(result)
                    if self.key:
                        message = message.replace(self.key, "[redacted]")
                    raise RuntimeError("Provider returned an unexpected response: " + message[:1200])
                return result
        except urllib.error.HTTPError as exc:
            raw = exc.read(8192).decode("utf-8", errors="replace")
            if self.key:
                raw = raw.replace(self.key, "[redacted]")
            try:
                raw = error_message(json.loads(raw))
            except ValueError:
                pass
            raise RuntimeError(f"Provider HTTP {exc.code}: {raw[:1200]}") from None
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Cannot connect to provider: {exc.reason}") from None

    def models(self):
        data = self.request("/models")
        entries = data.get("data", [])
        if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
            raise RuntimeError("Provider returned an invalid model list")
        models = sorted({gemini_model(str(e["id"])) if self.name == "Google Gemini" else str(e["id"]) for e in entries if e.get("id")})
        if not models:
            raise ValueError("Provider returned no models; enter the model ID manually")
        return models

    def chat(self, model, messages, tools):
        if self.name == "Google Gemini":
            model = gemini_model(model)
        if self.protocol == "anthropic":
            payload = anthropic_payload(model, messages, tools)
            reply = self.request("/messages", payload)
            if reply.get("stop_reason") == "max_tokens":
                raise RuntimeError("Claude reached its response limit; no additional CAD calls were executed")
            parts = reply.get("content", [])
            calls = [{"id": x["id"], "type": "function", "function": {"name": x["name"], "arguments": json.dumps(x["input"])}} for x in parts if x["type"] == "tool_use"]
            if not calls and not any(x["type"] == "text" and x.get("text") for x in parts):
                raise RuntimeError("Claude returned no text or tool calls")
            return {"role": "assistant", "content": "\n".join(x["text"] for x in parts if x["type"] == "text"),
                    "tool_calls": calls, "_anthropic_content": parts}
        if self.protocol == "responses":
            reply = self.request("/responses", responses_payload(model, messages, tools))
            output = reply.get("output", [])
            calls = [{"id": x["call_id"], "type": "function", "function": {"name": x["name"], "arguments": x["arguments"]}} for x in output if x["type"] == "function_call"]
            texts = [p["text"] for x in output if x["type"] == "message" for p in x.get("content", []) if p["type"] in {"output_text", "refusal"} and "text" in p]
            refusals = [p["refusal"] for x in output if x["type"] == "message" for p in x.get("content", []) if p["type"] == "refusal" and "refusal" in p]
            if reply.get("status") in {"failed", "incomplete"}:
                raise RuntimeError("OpenAI response did not complete: " + str(reply.get("incomplete_details") or reply.get("error")))
            if not calls and not texts and not refusals:
                raise RuntimeError("OpenAI returned no text or tool calls")
            return {"role": "assistant", "content": "\n".join(texts+refusals), "tool_calls": calls, "_response_items": output}
        clean = [{k: v for k, v in m.items() if not k.startswith("_") and not (k == "tool_calls" and not v)} for m in messages]
        reply = self.request("/chat/completions", {"model": model, "messages": clean, "tools": tools, "stream": False})
        try:
            result = reply["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise RuntimeError("Provider returned no assistant message") from None
        if not isinstance(reply["choices"][0], dict) or not isinstance(result, dict):
            raise RuntimeError("Provider returned an invalid assistant message")
        if reply["choices"][0].get("finish_reason") == "length":
            raise RuntimeError("Provider reached its response limit; no additional CAD calls were executed")
        if not result.get("content") and not result.get("tool_calls"):
            raise RuntimeError("Provider returned no text or tool calls")
        normalized = {"role": "assistant", "content": result.get("content") or "", "tool_calls": result.get("tool_calls") or []}
        for key in ("reasoning_details", "reasoning_content", "extra_content"):
            if key in result:
                normalized[key] = result[key]
        return normalized


def responses_payload(model, messages, tools):
    items, instructions = [], []
    for m in messages:
        if m["role"] == "system":
            instructions.append(m["content"])
        elif m["role"] == "tool":
            items.append({"type": "function_call_output", "call_id": m["tool_call_id"], "output": m["content"]})
        elif m.get("_response_items"):
            items.extend(m["_response_items"])
        elif m["role"] == "user":
            content = m["content"]
            if isinstance(content, list):
                content = [{"type": "input_text", "text": p["text"]} if p["type"] == "text" else
                           {"type": "input_image", "image_url": p["image_url"]["url"]} for p in content]
            items.append({"role": "user", "content": content})
        else:
            items.append({"role": "assistant", "content": m["content"]})
    return {"model": model, "instructions": "\n".join(instructions), "input": items,
            "tools": [{"type": "function", **t["function"], "strict": False} for t in tools],
            "store": False, "include": ["reasoning.encrypted_content"]}


def anthropic_payload(model, messages, tools):
    converted, system = [], []
    for m in messages:
        if m["role"] == "system":
            system.append(m["content"])
            continue
        if m["role"] == "tool":
            part = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
            if converted and converted[-1]["role"] == "user" and isinstance(converted[-1]["content"], list):
                converted[-1]["content"].append(part)
            else:
                converted.append({"role": "user", "content": [part]})
            continue
        if m["role"] == "assistant":
            content = m.get("_anthropic_content") or [{"type": "text", "text": m["content"]}]
        elif isinstance(m["content"], list):
            content = []
            for p in m["content"]:
                if p["type"] == "text":
                    content.append(p)
                else:
                    header, data = p["image_url"]["url"].split(",", 1)
                    content.append({"type": "image", "source": {"type": "base64", "media_type": header[5:].split(";")[0], "data": data}})
        else:
            content = m["content"]
        converted.append({"role": m["role"], "content": content})
    return {"model": model, "max_tokens": 4096, "system": "\n".join(system), "messages": converted,
            "tools": [{"name": t["function"]["name"], "description": t["function"]["description"], "input_schema": t["function"]["parameters"]} for t in tools]}
