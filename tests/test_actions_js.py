"""The chat's action blocks (```sunak-event``` / ```sunak-mail``` / ```sunak-doc```): `parseActions` of app.js, run with node (skipped without node).
Run:  python -m unittest discover tests"""

import json
import re
import shutil
import subprocess
import unittest

from sunak.server import STATIC

NODE = shutil.which("node")
SRC = (STATIC / "app.js").read_text(encoding="utf-8")
PART = re.search(r"// BEGIN parseActions[^\n]*\n(.*?)// END parseActions", SRC, re.S).group(1)

EV = '{"summary": "Zahnarzt", "start": "2026-10-09T10:00"}'
F = "```"
CASES = [
    # (text, text left over, blocks)
    (f"Klar.\n{F}sunak-event\n{EV}\n{F}", "Klar.", [("event", EV)]),
    (f"Klar.\n{F}sunak-mail\n{{\"body\": \"x\"}}\n{F}\nFertig", "Klar.\nFertig", [("mail", '{"body": "x"}')]),
    (f"Text\n{F}python\nprint(1)\n{F}", f"Text\n{F}python\nprint(1)\n{F}", []),
    # a document block holds Markdown (with a table), never JSON
    (f"Hier.\n{F}sunak-doc\n# Titel\n\n| A | B |\n|---|---|\n| 1 | 2 |\n{F}", "Hier.", [("doc", "# Titel\n\n| A | B |\n|---|---|\n| 1 | 2 |")]),
    (f"Hier.\n{F}sunak-do", "Hier.", []), (f"Hier.\n{F}sunak-doc\n# Tit", "Hier.", []),
    # a block inside another fence is an example, not a request
    (f"So sieht es aus:\n````markdown\n{F}sunak-event\n{EV}\n{F}\n````", f"So sieht es aus:\n````markdown\n{F}sunak-event\n{EV}\n{F}\n````", []),
    (f"{F}text\n{F}sunak-event\n{EV}\n{F}", f"{F}text\n{F}sunak-event\n{EV}\n{F}", []),
    # while streaming: an open block and a dangling start are hidden
    (f"Klar.\n{F}sunak-event\n{{\"summ", "Klar.", []),
    (f"Klar.\n{F}sunak-ev", "Klar.", []), (f"Klar.\n{F}", "Klar.", []), (f"Klar.\n{F}sun", "Klar.", []), ("Klar.\n``", "Klar.", []),
    (f"Klar.\n{F}sunak-event", "Klar.", []),
    # an ordinary closing fence at the end is not dangling
    (f"{F}js\nlet a = 1;\n{F}", f"{F}js\nlet a = 1;\n{F}", []),
    ("Nur Text mit `code`", "Nur Text mit `code`", []),
]


@unittest.skipUnless(NODE, "node is not installed")
class ParseActionsTest(unittest.TestCase):
    def test_cases(self):
        script = PART + "\nconst cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));\nconsole.log(JSON.stringify(cases.map((t) => parseActions(t))));"
        res = subprocess.run([NODE, "-e", script], input=json.dumps([c[0] for c in CASES]), capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(res.returncode, 0, res.stderr)
        for (text, rest, blocks), got in zip(CASES, json.loads(res.stdout)):
            self.assertEqual(got["text"], rest, text)
            self.assertEqual([(b["kind"], b["json"]) for b in got["blocks"]], blocks, text)


if __name__ == "__main__":
    unittest.main()
