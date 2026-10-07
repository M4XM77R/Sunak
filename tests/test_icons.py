"""The interface draws its own icons (static/icons.js) and uses no emojis. Run:  python -m unittest discover tests"""

import re
import unittest

from sunak.server import STATIC

EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u2712\u2714-\u27BF\u2B00-\u2BFF\uFF0B\ufe0f]")  # a plain checkmark is text, not an emoji


class IconsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.icons = set(re.findall(r"^\s*'?([\w-]+)'?: '<", (STATIC / "icons.js").read_text(encoding="utf-8"), re.M))
        cls.html = (STATIC / "index.html").read_text(encoding="utf-8")
        cls.js = (STATIC / "app.js").read_text(encoding="utf-8")

    def test_every_used_icon_exists(self):
        self.assertGreater(len(self.icons), 40)
        used = set(re.findall(r'data-i="([\w-]+)"', self.html)) | set(re.findall(r"\bicon\('([\w-]+)'", self.js))
        used |= set(re.findall(r"STEP_ICONS = \{([^}]*)\}", self.js)[0].replace("'", "").replace(":", ",").split(",")[1::2])
        used = {u.strip() for u in used if u.strip()}
        self.assertEqual(sorted(used - self.icons), [])

    def test_page_loads_icons_before_the_app(self):
        self.assertLess(self.html.index('src="/icons.js"'), self.html.index('src="/app.js"'))

    def test_no_emojis_in_the_interface(self):
        for name, text in (("index.html", self.html), ("app.js", self.js)):
            lines = [(i, l.strip()) for i, l in enumerate(text.splitlines(), 1) if EMOJI.search(l)]
            lines = [x for x in lines if "'🙂'" not in x[1]]  # the old profile default, filtered out in the code
            self.assertEqual(lines, [], name)
        for lang in STATIC.glob("lang-*.js"):
            keys = re.findall(r'^"((?:[^"\\]|\\.)*)": ', lang.read_text(encoding="utf-8"), re.M)
            self.assertEqual([k for k in keys if EMOJI.search(k)], [], lang.name)


if __name__ == "__main__":
    unittest.main()
