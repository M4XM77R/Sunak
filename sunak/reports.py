"""Error reports: unexpected errors become GitHub issues, so they can be found and fixed later.

Off by default (Settings → Error reports). Three modes: "off", "ask" (errors wait in Settings, the user sends or
dismisses each one) and "auto" (an error is sent at once when an access token is saved).

What a report contains: Sunak version, operating system, Python version, the error type and message, the stack
trace (file names inside Sunak, function names and Sunak's own source lines, no variable values) and the last log
lines. Never chats, prompts, mail or file contents, API keys, passwords or tokens. The issues are PUBLIC (the repository
is open), so everything passes a strict `anonymize` (private paths, user and host names, host names in addresses except well
known ones, IP and MAC addresses, e-mail addresses, long quoted texts) and `log.redact` before it is stored or shown.

Same error = same fingerprint (error type + the Sunak functions of the stack, no line numbers, so it survives
updates): the first report opens an issue, later ones add a short comment (at most one per day per error).
At most MAX_ISSUES_PER_HOUR new issues are opened per hour.

The access token (a fine-grained GitHub token that may only write issues of one repository) is saved in the
settings on this computer, never logged and never sent to the browser."""

import hashlib
import json
import logging
import os
import platform
import re
import socket
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import __version__, log

logger = log.get("reports")

REPO = os.environ.get("SUNAK_REPORT_REPO", "M4XM77R/Sunak")
API = "https://api.github.com"
LABEL = "auto-report"
STATE_FILE = "reports.json"
MAX_PENDING = 20
MAX_ISSUES_PER_HOUR = 3
COMMENT_EVERY = 24 * 3600   # a known error adds at most one comment per day
LOG_LINES = 30
MAX_MESSAGE = 200
MAX_TRACE_FRAMES = 25
URL_LIMIT = 6000            # the prefilled issue address must stay short enough for browsers and GitHub
TIMEOUT = 20
SKIP_NAMES = {"localhost", "root", "sunak", "python", "user", "users", "home"}  # too common to mask as a name
PKG_DIR = Path(__file__).resolve().parent

_local = threading.local()
_app = None
_lock = threading.RLock()


class ReportError(ValueError):
    """Sending did not work; the message is meant for the user (the server answers it as a 400)."""


# --- anonymising -------------------------------------------------------------------------------
# The issues are public: everybody can read them. So this is strict: private paths, host names, addresses and anything
# that looks like quoted text (it could be part of a chat or a document) are replaced before a report is stored.
SAFE_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "github.com", "api.github.com", "raw.githubusercontent.com", "huggingface.co",
              "ollama.com", "registry.ollama.ai", "api.anthropic.com", "api.openai.com", "duckduckgo.com", "html.duckduckgo.com"}
_FILE_END = r"[^\n\"'`:,;)\]]{0,160}?\.(?:pdf|docx?|xlsx?|pptx?|odt|txt|md|csv|json|png|jpe?g|gif|webp|zip|py|js|html?|log|eml)\b"
_PRIVATE_PATH = re.compile(r"(?:(?<![\w./-])(?:/(?:home|Users|root|tmp|var|mnt|opt|etc|usr|srv|media|private|Volumes)\b|~)(?:" + _FILE_END + r"|[^\s\"'`:,;)\]]*)"
                           r"|\b[A-Za-z]:[\\/](?:" + _FILE_END + r"|[^\s\"'`:,;)\]]*))", re.I)
_URL_HOST = re.compile(r"(?i)(\bhttps?://)([^/\s:@\"'`]+)")
_PATTERNS = (
    (re.compile(r"(?<=://)[^/\s@:]+:[^/\s@]+@"), "***@"),                     # user:password@host
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "<email>"),
    (re.compile(r"\b(?!127\.0\.0\.1\b|0\.0\.0\.0\b)\d{1,3}(?:\.\d{1,3}){3}\b"), "<ip>"),
    (re.compile(r"(?i)\b[0-9a-f]{1,4}(?::[0-9a-f]{0,4}){3,7}\b"), "<ip>"),    # IPv6
    (re.compile(r"(?i)\b[0-9a-f]{2}(?:[:-][0-9a-f]{2}){5}\b"), "<mac>"),
    (re.compile(r"(?i)\b[\w-]+\.(?:local|lan|home|internal|intranet|fritz\.box|localdomain)\b"), "<host>"),
)
_QUOTED = re.compile(r"([\"'`])(?:(?!\1)[^\n]){25,}\1")   # a long quoted text could be part of a chat or a document


