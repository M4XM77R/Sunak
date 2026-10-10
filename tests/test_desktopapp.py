"""The optional desktop app: choosing the package, the command, the one-time hint, the API."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sunak import desktopapp as d

RELS = [
    {"tag_name": "v1.0.0", "assets": [{"name": "x.AppImage", "browser_download_url": "http://x/old"}]},
    {"tag_name": "desktop-v1.2.0", "draft": True, "assets": [{"name": "a.AppImage", "browser_download_url": "http://x/draft"}]},
    {"tag_name": "desktop-v1.1.0", "assets": [
        {"name": "Sunak_1.1.0_amd64.AppImage", "browser_download_url": "http://x/linux"},
        {"name": "Sunak_1.1.0_aarch64.dmg", "browser_download_url": "http://x/mac"},
        {"name": "Sunak_1.1.0_x64-setup.exe", "browser_download_url": "http://x/win"}]},
]


class PickAssetTest(unittest.TestCase):
    def test_picks_the_package_of_the_newest_real_desktop_release(self):
        self.assertEqual(d.pick_asset(RELS, "linux", "x86_64")["url"], "http://x/linux")
        self.assertEqual(d.pick_asset(RELS, "mac", "arm64")["url"], "http://x/mac")
        self.assertEqual(d.pick_asset(RELS, "windows", "amd64")["tag"], "desktop-v1.1.0")

    def test_no_package(self):
        self.assertIsNone(d.pick_asset(RELS, "linux", "aarch64"))  # not built
        self.assertIsNone(d.pick_asset(RELS, "mac", "x86_64"))
        self.assertIsNone(d.pick_asset([], "linux", "x86_64"))
        self.assertIsNone(d.pick_asset(RELS[:2], "linux", "x86_64"))
        self.assertIsNone(d.pick_asset({"message": "rate limit"}, "linux", "x86_64"))

    def test_install_without_release_says_so(self):
        with mock.patch.object(d, "supported", return_value=True), mock.patch.object(d, "find_package", return_value=None):
            with self.assertRaises(d.DesktopError):
                d.install()

    def test_hint_is_shown_once_per_kind(self):
        with tempfile.TemporaryDirectory() as t, mock.patch.object(d, "supported", return_value=True), \
                mock.patch.object(d, "installed", return_value=False):
            self.assertTrue(d.notice_pending(t, "cli"))
            d.mark_notice(t, "cli")
            self.assertFalse(d.notice_pending(t, "cli"))
            self.assertTrue(d.notice_pending(t, "gui"))
            self.assertTrue((Path(t) / ".desktop-notice-cli").exists())


if __name__ == "__main__":
    unittest.main()
