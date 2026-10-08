"""The sunak command line: help for all commands from one list, details per command, typo hints."""

import contextlib
import inspect
import io
import re
import unittest
from unittest import mock

from sunak import __main__ as cli


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class CliHelpTest(unittest.TestCase):
    def test_overview_lists_every_command_and_option(self):
        for argv in (["-h"], ["--help"], ["help"], ["--port", "8123", "-h"]):
            code, out, _ = run(*argv)
            self.assertEqual(code, 0, argv)
            self.assertNotIn("\033[", out)  # no colors outside a terminal
            for name, c in cli.COMMANDS.items():
                self.assertRegex(out, rf"\n  {name} +{re.escape(c['summary'])}", name)
                self.assertIn(c["example"], out)
            for group in cli.GROUPS:
                self.assertIn(f"\n{group}\n", out)
            for opt in ("--port N", "--host ADDRESS", "--data-dir PATH", "--no-browser", "--version"):
                self.assertIn(opt, out)
            self.assertIn("SUNAK_DATA", out)
            self.assertIn(cli.DOCS, out)
        self.assertEqual({c["group"] for c in cli.COMMANDS.values()}, set(cli.GROUPS))

    def test_layout_follows_the_terminal_width(self):
        wide = cli.help_text(width=200).splitlines()
        narrow = cli.help_text(width=60).splitlines()
        self.assertTrue(any(line.startswith("  stop ") and line.endswith("sunak stop") for line in wide))
        i = next(i for i, line in enumerate(narrow) if line.startswith("  stop "))
        self.assertEqual(narrow[i + 1].strip(), "sunak stop")
        self.assertGreater(len(narrow), len(wide))

    def test_every_command_has_details_and_is_handled(self):
        handled = inspect.getsource(cli.run_command) + inspect.getsource(cli.main)
        for name, c in cli.COMMANDS.items():
            for argv in ([name, "-h"], [name, "--help"], ["help", name]):
                code, out, _ = run(*argv)
                self.assertEqual(code, 0, argv)
                self.assertIn(f"Usage: sunak {name}", out)
                self.assertIn(f"Example: {c['example']}", out)
            self.assertIn(f'"{name}"', handled, f"{name} is in COMMANDS but nothing runs it")
        self.assertIn("--with-models", run("uninstall", "-h")[1])
        self.assertIn("--port N", run("stop", "-h")[1])
        self.assertIn("status", run("help", "autostart")[1])

    def test_typos_get_a_hint(self):
        for argv, hint in ((["stpo"], "Did you mean 'stop'?"), (["--prot", "9"], "Did you mean '--port'?"),
                           (["help", "unistall"], "Did you mean 'uninstall'?"), (["xyzzy"], "Unknown command 'xyzzy'.")):
            code, out, err = run(*argv)
            self.assertEqual((code, out), (2, ""), argv)
            self.assertIn(hint, err)
            self.assertIn("sunak -h", err)

    def test_no_color_without_a_terminal(self):
        self.assertFalse(cli._color())  # stdout of the tests is not a terminal

    def test_no_console_at_all(self):
        # pythonw.exe (desktop icon, autostart on Windows) starts Sunak with sys.stdout = None
        with mock.patch.object(cli.sys, "stdout", None):
            self.assertFalse(cli._color())


if __name__ == "__main__":
    unittest.main()
