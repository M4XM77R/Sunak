"""Interface languages: the German texts cover the page, fit the placeholders, and the setting is checked."""

import html.parser
import json
import re
import tempfile
import threading
import unittest
import urllib.error

from sunak import server
from sunak.server import STATIC, make_server

import test_server

PLACEHOLDER = re.compile(r"\{\w+\}")


def load_lang(code):
    text = (STATIC / f"lang-{code}.js").read_text(encoding="utf-8")
    m = re.search(r"\.(\w+) = \{ name: '([^']+)', strings: (\{.*\}) \};\s*$", text, re.S)
    assert m and m.group(1) == code, f"lang-{code}.js has an unexpected layout"
    return m.group(2), json.loads(m.group(3))


class _Texts(html.parser.HTMLParser):
    """Visible text and translated attributes of a page, as i18n.js sees them."""
    SKIP = {"script", "style", "code", "textarea", "title"}

    def __init__(self):
        super().__init__()
        self.found, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        self.skip += tag in self.SKIP
        self.found += [v.strip() for k, v in attrs if k in ("title", "placeholder", "aria-label") and v and v.strip()]

    def handle_endtag(self, tag):
        self.skip -= tag in self.SKIP

    def handle_data(self, data):
        if not self.skip and re.search("[A-Za-z]{2}", data):
            self.found.append(data.strip())


class LanguageFilesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.name, cls.de = load_lang("de")

    def test_every_language_file_is_known_to_the_server(self):
        files = sorted(p.name[5:-3] for p in STATIC.glob("lang-*.js"))
        self.assertEqual(files, sorted(c for c in server.LANGUAGES if c != "en"))
        self.assertEqual(self.name, "Deutsch")
        page = (STATIC / "index.html").read_text(encoding="utf-8")
        order = [page.index(s) for s in ('src="/theme.js"', 'src="/lang-de.js"', 'src="/i18n.js"', 'src="/app.js"')]
        self.assertEqual(order, sorted(order))
        self.assertIn('src="/i18n.js"', (STATIC / "login.html").read_text(encoding="utf-8"))

    def test_pages_are_fully_translated(self):
        for page in ("index.html", "login.html"):
            p = _Texts()
            p.feed((STATIC / page).read_text(encoding="utf-8"))
            missing = [t for t in p.found if t not in self.de]
            self.assertEqual(missing, [], page)

    def test_every_tr_call_is_translated(self):
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        keys = re.findall(r"\btr\('((?:[^'\\]|\\.)*)'", js) + re.findall(r"\btrn\([^,]+, '([^']*)', '([^']*)'", js)
        keys = [k for item in keys for k in (item if isinstance(item, tuple) else (item,))]
        self.assertGreater(len(keys), 60)
        self.assertEqual([k for k in keys if k not in self.de], [])
        self.assertIn("TITLES[view]", js)  # translated with tr() too
        titles = re.search(r"const TITLES = (\{.*?\});", js).group(1)
        self.assertEqual([t for t in re.findall(r"'([^']+)'", titles)[1::2] if t not in self.de], [])

    def test_placeholders_match_and_keys_are_trimmed(self):
        for key, value in self.de.items():
            self.assertEqual(sorted(PLACEHOLDER.findall(key)), sorted(PLACEHOLDER.findall(value)), key)
            self.assertEqual(key, key.strip())
            self.assertTrue(value.strip(), key)

    def test_translations_are_not_translated_again(self):
        # i18n.js translates every new text, also its own output: a German text must not look like an English key
        patterns = []
        for key in self.de:
            if PLACEHOLDER.search(key) and len(PLACEHOLDER.sub("", key)) >= 10:  # same rule as in i18n.js
                parts = re.split(r"(\{\w+\})", key)
                patterns.append(re.compile("^" + "".join("[\\s\\S]+?" if i % 2 else re.escape(s) for i, s in enumerate(parts)) + "$"))
        for key, value in self.de.items():
            shown = PLACEHOLDER.sub("X", value)
            if shown in self.de:
                self.assertEqual(self.de[shown], shown, f"{key!r} → {value!r} is itself a key")
            if value != key:
                self.assertFalse([p.pattern for p in patterns if p.match(shown)], value)

    def test_server_messages_match_their_source(self):
        # a few translated server texts, so a reworded message shows up here instead of silently in English
        src = "".join((STATIC.parent / f).read_text(encoding="utf-8") for f in ("server.py", "mail.py", "ollama.py", "gpu.py"))
        for text in ("Thinking of a search query…", "Planning search queries…", "Wrong password",
                     "Tiny and fast. Runs on almost any computer.", "Use the separate e-mail password from the Telekom"):
            self.assertIn(text, src)
            self.assertTrue(any(k.startswith(text) for k in self.de), text)


class LanguageSettingTest(unittest.TestCase):
    call = classmethod(test_server.SunakTest.call.__func__)

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

    def test_language_setting(self):
        self.assertEqual(self.call("GET", "/api/settings")["language"], "")  # follow the browser
        self.assertEqual(self.call("PUT", "/api/settings", {"language": "de"})["language"], "de")
        self.assertEqual(self.call("GET", "/api/settings")["language"], "de")
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.call("PUT", "/api/settings", {"language": "xx"})
        self.assertEqual(e.exception.code, 400)
        self.assertIn("Unknown language", json.loads(e.exception.read())["error"])
        self.assertEqual(self.call("PUT", "/api/settings", {"language": ""})["language"], "")

    def test_language_files_are_served_without_login(self):
        self.call("PUT", "/api/settings", {"password": "secret1"})
        try:
            for f in ("/i18n.js", "/lang-de.js"):
                self.assertIn("SUNAK_LANG", self.call("GET", f, raw=True, headers={}))
        finally:
            self.srv.RequestHandlerClass.app.db.set_setting("password_hash", "")


if __name__ == "__main__":
    unittest.main()
