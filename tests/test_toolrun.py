"""Tools in the chat: the tool loop against fake Claude, Ollama and OpenAI-compatible backends (native tool calls and
the text protocol) calling a fake MCP server, with approve/deny/cancel, and the endpoints that are gone."""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from sunak import toolrun
from sunak.server import make_server

import test_mcp
from toolbackend import FakeToolBackend


class ParserTest(unittest.TestCase):
    def test_text_protocol_parser(self):
        self.assertIsNone(toolrun._find_call('hi ```tool\n{"tool": "Fake__echo", "args": {"te'))
        s, e, obj = toolrun._find_call('hi ```tool\n{"tool": "x", "args": {"c": "``` inside"}}\n```\nafter')
        self.assertEqual(obj["args"]["c"], "``` inside")
        self.assertEqual('hi ```tool\n{"tool": "x", "args": {"c": "``` inside"}}\n```\nafter'[e:], "\nafter")

    def test_arguments(self):
        self.assertEqual(toolrun._parse_args('{"a": 1}'), ({"a": 1}, None))
        self.assertEqual(toolrun._parse_args(""), ({}, None))
        self.assertIsNone(toolrun._parse_args("{broken")[0])
        self.assertIsNone(toolrun._parse_args("[1]")[0])


class ToolServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = ThreadingHTTPServer(("127.0.0.1", 0), FakeToolBackend)
        threading.Thread(target=cls.backend.serve_forever, daemon=True).start()
        bp = cls.backend.server_address[1]
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        script = os.path.join(cls.tmp.name, "fake mcp.py")
        with open(script, "w") as f:
            f.write(test_mcp.FAKE_STDIO)
        cls.data = os.path.join(cls.tmp.name, "data")
        cls.srv = make_server("127.0.0.1", 0, cls.data)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.app = cls.srv.RequestHandlerClass.app
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        cls.call("PUT", "/api/settings", {
            "mcp_servers": [{"name": "Fake", "type": "stdio", "command": test_mcp.command_line(script)}],
            "providers": [
                {"id": "ollama", "name": "Ollama", "type": "ollama", "base_url": f"http://127.0.0.1:{bp}"},
                {"id": "cloud", "name": "Cloud", "type": "openai", "base_url": f"http://127.0.0.1:{bp}/v1"},
                {"id": "claude", "name": "Claude", "type": "anthropic", "base_url": f"http://127.0.0.1:{bp}/anthropic",
                 "api_key": "sk-test"}]})

    @classmethod
    def tearDownClass(cls):
        cls.app.mcp.close_all()
        for s in (cls.srv, cls.backend):
            s.shutdown()
            s.server_close()
        cls.tmp.cleanup()

    def setUp(self):
        FakeToolBackend.bodies = []

    @classmethod
    def call(cls, method, path, body=None):
        req = urllib.request.Request(cls.base + path, json.dumps(body).encode() if body is not None else None,
                                     {"Content-Type": "application/json", "X-Requested-With": "sunak"}, method=method)
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)

    def run_tools(self, model, content="Do it", decide=lambda ev: "allow", session=None, system=""):
        """Run /api/tools, answer each confirm with decide(event), return the chat and all events."""
        s = session or self.call("POST", "/api/sessions", {"system": system})
        req = urllib.request.Request(self.base + "/api/tools", json.dumps(
            {"session_id": s["id"], "model": model, "content": content}).encode(),
            {"Content-Type": "application/json", "X-Requested-With": "sunak"}, method="POST")
        events, run = [], None
        with urllib.request.urlopen(req, timeout=30) as r:
            for line in r:
                ev = json.loads(line)
                events.append(ev)
                if ev["type"] == "start":
                    run = ev["run"]
                if ev["type"] == "confirm":
                    d = decide(ev)
                    if d == "cancel":
                        self.call("POST", "/api/tools/cancel", {"run": run})
                    else:
                        self.call("POST", "/api/tools/confirm", {"run": run, "id": ev["id"], "decision": d})
        return s, events

    def text(self, events):
        return "".join(e["t"] for e in events if e["type"] == "text")

    def test_claude_calls_a_tool_after_approval(self):
        s, events = self.run_tools("claude::claude-opus-5-5")
        confirm = next(e for e in events if e["type"] == "confirm")
        self.assertEqual((confirm["kind"], confirm["title"]), ("tool:Fake__echo", "Fake · echo"))
        self.assertEqual(events[-1], {"type": "done", "stopped": False})
        self.assertEqual(self.text(events), "Step 0.All done.")
        # the second request carries the signed thinking block, the tool_use and the tool_result
        path, body = FakeToolBackend.bodies[-1]
        self.assertNotIn("eager_input_streaming", body["tools"][0])  # only on api.anthropic.com
        assistant, result = body["messages"][-2:]
        self.assertEqual(assistant["content"][0], {"type": "thinking", "thinking": "plan", "signature": "sig0"})
        self.assertEqual(assistant["content"][2], {"type": "tool_use", "id": "tu0", "name": "Fake__echo", "input": {"text": "hi"}})
        self.assertEqual(result["content"][0]["tool_use_id"], "tu0")
        self.assertFalse(result["content"][0]["is_error"])
        # stored with its steps
        msg = self.call("GET", f"/api/sessions/{s['id']}")["messages"][-1]
        parts = msg["meta"]["tools"]["parts"]
        self.assertEqual(parts[1]["step"]["status"], "done")
        self.assertEqual(parts[1]["step"]["tool"], "Fake__echo")
        self.assertIn("All done.", msg["content"])

    def test_deny_and_allow_in_this_chat(self):
        script = "SCRIPT" + json.dumps([["Fake__echo", {"text": "a"}], ["Fake__echo", {"text": "b"}]]) + "END"
        s, events = self.run_tools("claude::claude-opus-5-5", decide=lambda ev: "deny", system=script)
        self.assertEqual([e["status"] for e in events if e["type"] == "step_done"], ["denied", "denied"])
        self.assertTrue(FakeToolBackend.bodies[1][1]["messages"][-1]["content"][0]["is_error"])
        # "always" covers the next calls in this chat without asking
        asked = []
        self.run_tools("claude::claude-opus-5-5", session=s, decide=lambda ev: asked.append(1) or "always")
        self.assertEqual(len(asked), 1)
        self.call("POST", "/api/tools/revoke", {"session_id": s["id"]})
        asked.clear()
        self.run_tools("claude::claude-opus-5-5", session=s, decide=lambda ev: asked.append(1) or "deny")
        self.assertEqual(len(asked), 2)

    def test_ollama_tools_and_a_bad_call(self):
        s, events = self.run_tools("ollama::tool:1b")
        done = [e for e in events if e["type"] == "step_done"]
        self.assertEqual([e["status"] for e in done], ["done", "error", "done"])
        self.assertEqual(done[0]["output"], "echo: a")
        self.assertIn("needs the argument text", done[1]["output"])
        tool_msgs = [m for m in FakeToolBackend.bodies[-1][1]["messages"] if m["role"] == "tool"]
        self.assertEqual(tool_msgs[0]["tool_name"], "Fake__echo")
        self.assertEqual(tool_msgs[0]["content"], "echo: a")
        self.assertEqual(self.text(events), "Finished.")

    def test_text_protocol_fallback(self):
        s, events = self.run_tools("ollama::notools:1b")
        self.assertTrue(any(e["type"] == "notice" for e in events))
        self.assertEqual(self.text(events), "Let me read it.\nThe tool said hi.")
        self.assertNotIn("Invented", json.dumps(events))
        last = FakeToolBackend.bodies[-1][1]
        self.assertNotIn("tools", last)
        self.assertIn("```tool", last["messages"][0]["content"])
        self.assertTrue(last["messages"][-1]["content"].startswith("[Result of Fake__echo]\necho: x"))

    def test_openai_calls_a_tool(self):
        s, events = self.run_tools("cloud::gpt-tools")
        step = next(e for e in events if e["type"] == "step_done")
        self.assertEqual(step["output"], "echo: 42")
        msgs = FakeToolBackend.bodies[-1][1]["messages"]
        self.assertEqual(msgs[-2]["tool_calls"][0]["function"]["name"], "Fake__echo")
        self.assertEqual(msgs[-1], {"role": "tool", "tool_call_id": "c1", "content": "echo: 42"})
        self.assertEqual(self.text(events), "The answer is 42.")

    def test_cancel_while_waiting(self):
        s, events = self.run_tools("claude::claude-opus-5-5", decide=lambda ev: "cancel")
        self.assertEqual(events[-1], {"type": "done", "stopped": True})
        msg = self.call("GET", f"/api/sessions/{s['id']}")["messages"][-1]
        self.assertEqual(msg["meta"]["tools"]["parts"][-1]["step"]["status"], "stopped")

    def test_rejected_requests(self):
        s = self.call("POST", "/api/sessions", {})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.call("POST", "/api/tools/confirm", {"run": "nope", "id": "s1", "decision": "allow"})
        self.assertEqual(cm.exception.code, 404)
        req = urllib.request.Request(self.base + "/api/tools", json.dumps(
            {"session_id": s["id"], "model": "ollama::tool:1b", "content": "x"}).encode(),
            {"Content-Type": "application/json", "X-Requested-With": "sunak", "X-Forwarded-For": "203.0.113.5"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(cm.exception.code, 403)
        self.assertIn("password", json.load(cm.exception)["error"])

    def test_agent_mode_is_gone(self):
        for path in ("/api/agent", "/api/agent/confirm", "/api/agent/cancel", "/api/agent/revoke"):
            with self.assertRaises(urllib.error.HTTPError, msg=path) as cm:
                self.call("POST", path, {})
            self.assertEqual(cm.exception.code, 404, path)
        # old agent settings are ignored: not shown, not an error
        self.call("PUT", "/api/settings", {"agent_enabled": True, "agent_timeout": 99})
        s = self.call("GET", "/api/settings")
        self.assertFalse([k for k in s if k.startswith("agent_")])

    def test_chats_stored_with_the_agent_still_load(self):
        s = self.call("POST", "/api/sessions", {})
        self.app.db.add_message(s["id"], "user", "hi", "x::y", {})
        self.app.db.add_message(s["id"], "assistant", "done", "x::y", {"agent": {"folder": "/p", "parts": [
            {"step": {"id": "s1", "tool": "list_files", "title": "list_files .", "status": "done", "output": "a"}},
            {"text": "done"}]}})
        msgs = self.call("GET", f"/api/sessions/{s['id']}")["messages"]
        self.assertEqual([m["content"] for m in msgs], ["hi", "done"])
        self.assertEqual(msgs[-1]["meta"]["agent"]["parts"][0]["step"]["tool"], "list_files")


class FrontendTest(unittest.TestCase):
    """The browser side lives in app.js and lang-de.js; check what the Python tests cannot run."""
    STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sunak", "static")

    def read(self, name):
        with open(os.path.join(self.STATIC, name), encoding="utf-8") as f:
            return f.read()

    def test_old_agent_steps_still_show_command_and_diff(self):
        js = self.read("app.js")
        step = js.split("function stepEl")[1][:600]
        self.assertIn("st.command", step)
        self.assertIn("diffEl(st.diff)", step)
        self.assertIn(".step .diff .add", self.read("app.css"))

    def test_pictures_are_painted_with_tools_on_too(self):
        js = self.read("app.js")
        self.assertIn("pictureIntent(text, false, 'chat')", js)
        self.assertNotIn("tools (MCP) are on", js)

    def test_notices_of_the_server_are_translated(self):
        de = self.read("lang-de.js")
        self.assertIn(f'"Stopped after {toolrun.MAX_STEPS} steps. Send a message to let the model continue."', de)
        self.assertNotIn("project folder", de.lower())


if __name__ == "__main__":
    unittest.main()
