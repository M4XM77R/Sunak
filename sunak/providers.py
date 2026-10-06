"""Model backends: Ollama, Claude (Anthropic API) and any OpenAI-compatible API
(OpenAI, OpenRouter, LM Studio, llama.cpp server, vLLM, Groq, ...). Pure stdlib, streaming."""

import http.client
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
    """A backend could not be reached or returned an error. The message is shown to the user."""
    pass


def default_providers():
    """Providers used on first start: a local Ollama (address from OLLAMA_BASE_URL),
    plus Claude when ANTHROPIC_API_KEY is set."""
    out = [
        {
            "id": "ollama",
            "name": "Ollama (local)",
            "type": "ollama",
            "base_url": os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
            "api_key": "",
        }
    ]
    if os.environ.get("ANTHROPIC_API_KEY"):
        out.append({"id": "claude", "name": "Claude", "type": "anthropic", "base_url": ANTHROPIC_URL,
                    "api_key": os.environ["ANTHROPIC_API_KEY"]})
    return out


def strip_think(text):
    """Remove <think>…</think> reasoning blocks so they are not sent back to the model."""
    return THINK_RE.sub("", text).strip()


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects, but never send API keys to another host."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlparse(newurl).netloc != urllib.parse.urlparse(req.full_url).netloc:
            for h in list(new.headers):
                if h.lower() in ("authorization", "x-api-key"):
                    del new.headers[h]
        return new


_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}), _SafeRedirect)
_DEFAULT = urllib.request.build_opener(_SafeRedirect)


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


