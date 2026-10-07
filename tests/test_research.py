"""Deep Research and web search robustness: search queries from models like Qwen, search engine fallback,
honest error messages, and picture requests in the research view."""

import tempfile
import threading
import unittest
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from sunak import research
from sunak.server import make_server

import test_server
from test_server import FakeBackend

Q = "Wie wird das Wetter morgen in Berlin?"
DDG_BLOCK = '<html><form id="challenge-form"><div class="anomaly-modal">Please complete the captcha</div></form></html>'
BING = ('<ol><li class="b_algo"><h2><a href="https://www.bing.com/ck/a?!&&p=x&u=a1aHR0cHM6Ly9leGFtcGxlLmNvbS9hYmM&ntb=1">Example ABC</a></h2></li>'
        '<li class="b_algo"><h2><a href="https://direct.example/page">Direct</a></h2></li></ol>')
LITE = '<a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Flite.example%2Fz&rut=1" class=\'result-link\'>Lite Z</a>'


class QueryTest(unittest.TestCase):
    def test_qwen_style_answers(self):
        cases = {
            "<think>\nOkay, the user wants weather.\n</think>\n\nWetter Berlin morgen\nBerlin Wettervorhersage": ["Wetter Berlin morgen", "Berlin Wettervorhersage"],
            "<think>\nOkay, let me think about this and never finish": [Q],  # unfinished reasoning: the question itself
            "": [Q],
            "   \n\n": [Q],
            '1. **"Wetter Berlin morgen"**\n2. - Berlin 7 Tage\n3) Query: Regen Berlin': ["Wetter Berlin morgen", "Berlin 7 Tage", "Regen Berlin"],
            "Here are three search queries:\nwetter berlin\nWetter Berlin": ["wetter berlin"],  # chatty line out, duplicate out
            "Okay, so the user asks about the weather in Berlin tomorrow and I should return queries": [Q],
            "x " * 200: [Q],  # far too long for a query
        }
        for raw, want in cases.items():
            self.assertEqual(research.clean_queries(raw, Q), want, raw[:40])

    def test_max_three_and_long_question(self):
        self.assertEqual(len(research.clean_queries("a\nb\nc\nd\ne", Q)), 3)
        self.assertEqual(len(research.clean_queries("", "word " * 100)[0]), 200)


class EngineTest(unittest.TestCase):
    def test_parsers(self):
        self.assertEqual(research.parse_bing(BING), [{"title": "Example ABC", "url": "https://example.com/abc"},
                                                     {"title": "Direct", "url": "https://direct.example/page"}])
        self.assertEqual(research.parse_ddg_lite(LITE), [{"title": "Lite Z", "url": "https://lite.example/z"}])

    def test_robot_check_is_an_error_not_no_results(self):
        with self.assertRaises(PermissionError):
            research._parsed(research.parse_ddg, DDG_BLOCK)
        self.assertEqual(research._parsed(research.parse_ddg, "<html>nothing here</html>"), [])

    def test_falls_back_to_the_next_engine(self):
        def blocked(q):
            raise PermissionError("robot check")
        found = research.search("q", engines=[("A", blocked), ("B", lambda q: []), ("C", lambda q: [{"title": "t", "url": "https://x.example"}])])
        self.assertEqual(found[0]["url"], "https://x.example")

    def test_all_blocked_says_why_each(self):
        def down(q):
            raise urllib.error.URLError("Name or service not known")
        def blocked(q):
            raise urllib.error.HTTPError("u", 403, "no", {}, None)
        with self.assertRaises(research.SearchError) as cm:
            research.search("q", engines=[("A", down), ("B", blocked)])
        self.assertIn("A not reachable", str(cm.exception))
        self.assertIn("B blocked the request (HTTP 403)", str(cm.exception))

    def test_nothing_found_is_not_offline(self):
        self.assertEqual(research.search("q", engines=[("A", lambda q: [])]), [])  # single engine (SearXNG): just empty
        with self.assertRaises(research.SearchError) as cm:
            research.search("q", engines=[("A", lambda q: []), ("B", lambda q: [])])
        self.assertIn("found nothing", str(cm.exception))


