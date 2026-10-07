"""Logging: a readable log in the terminal Sunak was started from, and a log file that never grows past 50 MB.

Every line has a time, a level and the part of Sunak it comes from. The terminal shows INFO and up (with
SUNAK_DEBUG: DEBUG as well, which adds every page and polling request); the file has the same lines with the
date. The file is `<data folder>/logs/sunak.log`, rotated at 10 MB and kept in five pieces (together at most
50 MB), readable only by the user.

Nothing private goes into the log: no prompts or answers, no file or mail contents, no passwords, API keys or
tokens, no query strings. Requests are logged with method, path (without query), status and duration. As a
second line of defence every line passes `redact`, which also masks the API keys saved in the settings."""

import logging
import logging.handlers
import os
import re
import sys
import threading
import time
from pathlib import Path

LOG_NAME = "sunak.log"
MAX_BYTES = 10 * 1024 * 1024   # one file
BACKUPS = 4                    # + the current file = 50 MB at most
ROOT = "sunak"

_SECRETS = set()
_lock = threading.Lock()
_PATTERNS = (
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 ***"),
    (re.compile(r"(?i)\b(api[_-]?key|apikey|token|password|passwd|secret|authorization|cookie)(\"?\s*[=:]\s*\"?)[^\s\"',;&]+"), r"\1\2***"),
    (re.compile(r"(?i)([?&](?:key|api_key|apikey|token|access_token|password|auth)=)[^&\s\"']+"), r"\1***"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), "sk-***"),
    (re.compile(r"\b[A-Fa-f0-9]{32,}\b"), "***"),
)


def add_secret(value):
    """Mask this value (an API key from the settings) wherever it shows up in a log line."""
    if isinstance(value, str) and len(value) >= 6:
        with _lock:
            _SECRETS.add(value)


def redact(text):
    """`text` without secrets: known keys, `password=…`, bearer tokens, `sk-…` keys, long hex tokens."""
    text = str(text)
    with _lock:
        known = sorted(_SECRETS, key=len, reverse=True)
    for secret in known:
        text = text.replace(secret, "***")
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class _Formatter(logging.Formatter):
    """One line per event: time, level, part, message (and the traceback below it), secrets masked."""

    def __init__(self, date=False, color=False):
        super().__init__()
        self.date, self.color = date, color

    COLORS = {"DEBUG": "\033[90m", "INFO": "\033[32m", "WARNING": "\033[33m", "ERROR": "\033[31m", "CRITICAL": "\033[1;31m"}

    def format(self, record):
        when = time.strftime("%Y-%m-%d %H:%M:%S" if self.date else "%H:%M:%S", time.localtime(record.created))
        part = record.name[len(ROOT) + 1:] or "main"
        level = record.levelname
        if self.color:
            level = f"{self.COLORS.get(record.levelname, '')}{level:<7}\033[0m"
            when = f"\033[90m{when}\033[0m"
            part = f"\033[35m{part:<8}\033[0m"
        else:
            level, part = f"{level:<7}", f"{part:<8}"
        line = f"{when} {level} {part} {record.getMessage()}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return redact(line)


class _SafeFileHandler(logging.handlers.RotatingFileHandler):
    """Rotating file that only its owner can read."""

    def _open(self):
        stream = super()._open()
        try:
            os.chmod(self.baseFilename, 0o600)
        except OSError:
            pass
        return stream


def get(part):
    """The logger of one part of Sunak: log.get("queue") → sunak.queue."""
    return logging.getLogger(f"{ROOT}.{part}")


def log_dir(data_dir):
    return Path(data_dir) / "logs"


def log_path(data_dir):
    return log_dir(data_dir) / LOG_NAME


def setup(data_dir, debug=None, stream=None, max_bytes=MAX_BYTES, backups=BACKUPS):
    """Log to the terminal (stderr) and to <data_dir>/logs/sunak.log. Safe to call again (replaces its handlers).
    Returns the log file's path, or None when the file could not be opened (the terminal log still works)."""
    debug = bool(os.environ.get("SUNAK_DEBUG")) if debug is None else debug
    root = logging.getLogger(ROOT)
    for h in list(root.handlers):
        if getattr(h, "_sunak", False):
            root.removeHandler(h)
            h.close()
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    root.propagate = False
    out = stream or sys.stderr
    console = logging.StreamHandler(out)
    console.setFormatter(_Formatter(color=bool(getattr(out, "isatty", lambda: False)()) and not os.environ.get("NO_COLOR")))
    console._sunak = True
    root.addHandler(console)
    path = None
    try:
        log_dir(data_dir).mkdir(parents=True, exist_ok=True)
        handler = _SafeFileHandler(log_path(data_dir), maxBytes=max_bytes, backupCount=backups, encoding="utf-8")
        handler.setFormatter(_Formatter(date=True))
        handler._sunak = True
        root.addHandler(handler)
        path = log_path(data_dir)
    except OSError as e:
        root.warning("No log file (%s); logging to the terminal only", e.strerror or type(e).__name__)
    return path


def tail(data_dir, lines=40):
    """The last `lines` lines of the log file, or None when there is none."""
    try:
        with open(log_path(data_dir), "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 256 * 1024))
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    return data.splitlines()[-lines:]


logging.getLogger(ROOT).addHandler(logging.NullHandler())  # quiet until setup() runs (tests, library use)
