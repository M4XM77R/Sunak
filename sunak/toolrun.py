"""Tool runs: the model calls the tools of the MCP servers (sunak/mcp.py) in a loop.

Every call needs the user's click ("Allow", or "Allow in this chat").

Tool calling uses the native format of each backend (Claude tool use, Ollama `tools`, OpenAI
`tools`). Models without tool support fall back to a small text protocol (```tool blocks).
Pure standard library."""

import http.client
import json
import secrets
import threading
import time
import urllib.parse

from . import jobqueue, mcp, providers, usage
from .providers import ProviderError

MAX_STEPS = 30                    # model rounds per answer (a round is one answer with its tool calls)
MAX_RESULT = 30_000               # characters of one tool result sent to the model
CONFIRM_TIMEOUT = 1800            # an unanswered question counts as "deny" after 30 minutes
PING_EVERY = 15                   # keep-alive while waiting, also notices a closed browser tab
UI_OUTPUT = 4000                  # characters of a tool result shown in the browser and stored
UI_DIFF = 20_000


class ToolError(Exception):
    """A tool call failed; the message goes back to the model so it can correct itself."""


class Cancelled(Exception):
    """The user stopped the run."""


class ToolsUnsupported(Exception):
    """The backend rejected the request because the model cannot call tools."""


def _clip(text, limit, keep_end=False):
    if len(text) <= limit:
        return text
    if keep_end:
        half = limit // 2
        return text[:half] + f"\n… [{len(text) - limit} characters left out] …\n" + text[-half:]
    return text[:limit] + f"\n… [{len(text) - limit} more characters left out]"


class Action:
    """A prepared tool call. `kind` is "tool:<name>" (needs approval); `preview` is what the user sees
    before approving; `run()` does it and returns the result text."""

    def __init__(self, run, kind=None, preview=None):
        self.run, self.kind, self.preview = run, kind, preview or {}


# backends -------------------------------------------------------------------------------------

def _openai_tools(tools):
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                              "parameters": t["parameters"]}} for t in tools]


def _parse_args(raw):
    """Tool arguments as a dict, or (None, error) when the model sent broken JSON."""
    if isinstance(raw, dict):
        return raw, None
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return {}, None
    try:
        val = json.loads(raw)
    except (TypeError, ValueError):
        return None, f"The tool arguments were not valid JSON: {str(raw)[:300]}"
    return (val, None) if isinstance(val, dict) else (None, "The tool arguments must be a JSON object")


def _metered(turn):
    """Count the tokens of the model request one `turn(self, meter)` generator makes (usage.py). The generator tells the
    meter about each streamed chunk and about the backend's token numbers; the record is stored when the turn ends."""
    def wrapper(self):
        meter, ok = usage.Meter(self.p, getattr(self, "model", None) or getattr(self, "payload", {}).get("model")), True
        try:
            return (yield from turn(self, meter))
        except Exception:
            ok = False
            raise
        finally:
            meter.finish(ok)
    wrapper.__name__ = turn.__name__
    return wrapper


