"""MCP (Model Context Protocol) client: tools of MCP servers for the chat (🔌) and agent mode.

Two kinds of servers: "stdio" (Sunak starts the server as a program and speaks JSON-RPC lines over its
stdin/stdout) and "http" (Streamable HTTP: JSON-RPC over POST, answers as JSON or server-sent events).
Sunak uses only tools (tools/list, tools/call), and every call needs the user's approval in the chat
(see agent.AgentRun). Pure standard library."""

import hashlib
import json
import os
import queue
import re
import shlex
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__, providers

PROTOCOL = "2025-06-18"
START_TIMEOUT = 60      # the first start of "npx -y …" or "uvx …" downloads the server
CALL_TIMEOUT = 300
STDERR_KEEP = 2000      # characters of a server's error output kept for messages
MAX_SERVERS = 20


class MCPError(Exception):
    """An MCP server could not be started or did not answer; the message is for the user."""


# names and results ----------------------------------------------------------------------------

def slug(text, size):
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", text).strip("_")[:size] or "x"


def exposed_name(server, tool):
    """The tool name the model sees: server and tool, at most 64 of [a-zA-Z0-9_-] (Claude and OpenAI rules)."""
    name = f"{slug(server, 20)}__{slug(tool, 200)}"
    if len(name) > 64:
        name = name[:55] + "_" + hashlib.sha1(f"{server}\0{tool}".encode()).hexdigest()[:8]
    return name


def result_text(res):
    """(text, is_error) of a tools/call result."""
    if not isinstance(res, dict):
        return json.dumps(res, ensure_ascii=False), False
    out = []
    for c in res.get("content") or []:
        if not isinstance(c, dict):
            continue
        kind = c.get("type")
        if kind == "text":
            out.append(str(c.get("text", "")))
        elif kind == "resource":
            r = c.get("resource") or {}
            out.append(str(r.get("text")) if r.get("text") is not None else f"[resource {r.get('uri', '')}]")
        elif kind == "resource_link":
            out.append(f"[{c.get('name') or 'link'}: {c.get('uri', '')}]")
        elif kind in ("image", "audio"):
            out.append(f"[{kind} ({c.get('mimeType', '?')}), not shown]")
    if not out and res.get("structuredContent") is not None:
        out.append(json.dumps(res["structuredContent"], ensure_ascii=False))
    return "\n".join(out).strip() or "(no output)", bool(res.get("isError"))


def schema(tool):
    """The tool's input schema in the form every backend accepts (an object schema)."""
    s = tool.get("inputSchema")
    if not isinstance(s, dict) or s.get("type") != "object":
        return {"type": "object", "properties": {}}
    s = dict(s)
    s.setdefault("properties", {})
    return s


def split(command):
    """A command line as a list; on Windows backslashes stay and "quoted parts" lose their quotes."""
    if os.name != "nt":
        return shlex.split(command)
    return [a[1:-1] if len(a) > 1 and a[0] == a[-1] == '"' else a for a in shlex.split(command, posix=False)]


# servers --------------------------------------------------------------------------------------

class Server:
    """One MCP server connection. Subclasses implement _open, _request, _notify and close."""

    def __init__(self, config):
        self.config = config
        self.name = config.get("name") or config["id"]
        self.tools = None
        self._lock = threading.Lock()
        self._next = 0

    def _id(self):
        self._next += 1
        return self._next

    def start(self):
        self._open()
        init = self._request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                            "clientInfo": {"name": "sunak", "version": __version__}}, START_TIMEOUT)
        self.info = init.get("serverInfo") or {} if isinstance(init, dict) else {}
        self._notify("notifications/initialized")
        tools, cursor = [], None
        for _ in range(50):
            res = self._request("tools/list", {"cursor": cursor} if cursor else {}, START_TIMEOUT)
            tools += [t for t in (res.get("tools") or []) if isinstance(t, dict) and isinstance(t.get("name"), str)]
            cursor = res.get("nextCursor")
            if not cursor:
                break
        self.tools = tools
        return tools

    def alive(self):
        return True

    def call(self, tool, args, cancelled=None):
        """(text, is_error) of one tool call."""
        with self._lock:
            res = self._request("tools/call", {"name": tool, "arguments": args}, CALL_TIMEOUT, cancelled)
        return result_text(res)


