"""MCP tools: a simulated stdio server (a small Python program) and a simulated Streamable HTTP server,
the settings (secrets never reach the browser) and chats that call MCP tools with the user's approval."""

import json
import os
import shlex
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sunak import mcp
from sunak.server import make_server

import test_server
from test_agent import FakeAgentBackend

FAKE_STDIO = r'''
import json, os, sys, time

def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()

print("starting fake server (not JSON)", flush=True)
TOOLS = [
    {"name": "echo", "description": "Repeat text", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "fail", "description": "Always fails", "inputSchema": {"type": "object"}},
    {"name": "env", "description": "Show SECRET_X"},
    {"name": "slow", "description": "Takes long", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "crash", "description": "Ends the program"},
]
for line in sys.stdin:
    msg = json.loads(line)
    method, rid = msg.get("method"), msg.get("id")
    if rid is None or method is None:
        if msg.get("id") == "p1" and msg.get("result") == {}:
            sys.stderr.write("got pong\n")
        continue
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": msg["params"]["protocolVersion"],
              "capabilities": {"tools": {}}, "serverInfo": {"name": "fake", "version": "1"}}})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": "p1", "method": "ping"})
        page = 1 if msg["params"].get("cursor") == "next" else 0
        send({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS[:3] if page == 0 else TOOLS[3:],
              **({"nextCursor": "next"} if page == 0 else {})}})
    elif method == "tools/call":
        name, args = msg["params"]["name"], msg["params"].get("arguments") or {}
        if name == "echo":
            res = {"content": [{"type": "text", "text": "echo: " + args["text"]}]}
        elif name == "fail":
            res = {"content": [{"type": "text", "text": "it broke"}], "isError": True}
        elif name == "env":
            res = {"content": [{"type": "text", "text": os.environ.get("SECRET_X", "-")}]}
        elif name == "slow":
            time.sleep(3)
            res = {"content": []}
        else:
            sys.stderr.write("fatal: crashed on purpose\n")
            sys.stderr.flush()
            sys.exit(3)
        send({"jsonrpc": "2.0", "id": rid, "result": res})
    else:
        send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unknown method"}})
'''


class FakeHttp(BaseHTTPRequestHandler):
    """Streamable HTTP: JSON answers, tools/call as server-sent events with a notification first."""
    seen = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        msg = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeHttp.seen.append((msg.get("method"), self.headers.get("Authorization"), self.headers.get("Mcp-Session-Id"),
                              self.headers.get("MCP-Protocol-Version")))
        if "id" not in msg:
            self.send_response(202)
            self.send_header("Content-Length", "0")
            return self.end_headers()
        if msg["method"] == "initialize":
            return self.json({"protocolVersion": "2025-03-26", "capabilities": {}, "serverInfo": {"name": "web"}}, msg["id"],
                             {"Mcp-Session-Id": "abc"})
        if msg["method"] == "tools/list":
            return self.json({"tools": [{"name": "weather", "description": "Weather of a city",
                                         "inputSchema": {"type": "object", "properties": {"city": {"type": "string"}}}}]}, msg["id"])
        events = [{"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progress": 1}},
                  {"jsonrpc": "2.0", "id": msg["id"], "result": {"content": [
                      {"type": "text", "text": f"Sunny in {msg['params']['arguments'].get('city')}"},
                      {"type": "image", "mimeType": "image/png", "data": "AAAA"}]}}]
        body = "".join(f"event: message\ndata: {json.dumps(e)}\n\n" for e in events).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_DELETE(self):
        FakeHttp.seen.append(("DELETE", None, self.headers.get("Mcp-Session-Id"), None))
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def json(self, result, rid, headers=None):
        body = json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def command_line(script):
    q = (lambda a: f'"{a}"') if os.name == "nt" else shlex.quote
    return f"{q(sys.executable)} -u {q(script)}"


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.script = os.path.join(cls.tmp.name, "fake mcp.py")  # a space in the path on purpose
        with open(cls.script, "w") as f:
            f.write(FAKE_STDIO)
        cls.cmd = command_line(cls.script)
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), FakeHttp)
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()
        cls.http_url = f"http://127.0.0.1:{cls.http.server_address[1]}/mcp"

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.tmp.cleanup()


