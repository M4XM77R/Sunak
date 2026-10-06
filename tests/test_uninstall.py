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
                  mock.patch.object(uninstall, "ollama_install", return_value=None),  # never the real Ollama
                  mock.patch.object(uninstall, "SERVICE_MODELS", self.home / "no-service-models"),
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
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(os.chdir, os.getcwd())
        self.calls = []
        root = Path(self.tmp.name)
        for p in (mock.patch.object(uninstall, "docker_projects", return_value=[("sunak", str(root))]),
                  mock.patch.object(uninstall, "_docker", side_effect=self.fake),
                  mock.patch.object(desktop, "running", return_value=None),
                  mock.patch.object(desktop, "disable_autostart", return_value=False),
                  mock.patch.object(uninstall, "program_files", return_value=[]),
                  mock.patch.object(uninstall, "windows_path_remove", return_value=False),
                  mock.patch.object(uninstall, "data_dir", return_value=root / "none"),
                  mock.patch.object(uninstall, "remove_path_lines", return_value=False),
                  mock.patch.object(uninstall, "ollama_install", return_value=None),
                  mock.patch.object(uninstall, "SERVICE_MODELS", root / "none"),
                  mock.patch.dict(os.environ, {"OLLAMA_MODELS": str(root / "no-models")}),
                  mock.patch("shutil.which", return_value=None)):
            p.start()
            self.addCleanup(p.stop)
        self.data = root / "data"
        (self.data / "ollama").mkdir(parents=True)
        (self.data / "sunak.db").write_text("x")

    def fake(self, *args, timeout=60):
        self.calls.append(args)
        if args[:2] == ("ps", "-aq"):
            return "s1\n" if "label=com.docker.compose.service=sunak" in args else "o1\n"
        return ""

    def removed(self):
        return [c[2:] for c in self.calls if c[:2] == ("rm", "-f")]

    def test_each_container_has_its_own_question(self):
        answers = iter(["y", "n", "n", "n", "n"])  # uninstall, Sunak container, Ollama container, data, models
        uninstall.main([], ask=lambda q: next(answers), out=lambda s: None)
        self.assertEqual(self.removed(), [])
        answers = iter(["y", "y", "n", "n", "n"])
        uninstall.main([], ask=lambda q: next(answers), out=lambda s: None)
        self.assertEqual(self.removed(), [("s1",)])

    def test_yes_keeps_the_ollama_container_and_all_data(self):
        uninstall.main(["--yes"], ask=lambda q: self.fail(q), out=lambda s: None)
        self.assertEqual(self.removed(), [("s1",)])
        self.assertTrue((self.data / "sunak.db").exists())
        uninstall.main(["--yes", "--purge"], ask=lambda q: self.fail(q), out=lambda s: None)
        self.assertFalse((self.data / "sunak.db").exists())
        self.assertTrue((self.data / "ollama").exists())  # models: only with --with-models
        uninstall.main(["--yes", "--with-ollama", "--with-models"], ask=lambda q: self.fail(q), out=lambda s: None)
        self.assertIn(("o1",), self.removed())
        self.assertFalse((self.data / "ollama").exists())

class OllamaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(os.chdir, os.getcwd())
        root = Path(self.tmp.name)
        self.ran = []
        for p in (mock.patch.object(uninstall, "docker_projects", return_value=[]),
                  mock.patch.object(desktop, "running", return_value=None),
                  mock.patch.object(desktop, "disable_autostart", return_value=False),
                  mock.patch.object(uninstall, "program_files", return_value=[]),
                  mock.patch.object(uninstall, "windows_path_remove", return_value=False),
                  mock.patch.object(uninstall, "data_dir", return_value=root / "none"),
                  mock.patch.object(uninstall, "remove_path_lines", return_value=False),
                  mock.patch.object(uninstall, "ollama_install", return_value={"how": "brew-cask"}),
                  mock.patch.object(uninstall, "_run", side_effect=lambda cmd, out: self.ran.append(cmd) or True),
                  mock.patch.object(uninstall, "SERVICE_MODELS", root / "none"),
                  mock.patch.dict(os.environ, {"OLLAMA_MODELS": str(root / "models")}),
                  mock.patch("shutil.which", return_value=None)):
            p.start()
            self.addCleanup(p.stop)
        self.models = root / "models"
        self.models.mkdir()

    def go(self, *args, answers=()):
        answers = list(answers)

        def ask(q):
            if not answers:
                raise EOFError
            return answers.pop(0)
        out = []
        code = uninstall.main(list(args), ask=ask, out=out.append)
        return code, out

    def test_ollama_is_only_removed_when_asked(self):
        self.go(answers=["y"])  # Enter (here: no terminal) on the Ollama question
        self.go("--yes")
        self.go("--yes", "--purge")
        self.go(answers=["y", "n", "n"])
        self.assertEqual(self.ran, [])
        self.assertTrue(self.models.exists())
        code, out = self.go(answers=["y", "y", "n"])  # uninstall, Ollama yes, models no
        self.assertEqual((code, self.ran), (0, [["brew", "uninstall", "--cask", "ollama"]]))
        self.assertTrue(self.models.exists())
        self.assertIn("  Ollama is uninstalled.", out)
        self.ran.clear()
        self.go("--yes", "--with-ollama")
        self.assertEqual(len(self.ran), 1)
        self.assertTrue(self.models.exists())  # models have their own flag
        self.go("--yes", "--with-models")
        self.assertFalse(self.models.exists())

    def test_failed_step_is_reported(self):
        with mock.patch.object(uninstall, "_run", return_value=False):
            code, out = self.go("--yes", "--with-ollama")
        self.assertEqual(code, 1)
        self.assertIn("  Failed: brew uninstall --cask ollama", out)

class DetectTest(unittest.TestCase):
    def test_projects_are_read_from_labels(self):
        with mock.patch("shutil.which", return_value="/usr/bin/docker"), \
                mock.patch.object(uninstall, "_docker", return_value="sunak\t/srv/sunak\nsunak\t/srv/sunak\n\n"):
            self.assertEqual(uninstall.docker_projects(), [("sunak", "/srv/sunak")])
        with mock.patch("shutil.which", return_value="/usr/bin/docker"), \
                mock.patch.object(uninstall, "_docker", return_value=None):  # daemon not running
            self.assertEqual(uninstall.docker_projects(), [])

    def test_commands_per_install(self):
        c = uninstall.ollama_commands
        self.assertEqual(c({"how": "winget"})[-1][:4], ["winget", "uninstall", "-e", "--id"])
        self.assertEqual(c({"how": "inno", "uninstaller": Path("u.exe")})[-1], ["u.exe", "/VERYSILENT", "/NORESTART"])
        self.assertEqual(c({"how": "brew"}), [["brew", "services", "stop", "ollama"], ["brew", "uninstall", "ollama"]])
        app = c({"how": "app", "apps": [Path("/Applications/Ollama.app")], "exe": None})
        self.assertEqual(app[1], ["rm", "-rf", str(Path("/Applications/Ollama.app"))])
        with mock.patch("os.geteuid", return_value=1000, create=True):
            script = c({"how": "script", "exe": "/usr/local/bin/ollama"})
            self.assertEqual(c({"how": "snap"}), [["sudo", "snap", "remove", "ollama"]])
        self.assertIn(["sudo", "systemctl", "stop", "ollama"], script)
        self.assertIn(["sudo", "rm", "-rf", str(Path("/usr/local/lib/ollama"))], script)
        self.assertTrue(all(uninstall._best_effort(x) for x in script if x[1] in ("systemctl", "userdel", "groupdel")))
        self.assertFalse(uninstall._best_effort(["sudo", "rm", "-f", "x"]))
        self.assertIsInstance(c({"how": "manual", "exe": "/usr/bin/ollama"}), str)

    def test_linux_detection(self):
        with mock.patch("platform.system", return_value="Linux"):
            with mock.patch("shutil.which", return_value="/usr/local/bin/ollama"):
                self.assertEqual(uninstall.ollama_install()["how"], "script")
            with mock.patch("shutil.which", return_value="/snap/bin/ollama"):
                self.assertEqual(uninstall.ollama_install()["how"], "snap")
            with mock.patch("shutil.which", return_value="/usr/bin/ollama"), \
                    mock.patch.object(Path, "exists", return_value=False):
                self.assertEqual(uninstall.ollama_install()["how"], "manual")
            with mock.patch("shutil.which", return_value=None):
                self.assertIsNone(uninstall.ollama_install())


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
