"""Security package: SSRF protection of web research, rate limit for wrong passwords and PINs, admin profiles without PIN."""

import json
import os
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from email.message import Message
from unittest import mock

from sunak import netguard, research, server
from sunak.server import check_password, hash_password, make_server


def resolver(*ips):
    """A stand-in for socket.getaddrinfo that answers with the given addresses."""
    def fake(host, port, type=0):
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in ips]
    return fake


class PublicAddressTest(unittest.TestCase):
    def test_ranges(self):
        for ip in ("8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700:4700::1111", "::ffff:8.8.8.8"):
            self.assertTrue(netguard.is_public_ip(ip), ip)
        for ip in ("127.0.0.1", "127.8.9.1", "10.1.2.3", "172.16.0.1", "172.31.255.255", "192.168.1.10", "169.254.169.254",
                   "0.0.0.0", "100.64.0.1", "224.0.0.1", "255.255.255.255", "::1", "::", "fc00::1", "fd12:3456::1", "fe80::1",
                   "::ffff:127.0.0.1", "::ffff:10.0.0.1", "64:ff9b::7f00:1", "2002:7f00:1::1", "2001:db8::1", "ff02::1", "nonsense", "fe80::1%eth0"):
            self.assertFalse(netguard.is_public_ip(ip), ip)

    def test_check_url(self):
        netguard.check_url("https://example.com/x", resolver("93.184.216.34"))
        for url in ("http://localhost/", "ftp://example.com/", "file:///etc/passwd", "http:///x", "http://[::1]:8080/", "http://127.0.0.1:11434/api/tags"):
            with self.assertRaises(netguard.BlockedAddress, msg=url):
                netguard.check_url(url)  # the real resolver: these are all local or not web addresses
        with self.assertRaises(netguard.BlockedAddress):  # a name that points to the home network
            netguard.check_url("http://evil.example/", resolver("192.168.0.5"))
        with self.assertRaises(netguard.BlockedAddress):  # one private answer among public ones is enough
            netguard.check_url("http://evil.example/", resolver("93.184.216.34", "10.0.0.1"))
        with self.assertRaises(netguard.BlockedAddress):
            netguard.check_url("http://evil.example/", resolver("::1"))
        with self.assertRaises(netguard.BlockedAddress):  # unknown name
            netguard.check_url("http://nope.invalid/", mock.Mock(side_effect=socket.gaierror("no")))

    def test_switch_off(self):
        with mock.patch.dict(os.environ, {"SUNAK_ALLOW_PRIVATE_FETCH": "1"}):
            netguard.check_url("http://192.168.0.5/")
            with self.assertRaises(netguard.BlockedAddress):  # still only web addresses
                netguard.check_url("file:///etc/passwd")

    def test_unresolvable_name_through_a_proxy(self):
        with mock.patch.object(netguard, "_proxied", return_value=True):
            netguard.check_url("http://intranet-name/", mock.Mock(side_effect=socket.gaierror("no")))


class RedirectTest(unittest.TestCase):
    def redirect(self, location):
        h = Message()
        h["Location"] = location
        return urllib.error.HTTPError("http://a.example/", 302, "Found", h, None)

    def test_redirect_into_the_network_is_blocked(self):
        opener = mock.Mock()
        opener.open.side_effect = self.redirect("http://169.254.169.254/latest/meta-data/")
        with self.assertRaises(netguard.BlockedAddress):
            netguard.fetch_public("http://a.example/", opener=opener, resolve=lambda h, p, type=0: resolver("93.184.216.34")(h, p) if h == "a.example" else socket.getaddrinfo(h, p, type=type))
        self.assertEqual(opener.open.call_count, 1)  # the second request was never made

    def test_relative_redirect_and_loop(self):
        ok = mock.MagicMock()
        opener = mock.Mock()
        opener.open.side_effect = [self.redirect("/b"), ok]
        self.assertIs(netguard.fetch_public("http://a.example/a", opener=opener, resolve=resolver("93.184.216.34")), ok)
        self.assertEqual(opener.open.call_args[0][0].full_url, "http://a.example/b")
        opener.open.side_effect = lambda *a, **k: (_ for _ in ()).throw(self.redirect("/again"))
        with self.assertRaises(urllib.error.URLError):
            netguard.fetch_public("http://a.example/a", opener=opener, resolve=resolver("93.184.216.34"))

    def test_other_errors_pass_through(self):
        opener = mock.Mock()
        opener.open.side_effect = urllib.error.HTTPError("http://a.example/", 404, "Nope", Message(), None)
        with self.assertRaises(urllib.error.HTTPError):
            netguard.fetch_public("http://a.example/", opener=opener, resolve=resolver("93.184.216.34"))


