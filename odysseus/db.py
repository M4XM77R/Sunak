"""SQLite storage. One file, created on first start."""

import json
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
"""


def new_id():
    return uuid.uuid4().hex[:16]


class DB:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def _q(self, sql, args=(), one=False):
        with self._lock:
            cur = self.conn.execute(sql, args)
            rows = [dict(r) for r in cur.fetchall()]
            self.conn.commit()
        if one:
            return rows[0] if rows else None
        return rows

    # settings ---------------------------------------------------------
    def get_setting(self, key, default=None):
        row = self._q("SELECT value FROM settings WHERE key = ?", (key,), one=True)
        return json.loads(row["value"]) if row else default

    def set_setting(self, key, value):
        self._q(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )

    # sessions ---------------------------------------------------------
    def list_sessions(self):
        return self._q("SELECT id, title, model, updated FROM sessions ORDER BY updated DESC")

    def get_session(self, sid):
        s = self._q("SELECT * FROM sessions WHERE id = ?", (sid,), one=True)
        if s:
            s["messages"] = self._q(
                "SELECT id, role, content, model, created FROM messages "
                "WHERE session_id = ? ORDER BY id",
                (sid,),
            )
        return s

    def create_session(self, title="New chat", model="", system=""):
        sid, now = new_id(), time.time()
        self._q(
            "INSERT INTO sessions(id, title, model, system, created, updated) VALUES(?,?,?,?,?,?)",
            (sid, title, model, system, now, now),
        )
        return self.get_session(sid)

    def update_session(self, sid, **fields):
        allowed = {k: v for k, v in fields.items() if k in ("title", "model", "system")}
        if not allowed:
            return
        sets = ", ".join(f"{k} = ?" for k in allowed)
        self._q(
            f"UPDATE sessions SET {sets}, updated = ? WHERE id = ?",
            (*allowed.values(), time.time(), sid),
        )

    def delete_session(self, sid):
        self._q("DELETE FROM sessions WHERE id = ?", (sid,))

    def add_message(self, sid, role, content, model=""):
        now = time.time()
        self._q(
            "INSERT INTO messages(session_id, role, content, model, created) VALUES(?,?,?,?,?)",
            (sid, role, content, model, now),
        )
        self._q("UPDATE sessions SET updated = ? WHERE id = ?", (now, sid))

    def truncate_messages(self, sid, from_id):
        """Delete message `from_id` and everything after it (used for regenerate/edit)."""
        self._q("DELETE FROM messages WHERE session_id = ? AND id >= ?", (sid, from_id))

    # documents --------------------------------------------------------
    def list_documents(self):
        return self._q("SELECT id, title, updated FROM documents ORDER BY updated DESC")

    def get_document(self, did):
        return self._q("SELECT * FROM documents WHERE id = ?", (did,), one=True)

    def save_document(self, did, title, content):
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
        self._q("DELETE FROM documents WHERE id = ?", (did,))

    # notes / memory ---------------------------------------------------
    def list_notes(self):
        return self._q("SELECT * FROM notes ORDER BY created DESC")

    def add_note(self, content, is_memory=False):
        nid = new_id()
        self._q(
            "INSERT INTO notes(id, content, is_memory, created) VALUES(?,?,?,?)",
            (nid, content, int(bool(is_memory)), time.time()),
        )
        return self._q("SELECT * FROM notes WHERE id = ?", (nid,), one=True)

    def update_note(self, nid, content=None, is_memory=None):
        if content is not None:
            self._q("UPDATE notes SET content = ? WHERE id = ?", (content, nid))
        if is_memory is not None:
            self._q("UPDATE notes SET is_memory = ? WHERE id = ?", (int(bool(is_memory)), nid))

    def delete_note(self, nid):
        self._q("DELETE FROM notes WHERE id = ?", (nid,))

    def memories(self):
        return [r["content"] for r in self._q("SELECT content FROM notes WHERE is_memory = 1 ORDER BY created")]