def _answer(msg, method_id):
    """The result of a JSON-RPC answer, or MCPError for an error answer."""
    if msg.get("error"):
        err = msg["error"]
        raise MCPError(err.get("message", str(err)) if isinstance(err, dict) else str(err))
    return msg.get("result") or {}


class StdioServer(Server):
    """A server program started by Sunak; JSON-RPC messages are single lines on stdin/stdout."""

    def __init__(self, config):
        super().__init__(config)
        self.proc = None
        self.waiting = {}
        self.stderr = ""
        self._write = threading.Lock()

    def _open(self):
        argv = split(self.config["command"])
        if not argv:
            raise MCPError("The command is empty")
        exe = shutil.which(argv[0])
        if not exe:
            raise MCPError(f"Program not found: {argv[0]}. Is it installed and in the PATH?")
        env = dict(os.environ, **(self.config.get("env") or {}))
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self.proc = subprocess.Popen([exe] + argv[1:], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, env=env, cwd=os.path.expanduser("~"), creationflags=flags)
        except OSError as e:
            raise MCPError(f"Could not start {argv[0]}: {e.strerror or e}") from None
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._read_err, daemon=True).start()

    def alive(self):
        p = self.proc
        return p is not None and p.poll() is None

    def _read(self):
        for raw in self.proc.stdout:
            try:
                msg = json.loads(raw)
            except ValueError:
                continue  # some servers print other things on stdout
            if not isinstance(msg, dict):
                continue
            if "method" in msg:
                if "id" in msg:  # a request from the server: answer the harmless ones
                    if msg["method"] == "ping":
                        self._send({"jsonrpc": "2.0", "id": msg["id"], "result": {}})
                    elif msg["method"] == "roots/list":
                        self._send({"jsonrpc": "2.0", "id": msg["id"], "result": {"roots": []}})
                    else:
                        self._send({"jsonrpc": "2.0", "id": msg["id"],
                                    "error": {"code": -32601, "message": "Not supported by Sunak"}})
                continue
            q = self.waiting.get(msg.get("id"))
            if q:
                q.put(msg)
        for q in list(self.waiting.values()):
            q.put(None)  # the program ended

    def _read_err(self):
        for raw in self.proc.stderr:
            self.stderr = (self.stderr + raw.decode("utf-8", "replace"))[-STDERR_KEEP:]

    def _send(self, msg):
        with self._write:
            try:
                self.proc.stdin.write(json.dumps(msg).encode() + b"\n")
                self.proc.stdin.flush()
            except OSError:
                pass  # noticed by the waiting request

    def _notify(self, method, params=None):
        self._send({"jsonrpc": "2.0", "method": method, **({"params": params} if params else {})})

    def _request(self, method, params, timeout, cancelled=None):
        rid = self._id()
        q = self.waiting[rid] = queue.Queue()
        try:
            self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            deadline = time.monotonic() + timeout
            while True:
                try:
                    msg = q.get(timeout=0.2)
                    break
                except queue.Empty:
                    if cancelled is not None and cancelled.is_set():
                        self._notify("notifications/cancelled", {"requestId": rid, "reason": "Stopped by the user"})
                        raise MCPError("Stopped") from None
                    if time.monotonic() > deadline:
                        self._notify("notifications/cancelled", {"requestId": rid, "reason": "Timeout"})
                        raise MCPError(f"{self.name} did not answer within {timeout} seconds") from None
            if msg is None:
                detail = self.stderr.strip().splitlines()[-3:]
                raise MCPError(f"{self.name} stopped" + (": " + " ".join(detail) if detail else ""))
            return _answer(msg, rid)
        finally:
            self.waiting.pop(rid, None)

    def close(self):
        p, self.proc = self.proc, None
        if not p:
            return
        for f in (p.stdin,):
            try:
                f.close()
            except OSError:
                pass
        try:
            p.wait(2)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait(5)