class ResearchEndpointTest(unittest.TestCase):
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

    def run_research(self, plan, search):
        seen = []

        def fake_search(q, limit=6):
            seen.append(q)
            return search(q)
        with mock.patch.object(research, "search", side_effect=fake_search), \
                mock.patch.object(research, "read_page", return_value=("Page", "useful text " * 50)), \
                mock.patch("sunak.server.providers.chat_once", return_value=plan if not isinstance(plan, Exception) else ""
                           ) as once:
            if isinstance(plan, Exception):
                once.side_effect = plan
            events = self.call("POST", "/api/research", {"question": Q, "model": "ollama::tiny:1b"})
        return events, seen

    def page(self, q):
        return [{"title": "P", "url": "https://example.com/" + str(abs(hash(q)) % 1000)}]

    def test_qwen_think_only_plan_searches_the_question(self):
        events, seen = self.run_research("<think>Okay, the user asks about weather and I will never finish", self.page)
        self.assertEqual(seen, [Q])
        self.assertEqual(events[-1]["type"], "done")

    def test_plan_with_noise_gives_clean_queries(self):
        events, seen = self.run_research("<think>hmm</think>\n1. **Wetter Berlin**\n2. \"Berlin morgen\"", self.page)
        self.assertEqual(seen[:2], ["Wetter Berlin", "Berlin morgen"])
        self.assertNotIn(Q, seen)  # found something, the last resort is not needed
        self.assertEqual(events[-1]["type"], "done")

    def test_question_is_the_last_resort(self):
        events, seen = self.run_research("alpha\nbeta", lambda q: self.page(q) if q == Q else [])
        self.assertEqual(seen, ["alpha", "beta", Q])
        self.assertEqual(events[-1]["type"], "done")

    def test_failing_model_plan_still_searches(self):
        events, seen = self.run_research(test_server.providers.ProviderError("boom"), self.page)
        self.assertEqual(seen, [Q])
        self.assertEqual(events[-1]["type"], "done")

    def test_engines_not_usable_says_so(self):
        def blocked(q):
            raise research.SearchError("DuckDuckGo blocked the request (robot check); Bing not reachable (timed out)")
        events, _ = self.run_research("a\nb", blocked)
        err = events[-1]["error"]
        self.assertIn("not working", err)
        self.assertIn("DuckDuckGo blocked", err)
        self.assertIn("SEARXNG_URL", err)
        self.assertNotIn("offline", err)

    def test_empty_results_are_not_called_offline(self):
        events, _ = self.run_research("a\nb", lambda q: [])
        err = events[-1]["error"]
        self.assertIn("found nothing", err)
        self.assertNotIn("not working", err)

    def test_chat_web_query_from_noisy_model(self):
        s = self.call("POST", "/api/sessions", {"use_web": True})
        seen = []
        with mock.patch.object(research, "search", side_effect=lambda q, limit=6: seen.append(q) or []), \
                mock.patch("sunak.server.providers.chat_once", return_value="<think>x</think>\n**\"Wetter Berlin\"**\nzweite Zeile"):
            self.call("POST", "/api/chat", {"session_id": s["id"], "model": "ollama::tiny:1b", "content": "Hallo"})  # first message: searched as asked
            self.call("POST", "/api/chat", {"session_id": s["id"], "model": "ollama::tiny:1b", "content": "und morgen?"})
        self.assertEqual(seen, ["Hallo", "Wetter Berlin"])


class PictureEverywhereTest(unittest.TestCase):
    """Every path a typed message can take asks the server first (the browser side lives in app.js)."""
    JS = (Path(__file__).resolve().parent.parent / "sunak" / "static" / "app.js").read_text(encoding="utf-8")

    def test_chat_and_agent_ask_before_sending(self):
        self.assertIn("await pictureIntent(text, agentOn(), agentOn() ? 'agent' : 'chat')", self.JS)

    def test_research_asks_before_searching(self):
        form = self.JS.split("$('#researchForm').onsubmit")[1][:400]
        self.assertIn("divertPicture(q, 'research')", form)
        self.assertLess(form.index("divertPicture"), form.index("/api/research") if "/api/research" in form else 10**9)

    def test_check_is_logged_even_for_normal_messages(self):
        with mock.patch("sunak.server.log_image") as log:
            srv = ResearchEndpointTest
            srv.setUpClass()
            try:
                r = srv.call("POST", "/api/imagine/intent", {"text": "Wie spät ist es in Tokio?", "where": "research", "quick": True})
            finally:
                srv.tearDownClass()
        self.assertFalse(r["image"])
        args = log.info.call_args[0]
        self.assertIn("Picture request check", args[0])
        self.assertEqual(args[1], "research")
        self.assertNotIn("Tokio", " ".join(str(a) for a in args))


if __name__ == "__main__":
    unittest.main()
