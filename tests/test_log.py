"""Logging (sunak/log.py): readable lines, a log file of at most 50 MB, and nothing private in it.
Run:  python -m unittest discover tests"""

import io
import json
import logging
import os
import stat
import tempfile
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from sunak import __main__ as cli, log
from sunak.server import make_server
from test_server import FakeBackend, serve


def reset():
    root = logging.getLogger(log.ROOT)
    for h in list(root.handlers):
        if getattr(h, "_sunak", False):
            root.removeHandler(h)
            h.close()
    root.setLevel(logging.NOTSET)
    root.propagate = True


class RedactTest(unittest.TestCase):
    def test_secrets_are_masked(self):
        log.add_secret("my-very-own-key-4711")
        for text, hidden in (("key my-very-own-key-4711 failed", "my-very-own-key-4711"),
                             ("Authorization: Bearer abcdefgh12345678", "abcdefgh12345678"),
                             ('{"api_key": "sk-ant-abcdefghijkl"}', "abcdefghijkl"),
                             ("GET /x?key=SECRETVALUE&a=1", "SECRETVALUE"),
                             ("password=hunter2 next", "hunter2"),
                             ("token " + "a1" * 20, "a1" * 20),
                             ("cookie: sunak_token=0123456789abcdef0123456789abcdef", "0123456789abcdef0123456789abcdef")):
            out = log.redact(text)
            self.assertNotIn(hidden, out, text)
            self.assertIn("***", out)
        self.assertEqual(log.redact("POST /api/chat 200 1.2s"), "POST /api/chat 200 1.2s")

    def test_total_size_limit_is_50_mb(self):
        self.assertEqual(log.MAX_BYTES * (log.BACKUPS + 1), 50 * 1024 * 1024)


class FileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

    def tearDown(self):
        reset()
        self.tmp.cleanup()

    def test_file_rotates_and_stays_small(self):
        path = log.setup(self.tmp.name, stream=io.StringIO(), max_bytes=2000, backups=2)
        self.assertEqual(path, Path(self.tmp.name) / "logs" / "sunak.log")
        logger = log.get("test")
        for i in range(400):
            logger.info("line number %d with some text to fill the file up", i)
        files = sorted(p.name for p in (Path(self.tmp.name) / "logs").iterdir())
        self.assertEqual(files, ["sunak.log", "sunak.log.1", "sunak.log.2"])
        self.assertLessEqual(sum(p.stat().st_size for p in (Path(self.tmp.name) / "logs").iterdir()), 3 * 2000 + 200)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        last = log.tail(self.tmp.name, 3)
        self.assertEqual(len(last), 3)
        self.assertIn("line number 399", last[-1])
        self.assertRegex(last[-1], r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d INFO    test     line number")

    def test_terminal_line_has_time_level_and_part_and_levels_filter(self):
        out = io.StringIO()
        log.setup(self.tmp.name, debug=False, stream=out)
        log.get("queue").info("hello")
        log.get("queue").debug("hidden")
        log.get("queue").warning("careful")
        text = out.getvalue()
        self.assertRegex(text, r"\d\d:\d\d:\d\d INFO    queue    hello")
        self.assertIn("WARNING queue    careful", text)
        self.assertNotIn("hidden", text)
        out2 = io.StringIO()
        log.setup(self.tmp.name, debug=True, stream=out2)
        log.get("queue").debug("shown")
        self.assertIn("DEBUG   queue    shown", out2.getvalue())

    def test_tracebacks_are_logged_without_secrets(self):
        out = io.StringIO()
        log.setup(self.tmp.name, stream=out)
        try:
            raise RuntimeError("connection failed, password=hunter2")
        except RuntimeError:
            log.get("app").error("Boom", exc_info=True)
        self.assertIn("RuntimeError", out.getvalue())
        self.assertNotIn("hunter2", out.getvalue())

    def test_unwritable_folder_still_logs_to_the_terminal(self):
        blocker = Path(self.tmp.name) / "file"
        blocker.write_text("x")
        out = io.StringIO()
        self.assertIsNone(log.setup(blocker / "data", stream=out))
        self.assertIn("No log file", out.getvalue())

    def test_logs_command(self):
        log.setup(self.tmp.name, stream=io.StringIO())
        for i in range(5):
            log.get("x").info("entry %d", i)
        out = io.StringIO()
        import contextlib
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.logs_command(["2", "--data-dir", self.tmp.name]), 0)
        text = out.getvalue()
        self.assertIn(str(Path(self.tmp.name) / "logs" / "sunak.log"), text)
        self.assertIn("entry 4", text)
        self.assertNotIn("entry 2", text)
        with contextlib.redirect_stdout(io.StringIO()) as empty:
            self.assertEqual(cli.logs_command(["--data-dir", self.tmp.name + "/none"]), 0)
        self.assertIn("no log yet", empty.getvalue())


class RequestLogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chat = serve(ThreadingHTTPServer(("127.0.0.1", 0), FakeBackend))
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.out = io.StringIO()
        log.setup(cls.tmp.name, debug=False, stream=cls.out)
        cls.app = serve(make_server("127.0.0.1", 0, cls.tmp.name))
        cls.port = cls.app.server_address[1]
        cls.call("PUT", "/api/settings", {"providers": [
            {"id": "ollama", "name": "Ollama", "type": "ollama", "api_key": "topsecretkey-9f8e7d6c",
             "base_url": f"http://127.0.0.1:{cls.chat.server_address[1]}"}]})

    @classmethod
    def tearDownClass(cls):
        reset()
        for s in (cls.app, cls.chat):
            s.shutdown()
            s.server_close()
        cls.tmp.cleanup()

    @classmethod
    def call(cls, method, path, body=None, expect_error=False):
        req = urllib.request.Request(f"http://127.0.0.1:{cls.port}{path}", data=json.dumps(body).encode() if body is not None else None,
                                     method=method, headers={"Content-Type": "application/json", "X-Requested-With": "sunak"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.read().decode()
        except urllib.error.HTTPError as e:
            if not expect_error:
                raise
            return e.code

    def test_requests_are_logged_without_contents(self):
        s = json.loads(self.call("POST", "/api/sessions", {"model": "ollama::tiny:1b"}))
        self.call("POST", "/api/chat", {"session_id": s["id"], "content": "MY-PRIVATE-QUESTION-42", "model": "ollama::tiny:1b"})
        self.call("GET", "/api/search?q=MY-PRIVATE-SEARCH-43", expect_error=True)
        self.assertEqual(self.call("POST", "/api/nonsense", {"a": 1}, expect_error=True), 404)
        for _ in range(100):  # the server logs a request just after it has answered it
            if "POST /api/nonsense 404" in self.out.getvalue() and "POST /api/chat 200" in self.out.getvalue():
                break
            time.sleep(0.05)
        text = self.out.getvalue()
        self.assertRegex(text, r"INFO    http     POST /api/sessions 200 \d+\.\ds")
        self.assertRegex(text, r"INFO    http     POST /api/chat 200 \d+\.\ds")
        self.assertRegex(text, r"WARNING http     POST /api/nonsense 404")
        for private in ("MY-PRIVATE-QUESTION-42", "MY-PRIVATE-SEARCH-43", "topsecretkey-9f8e7d6c", "Hello from Ollama"):
            self.assertNotIn(private, text)
            self.assertNotIn(private, "".join(log.tail(self.tmp.name, 1000) or []))
        self.assertNotIn("GET /api/sessions", text)  # reading is only logged in debug mode
        self.assertRegex("".join(log.tail(self.tmp.name, 1000)), r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d INFO    http     POST /api/chat")


if __name__ == "__main__":
    unittest.main()
