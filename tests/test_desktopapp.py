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

    def test_version_comparison(self):
        self.assertEqual(d.tag_version("desktop-v1.10.0"), (1, 10, 0))
        self.assertTrue(d.is_newer("desktop-v1.10.0", "desktop-v1.9.3"))  # numbers, not text
        self.assertFalse(d.is_newer("desktop-v1.1.0", "desktop-v1.1.0"))
        self.assertFalse(d.is_newer("desktop-v1.1.0", "desktop-v2.0.0"))
        self.assertTrue(d.is_newer("desktop-v1.1.0", ""))  # no record: renew once

    def test_update_does_nothing_without_an_installed_app(self):
        with mock.patch.object(d, "installed", return_value=False), mock.patch.object(d, "find_package") as find, \
                mock.patch.object(d, "install") as inst:
            self.assertEqual(d.update(), "none")
            self.assertEqual(d.pending_update(), "")
            find.assert_not_called()
            inst.assert_not_called()

    def test_update_only_when_newer_and_closed(self):
        pkg = {"tag": "desktop-v1.2.0", "name": "x.AppImage", "url": "https://github.com/x", "sums": None}
        with mock.patch.object(d, "installed", return_value=True), mock.patch.object(d, "find_package", return_value=pkg), \
                mock.patch.object(d, "install") as inst, mock.patch.object(d, "running", return_value=False):
            with mock.patch.object(d, "installed_tag", return_value="desktop-v1.2.0"):
                self.assertEqual(d.update(), "none")
            inst.assert_not_called()
            with mock.patch.object(d, "installed_tag", return_value="desktop-v1.1.0"):
                with mock.patch.object(d, "running", return_value=True):
                    self.assertEqual(d.update(), "running")
                inst.assert_not_called()
                self.assertEqual(d.update(), "updated")
                inst.assert_called_once()

    def test_corrupt_version_file_and_failed_lookup_do_not_break_anything(self):
        with tempfile.TemporaryDirectory() as t, mock.patch.dict("os.environ", {"SUNAK_HOME": t}):
            (Path(t) / "desktop-version").write_bytes(b"\xff\xfe\x00\x80")
            self.assertEqual(d.installed_tag(), "")
        calls = []
        with mock.patch.object(d, "installed", return_value=True), \
                mock.patch.object(d, "find_package", side_effect=lambda: calls.append(1) or (_ for _ in ()).throw(d.DesktopError("offline"))):
            d._pending.update(at=0.0, tag="")
            self.assertEqual(d.pending_update(), "")
            self.assertEqual(d.pending_update(), "")  # the failure is remembered: no second request
        self.assertEqual(len(calls), 1)

    def test_no_release_is_reported(self):
        with mock.patch.object(d, "installed", return_value=True), mock.patch.object(d, "find_package", return_value=None):
            self.assertEqual(d.update(), "no_release")

    def test_auto_update_never_fails_the_update(self):
        import io
        from contextlib import redirect_stderr, redirect_stdout
        from sunak import __main__ as cli
        with mock.patch.object(d, "update", side_effect=d.DesktopError("boom")), redirect_stdout(io.StringIO()), \
                redirect_stderr(io.StringIO()) as err:
            self.assertEqual(cli.desktop_command(["update", "--auto"]), 0)
        self.assertIn("boom", err.getvalue())

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
