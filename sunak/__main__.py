"""Start Sunak:  python -m sunak  [--port 7000] [--host 127.0.0.1] [--no-browser]"""

import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path

from . import __version__
from .server import make_server

PINK = "\033[38;5;205m" if sys.stdout.isatty() else ""
RESET = "\033[0m" if sys.stdout.isatty() else ""


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sunak", description="Self-hosted AI workspace")
    ap.add_argument("--host", default=os.environ.get("SUNAK_HOST", "127.0.0.1"),
                    help="address to listen on (use 0.0.0.0 for your LAN / phone)")
    ap.add_argument("--port", type=int, default=int(os.environ.get("SUNAK_PORT", "7000")))
    ap.add_argument("--data-dir", default=os.environ.get("SUNAK_DATA", str(Path.home() / ".sunak")))
    ap.add_argument("--no-browser", action="store_true", default=bool(os.environ.get("SUNAK_NO_BROWSER")))
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args(argv)

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
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  Bye 👋")


if __name__ == "__main__":
    main()
