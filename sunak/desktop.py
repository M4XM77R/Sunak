"""Desktop integration: start with the computer (autostart), desktop shortcut, and talking to a
Sunak that is already running (open it in the browser instead of starting twice, stop it)."""

import base64
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

APP_ID = "dev.sunak"
PKG_ROOT = Path(__file__).resolve().parent.parent  # folder that contains the sunak package


def _direct(req, timeout):
    return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout)


def running(port, host="127.0.0.1", timeout=1.5):
    """Version string of a Sunak answering on host:port, or None."""
    try:
        with _direct(urllib.request.Request(f"http://{host}:{port}/api/status"), timeout) as r:
            if not r.headers.get("Server", "").startswith("Sunak/"):
                return None
            return json.load(r).get("version") or "?"
    except (OSError, ValueError, urllib.error.URLError):
        return None


def stop(port, host="127.0.0.1", timeout=3):
    """Ask the Sunak on host:port to shut down. True when it accepted."""
    req = urllib.request.Request(f"http://{host}:{port}/api/shutdown", data=b"{}", method="POST",
                                 headers={"X-Requested-With": "sunak", "Content-Type": "application/json"})
    try:
        with _direct(req, timeout) as r:
            return r.status == 200
    except (OSError, urllib.error.URLError):
        return False


def command(*args, gui=False):
    """Command line that starts Sunak with this Python. `gui` prefers pythonw on Windows (no console)."""
    exe = Path(sys.executable)
    if gui and platform.system() == "Windows" and (exe.parent / "pythonw.exe").exists():
        exe = exe.parent / "pythonw.exe"
    return [str(exe), "-m", "sunak", *args]


def _env_pythonpath():
    return str(PKG_ROOT)


# autostart --------------------------------------------------------------------

def autostart_path():
    """File that makes the system start Sunak at login."""
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "LaunchAgents" / f"{APP_ID}.plist"
    if system == "Windows":
        return Path(os.environ.get("APPDATA", Path.home())) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Sunak.vbs"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart" / "sunak.desktop"


def _vbs(cmd):
    """Windows script that runs `cmd` without a console window, with PYTHONPATH set."""
    quoted = " ".join('""' + c + '""' if " " in c or c == cmd[0] else c for c in cmd)
    return ('Set sh = CreateObject("WScript.Shell")\r\n'
            f'sh.Environment("PROCESS")("PYTHONPATH") = "{_env_pythonpath()}"\r\n'
            f'sh.Run "{quoted}", 0, False\r\n')


def _desktop_entry(cmd, name="Sunak", autostart=False):
    """Linux .desktop file content."""
    exec_line = "env PYTHONPATH=" + _quote(_env_pythonpath()) + " " + " ".join(_quote(c) for c in cmd)
    lines = ["[Desktop Entry]", "Type=Application", f"Name={name}", "Comment=Private AI workspace",
             f"Exec={exec_line}", f"Icon={PKG_ROOT / 'sunak' / 'static' / 'icon.svg'}", "Terminal=false",
             "Categories=Utility;"]
    if autostart:
        lines.append("X-GNOME-Autostart-enabled=true")
    return "\n".join(lines) + "\n"


