"""Agent mode: folder limits, tools, commands, and the agent loop against fake Claude, Ollama and
OpenAI-compatible backends (native tool calls and the text protocol), with approve/deny/cancel."""

import json
import os
import re
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sunak import agent
from sunak.server import make_server

PY = f'"{sys.executable}"'


def read(path, mode="r"):
    with open(path, mode) as f:
        return f.read()


def can_symlink():
    with tempfile.TemporaryDirectory() as d:
        try:
            os.symlink(d, os.path.join(d, "l"), target_is_directory=True)
            return True
        except (OSError, NotImplementedError):
            return False


class FolderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.base = os.path.realpath(self.tmp.name)
        self.root = os.path.join(self.base, "proj")
        self.outside = os.path.join(self.base, "secret")
        os.makedirs(os.path.join(self.root, "src"))
        os.makedirs(self.outside)
        with open(os.path.join(self.outside, "key.txt"), "w") as f:
            f.write("TOP SECRET")
        with open(os.path.join(self.root, "src", "a.py"), "w", newline="") as f:
            f.write("x = 1\ny = 2\n")
        self.ws = agent.Workspace(self.root)
        self.never = threading.Event()

    def tearDown(self):
        self.tmp.cleanup()

    def test_paths_must_stay_inside(self):
        for bad in ["../secret/key.txt", "src/../../secret/key.txt", self.outside, os.path.join(self.outside, "key.txt"),
                    "a\x00b", "/", ".."]:
            with self.assertRaises(agent.ToolError, msg=bad):
                self.ws.path(bad)
        self.assertEqual(self.ws.path("src/a.py"), os.path.join(self.root, "src", "a.py"))
        self.assertEqual(self.ws.path("new/dir/file.txt"), os.path.join(self.root, "new", "dir", "file.txt"))
        self.assertEqual(self.ws.path(""), self.root)

    @unittest.skipUnless(can_symlink(), "symlinks not available")
    def test_symlinks_cannot_escape(self):
        os.symlink(self.outside, os.path.join(self.root, "link"), target_is_directory=True)
        os.symlink(os.path.join(self.outside, "key.txt"), os.path.join(self.root, "key.txt"))
        for bad in ["link/key.txt", "key.txt", "link/new.txt"]:
            with self.assertRaises(agent.ToolError, msg=bad):
                self.ws.path(bad)
        with self.assertRaises(agent.ToolError):
            agent.prepare(self.ws, "write_file", {"path": "link/x.txt", "content": "x"}, 10, self.never)
        self.assertNotIn("TOP SECRET", self.ws.search("SECRET"))
        listing = self.ws.list_files(".", True)
        self.assertIn("link@", listing)
        self.assertNotIn("link/key.txt", listing)

    def test_check_folder(self):
        data = os.path.join(self.base, "data")
        os.makedirs(data)
        self.assertEqual(agent.check_folder(self.root, data), self.root)
        for bad in ["", "relative/path", os.path.join(self.base, "missing"), os.path.join(self.root, "src", "a.py"),
                    os.path.abspath(os.sep), os.path.expanduser("~"), data, self.base, None, 5]:
            with self.assertRaises(ValueError, msg=bad):
                agent.check_folder(bad, data)

    def test_read_list_search(self):
        self.assertEqual(self.ws.read_file("src/a.py"), "src/a.py:\nx = 1\ny = 2")
        self.assertEqual(self.ws.read_file("src/a.py", 2), "src/a.py (lines 2-2 of 2):\ny = 2")
        os.makedirs(os.path.join(self.root, ".git"))
        with open(os.path.join(self.root, ".git", "config"), "w") as f:
            f.write("y = 2")
        with open(os.path.join(self.root, "img.bin"), "wb") as f:
            f.write(b"\x00\x01y = 2")
        self.assertEqual(self.ws.search("Y = 2"), "src/a.py:2: y = 2")
        self.assertEqual(self.ws.search(r"^x\s*=", regex=True), "src/a.py:1: x = 1")
        with self.assertRaises(agent.ToolError):
            self.ws.read_file("img.bin")
        self.assertIn("src/", self.ws.list_files())
        self.assertIn(".git/", self.ws.list_files())  # shown at the top, skipped when recursive
        rec = self.ws.list_files(".", True)
        self.assertIn("src/a.py  (12 bytes)", rec)
        self.assertNotIn(".git/config", rec)

    def test_edit_and_write(self):
        act = agent.prepare(self.ws, "edit_file", {"path": "src/a.py", "old_text": "y = 2", "new_text": "y = 3"}, 10, self.never)
        self.assertEqual(act.kind, "write")
        self.assertIn("-y = 2\n+y = 3", act.preview["diff"])
        self.assertEqual(read(os.path.join(self.root, "src", "a.py")), "x = 1\ny = 2\n")  # nothing before run()
        act.run()
        self.assertEqual(read(os.path.join(self.root, "src", "a.py")), "x = 1\ny = 3\n")
        for args, msg in [({"old_text": "nope", "new_text": "z"}, "not found"),
                          ({"old_text": "", "new_text": "z"}, "empty"),
                          ({"old_text": "y = 3", "new_text": "y = 3"}, "not change")]:
            with self.assertRaisesRegex(agent.ToolError, msg):
                agent.prepare(self.ws, "edit_file", dict(args, path="src/a.py"), 10, self.never)
        with open(os.path.join(self.root, "dup.txt"), "w") as f:
            f.write("a\na\n")
        with self.assertRaisesRegex(agent.ToolError, "2 times"):
            agent.prepare(self.ws, "edit_file", {"path": "dup.txt", "old_text": "a", "new_text": "b"}, 10, self.never)
        agent.prepare(self.ws, "edit_file", {"path": "dup.txt", "old_text": "a", "new_text": "b", "replace_all": True},
                      10, self.never).run()
        self.assertEqual(read(os.path.join(self.root, "dup.txt")), "b\nb\n")
        # new file in a new folder
        act = agent.prepare(self.ws, "write_file", {"path": "docs/new.md", "content": "# Hi\n"}, 10, self.never)
        self.assertTrue(act.preview["new_file"])
        self.assertIn("Created docs/new.md", act.run())
        # a file changed between preview and approval is not overwritten
        act = agent.prepare(self.ws, "write_file", {"path": "docs/new.md", "content": "other\n"}, 10, self.never)
        with open(os.path.join(self.root, "docs", "new.md"), "w") as f:
            f.write("changed by me\n")
        with self.assertRaisesRegex(agent.ToolError, "changed"):
            act.run()

    def test_windows_line_endings_are_kept(self):
        p = os.path.join(self.root, "win.txt")
        with open(p, "wb") as f:
            f.write(b"one\r\ntwo\r\n")
        agent.prepare(self.ws, "edit_file", {"path": "win.txt", "old_text": "one\ntwo", "new_text": "1\n2"}, 10, self.never).run()
        self.assertEqual(read(p, "rb"), b"1\r\n2\r\n")
        agent.prepare(self.ws, "write_file", {"path": "win.txt", "content": "a\nb\n"}, 10, self.never).run()
        self.assertEqual(read(p, "rb"), b"a\r\nb\r\n")

    def test_bad_arguments(self):
        for name, args in [("read_file", {}), ("read_file", {"path": 5}), ("nope", {}), ("read_file", "x"),
                           ("read_file", {"path": "src/a.py", "start_line": True})]:
            with self.assertRaises(agent.ToolError):
                agent.prepare(self.ws, name, args, 10, self.never)

    def test_commands(self):
        code, out, note = agent.run_command(f'{PY} -c "print(6*7)"', self.root, 20, self.never)
        self.assertEqual((code, out.strip(), note), (0, "42", ""))
        code, out, _ = agent.run_command(f'{PY} -c "import os,sys; print(os.getcwd()); sys.exit(3)"', self.root, 20, self.never)
        self.assertEqual(code, 3)
        self.assertEqual(os.path.normcase(os.path.realpath(out.strip())), os.path.normcase(self.root))
        t = time.time()
        code, _, note = agent.run_command(f'{PY} -c "import time; time.sleep(30)"', self.root, 1, self.never)
        self.assertIsNone(code)
        self.assertIn("longer than 1 seconds", note)
        self.assertLess(time.time() - t, 15)
        _, out, _ = agent.run_command(f'{PY} -c "print(\'x\' * 200000)"', self.root, 20, self.never)
        self.assertLess(len(out), agent.OUT_HEAD + agent.OUT_TAIL + 200)
        self.assertIn("bytes of output left out", out)
        stop = threading.Event()
        threading.Timer(0.5, stop.set).start()
        with self.assertRaises(agent.Cancelled):
            agent.run_command(f'{PY} -c "import time; time.sleep(30)"', self.root, 60, stop)

    def test_password_not_passed_to_commands(self):
        os.environ["SUNAK_PASSWORD"] = "pw-123"
        try:
            _, out, _ = agent.run_command(f'{PY} -c "import os; print(os.environ.get(\'SUNAK_PASSWORD\'))"',
                                          self.root, 20, self.never)
        finally:
            del os.environ["SUNAK_PASSWORD"]
        self.assertEqual(out.strip(), "None")

    def test_text_protocol_parser(self):
        self.assertIsNone(agent._find_call('hi ```tool\n{"tool": "read_file", "args": {"pa'))
        s, e, obj = agent._find_call('hi ```tool\n{"tool": "x", "args": {"c": "``` inside"}}\n```\nafter')
        self.assertEqual(obj["args"]["c"], "``` inside")
        self.assertEqual('hi ```tool\n{"tool": "x", "args": {"c": "``` inside"}}\n```\nafter'[e:], "\nafter")


