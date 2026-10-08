"""Events and e-mails prepared from the chat (sunak/intent.py `action`, POST /api/assistant/intent and /api/assistant/mail).
Nothing may be saved or sent by these requests.
Run:  python -m unittest discover tests"""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

from sunak import intent, mail
from sunak.server import make_server

EVENT = ["trag mir morgen 10 Uhr Zahnarzt ein", "Trag morgen 10 Uhr Zahnarzt in meinen Kalender ein",
         "Bitte erstelle einen Termin: Zahnarzt morgen um 10", "Kannst du mir einen Termin beim Friseur am Freitag um 15 Uhr eintragen?",
         "Vereinbare einen Termin mit Anna am Montag", "erinner mich morgen an die Steuer", "Remind me to call mom tomorrow at 5pm",
         "Add dentist tomorrow 10am to my calendar", "Schedule a meeting with Tom on Friday at 3pm",
         "Please create an appointment for next Tuesday 10am", "Put the barbecue on Saturday into my calendar",
         "Setz den Zahnarzt auf morgen 10 Uhr in den Kalender", "Create an appointment tomorrow 9am", "Leg einen Termin für Freitag 15 Uhr an",
         "Book a meeting with Sam next Monday", "Remind me in 2 hours to call"]
MAIL = ["schreib Anna eine Mail, dass ich später komme", "Schreibe eine E-Mail an chef@firma.de wegen Urlaub",
        "Write an email to Tom saying I'm late", "Draft a mail to my landlord about the heating",
        "Kannst du eine Mail an Anna verfassen, dass ich krank bin?", "Mail an Anna: ich komme später", "email Anna that I am late",
        "Send Anna an email that the meeting is moved", "Bitte schick Tom eine Mail mit der Absage", "Verfasse eine E-Mail an meinen Vermieter",
        "Schreib meinem Chef eine Mail wegen Urlaub", "Write a short email to Tom"]
NOT = ["Was steht morgen an?", "Welche Termine habe ich?", "Wie erstelle ich einen Termin in Outlook?", "Wie schreibe ich eine Mail an meinen Chef?",
       "Ich habe eine Mail geschrieben", "Ich schreibe gleich eine Mail an Anna", "Ich habe morgen einen Termin beim Zahnarzt",
       "Schreibe ein Python-Skript, das eine Mail sendet", "Can you explain how to schedule a meeting in code?", "Fasse diese Mail zusammen",
       "Erkläre mir den Termin", "Was ist ein Kalender?", "Soll ich einen Termin machen?", "Hast du eine Mail geschrieben?",
       "Why is my calendar empty?", "Trag ein Hemd", "Schreibe mir ein Gedicht", "Mailand ist schön, schreib mir was darüber",
       "Erstelle einen Plan für meine Woche",
       # pictures (the picture check must win)
       "Erstelle ein Bild von einem Meeting", "Mach mir ein Logo für unser Event", "make a picture of a meeting", "create a poster for our event",
       # events
       "Create an event loop in node", "Make me a meeting summary", "Erstelle eine Präsentation über Meetings", "Make a plan for the meeting agenda",
       "Erinnere mich daran, was wir besprochen haben", "Remind me what we discussed", "Trag das bitte ein",
       # mails
       "Schreib mir eine Zusammenfassung dieser Mail", "Schreib mir einen Text über Mails", "Please write an email template for customers",
       "I need to write an email to my landlord, any tips", "Send me the mail list", "Kannst du mir eine Zusammenfassung dieser Mail schreiben?",
       "Schreibe eine E-Mail-Vorlage für Bewerbungen", "Generiere ein Bild von einem Fuchs", "Draw a cat", "", "x" * 700 + " Mail schreiben"]


# review round 2: (text, what it is) one table, positives and negatives side by side
CASES = [
    # worked before 0.15.1 and must keep working
    ("add a dentist appointment tomorrow at 3pm", "event"), ("Leg mir für Montag einen Termin beim Arzt an", "event"),
    ("Send an email to tom@example.com that I'm late", "mail"), ("Schreib eine Mail an meinen Chef mit einem Beispiel für den Bericht", "mail"),
    ("Trag mir den Zahnarzt am 12.10. um 9 ein", "event"), ("Could you write an email to Tom saying I'm late?", "mail"),
    # verb-less event forms
    ("Termin am Freitag um 14 Uhr mit Tom", "event"), ("Termin morgen 10 Uhr Zahnarzt", "event"), ("Neuer Termin: Freitag 14 Uhr Friseur", "event"),
    ("Meeting with Tom on Friday at 2pm", "event"), ("Zahnarzt morgen um 10 eintragen", "event"),
    # not requests
    ("Remind me tomorrow what a monad is", ""), ("Remind me again how the event loop works today", ""),
    ("Erinnere mich daran, dass ich morgen nett zu Anna sein soll, was meinst du dazu", ""), ("Erstelle einen Event-Plan für Samstag", ""),
    ("Create a meeting invite text for Friday", ""), ("Write an email signature for me", ""),
    ("Write a newsletter mail for customers next Monday", ""), ("Termin verschoben, war gestern", ""),
    ("Meeting notes from Friday at 2pm", ""), ("Erstelle einen Terminplan für Samstag", ""), ("Make me a meeting summary for Friday at 2pm", ""),
]


