"""The sunak command: start Sunak (`python -m sunak [--port 7000] [--host 127.0.0.1] [--no-browser]`) or run
one of the commands in COMMANDS. `sunak -h` shows them all, `sunak <command> -h` the details of one."""

import argparse
import difflib
import os
import platform
import shutil
import sys
import threading
import webbrowser
from pathlib import Path

from . import __version__, changelog, desktop, gpu, log, updates
from .server import make_server


def _color():
    """ANSI colors only for a terminal, and never with NO_COLOR set (https://no-color.org)."""
    out = sys.stdout  # None under pythonw.exe (desktop icon, autostart on Windows)
    if out is None or not out.isatty() or os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return False
    if os.name == "nt":  # the Windows console shows colors only after switching them on
        try:
            import ctypes
            k = ctypes.windll.kernel32
            h, mode = k.GetStdHandle(-11), ctypes.c_uint32()
            return bool(k.GetConsoleMode(h, ctypes.byref(mode)) and k.SetConsoleMode(h, mode.value | 0x0004))
        except (AttributeError, OSError):
            return False
    return True


_COLOR = _color()


PINK = "\033[38;5;205m" if _COLOR else ""
BOLD = "\033[1m" if _COLOR else ""
DIM = "\033[2m" if _COLOR else ""
RESET = "\033[0m" if _COLOR else ""
DOCS = "https://github.com/M4XM77R/sunak#readme"