class FakeAgentBackend(BaseHTTPRequestHandler):
    """Scripted models. Each request answers according to how many tool results came back so far."""
    bodies = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        data = {"/api/tags": {"models": [{"name": "tool:1b"}, {"name": "notools:1b"}]},
                "/v1/models": {"data": [{"id": "gpt-agent"}]},
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
        calls = script or [["write_file", {"path": "hello.txt", "content": "hi\n"}]]
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
            if msgs[-1]["content"].startswith("[Result of read_file]"):
                return self.line({"message": {"content": "The readme says hello."}, "done": True})
            text = 'Let me read it.\n```tool\n{"tool": "read_file", "args": {"path": "README.md"}}\n```\nInvented result!'
            for i in range(0, len(text), 5):
                self.line({"message": {"content": text[i:i + 5]}, "done": False})
            return self.line({"message": {"content": ""}, "done": True})
        done = sum(1 for m in msgs if m["role"] == "tool")
        if done == 0:
            self.line({"message": {"content": "", "tool_calls": [
                {"function": {"name": "read_file", "arguments": {"path": "README.md"}}},
                {"function": {"name": "read_file", "arguments": {"path": "../outside.txt"}}}]}, "done": False})
            return self.line({"message": {"content": ""}, "done": True})
        if done == 2:
            self.line({"message": {"content": "", "tool_calls": [
                {"function": {"name": "edit_file", "arguments": {"path": "README.md", "old_text": "hello", "new_text": "bye"}}}]},
                "done": True})
            return
        self.line({"message": {"content": "Finished."}, "done": True})

    def openai(self, body, msgs):
        done = sum(1 for m in msgs if m["role"] == "tool")

        def data(obj):
            self.wfile.write(b"data: " + json.dumps(obj).encode() + b"\n\n")
            self.wfile.flush()
        if done == 0:
            args = json.dumps({"command": f'{PY} -c "print(6*7)"'})
            data({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "type": "function",
                                                          "function": {"name": "run_command", "arguments": ""}}]}}]})
            for i in range(0, len(args), 9):
                data({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": args[i:i + 9]}}]}}]})
        else:
            data({"choices": [{"delta": {"content": "The answer is 42."}}]})
        self.wfile.write(b"data: [DONE]\n\n")


class AgentServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = ThreadingHTTPServer(("127.0.0.1", 0), FakeAgentBackend)
        threading.Thread(target=cls.backend.serve_forever, daemon=True).start()
        bp = cls.backend.server_address[1]
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.data = os.path.join(cls.tmp.name, "data")
        cls.app = make_server("127.0.0.1", 0, cls.data)
        threading.Thread(target=cls.app.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.app.server_address[1]}"
        cls.call("PUT", "/api/settings", {"agent_enabled": True, "agent_timeout": 30, "providers": [
            {"id": "ollama", "name": "Ollama", "type": "ollama", "base_url": f"http://127.0.0.1:{bp}"},
            {"id": "cloud", "name": "Cloud", "type": "openai", "base_url": f"http://127.0.0.1:{bp}/v1"},
            {"id": "claude", "name": "Claude", "type": "anthropic", "base_url": f"http://127.0.0.1:{bp}/anthropic",
             "api_key": "sk-test"}]})

    @classmethod
    def tearDownClass(cls):
        cls.app.shutdown()
        cls.app.server_close()
        cls.backend.shutdown()
        cls.backend.server_close()
        cls.tmp.cleanup()

    def setUp(self):
        self.proj = tempfile.mkdtemp(dir=self.tmp.name)
        with open(os.path.join(self.proj, "README.md"), "w") as f:
            f.write("hello world\n")
        FakeAgentBackend.bodies = []

    @classmethod
    def call(cls, method, path, body=None):
        req = urllib.request.Request(cls.base + path, json.dumps(body).encode() if body is not None else None,
                                     {"Content-Type": "application/json", "X-Requested-With": "sunak"}, method=method)
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)

    def run_agent(self, model, content="Do it", decide=lambda ev: "allow", session=None, system=""):
        """Run /api/agent, answer each confirm with decide(event), return all events."""
        s = session or self.call("POST", "/api/sessions", {"system": system})
        req = urllib.request.Request(self.base + "/api/agent", json.dumps(
            {"session_id": s["id"], "model": model, "content": content, "folder": self.proj}).encode(),
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
                        self.call("POST", "/api/agent/cancel", {"run": run})
                    else:
                        self.call("POST", "/api/agent/confirm", {"run": run, "id": ev["id"], "decision": d})
        return s, events

    def text(self, events):
        return "".join(e["t"] for e in events if e["type"] == "text")

    def test_claude_writes_after_approval(self):
        s, events = self.run_agent("claude::claude-opus-5-5")
        confirm = next(e for e in events if e["type"] == "confirm")
        self.assertEqual((confirm["kind"], confirm["path"], confirm["new_file"]), ("write", "hello.txt", True))
        self.assertIn("+hi", confirm["diff"])
        self.assertEqual(read(os.path.join(self.proj, "hello.txt")), "hi\n")
        self.assertEqual(events[-1], {"type": "done", "stopped": False})
        self.assertEqual(self.text(events), "Step 0.All done.")
        # the second request carries the signed thinking block, the tool_use and the tool_result
        path, body = FakeAgentBackend.bodies[-1]
        self.assertEqual([t["name"] for t in body["tools"]], [t["name"] for t in agent.TOOLS])
        self.assertNotIn("eager_input_streaming", body["tools"][0])  # only on api.anthropic.com
        assistant, result = body["messages"][-2:]
        self.assertEqual(assistant["content"][0], {"type": "thinking", "thinking": "plan", "signature": "sig0"})
        self.assertEqual(assistant["content"][2], {"type": "tool_use", "id": "tu0", "name": "write_file",
                                                   "input": {"path": "hello.txt", "content": "hi\n"}})
        self.assertEqual(result["content"][0]["tool_use_id"], "tu0")
        self.assertFalse(result["content"][0]["is_error"])
        self.assertIn("project folder", body["system"])
        # stored with its steps
        msg = self.call("GET", f"/api/sessions/{s['id']}")["messages"][-1]
        parts = msg["meta"]["agent"]["parts"]
        self.assertEqual(parts[1]["step"]["status"], "done")
        self.assertEqual(parts[1]["step"]["tool"], "write_file")
        self.assertIn("All done.", msg["content"])

    def test_deny_and_allow_for_this_chat(self):
        script = "SCRIPT" + json.dumps([["write_file", {"path": "a.txt", "content": "a"}],
                                        ["write_file", {"path": "b.txt", "content": "b"}]]) + "END"
        s, events = self.run_agent("claude::claude-opus-5-5", decide=lambda ev: "deny", system=script)
        self.assertFalse(os.path.exists(os.path.join(self.proj, "a.txt")))
        self.assertEqual([e["status"] for e in events if e["type"] == "step_done"], ["denied", "denied"])
        self.assertTrue(FakeAgentBackend.bodies[1][1]["messages"][-1]["content"][0]["is_error"])
        # "always" covers the next writes in this chat without asking
        asked = []
        self.run_agent("claude::claude-opus-5-5", session=s, decide=lambda ev: asked.append(1) or "always")
        self.assertEqual(len(asked), 1)
        self.assertTrue(os.path.exists(os.path.join(self.proj, "b.txt")))
        self.call("POST", "/api/agent/revoke", {"session_id": s["id"]})
        os.remove(os.path.join(self.proj, "a.txt"))
        os.remove(os.path.join(self.proj, "b.txt"))
        asked.clear()
        self.run_agent("claude::claude-opus-5-5", session=s, decide=lambda ev: asked.append(1) or "deny")
        self.assertEqual(len(asked), 2)

    def test_ollama_tools_and_folder_limit(self):
        s, events = self.run_agent("ollama::tool:1b")
        done = [e for e in events if e["type"] == "step_done"]
        self.assertEqual([e["status"] for e in done], ["done", "error", "done"])
        self.assertIn("outside the project folder", done[1]["output"])
        self.assertEqual(read(os.path.join(self.proj, "README.md")), "bye world\n")
        tool_msgs = [m for m in FakeAgentBackend.bodies[-1][1]["messages"] if m["role"] == "tool"]
        self.assertEqual(tool_msgs[0]["tool_name"], "read_file")
        self.assertIn("hello world", tool_msgs[0]["content"])
        self.assertEqual(self.text(events), "Finished.")

    def test_text_protocol_fallback(self):
        s, events = self.run_agent("ollama::notools:1b")
        self.assertTrue(any(e["type"] == "notice" for e in events))
        self.assertEqual(self.text(events), "Let me read it.\nThe readme says hello.")
        self.assertNotIn("Invented", json.dumps(events))
        last = FakeAgentBackend.bodies[-1][1]
        self.assertNotIn("tools", last)
        self.assertIn("```tool", last["messages"][0]["content"])
        self.assertTrue(last["messages"][-1]["content"].startswith("[Result of read_file]\nREADME.md:\nhello world"))

    def test_openai_runs_a_command(self):
        s, events = self.run_agent("cloud::gpt-agent")
        confirm = next(e for e in events if e["type"] == "confirm")
        self.assertEqual(confirm["kind"], "run")
        step = next(e for e in events if e["type"] == "step_done")
        self.assertIn("Exit code: 0\n42", step["output"])
        msgs = FakeAgentBackend.bodies[-1][1]["messages"]
        self.assertEqual(msgs[-2]["tool_calls"][0]["function"]["name"], "run_command")
        self.assertEqual(msgs[-1], {"role": "tool", "tool_call_id": "c1", "content": step["output"]})
        self.assertEqual(self.text(events), "The answer is 42.")

    def test_cancel_while_waiting(self):
        s, events = self.run_agent("claude::claude-opus-5-5", decide=lambda ev: "cancel")
        self.assertEqual(events[-1], {"type": "done", "stopped": True})
        self.assertFalse(os.path.exists(os.path.join(self.proj, "hello.txt")))
        msg = self.call("GET", f"/api/sessions/{s['id']}")["messages"][-1]
        self.assertEqual(msg["meta"]["agent"]["parts"][-1]["step"]["status"], "stopped")

    def test_rejected_requests(self):
        s = self.call("POST", "/api/sessions", {})
        for folder in [os.path.join(self.tmp.name, "missing"), self.data, ""]:
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self.call("POST", "/api/agent", {"session_id": s["id"], "model": "ollama::tool:1b", "content": "x",
                                                 "folder": folder})
            self.assertEqual(cm.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.call("POST", "/api/agent/confirm", {"run": "nope", "id": "s1", "decision": "allow"})
        self.assertEqual(cm.exception.code, 404)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.call("PUT", "/api/settings", {"agent_timeout": 0})
        self.assertEqual(cm.exception.code, 400)
        self.call("PUT", "/api/settings", {"agent_enabled": False})
        try:
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self.call("POST", "/api/agent", {"session_id": s["id"], "model": "ollama::tool:1b", "content": "x",
                                                 "folder": self.proj})
            self.assertEqual(cm.exception.code, 403)
        finally:
            self.call("PUT", "/api/settings", {"agent_enabled": True})

    def test_other_devices_need_a_password(self):
        s = self.call("POST", "/api/sessions", {})
        req = urllib.request.Request(self.base + "/api/agent", json.dumps(
            {"session_id": s["id"], "model": "ollama::tool:1b", "content": "x", "folder": self.proj}).encode(),
            {"Content-Type": "application/json", "X-Requested-With": "sunak", "X-Forwarded-For": "203.0.113.5"},
            method="POST")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(cm.exception.code, 403)
        self.assertIn("password", json.load(cm.exception)["error"])


if __name__ == "__main__":
    unittest.main()
