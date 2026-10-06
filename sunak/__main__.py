"""Start Sunak:  python -m sunak  [--port 7000] [--host 127.0.0.1] [--no-browser]

Other commands:  stop | status | gpu | autostart on|off|status | shortcut | version | uninstall [--yes] [--purge]"""

import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path

from . import __version__, desktop, gpu
from .server import make_server

PINK = "\033[38;5;205m" if sys.stdout.isatty() else ""
RESET = "\033[0m" if sys.stdout.isatty() else ""


COMMANDS = ("stop", "status", "gpu", "autostart", "shortcut", "version")


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
    try:
        port = int(os.environ.get("SUNAK_PORT") or 7000)
    except ValueError:
        sys.exit("SUNAK_PORT must be a number, e.g. 7000.")
    if argv and argv[0] == "update":
        sys.exit("'update' is part of the installed sunak command. Without installing: git pull in this folder.")
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

    ap = argparse.ArgumentParser(prog="sunak", description="Self-hosted AI workspace",
                                 epilog="Commands: sunak stop | status | gpu | autostart on|off | shortcut | version | uninstall")
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
    if args.host == "0.0.0.0":
        print("  Reachable from other devices on your network. Set a password in Settings!")
    print("  Press Ctrl+C to stop.\n")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    srv.RequestHandlerClass.app.check_updates()  # in the background; the page shows "Update available"
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    srv.server_close()
    print("\n  Bye 👋")
    return 0


if __name__ == "__main__":
    sys.exit(main())
