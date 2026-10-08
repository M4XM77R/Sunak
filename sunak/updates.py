"""Update check and self-update.

`check()` asks git whether the clone Sunak was installed from has new commits on its remote; the app
shows an "Update available" hint for that. Every problem (no git, no network, no clone, no upstream
branch, a password prompt) just means "no update known": nothing here raises.

The Update button runs this module as a helper process (`python -m sunak.updates`): it waits until the
old server has stopped, installs the update like `sunak update` does, and starts Sunak again."""

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

from . import __version__, changelog, desktop

CHECK_EVERY = 6 * 3600   # seconds between two checks
RETRY_AFTER = 1800       # a failed check (offline?) is tried again after half an hour
RESULT_FILE = "update-result.json"
WINDOWS = platform.system() == "Windows"


def _env(root=desktop.PKG_ROOT):
    """Environment for git and the helper: never ask for passwords, find the sunak package in `root`."""
    path = os.environ.get("PYTHONPATH")
    return dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never",
                PYTHONPATH=str(root) + (os.pathsep + path if path else ""))


def _hidden():
    """No console window on Windows, no controlling terminal elsewhere (so ssh cannot ask for a passphrase)."""
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if WINDOWS else {"start_new_session": True}


def _git(repo, *args, timeout=60):
    """Output of a git command in `repo`, or None when it fails."""
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=_env(), stdin=subprocess.DEVNULL, **_hidden())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def repo_dir(root=desktop.PKG_ROOT):
    """The git clone this Sunak comes from: the app folder itself, or the clone the installer remembered
    (~/.sunak/source, on Windows %LOCALAPPDATA%\\sunak\\source.txt). None when there is none."""
    root = Path(root)
    if (root / ".git").exists():
        return root
    for name in ("source", "source.txt"):
        try:
            src = Path((root.parent / name).read_text(encoding="utf-8-sig").strip())
        except (OSError, ValueError):
            continue
        if src.is_absolute() and (src / ".git").exists():
            return src
    return None


def installed_commit(root, repo):
    """Commit of the installed copy: written to .commit by the installer, else the clone's HEAD."""
    if Path(root) == Path(repo):
        return "HEAD"
    try:
        commit = (Path(root) / ".commit").read_text(encoding="utf-8-sig").strip()
    except (OSError, ValueError):
        return "HEAD"
    return commit if re.fullmatch(r"[0-9a-f]{40,64}", commit) else "HEAD"


def inspect(root=desktop.PKG_ROOT):
    """The update check with details: {"behind": new commits (0 = up to date, None = unknown), "version": the
    version on the remote ("" when unknown), "changelog": the CHANGELOG.md entries between the installed
    and the remote version (newest first, [] when there are none or the file is missing), "error": why it could
    not be found out ("" when it could)}."""
    repo = repo_dir(root)
    if repo is None:
        return {"behind": None, "version": "", "changelog": [], "error": "no_clone"}
    if _git(repo, "fetch", "--quiet") is None:
        return {"behind": None, "version": "", "changelog": [], "error": "no_remote"}
    for base in dict.fromkeys((installed_commit(root, repo), "HEAD")):
        count = _git(repo, "rev-list", "--count", f"{base}..@{{u}}", timeout=20)
        if count is not None and count.isdigit():
            m = re.search(r'^__version__\s*=\s*"([^"]+)"', _git(repo, "show", "@{u}:sunak/__init__.py", timeout=20) or "", re.M)
            version = m.group(1) if m else ""
            entries = []
            if int(count):
                entries = changelog.between(changelog.parse(_git(repo, "show", "@{u}:CHANGELOG.md", timeout=20)), __version__, version)
            return {"behind": int(count), "version": version, "changelog": entries, "error": ""}
    return {"behind": None, "version": "", "changelog": [], "error": "no_upstream"}


def check(root=desktop.PKG_ROOT):
    """Number of new commits on the remote (0 = up to date), or None when that cannot be found out."""
    return inspect(root)["behind"]


