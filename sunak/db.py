"""SQLite storage. One file, created on first start."""

import json
import re
import sqlite3
import threading
import time
import uuid

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    system TEXT NOT NULL DEFAULT '',
    created REAL NOT NULL,
    updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    is_memory INTEGER NOT NULL DEFAULT 0,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kb_files (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    size INTEGER NOT NULL DEFAULT 0,
    chars INTEGER NOT NULL DEFAULT 0,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS kb_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT NOT NULL REFERENCES kb_files(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_kb_chunks_file ON kb_chunks(file_id, idx);
CREATE TABLE IF NOT EXISTS calendar_events (
    uid TEXT PRIMARY KEY,
    ics TEXT NOT NULL,
    updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS reminders_sent (
    key TEXT PRIMARY KEY,
    ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    kind TEXT NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_read_tokens INTEGER,
    cache_creation_tokens INTEGER,
    seconds REAL,
    tokens_per_second REAL,
    ok INTEGER NOT NULL DEFAULT 1
);
"""

# Columns added after the first release; created on start when an older database lacks them.
MIGRATIONS = [
    ("sessions", "use_kb", "INTEGER NOT NULL DEFAULT 0"),
    ("messages", "meta", "TEXT NOT NULL DEFAULT ''"),
    ("sessions", "persona", "TEXT NOT NULL DEFAULT ''"),
    ("sessions", "use_web", "INTEGER NOT NULL DEFAULT 0"),
    ("notes", "source", "TEXT NOT NULL DEFAULT ''"),  # chat id of a memory Sunak picked up by itself
]


def new_id():
    """Random 16-character hex id."""
    return uuid.uuid4().hex[:16]


class DB:
    """Thread-safe wrapper around one SQLite connection."""
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA)
        for table, column, decl in MIGRATIONS:
            cols = [r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")]
            if column not in cols:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        # Full-text index for the knowledge base (rowid = kb_chunks.id). Some SQLite builds lack
        # FTS5; then search falls back to a simple scan in Python (see knowledge.py).
        try:
            self.conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5(text, tokenize='unicode61 remove_diacritics 2')")
            self.fts = True
            # chunks added while FTS5 was unavailable (database copied from another Python) get indexed now
            indexed = self.conn.execute("SELECT COUNT(*) FROM kb_fts").fetchone()[0]
            if indexed < self.conn.execute("SELECT COUNT(*) FROM kb_chunks").fetchone()[0]:
                self.conn.execute("DELETE FROM kb_fts")
                self.conn.execute("INSERT INTO kb_fts(rowid, text) SELECT id, text FROM kb_chunks")
        except sqlite3.OperationalError:
            self.fts = False
        self.conn.commit()

    def close(self):
        with self._lock:
            self.conn.close()

    def _q(self, sql, args=(), one=False):
        """Run one statement under the lock and return rows as dicts (or the first row with one=True)."""
        with self._lock:
            cur = self.conn.execute(sql, args)
            rows = [dict(r) for r in cur.fetchall()]
            self.conn.commit()
        if one:
            return rows[0] if rows else None
        return rows

    # token counter ----------------------------------------------------
    USAGE_COLUMNS = ("ts", "provider", "model", "kind", "input_tokens", "output_tokens", "cache_read_tokens",
                     "cache_creation_tokens", "seconds", "tokens_per_second", "ok")

    def add_usage(self, row):
        """Store the numbers of one model request (see usage.py)."""
        cols = self.USAGE_COLUMNS
        self._q(f"INSERT INTO usage({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})", tuple(row.get(c) for c in cols))

    def usage_last(self, skip_kinds=()):
        """The latest record whose kind is not in `skip_kinds`, or None."""
        marks = ", ".join("?" * len(skip_kinds)) or "''"
        return self._q(f"SELECT {', '.join(self.USAGE_COLUMNS)} FROM usage WHERE kind NOT IN ({marks}) ORDER BY id DESC LIMIT 1",
                       tuple(skip_kinds), one=True)

    def usage_sums(self, only_kinds=None):
        """Sums of the token counts: {requests, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens, all}.
        With `only_kinds` only those kinds count. Missing (NULL) counts are zero. `all` includes the cache tokens."""
        where, args = ("WHERE kind IN (%s)" % ", ".join("?" * len(only_kinds)), tuple(only_kinds)) if only_kinds else ("", ())
        r = self._q("SELECT COUNT(*) AS requests, " + ", ".join(f"COALESCE(SUM({c}), 0) AS {c}" for c in
                    ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens")) + f" FROM usage {where}",
                    args, one=True)
        r["all"] = r["input_tokens"] + r["output_tokens"] + r["cache_read_tokens"] + r["cache_creation_tokens"]
        return r

    # settings ---------------------------------------------------------
    def get_setting(self, key, default=None):
        """Read a JSON-encoded setting."""
        row = self._q("SELECT value FROM settings WHERE key = ?", (key,), one=True)
        return json.loads(row["value"]) if row else default

    def set_setting(self, key, value):
        """Store a JSON-encodable setting."""
        self._q(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )

    # sessions ---------------------------------------------------------
    def list_sessions(self):
        """All chats, newest first, without messages."""
        return self._q("SELECT id, title, model, updated FROM sessions ORDER BY updated DESC")

    def get_session(self, sid):
        """One chat including its messages, or None."""
        s = self._q("SELECT * FROM sessions WHERE id = ?", (sid,), one=True)
        if s:
            s["messages"] = self._q(
                "SELECT id, role, content, model, created, meta FROM messages "
                "WHERE session_id = ? ORDER BY id",
                (sid,),
            )
            for m in s["messages"]:
                m["meta"] = json.loads(m["meta"]) if m["meta"] else {}
            s["use_kb"] = bool(s["use_kb"])
            s["use_web"] = bool(s["use_web"])
        return s

    def create_session(self, title="New chat", model="", system="", use_kb=False, persona="", use_web=False):
        """Create an empty chat and return it."""
        sid, now = new_id(), time.time()
        self._q(
            "INSERT INTO sessions(id, title, model, system, use_kb, persona, use_web, created, updated) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (sid, title, model, system, int(bool(use_kb)), persona or "", int(bool(use_web)), now, now),
        )
        return self.get_session(sid)

    def update_session(self, sid, **fields):
        """Update title, model, system prompt, knowledge-base switch (use_kb), web search switch (use_web)
        and/or persona of a chat."""
        allowed = {k: v for k, v in fields.items() if k in ("title", "model", "system", "use_kb", "persona", "use_web")}
        for k in ("use_kb", "use_web"):
            if k in allowed:
                allowed[k] = int(bool(allowed[k]))
        if not allowed:
            return
        sets = ", ".join(f"{k} = ?" for k in allowed)
        self._q(
            f"UPDATE sessions SET {sets}, updated = ? WHERE id = ?",
            (*allowed.values(), time.time(), sid),
        )

    def search_messages(self, query, limit=50):
        """Chats whose title or messages contain every word of `query` (case-insensitive, any language).

        Returns one hit per chat, newest chat first: {session_id, title, updated, message_id, snippet}.
        A plain scan in Python: fast enough for a personal history and, unlike SQL LIKE, handles umlauts."""
        words = query.casefold().split()
        if not words:
            return []
        with self._lock:
            sessions = self.conn.execute("SELECT id, title, updated FROM sessions ORDER BY updated DESC").fetchall()
            rows = self.conn.execute("SELECT id, session_id, content FROM messages ORDER BY id").fetchall()
        by_session = {}
        for r in rows:
            by_session.setdefault(r["session_id"], []).append(r)
        hits = []
        for s in sessions:
            title_hit = all(w in s["title"].casefold() for w in words)
            match = None
            for m in by_session.get(s["id"], []):
                text = re.sub(r"<think>.*?(</think>|$)", "", m["content"], flags=re.S)
                low = text.casefold()
                if all(w in low for w in words):
                    match = (m["id"], text, low.find(words[0]))
                    break
            if match or title_hit:
                hit = {"session_id": s["id"], "title": s["title"], "updated": s["updated"], "message_id": None, "snippet": ""}
                if match:
                    mid, text, pos = match
                    start = max(0, pos - 60)
                    snippet = " ".join(text[start:start + 180].split())
                    hit.update(message_id=mid, snippet=("…" if start else "") + snippet + ("…" if start + 180 < len(text) else ""))
                hits.append(hit)
                if len(hits) >= limit:
                    break
        return hits

    def export_all(self):
        """Every chat with its messages, documents, notes and knowledge-base texts (for a backup)."""
        sessions = [self.get_session(s["id"]) for s in self._q("SELECT id FROM sessions ORDER BY created")]
        kb = [self.kb_file(f["id"]) for f in self._q("SELECT id FROM kb_files ORDER BY created")]
        return {"sessions": sessions, "documents": self._q("SELECT * FROM documents ORDER BY updated"),
                "notes": self._q("SELECT * FROM notes ORDER BY created"), "knowledge": kb,
                "calendar": self._q("SELECT * FROM calendar_events ORDER BY updated")}

    # restoring a backup (see backup.py): nothing that exists is overwritten ----------
    def restore_session(self, s):
        """Insert a chat with its messages as one step. False (nothing written) when a chat with this id exists."""
        with self._lock:
            c = self.conn
            if c.execute("SELECT 1 FROM sessions WHERE id = ?", (s["id"],)).fetchone():
                return False
            if s.get("fresh"):  # no usable id in the file: the same title, time and first message mean the same chat
                first = s["messages"][0]["content"] if s["messages"] else None
                if c.execute("SELECT 1 FROM sessions WHERE title = ? AND (? IS NULL OR created = ?) AND "
                             "(SELECT content FROM messages WHERE session_id = sessions.id ORDER BY id LIMIT 1) IS ?",
                             (s["title"], s["given_created"], s["given_created"], first)).fetchone():
                    return False
            try:
                c.execute("INSERT INTO sessions(id, title, model, system, use_kb, persona, use_web, created, updated) "
                          "VALUES(?,?,?,?,?,?,?,?,?)",
                          (s["id"], s["title"], s["model"], s["system"], int(s["use_kb"]), s["persona"], int(s["use_web"]),
                           s["created"], s["updated"]))
                c.executemany("INSERT INTO messages(session_id, role, content, model, created, meta) VALUES(?,?,?,?,?,?)",
                              [(s["id"], m["role"], m["content"], m["model"], m["created"], json.dumps(m["meta"]) if m["meta"] else "")
                               for m in s["messages"]])
                c.commit()
            except Exception:
                c.rollback()
                raise
        return True

    def restore_document(self, d):
        """Insert a document unless one with this id, or with the same title and text, exists. True when added."""
        with self._lock:
            if self.conn.execute("SELECT 1 FROM documents WHERE id = ? OR (title = ? AND content = ?)",
                                 (d["id"], d["title"], d["content"])).fetchone():
                return False
            self.conn.execute("INSERT INTO documents(id, title, content, updated) VALUES(?,?,?,?)",
                              (d["id"], d["title"], d["content"], d["updated"]))
            self.conn.commit()
        return True

    def restore_note(self, n):
        """Insert a note unless one with this id, or with the same text, exists. True when added."""
        with self._lock:
            if self.conn.execute("SELECT 1 FROM notes WHERE id = ? OR content = ?", (n["id"], n["content"])).fetchone():
                return False
            self.conn.execute("INSERT INTO notes(id, content, is_memory, created, source) VALUES(?,?,?,?,?)",
                              (n["id"], n["content"], int(n["is_memory"]), n["created"], n["source"]))
            self.conn.commit()
        return True

    # Sunak's own calendar: one iCalendar text per event ----------------------
    def cal_events(self):
        return self._q("SELECT uid, ics FROM calendar_events")

    def cal_get(self, uid):
        row = self._q("SELECT ics FROM calendar_events WHERE uid = ?", (uid,), one=True)
        return row["ics"] if row else None

    def cal_put(self, uid, ics):
        self._q("INSERT INTO calendar_events(uid, ics, updated) VALUES(?, ?, ?) "
                "ON CONFLICT(uid) DO UPDATE SET ics = excluded.ics, updated = excluded.updated", (uid, ics, time.time()))

    def cal_delete(self, uid):
        self._q("DELETE FROM calendar_events WHERE uid = ?", (uid,))

    # calendar reminders already shown or sent (key = event|lead|channel), so none goes off twice
    def reminder_seen(self, key):
        return self._q("SELECT 1 FROM reminders_sent WHERE key = ?", (key,), one=True) is not None

    def reminder_mark(self, key):
        self._q("INSERT OR IGNORE INTO reminders_sent(key, ts) VALUES(?, ?)", (key, time.time()))
        self._q("DELETE FROM reminders_sent WHERE ts < ?", (time.time() - 14 * 86400,))

    def delete_session(self, sid):
        """Delete a chat and its messages."""
        self._q("DELETE FROM sessions WHERE id = ?", (sid,))

    def add_message(self, sid, role, content, model="", meta=None):
        """Append a message to a chat and bump its timestamp. `meta` (dict) holds e.g. the knowledge-base sources."""
        now = time.time()
        self._q(
            "INSERT INTO messages(session_id, role, content, model, created, meta) VALUES(?,?,?,?,?,?)",
            (sid, role, content, model, now, json.dumps(meta) if meta else ""),
        )
        self._q("UPDATE sessions SET updated = ? WHERE id = ?", (now, sid))

    def image_refs(self):
        """Names of all images that messages refer to (see sunak/images.py)."""
        refs = set()
        for r in self._q("SELECT meta FROM messages WHERE meta LIKE '%\"images\"%'"):
            try:
                refs.update(json.loads(r["meta"]).get("images") or [])
            except (ValueError, AttributeError):
                pass
        return refs

    def truncate_messages(self, sid, from_id):
        """Delete message `from_id` and everything after it (used for regenerate/edit)."""
        self._q("DELETE FROM messages WHERE session_id = ? AND id >= ?", (sid, from_id))

    # documents --------------------------------------------------------
    def list_documents(self):
        """All documents, newest first, without content."""
        return self._q("SELECT id, title, updated FROM documents ORDER BY updated DESC")

    def get_document(self, did):
        """One document, or None."""
        return self._q("SELECT * FROM documents WHERE id = ?", (did,), one=True)

    def save_document(self, did, title, content):
        """Update the document `did`, or create it when it does not exist. Returns the document."""
        now = time.time()
        if did and self.get_document(did):
            self._q(
                "UPDATE documents SET title = ?, content = ?, updated = ? WHERE id = ?",
                (title, content, now, did),
            )
        else:
            did = new_id()
            self._q(
                "INSERT INTO documents(id, title, content, updated) VALUES(?,?,?,?)",
                (did, title, content, now),
            )
        return self.get_document(did)

    def delete_document(self, did):
        """Delete a document."""
        self._q("DELETE FROM documents WHERE id = ?", (did,))

    # notes / memory ---------------------------------------------------
    def list_notes(self):
        """All notes, newest first; `source_title` is the title of the chat a memory came from."""
        return self._q("SELECT notes.*, sessions.title AS source_title FROM notes "
                       "LEFT JOIN sessions ON notes.source != '' AND sessions.id = notes.source ORDER BY notes.created DESC")

    def add_note(self, content, is_memory=False, source=""):
        """Create a note; `is_memory` notes are added to every chat's system prompt. `source` is the
        chat id when Sunak remembered it by itself (see memory.py)."""
        nid = new_id()
        self._q(
            "INSERT INTO notes(id, content, is_memory, created, source) VALUES(?,?,?,?,?)",
            (nid, content, int(bool(is_memory)), time.time(), source),
        )
        return self._q("SELECT * FROM notes WHERE id = ?", (nid,), one=True)

    def update_note(self, nid, content=None, is_memory=None):
        """Change the text and/or memory flag of a note."""
        if content is not None:
            self._q("UPDATE notes SET content = ? WHERE id = ?", (content, nid))
        if is_memory is not None:
            self._q("UPDATE notes SET is_memory = ? WHERE id = ?", (int(bool(is_memory)), nid))

    def delete_note(self, nid):
        """Delete a note."""
        self._q("DELETE FROM notes WHERE id = ?", (nid,))

    def memories(self):
        """Texts of all memory notes, oldest first."""
        return [r["content"] for r in self._q("SELECT content FROM notes WHERE is_memory = 1 ORDER BY created")]

    # knowledge base ---------------------------------------------------
    def kb_files(self):
        """All knowledge-base files, newest first."""
        return self._q("SELECT * FROM kb_files ORDER BY created DESC")

    def kb_file(self, fid):
        """One file with its full text, or None."""
        f = self._q("SELECT * FROM kb_files WHERE id = ?", (fid,), one=True)
        if f:
            f["text"] = "\n\n".join(r["text"] for r in self._q(
                "SELECT text FROM kb_chunks WHERE file_id = ? ORDER BY idx", (fid,)))
        return f

    def kb_add(self, name, size, chunks):
        """Store a file as text chunks (replacing a file with the same name) and index them."""
        fid, now = new_id(), time.time()
        old = [r["id"] for r in self._q("SELECT id FROM kb_files WHERE name = ?", (name,))]
        for o in old:
            self.kb_delete(o)
        with self._lock:
            c = self.conn
            c.execute("INSERT INTO kb_files(id, name, size, chars, created) VALUES(?,?,?,?,?)",
                      (fid, name, size, sum(len(x) for x in chunks), now))
            for i, text in enumerate(chunks):
                cid = c.execute("INSERT INTO kb_chunks(file_id, idx, text) VALUES(?,?,?)", (fid, i, text)).lastrowid
                if self.fts:
                    c.execute("INSERT INTO kb_fts(rowid, text) VALUES(?, ?)", (cid, text))
            c.commit()
        return self._q("SELECT * FROM kb_files WHERE id = ?", (fid,), one=True)

    def kb_delete(self, fid):
        """Remove a file, its chunks and their index entries."""
        with self._lock:
            if self.fts:
                self.conn.execute("DELETE FROM kb_fts WHERE rowid IN (SELECT id FROM kb_chunks WHERE file_id = ?)", (fid,))
            self.conn.execute("DELETE FROM kb_files WHERE id = ?", (fid,))
            self.conn.commit()

    def kb_chunks(self):
        """Every chunk with its file name, in file and reading order."""
        return self._q("SELECT c.id, c.file_id, c.idx, c.text, f.name FROM kb_chunks c "
                       "JOIN kb_files f ON f.id = c.file_id ORDER BY f.created, c.idx")

    def kb_total_chars(self):
        """Size of the whole knowledge base in characters."""
        return self._q("SELECT COALESCE(SUM(chars), 0) AS n FROM kb_files", one=True)["n"]

    def kb_match(self, query, limit):
        """FTS5 search (best first by bm25). Only call when self.fts is True."""
        return self._q("SELECT c.id, c.file_id, c.idx, c.text, f.name FROM kb_fts "
                       "JOIN kb_chunks c ON c.id = kb_fts.rowid JOIN kb_files f ON f.id = c.file_id "
                       "WHERE kb_fts MATCH ? ORDER BY bm25(kb_fts) LIMIT ?", (query, limit))
