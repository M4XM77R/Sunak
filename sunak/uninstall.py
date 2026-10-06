"""Remove Sunak from this computer:  sunak uninstall [--yes] [--purge]

Removes the program: the `sunak` command, the app folder, desktop and menu icons, autostart and the
PATH entry, and (after asking) Sunak's Docker containers. Your data (chats, settings, API keys, mail
accounts) is only deleted when you say so or pass --purge. Downloaded Ollama models are only deleted
when you say so; Ollama itself stays installed, because other programs may use it.
Safe to run twice: whatever is already gone is skipped."""

import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

from . import desktop

PATH_MARK = "# sunak PATH"  # written by install.sh into the shell start files
LAUNCHER_MARK = "Sunak launcher"
USAGE = "Usage: sunak uninstall [--yes] [--purge]\n  --yes    no questions: remove the program, keep your data\n  --purge  also delete your data"


def _windows():
    return platform.system() == "Windows"


def data_dir():
    return Path(os.environ.get("SUNAK_DATA") or Path.home() / ".sunak")


def install_dir():
    """Folder the installer put the app (and on Windows the launcher) into."""
    if _windows():
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "sunak"
    app = _launcher_app_dir()
    if app is not None and app.name == "app":
        return app.parent
    return Path(os.environ.get("SUNAK_HOME") or Path.home() / ".sunak")


def launcher():
    return Path.home() / ".local" / "bin" / "sunak"


def _read(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _launcher_app_dir():
    for line in _read(launcher()).splitlines():
        if line.startswith('APP_DIR="') and line.endswith('"'):
            return Path(line[9:-1])
    return None


def program_files():
    """Files and folders of the installed program (never the data), whether they exist or not."""
    home, inst = Path.home(), install_dir()
    if _windows():
        files = [inst / n for n in ("app", "app.new", "sunak.cmd", "update.ps1", "source.txt", "Sunak.vbs")]
        start_menu = Path(os.environ.get("APPDATA", home)) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        desktops = {desktop.desktop_dir(), home / "OneDrive" / "Desktop", *_windows_desktop()}
        files += [start_menu / "Sunak.lnk"] + [d / n for d in sorted(desktops) for n in ("Sunak.lnk", "Sunak.vbs")]
        return files
    files = [inst / "app", inst / "app.new", inst / "source"]
    if _launcher_is_ours():
        files.append(launcher())
    if platform.system() == "Darwin":
        files.append(home / "Applications" / "Sunak.app")
        files += [d / "Sunak.app" for d in {desktop.desktop_dir(), home / "Desktop"} if (d / "Sunak.app").is_symlink()]
    else:
        menu = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share")) / "applications" / "sunak.desktop"
        for f in sorted({menu, desktop.desktop_dir() / "sunak.desktop", home / "Desktop" / "sunak.desktop"}):
            if "-m sunak" in _read(f):  # only our own icons
                files.append(f)
    return files


def _launcher_is_ours():
    return LAUNCHER_MARK in _read(launcher())


def _windows_desktop():
    """The desktop folder Windows really uses (OneDrive can move it), from the registry."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            return [Path(os.path.expandvars(winreg.QueryValueEx(k, "Desktop")[0]))]
    except (ImportError, OSError):
        return []


def _exists(p):
    return p.exists() or p.is_symlink()


def remove(path, out):
    """Delete a file, link or folder. True when it is gone afterwards."""
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    except FileNotFoundError:
        pass
    except OSError as e:
        out(f"  Could not remove {path}: {e.strerror or e}")
        return False
    out(f"  Removed {path}")
    return True


def remove_path_lines(rc):
    """Drop the PATH line install.sh added (and the blank line before it). True when the file changed."""
    text = _read(rc)
    if PATH_MARK not in text:
        return False
    kept = []
    for line in text.split("\n"):
        if PATH_MARK in line:
            if kept and kept[-1] == "":
                kept.pop()
            continue
        kept.append(line)
    rc.write_text("\n".join(kept), encoding="utf-8")
    return True


def windows_path_remove(folder):
    """Remove `folder` from the user's PATH in the registry. True when it was there."""
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                        winreg.KEY_READ | winreg.KEY_WRITE) as k:
        try:
            value, kind = winreg.QueryValueEx(k, "Path")
        except FileNotFoundError:
            return False
        norm = os.path.normcase(str(folder).rstrip("\\/"))
        parts = value.split(";")
        kept = [p for p in parts if os.path.normcase(p.strip().rstrip("\\/")) != norm]
        if len(kept) == len(parts):
            return False
        winreg.SetValueEx(k, "Path", 0, kind, ";".join(kept))
    try:  # tell Explorer, so new terminals see the change
        import ctypes
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "Environment", 2, 3000, None)
    except (ImportError, AttributeError, OSError):
        pass
    return True


# Docker ----------------------------------------------------------------------

