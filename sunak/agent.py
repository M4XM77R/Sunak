"""Agent mode ("agentic coding"): the model works in one project folder the user picked.

It may list, read and search files there on its own. Writing a file, editing a file and running a
shell command each need the user's click ("Allow", or "Allow for this chat"). Every path is checked
against the folder after resolving `..` and symlinks, so the model cannot reach anything outside.

Tool calling uses the native format of each backend (Claude tool use, Ollama `tools`, OpenAI
`tools`). Models without tool support fall back to a small text protocol (```tool blocks).
Pure standard library."""

import difflib
import http.client
import json
import os
import platform
import secrets
import signal
import subprocess
import sys
import threading
import time
import urllib.parse

from . import jobqueue, mcp, providers, usage
from .providers import ProviderError

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache", ".tox",
             ".idea", ".next", ".cache"}
MAX_FILE = 2 * 1024 * 1024        # largest file the agent reads or edits
READ_LINES = 2000                 # lines per read_file call
MAX_RESULT = 30_000               # characters of one tool result sent to the model
MAX_WRITE = 2_000_000             # characters written by one write_file call
LIST_MAX = 500                    # entries of list_files
SEARCH_HITS = 200                 # matching lines of search
SEARCH_FILES = 5000               # files looked at by one search
OUT_HEAD, OUT_TAIL = 20_000, 30_000  # bytes of command output kept (start and end)
CONFIRM_TIMEOUT = 1800            # an unanswered question counts as "deny" after 30 minutes
PING_EVERY = 15                   # keep-alive while waiting, also notices a closed browser tab
UI_OUTPUT = 4000                  # characters of a tool result shown in the browser and stored
UI_DIFF = 20_000

TOOLS = [
    {"name": "list_files",
     "description": "List files and folders in the project. Folders end with /. Paths are relative to the project root.",
     "parameters": {"type": "object", "properties": {
         "path": {"type": "string", "description": "Folder to list, default '.' (the project root)"},
         "recursive": {"type": "boolean", "description": "Also list subfolders (skips .git, node_modules and similar)"}},
         "required": []}},
    {"name": "read_file",
     "description": f"Read a text file of the project. Returns at most {READ_LINES} lines; use start_line to read further.",
     "parameters": {"type": "object", "properties": {
         "path": {"type": "string", "description": "File path relative to the project root"},
         "start_line": {"type": "integer", "description": "First line to return (1-based), default 1"},
         "end_line": {"type": "integer", "description": "Last line to return (inclusive)"}},
         "required": ["path"]}},
    {"name": "search",
     "description": "Search all text files of the project (or one folder) for a text. Returns file:line: text for each match.",
     "parameters": {"type": "object", "properties": {
         "pattern": {"type": "string", "description": "Text to find (case-insensitive), or a regular expression when regex is true"},
         "path": {"type": "string", "description": "Folder or file to search in, default '.'"},
         "regex": {"type": "boolean", "description": "Treat pattern as a Python regular expression"}},
         "required": ["pattern"]}},
    {"name": "write_file",
     "description": "Create a file or replace its whole content. Missing folders are created. "
                    "The user must approve it. For small changes to an existing file use edit_file.",
     "parameters": {"type": "object", "properties": {
         "path": {"type": "string", "description": "File path relative to the project root"},
         "content": {"type": "string", "description": "The complete new content of the file"}},
         "required": ["path", "content"]}},
    {"name": "edit_file",
     "description": "Replace an exact piece of text in a file. old_text must match the file exactly (including "
                    "indentation) and occur only once unless replace_all is true. The user must approve it.",
     "parameters": {"type": "object", "properties": {
         "path": {"type": "string", "description": "File path relative to the project root"},
         "old_text": {"type": "string", "description": "Exact text to replace; include enough lines to make it unique"},
         "new_text": {"type": "string", "description": "Replacement text"},
         "replace_all": {"type": "boolean", "description": "Replace every occurrence"}},
         "required": ["path", "old_text", "new_text"]}},
    {"name": "run_command",
     "description": "Run a shell command in the project folder and return its exit code and output. "
                    "There is no input (stdin is empty) and a time limit. The user must approve it.",
     "parameters": {"type": "object", "properties": {
         "command": {"type": "string", "description": "The command line, e.g. 'python -m pytest -q'"}},
         "required": ["command"]}},
]
TOOL_NAMES = {t["name"] for t in TOOLS}
_TYPES = {"string": str, "boolean": bool, "integer": int}


class ToolError(Exception):
    """A tool call failed; the message goes back to the model so it can correct itself."""


class Cancelled(Exception):
    """The user stopped the agent."""


class ToolsUnsupported(Exception):
    """The backend rejected the request because the model cannot call tools."""


# folder checks --------------------------------------------------------------------------------

def _norm(p):
    return os.path.normcase(os.path.realpath(p))


def _inside(path, root):
    """True when `path` (resolved) is `root` or lies below it."""
    try:
        return os.path.commonpath([_norm(path), _norm(root)]) == _norm(root)
    except ValueError:  # different drives on Windows
        return False