class PinnedConnectionTest(unittest.TestCase):
    """The connection goes to the address that was checked, not to a second DNS answer (DNS rebinding)."""

    @classmethod
    def setUpClass(cls):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        cls.hosts = []

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                cls.hosts.append(self.headers["Host"])
                body = b"hello"
                self.send_response(200)
                self.send_header("Content-Length", "5")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        cls.srv = HTTPServer(("127.0.0.1", 0), H)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def answers(self, *per_call):
        """getaddrinfo stand-in: the n-th lookup of the test name gets the n-th address (the last one repeats)."""
        calls = []
        real = socket.getaddrinfo

        def fake(host, port, *a, **kw):
            if host != "rebind.example":
                return real(host, port, *a, **kw)
            ip = per_call[min(len(calls), len(per_call) - 1)]
            calls.append(ip)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
        return fake

    def test_second_dns_answer_is_not_used(self):
        self.hosts.clear()
        # the check sees a public address, the connection lookup sees 127.0.0.1: refused, and the server is never hit
        with mock.patch.object(socket, "getaddrinfo", self.answers("93.184.216.34", "127.0.0.1")), \
                mock.patch.object(netguard, "_proxied", return_value=False):
            with self.assertRaises(netguard.BlockedAddress):
                netguard.fetch_public("http://rebind.example:%d/" % self.port, opener=None)
        self.assertEqual(self.hosts, [])

    def test_connects_to_the_checked_address_with_the_name_as_host(self):
        self.hosts.clear()
        with mock.patch.dict(os.environ, {"SUNAK_ALLOW_PRIVATE_FETCH": "1"}), \
                mock.patch.object(socket, "getaddrinfo", self.answers("127.0.0.1")), \
                mock.patch.object(netguard, "_proxied", return_value=False):
            with netguard.fetch_public("http://rebind.example:%d/" % self.port) as r:
                self.assertEqual(r.read(), b"hello")
        self.assertEqual(self.hosts, ["rebind.example:%d" % self.port])

    def test_local_address_is_refused_before_connecting(self):
        self.hosts.clear()
        with mock.patch.object(netguard, "_proxied", return_value=False):
            with self.assertRaises(netguard.BlockedAddress):
                netguard.fetch_public("http://127.0.0.1:%d/" % self.port)
        self.assertEqual(self.hosts, [])


class ResearchTest(unittest.TestCase):
    def test_read_page_refuses_local_addresses(self):
        for url in ("http://127.0.0.1:11434/api/tags", "http://localhost/", "http://[::1]/", "http://169.254.169.254/"):
            with self.assertRaises(netguard.BlockedAddress, msg=url):
                research.read_page(url)

    def test_gather_skips_them(self):
        found = [{"title": "Inside", "url": "http://127.0.0.1:9/secret"}]
        with mock.patch.object(research, "search", return_value=found):
            self.assertEqual(research.gather("q"), [])

    def test_search_engines_may_be_local(self):
        # your own SearXNG on localhost keeps working: the engines do not use the page guard
        with mock.patch.object(research.urllib.request, "urlopen") as op, mock.patch.object(research.netguard, "fetch_public") as fp:
            op.return_value.__enter__.return_value = op.return_value  # like a real response
            op.return_value.read.return_value = b'{"results": []}'
            op.return_value.headers.get_content_charset.return_value = "utf-8"
            op.return_value.headers.get.return_value = "application/json"
            research.search_searxng("http://127.0.0.1:8888", "x")
            fp.assert_not_called()


