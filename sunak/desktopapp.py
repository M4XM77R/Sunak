"""The optional desktop app (Tauri, see desktop/): find, install and remove the finished package.

The package comes from the newest GitHub release whose tag starts with `desktop-v`; nothing is built locally and
nothing needs Rust. Used by `sunak desktop`, by Settings → Desktop app and by the installers (`--desktop`).
Every problem is reported as DesktopError (or "no package"), never as a crash."""

import json
import os
import platform
import shutil
import subprocess
import tempfile
import threading
import urllib.request
from pathlib import Path

REPO = os.environ.get("SUNAK_REPO") or "M4XM77R/sunak"
TAG_PREFIX = "desktop-v"
MAC_APP = "Sunak Desktop.app"


class DesktopError(Exception):
    pass


def system():
    """('linux' | 'mac' | 'windows' | other, machine in lower case)."""
    return {"Linux": "linux", "Darwin": "mac", "Windows": "windows"}.get(platform.system(), platform.system().lower()), platform.machine().lower()


def supported(sysname=None, machine=None):
    """Which systems the published packages exist for: Windows, macOS on Apple silicon, Linux x86_64."""
    s, m = (sysname, machine) if sysname else system()
    m = machine or m
    return s == "windows" or (s == "mac" and m in ("arm64", "aarch64")) or (s == "linux" and m in ("x86_64", "amd64"))


def pick_asset(releases, sysname, machine):
    """{'tag', 'name', 'url'} of the package for this system in the newest suitable release, or None."""
    want = {"linux": ".AppImage", "mac": ".dmg", "windows": "-setup.exe"}.get(sysname)
    if not want or not supported(sysname, machine) or not isinstance(releases, list):
        return None
    for r in releases:
        if not isinstance(r, dict) or not str(r.get("tag_name", "")).startswith(TAG_PREFIX) or r.get("draft") or r.get("prerelease"):
            continue
        for a in r.get("assets") or []:
            name = str(a.get("name", ""))
            if name.endswith(want) and a.get("browser_download_url"):
                return {"tag": r["tag_name"], "name": name, "url": a["browser_download_url"]}
    return None


def _get(url, timeout=30):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "sunak"}), timeout=timeout)


def find_package():
    """The package for this system, or None when there is no release yet. Raises DesktopError when GitHub is unreachable."""
    s, m = system()
    if not supported(s, m):
        return None
    try:
        with _get(f"https://api.github.com/repos/{REPO}/releases?per_page=30") as r:
            return pick_asset(json.load(r), s, m)
    except (OSError, ValueError) as e:
        raise DesktopError(f"Could not reach GitHub: {e}") from e


def _home():
    return Path(os.environ.get("SUNAK_HOME") or Path.home() / ".sunak")


def app_path():
    """Where the app lives (Linux: the AppImage, macOS: the .app, Windows: the install folder), or None."""
    s, _ = system()
    if s == "linux":
        return _home() / "Sunak.AppImage"
    if s == "mac":
        return Path.home() / "Applications" / MAC_APP
    if s == "windows" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "Sunak"
    return None


def installed():
    p = app_path()
    if p is None or not p.exists():
        return False
    return _windows_installed(p) if system()[0] == "windows" else True


def _windows_installed(p):
    return p.is_dir() and any(f.suffix.lower() == ".exe" for f in p.iterdir())


def _download(url, dest, progress):
    with _get(url, 60) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                progress(f"{done * 100 // total}%")


def install(progress=lambda msg: None):
    """Download and install the package. Returns the file name that was installed."""
    s, m = system()
    if not supported(s, m):
        raise DesktopError(f"There is no desktop app package for this system ({s}, {m}).")
    pkg = find_package()
    if pkg is None:
        raise DesktopError("There is no desktop app release yet. See desktop/README.md to build it yourself.")
    progress(f"Downloading {pkg['name']} …")
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / pkg["name"]
        try:
            _download(pkg["url"], f, progress)
        except OSError as e:
            raise DesktopError(f"Download failed: {e}") from e
        progress("Installing …")
        try:
            if s == "linux":
                dest = app_path()
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), dest)
                dest.chmod(0o755)
                menu = Path.home() / ".local" / "share" / "applications"
                menu.mkdir(parents=True, exist_ok=True)
                (menu / "sunak-desktop.desktop").write_text(
                    f"[Desktop Entry]\nType=Application\nName=Sunak Desktop\nExec={dest}\nTerminal=false\nCategories=Utility;\n", encoding="utf-8")
            elif s == "mac":
                mnt = Path(tmp) / "mnt"
                mnt.mkdir()
                subprocess.run(["hdiutil", "attach", "-nobrowse", "-quiet", "-mountpoint", str(mnt), str(f)], check=True)
                try:
                    dest = app_path()
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.rmtree(dest, ignore_errors=True)
                    shutil.copytree(mnt / "Sunak.app", dest, symlinks=True)
                finally:
                    subprocess.run(["hdiutil", "detach", "-quiet", str(mnt)], check=False)
            else:
                subprocess.run([str(f), "/S"], check=True)
        except (OSError, subprocess.CalledProcessError) as e:
            raise DesktopError(f"Installation failed: {e}") from e
    return pkg["name"]


def uninstall():
    """Remove the app. False when it was not installed."""
    s, _ = system()
    p = app_path()
    if not installed():
        return False
    try:
        if s == "windows":
            un = p / "uninstall.exe"
            if not un.exists():
                raise DesktopError("The uninstaller was not found. Remove 'Sunak' in Windows Settings → Apps.")
            subprocess.run([str(un), "/S"], check=True)
        elif s == "mac":
            shutil.rmtree(p)
        else:
            p.unlink()
            (Path.home() / ".local" / "share" / "applications" / "sunak-desktop.desktop").unlink(missing_ok=True)
    except (OSError, subprocess.CalledProcessError) as e:
        raise DesktopError(f"Removal failed: {e}") from e
    return True


# one-time hint after the update --------------------------------------------

def notice_pending(data_dir, kind):
    """True once per `kind` ('cli' or 'gui') for a computer that has no desktop app and could use it."""
    return supported() and not (Path(data_dir) / f".desktop-notice-{kind}").exists() and not installed()


def mark_notice(data_dir, kind):
    try:
        (Path(data_dir) / f".desktop-notice-{kind}").write_text("1", encoding="utf-8")
    except OSError:
        pass


# background job for the Settings button ---------------------------------------

_job = {"busy": False, "msg": "", "error": "", "done": False}
_lock = threading.Lock()


def job_state():
    with _lock:
        return dict(_job)


def start_job(action):
    """Run 'install' or 'uninstall' in the background. False when one is already running."""
    with _lock:
        if _job["busy"]:
            return False
        _job.update(busy=True, msg="", error="", done=False)

    def run():
        try:
            if action == "install":
                install(lambda m: _job.update(msg=m))
            else:
                uninstall()
        except DesktopError as e:
            _job["error"] = str(e)
        except Exception as e:  # noqa: BLE001 - a background job must report, not die
            _job["error"] = f"{type(e).__name__}: {e}"
        finally:
            with _lock:
                _job.update(busy=False, done=True)
    threading.Thread(target=run, daemon=True).start()
    return True