def check_folder(folder, data_dir):
    """Validate the project folder chosen by the user and return its resolved absolute path.
    Raises ValueError. Not allowed: a drive root, the home folder itself, and any folder that
    contains Sunak's data folder (API keys, password hash) or lies inside it."""
    if not isinstance(folder, str) or not folder.strip() or "\x00" in folder:
        raise ValueError("Choose a project folder for the agent")
    path = os.path.expanduser(folder.strip())
    if not os.path.isabs(path):
        raise ValueError("Enter the full path of the project folder, e.g. /home/me/project or C:\\Users\\me\\project")
    real = os.path.realpath(path)
    if not os.path.isdir(real):
        raise ValueError(f"Folder not found: {folder.strip()}")
    if os.path.dirname(real) == real:
        raise ValueError("The agent cannot work on a whole drive. Choose a project folder.")
    if _norm(real) == _norm(os.path.expanduser("~")):
        raise ValueError("The agent cannot work on your whole home folder. Choose a project folder.")
    if _inside(data_dir, real) or _inside(real, data_dir):
        raise ValueError("This folder contains Sunak's own data (keys, chats). Choose another folder.")
    return real


class Workspace:
    """The project folder. Every path from the model goes through `path()`."""

    def __init__(self, root):
        self.root = os.path.realpath(root)

    def path(self, rel):
        """Resolve a model-given path (relative to the root) and make sure it stays inside."""
        if not isinstance(rel, str) or "\x00" in rel:
            raise ToolError("Invalid path")
        rel = rel.strip() or "."
        full = os.path.realpath(os.path.join(self.root, rel))
        if not _inside(full, self.root):
            raise ToolError(f"{rel} is outside the project folder. Only paths inside the project are allowed.")
        return full

    def rel(self, full):
        r = os.path.relpath(full, self.root)
        return "." if r == "." else r.replace(os.sep, "/")

    # read-only tools ------------------------------------------------------------------------
    def list_files(self, path=".", recursive=False):
        top = self.path(path)
        if not os.path.isdir(top):
            raise ToolError(f"{path} is not a folder")
        out, more = [], False
        for cur, dirs, files in os.walk(top):
            dirs[:] = sorted(d for d in dirs if not (recursive and d in SKIP_DIRS))
            prefix = "" if not recursive or self.rel(cur) == "." else self.rel(cur) + "/"
            for n in [d + "/" for d in dirs] + sorted(files):
                if len(out) >= LIST_MAX:
                    more = True
                    break
                p = os.path.join(cur, n.rstrip("/"))
                if os.path.islink(p):
                    n = n.rstrip("/") + "@"  # symlinks are listed but never followed
                elif not n.endswith("/"):
                    try:
                        n += f"  ({os.path.getsize(p)} bytes)"
                    except OSError:
                        pass
                out.append(prefix + n)
            if not recursive or more:
                break
        if not out:
            return "(empty folder)"
        return "\n".join(out) + (f"\n… more than {LIST_MAX} entries, list a subfolder" if more else "")

    def read_text(self, full):
        """File content as text with its own line endings. Raises ToolError for binary or huge files."""
        if not os.path.isfile(full):
            raise ToolError(f"{self.rel(full)} is not a file")
        if os.path.getsize(full) > MAX_FILE:
            raise ToolError(f"{self.rel(full)} is larger than {MAX_FILE // 1024 // 1024} MB")
        with open(full, "rb") as f:
            data = f.read()
        if b"\x00" in data[:8192]:
            raise ToolError(f"{self.rel(full)} is a binary file")
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            raise ToolError(f"{self.rel(full)} is not UTF-8 text") from None

    def read_file(self, path, start_line=1, end_line=None):
        full = self.path(path)
        lines = self.read_text(full).replace("\r\n", "\n").split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        total = len(lines)
        start = max(1, start_line or 1)
        end = min(total, end_line or total, start + READ_LINES - 1)
        if total == 0:
            return f"{self.rel(full)} is empty"
        if start > total:
            raise ToolError(f"{self.rel(full)} has only {total} lines")
        body = "\n".join(lines[start - 1:end])
        head = f"{self.rel(full)} (lines {start}-{end} of {total})" if (start, end) != (1, total) else self.rel(full)
        return f"{head}:\n{body}"

    def search(self, pattern, path=".", regex=False):
        import re
        if not pattern:
            raise ToolError("pattern is empty")
        try:
            rx = re.compile(pattern if regex else re.escape(pattern), re.I)
        except re.error as e:
            raise ToolError(f"Invalid regular expression: {e}") from None
        top = self.path(path)
        if os.path.isfile(top):
            files = [top]
        else:
            files = []
            for cur, dirs, names in os.walk(top):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not os.path.islink(os.path.join(cur, d)))
                files += [os.path.join(cur, n) for n in sorted(names)]
                if len(files) > SEARCH_FILES:
                    break
        hits = []
        for f in files[:SEARCH_FILES]:
            if os.path.islink(f) and not _inside(f, self.root):
                continue
            try:
                if os.path.getsize(f) > MAX_FILE // 2:
                    continue
                text = self.read_text(f)
            except (ToolError, OSError):
                continue
            for no, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{self.rel(f)}:{no}: {line.strip()[:300]}")
                    if len(hits) >= SEARCH_HITS:
                        return "\n".join(hits) + f"\n… stopped after {SEARCH_HITS} matches, search more precisely"
        return "\n".join(hits) or "No matches"


