"""Static checks of the installers (they cannot run in CI on every system)."""

import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class InstallerTest(unittest.TestCase):
    def test_install_ps1_is_ascii(self):
        # Windows PowerShell 5.1 reads a .ps1 without BOM in the ANSI code page: any UTF-8 character
        # like a check mark can turn into a quote and break the whole script.
        data = (ROOT / "install.ps1").read_bytes()
        bad = sorted({ch for ch in data.decode("utf-8") if ord(ch) > 127})
        self.assertEqual(bad, [], "use ASCII in install.ps1, e.g. [char]0x2713 for a check mark")

    def test_update_reinstalls_into_the_same_folder(self):
        sh = (ROOT / "install.sh").read_text(encoding="utf-8")
        update = sh[sh.index("  update)"):sh.index("    exit ;;")]
        self.assertIn('export SUNAK_HOME="$HOME_DIR"', update)

    def test_git_pull_in_update_ps1_does_not_stop_on_stderr(self):
        ps = (ROOT / "install.ps1").read_text(encoding="ascii")
        block = ps[ps.index("git -C $src pull") - 200:ps.index("git -C $src pull")]
        self.assertIn('$ErrorActionPreference = "Continue"', block)

    def test_uninstall_ps1_is_ascii(self):
        data = (ROOT / "uninstall.ps1").read_bytes()
        self.assertEqual(sorted({ch for ch in data.decode("utf-8") if ord(ch) > 127}), [])

    def test_launchers_hand_uninstall_to_python(self):
        # the old bash branch deleted everything including the data after a single question
        sh = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn('uninstall) cd "\\$HOME" && exec python3 -m sunak "\\$@" ;;', sh)
        self.assertNotIn("rm -rf \"$HOME_DIR\"", sh)
        # sunak.cmd is deleted while it runs: the uninstall block must end with exit /b
        ps = (ROOT / "install.ps1").read_text(encoding="ascii")
        block = ps[ps.index('if /I "%~1"=="uninstall" ('):]
        self.assertLess(block.index("-m sunak %*"), block.index("exit /b"))
        self.assertLess(block.index("exit /b"), block.index("\n)"))

    def test_uninstall_sh_parses_and_rejects_unknown_options(self):
        if not shutil.which("bash") or os.name == "nt":
            self.skipTest("needs bash")
        self.assertEqual(subprocess.run(["bash", "-n", str(ROOT / "uninstall.sh")]).returncode, 0)
        r = subprocess.run(["bash", str(ROOT / "uninstall.sh"), "--everything"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("Unknown option", r.stderr)


if __name__ == "__main__":
    unittest.main()
