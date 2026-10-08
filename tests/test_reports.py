"""Error reports (sunak/reports.py): what a report contains and never contains, the modes, GitHub issues
(against a fake GitHub), duplicates, the rate limit and the token.
Run:  python -m unittest discover tests"""

import json
import logging
import re
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from sunak import log, reports
from sunak.server import make_server
from test_server import serve

TOKEN = "github_pat_11AAAAAAA0abcdefghijklmnopqrstuvwxyz0123456789"


class FakeGitHub(BaseHTTPRequestHandler):
    """Just enough of the GitHub issues API: list, create, comment. Needs `Bearer TOKEN`."""
    issues = []
    comments = []

    def log_message(self, *a):
        pass

    def reply(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        return self.headers.get("Authorization") == f"Bearer {TOKEN}"

    def do_GET(self):
        if not self.authorized():
            return self.reply(401, {"message": "Bad credentials"})
        if not self.path.startswith("/repos/test/repo/issues"):
            return self.reply(404, {})
        page = int(re.search(r"[?&]page=(\d+)", self.path).group(1)) if re.search(r"[?&]page=", self.path) else 1
        self.reply(200, type(self).issues[(page - 1) * 100: page * 100])

    def do_POST(self):
        if not self.authorized():
            return self.reply(401, {"message": "Bad credentials"})
        data = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        m = re.fullmatch(r"/repos/test/repo/issues/(\d+)/comments", self.path)
        if m:
            type(self).comments.append((int(m.group(1)), data["body"]))
            return self.reply(201, {})
        if self.path == "/repos/test/repo/issues":
            issue = dict(data, number=len(type(self).issues) + 1, state="open")
            type(self).issues.insert(0, issue)
            return self.reply(201, issue)
        self.reply(404, {})


def boom(kind, message="it broke"):
    """An exception that went through Sunak code (reports.clean_token), caught like the server does."""
    try:
        reports.clean_token(5)
    except ValueError:
        try:
            raise type(kind, (Exception,), {})(message)
        except Exception:  # noqa: BLE001
            import sys
            return sys.exc_info()


def logged_error(kind="Boom", message="it broke"):
    """Log an error with a traceback the way the server does (log_app.error(..., exc_info=True))."""
    try:
        raise type(kind, (Exception,), {})(message)
    except Exception:  # noqa: BLE001
        log.get("app").error("Unexpected error while answering", exc_info=True)


class AnonymizeTest(unittest.TestCase):
    def test_private_things_are_masked(self):
        for text, hidden in (("/home/maria/projects/x.py", "maria"), ("/Users/Maria Schmidt/Library", "Maria"),
                             (r"C:\Users\maria\AppData\x", "maria"), ("see https://bob:hunter22@example.org/x", "hunter22"),
                             ("mail to maria@example.org failed", "maria@example.org"), ("server at 192.168.1.23 down", "192.168.1.23"),
                             ("Authorization: Bearer abcdefgh12345678", "abcdefgh12345678"), ("token=" + TOKEN, TOKEN)):
            self.assertNotIn(hidden, reports.anonymize(text), text)
        self.assertIn("127.0.0.1", reports.anonymize("http://127.0.0.1:8000"))
        self.assertEqual(reports.anonymize("/home/maria/x.py"), "<path>")
        self.assertEqual(reports.anonymize("GET /api/sessions/abc 200 0.1s"), "GET /api/sessions/abc 200 0.1s")  # not a private path

    def test_the_issues_are_public_so_masking_is_strict(self):
        for text, hidden in (("not found: /home/maria/Documents/Steuer 2025.pdf", "Steuer"), ("open C:\\Users\\Maria\\mein geheimes.txt", "geheimes"),
                             ("connect to http://nas.local:11434/api failed", "nas"), ("see http://meinserver.example.org/x", "meinserver"),
                             ("KeyError: 'Das ist ein langer privater Satz aus einem Chat darüber'", "Chat darüber"),
                             ("device aa:bb:cc:dd:ee:ff", "aa:bb"), ("addr fe80::1:2:3:4", "fe80"), ("Log: /tmp/x/sunak.log", "sunak.log")):
            self.assertNotIn(hidden, reports.anonymize(text), text)
        self.assertIn("https://api.github.com/x", reports.anonymize("https://api.github.com/x"))
        self.assertIn("http://127.0.0.1:7000", reports.anonymize("http://127.0.0.1:7000"))

    def test_own_home_and_host_name_are_masked(self):
        text = f"file {Path.home() / 'secret-folder' / 'a.txt'}"
        self.assertNotIn(str(Path.home()) if str(Path.home()) not in ("/", "/root") else "@@", reports.anonymize(text))


class BuildTest(unittest.TestCase):
    def test_report_has_the_facts_and_no_values(self):
        def secret_holder():
            password = "correct-horse-battery"  # noqa: F841 - a local variable must never show up
            raise KeyError("missing")
        try:
            secret_holder()
        except KeyError:
            import sys
            info = sys.exc_info()
        r = reports.build(info, lines=["12:00:00 INFO    http     GET /api/status 200 0.0s"])
        self.assertIn("KeyError", r["title"])
        self.assertIn(r["fp"], r["title"])
        self.assertIn("public", r["body"])
        for text in ("Sunak", "Python", "Stack trace", "GET /api/status", f"sunak-fingerprint: {r['fp']}"):
            self.assertIn(text, r["body"])
        self.assertNotIn("correct-horse-battery", r["body"])

    def test_fingerprint_ignores_the_message_but_not_the_kind(self):
        a, b, c = boom("Alpha", "one"), boom("Alpha", "two"), boom("Beta", "one")
        fp = lambda i: reports.fingerprint(i, reports.describe(i)[2])  # noqa: E731
        self.assertEqual(fp(a), fp(b))
        self.assertNotEqual(fp(a), fp(c))

    def test_secrets_in_the_message_are_masked(self):
        r = reports.build(boom("Oops", "failed with password=hunter22 for /home/maria/x and 10.0.0.5"), lines=[])
        for hidden in ("hunter22", "maria", "10.0.0.5"):
            self.assertNotIn(hidden, r["body"])

    def test_cutting_the_message_cannot_uncover_an_address_or_a_quote(self):
        # the message is cut to MAX_MESSAGE characters; the cut must not split an address or a quote so it is no longer masked
        pad = "x" * (reports.MAX_MESSAGE - 12)
        error = reports.describe(boom("Oops", pad + " john.doe@example.com"))[0]
        self.assertNotIn("john.doe@", error)
        quoted = reports.describe(boom("Oops", "see 'my secret diary entry about my private life' ok" + pad))[0]
        self.assertNotIn("diary", quoted)
        long_quote = reports.describe(boom("Oops", "a" * (reports.MAX_MESSAGE - 20) + " 'my secret diary entry that goes on and on and on'"))[0]
        self.assertNotIn("diary", long_quote)

    def test_user_and_password_do_not_hide_the_real_host(self):
        out = reports.anonymize("failed: http://bob:pw123@intranet.corp.example/x")
        for hidden in ("bob", "pw123", "intranet.corp"):
            self.assertNotIn(hidden, out)

    def test_prefilled_issue_address_stays_short(self):
        r = reports.build(boom("Big", "x" * 250), lines=["12:00:00 INFO app " + "y" * 280] * 30)
        self.assertLess(len(reports.issue_url(r)), reports.URL_LIMIT + 200)
        self.assertIn("issues/new?", reports.issue_url(r))


class ReportsTest(unittest.TestCase):
    def setUp(self):
        FakeGitHub.issues, FakeGitHub.comments = [], []
        self.github = serve(ThreadingHTTPServer(("127.0.0.1", 0), FakeGitHub))
        self.old = reports.API, reports.REPO
        reports.API, reports.REPO = f"http://127.0.0.1:{self.github.server_address[1]}", "test/repo"
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.srv = serve(make_server("127.0.0.1", 0, self.tmp.name))
        self.port = self.srv.server_address[1]
        self.app = self.srv.RequestHandlerClass.app

    def tearDown(self):
        reports.API, reports.REPO = self.old
        for s in (self.srv, self.github):
            s.shutdown()
            s.server_close()
        self.tmp.cleanup()

    def call(self, method, path, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body).encode() if body is not None else None,
                                     method=method, headers={"Content-Type": "application/json", "X-Requested-With": "sunak"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return {"status": e.code, **json.loads(e.read().decode() or "{}")}

    def mode(self, mode, token=True):
        self.call("PUT", "/api/settings", {"error_reports": mode})
        if token:
            self.call("POST", "/api/reports/token", {"token": TOKEN})

    def wait(self, check, seconds=5):
        end = time.time() + seconds
        while time.time() < end:
            if check():
                return True
            time.sleep(0.05)
        return check()

    def test_off_by_default_collects_nothing(self):
        self.assertEqual(self.call("GET", "/api/reports")["mode"], "off")
        logged_error()
        self.assertEqual(self.call("GET", "/api/reports")["pending"], [])
        self.assertFalse((Path(self.tmp.name) / reports.STATE_FILE).exists())

    def test_ask_mode_keeps_errors_until_the_user_decides(self):
        self.mode("ask", token=False)
        logged_error("Alpha")
        logged_error("Alpha", "again")
        logged_error("Beta")
        pending = self.call("GET", "/api/reports")["pending"]
        self.assertEqual(sorted(p["count"] for p in pending), [1, 2])
        self.assertEqual(FakeGitHub.issues, [])  # nothing is sent without the user
        self.assertTrue(all(p["url"].startswith("https://github.com/test/repo/issues/new?") for p in pending))
        self.assertEqual(self.call("GET", "/api/settings")["reports_pending"], 2)
        self.call("POST", "/api/reports/dismiss", {"id": pending[0]["fp"]})
        self.assertEqual(len(self.call("GET", "/api/reports")["pending"]), 1)

    def test_sending_needs_a_token_and_creates_an_issue(self):
        self.mode("ask", token=False)
        logged_error("Gamma")
        fp = self.call("GET", "/api/reports")["pending"][0]["fp"]
        self.assertIn("No GitHub token", self.call("POST", "/api/reports/send", {"id": fp})["error"])
        self.call("POST", "/api/reports/token", {"token": TOKEN})
        r = self.call("POST", "/api/reports/send", {"id": fp})
        self.assertEqual((r["action"], r["number"]), ("created", 1))
        issue = FakeGitHub.issues[0]
        self.assertIn(fp, issue["title"])
        self.assertEqual(issue["labels"], ["auto-report"])
        state = self.call("GET", "/api/reports")
        self.assertEqual((state["pending"], len(state["sent"])), ([], 1))
        logged_error("Gamma")  # the same error again: counted, no second issue
        self.assertEqual(len(FakeGitHub.issues), 1)
        self.assertEqual(self.call("GET", "/api/reports")["pending"], [])

    def test_known_open_issue_gets_a_comment_and_a_closed_one_a_new_issue(self):
        self.mode("ask")
        logged_error("Delta")
        fp = self.call("GET", "/api/reports")["pending"][0]["fp"]
        FakeGitHub.issues = [{"number": 7, "title": f"[auto-report] Delta in x ({fp})", "state": "open"}]
        r = self.call("POST", "/api/reports/send", {"id": fp})
        self.assertEqual((r["action"], r["number"]), ("commented", 7))
        self.assertEqual(len(FakeGitHub.issues), 1)
        self.assertEqual(FakeGitHub.comments[0][0], 7)
        # a fixed (closed) issue that comes back: new issue that points to the old one
        self.tearDownApp()
        FakeGitHub.issues = [{"number": 7, "title": f"[auto-report] Delta in x ({fp})", "state": "closed"}]
        self.setUp_again()
        self.mode("ask")
        logged_error("Delta")
        r = self.call("POST", "/api/reports/send", {"id": self.call("GET", "/api/reports")["pending"][0]["fp"]})
        self.assertEqual(r["action"], "created")
        self.assertIn("#7", FakeGitHub.issues[0]["body"])

    def tearDownApp(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def setUp_again(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.srv = serve(make_server("127.0.0.1", 0, self.tmp.name))
        self.port = self.srv.server_address[1]
        self.app = self.srv.RequestHandlerClass.app

    def test_auto_mode_sends_by_itself(self):
        self.mode("auto")
        logged_error("Epsilon")
        self.assertTrue(self.wait(lambda: len(FakeGitHub.issues) == 1))
        self.assertTrue(self.wait(lambda: len(self.call("GET", "/api/reports")["sent"]) == 1))
        self.assertEqual(self.call("GET", "/api/reports")["pending"], [])

    def test_auto_mode_without_token_waits(self):
        self.mode("auto", token=False)
        logged_error("Zeta")
        self.assertEqual(len(self.call("GET", "/api/reports")["pending"]), 1)
        self.assertEqual(FakeGitHub.issues, [])

    def test_rate_limit_of_new_issues(self):
        self.mode("ask")
        for i in range(reports.MAX_ISSUES_PER_HOUR + 1):
            logged_error(f"Many{'abcdefgh'[i]}")
        for p in self.call("GET", "/api/reports")["pending"][: reports.MAX_ISSUES_PER_HOUR]:
            self.assertEqual(self.call("POST", "/api/reports/send", {"id": p["fp"]})["action"], "created")
        last = self.call("GET", "/api/reports")["pending"][0]
        self.assertIn("Too many reports", self.call("POST", "/api/reports/send", {"id": last["fp"]})["error"])
        self.assertEqual(len(FakeGitHub.issues), reports.MAX_ISSUES_PER_HOUR)

    def test_token_is_checked_saved_and_never_shown(self):
        bad = self.call("POST", "/api/reports/token", {"token": "has spaces in it"})
        self.assertEqual(bad["status"], 400)
        self.call("POST", "/api/reports/token", {"token": TOKEN})
        self.assertTrue(self.call("GET", "/api/reports")["token_set"])
        self.assertEqual(self.call("POST", "/api/reports/check")["repo"], "test/repo")
        for path in ("/api/reports", "/api/settings"):
            self.assertNotIn(TOKEN, json.dumps(self.call("GET", path)))
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/export", headers={"X-Requested-With": "sunak"})
        self.assertNotIn(TOKEN, urllib.request.urlopen(req, timeout=10).read().decode())
        self.assertNotIn(TOKEN, log.redact(f"sent with {TOKEN}"))
        self.call("POST", "/api/reports/token", {"token": "wrong" + "x" * 30})
        self.assertEqual(self.call("POST", "/api/reports/check")["status"], 400)  # GitHub says 401
        self.call("POST", "/api/reports/token", {"token": ""})
        self.assertFalse(self.call("GET", "/api/reports")["token_set"])

    def test_sample_report_shows_what_would_be_sent(self):
        state = self.call("POST", "/api/reports/sample")
        self.assertEqual(len(state["pending"]), 1)
        self.assertIn("[sample]", state["pending"][0]["title"])
        self.assertEqual(self.call("PUT", "/api/settings", {"error_reports": "maybe"})["status"], 400)


if __name__ == "__main__":
    unittest.main()