# Every command of `sunak`, in the order of the help. A new command only needs an entry here (and its code in
# run_command): it then appears in `sunak -h`, gets `sunak <command> -h` and the "Did you mean" hint.
COMMANDS = {
    "status": {"group": "Manage", "args": "[--port N]", "summary": "Is Sunak running? Address and autostart",
               "example": "sunak status"},
    "stop": {"group": "Manage", "args": "[--port N]", "summary": "Stop the running Sunak", "example": "sunak stop"},
    "update": {"group": "Manage", "args": "[--yes]", "summary": "Install the newest version", "example": "sunak update",
               "details": "Shows what is new (the changelog) and asks before it installs. Stops a running Sunak; start it\n"
                          "again afterwards. In the app, the Update button does the same.\n"
                          "  --yes, -y  do not ask (for scripts; without a terminal Sunak never asks)\n"
                          "Part of the installed sunak command. Without installing: run git pull in the Sunak folder."},
    "changelog": {"group": "Manage", "args": "[--confirm] [--yes]", "summary": "What the next update changes", "example": "sunak changelog",
                  "details": "Looks for a newer version and shows its changes from CHANGELOG.md, without installing anything.\n"
                             "When Sunak is up to date, it shows the changes of the installed version.\n"
                             "  --confirm  ask \"Install the update now? [y/N]\" afterwards (what `sunak update` does; exit code 3\n"
                             "             means no). With --yes, or without a terminal, it does not ask."},
    "version": {"group": "Manage", "args": "", "summary": "Print the installed version", "example": "sunak version"},
    "gpu": {"group": "Manage", "args": "", "summary": "Which graphics card Ollama can use", "example": "sunak gpu"},
    "mail-selftest": {"group": "Manage", "args": "[--account EMAIL] [--new] [--data-dir PATH] [--keep] [--yes]",
                      "summary": "Test a real mail account end to end", "example": "sunak mail-selftest --account me@gmail.com",
                      "details": "Logs in over IMAP and SMTP, reads the Inbox, checks the new-mail notice, sends a mail to\n"
                                 "the account itself with an attachment, receives it, forwards the attachment as a draft,\n"
                                 "moves and deletes. Only its own test messages are touched and deleted at the end.\n"
                                 "  --account EMAIL  which linked account (needed when several are linked)\n"
                                 "  --new            type in an address and an app password instead (not saved)\n"
                                 "  --data-dir PATH  Sunak's data folder (default ~/.sunak)\n"
                                 "  --keep           keep the test messages\n"
                                 "  --yes            do not ask before starting\n"
                                 "Gmail: turn on 2-Step Verification and create an app password at\n"
                                 "https://myaccount.google.com/apppasswords"},
    "logs": {"group": "Manage", "args": "[LINES] [--data-dir PATH]", "summary": "Where the log file is, and its last lines",
             "example": "sunak logs 100",
             "details": "Sunak writes what it does (start, requests, queue, pictures, errors) to the terminal it was\n"
                        "started from and to <data folder>/logs/sunak.log: five files of at most 10 MB, so 50 MB in all.\n"
                        "Never prompts, answers, passwords or keys. SUNAK_DEBUG=1 adds details (every request).\n"
                        "  LINES            how many lines to show (default 40)\n"
                        "  --data-dir PATH  Sunak's data folder (default ~/.sunak)"},
    "autostart": {"group": "Desktop", "args": "on|off|status", "summary": "Start Sunak when you log in (on|off|status)",
                  "example": "sunak autostart on",
                  "details": "  on      start Sunak in the background when you log in\n  off     do not start it any more\n"
                             "  status  show whether it is on (the default)"},
    "shortcut": {"group": "Desktop", "args": "", "summary": "Create the desktop icon again",
                 "example": "sunak shortcut"},
    "uninstall": {"group": "Remove", "args": "[--yes] [--purge] [--with-ollama] [--with-models]",
                  "summary": "Remove Sunak, asks before deleting data",
                  "example": "sunak uninstall", "details": None},  # details: uninstall.USAGE
    "help": {"group": "Help", "args": "<command>", "summary": "Details of a command", "example": "sunak help stop"},
}
GROUPS = ("Manage", "Desktop", "Remove", "Help")
OPTIONS = (  # options for starting Sunak
    ("--port N", "First port to try (default 7000)", "sunak --port 8123"),
    ("--host ADDRESS", "Address to listen on (default 127.0.0.1)", "sunak --host 0.0.0.0"),
    ("--data-dir PATH", "Folder for your data (default ~/.sunak)", "sunak --data-dir ~/ai"),
    ("--no-browser", "Do not open the browser", "sunak --no-browser"),
    ("-h, --help", "Show this help", "sunak -h"),
    ("--version", "Print the version", "sunak --version"),
)
ENV_VARS = ("SUNAK_PORT", "SUNAK_HOST", "SUNAK_DATA", "SUNAK_PASSWORD", "SUNAK_NO_BROWSER", "SUNAK_DEBUG",
            "SUNAK_ALLOWED_HOSTS", "SUNAK_MODEL_SLOTS", "SUNAK_REPORT_REPO", "OLLAMA_BASE_URL", "ANTHROPIC_API_KEY", "SEARXNG_URL", "NO_COLOR")
START_OPTIONS = ("--port", "--host", "--data-dir", "--no-browser", "--version", "--help", "-h")


def help_text(width=None):
    """The overview shown by `sunak -h`: one line per option and command with an example, grouped. When the
    terminal is too narrow for that, every example moves to its own line (all of them, so the columns stay)."""
    width = width or shutil.get_terminal_size((80, 24)).columns
    sections = [("Start options", list(OPTIONS))]
    for group in GROUPS:
        sections.append((group, [(name, c["summary"], c["example"]) for name, c in COMMANDS.items() if c["group"] == group]))
    rows = [r for _, rs in sections for r in rs]
    left_w = max(len(r[0]) for r in rows) + 3
    text_w = max(len(r[1]) for r in rows) + 2
    inline = 2 + left_w + text_w + max(len(r[2]) for r in rows) <= width
    lines = [f"{PINK}{BOLD}⛵ Sunak {__version__}{RESET} {DIM}·{RESET} your private AI workspace", "",
             f"{BOLD}Usage{RESET}",
             f"  {PINK}sunak{RESET} [options]             Start Sunak and open it in the browser",
             f"  {PINK}sunak{RESET} <command> [options]   Run a command"]
    for title, rs in sections:
        lines += ["", f"{BOLD}{title}{RESET}"]
        for left, text, example in rs:
            if inline:
                lines.append(f"  {PINK}{left.ljust(left_w)}{RESET}{text.ljust(text_w)}{DIM}{example}{RESET}")
            else:
                lines += [f"  {PINK}{left.ljust(left_w)}{RESET}{text}", f"  {' ' * left_w}{DIM}{example}{RESET}"]
    lines += ["", f"Details and options of a command: {PINK}sunak <command> -h{RESET}",
              f"Environment variables: {', '.join(ENV_VARS)}", f"Documentation: {DOCS}"]
    return "\n".join(lines)