class ClaudeTurns:
    """Claude tool use over the Messages API: the assistant content (thinking with signature,
    text, tool_use) goes back unchanged, results come back as tool_result blocks."""

    def __init__(self, p, model, messages, options, tools):
        self.p = p
        self.payload, self.headers = providers.anthropic_payload(p, model, messages)
        official = urllib.parse.urlparse(providers._base(p)).hostname == "api.anthropic.com"
        self.payload["tools"] = [dict({"name": t["name"], "description": t["description"],
                                       "input_schema": t["parameters"]},
                                      **({"eager_input_streaming": True} if official else {})) for t in tools]

    @_metered
    def turn(self, meter):
        resp = providers._request(providers._base(self.p) + "/v1/messages", self.payload, extra_headers=self.headers)
        blocks, partial, stop = {}, {}, None
        with resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                ev = json.loads(line[5:].strip())
                kind = ev.get("type")
                if kind == "content_block_start":
                    blocks[ev["index"]] = dict(ev.get("content_block") or {})
                elif kind == "content_block_delta":
                    d = ev.get("delta") or {}
                    dt = d.get("type")
                    b = blocks.setdefault(ev.get("index", 0), {"type": "thinking" if dt == "thinking_delta" else "text"})
                    if dt == "text_delta" and d.get("text"):
                        b["text"] = b.get("text", "") + d["text"]
                        meter.tick()
                        yield "text", d["text"]
                    elif dt == "thinking_delta" and d.get("thinking"):
                        b["thinking"] = b.get("thinking", "") + d["thinking"]
                        meter.tick()
                        yield "think", d["thinking"]
                    elif dt == "signature_delta":
                        b["signature"] = b.get("signature", "") + d.get("signature", "")
                    elif dt == "input_json_delta":
                        meter.tick()
                        partial[ev.get("index", 0)] = partial.get(ev.get("index", 0), "") + d.get("partial_json", "")
                elif kind == "message_start":
                    usage.anthropic_usage(meter, (ev.get("message") or {}).get("usage"), start=True)
                elif kind == "message_delta":
                    usage.anthropic_usage(meter, ev.get("usage"))
                    stop = (ev.get("delta") or {}).get("stop_reason") or stop
                elif kind == "error":
                    err = ev.get("error") or {}
                    raise ProviderError(err.get("message") or "Claude API error")
                elif kind == "message_stop":
                    break
        if stop == "refusal":
            raise ProviderError("Claude declined to answer this request.")
        content, calls = [], []
        for idx in sorted(blocks):
            b = blocks[idx]
            if b.get("type") == "tool_use":
                args, err = _parse_args(partial.get(idx, ""))
                content.append({"type": "tool_use", "id": b["id"], "name": b["name"], "input": args or {}})
                calls.append({"id": b["id"], "name": b["name"], "args": args, "error": err})
            elif b.get("type") == "text":
                if b.get("text"):
                    content.append({"type": "text", "text": b["text"]})
            elif b.get("type") == "thinking":
                content.append({"type": "thinking", "thinking": b.get("thinking", ""), "signature": b.get("signature", "")})
            else:
                content.append(b)  # e.g. redacted_thinking: passed back as received
        if stop == "max_tokens" and calls:
            raise ProviderError("The answer hit the length limit in the middle of a tool call. Ask for smaller steps.")
        if content:
            self.payload["messages"].append({"role": "assistant", "content": content})
        return calls

    def add_results(self, results):
        self.payload["messages"].append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": r["id"], "content": r["content"], "is_error": r["is_error"]}
            for r in results]})


class OllamaTurns:
    """Ollama /api/chat with `tools`."""

    def __init__(self, p, model, messages, options, tools):
        self.p, self.model, self.options, self.tools = p, model, options or {}, tools
        self.msgs = [dict(m) for m in messages]

    @_metered
    def turn(self, meter):
        payload = {"model": self.model, "messages": self.msgs, "stream": True, "tools": _openai_tools(self.tools)}
        if "temperature" in self.options:
            payload["options"] = {"temperature": self.options["temperature"]}
        try:
            resp = providers._request(providers._base(self.p) + "/api/chat", payload, self.p.get("api_key", ""))
        except ProviderError as e:
            if "does not support tools" in str(e).lower():
                raise ToolsUnsupported from None
            raise
        text, raw_calls = [], []
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
                    meter.tick()
                    yield "think", msg["thinking"]
                if msg.get("content"):
                    text.append(msg["content"])
                    meter.tick()
                    yield "text", msg["content"]
                raw_calls += [c for c in msg.get("tool_calls") or [] if isinstance(c, dict)]
                if obj.get("done"):
                    usage.ollama_usage(meter, obj)
                    break
        out = {"role": "assistant", "content": "".join(text)}
        if raw_calls:
            out["tool_calls"] = raw_calls
        self.msgs.append(out)
        calls = []
        for i, c in enumerate(raw_calls):
            fn = c.get("function") or {}
            args, err = _parse_args(fn.get("arguments"))
            calls.append({"id": str(i), "name": str(fn.get("name") or ""), "args": args, "error": err})
        return calls

    def add_results(self, results):
        for r in results:
            self.msgs.append({"role": "tool", "content": r["content"], "tool_name": r["name"]})