def _diff(rel, old, new):
    """Unified diff for the user; `old` is None for a new file."""
    a = (old or "").replace("\r\n", "\n").splitlines(keepends=True)
    b = new.replace("\r\n", "\n").splitlines(keepends=True)
    d = "".join(difflib.unified_diff(a, b, "a/" + rel if old is not None else "/dev/null", "b/" + rel, n=3))
    return d or "(no change)"


def _clip(text, limit, keep_end=False):
    if len(text) <= limit:
        return text
    if keep_end:
        half = limit // 2
        return text[:half] + f"\n… [{len(text) - limit} characters left out] …\n" + text[-half:]
    return text[:limit] + f"\n… [{len(text) - limit} more characters left out]"


class Action:
    """A prepared tool call. `kind` is None (runs at once), "write" or "run" (needs approval);
    `preview` is what the user sees before approving; `run()` does it and returns the result text."""

    def __init__(self, run, kind=None, preview=None):
        self.run, self.kind, self.preview = run, kind, preview or {}


def describe(name, args):
    """Short human-readable title of a tool call."""
    args = args if isinstance(args, dict) else {}
    target = args.get("command") if name == "run_command" else args.get("path") or args.get("pattern") or ""
    if name == "search" and args.get("path"):
        target = f"{args.get('pattern', '')}  in {args['path']}"
    return f"{name} {str(target)[:200]}".strip()


def _check_args(name, args):
    spec = next((t["parameters"] for t in TOOLS if t["name"] == name), None)
    if spec is None:
        raise ToolError(f"Unknown tool {name}. Available tools: {', '.join(sorted(TOOL_NAMES))}")
    if not isinstance(args, dict):
        raise ToolError("Tool arguments must be a JSON object")
    for key in spec["required"]:
        if key not in args:
            raise ToolError(f"{name} needs the argument {key}")
    clean = {}
    for key, val in args.items():
        prop = spec["properties"].get(key)
        if prop is None or val is None:
            continue  # unknown or empty optional arguments are ignored
        want = _TYPES[prop["type"]]
        if want is int and isinstance(val, float) and val.is_integer():
            val = int(val)
        if not isinstance(val, want) or (want is int and isinstance(val, bool)):
            raise ToolError(f"{name}: {key} must be a {prop['type']}")
        clean[key] = val
    return clean


# shell commands -------------------------------------------------------------------------------

