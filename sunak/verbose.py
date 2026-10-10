"""Verbose mode (`sunak --verbose`, `-v`, SUNAK_VERBOSE=1): every request in full, for finding out what really happens.

Logged: each HTTP request Sunak sends (to model backends, web search, calendar, GitHub, ...) with method, URL, headers,
body, and the answer (status, headers, body; a stream is logged as the assembled text when it ends), and each request
the Sunak server receives with its answer and duration. Output goes to the terminal (stderr) and, with `--log-file`,
to that file. This is NOT the normal log (`sunak.log`) and never reaches the error report (`log.recent`): it contains
your chats and prompts.

What stays hidden even here: API keys, passwords, tokens, cookies and the Authorization header (masked by name and by
the same patterns as the normal log), and bulky data such as pictures (base64) or binary files, which are replaced by
their size. Longer bodies are cut with the number of missing characters. Mail (IMAP/SMTP) is not HTTP and not logged."""

import io
import json
import logging
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import log

NAME = "sunak_verbose"      # deliberately not below "sunak": the normal log, its file and the report ring never see it
MAX_BODY = 20000            # characters of one body; more is cut
MAX_RECORD = 256 * 1024     # bytes remembered of one body while it passes
LONG_STRING = 300           # a JSON string this long made of base64 characters is replaced by its size
MAX_BYTES, BACKUPS = 10 * 1024 * 1024, 2

# Deny by default: only headers on this list are shown; every other value is masked (vendor headers carry keys,
# session ids and tokens under names nobody can list in advance).
SAFE_HEADERS = {"content-type", "content-length", "content-encoding", "accept", "accept-encoding", "accept-language",
                "user-agent", "host", "date", "server", "cache-control", "connection", "transfer-encoding",
                "x-requested-with", "etag", "last-modified", "vary", "retry-after"}
URL_HEADERS = {"location", "referer", "origin", "content-location"}
# Names whose value is hidden, whatever it holds (a whole list or object included). Word-bounded short names plus
# longer fragments; anything ending in "key" counts (anthropic_key, brave_key).
SECRET_KEY = re.compile(
    r"(?i)(?:^|[^a-z0-9])(?:pat|pins?|code|auth|jwt|key|sid|sig|otp|dsn)(?:$|[^a-z0-9])"
    r"|pass(?:word|wd|phrase|code)?|secret|token(?!s)|api[_-]?key|apikey|authoriz|cookie|credential|bearer|signature|session|private|key$|_key")
NAME_FIELDS = ("name", "key", "id", "header", "field", "label", "variable", "env")
BASE64 = re.compile(r"^(data:[^,]{0,80},)?[A-Za-z0-9+/_=\s-]+$")

_logger = logging.getLogger(NAME)
_logger.addHandler(logging.NullHandler())
_logger.propagate = False
_state = {"on": False, "installed": False}
_count = 0
_lock = threading.Lock()


def enabled():
    return _state["on"]


# redaction ----------------------------------------------------------------

def _secret_name(name):
    return isinstance(name, str) and bool(SECRET_KEY.search(name))


def _clean(value, depth=0):
    """Walk parsed JSON: a secret-looking key hides its whole value (lists and objects too), {"name": "API_KEY",
    "value": ...} pairs are hidden, JSON inside strings (tool call arguments) is cleaned, base64 blobs become sizes."""
    if depth > 30:
        return "<too deep>"
    if isinstance(value, dict):
        pair = any(_secret_name(value.get(f)) for f in NAME_FIELDS)
        out = {}
        for k, v in value.items():
            if v is not None and (_secret_name(k) or (pair and k.lower() in ("value", "val", "data", "content", "secret"))):
                out[k] = "***"
            else:
                out[k] = _clean(v, depth + 1)
        return out
    if isinstance(value, list):
        return [_clean(v, depth + 1) for v in value]
    if isinstance(value, str):
        if value.lstrip()[:1] in ("{", "["):
            try:
                return json.dumps(_clean(json.loads(value), depth + 1), ensure_ascii=False)
            except ValueError:
                pass
        if len(value) >= LONG_STRING and BASE64.match(value):
            return f"<{len(value)} characters of base64 data>"
    return value


def _params(text, sep="&"):
    """`a=1&secret=2` with secret-named parameters hidden (the rest stays exactly as written)."""
    out = []
    for part in text.split(sep):
        name, eq, val = part.partition("=")
        out.append(f"{name}=***" if eq and _secret_name(urllib.parse.unquote_plus(name)) and val != "" else part)
    return sep.join(out)


def _cut(text):
    return text if len(text) <= MAX_BODY else text[:MAX_BODY] + f"\n… ({len(text) - MAX_BODY} more characters)"


