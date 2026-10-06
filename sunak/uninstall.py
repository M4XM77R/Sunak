"""Remove Sunak from this computer:  sunak uninstall [--yes] [--purge] [--with-ollama] [--with-models]

Removes the program: the `sunak` command, the app folder, desktop and menu icons, autostart and the
PATH entry, and (after asking) Sunak's Docker container. Everything else is a question of its own
whose answer defaults to keeping it: your data (chats, settings, API keys, mail accounts), Ollama
(native or its Docker container), and the downloaded Ollama models. Without a terminal nothing of that
is deleted. Safe to run twice: whatever is already gone is skipped."""

import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

from . import desktop

PATH_MARK = "# sunak PATH"  # written by install.sh into the shell start files
LAUNCHER_MARK = "Sunak launcher"
SERVICE_MODELS = Path("/usr/share/ollama/.ollama/models")  # where the Linux Ollama service keeps its models
USAGE = """Usage: sunak uninstall [--yes] [--purge] [--with-ollama] [--with-models]
  --yes          no questions: remove the program, keep your data, Ollama and its models
  --purge        also delete your data
  --with-ollama  also uninstall Ollama (and remove its Docker container)
  --with-models  also delete the downloaded Ollama models"""


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


def docker_containers(project, service):
    return (_docker("ps", "-aq", "--filter", f"label=com.docker.compose.project={project}",
                    "--filter", f"label=com.docker.compose.service={service}") or "").split()


def docker_remove(project, service, out):
    """Remove the containers of one Compose service and their image. Data folders stay."""
    ids = docker_containers(project, service)
    images = [i for i in (_docker("inspect", "-f", "{{.Image}}", *ids) or "").split()] if ids else []
    if ids and _docker("rm", "-f", *ids) is None:
        out(f"  Could not remove the Docker container '{service}' of '{project}'.")
        return False
    if service == "sunak":
        images += [f"{project}-sunak", f"{project}_sunak"]  # built by Compose v2 / v1
    for image in images:
        _docker("image", "rm", image)  # fails harmlessly when something else still uses it
    _docker("network", "rm", f"{project}_default")  # only works once no container uses it
    out(f"  Removed the Docker container '{service}' of '{project}'")
    return True


# Ollama ----------------------------------------------------------------------

def _run(cmd, out):
    """Run a command with the terminal attached (sudo may ask for a password). True on success."""
    try:
        return subprocess.run(cmd).returncode == 0
    except OSError as e:
        out(f"  Could not run {cmd[0]}: {e.strerror or e}")
        return False