def command_help(name):
    """The details shown by `sunak <command> -h`."""
    c = COMMANDS[name]
    if name == "uninstall":
        from . import uninstall
        details = uninstall.USAGE.split("\n", 1)[1]
    else:
        details = c.get("details") or ""
    lines = [f"{BOLD}Usage:{RESET} {PINK}sunak {name}{(' ' + c['args']) if c['args'] else ''}{RESET}", "", c["summary"] + "."]
    if details:
        lines += [""] + details.split("\n")
    if c["args"] == "[--port N]":
        lines += ["", "  --port N   where to look for Sunak: this port and the nine after it (default 7000, or SUNAK_PORT)"]
    lines += ["", f"{DIM}Example: {c['example']}{RESET}"]
    return "\n".join(lines)


def suggest(word, choices):
    """ "Did you mean …?" for a mistyped command or option, or ""."""
    match = difflib.get_close_matches(word, list(choices), n=1, cutoff=0.6)
    return f" Did you mean '{match[0]}'?" if match else ""


def fail(message):
    """A wrong command or option: say so on stderr, point to the help, exit code 2 (like argparse)."""
    print(f"{message} See: sunak -h", file=sys.stderr)
    return 2


def find_running(port):
    """(port, version) of a Sunak already running on this computer in port..port+9, or None."""
    for p in range(port, port + 10):
        v = desktop.running(p)
        if v:
            return p, v
    return None


def gpu_report(info):
    """Lines that tell the user which GPU Ollama can use (printed by `sunak gpu` and the installers)."""
    if info["hint"]:
        return [info["hint"]]
    if not info["usable"]:
        return ["No GPU that Ollama can use was found. Models run on the CPU; smaller models answer faster."]
    how = {"nvidia": "Ollama uses it automatically (CUDA, needs the NVIDIA driver).",
           "amd": "Ollama uses it automatically (ROCm, set up by the Ollama installer).",
           "apple": "Ollama uses the GPU automatically (Metal)."}[info["vendor"]]
    mem = "shares the main memory" if info["unified"] else f"{info['vram_gb']} GB VRAM"
    return [f"GPU: {info['name']} ({mem}). {how}"]


def logs_command(rest):
    """sunak logs [LINES] [--data-dir PATH]: where the log file is and its last lines."""
    data_dir, lines = os.environ.get("SUNAK_DATA", str(Path.home() / ".sunak")), 40
    i = 0
    while i < len(rest):
        if rest[i] == "--data-dir" and i + 1 < len(rest):
            data_dir, i = rest[i + 1], i + 2
        elif rest[i].isdigit():
            lines, i = max(1, min(int(rest[i]), 5000)), i + 1
        else:
            return fail(f"Unknown option '{rest[i]}'. Usage: sunak logs [LINES] [--data-dir PATH]")
    path = log.log_path(data_dir)
    last = log.tail(data_dir, lines)
    print(f"Log file: {path}")
    if last is None:
        print("There is no log yet. Start Sunak first.")
        return 0
    print("\n".join(last))
    return 0


