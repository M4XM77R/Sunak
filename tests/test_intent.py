"""Recognising picture requests in the chat (sunak/intent.py and POST /api/imagine/intent).
Run:  python -m unittest discover tests"""

import json
import tempfile
import threading
import unittest
import urllib.request
from unittest import mock

from sunak import intent
from sunak.server import make_server

YES = ["Generiere ein Bild von einem Fuchs", "erstell ein Bild von einem Berg", "Kannst du ein Bild von einem Hund generieren?",
       "generate an image of a fox", "Make a picture of a red car", "create a logo for my bakery", "Erschaffe ein Bild von einer Burg",
       "Bitte ein Bild von einem Fuchs generieren", "a picture of: a mountainous landscape covered in snow",
       "picture of a red barn", "a picture of a cat please", "image of a cat on a sofa", "Bild von einem Fuchs im Wald", "Foto von einem Strand bei Nacht",
       "Bild: Leuchtturm im Sturm", "draw a cat", "Draw me a dragon", "zeichne einen Drachen", "Zeichne mir ein Haus am See",
       "mal mir eine Katze", "Male mir bitte ein Haus", "could you create an image of a boat?", "Mach mir ein Foto von einem Strand bei Sonnenuntergang"]
MAYBE = ["Mal einen Drachen", "Ich hätte gern ein Foto von einem Strand",
         "Zeig mir ein Bild von einem Fuchs", "Wie erstelle ich ein Bild in Photoshop?",
         "Schreibe ein Python-Skript, das ein Bild erzeugt", "wie funktioniert ein Bild-Sensor, erzeuge ich damit Fotos?",
         "Ich mache gleich ein Foto vom Essen und schicke es dir", "Ich möchte, dass du ein Bild von einem Hund erstellst"]
NO = ["Was ist die Hauptstadt von Frankreich?", "Mal sehen, was das wird", "Erkläre mir die Bildung im Mittelalter", "Fasse den Text zusammen",
      "Photoshop ist teuer", "Wie installiere ich Docker image?", "Übersetze das ins Englische", "", "x" * 700 + " Bild generieren"]


class ClassifyTest(unittest.TestCase):
    def test_clear_requests_are_yes(self):
        for t in YES:
            self.assertEqual(intent.classify(t), "yes", t)

    def test_unclear_messages_are_maybe(self):
        for t in MAYBE:
            self.assertEqual(intent.classify(t), "maybe", t)

    def test_everything_else_is_no(self):
        for t in NO:
            self.assertEqual(intent.classify(t), "no", t)

    def test_subject_without_the_request_words(self):
        for text, want in (("Generiere ein Bild von einem Fuchs", "einem Fuchs"), ("mal mir eine Katze bitte", "eine Katze"),
                           ("draw me a cat", "a cat"), ("a picture of: a mountainous landscape covered in snow", "a mountainous landscape covered in snow"),
                           ("Bild: Leuchtturm im Sturm", "Leuchtturm im Sturm"), ("Foto von einem Strand bei Nacht", "einem Strand bei Nacht"), ("generate an image of a lighthouse at dusk, please", "a lighthouse at dusk"),
                           ("Zeichne einen Drachen im Schnee", "einen Drachen im Schnee")):
            self.assertEqual(intent.subject(text), want, text)

    def test_answer_of_the_model(self):
        for a, want in (("YES", True), ("Yes.", True), ("Ja", True), ("NO", False), ("No, it is a question", False), ("", False),
                        ("I think not", False)):
            self.assertEqual(intent.parse(a), want, a)


def model_says(answer):
    """A fake chat model that streams `answer`."""
    def fake(prov, model, messages, options=None):
        yield ("text", answer)
    return fake


class EndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.srv = make_server("127.0.0.1", 0, cls.tmp.name)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def setUp(self):
        self.call("PUT", "/api/settings", {"image_gen": "automatic1111", "image_gen_url": "http://127.0.0.1:9", "ai_image_detect": True})

    def call(self, method, path, body=None):
        r = urllib.request.Request(self.base + path, json.dumps(body).encode() if body is not None else None,
                                   {"Content-Type": "application/json", "X-Requested-With": "sunak"}, method=method)
        with urllib.request.urlopen(r, timeout=10) as resp:
            return json.loads(resp.read())

    def ask(self, text, **kw):
        return self.call("POST", "/api/imagine/intent", {"text": text, "model": "ollama::tiny:1b", **kw})

    def test_unclear_messages_are_put_to_the_chat_model_when_pictures_are_set_up(self):
        with mock.patch("sunak.server.providers.chat_stream", model_says("YES")):
            r = self.ask("Ein Fuchs im Schnee, fotorealistisch, 4k")  # no picture word at all
            self.assertEqual((r["image"], r["via"], r["subject"]), (True, "model", "Ein Fuchs im Schnee, fotorealistisch, 4k"))
        for answer in ("NO", "Sure, here is how", ""):  # only a YES makes a picture
            with mock.patch("sunak.server.providers.chat_stream", model_says(answer)):
                for text in ("Wie erstelle ich ein Bild in Photoshop?", "Was ist die Hauptstadt von Frankreich?"):
                    r = self.ask(text)
                    self.assertEqual((r["image"], r["via"]), (False, "model"), (answer, text))

    def test_clear_requests_are_painted_without_asking_the_model(self):
        with mock.patch("sunak.server.providers.chat_stream", side_effect=AssertionError("not asked")):
            for text in ("Generiere ein Bild von einem Fuchs", "generiere mir ein bild von einem Fuchs",
                         "a picture of: a mountainous landscape covered in snow"):
                r = self.ask(text)
                self.assertEqual((r["image"], r["via"]), (True, "rules"), text)

    def test_only_the_last_message_goes_to_the_model(self):
        seen = []

        def fake(prov, model, messages, options=None):
            seen.append(messages)
            yield ("text", "YES")
        with mock.patch("sunak.server.providers.chat_stream", fake):
            self.ask("Mal einen Drachen")
        self.assertEqual([m["role"] for m in seen[0]], ["system", "user"])
        self.assertEqual(seen[0][1]["content"], "Mal einen Drachen")

    def test_rules_decide_when_the_model_cannot(self):
        from sunak import providers

        def broken(prov, model, messages, options=None):
            raise providers.ProviderError("down")
            yield
        with mock.patch("sunak.server.providers.chat_stream", broken):
            r = self.ask("Generiere ein Bild von einem Fuchs")
            self.assertEqual((r["image"], r["via"], r["subject"]), (True, "rules", "einem Fuchs"))
            self.assertFalse(self.ask("Mal einen Drachen")["image"])  # unclear without a model answer: a normal message

    def test_slow_model_is_given_up_on(self):
        import time

        def slow(prov, model, messages, options=None):
            time.sleep(1.5)
            yield ("text", "NO")
        with mock.patch("sunak.server.providers.chat_stream", slow), mock.patch("sunak.server.App.ask_intent.__defaults__", (0.2,)):
            r = self.ask("Ein Fuchs im Schnee")
        self.assertEqual((r["image"], r["via"]), (False, "rules"))

    def test_busy_model_is_not_asked(self):
        from sunak import jobqueue, providers
        key = providers.queue_key({"id": "ollama"})
        g = jobqueue.gate(key, 1)
        g.acquire()
        try:
            with mock.patch("sunak.server.providers.chat_stream", side_effect=AssertionError("busy: not asked")):
                r = self.ask("Ein Fuchs im Schnee")
            self.assertEqual((r["image"], r["via"]), (False, "rules"))
        finally:
            g.release()

    def test_no_extra_call_when_pictures_are_off_or_the_setting_is_off_or_quick(self):
        with mock.patch("sunak.server.providers.chat_stream", side_effect=AssertionError("not asked")):
            self.assertTrue(self.ask("generiere mir ein bild von einem Fuchs", quick=True)["image"])
            self.assertFalse(self.ask("Mal einen Drachen", quick=True)["image"])
            self.call("PUT", "/api/settings", {"ai_image_detect": False})
            self.assertEqual(self.ask("a picture of: snow")["via"], "rules")
            self.call("PUT", "/api/settings", {"ai_image_detect": True, "image_gen": "off"})
            r = self.ask("a picture of: a mountainous landscape covered in snow")
            self.assertEqual((r["image"], r["via"]), (True, "rules"))  # clear rules: the client then explains what is missing
            self.assertFalse(self.ask("Ein Fuchs im Schnee")["image"])


if __name__ == "__main__":
    unittest.main()
