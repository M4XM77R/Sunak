"""Regression tests for bugs found in the second review: hostile PDFs, logins across restarts,
removed providers, API keys on redirects."""

import json
import os
import tempfile
import threading
import time
import unittest
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from sunak import extract, providers
from sunak.server import App


class HostilePdfTest(unittest.TestCase):
    def run_fast(self, pdf):
        t = time.time()
        with self.assertRaises(extract.ExtractError):
            extract.extract_text("x.pdf", pdf)
        self.assertLess(time.time() - t, 5)

    def test_overlapping_object_stream_offsets(self):
        # offsets 0, L, 0, L, ... used to copy L bytes per object: GBs of RAM from a 17 KB upload
        n, size = 6000, 1_000_000
        head = b" ".join(b"%d %d" % (i + 10, 0 if i % 2 == 0 else size) for i in range(n)) + b" "
        comp = zlib.compress(head + b"x" * (size + 10), 9)
        self.run_fast(b"%%PDF-1.5\n1 0 obj\n<< /Type /ObjStm /N %d /First %d /Filter /FlateDecode /Length %d >>\nstream\n"
                      % (n, len(head), len(comp)) + comp + b"\nendstream\nendobj\n")

    def test_streams_without_endstream(self):
        # every object copied the rest of the file: quadratic time and memory
        self.run_fast(b"%PDF-1.4\n" + b"".join(b"%d 0 obj << >> stream\nendobj\n" % i for i in range(16000)))


class LoginTest(unittest.TestCase):
    def test_env_password_keeps_logins_across_restarts(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, \
                mock.patch.dict(os.environ, {"SUNAK_PASSWORD": "secret1"}):
            first = App(tmp)
            token = first.token()
            self.assertEqual(App(tmp).token(), token)  # same password, same cookie
            with mock.patch.dict(os.environ, {"SUNAK_PASSWORD": "other"}):
                self.assertNotEqual(App(tmp).token(), token)  # a new password logs everyone out


class ProvidersTest(unittest.TestCase):
    def test_removing_all_providers_sticks(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            app = App(tmp)
            app.save_settings({"providers": []})
            self.assertEqual(app.settings()["providers"], [])


class RedirectTest(unittest.TestCase):
    def test_api_key_is_not_sent_to_another_host(self):
        seen = {}

        class Target(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                seen["auth"] = self.headers.get("Authorization")
                body = json.dumps({"data": [{"id": "m"}]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        target = ThreadingHTTPServer(("127.0.0.1", 0), Target)

        class Redirect(Target):
            def do_GET(self):
                self.send_response(302)
                # "localhost" vs "127.0.0.1": another host name, so the key must be dropped
                self.send_header("Location", f"http://localhost:{target.server_address[1]}/v1/models")
                self.send_header("Content-Length", "0")
                self.end_headers()

        source = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
        for srv in (target, source):
            threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            p = {"type": "openai", "base_url": f"http://127.0.0.1:{source.server_address[1]}/v1", "api_key": "sk-secret"}
            self.assertEqual(providers.list_models(p), ["m"])
            self.assertIsNone(seen["auth"])
        finally:
            for srv in (target, source):
                srv.shutdown()
                srv.server_close()

    def test_a_busy_backend_keeps_its_model_list(self):
        """A backend that answers late does not empty the picker, in any profile; a refused connection does empty it."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            app = App(tmp)
            pid = app.settings()["providers"][0]["id"]
            release = threading.Event()
            calls = []

            def fake(p, timeout=0):
                calls.append(timeout)
                if len(calls) == 1:
                    return ["a", "b"]
                if len(calls) == 2:
                    release.wait(10)  # busy
                    return ["a", "b", "c"]
                raise providers.ProviderError("Cannot reach x: Connection refused")

            with mock.patch.object(providers, "list_models", fake), mock.patch.object(providers, "MODELS_GRACE", 0.2):
                self.assertEqual([m["name"] for m in app.models()["models"]], ["a", "b"])
                other = app.view("kid")  # a new view for every request: the list belongs to the installation
                self.assertIsNot(other, app)
                start = time.time()
                r = other.models()
                self.assertLess(time.time() - start, 5)
                self.assertEqual([m["name"] for m in r["models"]], ["a", "b"])  # at once, from the last success
                self.assertTrue(r["errors"][0]["stale"])
                release.set()
                for _ in range(50):  # the request that went on refreshes the list
                    if app.root._model_lists and len(next(iter(app.root._model_lists.values()))) == 3:
                        break
                    time.sleep(0.1)
                r = app.models()
                self.assertEqual((r["models"], r["errors"][0]["provider"], r["errors"][0]["stale"]), ([], pid, False))
            self.assertEqual(calls, [providers.MODELS_TIMEOUT] * 3)


if __name__ == "__main__":
    unittest.main()