def _quiet(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def ollama_install():
    """How Ollama is installed on this computer (not in Docker): a dict with 'how', or None."""
    system, exe = platform.system(), shutil.which("ollama")
    if system == "Windows":
        folder = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Programs" / "Ollama"
        if (folder / "unins000.exe").exists():
            return {"how": "inno", "uninstaller": folder / "unins000.exe"}
        if exe or folder.exists():
            return {"how": "winget" if shutil.which("winget") else "manual"}
        return None
    if system == "Darwin":
        if shutil.which("brew"):
            if _quiet(["brew", "list", "--cask", "ollama"]):
                return {"how": "brew-cask"}
            if _quiet(["brew", "list", "--formula", "ollama"]):
                return {"how": "brew"}
        apps = [p for p in (Path("/Applications/Ollama.app"), Path.home() / "Applications" / "Ollama.app") if p.exists()]
        return {"how": "app", "apps": apps, "exe": exe} if apps or exe else None
    if not exe:
        return None
    if exe.startswith("/snap/"):
        return {"how": "snap"}
    if Path("/etc/systemd/system/ollama.service").exists() or Path(exe).parent == Path("/usr/local/bin"):
        return {"how": "script", "exe": exe}  # the official install.sh from ollama.com
    return {"how": "manual", "exe": exe}  # a distribution package: its package manager removes it


def ollama_commands(info):
    """Commands that remove Ollama, or a hint (str) when that has to be done by hand."""
    how = info["how"]
    if how == "inno":
        return [["taskkill", "/F", "/IM", "ollama app.exe"], ["taskkill", "/F", "/IM", "ollama.exe"],
                [str(info["uninstaller"]), "/VERYSILENT", "/NORESTART"]]
    if how == "winget":
        return [["taskkill", "/F", "/IM", "ollama app.exe"], ["taskkill", "/F", "/IM", "ollama.exe"],
                ["winget", "uninstall", "-e", "--id", "Ollama.Ollama", "--silent", "--accept-source-agreements"]]
    if how == "brew-cask":
        return [["brew", "uninstall", "--cask", "ollama"]]
    if how == "brew":
        return [["brew", "services", "stop", "ollama"], ["brew", "uninstall", "ollama"]]
    if how == "app":
        cmds = [["osascript", "-e", 'quit app "Ollama"']] + [["rm", "-rf", str(a)] for a in info["apps"]]
        if info["exe"] and ".app/" in os.path.realpath(info["exe"]):  # the link the app puts in /usr/local/bin
            cmds.append(["rm", "-f", info["exe"]])
        return cmds
    sudo = [] if hasattr(os, "geteuid") and os.geteuid() == 0 else ["sudo"]
    if how == "snap":
        return [sudo + ["snap", "remove", "ollama"]]
    if how == "script":
        exe = Path(info["exe"])
        return [sudo + ["systemctl", "stop", "ollama"], sudo + ["systemctl", "disable", "ollama"],
                sudo + ["rm", "-f", "/etc/systemd/system/ollama.service", str(exe)],
                sudo + ["rm", "-rf", str(exe.parent.parent / "lib" / "ollama")],
                sudo + ["userdel", "ollama"], sudo + ["groupdel", "ollama"]]
    if platform.system() == "Windows":
        return "Remove it in Settings > Apps > Ollama > Uninstall."
    return f"Remove it with your package manager (it is at {info.get('exe')})."


def _best_effort(cmd):
    """Steps that may fail without harm: stopping what is not running, a user that does not exist."""
    c = cmd[1:] if cmd[0] == "sudo" else cmd
    return c[0] in ("taskkill", "osascript", "userdel", "groupdel") or c[:2] in (["systemctl", "stop"], ["systemctl", "disable"]) \
        or c[:3] == ["brew", "services", "stop"]


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
    if flags - {"--yes", "-y", "--purge", "--with-ollama", "--with-models"}:
        out(USAGE)
        return 2
    yes, purge = bool(flags & {"--yes", "-y"}), "--purge" in flags
    with_ollama, with_models = "--with-ollama" in flags, "--with-models" in flags

    def confirm(question, default):
        try:
            answer = ask(f"{question} [{'Y/n' if default else 'y/N'}] ").strip().lower()
        except EOFError:
            answer = ""
        return default if not answer else answer.startswith("y")

    def decide(flag, question):
        """Flag given: yes. --yes without the flag: no. Otherwise ask, default no."""
        return flag or (not yes and confirm(question, False))

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

    # Docker: Sunak's container, then (separately) the Ollama container next to it
    data_folders, models = [], []
    for project, folder in docker_projects():
        where = f"project '{project}' in {folder or '?'}"
        if yes or confirm(f"Remove Sunak's Docker container ({where})?", False):
            failed |= not docker_remove(project, "sunak", out)
        if docker_containers(project, "ollama"):
            if decide(with_ollama, f"Also remove the Ollama Docker container ({where})? Other setups may use it."):
                failed |= not docker_remove(project, "ollama", out)
            else:
                out(f"Kept the Ollama Docker container of '{project}'.")
        if folder:
            data_folders.append(Path(folder) / "data")
            models.append(Path(folder) / "data" / "ollama")  # models of the Ollama container

    # Sunak's data: chats, settings, API keys, mail accounts
    for folder in [data_dir()] + data_folders:
        if not folder.is_dir():
            continue
        what = f"your chats, settings, API keys and mail accounts in {folder}"
        if not _safe_to_delete(folder):
            out(f"Kept {folder}: it is not a folder of its own (check SUNAK_DATA).")
        elif purge or (not yes and confirm(f"Also delete {what}? This cannot be undone.", False)):
            # Docker's data folder also holds the Ollama models: those have their own question below
            parts = [p for p in folder.iterdir() if p not in models] if folder in data_folders else [folder]
            for part in parts:
                if not remove(part, out):
                    failed = True
                    if not _windows():  # e.g. files a container wrote as root
                        out(f"  Delete it yourself, e.g. with: sudo rm -rf \"{part}\"")
        else:
            out(f"Kept {what}. Delete that folder to remove them.")

    # Ollama itself: only when the user says so, because other programs may use it
    info = ollama_install()
    if info:
        if decide(with_ollama, "Also uninstall Ollama? Other programs may use it."):
            cmds = ollama_commands(info)
            if isinstance(cmds, str):
                out("  " + cmds)
                failed = True
            else:
                out("Uninstalling Ollama…")
                for cmd in cmds:
                    if not _run(cmd, out) and not _best_effort(cmd):
                        failed = True
                        out("  Failed: " + " ".join(cmd))
                if _windows():
                    out("  Ollama's uninstaller has run.")
                else:
                    out("  Ollama is uninstalled." if not shutil.which("ollama") else "  Ollama may still be installed, see above.")
        else:
            out("Kept Ollama (other programs may use it).")

    # downloaded models: big, and usable again after reinstalling Ollama, so a question of their own
    models = [Path(os.environ.get("OLLAMA_MODELS") or Path.home() / ".ollama" / "models"),
              SERVICE_MODELS] + models
    for folder in dict.fromkeys(models):
        if not folder.is_dir() or not _safe_to_delete(folder):
            continue
        if decide(with_models, f"Also delete the downloaded Ollama models in {folder} ({_size(folder):.1f} GB)?"):
            if not remove(folder, out):
                failed = True
                if not _windows():
                    out(f"  Delete them yourself, e.g. with: sudo rm -rf \"{folder}\"")
        else:
            out(f"Kept the Ollama models in {folder}.")
    out("Some parts could not be removed, see above." if failed else "Sunak is uninstalled.")
    return 1 if failed else 0
