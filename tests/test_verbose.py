"""Verbose mode (sunak/verbose.py): full requests and answers, secrets still masked, off by default.
Run:  python -m unittest discover tests"""

import base64
import io
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from sunak import __main__ as cli, log, verbose
from sunak.server import make_server
from test_server import serve


class Echo(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path == "/fail":
            body, code = b'{"error": "nope", "token": "supersecrettoken1"}', 400
        else:
            body, code = b'{"text": "hello"}\n{"text": "world"}\n', 200
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Set-Cookie", "session=abcdef123456")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class VerboseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.echo = serve(ThreadingHTTPServer(("127.0.0.1", 0), Echo))
        cls.url = f"http://127.0.0.1:{cls.echo.server_address[1]}"

    def setUp(self):
        self.out = io.StringIO()
        verbose.enable(stream=self.out)
        self.addCleanup(verbose.disable)

    def post(self, path, payload, headers=None):
        h = {"Content-Type": "application/json", **(headers or {})}
        return urllib.request.Request(self.url + path, json.dumps(payload).encode(), h, method="POST")

    def test_request_and_streamed_answer_are_logged_in_full(self):
        with urllib.request.urlopen(self.post("/chat", {"messages": [{"role": "user", "content": "Hi there"}]})) as r:
            lines = [line for line in r]
        self.assertEqual(len(lines), 2)  # the caller still gets the data unchanged
        text = self.out.getvalue()
        for part in ("→ POST", "/chat", "Hi there", "← 200", '"text": "hello"', '"text": "world"'):
            self.assertIn(part, text)

    def test_secrets_are_masked_everywhere(self):
        req = self.post("/chat", {"api_key": "sk-ant-abcdefghijkl", "password": "hunter2hunter2", "max_tokens": 5},
                        {"Authorization": "Bearer abcdefgh12345678", "x-api-key": "KEYKEYKEY12345"})
        urllib.request.urlopen(req).read()
        text = self.out.getvalue()
        for secret in ("abcdefghijkl", "hunter2hunter2", "abcdefgh12345678", "KEYKEYKEY12345", "abcdef123456"):
            self.assertNotIn(secret, text)
        self.assertIn('"max_tokens": 5', text)  # counters are not secrets

    def test_errors_are_logged_and_still_readable_by_the_caller(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.post("/fail", {}))
        self.assertEqual(cm.exception.code, 400)
        self.assertIn("nope", cm.exception.read().decode())
        text = self.out.getvalue()
        self.assertIn("← 400", text)
        self.assertNotIn("supersecrettoken1", text)

    def test_big_and_binary_data_is_replaced_by_its_size(self):
        blob = base64.b64encode(bytes(range(256)) * 200).decode()
        urllib.request.urlopen(self.post("/chat", {"images": [blob]})).read()
        text = self.out.getvalue()
        self.assertNotIn(blob[:200], text)
        self.assertIn("characters of base64 data", text)
        self.assertIn("bytes of binary data", verbose.body_text(b"\x00\x01\x02", "application/octet-stream"))
        self.assertIn("more characters", verbose.body_text(("x" * 30000).encode(), "text/plain"))

    def test_off_means_silent(self):
        verbose.disable()
        urllib.request.urlopen(self.post("/chat", {"a": 1})).read()
        self.assertEqual(self.out.getvalue(), "")

    def test_verbose_never_reaches_the_report_ring(self):
        urllib.request.urlopen(self.post("/chat", {"messages": "secret chat text"})).read()
        self.assertFalse(any("secret chat text" in line for line in log.recent(200)))

    def test_incoming_requests_are_logged(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            app = serve(make_server("127.0.0.1", 0, tmp))
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{app.server_address[1]}/api/login",
                                             json.dumps({"password": "pw-12345678", "profile": "x"}).encode(),
                                             {"Content-Type": "application/json", "X-Requested-With": "sunak"}, method="POST")
                try:
                    urllib.request.urlopen(req).read()
                except urllib.error.HTTPError:
                    pass
            finally:
                app.shutdown()
                app.server_close()
        text = self.out.getvalue()
        self.assertIn("⇐ POST /api/login", text)
        self.assertIn("⇒", text)
        self.assertNotIn("pw-12345678", text)


class RedactionTripwireTest(unittest.TestCase):
    """Deny by default: whatever the name, these must never show up (found by review of the first version)."""

    def test_unknown_headers_are_hidden(self):
        items = [("anthropic-api-key", "LEAK1"), ("PRIVATE-TOKEN", "LEAK2"), ("X-Api-Token", "LEAK3"),
                 ("X-Amz-Security-Token", "LEAK4"), ("OpenAI-Organization", "LEAK5"), ("Mcp-Session-Id", "LEAK6"),
                 ("X-Whatever-Custom", "LEAK7"), ("Content-Type", "application/json"), ("Location", "http://h/x?token=LEAK8")]
        text = verbose.header_lines(items)
        for n in range(1, 9):
            self.assertNotIn(f"LEAK{n}", text)
        self.assertIn("application/json", text)

    def test_json_secrets_in_any_shape(self):
        body = {"api_key": ["LEAK1"], "anthropic_key": "LEAK2", "openai_key": "LEAK3", "brave_key": "LEAK4", "key": "LEAK5",
                "GITHUB_PAT": "LEAK6", "pin": 1, "pin2": {"pin": 0}, "auth": {"user": "LEAK7"}, "jwt": "LEAK8",
                "env": [{"name": "API_KEY", "value": "LEAK9"}],
                "tool_calls": [{"function": {"arguments": json.dumps({"password": "LEAK10"})}}],
                "client_secret": {"a": ["LEAK11"]}, "max_tokens": 5, "model": "llama3"}
        text = verbose.body_text(json.dumps(body).encode(), "application/json")
        for n in range(1, 12):
            self.assertNotIn(f"LEAK{n}", text)
        self.assertIn('"pin": "***"', text)
        self.assertIn('"max_tokens": 5', text)
        self.assertIn("llama3", text)

    def test_urls(self):
        text = verbose.url_text("https://user:LEAK1@h.com/a?client_secret=LEAK2&refresh_token=LEAK3&signature=LEAK4&code=LEAK5"
                                "&pin=LEAK6&sid=LEAK7&q=hello#access_token=LEAK8")
        for n in range(1, 9):
            self.assertNotIn(f"LEAK{n}", text)
        self.assertIn("q=hello", text)

    def test_form_bodies(self):
        text = verbose.body_text(b"grant_type=refresh_token&refresh_token=LEAK1&client_secret=LEAK2&scope=a",
                                 "application/x-www-form-urlencoded")
        self.assertNotIn("LEAK", text)
        self.assertIn("grant_type=refresh_token", text)

    def test_log_redact_after_underscores(self):
        out = log.redact("refresh_token=LEAK1 client_secret: LEAK2 secret_key=LEAK3 max_tokens: 5")
        self.assertNotIn("LEAK", out)
        self.assertIn("max_tokens: 5", out)

    def test_log_file_is_private_from_the_start(self):
        import os, stat
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = str(Path(tmp) / "v.log")
            verbose.enable(path, stream=io.StringIO())
            try:
                verbose.emit("x")
            finally:
                verbose.disable()
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)


class VerboseCliTest(unittest.TestCase):
    def test_options_are_known_and_documented(self):
        for opt in ("--verbose", "-v", "--log-file"):
            self.assertIn(opt, cli.START_OPTIONS)
        self.assertIn("SUNAK_VERBOSE", cli.ENV_VARS)
        self.assertIn("verbose", Path(cli.__file__).with_name("verbose.py").read_text(encoding="utf-8").lower())

    def test_log_file_gets_the_lines(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = str(Path(tmp) / "sub" / "v.log")
            self.assertEqual(verbose.enable(path, stream=io.StringIO()), path)
            try:
                verbose.emit("[1] hello password=abc12345")
            finally:
                verbose.disable()
            content = Path(path).read_text(encoding="utf-8")
            self.assertIn("hello", content)
            self.assertNotIn("abc12345", content)
