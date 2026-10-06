"""HTTP server and JSON API. Python standard library only."""

import hashlib
import hmac
import json
import mimetypes
import os
import platform
import queue
import re
import secrets
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import __version__, ollama, providers, research
from .db import DB

STATIC = Path(__file__).parent / "static"
MAX_BODY = 20 * 1024 * 1024

DEFAULT_SETTINGS = {
    "default_model": "",
    "system_prompt": "You are Sunak, a helpful, honest and concise assistant. Use Markdown when it helps.",
    "temperature": 0.7,
    "use_memory": True,
    "accent": "#ff4fa3",
    "theme": "dark",
}

# Hardware-aware starter models (Ollama tags). RAM in GB -> model.
RECOMMENDATIONS = [
    (6, "qwen3:1.7b", "1.4 GB"),
    (12, "qwen3:4b", "2.6 GB"),
    (24, "qwen3:8b", "5.2 GB"),
    (10**9, "qwen3:14b", "9.3 GB"),
]


def total_ram_gb():
    """Total system memory in GB (Linux, macOS, Windows), or None if unknown."""
    try:
        system = platform.system()
        if system == "Linux":
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return round(int(line.split()[1]) / 1024 / 1024, 1)
        elif system == "Darwin":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=3).stdout
            return round(int(out.strip()) / 1024**3, 1)
        elif system == "Windows":
            import ctypes

            class MEMSTAT(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]

            st = MEMSTAT()
            st.dwLength = ctypes.sizeof(MEMSTAT)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return round(st.ullTotalPhys / 1024**3, 1)
    except Exception:
        pass
    return None


def recommend(ram):
    """Pick a starter model that fits into `ram` GB of memory."""
    for limit, model, size in RECOMMENDATIONS:
        if ram is None or ram < limit:
            return {"model": model, "size": size}
    return {"model": RECOMMENDATIONS[-1][1], "size": RECOMMENDATIONS[-1][2]}


