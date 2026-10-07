"""CHANGELOG.md: the parser, the versions between two releases, the file in the repository, and `sunak changelog`."""

import contextlib
import io
import unittest
import unittest.mock
from pathlib import Path

from sunak import __main__ as cli
from sunak import __version__, changelog, updates

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = """# Changelog

Intro text, ignored.

## [0.3.0] – 2026-10-07

### Added
- three `code`

## [0.2.1]
- two point one

## [0.2.0] - 2026-10-06
- two

## [0.1.0] – kaputt
- one

## [0.2.0] – 2026-01-01
- duplicate, ignored
"""


def run(*argv, tty=False, answer=""):
    out = io.StringIO()
    stdin = unittest.mock.MagicMock()
    stdin.isatty.return_value = tty
    with contextlib.redirect_stdout(out), unittest.mock.patch("sys.stdin", stdin), \
            unittest.mock.patch("sys.stdout.isatty", return_value=tty, create=True), \
            unittest.mock.patch("builtins.input", return_value=answer) as ask:
        code = cli.changelog_command(list(argv))
    return code, out.getvalue(), ask


class ParserTest(unittest.TestCase):
    def test_parse(self):
        entries = changelog.parse(SAMPLE)
        self.assertEqual([e["version"] for e in entries], ["0.3.0", "0.2.1", "0.2.0", "0.1.0"])
        self.assertEqual([e["date"] for e in entries], ["2026-10-07", "", "2026-10-06", ""])  # only real dates
        self.assertEqual(entries[0]["body"], "### Added\n- three `code`")
        self.assertEqual(entries[2]["body"], "- two")  # the second 0.2.0 is ignored

    def test_between(self):
        entries = changelog.parse(SAMPLE)
        pick = lambda cur, new="": [e["version"] for e in changelog.between(entries, cur, new)]
        self.assertEqual(pick("0.2.0"), ["0.3.0", "0.2.1"])
        self.assertEqual(pick("0.2.0", "0.2.1"), ["0.2.1"])
        self.assertEqual(pick("0.3.0"), [])
        self.assertEqual(pick("0.1.0", "0.2.0"), ["0.2.0"])
        self.assertEqual(pick("0.0.1"), ["0.3.0", "0.2.1", "0.2.0", "0.1.0"])
        self.assertEqual(pick("0.9.0", ""), [])
        self.assertEqual(changelog.between(changelog.parse("## [0.10.0]\n- a\n## [0.9.0]\n- b\n"), "0.9.0"),
                         [{"version": "0.10.0", "date": "", "body": "- a"}])  # 0.10 is newer than 0.9

    def test_missing_or_broken_input_gives_no_entries(self):
        for bad in (None, "", "   \n", "no headings at all", b"## [0.1.0]\n", 42, "## [x.y.z]\n- a", "## 1.2\n- a", "x" * (changelog.MAX_CHARS + 1)):
            self.assertEqual(changelog.parse(bad), [], repr(bad)[:30])
        self.assertEqual(changelog.parse("﻿## [1.0.0]\r\n- a\r\n")[0]["body"], "- a")  # BOM and Windows line ends

    def test_text_for_the_terminal(self):
        text = changelog.to_text(changelog.between(changelog.parse(SAMPLE), "0.2.0"))
        self.assertEqual(text, "Sunak 0.3.0 (2026-10-07)\nAdded:\n- three code\n\nSunak 0.2.1\n- two point one")

    def test_the_changelog_of_this_repository(self):
        entries = changelog.parse((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
        self.assertEqual(entries[0]["version"], __version__)  # every version has its entry, newest first
        keys = [changelog.version_key(e["version"]) for e in entries]
        self.assertEqual(keys, sorted(keys, reverse=True))
        self.assertTrue(all(e["body"] for e in entries))


class CliTest(unittest.TestCase):
    def inspect(self, behind, entries=(), version="9.9.9", error=""):
        return unittest.mock.patch.object(updates, "inspect", return_value={
            "behind": behind, "version": version, "changelog": list(entries), "error": error})

    ENTRY = {"version": "9.9.9", "date": "2030-01-01", "body": "- shiny"}

    def test_shows_the_changes_without_asking(self):
        with self.inspect(2, [self.ENTRY]):
            code, out, ask = run()
        self.assertEqual(code, 0)
        self.assertIn("Sunak 9.9.9 is available", out)
        self.assertIn("Sunak 9.9.9 (2030-01-01)\n- shiny", out)
        ask.assert_not_called()

    def test_up_to_date_shows_the_installed_version(self):
        with self.inspect(0):
            code, out, _ = run()
        self.assertEqual(code, 0)
        self.assertIn(f"Sunak {__version__} is up to date", out)
        self.assertIn(f"Sunak {__version__} (", out)  # its own entry from the local CHANGELOG.md

    def test_confirm_asks_and_declining_stops_the_update(self):
        with self.inspect(1, [self.ENTRY]):
            self.assertEqual(run("--confirm", tty=True, answer="n")[0], 3)
            self.assertEqual(run("--confirm", tty=True, answer="")[0], 3)
            code, out, ask = run("--confirm", tty=True, answer="y")
            self.assertEqual(code, 0)
            self.assertIn("- shiny", out)
            ask.assert_called_once()
            self.assertEqual(run("--confirm", tty=True, answer="Ja")[0], 0)

    def test_confirm_does_not_block_in_scripts(self):
        with self.inspect(1, [self.ENTRY]):
            code, out, ask = run("--confirm", tty=False)  # no terminal: autostart, the Update button, cron
            self.assertEqual(code, 0)
            self.assertIn("- shiny", out)
            ask.assert_not_called()
            code, _, ask = run("--confirm", "--yes", tty=True)
            self.assertEqual(code, 0)
            ask.assert_not_called()
            self.assertEqual(run("--confirm", "-y", tty=True)[0], 0)

    def test_no_changelog_never_stops_the_update(self):
        with self.inspect(3, []):
            code, out, ask = run("--confirm", tty=True, answer="y")
        self.assertEqual(code, 0)
        self.assertIn("No changelog available.", out)
        ask.assert_called_once()
        with self.inspect(None, error="no_remote"):  # offline: git pull will say what is wrong
            code, out, ask = run("--confirm", tty=True, answer="")
        self.assertEqual(code, 0)
        self.assertIn("No changelog available.", out)
        ask.assert_not_called()
        with self.inspect(None, error="no_remote"):
            self.assertEqual(run()[0], 1)  # plain `sunak changelog` reports the failure

    def test_up_to_date_update_is_not_asked(self):
        with self.inspect(0):
            code, out, ask = run("--confirm", tty=True)
        self.assertEqual((code, out), (0, ""))
        ask.assert_not_called()

    def test_unknown_option(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(run("--nope")[0], 2)


if __name__ == "__main__":
    unittest.main()