def changelog_command(rest):
    """sunak changelog [--confirm] [--yes]: the changes of the next update, optionally asking before it installs
    (the `sunak update` launcher runs it first). Exit code 3 = the user said no; a check that does not work
    never stops an update."""
    flags = [a for a in rest if a in ("--confirm", "--yes", "-y")]
    if len(flags) != len(rest):
        return fail(f"Unknown option '{next(a for a in rest if a not in flags)}'. Usage: sunak changelog [--confirm] [--yes]")
    r = updates.inspect()
    confirm, behind = "--confirm" in flags, r["behind"]
    if behind is None:
        print("Could not look for a newer version (" + {"no_clone": "Sunak was not installed from a git clone",
              "no_remote": "no network or no access to the update source", "no_upstream": "the clone has no branch to compare with"}
              .get(r["error"], "unknown reason") + ").")
        if not confirm:
            return 1
    elif behind:
        print(f"Sunak {r['version'] or 'update'} is available (you have {__version__}, {behind} new change{'' if behind == 1 else 's'}).\n")
    elif not confirm:
        print(f"Sunak {__version__} is up to date.")
    if behind or behind is None:
        print(changelog.to_text(r["changelog"]) if r["changelog"] else "No changelog available.")
    elif not confirm:
        try:
            entries = changelog.between(changelog.parse((desktop.PKG_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")), "0.0.0", __version__)[:1]
        except OSError:
            entries = []
        if entries:
            print("\n" + changelog.to_text(entries))
    if not confirm or not behind:
        return 0
    if "--yes" in flags or "-y" in flags or not (sys.stdin.isatty() and sys.stdout.isatty()):
        return 0
    try:
        answer = input("\nInstall the update now? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer in ("y", "yes", "j", "ja"):
        return 0
    print("Update cancelled.")
    return 3


def run_command(cmd, rest, port):
    """Commands besides starting the server. Returns the exit code."""
    if cmd == "version":
        print(__version__)
    elif cmd == "status":
        found = find_running(port)
        print(f"Sunak {found[1]} is running at http://localhost:{found[0]}" if found else "Sunak is not running.")
        print("Autostart: " + ("on" if desktop.autostart_enabled() else "off"))
    elif cmd == "gpu":
        for line in gpu_report(gpu.summary(gpu.detect())):
            print(line)
    elif cmd == "stop":
        found = find_running(port)
        if not found:
            print("Sunak is not running.")
        elif desktop.stop(found[0]):
            print(f"Stopped Sunak on port {found[0]}.")
        else:
            print("Could not stop Sunak.")
            return 1
    elif cmd == "autostart":
        what = rest[0] if rest else "status"
        if what == "on":
            print(f"Sunak now starts in the background when you log in ({desktop.enable_autostart()}).")
        elif what == "off":
            print("Autostart removed." if desktop.disable_autostart() else "Autostart was not on.")
        elif what == "status":
            print("Autostart: " + ("on" if desktop.autostart_enabled() else "off"))
        else:
            print("Usage: sunak autostart on|off|status")
            return 2
    elif cmd == "shortcut":
        for path in desktop.create_shortcut():
            print(f"Created {path}")
    return 0


def main(argv=None):
    """Parse the command line, find a free port, start the server and open the browser.
    If Sunak already runs, just open it."""
    argv = list(sys.argv[1:] if argv is None else argv)
    for stream in (sys.stdout, sys.stderr):  # a redirected Windows console (cp1252) must not crash on the sailboat or other symbols
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        port = int(os.environ.get("SUNAK_PORT") or 7000)
    except ValueError:
        sys.exit("SUNAK_PORT must be a number, e.g. 7000.")
    if argv and argv[0] in ("-h", "--help", "help") and len(argv) == 1:
        print(help_text())
        return 0
    if argv and argv[0] in COMMANDS and any(a in ("-h", "--help") for a in argv[1:]):
        print(command_help(argv[0]))
        return 0
    if argv and argv[0] == "help":
        if argv[1] not in COMMANDS:
            return fail(f"Unknown command '{argv[1]}'.{suggest(argv[1], COMMANDS)}")
        print(command_help(argv[1]))
        return 0
    if argv and argv[0] == "update":
        sys.exit("'update' is part of the installed sunak command. Without installing: git pull in this folder.")
    if argv and argv[0] == "logs":
        return logs_command(argv[1:])
    if argv and argv[0] == "changelog":
        return changelog_command(argv[1:])
    if argv and argv[0] == "mail-selftest":
        from . import mailtest
        return mailtest.main(argv[1:])
    if argv and argv[0] == "uninstall":
        from . import uninstall
        return uninstall.main(argv[1:])
    if argv and argv[0] in COMMANDS:
        rest = argv[1:]
        if "--port" in rest[:-1]:  # e.g. sunak stop --port 8123
            i = rest.index("--port")
            if not rest[i + 1].isdigit():
                sys.exit("--port needs a number, e.g. --port 8123.")
            port = int(rest[i + 1])
            rest = rest[:i] + rest[i + 2:]
        return run_command(argv[0], rest, port)
    if argv and argv[0] not in COMMANDS and any(a in ("-h", "--help") for a in argv):
        print(help_text())
        return 0
    if argv and not argv[0].startswith("-"):
        return fail(f"Unknown command '{argv[0]}'.{suggest(argv[0], COMMANDS)}")
    for a in argv:
        name = a.split("=", 1)[0]
        if a.startswith("-") and name not in START_OPTIONS:
            return fail(f"Unknown option '{name}'.{suggest(name, START_OPTIONS)}")

    ap = argparse.ArgumentParser(prog="sunak", add_help=False)
    ap.add_argument("--host", default=os.environ.get("SUNAK_HOST", "127.0.0.1"),
                    help="address to listen on (use 0.0.0.0 for your LAN / phone)")
    ap.add_argument("--port", type=int, default=port)
    ap.add_argument("--data-dir", default=os.environ.get("SUNAK_DATA", str(Path.home() / ".sunak")))
    ap.add_argument("--no-browser", action="store_true", default=bool(os.environ.get("SUNAK_NO_BROWSER")))
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args(argv)

    found = find_running(args.port) if args.host in ("127.0.0.1", "0.0.0.0", "localhost") else None
    if found:
        url = f"http://localhost:{found[0]}"
        print(f"\n  {PINK}⛵ Sunak{RESET} is already running at {PINK}{url}{RESET} (stop it with: sunak stop)\n")
        if not args.no_browser:
            webbrowser.open(url)
        return 0

    log_file = log.setup(args.data_dir)

    def thread_crashed(info):  # a background thread died: log it (with its traceback) instead of printing it alone
        if info.exc_type is not SystemExit and not issubclass(info.exc_type, (BrokenPipeError, ConnectionError)):
            log.get("app").error("A background thread crashed", exc_info=(info.exc_type, info.exc_value, info.exc_traceback))
    threading.excepthook = thread_crashed
    srv = None
    for port in range(args.port, args.port + 10):
        try:
            srv = make_server(args.host, port, args.data_dir)
            break
        except OSError:
            continue
    if srv is None:
        sys.exit(f"Ports {args.port}-{args.port + 9} are all busy. Try --port 8123.")

    shown = "localhost" if args.host in ("127.0.0.1", "0.0.0.0") else args.host
    url = f"http://{shown}:{port}"
    print(f"\n  {PINK}⛵ Sunak {__version__}{RESET} is running at {PINK}{url}{RESET}")
    print(f"  Data: {args.data_dir}")
    if log_file:
        print(f"  Log:  {log_file} (sunak logs shows the end)")
    if args.host == "0.0.0.0":
        print("  Reachable from other devices on your network. Set a password in Settings!")
    print("  Press Ctrl+C to stop.\n")
    log.get("main").info("Sunak %s started on %s (Python %s, %s, data folder %s)", __version__, url,
                         platform.python_version(), platform.system(), args.data_dir)
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    app = srv.RequestHandlerClass.app
    app.restore_lan()  # phone access, if it was on
    if app.lan is not None:
        print(f"  Phone access is on: {PINK}{app.lan_info()['url']}{RESET}\n")
    srv.RequestHandlerClass.app.check_updates()  # in the background; the page shows "Update available"
    app.reminders.start()  # calendar reminders of the profiles that turned them on
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    srv.server_close()
    app.reminders.stop()
    app.mcp.close_all()
    log.get("main").info("Sunak stopped")
    print("\n  Bye 👋")
    return 0


if __name__ == "__main__":
    sys.exit(main())
