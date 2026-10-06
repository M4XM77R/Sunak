"""Tests for `sunak uninstall`: the program goes, the data stays unless asked, twice is fine."""

import os
import platform
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from sunak import __main__ as cli, desktop, uninstall

POSIX = platform.system() != "Windows"


class UninstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.home = Path(self.tmp.name).resolve()
        env = {"HOME": str(self.home), "USERPROFILE": str(self.home), "APPDATA": str(self.home / "AppData"),
               "LOCALAPPDATA": str(self.home / "Local"), "XDG_CONFIG_HOME": str(self.home / ".config"),
               "XDG_DATA_HOME": str(self.home / ".local" / "share")}
        for p in (mock.patch.dict(os.environ, env), mock.patch.object(desktop, "running", return_value=None),
                  mock.patch.object(uninstall, "docker_projects", return_value=[]),
                  mock.patch.object(uninstall, "windows_path_remove", return_value=False),
                  mock.patch.object(uninstall, "_windows_desktop", return_value=[]),  # never the real desktop
                  mock.patch("shutil.which", return_value=None)):
            p.start()
            self.addCleanup(p.stop)
        for k in ("SUNAK_DATA", "SUNAK_HOME", "OLLAMA_MODELS"):
            os.environ.pop(k, None)
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        self.addCleanup(self.tmp.cleanup)
        self.data = self.home / ".sunak"
        self.out = []

    def install(self):
        """A fake install the way install.sh / install.ps1 lay it out."""
        self.data.mkdir(parents=True, exist_ok=True)
        (self.data / "sunak.db").write_text("chats")
        if POSIX:
            app = self.data / "app"
            (app / "sunak").mkdir(parents=True, exist_ok=True)
            (self.data / "source").write_text("/src")
            bin_dir = self.home / ".local" / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            (bin_dir / "sunak").write_text(f'#!/usr/bin/env bash\n# Sunak launcher.\nAPP_DIR="{app}"\n')
            (self.home / ".bashrc").write_text("alias ll='ls -l'\n\nexport PATH=\"/x:$PATH\"  # sunak PATH\n")
        else:
            inst = self.home / "Local" / "sunak"
            (inst / "app" / "sunak").mkdir(parents=True, exist_ok=True)
            for n in ("sunak.cmd", "update.ps1", "source.txt"):
                (inst / n).write_text("x")
        (self.home / "Desktop").mkdir(exist_ok=True)
        with mock.patch.object(desktop, "PKG_ROOT", self.home / "pkg"), mock.patch("subprocess.run"):
            desktop.enable_autostart()
            if platform.system() != "Windows":  # Windows icons need PowerShell; checked separately
                desktop.create_shortcut()

    def run_cli(self, *args, answers=()):
        answers = list(answers)

        def ask(q):
            self.out.append(q)
            if not answers:
                raise EOFError
            return answers.pop(0)
        return uninstall.main(list(args), ask=ask, out=self.out.append)

    def program_gone(self):
        self.assertFalse(desktop.autostart_enabled())
        for p in uninstall.program_files():
            self.assertFalse(uninstall._exists(p), p)
        if POSIX:
            self.assertFalse((self.home / ".local" / "bin" / "sunak").exists())
            self.assertFalse((self.data / "app").exists())
            self.assertEqual((self.home / ".bashrc").read_text(), "alias ll='ls -l'\n")
            if platform.system() == "Linux":
                self.assertEqual(list((self.home / ".local" / "share" / "applications").iterdir()), [])
        else:
            self.assertFalse((self.home / "Local" / "sunak").exists())

    def test_yes_removes_the_program_and_keeps_the_data(self):
        self.install()
        self.assertEqual(self.run_cli("--yes"), 0)
        self.program_gone()
        self.assertEqual((self.data / "sunak.db").read_text(), "chats")
        self.assertTrue(any("Kept your chats" in line for line in self.out))
        # a second run is harmless
        self.out.clear()
        self.assertEqual(self.run_cli("--yes"), 0)
        self.assertTrue((self.data / "sunak.db").exists())
        self.assertFalse(any(line.startswith("  Removed") for line in self.out))

    def test_purge_also_deletes_the_data(self):
        self.install()
        self.assertEqual(self.run_cli("--yes", "--purge"), 0)
        self.program_gone()
        self.assertFalse(self.data.exists())

    def test_questions_default_to_keeping(self):
        self.install()
        self.assertEqual(self.run_cli(answers=[""]), 0)  # Enter on "Uninstall?" keeps everything
        self.assertTrue(desktop.autostart_enabled())
        self.assertIn("Nothing removed", self.out[-1])
        self.assertEqual(self.run_cli(), 0)  # no terminal (EOF): also nothing
        self.assertTrue(desktop.autostart_enabled())
        self.assertEqual(self.run_cli(answers=["y", ""]), 0)  # yes to uninstall, Enter on "delete data?"
        self.program_gone()
        self.assertTrue((self.data / "sunak.db").exists())
        self.assertEqual(self.run_cli(answers=["y", "yes"]), 0)
        self.assertFalse(self.data.exists())

    def test_ollama_models_only_on_request(self):
        models = self.home / ".ollama" / "models"
        models.mkdir(parents=True)
        (models / "blob").write_bytes(b"x" * 10)
        self.run_cli("--yes", "--purge")
        self.assertTrue(models.exists())
        self.run_cli(answers=["y", "n"])
        self.assertTrue(models.exists())
        self.run_cli(answers=["y", "y"])
        self.assertFalse(models.exists())

    def test_never_deletes_home(self):
        os.environ["SUNAK_DATA"] = str(self.home)
        (self.home / "important.txt").write_text("x")
        self.run_cli("--yes", "--purge")
        self.assertTrue((self.home / "important.txt").exists())

    def test_unknown_option(self):
        self.assertEqual(self.run_cli("--all"), 2)

    def test_cli_runs_it(self):
        with mock.patch.object(uninstall, "main", return_value=0) as m:
            self.assertEqual(cli.main(["uninstall", "--yes"]), 0)
        m.assert_called_once_with(["--yes"])

    def test_foreign_launcher_and_icons_stay(self):
        bin_dir = self.home / ".local" / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "sunak").write_text("#!/bin/sh\necho someone else's tool\n")
        (self.home / "Desktop").mkdir()
        (self.home / "Desktop" / "sunak.desktop").write_text("[Desktop Entry]\nExec=other\n")
        self.run_cli("--yes")
        self.assertTrue((bin_dir / "sunak").exists())
        self.assertTrue((self.home / "Desktop" / "sunak.desktop").exists())


