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
"""

# Columns added after the first release; created on start when an older database lacks them.
MIGRATIONS = [
    ("sessions", "use_kb", "INTEGER NOT NULL DEFAULT 0"),
    ("messages", "meta", "TEXT NOT NULL DEFAULT ''"),
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
        except sqlite3.OperationalError:
            self.fts = False
        self.conn.commit()

    def _q(self, sql, args=(), one=False):
        """Run one statement under the lock and return rows as dicts (or the first row with one=True)."""
        with self._lock:
            cur = self.conn.execute(sql, args)
            rows = [dict(r) for r in cur.fetchall()]
            self.conn.commit()
        if one:
            return rows[0] if rows else None
        return rows

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
        return s

    def create_session(self, title="New chat", model="", system="", use_kb=False):
        """Create an empty chat and return it."""
        sid, now = new_id(), time.time()
        self._q(
            "INSERT INTO sessions(id, title, model, system, use_kb, created, updated) VALUES(?,?,?,?,?,?,?)",
            (sid, title, model, system, int(bool(use_kb)), now, now),
        )
        return self.get_session(sid)

    def update_session(self, sid, **fields):
        """Update title, model, system prompt and/or knowledge-base switch (use_kb) of a chat."""
        allowed = {k: v for k, v in fields.items() if k in ("title", "model", "system", "use_kb")}
        if "use_kb" in allowed:
            allowed["use_kb"] = int(bool(allowed["use_kb"]))
        if not allowed:
            return
        sets = ", ".join(f"{k} = ?" for k in allowed)
        self._q(
            f"UPDATE sessions SET {sets}, updated = ? WHERE id = ?",
            (*allowed.values(), time.time(), sid),
        )

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
        """All notes, newest first."""
        return self._q("SELECT * FROM notes ORDER BY created DESC")

    def add_note(self, content, is_memory=False):
        """Create a note; `is_memory` notes are added to every chat's system prompt."""
        nid = new_id()
        self._q(
            "INSERT INTO notes(id, content, is_memory, created) VALUES(?,?,?,?)",
            (nid, content, int(bool(is_memory)), time.time()),
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
