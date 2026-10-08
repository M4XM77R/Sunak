"""Restore a backup (Settings → Data → Download backup) or a single chat exported as JSON.

Importing only adds: whatever exists already stays as it is, and items that are there already are skipped (same id,
or the same content where ids are not stable). Every item is checked on its own, so one damaged entry is counted as
invalid and the rest still comes in. `restore_content` handles what lives in a profile's database (chats, documents,
notes, knowledge base, calendar events); settings, mail accounts and calendar accounts need the app's own checks
and are done by `App.import_backup` (server.py), which calls this module first."""

import json
import math
import re
import time

from . import __version__, cal, knowledge
from .db import new_id

MAX_BYTES = 256 * 1024 * 1024  # a file for `sunak import`; the HTTP request is limited by server.MAX_BODY
DATA_KEYS = ("sessions", "documents", "notes", "knowledge", "calendar")
BACKUP_KEYS = DATA_KEYS + ("settings", "mail_accounts", "calendars")
LISTS = DATA_KEYS + ("mail_accounts", "calendars")  # these must be lists
ROLES = ("user", "assistant", "system")
ID_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")
COUNTS = ("chats", "documents", "notes", "knowledge", "events", "mail_accounts", "calendars", "personas", "providers", "settings")


def new_report():
    """What an import did: items added, items skipped because they exist already, items that were damaged, the
    passwords and keys the user has to enter again (`secrets`: {kind: mail|calendar|provider, name}), and notes."""
    return {"kind": "", "added": dict.fromkeys(COUNTS, 0), "skipped": dict.fromkeys(COUNTS, 0), "invalid": 0,
            "secrets": [], "notes": []}


def read_file(path):
    """The parsed content of a file for `sunak import`. Raises ValueError (message for the user) when it is too big or no JSON."""
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_BYTES + 1)
    except OSError as e:
        raise ValueError(f"Cannot read {path}: {e.strerror or e}") from None
    if len(raw) > MAX_BYTES:
        raise ValueError(f"The file is bigger than {MAX_BYTES // 1024 // 1024} MB")
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except UnicodeDecodeError:
        raise ValueError("The file is not UTF-8 text") from None
    except RecursionError:
        raise ValueError("Invalid JSON: nested too deeply") from None
    except ValueError as e:
        raise ValueError(f"The file is not valid JSON ({e})") from None


def _version(text):
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", text.strip()) if isinstance(text, str) else None
    return tuple(map(int, m.groups())) if m else None


def classify(data, report):
    """"backup" or "chat" (and notes about its version in `report`); ValueError when the file is neither or malformed."""
    if not isinstance(data, dict):
        raise ValueError("This is not a Sunak backup: the file does not hold a JSON object")
    if not any(k in data for k in BACKUP_KEYS):
        if isinstance(data.get("messages"), list) and "title" in data:
            report["kind"] = "chat"
            return "chat"
        raise ValueError("This is neither a Sunak backup nor a chat exported from Sunak")
    for k in LISTS:
        if k in data and not isinstance(data[k], list):
            raise ValueError(f"Malformed backup: '{k}' must be a list")
    if "settings" in data and not isinstance(data["settings"], dict):
        raise ValueError("Malformed backup: 'settings' must be an object")
    theirs, ours = _version(data.get("sunak_version")), _version(__version__)
    if theirs and ours and theirs > ours:
        report["notes"].append("The backup was made by a newer Sunak; parts this version does not know are ignored.")
    report["kind"] = "backup"
    return "backup"


def _text(v, default="", limit=None):
    v = v if isinstance(v, str) else default
    return v[:limit] if limit else v


def _time(v, default):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0 < v < 4e9 else default


def clean_session(s):
    """A chat ready for DB.restore_session, or None when it is damaged. Pictures are not part of a backup, so
    their references are dropped; the second value tells how many messages had some."""
    if not isinstance(s, dict) or not isinstance(s.get("messages", []), list):
        return None, 0
    now, pictures, messages = time.time(), 0, []
    for m in s.get("messages", []):
        if not isinstance(m, dict) or m.get("role") not in ROLES or not isinstance(m.get("content"), str):
            return None, 0
        meta = m.get("meta") if isinstance(m.get("meta"), dict) else {}
        if "images" in meta:
            meta = {k: v for k, v in meta.items() if k != "images"}
            pictures += 1
        messages.append({"role": m["role"], "content": m["content"], "model": _text(m.get("model"), limit=200),
                         "created": _time(m.get("created"), now), "meta": meta})
    sid = s.get("id") if isinstance(s.get("id"), str) and ID_RE.fullmatch(s["id"]) else new_id()
    created = _time(s.get("created"), now)
    return {"id": sid, "title": _text(s.get("title"), "Imported chat", 200).strip() or "Imported chat",
            "model": _text(s.get("model"), limit=200), "system": _text(s.get("system")),
            "use_kb": s.get("use_kb") is True, "use_web": s.get("use_web") is True, "persona": _text(s.get("persona"), limit=40),
            "created": created, "updated": _time(s.get("updated"), created), "messages": messages}, pictures


