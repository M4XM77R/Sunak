"""The optional desktop app: choosing the package, the command, the one-time hint, the API."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sunak import desktopapp as d

RELS = [
    {"tag_name": "v1.0.0", "assets": [{"name": "x.AppImage", "browser_download_url": "https://github.com/x/old"}]},
    {"tag_name": "desktop-v1.2.0", "draft": True, "assets": [{"name": "a.AppImage", "browser_download_url": "https://github.com/x/draft"}]},
    {"tag_name": "desktop-v1.1.0", "assets": [
        {"name": "Sunak_1.1.0_amd64.AppImage", "browser_download_url": "https://github.com/x/linux"},
        {"name": "Sunak_1.1.0_aarch64.dmg", "browser_download_url": "https://github.com/x/mac"},
        {"name": "Sunak_1.1.0_x64-setup.exe", "browser_download_url": "https://github.com/x/win"}]},
]


class PickAssetTest(unittest.TestCase):
    def test_picks_the_package_of_the_newest_real_desktop_release(self):
        self.assertEqual(d.pick_asset(RELS, "linux", "x86_64")["url"], "https://github.com/x/linux")
        self.assertEqual(d.pick_asset(RELS, "mac", "arm64")["url"], "https://github.com/x/mac")
        self.assertEqual(d.pick_asset(RELS, "windows", "amd64")["tag"], "desktop-v1.1.0")

    def test_no_package(self):
        self.assertIsNone(d.pick_asset(RELS, "linux", "aarch64"))  # not built
        self.assertIsNone(d.pick_asset(RELS, "mac", "x86_64"))
        self.assertIsNone(d.pick_asset([], "linux", "x86_64"))
        self.assertIsNone(d.pick_asset(RELS[:2], "linux", "x86_64"))
        self.assertIsNone(d.pick_asset({"message": "rate limit"}, "linux", "x86_64"))

    def test_downloads_only_from_github_and_names_are_plain_file_names(self):
        rel = [{"tag_name": "desktop-v1", "assets": [{"name": "a.AppImage", "browser_download_url": "http://github.com/a"}]}]
        self.assertIsNone(d.pick_asset(rel, "linux", "x86_64"))  # not https
        rel[0]["assets"][0]["browser_download_url"] = "https://evil.example/a"
        self.assertIsNone(d.pick_asset(rel, "linux", "x86_64"))
        rel[0]["assets"][0].update(name="../../evil.AppImage", browser_download_url="https://github.com/a")
        self.assertEqual(d.pick_asset(rel, "linux", "x86_64")["name"], "evil.AppImage")

    def test_checksum_is_required_and_compared(self):
        import hashlib
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "p.AppImage"
            f.write_bytes(b"package")
            good = hashlib.sha256(b"package").hexdigest()

            class R:
                def __init__(self, text): self.text = text
                def __enter__(self): return self
                def __exit__(self, *a): return False
                def read(self, n): return self.text.encode()
            with self.assertRaises(d.DesktopError):
                d._verify(f, "p.AppImage", None)
            with mock.patch.object(d, "_get", return_value=R(f"{'0' * 64}  p.AppImage\n")), self.assertRaises(d.DesktopError):
                d._verify(f, "p.AppImage", "https://github.com/s")
            with mock.patch.object(d, "_get", return_value=R(f"{good}  p.AppImage\n")):
                d._verify(f, "p.AppImage", "https://github.com/s")

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