def _request(url, data=None, api_key="", timeout=TIMEOUT, method=None, extra_headers=None):
    """Open an HTTP request to a backend and return the response. Raises ProviderError.

    `api_key` is sent as a Bearer token; pass the key in `extra_headers` instead for APIs that use
    another header. Keys never appear in error messages."""
    headers = {"Content-Type": "application/json", "User-Agent": "sunak"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    headers.update(extra_headers or {})
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        if _is_local(url):
            return _DIRECT.open(req, timeout=timeout)
        return _DEFAULT.open(req, timeout=timeout)
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
    """Provider base URL without trailing slash."""
    return p["base_url"].rstrip("/")


def list_models(p, timeout=4):
    """Return the model names a provider offers. Raises ProviderError."""
    if p["type"] == "ollama":
        with _request(_base(p) + "/api/tags", api_key=p.get("api_key", ""), timeout=timeout) as r:
            data = json.load(r)
        return sorted(m["name"] for m in data.get("models", []))
    if p["type"] == "anthropic":
        return anthropic_models(p, timeout)
    with _request(_base(p) + "/models", api_key=p.get("api_key", ""), timeout=timeout) as r:
        data = json.load(r)
    return sorted(m["id"] for m in data.get("data", []))


def chat_stream(p, model, messages, options=None):
    """Yield ("text"|"think", chunk) tuples. Broken connections and malformed data from the
    backend raise ProviderError."""
    try:
        yield from _chat_stream(p, model, messages, options)
    except ProviderError:
        raise
    except (http.client.HTTPException, OSError, ValueError) as e:
        raise ProviderError(f"The connection to the model broke off ({type(e).__name__}: {e})") from None


def _with_images(messages, kind):
    """Messages in the backend's format for attached images (message["images"] = [{"type", "data"}]):
    Ollama wants base64 strings in "images", OpenAI-compatible APIs content parts with data URLs."""
    out = []
    for m in messages:
        m = dict(m)
        images = m.pop("images", None) or []
        if images and kind == "ollama":
            m["images"] = [i["data"] for i in images]
        elif images:
            m["content"] = ([{"type": "text", "text": m["content"]}] if m["content"] else []) + [
                {"type": "image_url", "image_url": {"url": f"data:{i['type']};base64,{i['data']}"}} for i in images]
        out.append(m)
    return out


def ollama_capabilities(p, model, timeout=5):
    """What Ollama says a model can do (e.g. ["completion", "vision"]), or None when it does not say."""
    try:
        with _request(_base(p) + "/api/show", {"model": model}, p.get("api_key", ""), timeout=timeout) as r:
            caps = json.load(r).get("capabilities")
    except (ProviderError, OSError, ValueError, AttributeError):
        return None
    return caps if isinstance(caps, list) else None


def _chat_stream(p, model, messages, options=None):
    options = options or {}
    if p["type"] == "anthropic":
        yield from anthropic_stream(p, model, messages)
        return
    if any(m.get("images") for m in messages):
        messages = _with_images(messages, p["type"])
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


def ollama_version(p, timeout=3):
    """Version string of a running Ollama. Raises ProviderError when it is not reachable."""
    with _request(_base(p) + "/api/version", api_key=p.get("api_key", ""), timeout=timeout) as r:
        return json.load(r).get("version", "")


def ollama_tags(p, timeout=4):
    """Installed Ollama models with size and details, sorted by name."""
    with _request(_base(p) + "/api/tags", api_key=p.get("api_key", ""), timeout=timeout) as r:
        data = json.load(r)
    out = []
    for m in data.get("models", []):
        d = m.get("details") or {}
        out.append({"name": m["name"], "size": m.get("size", 0), "modified": m.get("modified_at", ""),
                    "parameters": d.get("parameter_size", ""), "quantization": d.get("quantization_level", ""),
                    "family": d.get("family", "")})
    return sorted(out, key=lambda m: m["name"])


def ollama_ps(p, timeout=3):
    """Models Ollama has loaded right now, with how much of each sits in GPU memory (size_vram)."""
    with _request(_base(p) + "/api/ps", api_key=p.get("api_key", ""), timeout=timeout) as r:
        data = json.load(r)
    return [{"name": m.get("name", ""), "size": m.get("size") or 0, "size_vram": m.get("size_vram") or 0}
            for m in data.get("models", []) if isinstance(m, dict)]


def ollama_delete(p, model):
    """Delete a downloaded model from Ollama."""
    with _request(_base(p) + "/api/delete", {"model": model}, p.get("api_key", ""), method="DELETE"):
        pass


# Claude (Anthropic Messages API) ----------------------------------------------

ANTHROPIC_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
# Shown when the Models endpoint cannot be reached (it still needs a valid key to chat).
CLAUDE_FALLBACK_MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-4-5", "claude-fable-5-1"]
# Models that accept server-side refusal fallbacks with `fallbacks: "default"`.
_FALLBACK_MODELS = ("claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5")
_FAMILY_RE = re.compile(r"claude-(opus|sonnet|fable|mythos)-(\d+)(?:-(\d+))?(?:-|$)")


def _claude_headers(p):
    if not p.get("api_key"):
        raise ProviderError("Claude needs an API key. Add it in Settings → Providers.")
    return {"x-api-key": p["api_key"], "anthropic-version": ANTHROPIC_VERSION}


def adaptive_thinking(model):
    """True for models with adaptive thinking (Opus/Sonnet 4.6+, Fable, Mythos); Haiku and older don't have it."""
    m = _FAMILY_RE.match(model)
    if not m:
        return False
    major, minor = int(m.group(2)), int(m.group(3) or 0)
    return major >= 5 or (major == 4 and minor >= 6)


def anthropic_models(p, timeout=6):
    """Claude model ids from GET /v1/models; a built-in list if that endpoint is unreachable."""
    headers = _claude_headers(p)
    ids, after = [], None
    try:
        for _ in range(5):  # pages of 100
            q = "?limit=100" + (f"&after_id={urllib.parse.quote(after)}" if after else "")
            with _request(_base(p) + "/v1/models" + q, timeout=timeout, extra_headers=headers) as r:
                data = json.load(r)
            ids += [m["id"] for m in data.get("data", [])]
            if not data.get("has_more"):
                break
            after = data.get("last_id")
    except ProviderError as e:
        if "HTTP 401" in str(e) or "HTTP 403" in str(e):
            raise ProviderError("Claude rejected the API key. Check it in Settings → Providers.") from None
        return list(CLAUDE_FALLBACK_MODELS)
    return ids or list(CLAUDE_FALLBACK_MODELS)


def claude_max_tokens(model):
    """Output limit that every model of that generation accepts (streaming makes large limits safe)."""
    if model.startswith("claude-3-haiku"):
        return 4096
    if model.startswith("claude-3"):
        return 8192
    if re.match(r"claude-opus-4(-[01])?(-\d{8})?$", model):
        return 32000
    return 64000


def _blocks(content):
    return content if isinstance(content, list) else [{"type": "text", "text": content}]


def anthropic_payload(p, model, messages):
    """Request body for POST /v1/messages: system prompt moved to the top level, streaming on,
    summarized reasoning on models with adaptive thinking (temperature is not sent; current
    Claude models reject it)."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    chat = []
    for m in messages:
        images = m.get("images") or []
        if m["role"] == "system" or not (m["content"] or images):
            continue
        content = m["content"]
        if images:  # pictures first, then the question about them
            content = [{"type": "image", "source": {"type": "base64", "media_type": i["type"], "data": i["data"]}}
                       for i in images] + ([{"type": "text", "text": m["content"]}] if m["content"] else [])
        if chat and chat[-1]["role"] == m["role"]:  # the API needs alternating turns
            prev = chat[-1]["content"]
            if isinstance(prev, str) and isinstance(content, str):
                chat[-1]["content"] = prev + "\n\n" + content
            else:
                chat[-1]["content"] = _blocks(prev) + _blocks(content)
        else:
            chat.append({"role": m["role"], "content": content})
    payload = {"model": model, "max_tokens": claude_max_tokens(model), "stream": True, "messages": chat}
    if system:
        payload["system"] = system
    if adaptive_thinking(model):
        payload["thinking"] = {"type": "adaptive", "display": "summarized"}
    headers = _claude_headers(p)
    host = urllib.parse.urlparse(_base(p)).hostname
    if host == "api.anthropic.com" and model in _FALLBACK_MODELS:
        payload["fallbacks"] = "default"
        headers["anthropic-beta"] = "server-side-fallback-2026-07-01"
    return payload, headers


def anthropic_stream(p, model, messages):
    """Stream a Claude answer as ("think"|"text", chunk) tuples from the SSE event stream."""
    payload, headers = anthropic_payload(p, model, messages)
    resp = _request(_base(p) + "/v1/messages", payload, extra_headers=headers)
    with resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            ev = json.loads(line[5:].strip())
            kind = ev.get("type")
            if kind == "content_block_delta":
                delta = ev.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    yield "text", delta["text"]
                elif delta.get("type") == "thinking_delta" and delta.get("thinking"):
                    yield "think", delta["thinking"]
            elif kind == "message_delta":
                if (ev.get("delta") or {}).get("stop_reason") == "refusal":
                    raise ProviderError("Claude declined to answer this request.")
            elif kind == "error":
                err = ev.get("error") or {}
                raise ProviderError(err.get("message") or "Claude API error")
            elif kind == "message_stop":
                break