def _document(d):
    if not isinstance(d, dict) or not isinstance(d.get("content", ""), str):
        return None
    did = d.get("id") if isinstance(d.get("id"), str) and ID_RE.fullmatch(d["id"]) else new_id()
    return {"id": did, "title": _text(d.get("title"), "Imported document", 300) or "Imported document",
            "content": _text(d.get("content")), "updated": _time(d.get("updated"), time.time())}


def _note(n):
    if not isinstance(n, dict) or not isinstance(n.get("content"), str) or not n["content"].strip():
        return None
    nid = n.get("id") if isinstance(n.get("id"), str) and ID_RE.fullmatch(n["id"]) else new_id()
    return {"id": nid, "content": n["content"], "is_memory": n.get("is_memory") in (1, True),
            "created": _time(n.get("created"), time.time()),
            "source": n["source"] if isinstance(n.get("source"), str) and ID_RE.fullmatch(n["source"]) else ""}


def _count(report, key, added):
    report["added" if added else "skipped"][key] += 1


def restore_content(db, data, report):
    """Add the chats, documents, notes, knowledge-base files and calendar events of `data` (a backup or one chat) to `db`."""
    sessions = [data] if report["kind"] == "chat" else data.get("sessions", [])
    pictures = 0
    for raw in sessions:
        s, pics = clean_session(raw)
        if s is None:
            report["invalid"] += 1
            continue
        pictures += pics
        _count(report, "chats", db.restore_session(s))
    if pictures:
        report["notes"].append("Some messages had pictures. Pictures are not part of a backup, so they are missing.")
    for key, count, clean, restore in (("documents", "documents", _document, db.restore_document),
                                       ("notes", "notes", _note, db.restore_note)):
        for raw in data.get(key, []):
            item = clean(raw)
            if item is None:
                report["invalid"] += 1
            else:
                _count(report, count, restore(item))
    known = {f["name"] for f in db.kb_files()}
    for raw in data.get("knowledge", []):
        name = _text(raw.get("name"), limit=300).strip() if isinstance(raw, dict) else ""
        text = raw.get("text") if isinstance(raw, dict) else None
        chunks = knowledge.chunk(text) if isinstance(text, str) else []
        if not name or not chunks:
            report["invalid"] += 1
        elif name in known:
            report["skipped"]["knowledge"] += 1
        else:
            size = raw.get("size") if isinstance(raw.get("size"), int) and not isinstance(raw.get("size"), bool) else 0
            db.kb_add(name, max(0, size) or len(text.encode("utf-8")), chunks)
            known.add(name)
            report["added"]["knowledge"] += 1
    for raw in data.get("calendar", []):
        uid, ics = (raw.get("uid"), raw.get("ics")) if isinstance(raw, dict) else (None, None)
        try:
            if not isinstance(uid, str) or not 0 < len(uid) <= 300 or not isinstance(ics, str):
                raise cal.CalendarError("damaged")
            cal.parse(ics)
        except (cal.CalendarError, ValueError):
            report["invalid"] += 1
            continue
        if db.cal_get(uid) is not None:
            report["skipped"]["events"] += 1
        else:
            db.cal_put(uid, ics)
            report["added"]["events"] += 1


LABELS = {"chats": ("chat", "chats"), "documents": ("document", "documents"), "notes": ("note", "notes"),
          "knowledge": ("knowledge-base file", "knowledge-base files"), "events": ("calendar event", "calendar events"),
          "mail_accounts": ("mail account", "mail accounts"), "calendars": ("calendar account", "calendar accounts"),
          "personas": ("persona", "personas"), "providers": ("provider", "providers"), "settings": ("setting", "settings")}
SECRET_WHAT = {"mail": "mail account {name}: password", "calendar": "calendar {name}: password",
               "provider": "provider {name}: API key (if it needs one)"}


def summary(report):
    """The report as lines of text for the terminal."""
    def counts(group):
        return ", ".join(f"{n} {LABELS[k][n != 1]}" for k, n in report[group].items() if n)
    lines = ["Added: " + (counts("added") or "nothing")]
    if counts("skipped"):
        lines.append("Skipped, already there: " + counts("skipped"))
    if report["invalid"]:
        lines.append(f"Skipped, damaged: {report['invalid']}")
    if report["secrets"]:
        lines.append("Enter again in Settings (secrets are never part of a backup): " +
                     "; ".join(SECRET_WHAT[x["kind"]].format(name=x["name"]) for x in report["secrets"]))
    return lines + report["notes"]