def _mask_host(m):
    return m.group(1) + (m.group(2) if m.group(2).lower() in SAFE_HOSTS else "<host>")


def anonymize(text, extra=()):
    """`text` without private paths, user names, host names, addresses, long quoted texts and secrets."""
    text = _PRIVATE_PATH.sub("<path>", str(text))
    names = {str(n): "<user>" for n in extra}
    for getter, mark in ((lambda: str(Path.home()), "<path>"), (socket.gethostname, "<host>"),
                         (lambda: os.environ.get("USER") or os.environ.get("USERNAME") or "", "<user>")):
        try:
            names[getter()] = mark
        except Exception:  # noqa: BLE001 - not knowing a name is fine
            pass
    for name in sorted((n for n in names if len(n) >= 3 and n.lower() not in SKIP_NAMES), key=len, reverse=True):
        text = text.replace(name, names[name])
    text = _URL_HOST.sub(_mask_host, text)
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    text = _QUOTED.sub("<text>", text)
    return log.redact(text)


def _frame_name(filename):
    """A file name that says where it is without saying who owns the computer."""
    p = Path(filename)
    try:
        return "sunak/" + p.resolve().relative_to(PKG_DIR).as_posix()
    except (ValueError, OSError):
        pass
    parts = p.parts
    if "site-packages" in parts:
        return "/".join(parts[parts.index("site-packages") + 1:])
    return "/".join(parts[-2:]) if len(parts) > 1 else p.name


def _is_sunak(filename):
    try:
        Path(filename).resolve().relative_to(PKG_DIR)
        return True
    except (ValueError, OSError):
        return False


def describe(exc_info):
    """(error line, trace text, [Sunak frames as 'file:function']) of an exception, anonymised."""
    etype, value, tb = exc_info
    frames = traceback.extract_tb(tb)[-MAX_TRACE_FRAMES:]
    lines, own = [], []
    for fr in frames:
        mine = _is_sunak(fr.filename)
        name = _frame_name(fr.filename)
        lines.append(f"{name}:{fr.lineno} in {fr.name}")
        if mine and fr.line:
            lines.append("    " + fr.line.strip())  # only Sunak's own source, never other code or variable values
        if mine:
            own.append(f"{name}:{fr.name}")
    message = " ".join(str(value).split())[:MAX_MESSAGE]
    error = f"{etype.__name__}: {message}" if message else etype.__name__
    return anonymize(error), anonymize("\n".join(lines)), own


def fingerprint(exc_info, own):
    """Short id of an error: its type and the Sunak functions it went through (no line numbers, no message)."""
    key = exc_info[0].__name__ + "|" + "|".join(own[-4:] or ["-"])
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def build(exc_info, lines=None):
    """A report (dict) for an exception: title, body (Markdown), fingerprint. Nothing is sent."""
    error, trace, own = describe(exc_info)
    fp = fingerprint(exc_info, own)
    where = own[-1].replace("sunak/", "") if own else "unknown place"
    title = f"[{LABEL}] {exc_info[0].__name__} in {where} ({fp})"
    recent = [anonymize(l)[:300] for l in (log.recent(LOG_LINES) if lines is None else lines)]
    body = "\n".join([
        f"**Sunak** {__version__} · **System** {platform.system()} {platform.release()} ({platform.machine()}) · "
        f"**Python** {platform.python_version()}",
        "", "## Error", "", f"`{error}`", "", "## Stack trace", "", "```", trace, "```", "",
        "## Last log lines", "", "```", "\n".join(recent) or "(none)", "```", "",
        f"<!-- sunak-fingerprint: {fp} -->",
        "_Sent by Sunak's error reports (this issue is public). It contains no chats, prompts, mail contents, keys or passwords; "
        "private paths, host names, IP addresses and long quoted texts are masked._",
    ])
    return {"fp": fp, "title": title, "body": body, "error": error}


def issue_url(report):
    """A GitHub address that opens a prefilled new issue in the browser (no token needed)."""
    body = report["body"]
    base = f"https://github.com/{REPO}/issues/new?" + urllib.parse.urlencode({"title": report["title"], "labels": LABEL})
    while len(base) + len(urllib.parse.quote(body)) + 6 > URL_LIMIT and len(body) > 600:
        body = body[: int(len(body) * 0.8)] + "\n…(cut)"
    return base + "&body=" + urllib.parse.quote(body)