def _env():
    env = dict(os.environ)
    env.pop("SUNAK_PASSWORD", None)
    env["GIT_TERMINAL_PROMPT"] = "0"  # never hang on a password prompt
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def _kill(proc):
    """Stop a command together with everything it started."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=10)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
        proc.wait(5)
    except (OSError, subprocess.SubprocessError):
        pass


def run_command(command, cwd, timeout, cancelled):
    """Run `command` in a shell in `cwd`. Returns (exit code or None, output, note).
    Kills the whole process group on timeout or when `cancelled` (threading.Event) is set;
    in that case raises Cancelled."""
    kw = {"start_new_session": True} if os.name != "nt" else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    proc = subprocess.Popen(command, shell=True, cwd=cwd, env=_env(), stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kw)
    head, tail, dropped = bytearray(), bytearray(), [0]

    def reader():
        for chunk in iter(lambda: proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(4096), b""):
            room = OUT_HEAD - len(head)
            if room > 0:
                head.extend(chunk[:room])
                chunk = chunk[room:]
            tail.extend(chunk)
            if len(tail) > OUT_TAIL:
                dropped[0] += len(tail) - OUT_TAIL
                del tail[:len(tail) - OUT_TAIL]

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    deadline = time.monotonic() + timeout
    note = ""
    try:
        while True:
            try:
                proc.wait(0.2)
                break
            except subprocess.TimeoutExpired:
                pass
            if cancelled.is_set():
                _kill(proc)
                raise Cancelled
            if time.monotonic() > deadline:
                _kill(proc)
                note = f"Stopped: the command ran longer than {timeout} seconds."
                break
    finally:
        t.join(5)  # a detached grandchild may keep the pipe open; don't wait for it forever
        try:
            proc.stdout.close()
        except OSError:
            pass
    out = bytes(head)
    if dropped[0]:
        out += f"\n… [{dropped[0]} bytes of output left out] …\n".encode()
    out += bytes(tail)
    text = out.decode("utf-8", "replace")
    return (None if note else proc.returncode), text, note


# preparing tool calls -------------------------------------------------------------------------

def prepare(ws, name, args, timeout, cancelled):
    """Validate a tool call and return an Action. Raises ToolError."""
    args = _check_args(name, args)
    if name == "list_files":
        return Action(lambda: ws.list_files(args.get("path", "."), args.get("recursive", False)))
    if name == "read_file":
        return Action(lambda: ws.read_file(args["path"], args.get("start_line", 1), args.get("end_line")))
    if name == "search":
        return Action(lambda: ws.search(args["pattern"], args.get("path", "."), args.get("regex", False)))
    if name in ("write_file", "edit_file"):
        full = ws.path(args["path"])
        rel = ws.rel(full)
        if os.path.isdir(full):
            raise ToolError(f"{rel} is a folder")
        exists = os.path.exists(full)
        old = ws.read_text(full) if exists else None
        if name == "write_file":
            new = args["content"]
            if len(new) > MAX_WRITE:
                raise ToolError("content is too large")
            if old is not None and "\r\n" in old and "\r\n" not in new:
                new = new.replace("\n", "\r\n")  # keep the file's Windows line endings
        else:
            if old is None:
                raise ToolError(f"{rel} does not exist. Use write_file to create it.")
            o, n = args["old_text"], args["new_text"]
            if not o:
                raise ToolError("old_text is empty")
            if o not in old and "\r\n" in old:
                o, n = o.replace("\r\n", "\n").replace("\n", "\r\n"), n.replace("\r\n", "\n").replace("\n", "\r\n")
            count = old.count(o)
            if count == 0:
                raise ToolError(f"old_text was not found in {rel}. Read the file again and copy the text exactly.")
            if count > 1 and not args.get("replace_all"):
                raise ToolError(f"old_text occurs {count} times in {rel}. Include more surrounding lines "
                                "or set replace_all to true.")
            new = old.replace(o, n)
        if new == old:
            raise ToolError("This would not change the file")

        def write():
            now = ws.read_text(full) if os.path.exists(full) else None
            if now != old:
                raise ToolError(f"{rel} was changed by someone else meanwhile. Read it again.")
            os.makedirs(os.path.dirname(full), exist_ok=True)
            if not _inside(full, ws.root):  # a folder on the way was replaced by a symlink
                raise ToolError(f"{rel} is outside the project folder")
            with open(full, "w", encoding="utf-8", newline="") as f:
                f.write(new)
            lines = new.count("\n") + (0 if new.endswith("\n") or not new else 1)
            return f"{'Updated' if exists else 'Created'} {rel} ({lines} line{'' if lines == 1 else 's'})"

        return Action(write, "write", {"path": rel, "new_file": not exists, "diff": _diff(rel, old, new)})
    if name == "run_command":
        cmd = args["command"].strip()
        if not cmd:
            raise ToolError("command is empty")

        def run():
            code, out, note = run_command(cmd, ws.root, timeout, cancelled)
            status = note or f"Exit code: {code}"
            return f"{status}\n{_clip(out, MAX_RESULT - 200, keep_end=True)}".rstrip()

        return Action(run, "run", {"command": cmd})
    raise ToolError(f"Unknown tool {name}")


# backends -------------------------------------------------------------------------------------

def _openai_tools(tools):
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                              "parameters": t["parameters"]}} for t in tools]


def _parse_args(raw):
    """Tool arguments as a dict, or (None, error) when the model sent broken JSON."""
    if isinstance(raw, dict):
        return raw, None
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return {}, None
    try:
        val = json.loads(raw)
    except (TypeError, ValueError):
        return None, f"The tool arguments were not valid JSON: {str(raw)[:300]}"
    return (val, None) if isinstance(val, dict) else (None, "The tool arguments must be a JSON object")


def _metered(turn):
    """Count the tokens of the model request one `turn(self, meter)` generator makes (usage.py). The generator tells the
    meter about each streamed chunk and about the backend's token numbers; the record is stored when the turn ends."""
    def wrapper(self):
        meter, ok = usage.Meter(self.p, getattr(self, "model", None) or getattr(self, "payload", {}).get("model")), True
        try:
            return (yield from turn(self, meter))
        except Exception:
            ok = False
            raise
        finally:
            meter.finish(ok)
    wrapper.__name__ = turn.__name__
    return wrapper