def _docker(*args, timeout=60):
    try:
        r = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def docker_projects():
    """Docker Compose projects that run Sunak: [(project, working_dir)]."""
    if not shutil.which("docker"):
        return []
    out = _docker("ps", "-a", "--filter", "label=com.docker.compose.service=sunak", "--format",
                  '{{.Label "com.docker.compose.project"}}\t{{.Label "com.docker.compose.project.working_dir"}}')
    found = {}
    for line in (out or "").splitlines():
        name, _, folder = line.partition("\t")
        if name.strip():
            found[name.strip()] = folder.strip()
    return sorted(found.items())


def docker_remove(project, out):
    """Remove the containers, network and built image of a Compose project. The data folder stays."""
    ids = (_docker("ps", "-aq", "--filter", f"label=com.docker.compose.project={project}") or "").split()
    if ids and _docker("rm", "-f", *ids) is None:
        out(f"  Could not remove the Docker containers of '{project}'.")
        return False
    _docker("network", "rm", f"{project}_default")
    for image in (f"{project}-sunak", f"{project}_sunak"):  # Compose v2 / v1 names
        _docker("image", "rm", image)
    out(f"  Removed Docker containers of '{project}'")
    return True


# the command -----------------------------------------------------------------

def _stop_running(out):
    for port in range(7000, 7010):
        if desktop.running(port) and desktop.stop(port):
            out(f"  Stopped Sunak on port {port}")
            for _ in range(25):
                if not desktop.running(port):
                    break
                time.sleep(0.2)


def _safe_to_delete(folder):
    """Never delete the home folder, a folder above it, or a drive root (e.g. SUNAK_DATA=~ by mistake)."""
    try:
        real, home = folder.resolve(), Path.home().resolve()
    except OSError:
        return False
    return real != home and real not in home.parents and real.parent != real


def _size(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total / 1e9


def main(argv, ask=input, out=print):
    """Run the uninstall. `ask` reads an answer (EOF or Enter means the default). Returns the exit code."""
    flags = set(argv)
    if flags - {"--yes", "-y", "--purge"}:
        out(USAGE)
        return 2
    yes, purge = bool(flags & {"--yes", "-y"}), "--purge" in flags

    def confirm(question, default):
        try:
            answer = ask(f"{question} [{'Y/n' if default else 'y/N'}] ").strip().lower()
        except EOFError:
            answer = ""
        return default if not answer else answer.startswith("y")

    if not yes and not confirm("Uninstall Sunak from this computer? Your data is kept unless you say otherwise.", False):
        out("Nothing removed. (To uninstall without questions: --yes)")
        return 0
    try:
        os.chdir(Path.home())  # Windows cannot delete a folder that is the current directory
    except OSError:
        pass
    failed = False
    out("Removing Sunak…")
    _stop_running(out)
    if desktop.disable_autostart():
        out("  Removed autostart")

    inst = install_dir()
    for path in program_files():
        if _exists(path):
            failed |= not remove(path, out)
    if _windows():
        try:
            if windows_path_remove(inst):
                out(f"  Removed {inst} from PATH")
        except (ImportError, OSError) as e:
            out(f"  Could not update PATH: {e}")
    else:
        for rc in (".bashrc", ".bash_profile", ".zshrc", ".profile"):
            if remove_path_lines(Path.home() / rc):
                out(f"  Removed the PATH line from ~/{rc}")
    try:
        inst.rmdir()  # only when empty, i.e. no data left inside
    except OSError:
        pass

    data_folders = []
    for project, folder in docker_projects():
        if yes or confirm(f"Remove the Docker containers of Sunak (project '{project}' in {folder or '?'})?", False):
            failed |= not docker_remove(project, out)
        if folder:
            data_folders.append(Path(folder) / "data")

    for folder in [data_dir()] + data_folders:
        if not folder.is_dir():
            continue
        what = f"your chats, settings, API keys and mail accounts in {folder}"
        if not _safe_to_delete(folder):
            out(f"Kept {folder}: it is not a folder of its own (check SUNAK_DATA).")
        elif purge or (not yes and confirm(f"Also delete {what}? This cannot be undone.", False)):
            if not remove(folder, out):
                failed = True
                if not _windows():  # e.g. files the Ollama container wrote as root
                    out(f"  Delete it yourself, e.g. with: sudo rm -rf \"{folder}\"")
        else:
            out(f"Kept {what}. Delete that folder to remove them.")

    models = Path(os.environ.get("OLLAMA_MODELS") or Path.home() / ".ollama" / "models")
    if models.is_dir() and _safe_to_delete(models):
        if not yes and confirm(f"Also delete the downloaded Ollama models in {models} ({_size(models):.1f} GB)?", False):
            failed |= not remove(models, out)
        else:
            out(f"Kept the Ollama models in {models}.")
    if shutil.which("ollama"):
        out("Ollama stays installed (other programs may use it). To remove it: "
            + {"Windows": "Settings > Apps > Ollama > Uninstall.",
               "Darwin": "quit Ollama and move it from Applications to the Trash."}.get(
                platform.system(), "see https://github.com/ollama/ollama/blob/main/docs/linux.md#uninstall"))
    out("Some parts could not be removed, see above." if failed else "Sunak is uninstalled.")
    return 1 if failed else 0
