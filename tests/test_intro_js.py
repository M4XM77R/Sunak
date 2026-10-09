"""The introduction (first start of a profile): its steps in app.js (run with node, skipped without node), the German texts,
the icons and the per-profile setting `intro_seen`.
Run:  python -m unittest discover tests"""

import json
import re
import shutil
import subprocess
import tempfile
import unittest

from sunak.server import STATIC, make_server

import test_i18n
import test_server

NODE = shutil.which("node")
SRC = (STATIC / "app.js").read_text(encoding="utf-8")
PART = re.search(r"// BEGIN introSteps[^\n]*\n(.*?)// END introSteps", SRC, re.S).group(1)


def steps():
    res = subprocess.run([NODE, "-e", PART + "\nconsole.log(JSON.stringify(INTRO));"], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


@unittest.skipUnless(NODE, "node is not installed")
class IntroStepsTest(unittest.TestCase):
    def test_steps_are_complete_and_translated(self):
        de = test_i18n.load_lang("de")[1]
        st = steps()
        self.assertGreaterEqual(len(st), 5)
        icons = (STATIC / "icons.js").read_text(encoding="utf-8")
        texts = []
        for s in st:
            self.assertRegex(icons, rf"(?m)^\s*'?{re.escape(s['icon'])}'?:", s["title"])
            texts += [s["title"], *s["text"]]
        self.assertEqual([t for t in texts if t not in de], [])
        for t in ("Skip", "Back", "Next", "Get started"):
            self.assertIn(t, de)

    def test_slash_step_names_real_commands(self):
        chips = next(s["chips"] for s in steps() if s.get("chips"))
        names = re.findall(r"\{ name: '(\w+)'", SRC)
        self.assertEqual([c for c in chips if c[1:] not in names], [])


class IntroSettingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.app = test_server.serve(make_server("127.0.0.1", 0, cls.tmp.name))
        cls.base = f"http://127.0.0.1:{cls.app.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.app.shutdown()
        cls.app.server_close()
        cls.tmp.cleanup()

    call = test_server.SunakTest.call.__func__

    def test_seen_once_per_profile(self):
        self.assertIs(self.call("GET", "/api/settings")["intro_seen"], False)
        self.assertIs(self.call("PUT", "/api/settings", {"intro_seen": True})["intro_seen"], True)
        self.assertIs(self.call("GET", "/api/settings")["intro_seen"], True)
        with self.assertRaises(Exception):  # a text is not a flag
            self.call("PUT", "/api/settings", {"intro_seen": "yes"})


if __name__ == "__main__":
    unittest.main()