def _quote(s):
    """Quote an argument for a .desktop Exec line."""
    s = str(s)
    if not any(c in s for c in ' "\'\\$`'):
        return s
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`") + '"'


def autostart_enabled():
    return autostart_path().exists()


def enable_autostart():
    """Start Sunak in the background at every login (no browser window). Returns the file written."""
    path = autostart_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    system = platform.system()
    if system == "Darwin":
        log = Path.home() / ".sunak" / "sunak.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        plist = {"Label": APP_ID, "ProgramArguments": command("--no-browser"), "RunAtLoad": True,
                 "EnvironmentVariables": {"PYTHONPATH": _env_pythonpath()},
                 "StandardOutPath": str(log), "StandardErrorPath": str(log)}
        path.write_bytes(plistlib.dumps(plist))
    elif system == "Windows":
        path.write_text(_vbs(command("--no-browser", gui=True)), encoding="utf-8")
    else:
        path.write_text(_desktop_entry(command("--no-browser"), autostart=True), encoding="utf-8")
    return path


def disable_autostart():
    """Remove the autostart entry. Returns True when there was one."""
    path = autostart_path()
    if platform.system() == "Darwin" and path.exists() and shutil.which("launchctl"):
        subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
    if path.exists():
        path.unlink()
        return True
    return False


# desktop shortcut ------------------------------------------------------------

def desktop_dir():
    """The user's desktop folder (honours XDG user-dirs on Linux)."""
    if platform.system() == "Linux":
        cfg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "user-dirs.dirs"
        if cfg.exists():
            for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("XDG_DESKTOP_DIR="):
                    return Path(line.split("=", 1)[1].strip().strip('"').replace("$HOME", str(Path.home())))
    return Path.home() / "Desktop"


def create_shortcut():
    """Desktop icon that starts Sunak (or opens it when it already runs). Returns the paths written."""
    system = platform.system()
    written = []
    if system == "Darwin":
        # a tiny .app bundle in ~/Applications, plus a link to it on the desktop
        app = Path.home() / "Applications" / "Sunak.app"
        macos = app / "Contents" / "MacOS"
        macos.mkdir(parents=True, exist_ok=True)
        (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleName": "Sunak", "CFBundleIdentifier": APP_ID, "CFBundleExecutable": "sunak",
            "CFBundlePackageType": "APPL", "CFBundleVersion": "1"}))
        script = macos / "sunak"
        cmd = " ".join("'" + c.replace("'", "'\\''") + "'" for c in command())
        script.write_text(f"#!/bin/sh\nexport PYTHONPATH='{_env_pythonpath()}'\nexec {cmd} >> \"$HOME/.sunak/sunak.log\" 2>&1\n",
                          encoding="utf-8")
        script.chmod(0o755)
        written.append(app)
        link = desktop_dir() / "Sunak.app"
        if desktop_dir().is_dir() and not link.exists():
            link.symlink_to(app)
            written.append(link)
    elif system == "Windows":
        # the .vbs starts Sunak without a console window; the shortcut points at it
        vbs = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "sunak" / "Sunak.vbs"
        vbs.parent.mkdir(parents=True, exist_ok=True)
        vbs.write_text(_vbs(command(gui=True)), encoding="utf-8")
        # shortcuts on the desktop (also when OneDrive moved it) and in the Start menu
        ps = ("$ws = New-Object -ComObject WScript.Shell; "
              "foreach ($d in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) { "
              "$p = Join-Path $d 'Sunak.lnk'; $s = $ws.CreateShortcut($p); $s.TargetPath = 'wscript.exe'; "
              "$s.Arguments = '\"' + $env:SUNAK_VBS + '\"'; $s.Description = 'Sunak'; $s.Save(); $p }")
        res = None
        if shutil.which("powershell"):
            encoded = base64.b64encode(ps.encode("utf-16-le")).decode()  # avoids all quoting problems
            res = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                                 env=dict(os.environ, SUNAK_VBS=str(vbs)), capture_output=True, text=True)
        if res and res.returncode == 0:
            written.append(vbs)
            written += [Path(x.strip()) for x in res.stdout.splitlines() if x.strip()]
            return written
        lnk = desktop_dir() / "Sunak.vbs"  # no PowerShell: put the script itself on the desktop
        lnk.write_text(vbs.read_text(encoding="utf-8"), encoding="utf-8")
        written += [vbs, lnk]
    else:
        content = _desktop_entry(command())
        menu = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "applications" / "sunak.desktop"
        menu.parent.mkdir(parents=True, exist_ok=True)
        menu.write_text(content, encoding="utf-8")
        written.append(menu)
        if desktop_dir().is_dir():
            icon = desktop_dir() / "sunak.desktop"
            icon.write_text(content, encoding="utf-8")
            icon.chmod(0o755)
            if shutil.which("gio"):  # GNOME: mark as trusted so it starts on double-click
                subprocess.run(["gio", "set", str(icon), "metadata::trusted", "true"], capture_output=True)
            written.append(icon)
    return written
