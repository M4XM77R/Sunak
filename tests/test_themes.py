"""Themes: the same names in CSS, JavaScript and the server, every color set, readable contrast."""

import json
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from sunak.server import THEMES, make_server

STATIC = Path(__file__).resolve().parent.parent / "sunak" / "static"
COLORS = ("bg", "panel", "panel-2", "border", "text", "muted", "code-bg", "danger", "ok", "accent", "accent-text")


def css_themes():
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    out = {}
    for name, body in re.findall(r'^\[data-theme="([a-z-]+)"\]\s*\{([^}]*)\}', css, re.M):
        out[name] = dict(re.findall(r"--([a-z0-9-]+):\s*([^;]+);", body))
    return out


def luminance(hex_color):
    h = hex_color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    def lin(c):
        c = int(c, 16) / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(h[i:i + 2]) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class ThemeTest(unittest.TestCase):
    def test_same_themes_everywhere(self):
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        js_ids = re.findall(r"\{ id: '([a-z-]+)', name:", js)
        self.assertEqual(tuple(js_ids), THEMES)
        self.assertEqual(tuple(css_themes()), THEMES)

    def test_every_color_is_set(self):
        for name, vars_ in css_themes().items():
            for c in COLORS:
                self.assertRegex(vars_.get(c, ""), r"^#[0-9a-fA-F]{3,6}$", f"{name}: --{c}")

    def test_contrast(self):
        for name, v in css_themes().items():
            with self.subTest(theme=name):
                for surface in ("bg", "panel", "panel-2", "code-bg"):
                    self.assertGreaterEqual(contrast(v["text"], v[surface]), 7, f"text on {surface}")
                    self.assertGreaterEqual(contrast(v["muted"], v[surface]), 4.5, f"muted on {surface}")
                for fg in ("accent", "danger", "ok"):
                    for surface in ("bg", "panel"):
                        self.assertGreaterEqual(contrast(v[fg], v[surface]), 4.5, f"{fg} on {surface}")
                self.assertGreaterEqual(contrast(v["accent-text"], v["accent"]), 4.5, "button text")

    def test_server_accepts_only_known_themes(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            srv = make_server("127.0.0.1", 0, tmp)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            try:
                def put(body):
                    req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/api/settings", method="PUT",
                                                 data=json.dumps(body).encode(),
                                                 headers={"Content-Type": "application/json", "X-Requested-With": "sunak"})
                    with urllib.request.urlopen(req, timeout=10) as r:
                        return json.loads(r.read())
                self.assertEqual(put({"theme": "cyberpunk", "accent": ""})["theme"], "cyberpunk")
                self.assertEqual(put({"accent": "#38bdf8"})["accent"], "#38bdf8")
                for bad in ({"theme": "neon-pink"}, {"accent": "red; background:url(x)"}, {"accent": "#12345"}):
                    with self.assertRaises(urllib.error.HTTPError) as e:
                        put(bad)
                    self.assertEqual(e.exception.code, 400)
            finally:
                srv.shutdown()
                srv.server_close()


if __name__ == "__main__":
    unittest.main()