class OpenAITurns:
    """OpenAI-compatible /chat/completions with `tools`; tool calls arrive in pieces per index."""

    def __init__(self, p, model, messages, options, tools):
        self.p, self.model, self.options, self.tools = p, model, options or {}, tools
        self.msgs = [dict(m) for m in messages]

    @_metered
    def turn(self, meter):
        payload = {"model": self.model, "messages": self.msgs, "stream": True, "tools": _openai_tools(self.tools)}
        if "temperature" in self.options:
            payload["temperature"] = self.options["temperature"]
        try:
            resp = providers.open_openai_stream(self.p, "/chat/completions", payload)
        except ProviderError as e:
            msg = str(e).lower()
            if msg.startswith(("http 400", "http 404", "http 422", "http 501")) and ("tool" in msg or "function" in msg):
                raise ToolsUnsupported from None
            raise
        text, parts = [], {}
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
                usage.openai_usage(meter, obj.get("usage"))
                for choice in obj.get("choices", []):
                    delta = choice.get("delta") or {}
                    think = delta.get("reasoning_content") or delta.get("reasoning")
                    if think:
                        meter.tick()
                        yield "think", think
                    if delta.get("content"):
                        text.append(delta["content"])
                        meter.tick()
                        yield "text", delta["content"]
                    for tc in delta.get("tool_calls") or []:
                        cur = parts.setdefault(tc.get("index", len(parts)), {"id": "", "name": "", "arguments": ""})
                        fn = tc.get("function") or {}
                        cur["id"] = tc.get("id") or cur["id"]
                        cur["name"] += fn.get("name") or ""
                        args = fn.get("arguments")
                        cur["arguments"] += json.dumps(args) if isinstance(args, dict) else (args or "")
        ordered = [parts[k] for k in sorted(parts)]
        for i, c in enumerate(ordered):
            c["id"] = c["id"] or f"call_{i}"
        out = {"role": "assistant", "content": "".join(text) or None}
        if ordered:
            out["tool_calls"] = [{"id": c["id"], "type": "function",
                                  "function": {"name": c["name"], "arguments": c["arguments"] or "{}"}} for c in ordered]
        elif out["content"] is None:
            out["content"] = ""
        self.msgs.append(out)
        calls = []
        for c in ordered:
            args, err = _parse_args(c["arguments"])
            calls.append({"id": c["id"], "name": c["name"], "args": args, "error": err})
        return calls

    def add_results(self, results):
        for r in results:
            self.msgs.append({"role": "tool", "tool_call_id": r["id"], "content": r["content"]})


TEXT_PROTOCOL = """You can use tools. To call one, write a block exactly like this and then stop writing:
```tool
{"tool": "read_file", "args": {"path": "README.md"}}
```
Use only one tool block per message. The result arrives in the next message. When you need no more tools, answer normally.

Tools:
"""
MARK = "```tool"


def _find_call(text):
    """Find a complete ```tool block. Returns (start, end, call) or None while it is incomplete."""
    i = text.find(MARK)
    if i < 0:
        return None
    j = i + len(MARK)
    while j < len(text) and text[j] in " \t\r\n":
        j += 1
    try:
        obj, end = json.JSONDecoder().raw_decode(text, j)
    except ValueError:
        return None
    rest = text[end:]
    stripped = rest.lstrip()
    if stripped.startswith("```"):
        end += len(rest) - len(stripped) + 3
    return i, end, obj


class TextTurns:
    """Fallback for models without tool calling: the model writes ```tool blocks into its text.
    The block is not shown as text; it appears as a step instead."""

    def __init__(self, p, model, messages, options, tools):
        self.p, self.model, self.options = p, model, options
        lines = []
        for t in tools:
            props = t["parameters"].get("properties") or {}
            req = t["parameters"].get("required") or []
            sig = ", ".join(k + ("" if k in req else "?") for k in props)
            lines.append(f"- {t['name']}({sig}): {t['description']}")
        proto = TEXT_PROTOCOL + "\n".join(lines)
        self.msgs = [dict(m) for m in messages]
        if self.msgs and self.msgs[0]["role"] == "system":
            self.msgs[0]["content"] += "\n\n" + proto
        else:
            self.msgs.insert(0, {"role": "system", "content": proto})

    def turn(self):
        gen = providers.chat_stream(self.p, self.model, self.msgs, self.options)
        buf, sent, found = "", 0, None
        try:
            for kind, c in gen:
                if kind != "text":
                    yield kind, c
                    continue
                buf += c
                found = _find_call(buf)
                if found:
                    break
                # hold back the start of a possible ```tool block until it is clear
                safe = buf.find(MARK)
                if safe < 0:
                    safe = len(buf)
                    for k in range(min(len(MARK) - 1, len(buf)), 0, -1):
                        if MARK.startswith(buf[-k:]):
                            safe = len(buf) - k
                            break
                if safe > sent:
                    yield "text", buf[sent:safe]
                    sent = safe
        finally:
            gen.close()
        calls = []
        if found:
            start, _, obj = found
            name = obj.get("tool") or obj.get("name") if isinstance(obj, dict) else None
            args = obj.get("args", obj.get("arguments", {})) if isinstance(obj, dict) else None
            args, err = _parse_args(args)
            calls.append({"id": "0", "name": str(name or ""), "args": args,
                          "error": err or (None if name else 'A tool block needs "tool" and "args"')})
            shown = buf[:start]
        else:
            shown = buf
            if MARK in buf:  # a tool block that never became valid JSON
                calls.append({"id": "0", "name": "", "args": None,
                              "error": "Could not read the tool block. Write valid JSON like the example."})
        if len(shown) > sent:
            yield "text", shown[sent:]
        self.msgs.append({"role": "assistant", "content": buf[:found[1]] if found else buf})
        return calls

    def add_results(self, results):
        self.msgs.append({"role": "user", "content": "\n\n".join(
            f"[Result of {r['name'] or 'tool'}{' (error)' if r['is_error'] else ''}]\n{r['content']}" for r in results)})