class ClientTest(Base):
    def stdio(self, **extra):
        srv = mcp.connect({"id": "fake", "name": "Fake", "type": "stdio", "command": self.cmd, **extra})
        self.addCleanup(srv.close)
        return srv

    def test_names_and_results(self):
        self.assertEqual(mcp.exposed_name("My Files!", "read file"), "My_Files__read_file")
        long = mcp.exposed_name("s" * 30, "t" * 80)
        self.assertLessEqual(len(long), 64)
        self.assertNotEqual(long, mcp.exposed_name("s" * 30, "t" * 79 + "u"))
        self.assertRegex(long, r"^[a-zA-Z0-9_-]+$")
        self.assertEqual(mcp.result_text({"content": [{"type": "text", "text": "a"}, {"type": "resource", "resource": {"uri": "x", "text": "b"}},
                                                      {"type": "image", "mimeType": "image/png"}]}),
                         ("a\nb\n[image (image/png), not shown]", False))
        self.assertEqual(mcp.result_text({"content": [], "structuredContent": {"n": 1}, "isError": True}), ('{"n": 1}', True))
        self.assertEqual(mcp.result_text({}), ("(no output)", False))
        self.assertEqual(mcp.schema({"inputSchema": {"type": "string"}}), {"type": "object", "properties": {}})
        self.assertEqual(mcp.schema({}), {"type": "object", "properties": {}})

    def test_stdio_server(self):
        srv = self.stdio(env={"SECRET_X": "s3cret"})
        tools = srv.start()
        self.assertEqual([t["name"] for t in tools], ["echo", "fail", "env", "slow", "crash"])  # both pages, junk line ignored
        self.assertEqual(srv.info, {"name": "fake", "version": "1"})
        self.assertEqual(srv.call("echo", {"text": "hi"}), ("echo: hi", False))
        self.assertEqual(srv.call("fail", {}), ("it broke", True))
        self.assertEqual(srv.call("env", {}), ("s3cret", False))
        for _ in range(50):  # the ping from the server was answered
            if "got pong" in srv.stderr:
                break
            time.sleep(0.05)
        self.assertIn("got pong", srv.stderr)
        stop = threading.Event()
        threading.Timer(0.3, stop.set).start()
        t0 = time.monotonic()
        with self.assertRaisesRegex(mcp.MCPError, "Stopped"):
            srv.call("slow", {}, stop)
        self.assertLess(time.monotonic() - t0, 5)
        with self.assertRaisesRegex(mcp.MCPError, "Fake stopped: .*fatal: crashed on purpose"):
            srv.call("crash", {})
        srv.proc.wait(5)
        self.assertFalse(srv.alive())

    def test_stdio_errors(self):
        with self.assertRaisesRegex(mcp.MCPError, "Program not found: no-such-program-xyz"):
            self.stdio(command="no-such-program-xyz --flag").start()
        srv = self.stdio(command=command_line(os.path.join(self.tmp.name, "missing.py")))
        with self.assertRaisesRegex(mcp.MCPError, "Fake stopped"):
            srv.start()

    def test_http_server(self):
        FakeHttp.seen.clear()
        srv = mcp.connect({"id": "web", "name": "Web", "type": "http", "url": self.http_url, "token": "tok"})
        self.assertEqual([t["name"] for t in srv.start()], ["weather"])
        self.assertEqual(srv.call("weather", {"city": "Rom"}), ("Sunny in Rom\n[image (image/png), not shown]", False))
        srv.close()
        self.assertEqual([s[0] for s in FakeHttp.seen], ["initialize", "notifications/initialized", "tools/list", "tools/call", "DELETE"])
        self.assertTrue(all(s[1] == "Bearer tok" for s in FakeHttp.seen[:4]))
        self.assertEqual([s[2] for s in FakeHttp.seen], [None, "abc", "abc", "abc", "abc"])
        self.assertEqual(FakeHttp.seen[3][3], "2025-03-26")
        bad = mcp.connect({"id": "x", "name": "X", "type": "http", "url": "http://127.0.0.1:9/mcp"})
        with self.assertRaisesRegex(mcp.MCPError, "Cannot reach X"):
            bad.start()

    def test_manager(self):
        m = mcp.Manager()
        self.addCleanup(m.close_all)
        cfg = {"id": "fake", "name": "Fake", "type": "stdio", "command": self.cmd, "enabled": True, "env": {}}
        off = {"id": "web", "name": "Web", "type": "http", "url": self.http_url, "enabled": False, "token": ""}
        broken = {"id": "nope", "name": "Nope", "type": "stdio", "command": "no-such-program-xyz", "enabled": True, "env": {}}
        m.configure([cfg, off, broken])
        started = []
        tools, errors = m.tools([cfg, off, broken], started.append)
        self.assertEqual(sorted(started), ["Fake", "Nope"])
        self.assertEqual([t[0] for t in tools], ["Fake__echo", "Fake__fail", "Fake__env", "Fake__slow", "Fake__crash"])
        self.assertIn("Program not found", errors["Nope"])
        first = m.running["fake"]
        started.clear()
        m.tools([cfg], started.append)
        self.assertEqual(started, [])  # still running
        with self.assertRaises(mcp.MCPError):
            first.call("crash", {})
        first.proc.wait(5)
        m.tools([cfg], started.append)
        self.assertEqual(started, ["Fake"])  # a crashed server starts again
        self.assertIsNot(m.running["fake"], first)
        second = m.running["fake"].proc
        m.configure([dict(cfg, command=self.cmd + " ")])  # changed settings stop it
        self.assertNotIn("fake", m.running)
        second.wait(5)

    def test_clean_settings(self):
        old = mcp.clean([{"name": "Files", "type": "stdio", "command": "npx -y server", "env": "A=1\n# note\nB = two"},
                         {"name": "Web", "type": "http", "url": "https://x.example/mcp", "token": "t0k"}], [])
        self.assertEqual(old[0], {"id": "files", "name": "Files", "type": "stdio", "enabled": True, "command": "npx -y server",
                                  "env": {"A": "1", "B": "two"}})
        self.assertEqual(old[1]["token"], "t0k")
        self.assertEqual(mcp.public(old[0])["env_keys"], ["A", "B"])
        self.assertNotIn("env", mcp.public(old[0]))
        self.assertEqual(mcp.public(old[1]), {"id": "web", "name": "Web", "type": "http", "enabled": True,
                                              "url": "https://x.example/mcp", "has_token": True})
        # the browser sends the servers back without secrets: they are kept for the same command / address
        kept = mcp.clean([dict(mcp.public(c), enabled=False) for c in old], old)
        self.assertEqual((kept[0]["env"], kept[1]["token"], kept[0]["enabled"]), ({"A": "1", "B": "two"}, "t0k", False))
        moved = mcp.clean([dict(mcp.public(old[0]), command="evil"), dict(mcp.public(old[1]), url="https://other.example")], old)
        self.assertEqual((moved[0]["env"], moved[1]["token"]), ({}, ""))
        self.assertEqual([c["id"] for c in mcp.clean([{"name": "A", "type": "http", "url": "http://a"}] * 2, [])], ["a", "ax"])
        for bad, msg in [({"name": "", "type": "stdio", "command": "x"}, "needs a name"),
                         ({"name": "A", "type": "ftp"}, "needs a type"),
                         ({"name": "A", "type": "stdio", "command": " "}, "enter the command"),
                         ({"name": "A", "type": "stdio", "command": "x", "env": "NOEQUALS"}, "NAME=value"),
                         ({"name": "A", "type": "stdio", "command": "x", "env": {"1BAD": "v"}}, "not a valid variable"),
                         ({"name": "A", "type": "http", "url": "localhost:3000"}, "http:// or https://")]:
            with self.assertRaisesRegex(ValueError, msg):
                mcp.clean([bad], [])
        with self.assertRaises(ValueError):
            mcp.clean({"name": "A"}, [])


