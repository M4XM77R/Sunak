"""Automatic memory (sunak/memory.py): facts the chat's model picks up after an answer become memory notes.
Run:  python -m unittest discover tests"""

import json
import tempfile
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

from sunak import memory
from sunak.server import make_server
from test_server import FakeBackend, serve


class ParseTest(unittest.TestCase):
    def test_json_array_with_thinking_and_chatter(self):
        self.assertEqual(memory.parse('<think>hm</think>Sure: ["Name is Max.", "Likes  short answers.", 3]'),
                         ["Name is Max.", "Likes short answers."])

    def test_dash_list_fallback_and_nothing(self):
        self.assertEqual(memory.parse("- Lives in Graz.\n* Codes in Python.\nother"), ["Lives in Graz.", "Codes in Python."])
        self.assertEqual(memory.parse("[]"), [])
        self.assertEqual(memory.parse("Nothing new."), [])

    def test_clean_drops_secrets_duplicates_and_limits(self):
        facts = ["Name is Max.", "name is max", "Password for Gmail is hunter2.", "API key is sk-abcdefghijkl.",
                 "Card 4111 1111 1111 1111.", "Lives in Graz.", "Likes cats.", "Plays chess.", "x" * 300]
        self.assertEqual(memory.clean(facts, ["Lives in Graz."]), ["Name is Max.", "Likes cats.", "Plays chess."])

    def test_explicit(self):
        for t in ("Merk dir, dass ich Max heiße", "please remember that I use Linux", "Vergiss nicht: ich bin Veganer"):
            self.assertTrue(memory.is_explicit(t), t)
        for t in ("What is the capital of France?", "Remembrance Day is in November"):
            self.assertFalse(memory.is_explicit(t), t)


class RememberEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = serve(ThreadingHTTPServer(("127.0.0.1", 0), FakeBackend))
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.app = serve(make_server("127.0.0.1", 0, cls.tmp.name))
        cls.base = f"http://127.0.0.1:{cls.app.server_address[1]}"
        cls.call("PUT", "/api/settings", {"providers": [
            {"id": "ollama", "name": "Ollama", "type": "ollama", "base_url": f"http://127.0.0.1:{cls.backend.server_address[1]}"}]})

    @classmethod
    def tearDownClass(cls):
        cls.app.shutdown()
        cls.backend.shutdown()
        cls.app.server_close()
        cls.tmp.cleanup()

    @classmethod
    def call(cls, method, path, body=None):
        req = urllib.request.Request(cls.base + path, data=json.dumps(body).encode() if body is not None else None,
                                     method=method, headers={"Content-Type": "application/json", "X-Requested-With": "sunak"})
        with urllib.request.urlopen(req, timeout=10) as r:
            text = r.read().decode()
        return [json.loads(x) for x in text.splitlines() if x.strip()] if "ndjson" in r.headers["Content-Type"] else json.loads(text)

    def tearDown(self):
        for n in self.call("GET", "/api/notes"):
            self.call("DELETE", f"/api/notes/{n['id']}")
        self.call("PUT", "/api/settings", {"use_memory": True, "auto_memory": True})

    def chat(self, text):
        s = self.call("POST", "/api/sessions", {})
        self.call("POST", "/api/chat", {"session_id": s["id"], "model": "ollama::tiny:1b", "content": text})
        return s["id"]

    def remember(self, sid, reply):
        with mock.patch("sunak.memory.providers.chat_once", return_value=reply) as m:
            r = self.call("POST", f"/api/sessions/{sid}/remember", {})
        return r, m

    def test_facts_become_memory_notes_with_their_chat(self):
        sid = self.chat("I'm Max and I like short answers")
        r, m = self.remember(sid, '["Name is Max.", "Prefers short answers."]')
        self.assertEqual([n["content"] for n in r["added"]], ["Name is Max.", "Prefers short answers."])
        prompt = m.call_args[0][2]
        self.assertIn("USER: I'm Max and I like short answers", prompt[1]["content"])
        self.assertIn("ASSISTANT: Hello from Ollama", prompt[1]["content"])
        notes = self.call("GET", "/api/notes")
        self.assertTrue(all(n["is_memory"] and n["source"] == sid and n["source_title"] for n in notes))
        # known facts go to the model and are never stored twice
        r, m = self.remember(sid, '["Name is Max.", "Lives in Graz."]')
        self.assertEqual([n["content"] for n in r["added"]], ["Lives in Graz."])
        self.assertIn("- Name is Max.", m.call_args[0][2][1]["content"])
        # the next chat knows them
        self.chat("hi")
        self.assertIn("Lives in Graz.", FakeBackend.last_messages[0]["content"])
        # a deleted chat leaves the memory, without a title
        self.call("DELETE", f"/api/sessions/{sid}")
        self.assertTrue(all(n["source_title"] is None for n in self.call("GET", "/api/notes")))

    def test_switches_and_explicit_requests(self):
        self.call("PUT", "/api/settings", {"auto_memory": False})
        r, m = self.remember(self.chat("I live in Graz"), '["Lives in Graz."]')
        self.assertEqual((r["added"], m.called), ([], False))
        r, m = self.remember(self.chat("Merk dir: ich heiße Max"), '["Heißt Max."]')
        self.assertEqual([n["content"] for n in r["added"]], ["Heißt Max."])
        self.assertIn("explicitly asks", m.call_args[0][2][0]["content"])
        self.call("PUT", "/api/settings", {"use_memory": False})
        r, m = self.remember(self.chat("Merk dir: ich mag Katzen"), '["Mag Katzen."]')
        self.assertEqual((r["added"], m.called), ([], False))

    def test_secrets_and_model_errors(self):
        r, m = self.remember(self.chat("my wifi password is hunter2"), '["WiFi password is hunter2."]')
        self.assertEqual((r["added"], m.called), ([], False))
        r, _ = self.remember(self.chat("remember my PIN 1234"), '["PIN is 1234."]')
        self.assertEqual(r["added"], [])
        with mock.patch("sunak.memory.providers.chat_once", side_effect=memory.providers.ProviderError("down")):
            r = self.call("POST", f"/api/sessions/{self.chat('I am Max')}/remember", {})
        self.assertEqual(r, {"added": [], "error": "down"})
        self.assertEqual(self.call("GET", "/api/notes"), [])

    def test_nothing_before_an_answer(self):
        s = self.call("POST", "/api/sessions", {})
        r, m = self.remember(s["id"], '["x"]')
        self.assertEqual((r["added"], m.called), ([], False))