def body_text(data, ctype=""):
    """A body as safe, readable text: JSON cleaned up, other text masked, binary replaced by its size."""
    if data is None or data == b"":
        return "(empty)"
    if isinstance(data, str):
        data = data.encode("utf-8", "replace")
    if not isinstance(data, (bytes, bytearray)):
        return f"<{type(data).__name__} body>"
    if "json" not in (ctype or "").lower() and ("octet" in (ctype or "").lower() or b"\x00" in data[:2000]
                                                  or re.match(r"(image|audio|video)/|application/(pdf|zip)", (ctype or "").lower())):
        return f"<{len(data)} bytes of binary data ({ctype or 'unknown type'})>"
    try:
        text = bytes(data).decode("utf-8")
    except UnicodeDecodeError:
        return f"<{len(data)} bytes of binary data>"
    stripped = text.strip()
    if "x-www-form-urlencoded" in (ctype or "").lower():
        return _cut(log.redact(_params(stripped)))
    if stripped[:1] in "{[":
        try:
            return _cut(log.redact(json.dumps(_clean(json.loads(stripped)), ensure_ascii=False, indent=2)))
        except ValueError:
            pass
    lines = []  # NDJSON / server-sent events: clean line by line
    for line in text.splitlines():
        payload = line[5:].strip() if line.startswith("data:") else line.strip()
        if payload[:1] in "{[":
            try:
                lines.append(json.dumps(_clean(json.loads(payload)), ensure_ascii=False))
                continue
            except ValueError:
                pass
        lines.append(line)
    return _cut(log.redact("\n".join(lines)))


def header_lines(items):
    out = []
    for k, v in items:
        low = k.lower()
        if low in SAFE_HEADERS:
            shown = log.redact(v)
        elif low in URL_HEADERS:
            shown = url_text(v)
        else:
            shown = "***"
        out.append(f"    {k}: {shown}")
    return "\n".join(out) or "    (none)"


def url_text(url):
    """A URL without user:password@, with secret query and fragment parameters hidden."""
    try:
        sp = urllib.parse.urlsplit(url)
        netloc = sp.netloc
        if "@" in netloc:
            netloc = "***:***@" + netloc.rsplit("@", 1)[1]
        query = _params(sp.query)
        fragment = _params(sp.fragment) if "=" in sp.fragment else sp.fragment
        url = urllib.parse.urlunsplit((sp.scheme, netloc, sp.path, query, fragment))
    except ValueError:
        pass
    return log.redact(url)


# output ---------------------------------------------------------------------

def _next_id():
    global _count
    with _lock:
        _count += 1
        return _count


def emit(text):
    if _state["on"]:
        _logger.info(log.redact(text))


class _Format(logging.Formatter):
    def format(self, record):
        return f"{time.strftime('%H:%M:%S', time.localtime(record.created))}.{int(record.msecs):03d} {record.getMessage()}"