class LimiterTest(unittest.TestCase):
    def test_backoff_and_reset(self):
        t = [0.0]
        lim = netguard.LoginLimiter(free=3, base=30, cap=100, clock=lambda: t[0])
        for _ in range(3):
            self.assertEqual(lim.wait("a"), 0)
            lim.fail("a")
        self.assertEqual(lim.wait("a"), 30)  # third failure: first lock
        self.assertEqual(lim.wait("b"), 0)  # other keys are not affected
        t[0] = 31
        self.assertEqual(lim.wait("a"), 0)
        lim.fail("a")
        self.assertEqual(lim.wait("a"), 60)  # doubles
        t[0] = 100
        lim.fail("a")
        self.assertEqual(lim.wait("a"), 100)  # capped
        lim.ok("a")
        self.assertEqual(lim.wait("a"), 0)

    def test_forgets_old_failures_and_stays_small(self):
        t = [0.0]
        lim = netguard.LoginLimiter(free=2, forget=100, max_keys=10, clock=lambda: t[0])
        lim.fail("a")
        t[0] = 200
        lim.fail("a")  # the first failure is old: counting starts again
        self.assertEqual(lim.wait("a"), 0)
        for i in range(50):
            lim.fail("k%d" % i)
        self.assertLessEqual(len(lim._state), 10)


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.srv = make_server("127.0.0.1", 0, os.path.join(cls.tmp.name, "data"))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.app = cls.srv.RequestHandlerClass.app
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def setUp(self):
        for p in self.app.profiles():
            if p["id"] != "default":
                self.app.close_profile(p["id"])
        self.app.main.set_setting("profiles", [])
        self.app.main.set_setting("password_hash", "")
        self.app.ip_limit = netguard.LoginLimiter(free=5)
        self.app.account_limit = netguard.LoginLimiter(free=20, base=15)
        patch = mock.patch.object(server.time, "sleep")
        patch.start()
        self.addCleanup(patch.stop)

    def req(self, method, path, body=None, headers=None):
        """(status, parsed body, response headers); `headers` may add e.g. X-Forwarded-For to look like a remote client."""
        h = {"Content-Type": "application/json", "X-Requested-With": "sunak", **(headers or {})}
        r = urllib.request.Request(self.base + path, json.dumps(body).encode() if body is not None else None, h, method=method)
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, json.loads(resp.read() or b"null"), resp.headers
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null"), e.headers

    REMOTE = {"X-Forwarded-For": "203.0.113.7"}

    # login rate limit
    def test_login_lockout(self):
        self.app.main.set_setting("password_hash", hash_password("secret-pw"))
        for _ in range(5):
            self.assertEqual(self.req("POST", "/api/login", {"password": "nope"})[0], 401)
        status, body, headers = self.req("POST", "/api/login", {"password": "nope"})
        self.assertEqual(status, 429)
        self.assertGreater(int(headers["Retry-After"]), 0)
        self.assertIn("Too many", body["error"])
        self.assertEqual(self.req("POST", "/api/login", {"password": "secret-pw"})[0], 429)  # even the right one has to wait
        # another client address is not locked by the first one
        self.assertEqual(self.req("POST", "/api/login", {"password": "secret-pw"}, self.REMOTE)[0], 200)

    def test_login_success_resets(self):
        self.app.main.set_setting("password_hash", hash_password("secret-pw"))
        for _ in range(4):
            self.req("POST", "/api/login", {"password": "nope"})
        self.assertEqual(self.req("POST", "/api/login", {"password": "secret-pw"})[0], 200)
        for _ in range(4):
            self.assertEqual(self.req("POST", "/api/login", {"password": "nope"})[0], 401)

    def test_login_account_limit_against_many_addresses(self):
        self.app.main.set_setting("password_hash", hash_password("secret-pw"))
        for i in range(20):
            self.assertEqual(self.req("POST", "/api/login", {"password": "nope"}, {"X-Forwarded-For": "198.51.100.%d" % i})[0], 401)
        self.assertEqual(self.req("POST", "/api/login", {"password": "secret-pw"}, {"X-Forwarded-For": "198.51.100.99"})[0], 429)

    # profiles
    def two_profiles(self, admin_pin=""):
        self.app.main.set_setting("profiles", [{"id": "default", "name": "", "emoji": "", "admin": True, "pin_hash": hash_password(admin_pin) if admin_pin else ""},
                                               {"id": "guest", "name": "Guest", "emoji": "", "admin": False, "pin_hash": hash_password("1234")}])

    def test_admin_without_pin_is_locked_for_remote_clients(self):
        self.two_profiles()
        status, body, _ = self.req("POST", "/api/profiles/select", {"id": "default", "pin": ""}, self.REMOTE)
        self.assertEqual(status, 403)
        self.assertIn("needs a PIN", body["error"])
        listed = self.req("GET", "/api/profiles", headers=self.REMOTE)[1]["profiles"]
        self.assertEqual({p["id"]: p["locked"] for p in listed}, {"default": True, "guest": False})
        # this computer itself can still open it (and set the PIN)
        self.assertEqual(self.req("POST", "/api/profiles/select", {"id": "default", "pin": ""})[0], 200)
        self.assertFalse(self.req("GET", "/api/profiles")[1]["profiles"][0]["locked"])

    def test_admin_with_pin_and_single_profile_are_unchanged(self):
        self.two_profiles(admin_pin="9999")
        self.assertEqual(self.req("POST", "/api/profiles/select", {"id": "default", "pin": "9999"}, self.REMOTE)[0], 200)
        self.assertEqual(self.req("POST", "/api/profiles/select", {"id": "default", "pin": "0000"}, self.REMOTE)[0], 403)
        self.app.main.set_setting("profiles", [])  # only the main profile, no PIN: nothing to protect from
        self.assertEqual(self.req("POST", "/api/profiles/select", {"id": "default", "pin": ""}, self.REMOTE)[0], 200)
        self.assertFalse(self.req("GET", "/api/profiles", headers=self.REMOTE)[1]["profiles"][0]["locked"])

    def test_pin_lockout_is_per_client_and_profile(self):
        self.two_profiles()
        for _ in range(5):
            self.assertEqual(self.req("POST", "/api/profiles/select", {"id": "guest", "pin": "0000"}, self.REMOTE)[0], 403)
        self.assertEqual(self.req("POST", "/api/profiles/select", {"id": "guest", "pin": "1234"}, self.REMOTE)[0], 429)
        self.assertEqual(self.req("POST", "/api/profiles/select", {"id": "guest", "pin": "1234"})[0], 200)  # other client

    def test_hash_roundtrip_still_works(self):
        self.assertTrue(check_password("x", hash_password("x")))


if __name__ == "__main__":
    unittest.main()