class ActionTest(unittest.TestCase):
    def test_table(self):
        for text, want in CASES:
            self.assertEqual(intent.action(text), want, text)

    def test_events(self):
        for t in EVENT:
            self.assertEqual(intent.action(t), "event", t)

    def test_mails(self):
        for t in MAIL:
            self.assertEqual(intent.action(t), "mail", t)

    def test_questions_reports_and_technical_talk_are_normal_chats(self):
        for t in NOT:
            self.assertEqual(intent.action(t), "", t)

    def test_picture_requests_stay_pictures(self):
        for t in ("Generiere ein Bild von einem Fuchs", "mal mir eine Katze", "Foto von einem Strand bei Nacht"):
            self.assertEqual(intent.action(t), "", t)
            self.assertEqual(intent.classify(t), "yes", t)

    def test_addresses(self):
        self.assertEqual(intent.addresses("Mail an a.b@x.de und c@y.org, nochmal a.b@x.de"), ["a.b@x.de", "c@y.org"])
        self.assertEqual(intent.addresses("keine Adresse @ hier"), [])


class AbilitiesTest(unittest.TestCase):
    def test_the_model_is_told_what_sunak_can_do(self):
        import datetime
        note = intent.abilities(datetime.datetime(2026, 10, 8, 12, 30, tzinfo=datetime.timezone(datetime.timedelta(hours=2))))
        for want in ("sunak-event", "sunak-mail", "Never say that you cannot add calendar entries", "Thursday, 2026-10-08 12:30 (UTC+02:00)"):
            self.assertIn(want, note)

    def test_it_is_part_of_every_chat_prompt(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            srv = make_server("127.0.0.1", 0, tmp)
            try:
                system = srv.RequestHandlerClass.app.build_messages({}, [{"role": "user", "content": "trag mir einen Termin ein"}])[0]["content"]
                self.assertIn("```sunak-event", system)
                self.assertIn("```sunak-mail", system)
            finally:
                srv.server_close()


class DraftTest(unittest.TestCase):
    def test_draft_from_the_model_answer(self):
        a = 'Here: {"to": "anna@example.com", "to_name": "Anna", "subject": "Später", "body": "Hi Anna,\\nich komme später.\\nMax"}'
        self.assertEqual(mail.parse_draft(a), {"to": "anna@example.com", "to_name": "Anna", "subject": "Später", "body": "Hi Anna,\nich komme später.\nMax"})
        self.assertEqual(mail.parse_draft(a, ["real@example.com"])["to"], "real@example.com")  # an address from the request wins
        self.assertEqual(mail.parse_draft('{"to": "Anna", "subject": "x", "body": "y"}')["to"], "")  # a name is no address
        for bad in ("", "no json", '{"subject": "x"}', '{"body": "  "}', '{"body": 5}'):
            with self.assertRaises(mail.MailError):
                mail.parse_draft(bad)

    def test_prompt_names_the_account(self):
        msgs = mail.draft_messages("schreib Anna", {"name": "Max Muster", "email": "max@example.com"}, ["Max wohnt in Köln"])
        self.assertIn("Max Muster <max@example.com>", msgs[0]["content"])
        self.assertIn("Max wohnt in Köln", msgs[0]["content"])
        self.assertEqual(msgs[1], {"role": "user", "content": "schreib Anna"})


class EndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.srv = make_server("127.0.0.1", 0, cls.tmp.name)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        cls.app = cls.srv.RequestHandlerClass.app

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def setUp(self):
        self.app.db.set_setting("mail_accounts", [])

    def call(self, path, body):
        r = urllib.request.Request(self.base + path, json.dumps(body).encode(), {"Content-Type": "application/json", "X-Requested-With": "sunak"}, method="POST")
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def events(self):
        r = urllib.request.Request(self.base + "/api/calendar/events?start=2026-10-01T00:00:00Z&end=2026-11-01T00:00:00Z", headers={"X-Requested-With": "sunak"})
        with urllib.request.urlopen(r, timeout=10) as resp:
            return json.loads(resp.read())["events"]

    def test_intent_endpoint_uses_no_model(self):
        with mock.patch("sunak.server.providers.chat_stream", side_effect=AssertionError("no model")), \
                mock.patch("sunak.server.providers.chat_once", side_effect=AssertionError("no model")):
            for text, want in (("trag mir morgen 10 Uhr Zahnarzt ein", "event"), ("schreib Anna eine Mail, dass ich später komme", "mail"),
                               ("Was steht morgen an?", ""), ("Hallo", "")):
                self.assertEqual(self.call("/api/assistant/intent", {"text": text}), (200, {"action": want}), text)
        self.assertEqual(self.call("/api/assistant/intent", {"text": 5})[0], 400)

    def test_mail_draft_needs_an_account_and_sends_nothing(self):
        status, r = self.call("/api/assistant/mail", {"text": "schreib Anna eine Mail", "model": "ollama::tiny:1b"})
        self.assertEqual((status, r["error"]), (400, "Add a mail account first"))  # a hint, not a crash
        self.app.db.set_setting("mail_accounts", [{"id": "a1", "name": "Max Muster", "email": "max@example.com", "password": "pw"}])
        seen = []

        def fake(prov, model, messages, options=None):
            seen.append(messages)
            return '{"to": "", "to_name": "Anna", "subject": "Später", "body": "Hi Anna, ich komme später. Max"}'
        with mock.patch("sunak.server.providers.chat_once", fake), mock.patch("sunak.mail.smtplib.SMTP", side_effect=AssertionError("sent")), \
                mock.patch("sunak.mail.smtplib.SMTP_SSL", side_effect=AssertionError("sent")):
            status, r = self.call("/api/assistant/mail", {"text": "schreib Anna an anna@example.com, dass ich später komme", "model": "ollama::tiny:1b"})
        self.assertEqual(status, 200)
        self.assertEqual((r["to"], r["to_name"], r["subject"], r["account"]), ("anna@example.com", "Anna", "Später", "a1"))
        self.assertIn("Max Muster <max@example.com>", seen[0][0]["content"])
        for bad in ({"text": " "}, {"text": "x", "account": "nope"}):
            self.assertEqual(self.call("/api/assistant/mail", bad)[0], 400)
        with mock.patch("sunak.server.providers.chat_once", return_value="sorry, no"):
            self.assertEqual(self.call("/api/assistant/mail", {"text": "schreib Anna", "model": "ollama::tiny:1b"})[0], 400)

    def test_the_block_of_the_chat_model_is_checked_like_any_answer(self):
        now = "2026-10-08T09:00:00+02:00"
        status, r = self.call("/api/assistant/check", {"kind": "event", "now": now,
                                                      "json": '{"summary": "Zahnarzt", "start": "2026-10-09T10:00", "end": null}'})
        self.assertEqual((status, r["summary"], r["start"], r["end"], r["all_day"]), (200, "Zahnarzt", "2026-10-09T10:00", "2026-10-09T11:00", False))
        self.assertEqual(self.call("/api/assistant/check", {"kind": "event", "now": now, "json": "<script>alert(1)</script>"})[0], 400)
        self.assertEqual(self.call("/api/assistant/check", {"kind": "event", "now": "x", "json": "{}"})[0], 400)
        self.assertEqual(self.call("/api/assistant/check", {"kind": "other", "json": "{}"})[0], 400)
        block = '{"to": "anna@example.com", "subject": "Später", "body": "Hi Anna"}'
        status, r = self.call("/api/assistant/check", {"kind": "mail", "json": block})
        self.assertEqual((status, r["error"]), (400, "Add a mail account first"))
        self.app.db.set_setting("mail_accounts", [{"id": "a1", "name": "Max", "email": "max@example.com", "password": "pw"}])
        status, r = self.call("/api/assistant/check", {"kind": "mail", "json": block})
        self.assertEqual((status, r["to"], r["subject"], r["account"]), (200, "anna@example.com", "Später", "a1"))
        self.assertEqual(self.call("/api/assistant/check", {"kind": "mail", "json": '{"to": "x"}'})[0], 400)

    def test_event_parse_saves_nothing(self):
        before = len(self.events())
        answer = '{"summary": "Zahnarzt", "start": "2026-10-09T10:00", "end": null, "location": "", "description": ""}'
        with mock.patch("sunak.server.providers.chat_once", return_value=answer):
            status, r = self.call("/api/calendar/parse", {"text": "trag mir morgen 10 Uhr Zahnarzt ein", "now": "2026-10-08T09:00:00+02:00", "model": "ollama::tiny:1b"})
        self.assertEqual((status, r["summary"], r["start"], r["end"]), (200, "Zahnarzt", "2026-10-09T10:00", "2026-10-09T11:00"))
        self.assertEqual(len(self.events()), before)  # only the Save click stores it
        status, _ = self.call("/api/calendar/events", {"source": "local", "event": {"summary": "Zahnarzt", "all_day": False, "start": "2026-10-09T08:00:00.000Z",
                                                                                  "end": "2026-10-09T09:00:00.000Z", "location": "", "description": "", "repeat": ""}})
        self.assertEqual(status, 200)
        self.assertEqual(len(self.events()), before + 1)


if __name__ == "__main__":
    unittest.main()