TURNS = {"anthropic": ClaudeTurns, "ollama": OllamaTurns, "openai": OpenAITurns}


# the tool loop --------------------------------------------------------------------------------

SYSTEM_PROMPT = ("You can use tools of the user's connected MCP servers (a tool's name starts with its server). "
                 "Every tool call needs the user's approval. If the user denies a call, do not try the same thing "
                 "another way; explain or ask instead. Never print secrets such as API keys.")


def new_run_id():
    return secrets.token_hex(8)


class ToolRun:
    """One answer with tools: alternate model turns and tool calls until the model stops calling tools.

    `emit(event)` sends NDJSON events to the browser: think/text chunks, step (a tool call starts),
    confirm (waiting for the user), step_done, notice, ping. `parts` collects text and steps in order
    for storing the answer."""

    def __init__(self, prov, model, messages, emit, options=None, allowed=None, mcp_tools=None, run_id=None):
        """`mcp_tools` is [(exposed name, server, tool)]."""
        self.id = run_id or new_run_id()
        self.prov, self.model, self.emit = prov, model, emit
        self.mcp = {name: (srv, tool) for name, srv, tool in mcp_tools or []}
        self.tools = [
            {"name": name, "description": str(tool.get("description") or tool.get("title") or tool["name"])[:1024],
             "parameters": mcp.schema(tool)} for name, (srv, tool) in self.mcp.items()]
        self.options = options or {}
        self.allowed = allowed if allowed is not None else set()
        self.cancelled = threading.Event()
        self.pending = {}
        self.parts = []
        self.texts = []
        self._steps = 0
        msgs = [dict(m) for m in messages]
        extra = SYSTEM_PROMPT
        if msgs and msgs[0]["role"] == "system":
            msgs[0]["content"] += "\n\n" + extra
        else:
            msgs.insert(0, {"role": "system", "content": extra})
        self.messages = msgs

    # called from other request threads
    def cancel(self):
        self.cancelled.set()
        for h in list(self.pending.values()):
            h["event"].set()

    def decide(self, step_id, decision):
        h = self.pending.get(step_id)
        if not h:
            return False
        h["decision"] = decision
        h["event"].set()
        return True

    def text(self):
        """The whole answer as stored in the chat (reasoning in <think> tags)."""
        return "\n\n".join(t for t in self.texts if t.strip())

    # the loop
    def run(self):
        ptype = self.prov["type"]
        turns = TURNS.get(ptype, TextTurns)(self.prov, self.model, self.messages, self.options, self.tools)
        first = True
        for _ in range(MAX_STEPS):
            try:
                calls = self._turn(turns)
            except ToolsUnsupported:
                if not first:
                    raise ProviderError("The model stopped accepting tool calls.") from None
                self.emit({"type": "notice", "t": "This model has no tool calling. Sunak uses a simple text "
                                                  "protocol instead; small models may get it wrong."})
                turns = TextTurns(self.prov, self.model, self.messages, self.options, self.tools)
                calls = self._turn(turns)
            first = False
            if not calls:
                return
            turns.add_results([self._step(c) for c in calls])
        self.emit({"type": "notice", "t": f"Stopped after {MAX_STEPS} steps. Send a message to let the model continue."})

    def _turn(self, turns):
        """One model call of the loop. It waits its turn when the backend is busy with other requests; the
        place in the queue is shown to the user. Waiting for the user's confirmation does not hold a place."""
        try:
            with jobqueue.slot(providers.queue_key(turns.p), providers.queue_slots(turns.p),
                               notify=lambda place: self.emit({"type": "queued", "position": place}),
                               cancelled=self.cancelled.is_set):
                return self._turn_inner(turns)
        except jobqueue.Cancelled:
            raise Cancelled from None
        except jobqueue.Timeout:
            raise ProviderError("The model was busy with other requests for too long. Please try again.") from None

    def _turn_inner(self, turns):
        from .server import stream_to_text
        chunks = []
        gen = turns.turn()
        try:
            while True:
                if self.cancelled.is_set():
                    raise Cancelled
                try:
                    kind, c = next(gen)
                except StopIteration as stop:
                    return stop.value or []
                chunks.append((kind, c))
                self.emit({"type": kind, "t": c})
        except (http.client.HTTPException, OSError, ValueError) as e:
            if isinstance(e, (BrokenPipeError, ConnectionResetError)):
                raise
            raise ProviderError(f"The connection to the model broke off ({type(e).__name__}: {e})") from None
        finally:
            gen.close()
            text = stream_to_text(chunks)
            if text.strip():
                self.texts.append(text)
                self.parts.append({"text": text})

    def _step(self, call):
        self._steps += 1
        sid = f"s{self._steps}"
        name, args = call["name"], call["args"]
        title = f"{self.mcp[name][0].name} · {self.mcp[name][1]['name']}" if name in self.mcp else name
        step = {"id": sid, "tool": name, "title": title, "status": "running"}
        self.parts.append({"step": step})
        self.emit({"type": "step", **step})
        try:
            if call.get("error"):
                raise ToolError(call["error"])
            if name in self.mcp:
                action = self._mcp_action(name, args)
            else:
                raise ToolError(f"Unknown tool {name}. Available tools: {', '.join(sorted(self.mcp))}")
            step.update(action.preview)
            if not self._approved(sid, action, step):
                step["status"] = "denied"
                result = ("The user denied this action. Do not try to do the same in another way; "
                          "continue without it or ask the user.")
            else:
                result = action.run()
                step["status"] = "done"
        except ToolError as e:
            step["status"] = "error"
            result = f"Error: {e}"
        except OSError as e:
            step["status"] = "error"
            result = f"Error: {type(e).__name__}: {e.strerror or e}"
        except Cancelled:
            step["status"] = "stopped"
            raise
        result = _clip(result, MAX_RESULT)
        step["output"] = _clip(result, UI_OUTPUT, keep_end=True)
        self.emit({"type": "step_done", **step})
        return {"id": call["id"], "name": name, "content": result, "is_error": step["status"] != "done"}

    def _mcp_action(self, name, args):
        """An MCP tool call; it always needs approval (kind "tool:<name>", allowed per tool)."""
        srv, tool = self.mcp[name]
        if not isinstance(args, dict):
            raise ToolError("Tool arguments must be a JSON object")
        missing = [k for k in mcp.schema(tool).get("required") or [] if k not in args]
        if missing:
            raise ToolError(f"{tool['name']} needs the argument {', '.join(map(str, missing))}")

        def run():
            try:
                text, is_error = srv.call(tool["name"], args, self.cancelled)
            except mcp.MCPError as e:
                if self.cancelled.is_set():
                    raise Cancelled from None
                raise ToolError(str(e)) from None
            if is_error:
                raise ToolError(text)
            return text

        shown = json.dumps(args, indent=2, ensure_ascii=False)
        return Action(run, f"tool:{name}", {"server": srv.name, "mcp_tool": tool["name"], "input": _clip(shown, UI_DIFF)})

    def _approved(self, sid, action, step):
        if action.kind in self.allowed:
            return True
        holder = {"event": threading.Event(), "decision": None}
        self.pending[sid] = holder
        try:
            self.emit({"type": "confirm", **step, "kind": action.kind})
            deadline = time.monotonic() + CONFIRM_TIMEOUT
            while not holder["event"].wait(PING_EVERY):
                if time.monotonic() > deadline:
                    break
                self.emit({"type": "ping"})
        finally:
            self.pending.pop(sid, None)
        if self.cancelled.is_set():
            raise Cancelled
        if holder["decision"] == "always":
            self.allowed.add(action.kind)
        return holder["decision"] in ("allow", "always")


class Registry:
    """Running tool answers (for confirm and cancel) and the per-chat "allow for this chat" choices.
    The choices live in memory only, so they end when Sunak restarts."""

    def __init__(self):
        self.runs = {}
        self._allowed = {}
        self._lock = threading.Lock()

    def allowed(self, session_id):
        """The kinds allowed for this chat."""
        with self._lock:
            return self._allowed.setdefault(session_id, set())

    def revoke(self, session_id):
        with self._lock:
            self._allowed.pop(session_id, None)

    def add(self, run):
        self.runs[run.id] = run

    def remove(self, run):
        self.runs.pop(run.id, None)

    def get(self, run_id):
        return self.runs.get(run_id)
