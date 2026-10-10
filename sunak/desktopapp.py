"""The optional desktop app (Tauri, see desktop/): find, install and remove the finished package.

The package comes from the newest GitHub release whose tag starts with `desktop-v`; nothing is built locally and
nothing needs Rust. Used by `sunak desktop`, by Settings → Desktop app and by the installers (`--desktop`).
Every problem is reported as DesktopError (or "no package"), never as a crash."""

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
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
        assets = [a for a in r.get("assets") or [] if isinstance(a, dict)]
        sums = next((a.get("browser_download_url") for a in assets if a.get("name") == "SHA256SUMS"), None)
        for a in assets:
            name = Path(str(a.get("name", ""))).name
            if name.endswith(want) and _trusted(a.get("browser_download_url")):
                return {"tag": r["tag_name"], "name": name, "url": a["browser_download_url"],
                        "sums": sums if _trusted(sums) else None}
    return None


def _trusted(url):
    """Downloads only come from GitHub over https."""
    u = urlparse(str(url or ""))
    return u.scheme == "https" and (u.hostname or "") in ("github.com", "api.github.com", "objects.githubusercontent.com",
                                                          "release-assets.githubusercontent.com")


class _OnlyGitHub(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _trusted(newurl):
            raise urllib.error.URLError(f"redirect to {urlparse(newurl).hostname} refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _get(url, timeout=30):
    opener = urllib.request.build_opener(_OnlyGitHub)
    return opener.open(urllib.request.Request(url, headers={"User-Agent": "sunak"}), timeout=timeout)


def find_package():
    """The package for this system, or None when there is no release yet. Raises DesktopError when GitHub is unreachable."""
    s, m = system()
    if not supported(s, m):
        return None
    try:
        with _get(f"https://api.github.com/repos/{REPO}/releases?per_page=30") as r:
            return pick_asset(json.load(r), s, m)
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise DesktopError("GitHub refused the request (rate limit?). Try again in a while.") from e
        raise DesktopError(f"Could not reach GitHub: HTTP {e.code}") from e
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


# version of the installed shell -----------------------------------------------

def _version_file():
    return _home() / "desktop-version"


def tag_version(tag):
    """'desktop-v1.2.0' -> (1, 2, 0); an unknown or empty tag -> ()."""
    return tuple(int(n) for n in re.findall(r"\d+", str(tag or "")))


def installed_tag():
    """Release tag of the installed app as recorded by install(); '' when unknown."""
    try:
        return _version_file().read_text(encoding="utf-8").strip()
    except (OSError, ValueError):  # missing, unreadable or not text
        return ""


def is_newer(new_tag, old_tag):
    return tag_version(new_tag) > tag_version(old_tag)


def running():
    """Is the desktop app open right now? (Replacing a running app is not safe on any system.)"""
    s, _ = system()
    try:
        if s == "windows":
            out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=15).stdout.lower()
            return any(f'"{n}"' in out for n in ("sunak-desktop.exe", "sunak.exe"))
        pattern = "Sunak.AppImage" if s == "linux" else f"{MAC_APP}/Contents"
        return subprocess.run(["pgrep", "-f", pattern], capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


_pending = {"at": 0.0, "tag": ""}


def pending_update():
    """Tag of a newer desktop release for an installed app, else ''. Looked up at most every 6 hours; never raises."""
    if not installed():
        return ""
    if time.time() - _pending["at"] > 6 * 3600:
        try:
            pkg = find_package()
            _pending.update(at=time.time(), tag=pkg["tag"] if pkg and is_newer(pkg["tag"], installed_tag()) else "")
        except Exception:  # noqa: BLE001 - a hint must never break the update check; a failure is remembered too (no retry per request)
            _pending.update(at=time.time(), tag="")
    return _pending["tag"]


def update(progress=lambda msg: None):
    """Renew an installed app when a newer release exists. Returns 'none' (not installed, or up to date), 'running'
    (the app is open: nothing was touched), 'no_release' (nothing published yet) or 'updated'. Raises DesktopError on a failure."""
    if not installed():
        return "none"
    pkg = find_package()
    if pkg is None:
        return "no_release"
    if not is_newer(pkg["tag"], installed_tag()):
        return "none"
    if running():
        return "running"
    install(progress)
    _pending.update(at=0.0, tag="")
    return "updated"


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
        if total and done != total:
            raise OSError(f"the download stopped at {done} of {total} bytes")


def _verify(file, name, sums_url):
    """Compare the SHA-256 of the download with the release's SHA256SUMS. Nothing is run without a match."""
    if not sums_url:
        raise DesktopError("The release has no SHA256SUMS, so the download cannot be checked. Nothing was installed.")
    try:
        with _get(sums_url) as r:
            lines = r.read(1 << 20).decode("utf-8", "replace").splitlines()
    except OSError as e:
        raise DesktopError(f"Could not download SHA256SUMS: {e}") from e
    want = next((ln.split()[0].lower() for ln in lines if len(ln.split()) == 2 and ln.split()[1].lstrip("*") == name), None)
    h = hashlib.sha256()
    with open(file, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if want is None or h.hexdigest() != want:
        raise DesktopError("The download does not match its checksum. Nothing was installed.")


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
        progress("Checking …")
        _verify(f, pkg["name"], pkg.get("sums"))
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
                    f"[Desktop Entry]\nType=Application\nName=Sunak Desktop\nExec=\"{dest}\"\nIcon=web-browser\nTerminal=false\nCategories=Utility;\n", encoding="utf-8")
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
    try:
        _version_file().parent.mkdir(parents=True, exist_ok=True)
        _version_file().write_text(pkg["tag"], encoding="utf-8")
    except OSError:
        pass
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
            # without _?= the NSIS uninstaller copies itself away and returns at once, before anything is removed
            subprocess.run([str(un), "/S", f"_?={p}"], check=True)
            shutil.rmtree(p, ignore_errors=True)
        elif s == "mac":
            shutil.rmtree(p)
        else:
            p.unlink()
            (Path.home() / ".local" / "share" / "applications" / "sunak-desktop.desktop").unlink(missing_ok=True)
    except (OSError, subprocess.CalledProcessError) as e:
        raise DesktopError(f"Removal failed: {e}") from e
    _version_file().unlink(missing_ok=True)
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