def hash_password(pw, salt=None):
    """PBKDF2-SHA256 hash, stored as 'salt$hex'."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex()
    return f"{salt}${digest}"


def check_password(pw, stored):
    """Compare `pw` with a stored hash in constant time."""
    salt, _, digest = stored.partition("$")
    return hmac.compare_digest(hash_password(pw, salt).split("$")[1], digest)


class App:
    """Application state shared by all requests: database, settings, model resolution, auth and prompt building."""
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = DB(str(self.data_dir / "sunak.db"))
        if not self.db.get_setting("secret"):
            self.db.set_setting("secret", secrets.token_hex(32))
        env_pw = os.environ.get("SUNAK_PASSWORD")
        if env_pw:
            self.db.set_setting("password_hash", hash_password(env_pw))
        self.ram = total_ram_gb()

    # settings ---------------------------------------------------------
    def settings(self):
        """User preferences merged over DEFAULT_SETTINGS, plus the provider list."""
        s = dict(DEFAULT_SETTINGS)
        s.update(self.db.get_setting("prefs", {}))
        s["providers"] = self.db.get_setting("providers") or providers.default_providers()
        return s

    def save_settings(self, data):
        """Validate and store the keys present in `data` (prefs, providers, password)."""
        prefs = self.db.get_setting("prefs", {})
        for k in DEFAULT_SETTINGS:
            if k in data:
                prefs[k] = data[k]
        self.db.set_setting("prefs", prefs)
        if "providers" in data:
            clean = []
            for p in data["providers"]:
                if p.get("type") not in ("ollama", "openai") or not p.get("base_url"):
                    raise ValueError("Each provider needs a type (ollama/openai) and a base URL")
                pid = re.sub(r"[^a-z0-9_-]", "", (p.get("id") or p.get("name") or "p").lower())[:24] or "p"
                while any(c["id"] == pid for c in clean):
                    pid += "x"
                clean.append({"id": pid, "name": p.get("name") or pid, "type": p["type"],
                              "base_url": p["base_url"].strip(), "api_key": p.get("api_key", "").strip()})
            self.db.set_setting("providers", clean)
        if "password" in data:
            pw = data["password"] or ""
            self.db.set_setting("password_hash", hash_password(pw) if pw else "")
        return self.settings()

    def provider(self, pid):
        """Look up a configured provider by id."""
        for p in self.settings()["providers"]:
            if p["id"] == pid:
                return p
        raise providers.ProviderError(f"Unknown provider '{pid}'. Check Settings.")

    def ollama_provider(self):
        """The first configured Ollama provider (used by the Models page)."""
        for p in self.settings()["providers"]:
            if p["type"] == "ollama":
                return p
        raise providers.ProviderError("No Ollama provider configured. Add one in Settings → Providers.")

    def resolve(self, model_id):
        """Turn a model id 'provider::model' (or the default) into (provider, model name)."""
        if not model_id:
            model_id = self.settings()["default_model"]
        if not model_id:
            models = self.models()["models"]
            if not models:
                raise providers.ProviderError("No model available. Install one in Settings → Models.")
            model_id = models[0]["id"]
        pid, sep, name = model_id.partition("::")
        if not sep:
            raise providers.ProviderError(f"Invalid model id '{model_id}'")
        return self.provider(pid), name

    def models(self):
        """Ask all providers in parallel for their models; unreachable providers are listed in `errors`."""
        out, errors = [], []
        provs = self.settings()["providers"]

        def fetch(p):
            try:
                return p, providers.list_models(p), None
            except Exception as e:  # noqa: BLE001 - surface any provider failure to the UI
                return p, [], str(e)

        with ThreadPoolExecutor(max_workers=max(1, len(provs))) as ex:
            for p, names, err in ex.map(fetch, provs):
                if err:
                    errors.append({"provider": p["id"], "name": p["name"], "error": err})
                for n in names:
                    out.append({"id": f"{p['id']}::{n}", "name": n, "provider": p["id"], "provider_name": p["name"]})
        return {"models": out, "errors": errors}

    # auth -------------------------------------------------------------
    def auth_required(self):
        """True when a password is set."""
        return bool(self.db.get_setting("password_hash"))

    def token(self):
        """Login cookie value; changes whenever the password changes."""
        return hmac.new(self.db.get_setting("secret").encode(), (self.db.get_setting("password_hash") or "").encode(),
                        "sha256").hexdigest()

    # chat -------------------------------------------------------------
    def build_messages(self, session, history):
        """Chat history for the model: system prompt, session prompt, memory notes, then the messages."""
        s = self.settings()
        system = "\n\n".join(x for x in (s["system_prompt"], session.get("system", "")) if x.strip())
        if s["use_memory"]:
            mem = self.db.memories()
            if mem:
                system += "\n\nThings you remember about the user:\n" + "\n".join(f"- {m}" for m in mem)
        msgs = [{"role": "system", "content": system}] if system.strip() else []
        for m in history:
            content = providers.strip_think(m["content"]) if m["role"] == "assistant" else m["content"]
            msgs.append({"role": m["role"], "content": content})
        return msgs

    def options(self):
        """Generation options (temperature) from the settings."""
        try:
            return {"temperature": float(self.settings()["temperature"])}
        except (TypeError, ValueError):
            return {}


def stream_to_text(chunks):
    """Merge ("think"/"text") chunks into a single string with <think> wrapping."""
    out, thinking = [], False
    for kind, c in chunks:
        if kind == "think" and not thinking:
            out.append("<think>")
            thinking = True
        elif kind == "text" and thinking:
            out.append("</think>\n\n")
            thinking = False
        out.append(c)
    if thinking:
        out.append("</think>")
    return "".join(out)


class Handler(BaseHTTPRequestHandler):
    """HTTP request handler. Static files are served from STATIC; JSON API routes are listed in ROUTES.

    Streaming endpoints answer with NDJSON: one JSON object per line, e.g. {"type": "text", "t": "Hello"}."""
    app: App = None
    server_version = "Sunak/" + __version__

    def log_message(self, fmt, *args):
        if os.environ.get("SUNAK_DEBUG"):
            super().log_message(fmt, *args)

    # helpers ----------------------------------------------------------
    def send_json(self, obj, status=200):
        """Send `obj` as a JSON response."""
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def error(self, msg, status=400):
        """Send {"error": msg} with the given status."""
        self.send_json({"error": msg}, status)

    def body(self):
        """Parse the JSON request body (max MAX_BODY bytes)."""
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("Request too large")
        raw = self.rfile.read(n) if n else b""
        return json.loads(raw) if raw else {}

    def start_stream(self):
        """Send headers for an NDJSON stream; the connection closes when it ends."""
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()

    def emit(self, obj):
        """Write one NDJSON event and flush it to the browser."""
        self.wfile.write((json.dumps(obj) + "\n").encode())
        self.wfile.flush()

    def authed(self):
        """True when no password is set or the request carries a valid login cookie."""
        if not self.app.auth_required():
            return True
        cookies = self.headers.get("Cookie", "")
        m = re.search(r"(?:^|;\s*)sunak_token=([a-f0-9]+)", cookies)
        return bool(m) and hmac.compare_digest(m.group(1), self.app.token())

    # routing ----------------------------------------------------------
    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_PUT(self):
        self.route("PUT")

    def do_PATCH(self):
        self.route("PATCH")

    def do_DELETE(self):
        self.route("DELETE")

    def route(self, method):
        """Dispatch a request: static files, CSRF header check, login, auth check, then ROUTES."""
        path = urlparse(self.path).path
        try:
            if not path.startswith("/api/"):
                if method != "GET":
                    return self.error("Not found", 404)
                return self.static(path)
            if method != "GET" and self.headers.get("X-Requested-With") != "sunak":
                return self.error("Missing X-Requested-With header", 403)
            if path == "/api/login" and method == "POST":
                return self.login()
            if path == "/api/status" and method == "GET":
                return self.status()
            if not self.authed():
                return self.error("Login required", 401)
            for pattern, meth, fn in ROUTES:
                m = re.fullmatch(pattern, path)
                if m and meth == method:
                    return fn(self, *m.groups())
            return self.error("Not found", 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (ValueError, providers.ProviderError) as e:
            self.error(str(e))

    def static(self, path):
        """Serve a file from the static folder (login page instead of the app when not logged in)."""
        if path in ("/", "/index.html"):
            path = "/index.html" if self.authed() else "/login.html"
        target = (STATIC / path.lstrip("/")).resolve()
        if STATIC.resolve() not in target.parents or not target.is_file():
            return self.error("Not found", 404)
        data = target.read_bytes()
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    # endpoints --------------------------------------------------------
    def status(self):
        """GET /api/status: version, auth state, RAM and recommended model."""
        self.send_json({
            "version": __version__,
            "auth_required": self.app.auth_required(),
            "authed": self.authed(),
            "ram_gb": self.app.ram,
            "recommended": recommend(self.app.ram),
        })

    def login(self):
        """POST /api/login: check the password and set the login cookie."""
        data = self.body()
        stored = self.app.db.get_setting("password_hash")
        if stored and not check_password(data.get("password", ""), stored):
            time.sleep(1)
            return self.error("Wrong password", 401)
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Set-Cookie", f"sunak_token={self.app.token()}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000")
        self.end_headers()
        self.wfile.write(body)

    def logout(self):
        """POST /api/logout: clear the login cookie."""
        self.send_response(200)
        self.send_header("Set-Cookie", "sunak_token=; Path=/; Max-Age=0")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def get_settings(self):
        """GET /api/settings"""
        s = self.app.settings()
        s["password_set"] = self.app.auth_required()
        self.send_json(s)

    def put_settings(self):
        """PUT /api/settings"""
        self.app.save_settings(self.body())
        self.get_settings()

    def get_models(self):
        """GET /api/models: all models of all providers."""
        self.send_json(self.app.models())

    # sessions
    def list_sessions(self):
        """GET /api/sessions"""
        self.send_json(self.app.db.list_sessions())

    def create_session(self):
        """POST /api/sessions"""
        d = self.body()
        self.send_json(self.app.db.create_session(model=d.get("model", ""), system=d.get("system", "")))

    def get_session(self, sid):
        """GET /api/sessions/<id>: session with all messages."""
        s = self.app.db.get_session(sid)
        return self.send_json(s) if s else self.error("Not found", 404)

    def patch_session(self, sid):
        """PATCH /api/sessions/<id>: change title, model or system prompt."""
        self.app.db.update_session(sid, **self.body())
        self.get_session(sid)

    def delete_session(self, sid):
        """DELETE /api/sessions/<id>"""
        self.app.db.delete_session(sid)
        self.send_json({"ok": True})

    def chat(self):
        """POST /api/chat: store the user message, stream the answer, store it.

        `truncate_from` deletes that message and everything after it first (regenerate / edit).
        Events: start, think, text, done | error. A partial answer is kept if the stream breaks."""
        d = self.body()
        db = self.app.db
        session = db.get_session(d.get("session_id", ""))
        if not session:
            return self.error("Session not found", 404)
        model_id = d.get("model") or session["model"]
        prov, model = self.app.resolve(model_id)
        model_id = f"{prov['id']}::{model}"
        sid = session["id"]
        if d.get("truncate_from"):
            db.truncate_messages(sid, int(d["truncate_from"]))
        content = (d.get("content") or "").strip()
        if content:
            db.add_message(sid, "user", content)
        session = db.get_session(sid)
        if not session["messages"] or session["messages"][-1]["role"] != "user":
            return self.error("Nothing to answer")
        updates = {"model": model_id}
        if session["title"] == "New chat":
            first = session["messages"][0]["content"].strip().splitlines()[0]
            updates["title"] = (first[:57] + "…") if len(first) > 58 else first
        db.update_session(sid, **updates)

        messages = self.app.build_messages(session, session["messages"])
        self.start_stream()
        self.emit({"type": "start", "title": updates.get("title", session["title"]), "model": model_id})
        chunks = []
        try:
            for kind, c in providers.chat_stream(prov, model, messages, self.app.options()):
                chunks.append((kind, c))
                self.emit({"type": kind, "t": c})
        except providers.ProviderError as e:
            text = stream_to_text(chunks)
            if text:
                db.add_message(sid, "assistant", text, model_id)
            return self.emit({"type": "error", "error": str(e)})
        except (BrokenPipeError, ConnectionResetError):
            text = stream_to_text(chunks)
            if text:
                db.add_message(sid, "assistant", text, model_id)
            return
        db.add_message(sid, "assistant", stream_to_text(chunks), model_id)
        self.emit({"type": "done"})

    def compare(self):
        """POST /api/compare: stream one prompt to 2-4 models in parallel. Events carry `i`, the model index."""
        d = self.body()
        prompt = (d.get("prompt") or "").strip()
        model_ids = d.get("models") or []
        if not prompt or len(model_ids) < 2:
            raise ValueError("Pick at least two models and enter a prompt")
        targets = [self.app.resolve(mid) for mid in model_ids[:4]]
        session = {"system": ""}
        messages = self.app.build_messages(session, [{"role": "user", "content": prompt}])
        q = queue.Queue()
        stop = threading.Event()

        def run(i, prov, model):
            t0 = time.time()
            n = 0
            try:
                for kind, c in providers.chat_stream(prov, model, messages, self.app.options()):
                    if stop.is_set():
                        return
                    n += len(c)
                    q.put({"i": i, "type": kind, "t": c})
                q.put({"i": i, "type": "done", "seconds": round(time.time() - t0, 1), "chars": n})
            except Exception as e:  # noqa: BLE001
                q.put({"i": i, "type": "error", "error": str(e)})

        self.start_stream()
        threads = [threading.Thread(target=run, args=(i, p, m), daemon=True) for i, (p, m) in enumerate(targets)]
        for t in threads:
            t.start()
        finished = 0
        try:
            while finished < len(threads):
                ev = q.get()
                if ev["type"] in ("done", "error"):
                    finished += 1
                self.emit(ev)
        finally:
            stop.set()

    def research(self):
        """POST /api/research: plan queries, search, read pages, stream a cited report.

        Events: status, sources, think, text, done | error."""
        d = self.body()
        question = (d.get("question") or "").strip()
        if not question:
            raise ValueError("Enter a question")
        prov, model = self.app.resolve(d.get("model"))
        self.start_stream()
        try:
            self.emit({"type": "status", "t": "Planning search queries…"})
            plan = providers.chat_once(prov, model, [
                {"role": "system", "content": "Return 3 short web search queries (one per line, no numbering, "
                                              "no quotes) that together answer the user's question."},
                {"role": "user", "content": question},
            ], {"temperature": 0.2})
            queries = [re.sub(r"^[\s\-*\d.)\"']+|[\"']+$", "", q).strip() for q in plan.splitlines()]
            queries = [q for q in queries if q][:3] or [question]
            results, seen = [], set()
            for qy in queries:
                self.emit({"type": "status", "t": f"Searching: {qy}"})
                try:
                    for r in research.search(qy, limit=4):
                        if r["url"] not in seen:
                            seen.add(r["url"])
                            results.append(r)
                except Exception as e:  # noqa: BLE001
                    self.emit({"type": "status", "t": f"Search failed ({e})"})
            if not results:
                return self.emit({"type": "error", "error": "Web search returned no results (offline?)."})
            sources = []
            for r in results[:8]:
                self.emit({"type": "status", "t": f"Reading {r['url']}"})
                try:
                    title, text = research.read_page(r["url"])
                except Exception:  # noqa: BLE001
                    continue
                if len(text) > 200:
                    sources.append({"title": title or r["title"], "url": r["url"], "text": text})
                if len(sources) >= 5:
                    break
            if not sources:
                return self.emit({"type": "error", "error": "Could not read any of the found pages."})
            self.emit({"type": "sources", "sources": [{"title": s["title"], "url": s["url"]} for s in sources]})
            self.emit({"type": "status", "t": f"Writing report from {len(sources)} sources…"})
            for kind, c in providers.chat_stream(prov, model, research.report_prompt(question, sources), {"temperature": 0.3}):
                self.emit({"type": kind, "t": c})
            self.emit({"type": "done"})
        except providers.ProviderError as e:
            self.emit({"type": "error", "error": str(e)})

    # documents
    def list_documents(self):
        """GET /api/documents"""
        self.send_json(self.app.db.list_documents())

    def create_document(self):
        """POST /api/documents"""
        d = self.body()
        self.send_json(self.app.db.save_document(None, d.get("title") or "Untitled", d.get("content", "")))

    def get_document(self, did):
        """GET /api/documents/<id>"""
        doc = self.app.db.get_document(did)
        return self.send_json(doc) if doc else self.error("Not found", 404)

    def put_document(self, did):
        """PUT /api/documents/<id>"""
        d = self.body()
        self.send_json(self.app.db.save_document(did, d.get("title") or "Untitled", d.get("content", "")))

    def delete_document(self, did):
        """DELETE /api/documents/<id>"""
        self.app.db.delete_document(did)
        self.send_json({"ok": True})

    def document_ai(self):
        """POST /api/documents/ai: stream a rewrite of the document or of `selection` following `instruction`."""
        d = self.body()
        instruction = (d.get("instruction") or "").strip()
        if not instruction:
            raise ValueError("Tell the AI what to do")
        prov, model = self.app.resolve(d.get("model"))
        selection = d.get("selection") or ""
        content = d.get("content") or ""
        if selection:
            user = (f"Full document for context:\n\n{content}\n\n---\nRewrite ONLY this selected part:\n\n{selection}"
                    f"\n\n---\nInstruction: {instruction}")
        else:
            user = f"Document:\n\n{content}\n\n---\nInstruction: {instruction}"
        messages = [
            {"role": "system", "content": "You are a writing assistant inside a Markdown editor. Return ONLY the "
                                          "resulting text, no explanations, no code fences around it."},
            {"role": "user", "content": user},
        ]
        self.start_stream()
        try:
            for kind, c in providers.chat_stream(prov, model, messages, self.app.options()):
                self.emit({"type": kind, "t": c})
            self.emit({"type": "done"})
        except providers.ProviderError as e:
            self.emit({"type": "error", "error": str(e)})

    # notes
    def list_notes(self):
        """GET /api/notes"""
        self.send_json(self.app.db.list_notes())

    def create_note(self):
        """POST /api/notes"""
        d = self.body()
        content = (d.get("content") or "").strip()
        if not content:
            raise ValueError("Note is empty")
        self.send_json(self.app.db.add_note(content, d.get("is_memory", False)))

    def patch_note(self, nid):
        """PATCH /api/notes/<id>: change text or memory flag."""
        d = self.body()
        self.app.db.update_note(nid, d.get("content"), d.get("is_memory"))
        self.send_json({"ok": True})

    def delete_note(self, nid):
        """DELETE /api/notes/<id>"""
        self.app.db.delete_note(nid)
        self.send_json({"ok": True})

    # model management (Ollama)
    def pull(self):
        """POST /api/models/pull: download an Ollama model and stream its progress.

        Progress of all layers is summed so the bar moves smoothly from 0 to 100 %.
        Closing the request (Cancel in the UI) stops the download; Ollama resumes it next time."""
        d = self.body()
        prov = self.app.provider(d["provider"]) if d.get("provider") else self.app.ollama_provider()
        if prov["type"] != "ollama":
            raise ValueError("Downloading models only works with Ollama")
        name = (d.get("model") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._:/-]+", name):
            raise ValueError("Invalid model name")
        self.start_stream()
        layers = {}
        events = providers.ollama_pull(prov, name)
        try:
            for ev in events:
                if ev.get("digest") and ev.get("total"):
                    layers[ev["digest"]] = (ev.get("completed") or 0, ev["total"])
                done = sum(c for c, _ in layers.values())
                total = sum(t for _, t in layers.values())
                self.emit({"type": "progress", "status": ev.get("status", ""), "completed": done, "total": total})
            self.emit({"type": "done"})
        except providers.ProviderError as e:
            self.emit({"type": "error", "error": str(e)})
        finally:
            events.close()  # closes the connection to Ollama, which cancels an unfinished pull

    def ollama_status(self):
        """GET /api/ollama: installed / running / version, installed models, catalog, install method."""
        self.send_json(ollama.status(self.app.ollama_provider(), self.app.ram))

    def ollama_start(self):
        """POST /api/ollama/start: start the local Ollama server in the background."""
        version = ollama.start(self.app.ollama_provider())
        self.send_json({"ok": True, "version": version})

    def ollama_install(self):
        """POST /api/ollama/install: install Ollama with winget (Windows) or Homebrew (macOS), streaming the output."""
        method, command = ollama.install_method()
        cmd = ollama.install_command(method)
        if not cmd:
            raise ValueError(f"Install Ollama yourself: {command}")
        self.start_stream()
        self.emit({"type": "status", "t": "$ " + " ".join(cmd)})
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
        except OSError as e:
            return self.emit({"type": "error", "error": str(e)})
        for line in proc.stdout:
            if line.strip():
                self.emit({"type": "status", "t": line.rstrip()[-300:]})
        if proc.wait() != 0:
            return self.emit({"type": "error", "error": f"Installer exited with code {proc.returncode}"})
        self.emit({"type": "done"})

    def delete_model(self):
        """POST /api/models/delete: remove an Ollama model from disk."""
        d = self.body()
        prov, model = self.app.resolve(d.get("model"))
        if prov["type"] != "ollama":
            raise ValueError("Deleting models only works with Ollama")
        providers.ollama_delete(prov, model)
        self.send_json({"ok": True})


ID = r"([a-f0-9]{16})"
ROUTES = [
    (r"/api/logout", "POST", Handler.logout),
    (r"/api/settings", "GET", Handler.get_settings),
    (r"/api/settings", "PUT", Handler.put_settings),
    (r"/api/models", "GET", Handler.get_models),
    (r"/api/models/pull", "POST", Handler.pull),
    (r"/api/models/delete", "POST", Handler.delete_model),
    (r"/api/ollama", "GET", Handler.ollama_status),
    (r"/api/ollama/start", "POST", Handler.ollama_start),
    (r"/api/ollama/install", "POST", Handler.ollama_install),
    (r"/api/sessions", "GET", Handler.list_sessions),
    (r"/api/sessions", "POST", Handler.create_session),
    (rf"/api/sessions/{ID}", "GET", Handler.get_session),
    (rf"/api/sessions/{ID}", "PATCH", Handler.patch_session),
    (rf"/api/sessions/{ID}", "DELETE", Handler.delete_session),
    (r"/api/chat", "POST", Handler.chat),
    (r"/api/compare", "POST", Handler.compare),
    (r"/api/research", "POST", Handler.research),
    (r"/api/documents", "GET", Handler.list_documents),
    (r"/api/documents", "POST", Handler.create_document),
    (r"/api/documents/ai", "POST", Handler.document_ai),
    (rf"/api/documents/{ID}", "GET", Handler.get_document),
    (rf"/api/documents/{ID}", "PUT", Handler.put_document),
    (rf"/api/documents/{ID}", "DELETE", Handler.delete_document),
    (r"/api/notes", "GET", Handler.list_notes),
    (r"/api/notes", "POST", Handler.create_note),
    (rf"/api/notes/{ID}", "PATCH", Handler.patch_note),
    (rf"/api/notes/{ID}", "DELETE", Handler.delete_note),
]


def make_server(host, port, data_dir):
    """Create a threaded HTTP server bound to host:port with its own App for `data_dir`."""
    handler = type("BoundHandler", (Handler,), {"app": App(data_dir)})
    srv = ThreadingHTTPServer((host, port), handler)
    srv.daemon_threads = True
    return srv
