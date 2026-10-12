"""Update check for a copy without a git clone (the Windows installer's download): version comparison with the public repo."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sunak import __version__, updates

INIT = 'x = 1\n__version__ = "%s"\n'
LOG = "# Changelog\n\n## [9.0.0] – 2026-10-12\n\n### Fixed\n- new\n\n## [%s] – 2026-10-11\n\n### Added\n- old\n"


def fake_raw(version, seen=None):
    def raw(branch, path, timeout=15):
        if seen is not None:
            seen.append((branch, path))
        if path.endswith("__init__.py"):
            return INIT % version if version else None
        return LOG % __version__
    return raw


class DownloadCheckTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)  # no .git, no source file

    def tearDown(self):
        self.root.cleanup()

    def inspect(self, version, channel=None, seen=None):
        with mock.patch.object(updates, "_raw", fake_raw(version, seen)):
            return updates.inspect(Path(self.root.name) / "app", channel)

    def test_newer_version_is_an_update_with_changelog(self):
        r = self.inspect("9.0.0")
        self.assertEqual((r["behind"], r["version"], r["error"]), (1, "9.0.0", ""))
        self.assertEqual([e["version"] for e in r["changelog"]], ["9.0.0"])

    def test_same_version_is_up_to_date(self):
        r = self.inspect(__version__)
        self.assertEqual((r["behind"], r["error"]), (0, ""))

    def test_unreachable_is_unknown_not_clone_error(self):
        r = self.inspect(None)
        self.assertIsNone(r["behind"])
        self.assertEqual(r["error"], "no_remote")

    def test_dev_version_of_the_remote(self):
        self.assertEqual(self.inspect("9.0.0-dev.3")["behind"], 1)
        self.assertEqual(self.inspect("1.0.0-dev.1")["behind"], 0)  # older than what is installed

    def test_channel_picks_branch(self):
        seen = []
        self.inspect("9.0.0", "dev", seen)
        self.assertEqual({b for b, _ in seen}, {"dev"})
        seen.clear()
        self.inspect("9.0.0", None, seen)
        self.assertEqual({b for b, _ in seen}, {"main"})


if __name__ == "__main__":
    unittest.main()