# --- GitHub ------------------------------------------------------------------------------------
def _github(token, method, path, data=None):
    """One GitHub API call; returns the decoded JSON. Raises ReportError with a message for the user."""
    req = urllib.request.Request(API + path, method=method, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"Sunak/{__version__}", **({"Content-Type": "application/json"} if data is not None else {})},
        data=None if data is None else json.dumps(data).encode())
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise ReportError("GitHub refused the token. It needs the permission “Issues: Read and write” for the Sunak repository.") from None
        if e.code == 404:
            raise ReportError("GitHub does not know the repository, or the token cannot see it.") from None
        raise ReportError("GitHub answered with error %d." % e.code) from None
    except (urllib.error.URLError, OSError, ValueError):
        raise ReportError("GitHub could not be reached (no network?).") from None


def check_token(token):
    """Raises ReportError when the token cannot read the issues of REPO."""
    _github(token, "GET", f"/repos/{REPO}/issues?per_page=1&state=all")


def find_issue(token, fp):
    """(number, state) of the issue that carries this fingerprint in its title, or None. Looks at the last 300 issues."""
    for page in (1, 2, 3):
        items = _github(token, "GET", f"/repos/{REPO}/issues?state=all&per_page=100&page={page}") or []
        for it in items:
            if "pull_request" not in it and f"({fp})" in (it.get("title") or ""):
                return it["number"], it.get("state", "open")
        if len(items) < 100:
            break
    return None


def clean_token(token):
    if token is None or token == "":
        return ""
    if not isinstance(token, str):
        raise ValueError("The token must be text")
    token = token.strip()
    if not re.fullmatch(r"[A-Za-z0-9_\-]{20,255}", token):
        raise ValueError("That does not look like a GitHub token (letters, digits and _ only, no spaces)")
    return token


