"""End-to-end tests against fake Ollama and OpenAI-compatible backends.
Run:  python -m unittest discover tests"""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sunak import research
from sunak.server import make_server, recommend, stream_to_text


class FakeBackend(BaseHTTPRequestHandler):
    """Speaks just enough of the Ollama and OpenAI APIs."""

    last_messages = None

    def log_message(self, *a):
        pass

    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/tags":
            return self._json({"models": [{"name": "tiny:1b"}, {"name": "think:1b"}]})
        if self.path == "/v1/models":
            return self._json({"data": [{"id": "gpt-fake"}]})
        self.send_error(404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).last_messages = body.get("messages")
        self.send_response(200)
        self.end_headers()
        if self.path == "/api/chat":
            if body["model"] == "think:1b":
                self.wfile.write(json.dumps({"message": {"thinking": "hmm"}}).encode() + b"\n")
            for w in ["Hello", " from", " Ollama"]:
                self.wfile.write(json.dumps({"message": {"content": w}, "done": False}).encode() + b"\n")
            self.wfile.write(json.dumps({"message": {"content": ""}, "done": True}).encode() + b"\n")
        elif self.path == "/v1/chat/completions":
            for w in ["Hi", " from", " OpenAI"]:
                self.wfile.write(b"data: " + json.dumps({"choices": [{"delta": {"content": w}}]}).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
        elif self.path == "/api/pull":
            for ev in [{"status": "pulling", "completed": 5, "total": 10}, {"status": "success"}]:
                self.wfile.write(json.dumps(ev).encode() + b"\n")


def serve(server):
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


class SunakTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = serve(ThreadingHTTPServer(("127.0.0.1", 0), FakeBackend))
        cls.bport = cls.backend.server_address[1]
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.app = serve(make_server("127.0.0.1", 0, cls.tmp.name))
        cls.base = f"http://127.0.0.1:{cls.app.server_address[1]}"
        cls.call("PUT", "/api/settings", {"providers": [
            {"id": "ollama", "name": "Ollama", "type": "ollama", "base_url": f"http://127.0.0.1:{cls.bport}"},
            {"id": "cloud", "name": "Cloud", "type": "openai", "base_url": f"http://127.0.0.1:{cls.bport}/v1"},
        ]})

    @classmethod
    def tearDownClass(cls):
        cls.app.shutdown()
        cls.backend.shutdown()
        cls.app.server_close()
        cls.tmp.cleanup()

    @classmethod
    def call(cls, method, path, body=None, headers=None, raw=False):
        h = {"Content-Type": "application/json", "X-Requested-With": "sunak"}
        h.update(headers or {})
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(cls.base + path, data=data, method=method, headers=h)
        with urllib.request.urlopen(req, timeout=10) as r:
            text = r.read().decode()
        if raw:
            return text
        if r.headers.get("Content-Type", "").startswith("application/x-ndjson"):
            return [json.loads(line) for line in text.splitlines() if line.strip()]
        return json.loads(text)

    def test_models_from_both_providers(self):
        r = self.call("GET", "/api/models")
        ids = [m["id"] for m in r["models"]]
        self.assertEqual(ids, ["ollama::think:1b", "ollama::tiny:1b", "cloud::gpt-fake"])
        self.assertEqual(r["errors"], [])

    def test_chat_flow_ollama_and_regenerate(self):
        s = self.call("POST", "/api/sessions", {})
        events = self.call("POST", "/api/chat", {"session_id": s["id"], "model": "ollama::tiny:1b", "content": "Hey there"})
        self.assertEqual(events[0]["type"], "start")
        self.assertEqual(events[0]["title"], "Hey there")
        self.assertEqual("".join(e["t"] for e in events if e["type"] == "text"), "Hello from Ollama")
        self.assertEqual(events[-1]["type"], "done")
        full = self.call("GET", f"/api/sessions/{s['id']}")
        self.assertEqual([m["role"] for m in full["messages"]], ["user", "assistant"])
        self.assertEqual(full["messages"][1]["content"], "Hello from Ollama")
        self.assertEqual(full["model"], "ollama::tiny:1b")
        # regenerate with another provider
        self.call("POST", "/api/chat", {"session_id": s["id"], "model": "cloud::gpt-fake",
                                        "truncate_from": full["messages"][1]["id"]})
        full = self.call("GET", f"/api/sessions/{s['id']}")
        self.assertEqual(len(full["messages"]), 2)
        self.assertEqual(full["messages"][1]["content"], "Hi from OpenAI")
        self.assertEqual(full["messages"][1]["model"], "cloud::gpt-fake")

    def test_thinking_is_wrapped_and_stripped_from_history(self):
        s = self.call("POST", "/api/sessions", {})
        self.call("POST", "/api/chat", {"session_id": s["id"], "model": "ollama::think:1b", "content": "q1"})
        full = self.call("GET", f"/api/sessions/{s['id']}")
        self.assertEqual(full["messages"][1]["content"], "<think>hmm</think>\n\nHello from Ollama")
        self.call("POST", "/api/chat", {"session_id": s["id"], "model": "ollama::tiny:1b", "content": "q2"})
        sent = FakeBackend.last_messages
        self.assertEqual(sent[0]["role"], "system")
        self.assertEqual(sent[2], {"role": "assistant", "content": "Hello from Ollama"})

    def test_memory_goes_into_system_prompt(self):
        n = self.call("POST", "/api/notes", {"content": "User is called Max", "is_memory": True})
        s = self.call("POST", "/api/sessions", {})
        self.call("POST", "/api/chat", {"session_id": s["id"], "model": "ollama::tiny:1b", "content": "who am i"})
        self.assertIn("User is called Max", FakeBackend.last_messages[0]["content"])
        self.call("DELETE", f"/api/notes/{n['id']}")

    def test_compare_streams_all_models(self):
        events = self.call("POST", "/api/compare", {"prompt": "x", "models": ["ollama::tiny:1b", "cloud::gpt-fake"]})
        texts = {0: "", 1: ""}
        for e in events:
            if e["type"] == "text":
                texts[e["i"]] += e["t"]
        self.assertEqual(texts, {0: "Hello from Ollama", 1: "Hi from OpenAI"})
        self.assertEqual(sum(e["type"] == "done" for e in events), 2)

    def test_documents_and_ai_edit(self):
        d = self.call("POST", "/api/documents", {"title": "Doc", "content": "abc"})
        d = self.call("PUT", f"/api/documents/{d['id']}", {"title": "Doc 2", "content": "abcd"})
        self.assertEqual((d["title"], d["content"]), ("Doc 2", "abcd"))
        events = self.call("POST", "/api/documents/ai", {"instruction": "shorter", "content": "abcd", "model": "cloud::gpt-fake"})
        self.assertEqual("".join(e["t"] for e in events if e["type"] == "text"), "Hi from OpenAI")
        self.call("DELETE", f"/api/documents/{d['id']}")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.call("GET", f"/api/documents/{d['id']}")
        self.assertEqual(cm.exception.code, 404)

    def test_research_flow(self):
        orig = research.search, research.read_page
        research.search = lambda q, limit=6: [{"title": "Page", "url": "https://example.com/" + q.replace(" ", "-")}]
        research.read_page = lambda url: ("Page " + url, "useful text " * 50)
        try:
            events = self.call("POST", "/api/research", {"question": "why is the sky blue", "model": "cloud::gpt-fake"})
        finally:
            research.search, research.read_page = orig
        types = [e["type"] for e in events]
        self.assertIn("sources", types)
        self.assertEqual(types[-1], "done")
        self.assertEqual("".join(e["t"] for e in events if e["type"] == "text"), "Hi from OpenAI")

    def test_pull_progress(self):
        events = self.call("POST", "/api/models/pull", {"model": "tiny:1b"})
        self.assertEqual(events[0], {"type": "progress", "status": "pulling", "completed": 5, "total": 10})
        self.assertEqual(events[-1]["type"], "done")

    def test_csrf_header_required(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.call("POST", "/api/sessions", {}, headers={"X-Requested-With": ""})
        self.assertEqual(cm.exception.code, 403)

    def test_static_and_traversal(self):
        self.assertIn("<title>Sunak</title>", self.call("GET", "/", raw=True))
        self.assertIn("function md(", self.call("GET", "/app.js", raw=True))
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.call("GET", "/../server.py", raw=True)
        self.assertEqual(cm.exception.code, 404)

    def test_unreachable_provider_reports_error(self):
        events = None
        s = self.call("POST", "/api/sessions", {})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.call("POST", "/api/chat", {"session_id": s["id"], "model": "nope::x", "content": "hi"})
        self.assertEqual(cm.exception.code, 400)
        self.assertIsNone(events)


class AuthTest(unittest.TestCase):
    def test_password_flow(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            srv = serve(make_server("127.0.0.1", 0, tmp))
            base = f"http://127.0.0.1:{srv.server_address[1]}"
            h = {"Content-Type": "application/json", "X-Requested-With": "sunak"}

            def req(method, path, body=None, cookie=None):
                hh = dict(h, **({"Cookie": cookie} if cookie else {}))
                r = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None, hh, method=method)
                return urllib.request.urlopen(r, timeout=5)

            req("PUT", "/api/settings", {"password": "secret1"})
            with self.assertRaises(urllib.error.HTTPError) as cm:
                req("GET", "/api/sessions")
            self.assertEqual(cm.exception.code, 401)
            self.assertIn("login", urllib.request.urlopen(base + "/", timeout=5).read().decode().lower())
            with self.assertRaises(urllib.error.HTTPError):
                req("POST", "/api/login", {"password": "wrong"})
            r = req("POST", "/api/login", {"password": "secret1"})
            cookie = r.headers["Set-Cookie"].split(";")[0]
            self.assertEqual(json.load(req("GET", "/api/sessions", cookie=cookie)), [])
            srv.shutdown()
            srv.server_close()


class UnitTest(unittest.TestCase):
    def test_stream_to_text(self):
        self.assertEqual(stream_to_text([("think", "a"), ("think", "b"), ("text", "c")]), "<think>ab</think>\n\nc")
        self.assertEqual(stream_to_text([("text", "x")]), "x")

    def test_recommend(self):
        self.assertEqual(recommend(4)["model"], "qwen3:1.7b")
        self.assertEqual(recommend(16)["model"], "qwen3:8b")
        self.assertEqual(recommend(64)["model"], "qwen3:14b")
        self.assertEqual(recommend(None)["model"], "qwen3:1.7b")

    def test_parse_ddg(self):
        page = ('<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa&amp;rut=x">'
                'Example <b>A</b></a>')
        self.assertEqual(research.parse_ddg(page), [{"title": "Example A", "url": "https://example.com/a"}])

    def test_html_to_text(self):
        title, text = research.html_to_text("<title>T</title><script>x()</script><p>Hello</p><p>World</p>")
        self.assertEqual(title, "T")
        self.assertEqual(text, "Hello\nWorld")


if __name__ == "__main__":
    unittest.main()
