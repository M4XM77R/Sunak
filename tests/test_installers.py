"""Static checks of the installers (they cannot run in CI on every system)."""

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
        update = sh[sh.index("  update)"):sh.index("  uninstall)")]
        self.assertIn('export SUNAK_HOME="$HOME_DIR"', update)

    def test_git_pull_in_update_ps1_does_not_stop_on_stderr(self):
        ps = (ROOT / "install.ps1").read_text(encoding="ascii")
        block = ps[ps.index("git -C $src pull") - 200:ps.index("git -C $src pull")]
        self.assertIn('$ErrorActionPreference = "Continue"', block)


if __name__ == "__main__":
    unittest.main()