# --- the store -----------------------------------------------------------------------------------
class Reports:
    """Pending and sent reports of one installation (<data>/reports.json), and the sending."""

    def __init__(self, app):
        self.app = app
        self.path = Path(app.data_dir) / STATE_FILE
        self.sending = set()

    # state
    def _load(self):
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return {"pending": d.get("pending") or {}, "sent": d.get("sent") or {}, "opened": d.get("opened") or []}
        except (OSError, ValueError):
            pass
        return {"pending": {}, "sent": {}, "opened": []}

    def _save(self, st):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(st), encoding="utf-8")
        os.replace(tmp, self.path)

    def mode(self):
        m = self.app.settings().get("error_reports", "off")
        return m if m in ("ask", "auto") else "off"

    def token(self):
        return self.app.main.get_setting("report_token") or ""

    def set_token(self, token):
        token = clean_token(token)
        self.app.main.set_setting("report_token", token)
        if token:
            log.add_secret(token)

    def state(self):
        with _lock:
            st = self._load()
        pending = sorted(st["pending"].values(), key=lambda r: r["last"], reverse=True)
        sent = sorted(st["sent"].values(), key=lambda r: r["time"], reverse=True)[:10]
        return {"mode": self.mode(), "token_set": bool(self.token()), "repo": REPO,
                "pending": [dict(r, url=issue_url(r)) for r in pending], "sent": sent}

    def pending_count(self):
        with _lock:
            return len(self._load()["pending"])

    # capture
    def capture(self, exc_info, sample=False):
        """Remember an error. Returns the fingerprint, or None when reports are off or the error is already known."""
        if not sample and self.mode() == "off":
            return None
        report = build(exc_info)
        if sample:
            report["title"] = report["title"].replace(f"[{LABEL}]", f"[{LABEL}] [sample]", 1)
        fp, now = report["fp"], time.time()
        with _lock:
            st = self._load()
            if fp in st["sent"] and not sample:
                st["sent"][fp]["count"] = st["sent"][fp].get("count", 1) + 1
                self._save(st)
                self._maybe_comment(fp, report, st)
                return None
            if fp in st["pending"]:
                st["pending"][fp]["count"] += 1
                st["pending"][fp]["last"] = now
                self._save(st)
                return None
            st["pending"][fp] = dict(report, count=1, first=now, last=now, version=__version__, sample=sample)
            for old in sorted(st["pending"].values(), key=lambda r: r["last"])[:-MAX_PENDING]:
                st["pending"].pop(old["fp"], None)
            self._save(st)
        logger.info("Error report %s is ready (%s)", fp, "waits for your OK in Settings" if self.mode() != "auto" or not self.token() else "sending")
        if self.mode() == "auto" and self.token() and not sample:
            threading.Thread(target=self._auto, args=(fp,), daemon=True).start()
        return fp

    def _auto(self, fp):
        try:
            self.send(fp)
        except ReportError as e:
            logger.warning("Error report %s was not sent: %s", fp, e)

    def _maybe_comment(self, fp, report, st):
        """A known error came again: one short comment per day, only in auto mode."""
        info = st["sent"][fp]
        if self.mode() != "auto" or not self.token() or time.time() - info.get("commented", info["time"]) < COMMENT_EVERY:
            return
        threading.Thread(target=self._comment_thread, args=(fp,), daemon=True).start()

    def _comment_thread(self, fp):
        try:
            self._comment(fp)
        except ReportError as e:
            logger.warning("Comment on the issue of error %s failed: %s", fp, e)

    def _comment(self, fp):
        with _lock:
            st = self._load()
            info = st["sent"].get(fp)
            if not info or not info.get("number") or self._limited(st, comment=True):
                return
            info["commented"] = time.time()
            st["opened"].append(["c", time.time()])
            self._save(st)
        text = f"Seen again: {info.get('count', 1)} times so far on this computer. Sunak {__version__}, {platform.system()}, Python {platform.python_version()}."
        _github(self.token(), "POST", f"/repos/{REPO}/issues/{info['number']}/comments", {"body": text})

    @staticmethod
    def _limited(st, comment=False):
        now = time.time()
        st["opened"] = [o for o in st["opened"] if now - o[1] < 24 * 3600]
        if comment:
            return sum(1 for o in st["opened"] if o[0] == "c") >= 10
        return sum(1 for o in st["opened"] if o[0] == "i" and now - o[1] < 3600) >= MAX_ISSUES_PER_HOUR

    # sending
    def send(self, fp):
        """Send one pending report: comment on its issue when it exists, else open a new one.
        Returns {"url", "number", "action": "created"|"commented"}."""
        token = self.token()
        if not token:
            raise ReportError("No GitHub token is saved. Save one, or use “Open on GitHub”.")
        with _lock:
            st = self._load()
            report = st["pending"].get(fp)
            if not report:
                raise ReportError("This report is gone (already sent or dismissed).")
            if fp in self.sending:
                raise ReportError("This report is being sent right now.")
            if self._limited(st):
                raise ReportError("Too many reports were sent in the last hour. Try again later.")
            self.sending.add(fp)
        try:
            found = find_issue(token, fp)
            body = report["body"]
            if found and found[1] == "open":
                number, action = found[0], "commented"
                _github(token, "POST", f"/repos/{REPO}/issues/{number}/comments",
                        {"body": f"Seen again ({report.get('count', 1)}×). Sunak {report.get('version', __version__)}, {platform.system()}, Python {platform.python_version()}."})
            else:
                if found:
                    body += f"\n\nEarlier issue with this error: #{found[0]} (closed)."
                made = _github(token, "POST", f"/repos/{REPO}/issues", {"title": report["title"], "body": body, "labels": [LABEL]})
                number, action = made["number"], "created"
            url = f"https://github.com/{REPO}/issues/{number}"
            with _lock:
                st = self._load()
                st["pending"].pop(fp, None)
                st["sent"][fp] = {"fp": fp, "title": report["title"], "number": number, "url": url, "time": time.time(),
                                  "count": report.get("count", 1), "commented": time.time()}
                if action == "created":
                    st["opened"].append(["i", time.time()])
                self._save(st)
            logger.info("Error report %s %s: issue #%d", fp, action, number)
            return {"url": url, "number": number, "action": action}
        finally:
            self.sending.discard(fp)

    def dismiss(self, fp):
        with _lock:
            st = self._load()
            st["pending"].pop(fp, None)
            self._save(st)

    def sample(self):
        """A harmless made-up error so the user can see what a report looks like (and try sending one)."""
        try:
            raise RuntimeError("This is a sample error created from Settings. It is not a real problem.")
        except RuntimeError:
            return self.capture(sys.exc_info(), sample=True)


# --- the logging hook ------------------------------------------------------------------------------
class _Hook(logging.Handler):
    """Errors that Sunak logged with a traceback go to the current installation's reports."""

    def emit(self, record):
        app = _app
        if app is None or not record.exc_info or not record.exc_info[0] or getattr(_local, "busy", False):
            return
        _local.busy = True
        try:
            app.reports.capture(record.exc_info)
        except Exception:  # noqa: BLE001 - reporting must never make things worse
            pass
        finally:
            _local.busy = False


_hook = _Hook(level=logging.ERROR)


def attach(app):
    """Make `app` the installation that collects error reports (call once per running server)."""
    global _app
    _app = app
    root = logging.getLogger(log.ROOT)
    if _hook not in root.handlers:
        root.addHandler(_hook)
