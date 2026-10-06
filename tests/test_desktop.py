"""Tests for the command line (stop, status, already running) and the autostart files."""

import contextlib
import io
import os
import platform
import tempfile
import threading
import unittest
from unittest import mock

from sunak import __main__ as cli, __version__, desktop
from sunak.server import make_server


class DesktopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        home = self.tmp.name
        env = {"HOME": home, "USERPROFILE": home, "APPDATA": os.path.join(home, "AppData"),
               "LOCALAPPDATA": os.path.join(home, "Local"), "XDG_CONFIG_HOME": os.path.join(home, ".config"),
               "XDG_DATA_HOME": os.path.join(home, ".local", "share")}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_autostart_on_and_off(self):
        self.assertFalse(desktop.autostart_enabled())
        path = desktop.enable_autostart()
        self.assertTrue(str(path).startswith(self.tmp.name))
        raw = path.read_bytes()
        content = raw.decode("utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8")
        self.assertIn("--no-browser", content)
        self.assertIn(str(desktop.PKG_ROOT), content.replace("\\\\", "\\"))
        self.assertTrue(desktop.autostart_enabled())
        self.assertTrue(desktop.disable_autostart())
        self.assertFalse(desktop.disable_autostart())
        self.assertFalse(path.exists())

    @unittest.skipUnless(platform.system() == "Linux", "Linux desktop files")
    def test_linux_shortcut(self):
        os.makedirs(os.path.join(self.tmp.name, "Desktop"))
        written = desktop.create_shortcut()
        self.assertEqual(len(written), 2)
        text = written[1].read_text()
        self.assertIn("Terminal=false", text)
        self.assertIn("-m sunak", text)

    def test_desktop_quoting(self):
        self.assertEqual(desktop._quote("/usr/bin/python3"), "/usr/bin/python3")
        # Desktop Entry spec: \" inside quotes, then every backslash doubled; %% for %
        self.assertEqual(desktop._quote('/My Apps/py "3"'), r'"/My Apps/py \\"3\\""')
        self.assertEqual(desktop._quote("/a b/c$d"), r'"/a b/c\\$d"')
        self.assertEqual(desktop._quote("/100%/py"), "/100%%/py")
        self.assertEqual(desktop._quote("C:\\x y"), r'"C:\\\\x y"')

    def test_running_open_and_stop(self):
        srv = make_server("127.0.0.1", 0, self.tmp.name + "/data")
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        self.assertEqual(desktop.running(port), __version__)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            # a second start only points at the running Sunak
            self.assertEqual(cli.main(["--no-browser", "--port", str(port)]), 0)
            self.assertEqual(cli.main(["status", "--port", str(port)]), 0)
            self.assertEqual(cli.main(["stop", "--port", str(port)]), 0)
        t.join(5)
        srv.server_close()
        self.assertFalse(t.is_alive())
        self.assertIn("already running", out.getvalue())
        self.assertIn(f"Stopped Sunak on port {port}", out.getvalue())
        self.assertIsNone(desktop.running(port))

    def test_commands(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["version"]), 0)
            self.assertEqual(cli.main(["autostart", "maybe"]), 2)
        self.assertTrue(out.getvalue().startswith(__version__))

    def test_bad_ports_and_launcher_only_commands_give_a_message(self):
        for argv, env in ((["stop", "--port", "abc"], {}), (["version"], {"SUNAK_PORT": "x"}), (["update"], {}),
                          (["uninstall"], {})):
            with mock.patch.dict(os.environ, env), self.assertRaises(SystemExit) as e:
                cli.main(argv)
            self.assertIsInstance(e.exception.code, str)  # a message, not a traceback

    def test_mac_app_creates_log_folder(self):
        with mock.patch("platform.system", return_value="Darwin"):
            written = desktop.create_shortcut()
        script = (written[0] / "Contents" / "MacOS" / "sunak").read_text()
        self.assertLess(script.index('mkdir -p "$HOME/.sunak"'), script.index("exec "))

    @unittest.skipIf(platform.system() == "Windows", "desktop entries are Linux files")
    def test_desktop_entry_exec_is_one_argument_per_value(self):
        with mock.patch.object(desktop, "PKG_ROOT", desktop.Path("/opt/My Apps/sunak")):
            entry = desktop._desktop_entry(["/usr/bin/python3", "-m", "sunak"])
        self.assertIn('Exec=env "PYTHONPATH=/opt/My Apps/sunak" /usr/bin/python3 -m sunak', entry)


if __name__ == "__main__":
    unittest.main()
