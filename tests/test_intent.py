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

    def call(self, method, path, body=None):
        r = urllib.request.Request(self.base + path, json.dumps(body).encode() if body is not None else None,
                                   {"Content-Type": "application/json", "X-Requested-With": "sunak"}, method=method)
        with urllib.request.urlopen(r, timeout=10) as resp:
            return json.loads(resp.read())

    def ask(self, text):
        return self.call("POST", "/api/imagine/intent", {"text": text, "model": "ollama::tiny:1b"})

    def test_rules_decide_clear_cases_without_the_model(self):
        with mock.patch("sunak.server.providers.chat_once", side_effect=AssertionError("the model must not be asked")):
            r = self.ask("Generiere ein Bild von einem Fuchs")
            self.assertEqual((r["image"], r["via"], r["subject"]), (True, "rules", "einem Fuchs"))
            self.assertFalse(self.ask("Was ist die Hauptstadt von Frankreich?")["image"])

    def test_unclear_cases_ask_the_chat_model_when_pictures_are_set_up(self):
        self.call("PUT", "/api/settings", {"image_gen": "automatic1111", "image_gen_url": "http://127.0.0.1:9"})
        with mock.patch("sunak.server.providers.chat_once", return_value="YES") as m:
            r = self.ask("Mal einen Drachen")
            self.assertEqual((r["image"], r["via"], r["subject"]), (True, "model", "einen Drachen"))
            self.assertIn("Mal einen Drachen", json.dumps(m.call_args.args[2]))
        with mock.patch("sunak.server.providers.chat_once", return_value="NO"):
            self.assertFalse(self.ask("Wie erstelle ich ein Bild in Photoshop?")["image"])
        from sunak import providers
        with mock.patch("sunak.server.providers.chat_once", side_effect=providers.ProviderError("down")):
            self.assertFalse(self.ask("Mal einen Drachen")["image"])  # no answer: a normal chat message

    def test_unclear_cases_are_chat_messages_when_pictures_are_not_set_up(self):
        self.call("PUT", "/api/settings", {"image_gen": "off"})
        with mock.patch("sunak.server.providers.chat_once", side_effect=AssertionError("not asked")):
            self.assertFalse(self.ask("Mal einen Drachen")["image"])


if __name__ == "__main__":
    unittest.main()
