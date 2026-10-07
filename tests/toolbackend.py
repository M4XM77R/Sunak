"""Scripted fake model backends (Claude, Ollama, OpenAI-compatible) that call the tools of the fake MCP server
(test_mcp.FAKE_STDIO, exposed as `Fake__echo` and so on). Used by test_toolrun.py and test_mcp.py."""

import json
import re
from http.server import BaseHTTPRequestHandler


class FakeToolBackend(BaseHTTPRequestHandler):
    """Scripted models. Each request answers according to how many tool results came back so far."""
    bodies = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        data = {"/api/tags": {"models": [{"name": "tool:1b"}, {"name": "notools:1b"}]},
                "/v1/models": {"data": [{"id": "gpt-tools"}]},
                "/anthropic/v1/models": {"data": [{"id": "claude-opus-5-5"}], "has_more": False}}.get(self.path)
        if data is None:
            return self.send_error(404)
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).bodies.append((self.path, body))
        msgs = body.get("messages", [])
        if self.path == "/api/chat" and body["model"] == "notools:1b" and "tools" in body:
            err = json.dumps({"error": "registry.ollama.ai/library/notools:1b does not support tools"}).encode()
            self.send_response(400)
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            return self.wfile.write(err)
        self.send_response(200)
        self.end_headers()
        if self.path == "/anthropic/v1/messages":
            return self.claude(body, msgs)
        if self.path == "/api/chat":
            try:
                return self.ollama(body, msgs)
            except (BrokenPipeError, ConnectionResetError):
                return  # the text protocol stops reading after the tool block
        if self.path == "/v1/chat/completions":
            return self.openai(body, msgs)

    def line(self, obj):
        self.wfile.write(json.dumps(obj).encode() + b"\n")
        self.wfile.flush()

    def sse(self, data):
        self.wfile.write(f"event: {data['type']}\ndata: {json.dumps(data)}\n\n".encode())
        self.wfile.flush()

    def claude(self, body, msgs):
        done = sum(1 for m in msgs if isinstance(m["content"], list) for b in m["content"] if b.get("type") == "tool_result")
        m = re.search(r"SCRIPT(\[.*?\])END", body.get("system", ""), re.S)
        script = json.loads(m.group(1)) if m else None
        calls = script or [["Fake__echo", {"text": "hi"}]]
        self.sse({"type": "message_start", "message": {"id": "m"}})
        if done < len(calls):
            self.sse({"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": "", "signature": ""}})
            self.sse({"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "plan"}})
            self.sse({"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": f"sig{done}"}})
            self.sse({"type": "content_block_stop", "index": 0})
            self.sse({"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}})
            self.sse({"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": f"Step {done}."}})
            self.sse({"type": "content_block_stop", "index": 1})
            name, args = calls[done]
            raw = json.dumps(args)
            self.sse({"type": "content_block_start", "index": 2,
                      "content_block": {"type": "tool_use", "id": f"tu{done}", "name": name, "input": {}}})
            for i in range(0, len(raw), 7):  # arguments arrive in pieces
                self.sse({"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": raw[i:i + 7]}})
            self.sse({"type": "content_block_stop", "index": 2})
            self.sse({"type": "message_delta", "delta": {"stop_reason": "tool_use"}})
        else:
            self.sse({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
            self.sse({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "All done."}})
            self.sse({"type": "message_delta", "delta": {"stop_reason": "end_turn"}})
        self.sse({"type": "message_stop"})

    def ollama(self, body, msgs):
        if body["model"] == "notools:1b":  # text protocol
            if msgs[-1]["content"].startswith("[Result of Fake__echo]"):
                return self.line({"message": {"content": "The tool said hi."}, "done": True})
            text = 'Let me read it.\n```tool\n{"tool": "Fake__echo", "args": {"text": "x"}}\n```\nInvented result!'
            for i in range(0, len(text), 5):
                self.line({"message": {"content": text[i:i + 5]}, "done": False})
            return self.line({"message": {"content": ""}, "done": True})
        done = sum(1 for m in msgs if m["role"] == "tool")
        if done == 0:
            self.line({"message": {"content": "", "tool_calls": [
                {"function": {"name": "Fake__echo", "arguments": {"text": "a"}}},
                {"function": {"name": "Fake__echo", "arguments": {}}}]}, "done": False})
            return self.line({"message": {"content": ""}, "done": True})
        if done == 2:
            self.line({"message": {"content": "", "tool_calls": [
                {"function": {"name": "Fake__echo", "arguments": {"text": "b"}}}]},
                "done": True})
            return
        self.line({"message": {"content": "Finished."}, "done": True})

    def openai(self, body, msgs):
        done = sum(1 for m in msgs if m["role"] == "tool")

        def data(obj):
            self.wfile.write(b"data: " + json.dumps(obj).encode() + b"\n\n")
            self.wfile.flush()
        if done == 0:
            args = json.dumps({"text": "42"})
            data({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "type": "function",
                                                          "function": {"name": "Fake__echo", "arguments": ""}}]}}]})
            for i in range(0, len(args), 9):
                data({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": args[i:i + 9]}}]}}]})
        else:
            data({"choices": [{"delta": {"content": "The answer is 42."}}]})
        self.wfile.write(b"data: [DONE]\n\n")