class DockerTest(unittest.TestCase):
    def test_containers_only_after_yes_and_data_kept(self):
        calls = []
        self.addCleanup(os.chdir, os.getcwd())

        def fake(*args, timeout=60):
            calls.append(args)
            return "c1\nc2\n" if args[:2] == ("ps", "-aq") else ""
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(uninstall, "docker_projects", return_value=[("sunak", tmp)]), \
                mock.patch.object(uninstall, "_docker", side_effect=fake), \
                mock.patch.object(desktop, "running", return_value=None), \
                mock.patch.object(desktop, "disable_autostart", return_value=False), \
                mock.patch.object(uninstall, "program_files", return_value=[]), \
                mock.patch.object(uninstall, "windows_path_remove", return_value=False), \
                mock.patch.object(uninstall, "data_dir", return_value=Path(tmp) / "none"), \
                mock.patch.object(uninstall, "remove_path_lines", return_value=False), \
                mock.patch.dict(os.environ, {"OLLAMA_MODELS": os.path.join(tmp, "no-models")}), \
                mock.patch("shutil.which", return_value=None):
            (Path(tmp) / "data").mkdir()
            answers = iter(["y", "n", "n"])
            uninstall.main([], ask=lambda q: next(answers), out=lambda s: None)
            self.assertEqual(calls, [])  # said no to the containers
            uninstall.main(["--yes"], ask=lambda q: self.fail(q), out=lambda s: None)
            self.assertIn(("rm", "-f", "c1", "c2"), calls)
            self.assertTrue((Path(tmp) / "data").exists())  # data only with --purge

    def test_projects_are_read_from_labels(self):
        with mock.patch("shutil.which", return_value="/usr/bin/docker"), \
                mock.patch.object(uninstall, "_docker", return_value="sunak\t/srv/sunak\nsunak\t/srv/sunak\n\n"):
            self.assertEqual(uninstall.docker_projects(), [("sunak", "/srv/sunak")])
        with mock.patch("shutil.which", return_value="/usr/bin/docker"), \
                mock.patch.object(uninstall, "_docker", return_value=None):  # daemon not running
            self.assertEqual(uninstall.docker_projects(), [])


class WindowsPathTest(unittest.TestCase):
    def test_only_our_folder_leaves_the_user_path(self):
        store = {"Path": (r"C:\Tools;C:\Users\Ä\AppData\Local\sunak\;D:\bin", 2)}

        class Key:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def set_value(k, name, _, kind, value):
            store[name] = (value, kind)
        fake = types.SimpleNamespace(HKEY_CURRENT_USER=1, KEY_READ=1, KEY_WRITE=2, OpenKey=lambda *a: Key(),
                                     QueryValueEx=lambda k, n: store[n], SetValueEx=set_value)
        with mock.patch.dict("sys.modules", {"winreg": fake}), \
                mock.patch("os.path.normcase", side_effect=str.lower):
            self.assertTrue(uninstall.windows_path_remove(r"C:\Users\Ä\AppData\Local\sunak"))
            self.assertEqual(store["Path"], (r"C:\Tools;D:\bin", 2))  # type kept (REG_EXPAND_SZ)
            self.assertFalse(uninstall.windows_path_remove(r"C:\Users\Ä\AppData\Local\sunak"))


if __name__ == "__main__":
    unittest.main()
