"""Slash commands of the chat (/termin, /event, …): `slashParse` and `slashSuggest` of app.js, run with node (skipped without node),
and the German texts for the command list.
Run:  python -m unittest discover tests"""

import json
import re
import shutil
import subprocess
import unittest

from sunak.server import STATIC

import test_i18n

NODE = shutil.which("node")
SRC = (STATIC / "app.js").read_text(encoding="utf-8")
PART = re.search(r"// BEGIN slashCommands[^\n]*\n(.*?)// END slashCommands", SRC, re.S).group(1)


def run_node(expr, data):
    script = PART + f"\nconst cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));\nconsole.log(JSON.stringify(cases.map((t) => {expr})));"
    res = subprocess.run([NODE, "-e", script], input=json.dumps(data), capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


@unittest.skipUnless(NODE, "node is not installed")
class SlashCommandsTest(unittest.TestCase):
    def test_parse(self):
        cases = ["/termin morgen 10 Uhr Zahnarzt", "/EVENT   dentist tomorrow  ", "/hilfe", "/help", "/foo", "/foo bar", "hello /termin",
                 "/etc/hosts", "/Users/max/x.txt lesen", "/", "/web\nzwei Zeilen", "  /heute", "//termin"]
        got = run_node("slashParse(t)", cases)
        names = [(g["cmd"] or {}).get("name") if g else None for g in got]
        self.assertEqual(names, ["termin", "termin", "hilfe", "hilfe", None, None, None, None, None, None, "web", "heute", None])
        self.assertEqual(got[0]["arg"], "morgen 10 Uhr Zahnarzt")
        self.assertEqual(got[1]["arg"], "dentist tomorrow")
        self.assertEqual(got[4]["word"], "foo")  # unknown name: the app says so
        self.assertEqual(got[5]["arg"], "bar")
        self.assertEqual(got[10]["arg"], "zwei Zeilen")
        for i in (6, 7, 8, 9, 12):  # not a command at all: a normal message
            self.assertIsNone(got[i], cases[i])

    def test_suggest(self):
        got = run_node("slashSuggest(t).map((c) => c.name)", ["/", "/te", "/ev", "/s", "/zzz", "/termin ", "hi", "/mo", "/h"])
        self.assertEqual(len(got[0]), 14)
        self.assertEqual(got[1], ["termin"])
        self.assertEqual(got[2], ["termin"])  # by the English name
        self.assertEqual(got[3], ["suche", "zusammenfassen"])  # "search" and "summarize" count as well
        self.assertEqual(got[4:7], [[], [], []])
        self.assertEqual(got[7], ["modell"])
        self.assertEqual(got[8], ["heute", "hilfe"])

    def test_word_follows_the_typed_start(self):
        self.assertEqual(run_node("slashWord(SLASH[0], t)", ["/te", "/ev", "/"]), ["termin", "event", "termin"])

    def test_the_commands(self):
        got = run_node("SLASH.map((c) => [c.name, c.alias])", [0])[0]
        names = [n for n, _ in got]
        self.assertEqual(names, ["termin", "mail", "bild", "web", "heute", "woche", "wissen", "modell", "persona", "neu", "export", "suche", "zusammenfassen", "hilfe"])
        for n, alias in got:  # every German name has an English one, unless the word is the same
            self.assertTrue(alias or n in ("mail", "web", "persona", "export"), n)

    def test_texts_are_translated(self):
        de = test_i18n.load_lang("de")[1]
        got = run_node("SLASH.flatMap((c) => [c.desc, c.arg])", [0])[0]
        self.assertEqual([t for t in got if t and t not in de], [])


if __name__ == "__main__":
    unittest.main()
