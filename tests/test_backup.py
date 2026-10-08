"""Importing a backup or an exported chat: round trip, no duplicates, damaged files, admin rights, `sunak import`."""

import base64
import contextlib
import io
import json
import os
import tempfile
import threading
import unittest
import unittest.mock
import urllib.error
import urllib.request

from sunak import __main__ as cli
from sunak import backup
from sunak.server import make_server

ICS = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:{uid}\r\nDTSTAMP:20261001T000000Z\r\n"
       "DTSTART:20261010T100000Z\r\nDTEND:20261010T110000Z\r\nSUMMARY:Dentist\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
MAIL = {"id": "m1abc", "email": "max@example.com", "name": "Max", "username": "max@example.com", "imap_host": "imap.example.com",
        "imap_port": 993, "imap_security": "ssl", "smtp_host": "smtp.example.com", "smtp_port": 465, "smtp_security": "ssl",
        "save_sent": True, "password": "geheim"}


class Instance:
    """A running Sunak with its own data folder."""
    def __init__(self, root, name):
        self.data = os.path.join(root, name)
        self.srv = make_server("127.0.0.1", 0, self.data)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.app = self.srv.RequestHandlerClass.app
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()
        for p in self.app.profiles():
            self.app.close_profile(p["id"])
        self.app.main.close()

    def select(self, pid):
        r = urllib.request.Request(self.base + "/api/profiles/select", json.dumps({"id": pid}).encode(),
                                   {"Content-Type": "application/json", "X-Requested-With": "sunak"}, method="POST")
        return urllib.request.urlopen(r).headers["Set-Cookie"].split(";")[0]

    def req(self, method, path, body=None, cookie=None, raw=False):
        h = {"Content-Type": "application/json", "X-Requested-With": "sunak"}
        if cookie:
            h["Cookie"] = cookie
        r = urllib.request.Request(self.base + path, json.dumps(body).encode() if body is not None else None, h, method=method)
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.read() if raw else json.loads(resp.read() or b"null")

    def error(self, *args, **kw):
        try:
            self.req(*args, **kw)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())["error"]
        raise AssertionError("the request should have failed")


class BackupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.made = []

    def tearDown(self):
        for i in self.made:
            i.close()

    def new(self, name):
        inst = Instance(self.tmp.name, f"{self._testMethodName}-{name}")
        self.made.append(inst)
        return inst

    def fill(self, inst):
        """Everything a backup holds, in one Sunak."""
        s = inst.req("POST", "/api/sessions", {})
        inst.app.db.update_session(s["id"], title="Trip plans", system="Be brief", persona="p1", use_kb=True)
        inst.app.db.add_message(s["id"], "user", "Where to?")
        inst.app.db.add_message(s["id"], "assistant", "<think>hm</think>Rome.", "ollama::tiny:1b", {"sources": ["a.md"], "images": ["x.png"]})
        doc = inst.req("POST", "/api/documents", {"title": "Plan", "content": "# Plan\nBuy tickets"})
        note = inst.req("POST", "/api/notes", {"content": "I like horses", "is_memory": True})
        inst.req("POST", "/api/knowledge", {"name": "atlantis.md", "data": base64.b64encode("Poseidonia is the capital.".encode()).decode()})
        inst.req("POST", "/api/calendar/events", {"event": {"summary": "Sport", "start": "2026-10-05T16:00:00Z", "end": "2026-10-05T17:00:00Z"}})
        inst.req("PUT", "/api/settings", {
            "theme": "ocean", "temperature": 1.2, "ntfy_topic": "secret-topic", "check_updates": False,
            "personas": [{"id": "p1", "icon": "🦉", "name": "Owl", "prompt": "Hoot."}],
            "providers": [{"id": "cloud", "name": "Cloud", "type": "openai", "base_url": "https://api.example.com/v1", "api_key": "sk-123"}]})
        inst.app.db.set_setting("mail_accounts", [dict(MAIL)])
        inst.app.db.set_setting("calendars", [
            {"id": "c1", "type": "caldav", "name": "Work", "url": "https://dav.example.com/", "username": "max@example.com", "color": "#3b82f6",
             "enabled": True, "mail_account": "m1abc", "password": "", "calendars": [{"href": "/cal/work/", "name": "Work", "color": "", "enabled": True}]},
            {"id": "c2", "type": "ics", "name": "Holidays", "url": "https://example.com/holidays.ics", "color": "#10b981", "enabled": True}])
        return s, doc, note

    def snapshot(self, inst):
        """What a user sees, without ids that are allowed to differ and without secrets."""
        db = inst.app.db
        sessions = [(s["title"], s["system"], s["persona"], s["use_kb"], [(m["role"], m["content"], m["model"], m["meta"]) for m in s["messages"]])
                    for s in (db.get_session(x["id"]) for x in db.list_sessions())]
        settings = inst.req("GET", "/api/settings")
        return {"sessions": sessions, "documents": sorted((d["title"], db.get_document(d["id"])["content"]) for d in db.list_documents()),
                "notes": sorted((n["content"], n["is_memory"]) for n in db.list_notes()),
                "knowledge": sorted((f["name"], db.kb_file(f["id"])["text"]) for f in db.kb_files()),
                "events": sorted(r["uid"] for r in db.cal_events()),
                "prefs": {k: settings[k] for k in ("theme", "temperature", "check_updates")},
                "personas": [(p["id"], p["name"], p["prompt"]) for p in settings["personas"] if p["id"] == "p1"],
                "providers": sorted((p["id"], p["type"], p["base_url"]) for p in settings["providers"] if p["id"] == "cloud"),
                "mail": [(a["id"], a["email"], a["imap_host"], a["smtp_port"]) for a in inst.app.mail_accounts()],
                "calendars": sorted((c["type"], c["name"], c["url"], c.get("mail_account"), len(c.get("calendars", []))) for c in inst.app.calendars())}

    def test_round_trip_into_an_empty_profile(self):
        a, b = self.new("a"), self.new("b")
        self.fill(a)
        exported = json.loads(a.req("GET", "/api/export", raw=True))
        r = b.req("POST", "/api/import", exported)
        self.assertEqual(r["kind"], "backup")
        # settings count only what differs from this Sunak's own (theme, temperature, check_updates and what saving them changed)
        self.assertEqual({**r["added"], "settings": 0}, {"chats": 1, "documents": 1, "notes": 1, "knowledge": 1, "events": 1,
                         "mail_accounts": 1, "calendars": 2, "personas": 1, "providers": 1, "settings": 0})
        self.assertGreaterEqual(r["added"]["settings"], 3)
        self.assertEqual(r["invalid"], 0)
        want, got = self.snapshot(a), self.snapshot(b)
        # a picture reference cannot come along: the files are not in a backup
        want["sessions"][0][4][1][3].pop("images")
        self.assertEqual(got, want)
        # secrets stay out and are listed
        self.assertEqual(b.app.mail_accounts()[0]["password"], "")
        self.assertEqual(b.app.settings()["ntfy_topic"], "")
        self.assertEqual([p for p in b.app.settings()["providers"] if p["id"] == "cloud"][0]["api_key"], "")
        self.assertEqual({(x["kind"], x["name"]) for x in r["secrets"]}, {("mail", "max@example.com"), ("provider", "Cloud")})
        self.assertIn("Some messages had pictures. Pictures are not part of a backup, so they are missing.", r["notes"])
        self.assertEqual(a.app.mail_accounts()[0]["password"], "geheim")  # the source is untouched

    def test_importing_twice_adds_nothing(self):
        a, b = self.new("a"), self.new("b")
        self.fill(a)
        exported = json.loads(a.req("GET", "/api/export", raw=True))
        b.req("POST", "/api/import", exported)
        before = self.snapshot(b)
        r = b.req("POST", "/api/import", exported)
        self.assertEqual(sum(r["added"].values()), 0, r["added"])
        self.assertEqual(r["secrets"], [])
        self.assertEqual(r["skipped"]["chats"], 1)
        self.assertEqual(r["skipped"]["calendars"], 2)
        self.assertEqual(self.snapshot(b), before)
        # into the Sunak it came from: everything is there already
        r = a.req("POST", "/api/import", exported)
        self.assertEqual(sum(r["added"].values()), 0, r["added"])
        self.assertEqual(len(a.app.db.list_sessions()), 1)

    def test_nothing_is_overwritten(self):
        a, b = self.new("a"), self.new("b")
        s, doc, _ = self.fill(a)
        exported = json.loads(a.req("GET", "/api/export", raw=True))
        b.req("PUT", "/api/settings", {"theme": "forest"})
        b.app.db.restore_document({"id": doc["id"], "title": "My own title", "content": "changed", "updated": 1.0})  # same id, other content
        b.app.db.set_setting("mail_accounts", [dict(MAIL, id="other", password="mine", imap_host="imap.other.com")])
        r = b.req("POST", "/api/import", exported)
        self.assertEqual(b.req("GET", "/api/settings")["theme"], "forest")
        self.assertEqual(b.app.db.get_document(doc["id"])["content"], "changed")
        self.assertEqual(r["skipped"]["documents"], 1)
        self.assertEqual(b.app.mail_accounts(), [dict(MAIL, id="other", password="mine", imap_host="imap.other.com")])
        self.assertEqual(r["added"]["mail_accounts"], 0)
        # the CalDAV account follows the mail account that is there already
        work = [c for c in b.app.calendars() if c["name"] == "Work"][0]
        self.assertEqual(work["mail_account"], "other")

    def test_single_chat_export(self):
        a, b = self.new("a"), self.new("b")
        s, _, _ = self.fill(a)
        chat = json.loads(a.req("GET", f"/api/sessions/{s['id']}/export?format=json", raw=True))
        r = b.req("POST", "/api/import", chat)
        self.assertEqual((r["kind"], r["added"]["chats"], sum(r["added"].values())), ("chat", 1, 1))
        got = b.app.db.get_session(s["id"])
        self.assertEqual([m["content"] for m in got["messages"]], ["Where to?", "<think>hm</think>Rome."])
        self.assertEqual((got["title"], got["system"], got["use_kb"]), ("Trip plans", "Be brief", True))
        self.assertEqual(b.req("POST", "/api/import", chat)["skipped"]["chats"], 1)
        self.assertEqual(len(b.app.db.list_sessions()), 1)

    def test_damaged_files_are_refused_and_damaged_items_skipped(self):
        b = self.new("b")
        for body in ({}, {"hello": 1}, {"sessions": "x"}, {"settings": []}, {"notes": {}}, {"title": "x"}):
            code, msg = b.error("POST", "/api/import", body)
            self.assertEqual(code, 400, body)
        self.assertIn("neither a Sunak backup", b.error("POST", "/api/import", {"hello": 1})[1])
        self.assertIn("'sessions' must be a list", b.error("POST", "/api/import", {"sessions": "x"})[1])
        req = urllib.request.Request(b.base + "/api/import", b"{not json", {"Content-Type": "application/json", "X-Requested-With": "sunak"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        self.assertEqual(e.exception.code, 400)
        req = urllib.request.Request(b.base + "/api/import", b"[1, 2]", {"Content-Type": "application/json", "X-Requested-With": "sunak"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        self.assertEqual(e.exception.code, 400)
        self.assertEqual(b.app.db.list_sessions(), [])
        mixed = {"sunak_version": "99.0.0", "sessions": [
            {"id": "ok1", "title": "Fine", "messages": [{"role": "user", "content": "hi"}]},
            {"id": "bad1", "title": "No role", "messages": [{"role": "robot", "content": "hi"}]},
            "text", 5, {"title": "Bad messages", "messages": "x"},
            {"id": "../../etc", "title": "Odd id", "created": "yesterday", "messages": []}],
            "documents": [{"title": "Fine", "content": "x"}, {"title": "Bad", "content": 5}, None],
            "notes": [{"content": "ok"}, {"content": ""}, {"content": 5}],
            "knowledge": [{"name": "a.txt", "text": "some text"}, {"name": "", "text": "x"}, {"name": "b.txt", "text": ""}, {"name": "c.txt"}],
            "calendar": [{"uid": "u1", "ics": ICS.format(uid="u1")}, {"uid": "u2", "ics": "not a calendar"}, {"uid": "", "ics": ICS}],
            "mail_accounts": [{"email": "nonsense"}, {"email": "a@example.com", "imap_host": "bad host!"}],
            "calendars": [{"type": "ftp", "url": "x"}, {"type": "ics", "url": "not a url"}],
            "settings": {"theme": "no-such-theme", "temperature": 99, "unknown_key": 1, "language": "de", "personas": [{"name": ""}, 5]}}
        r = b.req("POST", "/api/import", mixed)
        self.assertEqual(r["added"]["chats"], 2)  # "Odd id" gets a new id
        self.assertEqual({s["title"] for s in b.app.db.list_sessions()}, {"Fine", "Odd id"})
        self.assertNotIn("../../etc", [s["id"] for s in b.app.db.list_sessions()])
        self.assertEqual((r["added"]["documents"], r["added"]["notes"], r["added"]["knowledge"], r["added"]["events"]), (1, 1, 1, 1))
        self.assertEqual((r["added"]["mail_accounts"], r["added"]["calendars"], r["added"]["settings"], r["added"]["personas"]), (0, 0, 1, 0))
        self.assertEqual(r["invalid"], 4 + 2 + 3 + 3 + 2 + 2 + 2 + 3)
        self.assertIn("newer Sunak", " ".join(r["notes"]))
        self.assertEqual(b.req("GET", "/api/settings")["language"], "de")
        self.assertEqual(b.req("GET", "/api/settings")["theme"], "dark")

    def test_profiles_and_admin_rights(self):
        a, b = self.new("a"), self.new("b")
        self.fill(a)
        exported = json.loads(a.req("GET", "/api/export", raw=True))
        exported["settings"]["ntfy_url"] = "http://ntfy.example.com"
        exported["settings"]["image_gen"] = "local"
        kid = b.req("POST", "/api/profiles", {"name": "Kid"}, cookie=b.select("default"))
        # a kid profile: own data and own preferences come in, the installation is left alone
        cookie = b.select(kid["id"])
        r = b.req("POST", "/api/import", exported, cookie=cookie)
        self.assertEqual((r["added"]["chats"], r["added"]["providers"]), (1, 0))
        self.assertIn("only an admin profile can import them", " ".join(r["notes"]))
        self.assertEqual(b.req("GET", "/api/settings", cookie=cookie)["theme"], "ocean")
        self.assertEqual(b.req("GET", "/api/settings", cookie=cookie)["ntfy_url"], "")
        self.assertEqual(b.req("GET", "/api/settings", cookie=cookie)["image_gen"], "off")
        self.assertEqual([p["id"] for p in b.app.settings()["providers"]], ["ollama"])
        self.assertEqual(b.app.db.list_sessions(), [])  # the main profile got nothing
        self.assertEqual(b.app.settings()["theme"], "dark")
        self.assertEqual(len(b.app.view(kid["id"]).db.list_sessions()), 1)
        # the main profile is an admin: installation settings and providers come in
        main = b.select("default")
        r = b.req("POST", "/api/import", exported, cookie=main)
        self.assertEqual(r["added"]["providers"], 1)
        self.assertEqual(b.req("GET", "/api/settings", cookie=main)["ntfy_url"], "http://ntfy.example.com")
        self.assertEqual(len(b.app.view(kid["id"]).db.list_sessions()), 1)  # the kid's data stays where it is

    def test_command_line(self):
        a, b = self.new("a"), self.new("b")
        self.fill(a)
        path = os.path.join(self.tmp.name, "cli-backup.json")
        with open(path, "wb") as f:
            f.write(a.req("GET", "/api/export", raw=True))
        b.close()
        self.made.remove(b)

        def run(*argv):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(list(argv))
            return code, out.getvalue(), err.getvalue()
        code, out, err = run("import", path, "--data-dir", b.data)
        self.assertEqual((code, err), (0, ""), err)
        self.assertIn("Added: 1 chat, 1 document, 1 note, 1 knowledge-base file, 1 calendar event, 1 mail account, 2 calendar accounts", out)
        self.assertIn("provider Cloud: API key", out)
        self.assertIn("mail account max@example.com: password", out)
        code, out, _ = run("import", path, "--data-dir", b.data)
        self.assertIn("Added: nothing", out)
        self.assertIn("Skipped, already there: 1 chat", out)
        self.assertEqual(run("import", "--data-dir", b.data)[0], 2)
        self.assertEqual(run("import", path, "--bogus")[0], 2)
        self.assertEqual(run("import", path, "--profile", "nobody", "--data-dir", b.data)[0], 1)
        self.assertIn("no profile 'nobody'", run("import", path, "--profile", "nobody", "--data-dir", b.data)[2])
        self.assertIn("no Sunak data", run("import", path, "--data-dir", os.path.join(self.tmp.name, "nowhere"))[2])
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "nowhere")))
        self.assertIn("Cannot read", run("import", os.path.join(self.tmp.name, "missing.json"), "--data-dir", b.data)[2])
        bad = os.path.join(self.tmp.name, "bad.json")
        with open(bad, "w") as f:
            f.write("{oops")
        self.assertIn("not valid JSON", run("import", bad, "--data-dir", b.data)[2])
        with open(bad, "w") as f:
            f.write('{"hello": 1}')
        self.assertEqual(run("import", bad, "--data-dir", b.data)[0], 1)
        # what the command wrote is there when Sunak starts again
        again = Instance(self.tmp.name, f"{self._testMethodName}-b")
        self.made.append(again)
        self.assertEqual([s["title"] for s in again.app.db.list_sessions()], ["Trip plans"])

    def test_file_reader_limits(self):
        p = os.path.join(self.tmp.name, "big.json")
        with open(p, "wb") as f:
            f.write(b" " * 100)
        with unittest.mock.patch.object(backup, "MAX_BYTES", 50):
            with self.assertRaises(ValueError) as e:
                backup.read_file(p)
        self.assertIn("bigger than", str(e.exception))
        with open(p, "wb") as f:
            f.write(b"[" * 100000)
        with self.assertRaises(ValueError):
            backup.read_file(p)
        with open(p, "wb") as f:
            f.write(b"\xff\xfe\x00")
        with self.assertRaises(ValueError):
            backup.read_file(p)
        with open(p, "wb") as f:
            f.write(b"\xef\xbb\xbf{\"notes\": []}")  # a file saved with a BOM
        self.assertEqual(backup.read_file(p), {"notes": []})


if __name__ == "__main__":
    unittest.main()
