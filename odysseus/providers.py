"""Model backends: Ollama and any OpenAI-compatible API (OpenAI, OpenRouter,
LM Studio, llama.cpp server, vLLM, Groq, ...). Pure stdlib, streaming."""

import ipaddress
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 600  # long generations on slow CPUs are normal

THINK_RE = re.compile(r"<think>.*?(</think>|$)", re.S)


class ProviderError(Exception):
    pass


def default_providers():
    return [
        {
            "id": "ollama",
            "name": "Ollama (local)",
            "type": "ollama",
            "base_url": os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
            "api_key": "",
        }
    ]


def strip_think(text):
    return THINK_RE.sub("", text).strip()


_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _is_local(url):
    """Local / LAN backends must never go through a system HTTP proxy."""
    host = urllib.parse.urlparse(url).hostname or ""
    if host in ("localhost", "host.docker.internal") or host.endswith(".local") or "." not in host:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def _request(url, data=None, api_key="", timeout=TIMEOUT, method=None):
    headers = {"Content-Type": "application/json", "User-Agent": "odysseus-clone"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        if _is_local(url):
            return _DIRECT.open(req, timeout=timeout)
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        try:
            j = json.loads(detail)
            detail = j.get("error", {}).get("message") if isinstance(j.get("error"), dict) else j.get("error", detail)
        except ValueError:
            pass
        raise ProviderError(f"HTTP {e.code}: {detail}") from None
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise ProviderError(f"Cannot reach {url}: {reason}") from None


def _base(p):
    return p["base_url"].rstrip("/")


def list_models(p, timeout=4):
    """Return the model names a provider offers. Raises ProviderError."""
    if p["type"] == "ollama":
        with _request(_base(p) + "/api/tags", api_key=p.get("api_key", ""), timeout=timeout) as r:
            data = json.load(r)
        return sorted(m["name"] for m in data.get("models", []))
    with _request(_base(p) + "/models", api_key=p.get("api_key", ""), timeout=timeout) as r:
        data = json.load(r)
    return sorted(m["id"] for m in data.get("data", []))


def chat_stream(p, model, messages, options=None):
    """Yield ("text"|"think", chunk) tuples."""
    options = options or {}
    if p["type"] == "ollama":
        payload = {"model": model, "messages": messages, "stream": True}
        if "temperature" in options:
            payload["options"] = {"temperature": options["temperature"]}
        resp = _request(_base(p) + "/api/chat", payload, p.get("api_key", ""))
        with resp:
            for line in resp:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if obj.get("error"):
                    raise ProviderError(obj["error"])
                msg = obj.get("message") or {}
                if msg.get("thinking"):
                    yield "think", msg["thinking"]
                if msg.get("content"):
                    yield "text", msg["content"]
                if obj.get("done"):
                    break
        return

    payload = {"model": model, "messages": messages, "stream": True}
    if "temperature" in options:
        payload["temperature"] = options["temperature"]
    resp = _request(_base(p) + "/chat/completions", payload, p.get("api_key", ""))
    with resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            obj = json.loads(data)
            if obj.get("error"):
                err = obj["error"]
                raise ProviderError(err.get("message", str(err)) if isinstance(err, dict) else str(err))
            for choice in obj.get("choices", []):
                delta = choice.get("delta") or {}
                think = delta.get("reasoning_content") or delta.get("reasoning")
                if think:
                    yield "think", think
                if delta.get("content"):
                    yield "text", delta["content"]


def chat_once(p, model, messages, options=None):
    """Non-streaming helper: returns the full answer without reasoning."""
    return strip_think("".join(c for kind, c in chat_stream(p, model, messages, options) if kind == "text"))


def ollama_pull(p, model):
    """Yield progress dicts while Ollama downloads a model."""
    resp = _request(_base(p) + "/api/pull", {"model": model, "stream": True}, p.get("api_key", ""))
    with resp:
        for line in resp:
            line = line.strip()
            if line:
                obj = json.loads(line)
                if obj.get("error"):
                    raise ProviderError(obj["error"])
                yield obj


def ollama_delete(p, model):
    with _request(_base(p) + "/api/delete", {"model": model}, p.get("api_key", ""), method="DELETE"):
        pass