class ClaudeTurns:
    """Claude tool use over the Messages API: the assistant content (thinking with signature,
    text, tool_use) goes back unchanged, results come back as tool_result blocks."""

    def __init__(self, p, model, messages, options, tools):
        self.p = p
        self.payload, self.headers = providers.anthropic_payload(p, model, messages)
        official = urllib.parse.urlparse(providers._base(p)).hostname == "api.anthropic.com"
        self.payload["tools"] = [dict({"name": t["name"], "description": t["description"],
                                       "input_schema": t["parameters"]},
                                      **({"eager_input_streaming": True} if official else {})) for t in tools]

    @_metered
    def turn(self, meter):
        resp = providers._request(providers._base(self.p) + "/v1/messages", self.payload, extra_headers=self.headers)
        blocks, partial, stop = {}, {}, None
        with resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                ev = json.loads(line[5:].strip())
                kind = ev.get("type")
                if kind == "content_block_start":
                    blocks[ev["index"]] = dict(ev.get("content_block") or {})
                elif kind == "content_block_delta":
                    d = ev.get("delta") or {}
                    dt = d.get("type")
                    b = blocks.setdefault(ev.get("index", 0), {"type": "thinking" if dt == "thinking_delta" else "text"})
                    if dt == "text_delta" and d.get("text"):
                        b["text"] = b.get("text", "") + d["text"]
                        meter.tick()
                        yield "text", d["text"]
                    elif dt == "thinking_delta" and d.get("thinking"):
                        b["thinking"] = b.get("thinking", "") + d["thinking"]
                        meter.tick()
                        yield "think", d["thinking"]
                    elif dt == "signature_delta":
                        b["signature"] = b.get("signature", "") + d.get("signature", "")
                    elif dt == "input_json_delta":
                        partial[ev.get("index", 0)] = partial.get(ev.get("index", 0), "") + d.get("partial_json", "")
                elif kind == "message_start":
                    usage.anthropic_usage(meter, (ev.get("message") or {}).get("usage"))
                elif kind == "message_delta":
                    usage.anthropic_usage(meter, ev.get("usage"))
                    stop = (ev.get("delta") or {}).get("stop_reason") or stop
                elif kind == "error":
                    err = ev.get("error") or {}
                    raise ProviderError(err.get("message") or "Claude API error")
                elif kind == "message_stop":
                    break
        if stop == "refusal":
            raise ProviderError("Claude declined to answer this request.")
        content, calls = [], []
        for idx in sorted(blocks):
            b = blocks[idx]
            if b.get("type") == "tool_use":
                args, err = _parse_args(partial.get(idx, ""))
                content.append({"type": "tool_use", "id": b["id"], "name": b["name"], "input": args or {}})
                calls.append({"id": b["id"], "name": b["name"], "args": args, "error": err})
            elif b.get("type") == "text":
                if b.get("text"):
                    content.append({"type": "text", "text": b["text"]})
            elif b.get("type") == "thinking":
                content.append({"type": "thinking", "thinking": b.get("thinking", ""), "signature": b.get("signature", "")})
            else:
                content.append(b)  # e.g. redacted_thinking: passed back as received
        if stop == "max_tokens" and calls:
            raise ProviderError("The answer hit the length limit in the middle of a tool call. Ask for smaller steps.")
        if content:
            self.payload["messages"].append({"role": "assistant", "content": content})
        return calls

    def add_results(self, results):
        self.payload["messages"].append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": r["id"], "content": r["content"], "is_error": r["is_error"]}
            for r in results]})


class OllamaTurns:
    """Ollama /api/chat with `tools`."""

    def __init__(self, p, model, messages, options, tools):
        self.p, self.model, self.options, self.tools = p, model, options or {}, tools
        self.msgs = [dict(m) for m in messages]

    @_metered
    def turn(self, meter):
        payload = {"model": self.model, "messages": self.msgs, "stream": True, "tools": _openai_tools(self.tools)}
        if "temperature" in self.options:
            payload["options"] = {"temperature": self.options["temperature"]}
        try:
            resp = providers._request(providers._base(self.p) + "/api/chat", payload, self.p.get("api_key", ""))
        except ProviderError as e:
            if "does not support tools" in str(e).lower():
                raise ToolsUnsupported from None
            raise
        text, raw_calls = [], []
        with resp:
            for line in resp:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if obj.get("error"):
                    raise ProviderError(obj["error"])
                msg = obj.get("message") or {}
                if msg.get("thinking"):
                    meter.tick()
                    yield "think", msg["thinking"]
                if msg.get("content"):
                    text.append(msg["content"])
                    meter.tick()
                    yield "text", msg["content"]
                raw_calls += [c for c in msg.get("tool_calls") or [] if isinstance(c, dict)]
                if obj.get("done"):
                    usage.ollama_usage(meter, obj)
                    break
        out = {"role": "assistant", "content": "".join(text)}
        if raw_calls:
            out["tool_calls"] = raw_calls
        self.msgs.append(out)
        calls = []
        for i, c in enumerate(raw_calls):
            fn = c.get("function") or {}
            args, err = _parse_args(fn.get("arguments"))
            calls.append({"id": str(i), "name": str(fn.get("name") or ""), "args": args, "error": err})
        return calls

    def add_results(self, results):
        for r in results:
            self.msgs.append({"role": "tool", "content": r["content"], "tool_name": r["name"]})


