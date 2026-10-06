"""Phone access: second listener on the network address (only with a password) and the QR code."""

import hashlib
import http.cookiejar
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

from sunak import qr, server
from sunak.server import make_server


class QrTest(unittest.TestCase):
    # matrices from the reference library "qrcode" (byte mode, level M, fixed mask), as SHA-256 of 0/1 rows
    REFERENCE = [("http://192.168.1.20:7000", 0, 2, "f1e7c83854b2b7f2d13d40c1dc352bcf8c68fbcb3a5d39af2244a3af7d1cad63"),
                 ("http://192.168.178.123:7001/?x=" + "a" * 60, 5, 6, "8795ebf674a08922e36448dfa22e08525e687920ee188cee2f697d4802b045c6"),
                 ("y" * 213, 3, 10, "6e67170b9a2b24077eec251494aaa35b58fd73ce6d75383f2ceaf5331262b992")]

    def test_matches_reference_library(self):
        for text, mask, version, digest in self.REFERENCE:
            rows = qr.encode(text, mask=mask)
            self.assertEqual(len(rows), version * 4 + 17)
            bits = "\n".join("".join("1" if v else "0" for v in r) for r in rows)
            self.assertEqual(hashlib.sha256(bits.encode()).hexdigest(), digest, (text[:20], mask))

    def test_svg_and_limits(self):
        svg = qr.svg("http://10.0.0.2:7000")
        self.assertTrue(svg.startswith("<svg") and svg.endswith("</svg>"))
        self.assertIn('fill="#fff"', svg)  # quiet zone on white, also in dark themes
        with self.assertRaises(ValueError):
            qr.encode("x" * 214)
        auto = qr.encode("http://10.0.0.2:7000")
        self.assertIn(auto, [qr.encode("http://10.0.0.2:7000", mask=m) for m in range(8)])


class LanTest(unittest.TestCase):
    def setUp(self):
        self.ip = server.lan_ip()
        if not self.ip:
            self.skipTest("no network address on this machine")
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.srv = make_server("127.0.0.1", 0, self.tmp.name)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.app = self.srv.RequestHandlerClass.app
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                  urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.addCleanup(self.close)

    def close(self):
        self.app.stop_lan()
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def call(self, method, path, body=None, base=None):
        req = urllib.request.Request((base or self.base) + path, data=json.dumps(body).encode() if body is not None else None,
                                     method=method, headers={"Content-Type": "application/json", "X-Requested-With": "sunak"})
        with self.opener.open(req, timeout=10) as r:
            return json.load(r)

    def error(self, *args, **kw):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.call(*args, **kw)
        return e.exception.code, json.load(e.exception)["error"]

    def test_needs_a_password(self):
        info = self.call("GET", "/api/lan")
        self.assertEqual((info["enabled"], info["password_set"], info["qr"]), (False, False, None))
        self.assertEqual(info["address"], f"http://{self.ip}:{self.srv.server_address[1]}")
        code, err = self.error("POST", "/api/lan", {"enabled": True})
        self.assertEqual(code, 400)
        self.assertIn("Set a password first", err)
        self.assertIsNone(self.app.lan)

    def test_on_off_and_password_removal(self):
        self.call("PUT", "/api/settings", {"password": "geheim"})
        self.call("POST", "/api/login", {"password": "geheim"})
        info = self.call("POST", "/api/lan", {"enabled": True})
        lan = f"http://{self.ip}:{self.srv.server_address[1]}"
        self.assertEqual((info["enabled"], info["url"]), (True, lan))
        self.assertTrue(info["qr"].startswith("<svg"))
        self.assertTrue(self.app.db.get_setting("lan_access"))
        # the phone reaches the same Sunak, and needs to log in
        plain = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with plain.open(lan + "/api/status", timeout=5) as r:
            self.assertTrue(json.load(r)["auth_required"])
        with self.assertRaises(urllib.error.HTTPError) as e:
            plain.open(urllib.request.Request(lan + "/api/sessions"), timeout=5)
        self.assertEqual(e.exception.code, 401)
        self.assertEqual(self.call("POST", "/api/lan", {"enabled": True})["url"], lan)  # twice is fine
        # removing the password closes the network address
        self.call("PUT", "/api/settings", {"password": ""})
        self.assertIsNone(self.app.lan)
        self.assertFalse(self.app.db.get_setting("lan_access"))
        with self.assertRaises(OSError):
            plain.open(lan + "/api/status", timeout=3)

    def test_restored_at_start_and_off(self):
        self.call("PUT", "/api/settings", {"password": "geheim"})
        self.app.db.set_setting("lan_access", True)
        self.app.restore_lan()
        self.assertIsNotNone(self.app.lan)
        self.call("POST", "/api/login", {"password": "geheim"})
        self.assertFalse(self.call("POST", "/api/lan", {"enabled": False})["enabled"])
        self.assertIsNone(self.app.lan)
        self.app.db.set_setting("lan_access", True)
        with mock.patch.object(server, "lan_ip", return_value=None):  # no network at start: a note, no crash
            self.app.restore_lan()
        self.assertIn("No local network", self.app.lan_info()["error"])


class FixedHostTest(unittest.TestCase):
    def test_started_for_the_whole_network(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            app = server.App(tmp)
            app.host, app.port = "0.0.0.0", 7000
            with mock.patch.object(server, "lan_ip", return_value="192.168.1.5"):
                info = app.lan_info()
            self.assertEqual((info["enabled"], info["fixed"], info["url"]), (True, True, "http://192.168.1.5:7000"))
            app.db.conn.close()


if __name__ == "__main__":
    unittest.main()