class HttpServer(Server):
    """A server reachable over Streamable HTTP (one URL, JSON-RPC by POST)."""

    def __init__(self, config):
        super().__init__(config)
        self.session = None
        self.version = None

    def _open(self):
        self.session = None

    def _headers(self):
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "User-Agent": "sunak"}
        if self.config.get("token"):
            h["Authorization"] = f"Bearer {self.config['token']}"
        if self.session:
            h["Mcp-Session-Id"] = self.session
        if self.version:
            h["MCP-Protocol-Version"] = self.version
        return h

    def _post(self, msg, timeout):
        url = self.config["url"]
        req = urllib.request.Request(url, data=json.dumps(msg).encode(), headers=self._headers(), method="POST")
        opener = providers._DIRECT if providers._is_local(url) else providers._DEFAULT
        try:
            return opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300].strip()
            raise MCPError(f"{self.name}: HTTP {e.code} {detail}".strip()) from None
        except (urllib.error.URLError, OSError) as e:
            raise MCPError(f"Cannot reach {self.name} at {url}: {getattr(e, 'reason', e)}") from None

    def _notify(self, method, params=None):
        try:
            self._post({"jsonrpc": "2.0", "method": method, **({"params": params} if params else {})}, 30).close()
        except MCPError:
            pass

    def _request(self, method, params, timeout, cancelled=None):
        rid = self._id()
        with self._post({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}, timeout) as r:
            if method == "initialize":
                self.session = r.headers.get("Mcp-Session-Id") or None
            if "text/event-stream" in (r.headers.get("Content-Type") or ""):
                msg = self._from_events(r, rid, cancelled)
            else:
                try:
                    msg = json.loads(r.read())
                except ValueError:
                    raise MCPError(f"{self.name} sent an answer that is not JSON") from None
        if not isinstance(msg, dict):
            raise MCPError(f"{self.name} sent an unexpected answer")
        res = _answer(msg, rid)
        if method == "initialize" and isinstance(res, dict):
            self.version = res.get("protocolVersion") or PROTOCOL
        return res

    def _from_events(self, r, rid, cancelled):
        data = []
        for raw in r:
            if cancelled is not None and cancelled.is_set():
                raise MCPError("Stopped")
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line.startswith("data:"):
                data.append(line[5:].lstrip())
            elif not line and data:
                try:
                    msg = json.loads("\n".join(data))
                except ValueError:
                    msg = None
                data = []
                if isinstance(msg, dict) and msg.get("id") == rid and "method" not in msg:
                    return msg
        raise MCPError(f"{self.name} ended the answer without a result")

    def close(self):
        if self.session:
            req = urllib.request.Request(self.config["url"], headers=self._headers(), method="DELETE")
            opener = providers._DIRECT if providers._is_local(self.config["url"]) else providers._DEFAULT
            try:
                opener.open(req, timeout=5).close()
            except (urllib.error.URLError, OSError):
                pass
            self.session = None


def connect(config):
    return StdioServer(config) if config["type"] == "stdio" else HttpServer(config)


# settings -------------------------------------------------------------------------------------

def clean(items, old):
    """Validate the server list from the settings page. Saved environment values and tokens are never sent
    to the browser: missing ones are kept, but only for the same command or address. Raises ValueError."""
    if not isinstance(items, list) or not all(isinstance(s, dict) for s in items):
        raise ValueError("mcp_servers must be a list of objects")
    if len(items) > MAX_SERVERS:
        raise ValueError(f"At most {MAX_SERVERS} MCP servers")
    prev_by_id = {s["id"]: s for s in old}
    out = []
    for s in items:
        kind = s.get("type")
        name = str(s.get("name") or "").strip()[:40]
        if kind not in ("stdio", "http"):
            raise ValueError("Each MCP server needs a type: stdio (a program) or http (an address)")
        if not name:
            raise ValueError("Each MCP server needs a name")
        sid = re.sub(r"[^a-z0-9_-]", "", str(s.get("id") or "").lower())[:24] or slug(name.lower(), 24).lower()
        while any(c["id"] == sid for c in out):
            sid += "x"
        prev = prev_by_id.get(str(s.get("id") or ""))
        entry = {"id": sid, "name": name, "type": kind, "enabled": s.get("enabled") is not False}
        if kind == "stdio":
            cmd = s.get("command")
            if not isinstance(cmd, str) or not cmd.strip():
                raise ValueError(f"{name}: enter the command that starts the server")
            try:
                split(cmd)
            except ValueError as e:
                raise ValueError(f"{name}: the command cannot be read ({e})") from None
            entry["command"] = cmd.strip()
            env = s.get("env")
            if env is None and prev and prev.get("type") == "stdio" and prev.get("command") == entry["command"]:
                env = prev.get("env") or {}
            entry["env"] = parse_env(env or {}, name)
        else:
            url = s.get("url")
            if not isinstance(url, str) or not re.match(r"https?://[^/\s]+", url.strip(), re.I):
                raise ValueError(f"{name}: the address must start with http:// or https://")
            entry["url"] = url.strip()
            token = s.get("token") if isinstance(s.get("token"), str) else ""
            if not token.strip() and prev and prev.get("type") == "http" and prev.get("url") == entry["url"]:
                token = prev.get("token", "")
            entry["token"] = token.strip()
        out.append(entry)
    return out


