"""End-to-end tests against fake Ollama, Claude (Anthropic) and OpenAI-compatible backends.
Run:  python -m unittest discover tests"""

import base64
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sunak import ollama, providers, research
from sunak.providers import ProviderError
from sunak.server import make_server, recommend, stream_to_text


class FakeBackend(BaseHTTPRequestHandler):
    """Speaks just enough of the Ollama, Anthropic and OpenAI APIs."""

    last_messages = None
    last_body = None
    last_headers = None

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
        if self.path == "/api/version":
            return self._json({"version": "0.12.3"})
        if self.path == "/api/tags":
            return self._json({"models": [{"name": "tiny:1b"}, {"name": "think:1b"}]})
        if self.path == "/v1/models":
            return self._json({"data": [{"id": "gpt-fake"}]})
        if self.path.startswith("/anthropic/v1/models"):
            if self.headers.get("x-api-key") != "sk-test" or self.headers.get("anthropic-version") != "2023-06-01":
                return self.send_error(401)
            return self._json({"data": [{"id": "claude-opus-5-5"}, {"id": "claude-haiku-4-5"}], "has_more": False})
        self.send_error(404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).last_messages = body.get("messages")
        type(self).last_body = body
        type(self).last_headers = dict(self.headers)
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
        elif self.path == "/anthropic/v1/messages":
            def sse(event, data):
                self.wfile.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())
            sse("message_start", {"type": "message_start", "message": {"id": "msg_1"}})
            sse("content_block_start", {"type": "content_block_start", "index": 0,
                                        "content_block": {"type": "thinking", "thinking": ""}})
            sse("content_block_delta", {"type": "content_block_delta", "index": 0,
                                        "delta": {"type": "thinking_delta", "thinking": "hmm"}})
            sse("content_block_stop", {"type": "content_block_stop", "index": 0})
            for w in ["Hi", " from", " Claude"]:
                sse("content_block_delta", {"type": "content_block_delta", "index": 1,
                                            "delta": {"type": "text_delta", "text": w}})
            stop = "refusal" if body["model"] == "claude-refuse" else "end_turn"
            sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop}})
            sse("message_stop", {"type": "message_stop"})
        elif self.path == "/api/pull":
            for ev in [{"status": "pulling manifest"},
                       {"status": "pulling a", "digest": "a", "completed": 5, "total": 10},
                       {"status": "pulling b", "digest": "b", "completed": 0, "total": 30},
                       {"status": "pulling b", "digest": "b", "completed": 30, "total": 30},
                       {"status": "success"}]:
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
            {"id": "claude", "name": "Claude", "type": "anthropic", "base_url": f"http://127.0.0.1:{cls.bport}/anthropic",
             "api_key": "sk-test"},
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
        self.assertEqual(ids, ["ollama::think:1b", "ollama::tiny:1b", "cloud::gpt-fake",
                               "claude::claude-opus-5-5", "claude::claude-haiku-4-5"])
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
        progress = [(e["completed"], e["total"]) for e in events if e["type"] == "progress"]
        self.assertEqual(progress, [(0, 0), (5, 10), (5, 40), (35, 40), (35, 40)])
        self.assertEqual(events[-1]["type"], "done")

    def test_ollama_status_and_catalog(self):
        st = self.call("GET", "/api/ollama")
        self.assertTrue(st["running"])
        self.assertTrue(st["installed"])
        self.assertTrue(st["local"])
        self.assertEqual(st["version"], "0.12.3")
        self.assertEqual([m["name"] for m in st["models"]], ["think:1b", "tiny:1b"])
        self.assertIn("qwen3:4b", [m["name"] for m in st["catalog"]])
        self.assertTrue(all("fits" in m for m in st["catalog"]))
        self.assertIn(st["install"]["method"], ("winget", "brew", "script", "download"))

    def test_ollama_start_refuses_remote(self):
        with self.assertRaises(ProviderError):
            ollama.start({"base_url": "http://192.168.1.50:11434"})

    def test_pull_rejects_bad_names(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.call("POST", "/api/models/pull", {"model": "x; rm -rf /"})
        self.assertEqual(cm.exception.code, 400)

    def test_claude_chat(self):
        s = self.call("POST", "/api/sessions", {"system": "Be brief."})
        events = self.call("POST", "/api/chat", {"session_id": s["id"], "model": "claude::claude-opus-5-5", "content": "Hi"})
        self.assertEqual("".join(e["t"] for e in events if e["type"] == "text"), "Hi from Claude")
        self.assertEqual("".join(e["t"] for e in events if e["type"] == "think"), "hmm")
        full = self.call("GET", f"/api/sessions/{s['id']}")
        self.assertEqual(full["messages"][1]["content"], "<think>hmm</think>\n\nHi from Claude")
        body, headers = FakeBackend.last_body, {k.lower(): v for k, v in FakeBackend.last_headers.items()}
        self.assertEqual(headers["x-api-key"], "sk-test")
        self.assertEqual(headers["anthropic-version"], "2023-06-01")
        self.assertNotIn("authorization", headers)
        self.assertIn("Be brief.", body["system"])
        self.assertEqual(body["messages"], [{"role": "user", "content": "Hi"}])
        self.assertEqual(body["thinking"], {"type": "adaptive", "display": "summarized"})
        self.assertTrue(body["stream"])
        self.assertNotIn("temperature", body)
        self.assertNotIn("fallbacks", body)  # only sent to api.anthropic.com
        # follow-up turn: reasoning is not sent back
        self.call("POST", "/api/chat", {"session_id": s["id"], "model": "claude::claude-haiku-4-5", "content": "More"})
        body = FakeBackend.last_body
        self.assertEqual([m["role"] for m in body["messages"]], ["user", "assistant", "user"])
        self.assertEqual(body["messages"][1]["content"], "Hi from Claude")
        self.assertNotIn("thinking", body)  # Haiku 4.5 has no adaptive thinking

    def test_claude_in_compare(self):
        events = self.call("POST", "/api/compare", {"prompt": "x", "models": ["claude::claude-opus-5-5", "cloud::gpt-fake"]})
        self.assertEqual("".join(e["t"] for e in events if e["type"] == "text" and e["i"] == 0), "Hi from Claude")

    def test_claude_refusal_is_reported(self):
        s = self.call("POST", "/api/sessions", {})
        events = self.call("POST", "/api/chat", {"session_id": s["id"], "model": "claude::claude-refuse", "content": "x"})
        self.assertEqual(events[-1]["type"], "error")
        self.assertIn("declined", events[-1]["error"])

    def test_api_keys_never_reach_the_browser(self):
        st = self.call("GET", "/api/settings")
        claude = next(p for p in st["providers"] if p["id"] == "claude")
        self.assertNotIn("api_key", claude)
        self.assertTrue(claude["has_key"])
        self.assertFalse(next(p for p in st["providers"] if p["id"] == "ollama")["has_key"])
        self.assertNotIn("sk-test", json.dumps(st))
        # saving the masked list back (empty key field) keeps the stored key
        st = self.call("PUT", "/api/settings", {"providers": [dict(p, api_key="") for p in st["providers"]]})
        self.assertNotIn("sk-test", json.dumps(st))
        ids = [m["id"] for m in self.call("GET", "/api/models")["models"]]
        self.assertIn("claude::claude-opus-5-5", ids)

    def test_claude_bad_key_and_fallback_list(self):
        p = {"id": "c", "type": "anthropic", "base_url": f"http://127.0.0.1:{self.bport}/anthropic", "api_key": "wrong"}
        with self.assertRaises(ProviderError) as cm:
            providers.list_models(p)
        self.assertIn("API key", str(cm.exception))
        self.assertNotIn("wrong", str(cm.exception))
        p = dict(p, base_url=f"http://127.0.0.1:{self.bport}/nowhere", api_key="sk-test")
        self.assertEqual(providers.list_models(p), providers.CLAUDE_FALLBACK_MODELS)

    def test_knowledge_base_in_chat(self):
        data = base64.b64encode("Die Hauptstadt von Atlantis heißt Poseidonia.".encode()).decode()
        f = self.call("POST", "/api/knowledge", {"name": "atlantis.md", "data": data})
        self.assertEqual((f["name"], f["chars"]), ("atlantis.md", 45))
        listing = self.call("GET", "/api/knowledge")
        self.assertEqual([x["name"] for x in listing["files"]], ["atlantis.md"])
        hits = self.call("GET", "/api/knowledge/search?q=Poseidonia")
        self.assertEqual(hits[0]["name"], "atlantis.md")
        self.assertIn("Poseidonia", hits[0]["snippet"])
        self.assertEqual(self.call("GET", f"/api/knowledge/{f['id']}")["text"], "Die Hauptstadt von Atlantis heißt Poseidonia.")
        # chat with the knowledge base switched on: excerpts in the system prompt, sources event and stored meta
        s = self.call("POST", "/api/sessions", {"use_kb": True})
        self.assertTrue(s["use_kb"])
        events = self.call("POST", "/api/chat", {"session_id": s["id"], "model": "ollama::tiny:1b", "content": "Hauptstadt?"})
        self.assertEqual(events[1], {"type": "sources", "sources": [{"id": f["id"], "name": "atlantis.md"}]})
        self.assertIn("[atlantis.md]\nDie Hauptstadt", FakeBackend.last_messages[0]["content"])
        full = self.call("GET", f"/api/sessions/{s['id']}")
        self.assertEqual(full["messages"][1]["meta"]["sources"][0]["name"], "atlantis.md")
        # switched off in the request: no excerpts, stored on the chat
        events = self.call("POST", "/api/chat", {"session_id": s["id"], "model": "ollama::tiny:1b", "content": "x", "use_kb": False})
        self.assertNotIn("sources", [e["type"] for e in events])
        self.assertNotIn("Poseidonia", FakeBackend.last_messages[0]["content"])
        self.assertFalse(self.call("GET", f"/api/sessions/{s['id']}")["use_kb"])
        self.call("DELETE", f"/api/knowledge/{f['id']}")
        self.assertEqual(self.call("GET", "/api/knowledge")["files"], [])

    def test_title_ignores_attached_files(self):
        s = self.call("POST", "/api/sessions", {})
        ev = self.call("POST", "/api/chat", {"session_id": s["id"], "model": "ollama::tiny:1b",
                                             "content": "File `a.txt`:\n```\nlong text\n```\n\nSummarize this"})
        self.assertEqual(ev[0]["title"], "Summarize this")

    def test_extract_and_bad_uploads(self):
        r = self.call("POST", "/api/extract", {"name": "n.txt", "data": base64.b64encode(b"note").decode()})
        self.assertEqual(r, {"name": "n.txt", "text": "note"})
        for body, msg in (({"name": "x.txt", "data": "%%%"}, "damaged"), ({"name": "", "data": ""}, "name"),
                          ({"name": "x.pdf", "data": base64.b64encode(b"%PDF-1.4 nothing").decode()}, "no text"),
                          ({"name": "e.txt", "data": ""}, "no text")):
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self.call("POST", "/api/knowledge", body)
            self.assertIn(msg, json.loads(cm.exception.read())["error"])

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

    def test_claude_payload(self):
        p = {"id": "c", "type": "anthropic", "base_url": "https://api.anthropic.com", "api_key": "k"}
        msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "a"}, {"role": "user", "content": "b"}]
        body, headers = providers.anthropic_payload(p, "claude-opus-5-5", msgs)
        self.assertEqual(body["system"], "S")
        self.assertEqual(body["messages"], [{"role": "user", "content": "a\n\nb"}])
        self.assertEqual(body["fallbacks"], "default")
        self.assertEqual(headers["anthropic-beta"], "server-side-fallback-2026-07-01")
        body, headers = providers.anthropic_payload(p, "claude-haiku-4-5", msgs)
        self.assertNotIn("fallbacks", body)
        self.assertNotIn("anthropic-beta", headers)
        with self.assertRaises(ProviderError):
            providers.anthropic_payload(dict(p, api_key=""), "claude-opus-5-5", msgs)

    def test_claude_model_rules(self):
        self.assertTrue(providers.adaptive_thinking("claude-opus-5-5"))
        self.assertTrue(providers.adaptive_thinking("claude-sonnet-4-6"))
        self.assertTrue(providers.adaptive_thinking("claude-fable-5-1"))
        self.assertFalse(providers.adaptive_thinking("claude-haiku-4-5"))
        self.assertFalse(providers.adaptive_thinking("claude-sonnet-4-5-20250929"))
        self.assertEqual(providers.claude_max_tokens("claude-opus-5-5"), 64000)
        self.assertEqual(providers.claude_max_tokens("claude-opus-4-1-20250805"), 32000)
        self.assertEqual(providers.claude_max_tokens("claude-3-haiku-20240307"), 4096)

    def test_fits(self):
        self.assertTrue(ollama.fits(2.6, 8))
        self.assertFalse(ollama.fits(9.3, 8))
        self.assertTrue(ollama.fits(19, None))

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