def enable(log_file=None, stream=None):
    """Switch verbose mode on (safe to call again). Returns the log file path or None."""
    for h in list(_logger.handlers):
        _logger.removeHandler(h)
        h.close()
    _logger.setLevel(logging.INFO)
    out = stream or sys.stderr  # None under pythonw.exe (autostart on Windows): then only the file
    if out is not None:
        console = logging.StreamHandler(out)
        console.setFormatter(_Format())
        _logger.addHandler(console)
    path = None
    if log_file:
        try:
            parent = os.path.dirname(os.path.abspath(log_file))
            os.makedirs(parent, exist_ok=True)
            handler = log._SafeFileHandler(log_file, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
            handler.setFormatter(_Format())
            _logger.addHandler(handler)
            path = log_file
        except OSError as e:
            _logger.info("No verbose log file (%s); terminal only", e.strerror or type(e).__name__)
    _state["on"] = True
    install()
    return path


def disable():
    _state["on"] = False
    for h in list(_logger.handlers):
        _logger.removeHandler(h)
        h.close()
    _logger.addHandler(logging.NullHandler())


def banner(path=None):
    return ("Verbose mode: every request and answer is shown in full, including your chats and prompts"
            + (f" (also written to {path})" if path else "")
            + ". Keys, passwords and tokens are masked; look the log over before you share it.")


# outgoing requests ---------------------------------------------------------------

class _Recorder:
    """File-like wrapper around a response: passes everything through and remembers the start of the body."""

    def __init__(self, resp, finish):
        self._resp, self._finish, self._buf, self._size, self._done = resp, finish, bytearray(), 0, False

    def _note(self, data):
        if data:
            self._size += len(data)
            if len(self._buf) < MAX_RECORD:
                self._buf += data[:MAX_RECORD - len(self._buf)]
        return data

    def read(self, *a):
        data = self._note(self._resp.read(*a))
        if not data and (not a or a[0] != 0):
            self._end()
        return data

    def read1(self, *a):
        return self._note(self._resp.read1(*a))

    def readline(self, *a):
        data = self._note(self._resp.readline(*a))
        if not data:
            self._end()
        return data

    def readlines(self, *a):
        return [self._note(line) for line in self._resp.readlines(*a)]

    def __iter__(self):
        return self

    def __next__(self):
        line = self.readline()
        if not line:
            raise StopIteration
        return line

    def _end(self):
        if not self._done:
            self._done = True
            try:
                self._finish(bytes(self._buf), self._size)
            except Exception:  # noqa: BLE001 - logging must never break a request
                pass

    def close(self):
        try:
            self._resp.close()
        finally:
            self._end()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __del__(self):
        try:
            self._end()
        except Exception:  # noqa: BLE001
            pass

    def __getattr__(self, name):
        return getattr(self._resp, name)


def _describe_body(data, size, ctype):
    text = body_text(data, ctype)
    if size > len(data):
        text += f"\n… (body is {size} bytes, the first {len(data)} were kept)"
    return text


def _wrap_open(original):
    def open(self, fullurl, data=None, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, *rest):
        args = (fullurl, data, timeout)
        if not _state["on"]:
            return original(self, *args, *rest)
        n = _next_id()
        req = fullurl if isinstance(fullurl, urllib.request.Request) else urllib.request.Request(fullurl)
        body = data if data is not None else req.data
        started = time.monotonic()
        try:
            emit(f"[{n}] → {req.get_method()} {url_text(req.full_url)}\n  headers:\n{header_lines(req.header_items())}\n"
                 f"  body: {body_text(body, req.get_header('Content-type') or req.get_header('Content-Type') or '')}")
        except Exception:  # noqa: BLE001
            pass
        try:
            resp = original(self, *args, *rest)
        except urllib.error.HTTPError as e:
            raw = b""
            try:
                raw = e.read()
            except Exception:  # noqa: BLE001
                pass
            emit(f"[{n}] ← {e.code} {e.reason} after {time.monotonic() - started:.2f}s\n  headers:\n{header_lines(list(e.headers.items()) if e.headers else [])}\n"
                 f"  body: {_describe_body(raw[:MAX_RECORD], len(raw), e.headers.get('Content-Type', '') if e.headers else '')}")
            raise urllib.error.HTTPError(e.url, e.code, e.msg, e.headers, io.BytesIO(raw)) from None
        except Exception as e:  # noqa: BLE001 - the original error goes on unchanged
            emit(f"[{n}] ✗ {type(e).__name__}: {e} after {time.monotonic() - started:.2f}s")
            raise
        ctype = resp.headers.get("Content-Type", "") if getattr(resp, "headers", None) else ""
        emit(f"[{n}] ← {getattr(resp, 'status', '?')} {getattr(resp, 'reason', '')} after {time.monotonic() - started:.2f}s\n"
             f"  headers:\n{header_lines(list(resp.headers.items()) if getattr(resp, 'headers', None) else [])}")

        def finish(buf, size):
            emit(f"[{n}] ← body ({size} bytes, {time.monotonic() - started:.2f}s in all):\n{_describe_body(buf, size, ctype)}")
        return _Recorder(resp, finish)
    return open


def install():
    """Hook urllib once: every urlopen / opener.open (also the pinned one of web search) goes through it."""
    if _state["installed"]:
        return
    _state["installed"] = True
    urllib.request.OpenerDirector.open = _wrap_open(urllib.request.OpenerDirector.open)


# incoming requests (the Sunak server) --------------------------------------------------

class Tap:
    """Wraps rfile/wfile of one handler to remember what passes."""

    def __init__(self, stream):
        self._s, self.buf, self.size = stream, bytearray(), 0

    def _note(self, data):
        if data:
            self.size += len(data)
            if len(self.buf) < MAX_RECORD:
                self.buf += data[:MAX_RECORD - len(self.buf)]
        return data

    def read(self, *a):
        return self._note(self._s.read(*a))

    def readline(self, *a):
        return self._note(self._s.readline(*a))

    def write(self, data):
        self._note(bytes(data))
        return self._s.write(data)

    def __getattr__(self, name):
        return getattr(self._s, name)


def log_incoming(handler, method, path, started, rtap, wtap, status):
    """One request the Sunak server handled: headers and body in, status, headers and body out."""
    n = _next_id()
    took = time.monotonic() - started
    is_api = path.startswith("/api/")
    who = handler.client_address[0] if getattr(handler, "client_address", None) else "?"
    inbound = f"[{n}] ⇐ {method} {url_text(handler.path)} from {who}"
    if not is_api:  # pages and scripts: a line is enough
        emit(f"{inbound}\n[{n}] ⇒ {status} ({wtap.size} bytes sent, {took:.2f}s)")
        return
    ctype = handler.headers.get("Content-Type", "")
    head, _, rest = bytes(wtap.buf).partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")[1:]
    out_headers = [tuple(x.strip() for x in line.split(":", 1)) for line in lines if ":" in line]
    out_type = next((v for k, v in out_headers if k.lower() == "content-type"), "")
    sent = max(0, wtap.size - len(head) - 4)
    emit(f"{inbound}\n  headers:\n{header_lines(list(handler.headers.items()))}\n  body: {_describe_body(bytes(rtap.buf), rtap.size, ctype)}\n"
         f"[{n}] ⇒ {status} after {took:.2f}s\n  headers:\n{header_lines(out_headers)}\n  body: {_describe_body(rest, sent, out_type)}")