class OpenAITurns:
    """OpenAI-compatible /chat/completions with `tools`; tool calls arrive in pieces per index."""

    def __init__(self, p, model, messages, options, tools):
        self.p, self.model, self.options, self.tools = p, model, options or {}, tools
        self.msgs = [dict(m) for m in messages]

    @_metered
    def turn(self, meter):
        payload = {"model": self.model, "messages": self.msgs, "stream": True, "tools": _openai_tools(self.tools)}
        if "temperature" in self.options:
            payload["temperature"] = self.options["temperature"]
        try:
            resp = providers.open_openai_stream(self.p, "/chat/completions", payload)
        except ProviderError as e:
            msg = str(e).lower()
            if msg.startswith(("http 400", "http 404", "http 422", "http 501")) and ("tool" in msg or "function" in msg):
                raise ToolsUnsupported from None
            raise
        text, parts = [], {}
        with resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                obj = json.loads(data)
                if obj.get("error"):
                    err = obj["error"]
                    raise ProviderError(err.get("message", str(err)) if isinstance(err, dict) else str(err))
                usage.openai_usage(meter, obj.get("usage"))
                for choice in obj.get("choices", []):
                    delta = choice.get("delta") or {}
                    think = delta.get("reasoning_content") or delta.get("reasoning")
                    if think:
                        meter.tick()
                        yield "think", think
                    if delta.get("content"):
                        text.append(delta["content"])
                        meter.tick()
                        yield "text", delta["content"]
                    for tc in delta.get("tool_calls") or []:
                        cur = parts.setdefault(tc.get("index", len(parts)), {"id": "", "name": "", "arguments": ""})
                        fn = tc.get("function") or {}
                        cur["id"] = tc.get("id") or cur["id"]
                        cur["name"] += fn.get("name") or ""
                        args = fn.get("arguments")
                        cur["arguments"] += json.dumps(args) if isinstance(args, dict) else (args or "")
        ordered = [parts[k] for k in sorted(parts)]
        for i, c in enumerate(ordered):
            c["id"] = c["id"] or f"call_{i}"
        out = {"role": "assistant", "content": "".join(text) or None}
        if ordered:
            out["tool_calls"] = [{"id": c["id"], "type": "function",
                                  "function": {"name": c["name"], "arguments": c["arguments"] or "{}"}} for c in ordered]
        elif out["content"] is None:
            out["content"] = ""
        self.msgs.append(out)
        calls = []
        for c in ordered:
            args, err = _parse_args(c["arguments"])
            calls.append({"id": c["id"], "name": c["name"], "args": args, "error": err})
        return calls

    def add_results(self, results):
        for r in results:
            self.msgs.append({"role": "tool", "tool_call_id": r["id"], "content": r["content"]})


TEXT_PROTOCOL = """You can use tools. To call one, write a block exactly like this and then stop writing:
```tool
{"tool": "read_file", "args": {"path": "README.md"}}
```
Use only one tool block per message. The result arrives in the next message. When you need no more tools, answer normally.

Tools:
"""
MARK = "```tool"


def _find_call(text):
    """Find a complete ```tool block. Returns (start, end, call) or None while it is incomplete."""
    i = text.find(MARK)
    if i < 0:
        return None
    j = i + len(MARK)
    while j < len(text) and text[j] in " \t\r\n":
        j += 1
    try:
        obj, end = json.JSONDecoder().raw_decode(text, j)
    except ValueError:
        return None
    rest = text[end:]
    stripped = rest.lstrip()
    if stripped.startswith("```"):
        end += len(rest) - len(stripped) + 3
    return i, end, obj


class TextTurns:
    """Fallback for models without tool calling: the model writes ```tool blocks into its text.
    The block is not shown as text; it appears as a step instead."""

    def __init__(self, p, model, messages, options, tools):
        self.p, self.model, self.options = p, model, options
        lines = []
        for t in tools:
            props = t["parameters"].get("properties") or {}
            req = t["parameters"].get("required") or []
            sig = ", ".join(k + ("" if k in req else "?") for k in props)
            lines.append(f"- {t['name']}({sig}): {t['description']}")
        proto = TEXT_PROTOCOL + "\n".join(lines)
        self.msgs = [dict(m) for m in messages]
        if self.msgs and self.msgs[0]["role"] == "system":
            self.msgs[0]["content"] += "\n\n" + proto
        else:
            self.msgs.insert(0, {"role": "system", "content": proto})

    def turn(self):
        gen = providers.chat_stream(self.p, self.model, self.msgs, self.options)
        buf, sent, found = "", 0, None
        try:
            for kind, c in gen:
                if kind != "text":
                    yield kind, c
                    continue
                buf += c
                found = _find_call(buf)
                if found:
                    break
                # hold back the start of a possible ```tool block until it is clear
                safe = buf.find(MARK)
                if safe < 0:
                    safe = len(buf)
                    for k in range(min(len(MARK) - 1, len(buf)), 0, -1):
                        if MARK.startswith(buf[-k:]):
                            safe = len(buf) - k
                            break
                if safe > sent:
                    yield "text", buf[sent:safe]
                    sent = safe
        finally:
            gen.close()
        calls = []
        if found:
            start, _, obj = found
            name = obj.get("tool") or obj.get("name") if isinstance(obj, dict) else None
            args = obj.get("args", obj.get("arguments", {})) if isinstance(obj, dict) else None
            args, err = _parse_args(args)
            calls.append({"id": "0", "name": str(name or ""), "args": args,
                          "error": err or (None if name else 'A tool block needs "tool" and "args"')})
            shown = buf[:start]
        else:
            shown = buf
            if MARK in buf:  # a tool block that never became valid JSON
                calls.append({"id": "0", "name": "", "args": None,
                              "error": "Could not read the tool block. Write valid JSON like the example."})
        if len(shown) > sent:
            yield "text", shown[sent:]
        self.msgs.append({"role": "assistant", "content": buf[:found[1]] if found else buf})
        return calls

    def add_results(self, results):
        self.msgs.append({"role": "user", "content": "\n\n".join(
            f"[Result of {r['name'] or 'tool'}{' (error)' if r['is_error'] else ''}]\n{r['content']}" for r in results)})