def parse_env(env, name):
    """Environment variables from {"KEY": "value"} or "KEY=value" lines."""
    if isinstance(env, str):
        pairs = {}
        for line in env.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ValueError(f"{name}: write environment variables as NAME=value, one per line")
            k, v = line.split("=", 1)
            pairs[k.strip()] = v.strip()
        env = pairs
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        raise ValueError(f"{name}: environment variables must be text")
    for k in env:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
            raise ValueError(f"{name}: {k!r} is not a valid variable name")
    return env


def public(config):
    """A server as the browser sees it: without environment values and token."""
    out = {k: v for k, v in config.items() if k not in ("env", "token")}
    if config["type"] == "stdio":
        out["env_keys"] = sorted(config.get("env") or {})
    else:
        out["has_token"] = bool(config.get("token"))
    return out


# all servers of this Sunak -------------------------------------------------------------------

class Manager:
    """Running MCP servers. They start when a chat first needs their tools and keep running until the
    settings change or Sunak stops."""

    def __init__(self):
        self.running = {}
        self.configs = None   # the current settings, once configure() ran
        self._lock = threading.Lock()
        self._starting = threading.Lock()  # one start phase at a time, so two chats never start a server twice

    def configure(self, configs):
        """Stop servers whose settings changed or that were removed."""
        with self._lock:
            keep = self.configs = {c["id"]: c for c in configs}
            for sid, srv in list(self.running.items()):
                if keep.get(sid) != srv.config:
                    srv.close()
                    del self.running[sid]

    def _start(self, config):
        srv = connect(config)
        try:
            srv.start()
        except Exception:
            srv.close()
            raise
        return srv

    def tools(self, configs, on_start=None):
        """[(exposed name, server, tool dict)] of all enabled servers and {server name: error}. Servers that
        are not running yet start in parallel; `on_start(name)` is called for each."""
        enabled = [c for c in configs if c.get("enabled")]
        with self._starting:
            errors = self._start_missing(enabled, on_start)
        out, seen = [], set()
        for c in enabled:
            srv = self.running.get(c["id"])
            if not srv:
                errors.setdefault(c["name"], "did not start in time")
                continue
            for t in srv.tools or []:
                name = exposed_name(c["name"], t["name"])
                if name not in seen:
                    seen.add(name)
                    out.append((name, srv, t))
        return out, errors

    def _start_missing(self, enabled, on_start):
        with self._lock:
            for c in enabled:  # a server program that ended (crash, killed) is started again
                srv = self.running.get(c["id"])
                if srv and not srv.alive():
                    srv.close()
                    del self.running[c["id"]]
            todo = [c for c in enabled if c["id"] not in self.running]
        errors = {}

        def start(c):
            try:
                srv = self._start(c)
            except Exception as e:  # noqa: BLE001 - a broken server must not break the chat
                errors[c["name"]] = str(e) if isinstance(e, (MCPError, OSError, ValueError)) else f"unexpected answer ({type(e).__name__})"
                return
            with self._lock:
                if self.configs is not None and self.configs.get(c["id"]) != c:
                    old = srv  # the settings changed meanwhile
                else:
                    old = self.running.pop(c["id"], None)
                    self.running[c["id"]] = srv
            if old:
                old.close()

        threads = []
        for c in todo:
            if on_start:
                on_start(c["name"])
            t = threading.Thread(target=start, args=(c,), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join(START_TIMEOUT + 5)
        return errors

    def close_all(self):
        with self._lock:
            for srv in self.running.values():
                srv.close()
            self.running.clear()


def test(config):
    """Start a server once and list its tools (Settings → Test)."""
    srv = connect(config)
    try:
        return srv.start()
    finally:
        srv.close()
