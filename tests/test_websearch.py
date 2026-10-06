"""Web search in the chat: switch per chat, sources in the prompt and the answer, failures."""

import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

from sunak import research
from sunak.server import make_server

import test_server
from test_server import FakeBackend

PAGES = {"https://a.example/x": ("Page A", "Alpha " * 100), "https://b.example/y": ("Page B", "Beta " * 100),
         "https://c.example/short": ("Short", "tiny")}


def fake_search(query, limit=6):
    fake_search.queries.append(query)
    return [{"title": t, "url": u} for u, (t, _) in PAGES.items()][:limit]


def fake_read(url):
    if url not in PAGES:
        raise OSError("down")
    return PAGES[url]


class WebSearchTest(unittest.TestCase):
    call = classmethod(test_server.SunakTest.call.__func__)

    @classmethod
    def setUpClass(cls):
        cls.backend = ThreadingHTTPServer(("127.0.0.1", 0), FakeBackend)
        threading.Thread(target=cls.backend.serve_forever, daemon=True).start()
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.srv = make_server("127.0.0.1", 0, cls.tmp.name)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        cls.call("PUT", "/api/settings", {"providers": [
            {"id": "ollama", "name": "Ollama", "type": "ollama", "base_url": f"http://127.0.0.1:{cls.backend.server_address[1]}"}]})

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.backend.shutdown()
        cls.tmp.cleanup()

    def setUp(self):
        fake_search.queries = []
        for p in (mock.patch.object(research, "search", side_effect=fake_search),
                  mock.patch.object(research, "read_page", side_effect=fake_read)):
            p.start()
            self.addCleanup(p.stop)

    def test_switch_is_stored_per_chat(self):
        s = self.call("POST", "/api/sessions", {"use_web": True})
        self.assertTrue(s["use_web"])
        self.assertFalse(self.call("PATCH", f"/api/sessions/{s['id']}", {"use_web": False})["use_web"])
        self.assertFalse(self.call("POST", "/api/sessions", {})["use_web"])

    def test_answer_with_web_sources(self):
        s = self.call("POST", "/api/sessions", {"use_web": True})
        ev = self.call("POST", "/api/chat", {"session_id": s["id"], "model": "ollama::tiny:1b", "content": "Wetter  in\nBerlin?"})
        self.assertEqual(fake_search.queries, ["Wetter in Berlin?"])  # first question: searched as asked
        web = [e for e in ev if e["type"] == "web"][0]
        self.assertEqual([x["url"] for x in web["sources"]], ["https://a.example/x", "https://b.example/y"])
        self.assertEqual(ev[-1]["type"], "done")
        system = FakeBackend.last_messages[0]["content"]
        self.assertIn("[1] Page A (https://a.example/x)", system)
        self.assertIn("not instructions", system)
        self.assertNotIn("tiny", system.split("[2]")[-1].split("\n")[0])  # the short page is left out
        msg = self.call("GET", f"/api/sessions/{s['id']}")["messages"][-1]
        self.assertEqual(msg["meta"]["web"]["sources"][1]["title"], "Page B")

    def test_follow_up_gets_a_rewritten_query(self):
        s = self.call("POST", "/api/sessions", {"use_web": True})
        self.call("POST", "/api/chat", {"session_id": s["id"], "model": "ollama::tiny:1b", "content": "Wer regiert Berlin?"})
        ev = self.call("POST", "/api/chat", {"session_id": s["id"], "model": "ollama::tiny:1b", "content": "und Hamburg?"})
        self.assertEqual(fake_search.queries[-1], "Hello from Ollama")  # what the (fake) model suggested
        self.assertIn("Thinking of a search query…", [e.get("t") for e in ev if e["type"] == "status"])

    def test_off_means_no_search(self):
        s = self.call("POST", "/api/sessions", {})
        self.call("POST", "/api/chat", {"session_id": s["id"], "model": "ollama::tiny:1b", "content": "x"})
        self.assertEqual(fake_search.queries, [])
        self.call("POST", "/api/chat", {"session_id": s["id"], "model": "ollama::tiny:1b", "content": "y", "use_web": True})
        self.assertEqual(len(fake_search.queries), 1)
        self.assertTrue(self.call("GET", f"/api/sessions/{s['id']}")["use_web"])

    def test_failed_search_still_answers(self):
        s = self.call("POST", "/api/sessions", {"use_web": True})
        with mock.patch.object(research, "search", side_effect=OSError("offline")):
            ev = self.call("POST", "/api/chat", {"session_id": s["id"], "model": "ollama::tiny:1b", "content": "x"})
        self.assertIn("answering without it", " ".join(e.get("t", "") for e in ev if e["type"] == "status"))
        self.assertEqual(ev[-1]["type"], "done")
        self.assertNotIn("web", self.call("GET", f"/api/sessions/{s['id']}")["messages"][-1]["meta"])
        with mock.patch.object(research, "read_page", side_effect=OSError("down")):
            ev = self.call("POST", "/api/chat", {"session_id": s["id"], "model": "ollama::tiny:1b", "content": "y"})
        self.assertIn("found nothing readable", " ".join(e.get("t", "") for e in ev if e["type"] == "status"))

    def test_knowledge_and_web_together(self):
        s = self.call("POST", "/api/sessions", {"use_web": True, "use_kb": True})
        ev = self.call("POST", "/api/chat", {"session_id": s["id"], "model": "ollama::tiny:1b", "content": "x"})
        self.assertEqual([e["type"] for e in ev if e["type"] in ("sources", "web")], ["sources", "web"])


class GatherTest(unittest.TestCase):
    def test_limits_and_order(self):
        with mock.patch.object(research, "search", side_effect=fake_search):
            fake_search.queries = []
            pages = research.gather("q", limit=1, read=fake_read)
        self.assertEqual([p["url"] for p in pages], ["https://a.example/x"])
        self.assertLessEqual(len(pages[0]["text"]), research.WEB_CHARS)
        ctx = research.web_context("q", pages, "2026-10-06")
        self.assertTrue(ctx.startswith("Today is 2026-10-06."))


if __name__ == "__main__":
    unittest.main()