TURNS = {"anthropic": ClaudeTurns, "ollama": OllamaTurns, "openai": OpenAITurns}


# the agent loop -------------------------------------------------------------------------------

def system_prompt(root, timeout):
    if not root:
        return ("You can use tools of the user's connected MCP servers (a tool's name starts with its server). "
                "Every tool call needs the user's approval. If the user denies a call, do not try the same thing "
                "another way; explain or ask instead. Never print secrets such as API keys.")
    shell = "cmd.exe" if os.name == "nt" else "sh"
    return (
        f"You are working as a coding agent in the project folder \"{os.path.basename(root)}\" on "
        f"{platform.system() or sys.platform}. All paths are relative to that folder; you cannot access anything "
        "outside it. Look at the relevant files before you change them, prefer edit_file for small changes, "
        "and check your work (for example by running the tests) when that is useful. "
        f"Commands run with {shell} in the project folder, without input, and stop after {timeout} seconds. "
        "Writing files and running commands need the user's approval. If the user denies an action, do not try "
        "the same thing another way; explain or ask instead. Never print secrets such as API keys. "
        "When you are done, briefly tell the user what you changed.")


MCP_NOTE = ("Tools whose name starts with an MCP server's name come from the user's connected MCP servers; "
            "each of their calls needs the user's approval.")


def new_run_id():
    return secrets.token_hex(8)