class ServerTest(Base):
    call = classmethod(test_server.SunakTest.call.__func__)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.backend = ThreadingHTTPServer(("127.0.0.1", 0), FakeAgentBackend)
        threading.Thread(target=cls.backend.serve_forever, daemon=True).start()
        cls.srv = make_server("127.0.0.1", 0, os.path.join(cls.tmp.name, "data"))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.app = cls.srv.RequestHandlerClass.app
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        cls.call("PUT", "/api/settings", {"providers": [
            {"id": "claude", "name": "Claude", "type": "anthropic",
             "base_url": f"http://127.0.0.1:{cls.backend.server_address[1]}/anthropic", "api_key": "sk-test"}]})

    @classmethod
    def tearDownClass(cls):
        cls.app.mcp.close_all()
        for s in (cls.srv, cls.backend):
            s.shutdown()
            s.server_close()
        super().tearDownClass()

    def setUp(self):
        FakeAgentBackend.bodies = []
        self.call("PUT", "/api/settings", {"mcp_servers": [
            {"name": "Fake", "type": "stdio", "command": self.cmd, "env": "SECRET_X=hidden-value"}]})

    def error(self, *args, **kw):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.call(*args, **kw)
        return e.exception.code, json.loads(e.exception.read())["error"]

    def test_settings_hide_secrets(self):
        raw = self.call("GET", "/api/settings", raw=True)
        self.assertNotIn("hidden-value", raw)
        s = json.loads(raw)["mcp_servers"]
        self.assertEqual(s, [{"id": "fake", "name": "Fake", "type": "stdio", "enabled": True, "command": self.cmd,
                              "env_keys": ["SECRET_X"]}])
        self.call("PUT", "/api/settings", {"mcp_servers": s})  # sent back as the browser has it
        self.assertEqual(self.app.mcp_servers()[0]["env"], {"SECRET_X": "hidden-value"})
        code, err = self.error("PUT", "/api/settings", {"mcp_servers": [{"name": "X", "type": "stdio", "command": "x"}]},
                               headers={"X-Forwarded-For": "203.0.113.5"})
        self.assertEqual((code, "need a password" in err), (403, True))
        self.assertEqual(self.app.mcp_servers()[0]["name"], "Fake")
        self.assertEqual(self.error("PUT", "/api/settings", {"mcp_servers": [{"name": "X", "type": "nope"}]})[0], 400)

    def test_test_endpoint(self):
        res = self.call("POST", "/api/mcp/test", {"server": {"id": "fake", "name": "Fake", "type": "stdio", "command": self.cmd}})
        self.assertEqual([t["name"] for t in res["tools"]], ["echo", "fail", "env", "slow", "crash"])
        self.assertEqual(res["tools"][0]["description"], "Repeat text")
        code, err = self.error("POST", "/api/mcp/test", {"server": {"name": "N", "type": "stdio", "command": "no-such-program-xyz"}})
        self.assertEqual((code, "Program not found" in err), (400, True))

    def chat(self, script, decide, folder=""):
        s = self.call("POST", "/api/sessions", {"system": "SCRIPT" + json.dumps(script) + "END"})
        req = urllib.request.Request(self.base + "/api/agent", json.dumps(
            {"session_id": s["id"], "model": "claude::claude-opus-5-5", "content": "Go", "folder": folder, "mcp": True}).encode(),
            {"Content-Type": "application/json", "X-Requested-With": "sunak"}, method="POST")
        events, run = [], None
        with urllib.request.urlopen(req, timeout=60) as r:
            for line in r:
                ev = json.loads(line)
                events.append(ev)
                if ev["type"] == "start":
                    run = ev["run"]
                if ev["type"] == "confirm":
                    self.call("POST", "/api/agent/confirm", {"run": run, "id": ev["id"], "decision": decide(ev)})
        return s, events

    def test_chat_with_mcp_tools(self):
        script = [["Fake__echo", {"text": "one"}], ["Fake__env", {}], ["Fake__echo", {"text": "two"}], ["Fake__echo", {}],
                  ["Fake__fail", {}], ["write_file", {"path": "x", "content": "y"}]]
        answers = iter(["always", "deny", "allow"])
        s, events = self.chat(script, lambda ev: next(answers))
        self.assertIn("Starting MCP server Fake …", [e["t"] for e in events if e["type"] == "notice"])
        confirms = [e for e in events if e["type"] == "confirm"]
        self.assertEqual([c["kind"] for c in confirms], ["tool:Fake__echo", "tool:Fake__env", "tool:Fake__fail"])
        self.assertEqual((confirms[0]["server"], confirms[0]["mcp_tool"], confirms[0]["title"]), ("Fake", "echo", "Fake · echo"))
        self.assertEqual(json.loads(confirms[0]["input"]), {"text": "one"})
        done = [e for e in events if e["type"] == "step_done"]
        self.assertEqual([d["status"] for d in done], ["done", "denied", "done", "error", "error", "error"])
        self.assertEqual(done[0]["output"], "echo: one")
        self.assertEqual(done[2]["output"], "echo: two")  # "Allow in this chat" covered the second echo
        self.assertIn("needs the argument text", done[3]["output"])
        self.assertEqual(done[4]["output"], "Error: it broke")
        self.assertIn("Unknown tool write_file", done[5]["output"])  # no folder: no file tools
        self.assertNotIn("hidden-value", json.dumps(events))
        self.assertEqual(events[-1], {"type": "done", "stopped": False})
        body = FakeAgentBackend.bodies[0][1]
        self.assertEqual([t["name"] for t in body["tools"]], ["Fake__echo", "Fake__fail", "Fake__env", "Fake__slow", "Fake__crash"])
        self.assertEqual(body["tools"][0]["input_schema"]["required"], ["text"])
        self.assertIn("MCP servers", body["system"])
        stored = self.call("GET", f"/api/sessions/{s['id']}")["messages"][-1]
        self.assertEqual(len([p for p in stored["meta"]["agent"]["parts"] if "step" in p]), 6)

    def test_agent_mode_with_mcp(self):
        self.call("PUT", "/api/settings", {"agent_enabled": True})
        self.addCleanup(self.call, "PUT", "/api/settings", {"agent_enabled": False})
        folder = tempfile.mkdtemp(dir=self.tmp.name)
        with open(os.path.join(folder, "notes.txt"), "w") as f:
            f.write("x")
        s, events = self.chat([["Fake__echo", {"text": "x"}], ["list_files", {}]], lambda ev: "allow", folder)
        self.assertEqual([e["kind"] for e in events if e["type"] == "confirm"], ["tool:Fake__echo"])  # reading needs no question
        done = [e for e in events if e["type"] == "step_done"]
        self.assertEqual([(d["status"], d["output"]) for d in done], [("done", "echo: x"), ("done", "notes.txt  (1 bytes)")])
        body = FakeAgentBackend.bodies[0][1]
        names = [t["name"] for t in body["tools"]]
        self.assertIn("read_file", names)
        self.assertIn("Fake__echo", names)
        self.assertIn("project folder", body["system"])
        self.assertIn("MCP server", body["system"])

    def test_chat_needs_a_server(self):
        self.call("PUT", "/api/settings", {"mcp_servers": [
            {"name": "Fake", "type": "stdio", "command": self.cmd, "enabled": False}]})
        s = self.call("POST", "/api/sessions", {})
        code, err = self.error("POST", "/api/agent", {"session_id": s["id"], "content": "Go", "mcp": True,
                                                      "model": "claude::claude-opus-5-5"})
        self.assertEqual((code, "No MCP server" in err), (400, True))
        self.call("PUT", "/api/settings", {"mcp_servers": [{"name": "Nope", "type": "stdio", "command": "no-such-program-xyz"}]})
        events = self.call("POST", "/api/agent", {"session_id": s["id"], "content": "Go", "mcp": True,
                                                  "model": "claude::claude-opus-5-5"})
        self.assertIn("Program not found", " ".join(e.get("t", "") for e in events))
        self.assertEqual(events[-1], {"type": "error", "error": "None of the MCP servers is available."})
        code, err = self.error("POST", "/api/agent", {"session_id": s["id"], "content": "Go", "mcp": True,
                                                      "model": "claude::claude-opus-5-5"}, headers={"X-Forwarded-For": "203.0.113.5"})
        self.assertEqual(code, 403)


if __name__ == "__main__":
    unittest.main()
