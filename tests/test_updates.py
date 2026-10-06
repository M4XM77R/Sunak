"""Tests for the update check and the Update button (sunak/updates.py, /api/update)."""

import contextlib
import io
import json
import os
import platform
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
import unittest.mock
import urllib.error
import urllib.request
from pathlib import Path

from sunak import updates
from sunak.server import make_server

GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_NOSYSTEM="1")


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, check=True, capture_output=True,
                          text=True).stdout.strip()


def commit(repo, name):
    (Path(repo) / name).write_text(name, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", name)
    return git(repo, "rev-parse", "HEAD")


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class UpdateCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        t = Path(self.tmp.name)
        self.remote, self.clone, self.other = t / "remote.git", t / "clone", t / "other"
        git(t, "init", "-q", "--bare", str(self.remote))
        git(t, "clone", "-q", str(self.remote), str(self.clone))
        git(self.clone, "checkout", "-q", "-b", "main")
        self.first = commit(self.clone, "a.txt")
        git(self.clone, "push", "-q", "-u", "origin", "main")
        git(t, "clone", "-q", "-b", "main", str(self.remote), str(self.other))

    def tearDown(self):
        self.tmp.cleanup()

    def push_new_commit(self):
        commit(self.other, "b.txt")
        git(self.other, "push", "-q", "origin", "main")

    def test_clone_up_to_date_then_behind(self):
        self.assertEqual(updates.check(self.clone), 0)
        self.push_new_commit()
        self.assertEqual(updates.check(self.clone), 1)
        self.assertEqual(updates.update_command(self.clone)[-2:], ["pull", "--ff-only"])

    def test_installed_copy_uses_remembered_clone_and_commit(self):
        home = Path(self.tmp.name) / "home"
        app = home / "app"
        app.mkdir(parents=True)
        # PowerShell writes source.txt with a BOM
        (home / "source.txt").write_text(str(self.clone), encoding="utf-8-sig")
        self.assertEqual(updates.repo_dir(app), self.clone)
        self.assertEqual(updates.check(app), 0)
        self.push_new_commit()
        git(self.clone, "pull", "-q")  # the clone is current, but the installed copy is not
        (app / ".commit").write_text(self.first + "\n", encoding="utf-8")
        self.assertEqual(updates.check(app), 1)
        (app / ".commit").write_text("garbage", encoding="utf-8")  # unknown commit: fall back to the clone's HEAD
        self.assertEqual(updates.check(app), 0)

    def test_failures_are_silent(self):
        self.assertIsNone(updates.check(Path(self.tmp.name) / "nothing"))
        with unittest.mock.patch("subprocess.run", side_effect=FileNotFoundError("git")):
            self.assertIsNone(updates.check(self.clone))
        git(self.clone, "remote", "set-url", "origin", str(Path(self.tmp.name) / "gone.git"))  # offline
        self.assertIsNone(updates.check(self.clone))
        git(self.clone, "remote", "set-url", "origin", str(self.remote))
        git(self.clone, "checkout", "-q", "-b", "local-only")  # no upstream branch
        self.assertIsNone(updates.check(self.clone))

    def test_apply_pulls_and_restarts(self):
        self.push_new_commit()
        data = Path(self.tmp.name) / "data"
        data.mkdir()
        with unittest.mock.patch("sunak.desktop.running", return_value=None), \
                unittest.mock.patch("time.sleep"), contextlib.redirect_stdout(io.StringIO()), \
                unittest.mock.patch.object(updates, "_launch") as launch:
            self.assertTrue(updates.apply(7123, "0.0.0.0", data, root=self.clone))
        self.assertTrue((self.clone / "b.txt").exists())
        cmd = launch.call_args[0][0]
        self.assertEqual(cmd[1:], ["-m", "sunak", "--no-browser", "--host", "0.0.0.0", "--port", "7123",
                                   "--data-dir", str(data)])
        self.assertEqual(updates.pop_result(data), {"ok": True, "error": ""})
        self.assertIsNone(updates.pop_result(data))  # shown once

    def test_apply_reports_a_failed_update(self):
        data = Path(self.tmp.name) / "data"
        data.mkdir()
        (self.clone / "a.txt").write_text("local change", encoding="utf-8")
        git(self.clone, "commit", "-q", "-am", "diverge")
        self.push_new_commit()  # now the clone cannot fast-forward
        with unittest.mock.patch("sunak.desktop.running", return_value=None), \
                unittest.mock.patch("time.sleep"), contextlib.redirect_stdout(io.StringIO()), \
                unittest.mock.patch.object(updates, "_launch") as launch:
            self.assertFalse(updates.apply(7123, "127.0.0.1", data, root=self.clone))
        launch.assert_called_once()  # Sunak starts again anyway
        result = updates.pop_result(data)
        self.assertFalse(result["ok"])
        self.assertTrue(result["error"])


class LauncherTest(unittest.TestCase):
    @unittest.skipIf(platform.system() == "Windows", "the launcher is sunak.cmd there")
    def test_finds_the_launcher_of_this_copy_only(self):
        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.dict(os.environ, {"HOME": tmp}):
            app = Path(tmp) / ".sunak" / "app"
            app.mkdir(parents=True)
            self.assertIsNone(updates.update_command(app))
            bin_dir = Path(tmp) / ".local" / "bin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "sunak").write_text(f'#!/usr/bin/env bash\nAPP_DIR="{Path(tmp) / "other"}"\n', encoding="utf-8")
            self.assertIsNone(updates.update_command(app))
            (bin_dir / "sunak").write_text(f'#!/usr/bin/env bash\nAPP_DIR="{app}"\n', encoding="utf-8")
            self.assertEqual(updates.update_command(app), [str(bin_dir / "sunak"), "update"])


class UpdateApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.srv = make_server("127.0.0.1", 0, self.tmp.name)
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", "X-Requested-With": "sunak"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

    def wait_for_check(self):
        app = self.srv.RequestHandlerClass.app
        for _ in range(100):
            if not app._checking:
                return
            time.sleep(0.05)

    def test_hint_setting_and_result(self):
        with unittest.mock.patch.object(updates, "check", return_value=3) as check, \
                unittest.mock.patch.object(updates, "update_command", return_value=["true"]):
            self.call("GET", "/api/update")  # starts the background check
            self.wait_for_check()
            u = self.call("GET", "/api/update")
            self.assertEqual((u["available"], u["behind"], u["can_update"], u["enabled"]), (True, 3, True, True))
            self.assertEqual(check.call_count, 1)  # not again within CHECK_EVERY
            self.call("PUT", "/api/settings", {"check_updates": False})
            u = self.call("GET", "/api/update")
            self.assertEqual((u["available"], u["enabled"]), (False, False))
        (Path(self.tmp.name) / updates.RESULT_FILE).write_text('{"ok": false, "error": "no network"}', encoding="utf-8")
        with unittest.mock.patch.object(updates, "update_command", return_value=None):
            u = self.call("GET", "/api/update")
        self.assertEqual(u["result"], {"ok": False, "error": "no network"})
        self.assertFalse(u["can_update"])
        self.assertIn("instance", self.call("GET", "/api/status"))

    def test_failed_check_is_silent(self):
        with unittest.mock.patch.object(updates, "check", return_value=None):
            self.call("GET", "/api/update")
            self.wait_for_check()
            u = self.call("GET", "/api/update")
        self.assertEqual((u["available"], u["behind"]), (False, 0))

    def test_update_button_starts_helper_and_stops_server(self):
        with unittest.mock.patch.object(updates, "update_command", return_value=None):
            with self.assertRaises(urllib.error.HTTPError) as e:
                self.call("POST", "/api/update", {})
            self.assertEqual(e.exception.code, 400)
        with unittest.mock.patch.object(updates, "update_command", return_value=["true"]), \
                unittest.mock.patch.object(updates, "spawn_helper") as spawn:
            self.assertEqual(self.call("POST", "/api/update", {}), {"ok": True})
            self.thread.join(5)
        self.assertFalse(self.thread.is_alive())  # the server stopped for the helper
        spawn.assert_called_once_with(self.srv.server_address[1], "127.0.0.1", Path(self.tmp.name))


if __name__ == "__main__":
    unittest.main()