class AgentRun:
    """One agent answer: alternate model turns and tool calls until the model stops calling tools.

    `emit(event)` sends NDJSON events to the browser: think/text chunks, step (a tool call starts),
    confirm (waiting for the user), step_done, notice, ping. `parts` collects text and steps in order
    for storing the answer."""

    def __init__(self, prov, model, messages, folder, emit, options=None, allowed=None, timeout=120,
                 max_steps=30, mcp_tools=None, run_id=None):
        """`folder` may be empty when only MCP tools are used; `mcp_tools` is [(exposed name, server, tool)]."""
        self.id = run_id or new_run_id()
        self.prov, self.model, self.emit = prov, model, emit
        self.ws = Workspace(folder) if folder else None
        self.mcp = {name: (srv, tool) for name, srv, tool in mcp_tools or []}
        self.tools = (TOOLS if self.ws else []) + [
            {"name": name, "description": str(tool.get("description") or tool.get("title") or tool["name"])[:1024],
             "parameters": mcp.schema(tool)} for name, (srv, tool) in self.mcp.items()]
        self.options = options or {}
        self.allowed = allowed if allowed is not None else set()
        self.timeout, self.max_steps = timeout, max_steps
        self.cancelled = threading.Event()
        self.pending = {}
        self.parts = []
        self.texts = []
        self._steps = 0
        msgs = [dict(m) for m in messages]
        extra = system_prompt(folder, timeout)
        if folder and self.mcp:
            extra += " " + MCP_NOTE
        if msgs and msgs[0]["role"] == "system":
            msgs[0]["content"] += "\n\n" + extra
        else:
            msgs.insert(0, {"role": "system", "content": extra})
        self.messages = msgs

    # called from other request threads
    def cancel(self):
        self.cancelled.set()
        for h in list(self.pending.values()):
            h["event"].set()

    def decide(self, step_id, decision):
        h = self.pending.get(step_id)
        if not h:
            return False
        h["decision"] = decision
        h["event"].set()
        return True

    def text(self):
        """The whole answer as stored in the chat (reasoning in <think> tags)."""
        return "\n\n".join(t for t in self.texts if t.strip())

    # the loop
    def run(self):
        ptype = self.prov["type"]
        turns = TURNS.get(ptype, TextTurns)(self.prov, self.model, self.messages, self.options, self.tools)
        first = True
        for _ in range(self.max_steps):
            try:
                calls = self._turn(turns)
            except ToolsUnsupported:
                if not first:
                    raise ProviderError("The model stopped accepting tool calls.") from None
                self.emit({"type": "notice", "t": "This model has no tool calling. Sunak uses a simple text "
                                                  "protocol instead; small models may get it wrong."})
                turns = TextTurns(self.prov, self.model, self.messages, self.options, self.tools)
                calls = self._turn(turns)
            first = False
            if not calls:
                return
            turns.add_results([self._step(c) for c in calls])
        self.emit({"type": "notice", "t": f"Stopped after {self.max_steps} steps. Send a message to let the agent continue."})

    def _turn(self, turns):
        """One model call of the loop. It waits its turn when the backend is busy with other requests; the
        place in the queue is shown to the user. Waiting for the user's confirmation does not hold a place."""
        try:
            with jobqueue.slot(providers.queue_key(turns.p), providers.queue_slots(turns.p),
                               notify=lambda place: self.emit({"type": "queued", "position": place}),
                               cancelled=self.cancelled.is_set):
                return self._turn_inner(turns)
        except jobqueue.Cancelled:
            raise Cancelled from None
        except jobqueue.Timeout:
            raise ProviderError("The model was busy with other requests for too long. Please try again.") from None

    def _turn_inner(self, turns):
        from .server import stream_to_text
        chunks = []
        gen = turns.turn()
        try:
            while True:
                if self.cancelled.is_set():
                    raise Cancelled
                try:
                    kind, c = next(gen)
                except StopIteration as stop:
                    return stop.value or []
                chunks.append((kind, c))
                self.emit({"type": kind, "t": c})
        except (http.client.HTTPException, OSError, ValueError) as e:
            if isinstance(e, (BrokenPipeError, ConnectionResetError)):
                raise
            raise ProviderError(f"The connection to the model broke off ({type(e).__name__}: {e})") from None
        finally:
            gen.close()
            text = stream_to_text(chunks)
            if text.strip():
                self.texts.append(text)
                self.parts.append({"text": text})

    def _step(self, call):
        self._steps += 1
        sid = f"s{self._steps}"
        name, args = call["name"], call["args"]
        title = f"{self.mcp[name][0].name} · {self.mcp[name][1]['name']}" if name in self.mcp else describe(name, args)
        step = {"id": sid, "tool": name, "title": title, "status": "running"}
        self.parts.append({"step": step})
        self.emit({"type": "step", **step})
        try:
            if call.get("error"):
                raise ToolError(call["error"])
            if name in self.mcp:
                action = self._mcp_action(name, args)
            elif self.ws is None:
                raise ToolError(f"Unknown tool {name}. Available tools: {', '.join(sorted(self.mcp))}")
            else:
                action = prepare(self.ws, name, args, self.timeout, self.cancelled)
            step.update({k: (_clip(v, UI_DIFF) if k == "diff" else v) for k, v in action.preview.items()})
            if action.kind and not self._approved(sid, action, step):
                step["status"] = "denied"
                result = ("The user denied this action. Do not try to do the same in another way; "
                          "continue without it or ask the user.")
            else:
                result = action.run()
                step["status"] = "done"
        except ToolError as e:
            step["status"] = "error"
            result = f"Error: {e}"
        except OSError as e:
            step["status"] = "error"
            result = f"Error: {type(e).__name__}: {e.strerror or e}"
        except Cancelled:
            step["status"] = "stopped"
            raise
        result = _clip(result, MAX_RESULT)
        step["output"] = _clip(result, UI_OUTPUT, keep_end=True)
        self.emit({"type": "step_done", **step})
        return {"id": call["id"], "name": name, "content": result, "is_error": step["status"] != "done"}

    def _mcp_action(self, name, args):
        """An MCP tool call; it always needs approval (kind "tool:<name>", allowed per tool)."""
        srv, tool = self.mcp[name]
        if not isinstance(args, dict):
            raise ToolError("Tool arguments must be a JSON object")
        missing = [k for k in mcp.schema(tool).get("required") or [] if k not in args]
        if missing:
            raise ToolError(f"{tool['name']} needs the argument {', '.join(map(str, missing))}")

        def run():
            try:
                text, is_error = srv.call(tool["name"], args, self.cancelled)
            except mcp.MCPError as e:
                if self.cancelled.is_set():
                    raise Cancelled from None
                raise ToolError(str(e)) from None
            if is_error:
                raise ToolError(text)
            return text

        shown = json.dumps(args, indent=2, ensure_ascii=False)
        return Action(run, f"tool:{name}", {"server": srv.name, "mcp_tool": tool["name"], "input": _clip(shown, UI_DIFF)})

    def _approved(self, sid, action, step):
        if action.kind in self.allowed:
            return True
        holder = {"event": threading.Event(), "decision": None}
        self.pending[sid] = holder
        try:
            self.emit({"type": "confirm", **step, "kind": action.kind})
            deadline = time.monotonic() + CONFIRM_TIMEOUT
            while not holder["event"].wait(PING_EVERY):
                if time.monotonic() > deadline:
                    break
                self.emit({"type": "ping"})
        finally:
            self.pending.pop(sid, None)
        if self.cancelled.is_set():
            raise Cancelled
        if holder["decision"] == "always":
            self.allowed.add(action.kind)
        return holder["decision"] in ("allow", "always")


class Registry:
    """Running agent answers (for confirm and cancel) and the per-chat "allow for this chat" choices.
    The choices live in memory only, so they end when Sunak restarts."""

    def __init__(self):
        self.runs = {}
        self._allowed = {}
        self._lock = threading.Lock()

    def allowed(self, session_id, folder):
        """The kinds allowed for this chat and folder ("" when only MCP tools are used)."""
        with self._lock:
            return self._allowed.setdefault((session_id, _norm(folder) if folder else ""), set())

    def revoke(self, session_id):
        with self._lock:
            for key in [k for k in self._allowed if k[0] == session_id]:
                del self._allowed[key]

    def add(self, run):
        self.runs[run.id] = run

    def remove(self, run):
        self.runs.pop(run.id, None)

    def get(self, run_id):
        return self.runs.get(run_id)