def launcher(root=desktop.PKG_ROOT):
    """The `sunak` command written by the installer for this copy (its `update` reinstalls it), or None."""
    root = Path(root).resolve()
    if WINDOWS:
        cmd = root.parent / "sunak.cmd"
        return cmd if cmd.is_file() else None
    cmd = Path.home() / ".local" / "bin" / "sunak"
    try:
        text = cmd.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r'^APP_DIR="(.*)"$', text, re.M)
    return cmd if m and Path(m.group(1)).resolve() == root else None


def update_command(root=desktop.PKG_ROOT):
    """Command that installs the newest version of this copy, or None when Sunak cannot update itself."""
    if (Path(root) / ".git").exists():
        return ["git", "-C", str(root), "pull", "--ff-only"]
    cmd = launcher(root)
    if cmd is None:
        return None
    return ["cmd", "/c", "call", str(cmd), "update"] if WINDOWS else [str(cmd), "update"]


def pop_result(data_dir):
    """Outcome of the last update ({"ok", "error"}), once; None when there is none."""
    path = Path(data_dir) / RESULT_FILE
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
        path.unlink()
    except (OSError, ValueError):
        return None
    return result if isinstance(result, dict) else None


def _launch(cmd, data_dir, root, flags):
    """Start `cmd` in the background, detached from this process, with output in data_dir/update.log."""
    with open(Path(data_dir) / "update.log", "ab") as log:
        subprocess.Popen(cmd, cwd=str(data_dir), env=_env(root), stdin=subprocess.DEVNULL, stdout=log,
                         stderr=subprocess.STDOUT, close_fds=True, **flags)


def spawn_helper(port, host, data_dir, root=desktop.PKG_ROOT):
    """Start the helper that updates and restarts Sunak once this server has stopped."""
    data_dir = Path(data_dir)
    flags = _hidden()
    if WINDOWS:
        flags["creationflags"] |= subprocess.CREATE_NEW_PROCESS_GROUP
    _launch([sys.executable, "-m", "sunak.updates", "--port", str(port), "--host", host,
             "--data-dir", str(data_dir)], data_dir, root, flags)


def apply(port, host, data_dir, root=desktop.PKG_ROOT):
    """Helper process: wait for the old server to stop, install the update, start Sunak again.
    The outcome goes to data_dir/update-result.json, which the app shows after the restart."""
    data_dir = Path(data_dir)
    probe = "127.0.0.1" if host in ("", "0.0.0.0") else host
    for _ in range(60):
        if not desktop.running(port, probe):
            break
        time.sleep(0.5)
    time.sleep(1)  # let the operating system free the port
    cmd = update_command(root)
    if cmd is None:
        ok, out = False, "Sunak cannot update itself here. Run git pull and the installer in your clone."
    else:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=900,
                               cwd=str(data_dir), env=_env(root), stdin=subprocess.DEVNULL, **_hidden())
            ok, out = r.returncode == 0, (r.stdout or "") + (r.stderr or "")
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            ok, out = False, str(e)
    print(out, flush=True)
    lines = [x.strip() for x in out.splitlines() if x.strip()]
    result = {"ok": ok, "error": "" if ok else (" ".join(lines[-3:]) or "unknown error")[-300:]}
    try:
        (data_dir / RESULT_FILE).write_text(json.dumps(result), encoding="utf-8")
    except OSError:
        pass
    flags = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS \
        else {"start_new_session": True}
    _launch(desktop.command("--no-browser", "--host", host, "--port", str(port), "--data-dir", str(data_dir),
                            gui=True), data_dir, root, flags)
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m sunak.updates", description="Update and restart Sunak")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--data-dir", required=True)
    args = ap.parse_args(argv)
    return 0 if apply(args.port, args.host, args.data_dir) else 1


if __name__ == "__main__":
    sys.exit(main())
