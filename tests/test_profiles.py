"""Several profiles: choosing one (with PIN), separate data per profile, own preferences, admin rights."""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from sunak.server import make_server


class ProfilesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.data = os.path.join(cls.tmp.name, "data")
        cls.srv = make_server("127.0.0.1", 0, cls.data)
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

    def req(self, method, path, body=None, cookie=None, full=False):
        h = {"Content-Type": "application/json", "X-Requested-With": "sunak"}
        if cookie:
            h["Cookie"] = cookie
        r = urllib.request.Request(self.base + path, json.dumps(body).encode() if body is not None else None, h, method=method)
        with urllib.request.urlopen(r, timeout=10) as resp:
            out = json.loads(resp.read() or b"null")
            if full:
                return out, resp.headers.get("Set-Cookie", "")
            return out

    def error(self, *args, **kw):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.req(*args, **kw)
        return e.exception.code, json.loads(e.exception.read())["error"]

    def select(self, pid, pin=""):
        _, cookie = self.req("POST", "/api/profiles/select", {"id": pid, "pin": pin}, full=True)
        return cookie.split(";")[0]

    def make(self, **kw):
        return self.req("POST", "/api/profiles", kw, cookie=self.select("default"))

    def test_one_profile_needs_no_choice(self):
        res = self.req("GET", "/api/profiles")
        self.assertEqual(res, {"profiles": [{"id": "default", "name": "", "emoji": "🙂", "admin": True, "has_pin": False}],
                               "current": "default", "need_choice": False})
        self.assertEqual(self.req("GET", "/api/settings")["profile"]["id"], "default")

    def test_separate_data_and_preferences(self):
        kid = self.make(name="Kid", emoji="🦄", pin="1234")
        self.assertEqual(kid, {"id": kid["id"], "name": "Kid", "emoji": "🦄", "admin": False, "has_pin": True})
        res = self.req("GET", "/api/profiles")
        self.assertEqual((res["need_choice"], res["current"]), (True, None))
        self.assertEqual(self.error("GET", "/api/sessions"), (409, "Choose a profile"))
        self.assertEqual(self.error("POST", "/api/profiles/select", {"id": kid["id"], "pin": "0000"})[0], 403)
        self.assertEqual(self.error("POST", "/api/profiles/select", {"id": "nope"})[0], 404)
        main, k = self.select("default"), self.select(kid["id"], "1234")
        self.assertEqual(self.req("GET", "/api/profiles", cookie=k)["current"], kid["id"])
        forged = k.split(".")[0] + "." + "0" * 64
        self.assertEqual(self.error("GET", "/api/sessions", cookie=forged)[0], 409)
        # each profile has its own chats, notes, documents and calendar
        self.req("POST", "/api/sessions", {}, cookie=main)
        self.req("POST", "/api/notes", {"content": "My name is Max", "is_memory": True}, cookie=main)
        self.req("POST", "/api/documents", {"title": "Plan", "content": "x"}, cookie=main)
        self.req("POST", "/api/calendar/events", {"event": {"summary": "Dentist", "start": "2026-10-06", "all_day": True}}, cookie=main)
        self.assertEqual(len(self.req("GET", "/api/sessions", cookie=main)), 1)
        for path in ("/api/sessions", "/api/notes", "/api/documents"):
            self.assertEqual(self.req("GET", path, cookie=k), [], path)
        q = "/api/calendar/events?start=2026-10-01T00:00:00%2B02:00&end=2026-11-01T00:00:00%2B01:00"
        self.assertEqual(len(self.req("GET", q, cookie=main)["events"]), 1)
        self.assertEqual(self.req("GET", q, cookie=k)["events"], [])
        self.req("POST", "/api/notes", {"content": "I like horses", "is_memory": True}, cookie=k)
        self.assertEqual([n["content"] for n in self.req("GET", "/api/notes", cookie=main)], ["My name is Max"])
        self.assertTrue(os.path.exists(os.path.join(self.data, "profiles", kid["id"], "sunak.db")))
        kid_app = self.app.view(kid["id"])
        self.assertEqual(kid_app.db.memories(), ["I like horses"])
        self.assertEqual(str(kid_app.user_dir), os.path.join(self.data, "profiles", kid["id"]))
        self.assertIs(kid_app.mcp, self.app.mcp)  # shared parts come from the installation
        # preferences: own theme and prompt, installation settings shared
        self.req("PUT", "/api/settings", {"theme": "ocean", "system_prompt": "Talk like a pirate", "language": "de"}, cookie=k)
        self.req("PUT", "/api/settings", {"agent_timeout": 99, "theme": "retro"}, cookie=main)
        sk, sm = self.req("GET", "/api/settings", cookie=k), self.req("GET", "/api/settings", cookie=main)
        self.assertEqual((sk["theme"], sk["system_prompt"], sk["language"], sk["agent_timeout"]), ("ocean", "Talk like a pirate", "de", 99))
        self.assertEqual((sm["theme"], sm["language"], sm["agent_timeout"]), ("retro", "", 99))
        self.assertEqual(sk["providers"], sm["providers"])
        self.assertEqual((sk["profile"]["name"], sk["profile"]["admin"], sk["profiles_count"]), ("Kid", False, 2))
        self.assertNotIn("Max", json.dumps(self.req("GET", "/api/export", cookie=k)["notes"]))

    def test_admin_rights(self):
        kid = self.make(name="Kid")
        partner = self.make(name="Partner", admin=True)
        main, k, pa = self.select("default"), self.select(kid["id"]), self.select(partner["id"])
        for path, body in [("/api/settings", {"providers": []}), ("/api/settings", {"agent_enabled": True}),
                           ("/api/settings", {"password": "secret"}), ("/api/settings", {"mcp_servers": []})]:
            code, err = self.error("PUT", path, body, cookie=k)
            self.assertEqual((code, "admin" in err), (403, True), body)
        for path, body in [("/api/models/pull", {"model": "x"}), ("/api/agent", {}), ("/api/lan", {"enabled": True}),
                           ("/api/update", {}), ("/api/mcp/test", {}), ("/api/profiles", {"name": "X"})]:
            self.assertEqual(self.error("POST", path, body, cookie=k)[0], 403, path)
        self.assertEqual(self.error("DELETE", f"/api/profiles/{partner['id']}", cookie=k)[0], 403)
        self.assertEqual(self.error("PATCH", f"/api/profiles/{partner['id']}", {"name": "X"}, cookie=k)[0], 403)
        self.assertEqual(self.error("PATCH", f"/api/profiles/{kid['id']}", {"admin": True}, cookie=k)[0], 403)
        # own name, emoji and PIN: the device stays in the profile, other devices must enter the new PIN
        out, cookie = self.req("PATCH", f"/api/profiles/{kid['id']}", {"name": "Lena", "emoji": "🐴", "pin": "4321"}, cookie=k, full=True)
        self.assertEqual((out["name"], out["emoji"], out["has_pin"]), ("Lena", "🐴", True))
        new_k = cookie.split(";")[0]
        self.assertEqual(self.req("GET", "/api/settings", cookie=new_k)["profile"]["name"], "Lena")
        self.assertEqual(self.error("GET", "/api/settings", cookie=k)[0], 409)
        self.assertEqual(self.error("PATCH", f"/api/profiles/{kid['id']}", {"pin": "12"}, cookie=new_k)[0], 400)
        # an admin profile may do it all, except removing the main profile's rights or deleting it
        self.req("PUT", "/api/settings", {"agent_timeout": 77}, cookie=pa)
        self.assertEqual(self.error("PATCH", "/api/profiles/default", {"admin": False}, cookie=pa)[0], 400)
        self.assertEqual(self.error("DELETE", "/api/profiles/default", cookie=pa)[0], 400)
        self.assertEqual(self.error("DELETE", f"/api/profiles/{partner['id']}", cookie=pa)[0], 400)  # not the own one
        self.req("POST", "/api/notes", {"content": "x"}, cookie=new_k)
        folder = os.path.join(self.data, "profiles", kid["id"])
        self.assertTrue(os.path.isdir(folder))
        self.req("DELETE", f"/api/profiles/{kid['id']}", cookie=main)
        self.assertFalse(os.path.exists(folder))
        self.assertEqual([p["id"] for p in self.req("GET", "/api/profiles", cookie=main)["profiles"]], ["default", partner["id"]])
        self.assertEqual(self.error("GET", "/api/settings", cookie=new_k)[0], 409)

    def test_main_profile_with_pin(self):
        self.req("PATCH", "/api/profiles/default", {"name": "Max", "pin": "9999"})
        res = self.req("GET", "/api/profiles")
        self.assertEqual((res["need_choice"], res["profiles"][0]["has_pin"]), (True, True))
        main = self.select("default", "9999")
        self.assertEqual(self.req("GET", "/api/settings", cookie=main)["profile"]["name"], "Max")
        self.req("PATCH", "/api/profiles/default", {"pin": ""}, cookie=main)
        self.assertFalse(self.req("GET", "/api/profiles")["need_choice"])


if __name__ == "__main__":
    unittest.main()
