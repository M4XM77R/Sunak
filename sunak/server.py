"""HTTP server and JSON API. Python standard library only."""

import base64
import binascii
import contextlib
import datetime
import hashlib
import hmac
import ipaddress
import json
import logging
import mimetypes
import os
import platform
import queue
import re
import secrets
import shutil
import socket
import socketserver
import random
import sqlite3
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from . import (__version__, backup, cal, extract, gpu, imagegen, images, intent, jobqueue, knowledge, log, mail, mcp, memory, modelsearch,
               ollama, providers, qr, reminders, reports, research, sdcpp, speech, toolrun, updates, usage)
from .db import DB, new_id

log_http = log.get("http")
log_app = log.get("app")
log_image = log.get("image")
log_assist = log.get("assistant")

STATIC = Path(__file__).parent / "static"
ATTACHED_RE = re.compile(r"File `([^`\n]+)`:\n```\n.*?\n```\s*", re.S)  # files attached in the chat
MAX_BODY = 24 * 1024 * 1024  # a 15 MB upload is 20 MB as base64

DEFAULT_SETTINGS = {
    "default_model": "",
    "system_prompt": "You are Sunak, a helpful, honest and concise assistant. Use Markdown when it helps.",
    "temperature": 0.7,
    "use_memory": True,
    "auto_memory": True,     # Sunak picks up lasting facts about the user from chats by itself (memory.py)
    "accent": "",       # "" = the theme's own accent color
    "theme": "dark",
    "language": "",     # "" = the browser's language; else one of LANGUAGES
    "check_updates": True,
    "speech_input": "local", # 🎤: "local" (Whisper server or the browser's on-device recognition), "browser", "off"
    "whisper_url": "",       # local Whisper server for speech input, see speech.py
    "whisper_model": "",     # model name for OpenAI-compatible Whisper servers ("" = whisper-1)
    "image_gen": "off",      # 🎨 image generation: "off", "local" (sdcpp.py), "automatic1111" or "comfyui" (imagegen.py)
    "image_gen_url": "",     # address of that program ("" = its usual local address)
    "image_gen_model": "",   # checkpoint ("" = the program's current one / ComfyUI's first)
    "image_gen_size": 512,   # side of a square picture: 512 (SD 1.5), 768, 1024 (SDXL, Flux)
    "image_gen_steps": 25,
    "ai_image_detect": True, # ask the chat model whether a message wants a picture, when pictures are set up (intent.py)
    "error_reports": "off",  # unexpected errors as GitHub issues (reports.py): "off", "ask" (the user sends each one), "auto"
    "mail_notify": True,     # 📬 look for new mail every few minutes while Sunak is open, and say so
    "reminders": False,      # 🔔 calendar reminders (reminders.py): pages show them, ntfy sends them as push messages
    "ntfy_url": "",          # ntfy server for the push messages ("" = https://ntfy.sh); of the installation, only admins set it
    "ntfy_topic": "",        # the topic the phone subscribes to ("" = no push messages); it is the only secret of a public topic
    "reminder_lang": "en",   # language of the push messages: the interface language the settings were last saved in
}
INT_PREFS = {"image_gen_size": (512, 1024),
             "image_gen_steps": (1, imagegen.MAX_STEPS)}  # allowed ranges
# Settings of the whole installation (only admin profiles change them); all other prefs are per profile.
GLOBAL_PREFS = {"check_updates", "speech_input", "whisper_url", "whisper_model",
                "image_gen", "image_gen_url", "image_gen_model", "image_gen_size", "image_gen_steps", "error_reports", "ai_image_detect",
                "ntfy_url"}
GLOBAL_KEYS = GLOBAL_PREFS | {"providers", "mcp_servers", "password"}
MAX_PROFILES = 20

# Themes: [data-theme] blocks in static/app.css, THEMES in static/app.js.
THEMES = ("dark", "light", "retro", "cyberpunk", "ocean", "forest", "sunset", "corporate")
# Interface languages: English plus a static/lang-<code>.js file for each other one.
LANGUAGES = ("en", "de")

# Built-in personas; the user can edit, add and delete them in Settings → Personas.
DEFAULT_PERSONAS = [
    {"id": "assistant", "icon": "", "name": "Assistant", "prompt": ""},
    {"id": "coder", "icon": "", "name": "Coder",
     "prompt": "You are an expert software engineer. Give working, idiomatic code with short explanations. "
               "Point out bugs and edge cases. Ask for the language or framework only if it really matters."},
    {"id": "writer", "icon": "", "name": "Writer",
     "prompt": "You are a skilled writer and editor. Write clear, natural, engaging text in the user's language "
               "and tone. When editing, keep the meaning and explain bigger changes briefly."},
    {"id": "translator", "icon": "", "name": "Translator",
     "prompt": "You are a professional translator. Translate the user's text faithfully and idiomatically. "
               "If no target language is given, translate German to English and any other language to German. "
               "Reply with the translation only, unless asked for notes."},
    {"id": "teacher", "icon": "", "name": "Teacher",
     "prompt": "You are a patient teacher. Explain step by step with simple words and examples, check "
               "understanding with a short question at the end, and never make the user feel bad for asking."},
]

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


def recommend(ram, gpu_info=None):
    """Pick a starter model that fits into `ram` GB of memory, or a bigger one when it fits
    completely into the GPU's memory (then it is fast)."""
    pick = next((i for i, (limit, _, _) in enumerate(RECOMMENDATIONS) if ram is None or ram < limit),
                len(RECOMMENDATIONS) - 1)
    vram = (gpu_info or {}).get("vram_gb") if (gpu_info or {}).get("usable") else None
    for i, (_, model, size) in enumerate(RECOMMENDATIONS):
        if i > pick and ollama.fits_gpu(float(size.split()[0]), vram):
            pick = i
    _, model, size = RECOMMENDATIONS[pick]
    return {"model": model, "size": size}


def _check_pref(key, value, default):
    """Validate one preference against the type of its default. Raises ValueError."""
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false")
        return value
    if isinstance(default, int):
        lo, hi = INT_PREFS[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi or value != int(value):
            raise ValueError(f"{key} must be a whole number between {lo} and {hi}")
        if key == "image_gen_size" and value not in imagegen.SIZES:
            raise ValueError("image_gen_size must be one of: " + ", ".join(map(str, imagegen.SIZES)))
        return int(value)
    if isinstance(default, float):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 2:
            raise ValueError(f"{key} must be a number between 0 and 2")
        return float(value)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be text")
    if key == "speech_input" and value not in speech.MODES:
        raise ValueError("speech_input must be one of: " + ", ".join(speech.MODES))
    if key in ("whisper_url", "whisper_model"):
        value = value.strip()
    if key == "whisper_url" and value:
        speech.endpoint(value)
    if key == "error_reports" and value not in ("off", "ask", "auto"):
        raise ValueError("error_reports must be one of: off, ask, auto")
    if key == "image_gen" and value not in ("off", "local", *imagegen.BACKENDS):
        raise ValueError("image_gen must be one of: off, local, " + ", ".join(imagegen.BACKENDS))
    if key == "reminder_lang" and value not in LANGUAGES:
        raise ValueError("reminder_lang must be one of: " + ", ".join(LANGUAGES))
    if key in ("ntfy_url", "ntfy_topic"):
        value = value.strip()[:300]
    if key == "ntfy_url" and value and not re.match(r"https?://[^\s/]+", value):
        raise ValueError("The ntfy address must start with http:// or https://")
    if key == "ntfy_topic" and value and not reminders.TOPIC_RE.fullmatch(value):
        raise ValueError("The ntfy topic may only contain letters, digits, - and _ (up to 64 characters)")
    if key in ("image_gen_url", "image_gen_model"):
        value = value.strip()[:300]
    if key == "image_gen_url" and value and not re.match(r"https?://[^\s/]+", value):
        raise ValueError("The image generator address must start with http:// or https://")
    if key == "whisper_model" and len(value) > 200:
        raise ValueError("whisper_model is too long")
    if key == "language" and value and value not in LANGUAGES:
        raise ValueError("Unknown language. Choose one of: " + ", ".join(LANGUAGES))
    if key == "theme" and value not in THEMES:
        raise ValueError("Unknown theme. Choose one of: " + ", ".join(THEMES))
    if key == "accent" and value and not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError("accent must be a color like #ff4fa3, or empty for the theme's color")
    return value


def lan_ip():
    """This computer's address in the local network (the one it uses for outgoing traffic), or None."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.254.254.254", 1))  # UDP connect sends nothing, it only picks the route
            ip = s.getsockname()[0]
    except OSError:
        return None
    return None if ip.startswith("127.") or ip == "0.0.0.0" else ip


class Server(ThreadingHTTPServer):
    """ThreadingHTTPServer without the reverse DNS lookup of the address when it starts (HTTPServer looks
    up a name for it, which can take many seconds for a network address, e.g. on macOS)."""
    daemon_threads = True

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


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
    """Application state shared by all requests: database, settings, model resolution, auth and prompt building.

    Profiles: `main` is the database of the installation (global settings, and the data of the main
    profile); `db` and `user_dir` belong to the profile a request is made for (see ProfileView)."""
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = self.main = DB(str(self.data_dir / "sunak.db"))
        self.root, self.profile, self.user_dir = self, "default", self.data_dir
        self._profile_dbs, self._profiles_lock = {}, threading.Lock()
        if not self.main.get_setting("secret"):
            self.main.set_setting("secret", secrets.token_hex(32))
        env_pw = os.environ.get("SUNAK_PASSWORD")
        stored = self.main.get_setting("password_hash")
        if env_pw and not (stored and check_password(env_pw, stored)):  # same password: keep logins valid
            self.main.set_setting("password_hash", hash_password(env_pw))
        self.ram = total_ram_gb()
        self.gpu = None  # gpu.summary(), filled in the background (nvidia-smi can take a moment)
        threading.Thread(target=self._detect_gpu, daemon=True).start()
        self.instance = secrets.token_hex(8)  # changes with every start, so the page sees a restart
        self.update = {"behind": None, "checked": 0.0, "version": "", "changelog": []}
        self._update_lock = threading.Lock()
        self._checking = False
        self.tool_runs = toolrun.Registry()
        self.reminders = reminders.Reminders(self)  # started by __main__ (tests do not run it)
        self.reports = reports.Reports(self)
        if self.reports.token():
            log.add_secret(self.reports.token())
        self.mcp = mcp.Manager()  # MCP servers start when a chat first needs their tools
        self.mcp.configure(self.mcp_servers())
        self.host, self.port, self.handler = None, None, None  # set by make_server
        self.lan, self.lan_error = None, ""  # second server on the network address (phone access)
        self._lan_lock = threading.Lock()

    def _detect_gpu(self):
        try:
            self.gpu = gpu.summary(gpu.detect())
        except Exception:  # noqa: BLE001 - no GPU info is fine, the app works without it
            log_app.warning("Graphics card detection failed", exc_info=True)

    # updates ----------------------------------------------------------
    def check_updates(self):
        """Look for new commits in the background, at most every CHECK_EVERY seconds, when enabled."""
        if not self.settings()["check_updates"]:
            return
        with self._update_lock:
            if self._checking or time.time() - self.update["checked"] < updates.CHECK_EVERY:
                return
            self._checking = True

        def run():
            try:
                r = updates.inspect()
                behind = r["behind"]
                checked = time.time() if behind is not None else time.time() - updates.CHECK_EVERY + updates.RETRY_AFTER
                self.update = {"behind": behind, "checked": checked, "version": r["version"], "changelog": r["changelog"]}
                if behind:
                    log_app.info("Update check: %d new change%s available", behind, "" if behind == 1 else "s")
                else:
                    log_app.debug("Update check: %s", "up to date" if behind == 0 else "not possible (offline or no git clone)")
            finally:
                self._checking = False
        threading.Thread(target=run, daemon=True).start()

    def check_updates_now(self):
        """The "Check for updates" button: look right now (whatever the hint setting says) and say why when
        it did not work. Uses the same check as the background hint and refreshes its result."""
        with self._update_lock:
            if self._checking:
                raise ValueError("A check is already running. Try again in a moment.")
            self._checking = True
        try:
            r = updates.inspect()
        finally:
            self._checking = False
        checked = time.time() if r["behind"] is not None else time.time() - updates.CHECK_EVERY + updates.RETRY_AFTER
        self.update = {"behind": r["behind"], "checked": checked, "version": r["version"], "changelog": r["changelog"]}
        log_app.info("Update check (button): %s", "failed (%s)" % r["error"] if r["behind"] is None else
                     "%d new change%s, remote version %s" % (r["behind"], "" if r["behind"] == 1 else "s", r["version"] or "unknown") if r["behind"] else "up to date")
        return {"behind": r["behind"] or 0, "available": bool(r["behind"]), "known": r["behind"] is not None,
                "version": r["version"], "current": __version__, "error": r["error"], "changelog": r["changelog"],
                "can_update": updates.update_command() is not None}

    def update_info(self):
        """State for the "Update available" hint, plus the outcome of the last update (shown once)."""
        enabled = self.settings()["check_updates"]
        self.check_updates()
        behind = (self.update["behind"] or 0) if enabled else 0
        return {"enabled": enabled, "available": behind > 0, "behind": behind, "version": self.update["version"] if behind else "",
                "current": __version__, "changelog": self.update["changelog"] if behind else [],
                "can_update": updates.update_command() is not None, "result": updates.pop_result(self.data_dir)}

    # settings ---------------------------------------------------------
    def settings(self):
        """Preferences merged over DEFAULT_SETTINGS (GLOBAL_PREFS of the installation, the others of this
        profile), plus the provider list and this profile's personas."""
        s = dict(DEFAULT_SETTINGS)
        main_prefs = self.main.get_setting("prefs", {})
        own = main_prefs if self.db is self.main else self.db.get_setting("prefs", {})
        s.update({k: v for k, v in main_prefs.items() if k in GLOBAL_PREFS})
        s.update({k: v for k, v in own.items() if k not in GLOBAL_PREFS and k in DEFAULT_SETTINGS})  # old keys are ignored
        stored = self.main.get_setting("providers")
        s["providers"] = providers.default_providers() if stored is None else stored  # [] = all removed
        personas = self.db.get_setting("personas")
        s["personas"] = DEFAULT_PERSONAS if personas is None else personas
        return s

    def ask_intent(self, model_id, text, timeout=15.0):
        """Ask the chat model whether `text` is a request for a picture: True, False, or None when it cannot say (no model,
        it is busy with other requests, an error, or no answer within `timeout` seconds). Only the first words of the
        answer are read, so the model is stopped right away."""
        try:
            prov, model = self.resolve(model_id)
        except (providers.ProviderError, ValueError):
            return None
        running, waiting = jobqueue.snapshot().get(providers.queue_key(prov), (0, 0))
        if waiting or running >= providers.queue_slots(prov):
            log_image.debug("The chat model is busy, picture requests are told by the rules this time")
            return None
        result, done = [], threading.Event()

        def run():
            answer = ""
            try:
                with contextlib.closing(providers.chat_stream(prov, model, intent.messages(text), {"temperature": 0})) as chunks:
                    for kind, chunk in chunks:
                        if kind == "text":
                            answer += chunk
                            if len(answer.strip()) >= 3:
                                break
                result.append(intent.parse(answer))
            except (providers.ProviderError, OSError, ValueError) as e:
                log_image.info("Picture request check by the chat model failed (%s), the rules decide", str(e)[:150])
            finally:
                done.set()
        usage.thread(run).start()
        if not done.wait(timeout):
            log_image.info("Picture request check by the chat model took longer than %.0fs, the rules decide", timeout)
            return None
        return result[0] if result else None

    def mcp_servers(self):
        """The MCP servers with their secrets (environment values, tokens); never send these to the browser."""
        return self.main.get_setting("mcp_servers") or []

    def save_settings(self, data):
        """Validate everything in `data` (prefs, providers, personas, password), then store it.
        Nothing is saved when any part is invalid."""
        if not isinstance(data, dict):
            raise ValueError("Settings must be a JSON object")
        main_prefs = self.main.get_setting("prefs", {})
        own = main_prefs if self.db is self.main else self.db.get_setting("prefs", {})
        for k, default in DEFAULT_SETTINGS.items():
            if k in data:
                (main_prefs if k in GLOBAL_PREFS else own)[k] = _check_pref(k, data[k], default)
        new_providers = self._clean_providers(data["providers"]) if "providers" in data else None
        new_personas = self._clean_personas(data["personas"]) if "personas" in data else None
        new_mcp = mcp.clean(data["mcp_servers"], self.mcp_servers()) if "mcp_servers" in data else None
        if "password" in data and not isinstance(data["password"], (str, type(None))):
            raise ValueError("Password must be text")
        self.main.set_setting("prefs", main_prefs)
        if own is not main_prefs:
            self.db.set_setting("prefs", own)
        if new_providers is not None:
            self.main.set_setting("providers", new_providers)
        if new_personas is not None:
            self.db.set_setting("personas", new_personas)
        if new_mcp is not None:
            self.main.set_setting("mcp_servers", new_mcp)
            self.mcp.configure(new_mcp)
        if "password" in data:
            pw = data["password"] or ""
            self.main.set_setting("password_hash", hash_password(pw) if pw else "")
            if not pw and self.lan is not None:  # never reachable from the network without a password
                self.stop_lan()
        return self.settings()

    # backup import (backup.py) -------------------------------------------
    def import_backup(self, data, admin):
        """Add a backup, or one exported chat, to this profile and return the report (backup.new_report). Nothing that
        exists is overwritten; a setting is taken over only when this profile has not set it yet. Settings of the whole
        installation and providers only come in when `admin`. Raises ValueError when `data` is no backup."""
        report = backup.new_report()
        if backup.classify(data, report) == "backup":
            backup.restore_content(self.db, data, report)
            mail_ids = self._import_mail(data.get("mail_accounts", []), report)
            self._import_calendars(data.get("calendars", []), mail_ids, report)
            self._import_settings(data.get("settings", {}), admin, report)
            self.reminders.invalidate(self.profile)
        else:
            backup.restore_content(self.db, data, report)
        return report

    def _import_settings(self, s, admin, report):
        main_prefs = self.main.get_setting("prefs", {})
        own = main_prefs if self.db is self.main else self.db.get_setting("prefs", {})
        left_out, current = False, self.settings()
        for k, v in s.items():
            if k not in DEFAULT_SETTINGS or k == "ntfy_topic":  # the topic works like a password and is never in a backup
                continue
            target = main_prefs if k in GLOBAL_PREFS else own
            if k in GLOBAL_PREFS and not admin:
                left_out = True
                continue
            try:
                value = _check_pref(k, v, DEFAULT_SETTINGS[k])
            except (ValueError, KeyError):
                report["invalid"] += 1
                continue
            if value == current[k]:
                continue  # nothing to take over (a backup lists every setting, also those never changed)
            if k in target:
                report["skipped"]["settings"] += 1
            else:
                target[k] = value
                report["added"]["settings"] += 1
        if admin:
            self.main.set_setting("prefs", main_prefs)
        if own is not main_prefs:
            self.db.set_setting("prefs", own)
        have = self.settings()["personas"]
        added = False
        for p in s.get("personas", []) if isinstance(s.get("personas"), list) else []:
            try:
                new = self._clean_personas([p])[0]
            except ValueError:
                report["invalid"] += 1
                continue
            if new["id"] in {x["id"] for x in have} or new["name"].casefold() in {x["name"].casefold() for x in have}:
                report["skipped"]["personas"] += 1
                continue
            have = have + [new]
            report["added"]["personas"] += 1
            added = True
        if added:
            self.db.set_setting("personas", have)
        if isinstance(s.get("providers"), list) and s["providers"]:
            if admin:
                self._import_providers(s["providers"], report)
            else:
                left_out = True
        if left_out:
            report["notes"].append("Settings of the whole installation and the model providers were left out: "
                                   "only an admin profile can import them.")

    def _import_providers(self, items, report):
        stored = self.main.get_setting("providers")
        have = providers.default_providers() if stored is None else stored
        added = False
        for p in items:
            if not isinstance(p, dict):
                report["invalid"] += 1
                continue
            url = str(p.get("base_url") or "").strip().rstrip("/").lower()
            if any(h["id"] == p.get("id") or (h["type"] == p.get("type") and h["base_url"].rstrip("/").lower() == url) for h in have):
                report["skipped"]["providers"] += 1
                continue
            try:
                have = self._clean_providers(have + [dict(p, api_key="")])
            except ValueError:
                report["invalid"] += 1
                continue
            report["added"]["providers"] += 1
            added = True
            if have[-1]["type"] != "ollama":
                report["secrets"].append({"kind": "provider", "name": have[-1]["name"]})
        if added:
            self.main.set_setting("providers", have)

    def _import_mail(self, items, report):
        """Link the backup's mail accounts that are not linked yet (without passwords). Returns {id in the backup: id here}."""
        accounts, ids, changed = self.mail_accounts(), {}, False
        for raw in items:
            if not isinstance(raw, dict):
                report["invalid"] += 1
                continue
            old = str(raw.get("id") or "")
            same = next((a for a in accounts if a["email"].lower() == str(raw.get("email") or "").strip().lower()), None)
            if same:
                ids[old] = same["id"]
                report["skipped"]["mail_accounts"] += 1
                continue
            try:
                acc = mail.clean_account(dict(raw, id="", password="x"), accounts, new_id)  # "x": the password is not in a backup
            except mail.MailError:
                report["invalid"] += 1
                continue
            if backup.ID_RE.fullmatch(old) and not any(a["id"] == old for a in accounts):
                acc["id"] = old  # calendars refer to it
            acc["password"] = ""
            accounts.append(acc)
            ids[old] = acc["id"]
            changed = True
            report["added"]["mail_accounts"] += 1
            report["secrets"].append({"kind": "mail", "name": acc["email"]})
        if changed:
            self.db.set_setting("mail_accounts", accounts)
        return ids

    def _import_calendars(self, items, mail_ids, report):
        """Link the backup's CalDAV and ICS accounts that are not linked yet (without passwords)."""
        sources, mails, changed = self.calendars(), self.mail_accounts(), False

        def key(c):
            return (c.get("type"), str(c.get("url") or "").strip().rstrip("/").lower(), str(c.get("username") or "").lower())
        for raw in items:
            if not isinstance(raw, dict):
                report["invalid"] += 1
                continue
            if any(key(c) == key(raw) for c in sources):
                report["skipped"]["calendars"] += 1
                continue
            link = mail_ids.get(raw.get("mail_account"), raw.get("mail_account") if any(a["id"] == raw.get("mail_account") for a in mails) else "")
            try:
                src = cal.clean_source(dict(raw, id="", mail_account=link, password="x"), sources, mails)
            except ValueError:
                report["invalid"] += 1
                continue
            if src["type"] == "caldav":
                src["password"] = ""
            else:
                src.pop("password", None)
            sources.append(src)
            changed = True
            report["added"]["calendars"] += 1
            if src["type"] == "caldav" and not src["mail_account"]:
                report["secrets"].append({"kind": "calendar", "name": src["name"]})
        if changed:
            self.db.set_setting("calendars", sources)

    # phone access -------------------------------------------------------
    def listens_everywhere(self):
        return self.host in ("0.0.0.0", "::", "")

    def lan_info(self):
        """Phone access: on/off, the address for other devices and its QR code (SVG)."""
        ip = lan_ip()
        on = self.listens_everywhere() or self.lan is not None
        if self.lan is not None:
            ip = self.lan.server_address[0]
        url = f"http://{ip}:{self.port}" if ip and self.port else None
        return {"enabled": on, "fixed": self.listens_everywhere(), "url": url if on else None,
                "address": url, "password_set": self.auth_required(), "error": self.lan_error,
                "qr": qr.svg(url) if on and url else None}

    def start_lan(self):
        """Also listen on the network address, so phones and tablets in the same network can connect.
        Needs a password. Raises ValueError with a message for the user."""
        if not self.auth_required():
            raise ValueError("Set a password first (Settings → Security). Otherwise anyone in your network could use Sunak.")
        if not self.listens_everywhere():
            ip = lan_ip()
            if not ip:
                raise ValueError("No local network found. Is this computer connected to Wi-Fi or a network cable?")
            with self._lan_lock:
                if not (self.lan and self.lan.server_address[0] == ip):
                    self._close_lan()
                    try:
                        srv = Server((ip, self.port), self.handler)
                    except OSError as e:
                        raise ValueError(f"Could not open {ip}:{self.port} ({e.strerror or e}).") from None
                    threading.Thread(target=srv.serve_forever, daemon=True).start()
                    self.lan = srv
        self.lan_error = ""
        self.main.set_setting("lan_access", True)

    def stop_lan(self):
        with self._lan_lock:
            self._close_lan()
        self.main.set_setting("lan_access", False)

    def _close_lan(self):
        srv, self.lan = self.lan, None
        if srv:
            srv.shutdown()
            srv.server_close()

    def restore_lan(self):
        """At start: switch phone access back on when it was on (silently off when that fails)."""
        if self.main.get_setting("lan_access") and not self.listens_everywhere():
            try:
                self.start_lan()
            except ValueError as e:
                self.lan_error = str(e)

    def _clean_providers(self, items):
        if not isinstance(items, list) or not all(isinstance(p, dict) for p in items):
            raise ValueError("providers must be a list of objects")
        old = {p["id"]: p for p in self.settings()["providers"]}
        clean = []
        for p in items:
            ptype, url = p.get("type"), p.get("base_url")
            if ptype not in ("ollama", "openai", "anthropic") or not isinstance(url, str) or not url.strip():
                raise ValueError("Each provider needs a type (ollama/openai/anthropic) and a base URL")
            url = url.strip()
            if not re.match(r"https?://", url, re.I):
                raise ValueError(f"Base URL must start with http:// or https:// ({url})")
            name = p.get("name") if isinstance(p.get("name"), str) else ""
            raw_id = p.get("id") if isinstance(p.get("id"), str) else ""
            pid = re.sub(r"[^a-z0-9_-]", "", (raw_id or name or "p").lower())[:24] or "p"
            while any(c["id"] == pid for c in clean):
                pid += "x"
            # The browser never sees saved keys; an empty field means "keep the saved key", but only
            # for the same provider type and address, so a saved key is never sent to a new server.
            key = p.get("api_key") if isinstance(p.get("api_key"), str) else ""
            prev = old.get(raw_id)
            if not key.strip() and prev and prev["type"] == ptype and prev["base_url"].rstrip("/") == url.rstrip("/"):
                key = prev.get("api_key", "")
            clean.append({"id": pid, "name": name.strip() or pid, "type": ptype, "base_url": url, "api_key": key.strip()})
        return clean

    @staticmethod
    def _clean_personas(items):
        if not isinstance(items, list) or not all(isinstance(p, dict) for p in items):
            raise ValueError("personas must be a list of objects")
        clean = []
        for p in items:
            name = str(p.get("name") or "").strip()[:40]
            if not name:
                raise ValueError("Each persona needs a name")
            pid = (re.sub(r"[^a-z0-9_-]", "", str(p.get("id") or "").lower())[:24]
                   or re.sub(r"[^a-z0-9]", "", name.lower())[:24] or "persona")
            while any(c["id"] == pid for c in clean):
                pid += "x"
            clean.append({"id": pid, "icon": str(p.get("icon") or "").strip()[:8], "name": name,
                          "prompt": str(p.get("prompt") or "").strip()})
        return clean

    def provider(self, pid):
        """Look up a configured provider by id."""
        for p in self.settings()["providers"]:
            if p["id"] == pid:
                log.add_secret(p.get("api_key"))  # never to be written to the log
                return p
        raise providers.ProviderError(f"Unknown provider '{pid}'. Check Settings.")

    def ollama_provider(self):
        """The first configured Ollama provider (used by the Models page)."""
        for p in self.settings()["providers"]:
            if p["type"] == "ollama":
                return p
        raise providers.ProviderError("No Ollama provider configured. Add one in Settings → Providers.")

    def local_gpu(self):
        """GPU info of this computer when Ollama runs here, else None (a remote Ollama has its own GPU)."""
        try:
            return self.gpu if ollama.is_local(self.ollama_provider()) else None
        except providers.ProviderError:
            return None

    def resolve(self, model_id):
        """Turn a model id 'provider::model' (or the default) into (provider, model name)."""
        if model_id is not None and not isinstance(model_id, str):
            raise ValueError("model must be text")
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

    def vision(self, prov, model):
        """Can the model see images? True, False, or None when the backend does not tell."""
        if prov["type"] == "anthropic":
            return True
        if prov["type"] == "ollama":
            caps = providers.ollama_capabilities(prov, model)
            return None if caps is None else "vision" in caps
        return None

    def clean_images(self):
        """Delete image files that no message refers to any more."""
        images.cleanup(self.user_dir, self.db.image_refs())

    def models(self):
        """Ask all providers in parallel for their models; unreachable providers are listed in `errors`. A backend that is
        busy (Ollama generating on a slow CPU answers late) gets a second, longer try; when that fails too, the list from the
        last success is kept (marked `stale`) so that the model picker does not empty out while a model is working."""
        out, errors = [], []
        provs = self.settings()["providers"]
        known = self.__dict__.setdefault("_model_lists", {})

        def fetch(p):
            key = (p["id"], p["base_url"])
            err = None
            for timeout in (providers.MODELS_TIMEOUT, providers.MODELS_TIMEOUT_BUSY):
                try:
                    known[key] = providers.list_models(p, timeout)
                    return p, known[key], None, False
                except Exception as e:  # noqa: BLE001 - surface any provider failure to the UI
                    err = str(e)
                    if "timed out" not in err.lower():  # refused, wrong key or address: waiting does not help
                        break
            return p, known.get(key, []), err, key in known

        with ThreadPoolExecutor(max_workers=max(1, len(provs))) as ex:
            for p, names, err, stale in ex.map(fetch, provs):
                if err:
                    errors.append({"provider": p["id"], "name": p["name"], "error": err, "stale": stale})
                for n in names:
                    out.append({"id": f"{p['id']}::{n}", "name": n, "provider": p["id"], "provider_name": p["name"]})
        return {"models": out, "errors": errors}

    # mail accounts ----------------------------------------------------
    def mail_accounts(self):
        """Linked e-mail accounts, including their passwords (server side only)."""
        return self.db.get_setting("mail_accounts") or []

    LOCAL_CALENDAR = {"id": "local", "type": "local", "name": "Sunak", "color": "", "enabled": True}

    def calendar_load(self, start, end):
        """(events, errors) of all shown calendars between the aware datetimes `start` and `end`, recurring ones
        expanded, sorted. A calendar that fails is listed in `errors` and leaves the others alone."""
        mails = self.mail_accounts()
        jobs = [("local", None, None)]
        for src in self.calendars():
            if not src.get("enabled", True):
                continue
            if src["type"] == "ics":
                jobs.append((src["id"], src, None))
            else:
                jobs += [(src["id"], src, c) for c in src.get("calendars", []) if c.get("enabled", True)]
        results, errors = [None] * len(jobs), []

        def load(i, sid, src, c):
            try:
                if sid == "local":
                    out = []
                    for row in self.db.cal_events():
                        try:
                            out += [dict(e, writable=True, color="") for e in cal.events_in(row["ics"], start, end, "local")]
                        except cal.CalendarError:
                            pass
                elif src["type"] == "ics":
                    out = [dict(e, writable=False, color=src["color"]) for e in cal.events_in(cal.fetch_ics(src["url"]), start, end, sid)]
                else:
                    user, pw = cal.login(src, mails)
                    out = []
                    for href, etag, text in cal.caldav_events(c["href"], user, pw, start, end):
                        try:
                            out += [dict(e, href=href, etag=etag, calendar=c["href"], writable=True, color=c.get("color") or src["color"])
                                    for e in cal.events_in(text, start, end, sid)]
                        except cal.CalendarError:
                            pass
                results[i] = out
            except (cal.CalendarError, ValueError) as e:
                errors.append({"source": sid, "name": (c or {}).get("name") or (src or {}).get("name", ""), "error": str(e)})

        threads = [threading.Thread(target=load, args=(i, *job), daemon=True) for i, job in enumerate(jobs)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(cal.TIMEOUT * 3)
        events = [e for r in results if r for e in r]
        events.sort(key=lambda e: (e["start"][:10], not e["all_day"], e["start"]))
        return events, errors

    def agenda_note(self, now):
        """The profile's own calendar for the next days as a system prompt note (intent.agenda). A calendar that cannot be read is
        left out and named, so that the model does not say "nothing planned" when it does not know."""
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            events, errors = self.calendar_load(midnight, midnight + datetime.timedelta(days=intent.AGENDA_DAYS + 1))
        except Exception as e:  # noqa: BLE001 - the chat must work without the calendar
            log_app.warning("Calendar for the chat note failed: %s", e)
            return "The user's calendar could not be read right now; say so instead of guessing."
        note = intent.agenda(events, now)
        if errors:
            note += "\n(Not readable right now: " + ", ".join(e["name"] or e["source"] for e in errors) + ")"
        return note

    def calendars(self):
        """Calendar accounts (CalDAV and ICS addresses), including passwords (server side only)."""
        return self.db.get_setting("calendars") or []

    def mail_account(self, aid):
        """One account by id; raises ValueError when it does not exist."""
        acc = next((a for a in self.mail_accounts() if a["id"] == aid), None)
        if not acc:
            raise ValueError("Unknown mail account. Add it in Settings → Mail accounts.")
        return acc

    # auth -------------------------------------------------------------
    def auth_required(self):
        """True when a password is set."""
        return bool(self.main.get_setting("password_hash"))

    def token(self):
        """Login cookie value; changes whenever the password changes."""
        return hmac.new(self.main.get_setting("secret").encode(), (self.main.get_setting("password_hash") or "").encode(),
                        "sha256").hexdigest()

    # profiles ---------------------------------------------------------
    def profiles(self):
        """All profiles (with their PIN hashes); the main profile ("default") always exists and is an admin."""
        out = self.main.get_setting("profiles") or []
        if not any(p["id"] == "default" for p in out):
            out = [{"id": "default", "name": "", "emoji": "", "admin": True, "pin_hash": ""}] + out
        return out

    def profile_info(self, pid):
        return next((p for p in self.profiles() if p["id"] == pid), None)

    def profile_dir(self, pid):
        return self.data_dir if pid == "default" else self.data_dir / "profiles" / pid

    def profile_db(self, pid):
        """The database of a profile (opened once)."""
        if pid == "default":
            return self.main
        with self._profiles_lock:
            db = self._profile_dbs.get(pid)
            if db is None:
                path = self.profile_dir(pid)
                path.mkdir(parents=True, exist_ok=True)
                db = self._profile_dbs[pid] = DB(str(path / "sunak.db"))
            return db

    def close_profile(self, pid):
        with self._profiles_lock:
            db = self._profile_dbs.pop(pid, None)
        if db:
            db.close()

    def view(self, pid):
        """The App as profile `pid` sees it."""
        return self if pid == "default" else ProfileView(self, pid, self.profile_db(pid), self.profile_dir(pid))

    def profile_cookie(self, p):
        """Cookie value proving the profile was chosen (with its PIN, if it has one); changes with the PIN."""
        sig = hmac.new(self.main.get_setting("secret").encode(), f"profile|{p['id']}|{p.get('pin_hash', '')}".encode(),
                       "sha256").hexdigest()
        return f"{p['id']}.{sig}"

    # chat -------------------------------------------------------------
    def persona_prompt(self, pid, personas=None):
        """System prompt of a persona id ('' for none or an unknown id)."""
        for p in personas if personas is not None else self.settings()["personas"]:
            if p["id"] == pid:
                return p["prompt"]
        return ""

    def build_messages(self, session, history, extra="", with_images=False, vision=True, abilities=False):
        """Chat history for the model: system prompt, persona, session prompt, memory notes, `extra`
        (knowledge-base excerpts), then the messages. `with_images` adds attached images (see
        images.attach); with `vision` False the model gets a note instead of the pictures. `abilities` (chat and tools only, not
        compare) adds the note that Sunak can prepare events and e-mails (intent.abilities; the mail part only with a linked account)."""
        s = self.settings()
        persona = self.persona_prompt(session.get("persona", ""), s["personas"])
        system = "\n\n".join(x for x in (s["system_prompt"], persona, session.get("system", "")) if x.strip())
        if s["use_memory"]:
            mem = self.db.memories()
            if mem:
                system += "\n\nThings you remember about the user:\n" + "\n".join(f"- {m}" for m in mem)
        if abilities:
            now = datetime.datetime.now().astimezone()
            system += "\n\n" + intent.abilities(now, bool(self.mail_accounts()))
            asked = [m["content"] for m in history if m["role"] == "user"][-2:]
            if intent.wants_schedule(*asked):
                system += "\n\n" + self.agenda_note(now)
        if extra:
            system += "\n\n" + extra
        msgs = [{"role": "system", "content": system}] if system.strip() else []
        for m in history:
            content = providers.strip_think(m["content"]) if m["role"] == "assistant" else m["content"]
            msgs.append({"role": m["role"], "content": content})
        if with_images:
            images.attach(self.user_dir, history, msgs, vision)
        return msgs

    def options(self):
        """Generation options (temperature) from the settings."""
        try:
            return {"temperature": float(self.settings()["temperature"])}
        except (TypeError, ValueError):
            return {}


class ProfileView(App):
    """The App for one profile other than the main one: its own database and image folder, everything else
    (settings of the installation, running tool answers, MCP servers, phone access) shared with the root App."""
    _OWN = ("root", "profile", "db", "user_dir")

    def __init__(self, root, pid, db, user_dir):  # noqa: super().__init__ is not called on purpose
        for k, v in zip(self._OWN, (root, pid, db, user_dir)):
            object.__setattr__(self, k, v)

    def __getattr__(self, name):
        return getattr(self.root, name)

    def __setattr__(self, name, value):
        if name in self._OWN:
            object.__setattr__(self, name, value)
        else:
            setattr(self.root, name, value)


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


def session_markdown(session):
    """A chat as Markdown: title, then each message under a heading. Reasoning is left out."""
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(session["created"]))
    out = [f"# {session['title']}", "", f"*Sunak · {when}*", ""]
    for m in session["messages"]:
        if m["role"] == "user":
            pics = [f"*[Image: {n}]*" for n in (m.get("meta") or {}).get("images", [])]
            out += ["## You", "", *pics, m["content"].strip(), ""]
        else:
            model = m["model"].split("::", 1)[-1] if m["model"] else ""
            out += ["## Sunak" + (f" ({model})" if model else ""), ""]
            out += [f"*[Image: {n}]*" for n in (m.get("meta") or {}).get("images", [])]
            out += [providers.strip_think(m["content"]), ""]
            files = (m.get("meta") or {}).get("sources")
            if files:
                out += ["Sources: " + ", ".join(f["name"] for f in files), ""]
    return "\n".join(out)


def file_name(title, ext):
    """Safe download name from a chat title."""
    base = re.sub(r"[^\w\- ]+", "", title, flags=re.U).strip()[:60] or "chat"
    return f"{base}.{ext}"


# What a model request is counted as (usage.py), by the path of the request that made it.
USAGE_KINDS = ((r"/api/chat", "chat"), (r"/api/tools", "tools"), (r"/api/research", "research"), (r"/api/compare", "compare"),
               (r"/api/documents/ai", "document"), (r"/api/mail/ai", "mail"), (r"/api/assistant/mail", "mail"), (r"/api/calendar/parse", "calendar"),
               (r"/api/imagine/intent", "image_check"), (r"/api/imagine", "image_prompt"),
               (rf"/api/sessions/[^/]+/remember", "memory"))


def usage_kind(path):
    return next((kind for pattern, kind in USAGE_KINDS if re.fullmatch(pattern, path)), "other")


class Handler(BaseHTTPRequestHandler):
    """HTTP request handler. Static files are served from STATIC; JSON API routes are listed in ROUTES.

    Streaming endpoints answer with NDJSON: one JSON object per line, e.g. {"type": "text", "t": "Hello"}."""
    app: App = None
    server_version = "Sunak/" + __version__
    timeout = 120  # a client that stops sending in the middle of a request must not hold a thread forever

    def log_message(self, fmt, *args):
        """http.server's own notes (bad request lines, timeouts); requests themselves are logged by `route`."""
        log_http.debug("%s %s", self.address_string(), fmt % args)

    _status = 0
    _stream_error = ""

    def send_response(self, code, message=None):
        self._status = code
        super().send_response(code, message)

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

    def send_download(self, data, name, ctype):
        """Send `data` (str or bytes) as a file download."""
        body = data.encode() if isinstance(data, str) else data
        ascii_name = name.encode("ascii", "replace").decode().replace("?", "_").replace('"', "")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition",
                         f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def error(self, msg, status=400):
        """Send {"error": msg} with the given status."""
        self.send_json({"error": msg}, status)

    def body(self):
        """Parse the JSON request body (a JSON object of at most MAX_BODY bytes)."""
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ValueError("Invalid Content-Length") from None
        if n < 0 or n > MAX_BODY:
            raise ValueError("Request too large" if n > 0 else "Invalid Content-Length")
        raw = self.rfile.read(n) if n else b""
        try:
            data = json.loads(raw) if raw else {}
        except RecursionError:
            raise ValueError("Invalid JSON: nested too deeply") from None
        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object")
        return data

    @staticmethod
    def text(d, key, default=""):
        """A text field of a request body; ValueError when it has another type."""
        v = d.get(key, default)
        if v is None:
            return default
        if not isinstance(v, str):
            raise ValueError(f"{key} must be text")
        return v

    @staticmethod
    def flag(d, key, default=False):
        """A true/false field of a request body; ValueError when it has another type."""
        v = d.get(key, default)
        if not isinstance(v, bool):
            raise ValueError(f"{key} must be true or false")
        return v

    streaming = False
    profile = None       # the profile of this request (set by route)
    sent_images = False  # set by prepare_chat: the request carried images

    def start_stream(self):
        """Send headers for an NDJSON stream; the connection closes when it ends."""
        self.streaming = True
        # a request that has to wait for the model tells the browser its place in the queue (jobqueue.py)
        jobqueue.local.notify = lambda place: self.emit({"type": "queued", "position": place})
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()

    def emit(self, obj):
        """Write one NDJSON event and flush it to the browser."""
        if obj.get("type") == "error" and not self._stream_error:
            self._stream_error = str(obj.get("error") or "")[:200]  # shows up in the request's log line
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
        """Handle one request and log it: method, path (no query), status, duration. Never the contents."""
        started = time.monotonic()
        self._status, self._stream_error = 0, ""
        try:
            self.dispatch(method)
        finally:
            took = time.monotonic() - started
            path = urlparse(self.path).path
            status = self._status or 0
            if status >= 500:
                level = logging.ERROR
            elif status >= 400 and not (status in (401, 404) and (method == "GET" or not path.startswith("/api/"))):
                level = logging.WARNING
            elif self._stream_error:
                level = logging.WARNING
            else:
                level = logging.INFO if method != "GET" and path.startswith("/api/") else logging.DEBUG
            if log_http.isEnabledFor(level):
                who = "" if self.is_direct_local() else f" from {self.client_address[0]}"
                err = f" (stream error: {self._stream_error})" if self._stream_error else ""
                log_http.log(level, "%s %s %s %.1fs%s%s", method, path[:200], status, took, who, err)

    def dispatch(self, method):
        """Dispatch a request: static files, CSRF header check, login, auth check, then ROUTES."""
        path = urlparse(self.path).path
        usage.unbind()  # this thread served another request before
        try:
            if not self.host_allowed():
                return self.error("This address is not allowed. Open Sunak via localhost or its IP address, "
                                  "or add the host name to SUNAK_ALLOWED_HOSTS.", 403)
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
            if path == "/api/shutdown" and method == "POST" and (self.is_direct_local() or self.authed() and (self.chosen_profile() or {}).get("admin")):
                return self.shutdown()
            if not self.authed():
                return self.error("Login required", 401)
            if path == "/api/profiles" and method == "GET":
                return self.profiles_list()
            if path == "/api/profiles/select" and method == "POST":
                return self.profile_select()
            if path in ("/api/profiles/leave", "/api/logout") and method == "POST":
                return self.profile_leave() if path == "/api/profiles/leave" else self.logout()
            prof = self.chosen_profile()
            if prof is None:
                return self.error("Choose a profile", 409)
            self.profile = prof
            self.app = self.app.view(prof["id"])
            usage.bind(self.app.db, prof["id"], usage_kind(path))
            for pattern, meth, fn in ROUTES:
                m = re.fullmatch(pattern, path)
                if m and meth == method:
                    if (meth, pattern) in ADMIN_ONLY and not prof.get("admin"):
                        return self.error("Only an admin profile can do this", 403)
                    return fn(self, *m.groups())
            return self.error("Not found", 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (ValueError, providers.ProviderError) as e:
            self.fail(str(e), 400)
        except Exception as e:  # noqa: BLE001 - never leave the browser without an answer
            log_http.error("Internal error in %s %s", method, path[:200], exc_info=True)
            self.fail(f"Internal error: {type(e).__name__}: {e}", 500)

    def fail(self, msg, status):
        """Report an error: as JSON, or as an NDJSON error event when a stream has already started."""
        try:
            if self.streaming:
                self.emit({"type": "error", "error": msg})
            else:
                self.error(msg, status)
        except OSError:
            pass

    def host_allowed(self):
        """Protection against DNS rebinding: a web page on another domain must not reach the API.
        Allowed are localhost, IP addresses, single-label and .local names, and SUNAK_ALLOWED_HOSTS."""
        host = (self.headers.get("Host") or "").strip().lower()
        if not host:
            return True
        host = host[1:].split("]")[0] if host.startswith("[") else host.rsplit(":", 1)[0] if host.count(":") == 1 else host
        extra = [h.strip().lower() for h in os.environ.get("SUNAK_ALLOWED_HOSTS", "").split(",") if h.strip()]
        if "*" in extra or host in extra:
            return True
        if host == "localhost" or host.endswith((".localhost", ".local")) or "." not in host:
            return True
        try:
            ipaddress.ip_address(host)
            return True
        except ValueError:
            return False

    def is_direct_local(self):
        """From this computer and not forwarded by a reverse proxy (then anyone could be behind it)."""
        return self.is_loopback() and not (self.headers.get("X-Forwarded-For") or self.headers.get("Forwarded"))

    def is_loopback(self):
        """True when the request comes from this computer."""
        return self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

    def shutdown(self):
        """POST /api/shutdown: stop the server (`sunak stop`, or the Stop button in Settings).
        Allowed from this computer, or from elsewhere when logged in."""
        self.send_json({"ok": True})
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def update_get(self):
        """GET /api/update: is a newer version available? (checked with git in the background)"""
        self.send_json(self.app.update_info())

    def update_check(self):
        """POST /api/update/check: look for a newer version now and report: behind, version, error."""
        self.send_json(self.app.check_updates_now())

    # error reports (admin profiles only) -----------------------------
    def usage_get(self):
        """GET /api/usage: the token counter of this profile: {last, total, background}. `last` is the latest request
        that was not a background one (fields: ts, provider, model, kind, input_tokens, output_tokens, cache_read_tokens,
        cache_creation_tokens, seconds, tokens_per_second, ok; unknown numbers are null), `total` and `background` are
        sums ({requests, the four token counts, all}; `all` includes cache reads and writes; `background` is the part of
        `total` that Sunak asked for by itself). Admin profiles also get `installation`: the sum of all profiles."""
        out = usage.summary(self.app.db)
        if self.profile.get("admin"):
            try:
                out["installation"] = sum(self.app.root.profile_db(p["id"]).usage_sums()["all"] for p in self.app.profiles())
            except Exception:  # noqa: BLE001 - the extra line is optional
                log_app.debug("Could not add up the token counters of all profiles", exc_info=True)
        self.send_json(out)

    def reports_get(self):
        """GET /api/reports: mode, whether a token is saved (never the token), waiting and sent reports."""
        self.send_json(self.app.reports.state())

    def reports_token(self):
        """POST /api/reports/token {token}: save the GitHub token ("" removes it)."""
        d = self.body()
        if not isinstance(d, dict):
            raise ValueError("Invalid request")
        self.app.reports.set_token(d.get("token"))
        self.send_json(self.app.reports.state())

    def reports_check(self):
        """POST /api/reports/check: can the saved token read the issues of the repository?"""
        token = self.app.reports.token()
        if not token:
            raise ValueError("No GitHub token is saved.")
        reports.check_token(token)
        self.send_json({"ok": True, "repo": reports.REPO})

    def reports_send(self):
        """POST /api/reports/send {id}: send one waiting report as a GitHub issue (or a comment on it)."""
        d = self.body()
        self.send_json(self.app.reports.send(str(d.get("id", "")) if isinstance(d, dict) else ""))

    def reports_dismiss(self):
        """POST /api/reports/dismiss {id}: throw a waiting report away without sending it."""
        d = self.body()
        self.app.reports.dismiss(str(d.get("id", "")) if isinstance(d, dict) else "")
        self.send_json(self.app.reports.state())

    def reports_sample(self):
        """POST /api/reports/sample: add a harmless made-up report, to see what a report looks like."""
        self.app.reports.sample()
        self.send_json(self.app.reports.state())

    def update_apply(self):
        """POST /api/update: stop this server; a helper process installs the update and starts Sunak again."""
        if updates.update_command() is None:
            raise ValueError("Sunak cannot update itself here. Run git pull and the installer in your Sunak folder.")
        host, port = self.server.server_address[:2]
        log_app.info("Update requested: Sunak stops, installs the new version and starts again")
        updates.spawn_helper(port, host, self.app.data_dir)
        self.send_json({"ok": True})
        threading.Thread(target=self.server.shutdown, daemon=True).start()

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
            "recommended": recommend(self.app.ram, self.app.local_gpu()),
            "instance": self.app.instance,
        })

    def login(self):
        """POST /api/login: check the password and set the login cookie."""
        data = self.body()
        stored = self.app.main.get_setting("password_hash")
        if stored and not check_password(self.text(data, "password"), stored):
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
        # API keys stay on the server: the browser only learns whether one is saved.
        s["providers"] = [dict({k: v for k, v in p.items() if k != "api_key"}, has_key=bool(p.get("api_key")))
                          for p in s["providers"]]
        s["mcp_servers"] = [mcp.public(c) for c in self.app.mcp_servers()]  # without environment values and tokens
        s["profile"] = self.profile_public(self.profile)
        s["profiles_count"] = len(self.app.profiles())
        s["image_status"] = sdcpp.status(self.app.data_dir, s)  # what is missing for pictures with Sunak's own program
        if self.profile.get("admin"):
            s["reports_pending"] = self.app.reports.pending_count()
        self.send_json(s)

    def put_settings(self):
        """PUT /api/settings: the profile's own preferences; settings of the installation (GLOBAL_KEYS)
        only from an admin profile."""
        d = self.body()
        if isinstance(d, dict) and GLOBAL_KEYS & set(d) and not self.profile.get("admin"):
            return self.error("Only an admin profile can change this setting", 403)
        if isinstance(d, dict) and "mcp_servers" in d and not self.tools_allowed():
            return
        self.app.save_settings(d)
        self.get_settings()

    # profiles ---------------------------------------------------------
    @staticmethod
    def profile_public(p):
        return {"id": p["id"], "name": p.get("name", ""), "emoji": p.get("emoji", ""), "admin": bool(p.get("admin")),
                "has_pin": bool(p.get("pin_hash"))}

    def chosen_profile(self):
        """The profile of this request: from the profile cookie, or the only profile when there is one
        without a PIN. None when the user has to choose."""
        profiles = self.app.profiles()
        m = re.search(r"(?:^|;\s*)sunak_profile=([a-z0-9]+)\.([a-f0-9]+)", self.headers.get("Cookie", ""))
        if m:
            p = next((p for p in profiles if p["id"] == m.group(1)), None)
            if p and hmac.compare_digest(f"{m.group(1)}.{m.group(2)}", self.app.profile_cookie(p)):
                return p
        if len(profiles) == 1 and not profiles[0].get("pin_hash"):
            return profiles[0]
        return None

    def profiles_list(self):
        """GET /api/profiles: all profiles (no PINs), the current one, and whether the user must choose."""
        cur = self.chosen_profile()
        self.send_json({"profiles": [self.profile_public(p) for p in self.app.profiles()],
                        "current": cur["id"] if cur else None, "need_choice": cur is None})

    def set_profile_cookie(self, value, max_age=31536000):
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Set-Cookie", f"sunak_profile={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}")
        self.end_headers()
        self.wfile.write(body)

    def profile_select(self):
        """POST /api/profiles/select {id, pin}: switch to a profile (its PIN, if it has one)."""
        d = self.body()
        p = self.app.profile_info(self.text(d, "id"))
        if not p:
            return self.error("Unknown profile", 404)
        if p.get("pin_hash") and not check_password(self.text(d, "pin"), p["pin_hash"]):
            time.sleep(1)
            return self.error("Wrong PIN", 403)
        self.set_profile_cookie(self.app.profile_cookie(p))

    def profile_leave(self):
        """POST /api/profiles/leave: forget the chosen profile on this device (back to the choice)."""
        self.set_profile_cookie("", 0)

    def clean_profile_fields(self, d, p):
        if "name" in d:
            name = d["name"]
            if not isinstance(name, str) or not name.strip():
                raise ValueError("Give the profile a name")
            p["name"] = name.strip()[:40]
        if "emoji" in d:
            p["emoji"] = str(d["emoji"] or "").strip()[:8]
        if "pin" in d:
            pin = d["pin"]
            if pin is not None and not isinstance(pin, str):
                raise ValueError("pin must be text")
            if pin and len(pin) < 4:
                raise ValueError("Use at least 4 characters for the PIN")
            p["pin_hash"] = hash_password(pin) if pin else ""

    def profile_create(self):
        """POST /api/profiles {name, emoji, pin, admin}: add a profile (admins only). It starts empty."""
        d = self.body()
        profiles = self.app.profiles()
        if len(profiles) >= MAX_PROFILES:
            raise ValueError(f"At most {MAX_PROFILES} profiles")
        p = {"id": secrets.token_hex(6), "name": "", "emoji": "", "admin": self.flag(d, "admin"), "pin_hash": ""}
        self.clean_profile_fields(dict(d, name=d.get("name", "")), p)
        self.app.main.set_setting("profiles", profiles + [p])
        self.send_json(self.profile_public(p))

    def profile_update(self, pid):
        """PATCH /api/profiles/<id> {name, emoji, pin, admin}: an admin changes any profile, everyone their own
        (but not their admin rights). The main profile stays an admin."""
        d = self.body()
        if pid != self.profile["id"] and not self.profile.get("admin"):
            return self.error("Only an admin profile can change other profiles", 403)
        profiles = self.app.profiles()
        p = next((x for x in profiles if x["id"] == pid), None)
        if not p:
            return self.error("Unknown profile", 404)
        self.clean_profile_fields(d, p)
        if "admin" in d:
            admin = self.flag(d, "admin")
            if admin != bool(p.get("admin")):
                if not self.profile.get("admin"):
                    return self.error("Only an admin profile can change admin rights", 403)
                if pid == "default" and not admin:
                    raise ValueError("The main profile always stays an admin")
                p["admin"] = admin
        self.app.main.set_setting("profiles", profiles)
        out = self.profile_public(p)
        if pid == self.profile["id"] and "pin" in d:  # keep this device in the profile after a PIN change
            body = json.dumps(out).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Set-Cookie", f"sunak_profile={self.app.profile_cookie(p)}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000")
            self.end_headers()
            return self.wfile.write(body)
        self.send_json(out)

    def profile_delete(self, pid):
        """DELETE /api/profiles/<id>: delete a profile with all its chats, documents, notes, knowledge base,
        mail and calendar links (admins only; not the main profile and not the own one)."""
        if pid in ("default", self.profile["id"]):
            raise ValueError("The main profile and the one you are using cannot be deleted")
        profiles = self.app.profiles()
        if not any(p["id"] == pid for p in profiles):
            return self.error("Unknown profile", 404)
        self.app.main.set_setting("profiles", [p for p in profiles if p["id"] != pid])
        self.app.close_profile(pid)
        shutil.rmtree(self.app.profile_dir(pid), ignore_errors=True)
        self.send_json({"ok": True})

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
        self.send_json(self.app.db.create_session(model=self.text(d, "model"), system=self.text(d, "system"),
                                                  use_kb=self.flag(d, "use_kb"), persona=self.text(d, "persona"),
                                                  use_web=self.flag(d, "use_web")))

    def get_session(self, sid):
        """GET /api/sessions/<id>: session with all messages."""
        s = self.app.db.get_session(sid)
        return self.send_json(s) if s else self.error("Not found", 404)

    def patch_session(self, sid):
        """PATCH /api/sessions/<id>: change title, model, system prompt, persona, use_kb or use_web."""
        d = self.body()
        fields = {}
        for k in ("title", "model", "system", "persona"):
            if k in d:
                if not isinstance(d[k], str):
                    raise ValueError(f"{k} must be text")
                fields[k] = d[k].strip() if k == "title" else d[k]
        if fields.get("title") == "":
            raise ValueError("Title must not be empty")
        for k in ("use_kb", "use_web"):
            if k in d:
                fields[k] = self.flag(d, k)
        self.app.db.update_session(sid, **fields)
        self.get_session(sid)

    def search(self):
        """GET /api/search?q=: chats whose title or messages contain all words, with a snippet."""
        q = parse_qs(urlparse(self.path).query).get("q", [""])[0]
        self.send_json(self.app.db.search_messages(q))

    def export_session(self, sid):
        """GET /api/sessions/<id>/export?format=md|json: download one chat."""
        s = self.app.db.get_session(sid)
        if not s:
            return self.error("Not found", 404)
        fmt = parse_qs(urlparse(self.path).query).get("format", ["md"])[0]
        if fmt == "json":
            return self.send_download(json.dumps(s, indent=2, ensure_ascii=False), file_name(s["title"], "json"),
                                      "application/json; charset=utf-8")
        self.send_download(session_markdown(s), file_name(s["title"], "md"), "text/markdown; charset=utf-8")

    def export_all(self):
        """GET /api/export: everything as one JSON file (API keys and the password are left out)."""
        data = self.app.db.export_all()
        s = self.app.settings()
        s["ntfy_topic"] = ""  # the topic works like a password
        s["providers"] = [{k: v for k, v in p.items() if k != "api_key"} for p in s["providers"]]
        data.update(sunak_version=__version__, exported=time.strftime("%Y-%m-%dT%H:%M:%S"), settings=s,
                    mail_accounts=[{k: v for k, v in a.items() if k != "password"} for a in self.app.mail_accounts()],
                    calendars=[cal.public(c) for c in self.app.calendars()])
        self.send_download(json.dumps(data, indent=2, ensure_ascii=False),
                           f"sunak-backup-{time.strftime('%Y-%m-%d')}.json", "application/json; charset=utf-8")

    def import_data(self):
        """POST /api/import <a backup file or one exported chat as the request body>: add it to this profile. Answers with
        what was added and skipped, and which passwords and keys have to be entered again."""
        self.send_json(self.app.import_backup(self.body(), bool(self.profile.get("admin"))))

    def delete_session(self, sid):
        """DELETE /api/sessions/<id>"""
        self.app.db.delete_session(sid)
        self.app.clean_images()
        self.send_json({"ok": True})

    def lan_get(self):
        """GET /api/lan: phone access state, address and QR code."""
        self.send_json(self.app.lan_info())

    def lan_set(self):
        """POST /api/lan {enabled}: switch phone access on (needs a password) or off."""
        d = self.body()
        if self.flag(d, "enabled"):
            self.app.start_lan()
        elif self.app.listens_everywhere():
            raise ValueError("Sunak was started with --host 0.0.0.0 and is always reachable in the network. "
                             "Start it without that option to switch this off.")
        else:
            self.app.stop_lan()
        self.send_json(self.app.lan_info())

    def get_image(self, name):
        """GET /api/images/<name>: an image attached to a chat message."""
        found = images.load(self.app.user_dir, name)
        if not found:
            return self.error("Not found", 404)
        data, ctype = found
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "private, max-age=86400")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def prepare_chat(self, d, allow_images=False):
        """Shared start of /api/chat and /api/tools: check the request, apply truncate_from, store the
        user message (with new `images` [{name, data}] and kept `image_refs`), update
        model/persona/use_kb/title of the chat. Returns (session, provider, model, model id, title),
        or None when an error was already sent."""
        db = self.app.db
        session = db.get_session(str(d.get("session_id") or ""))
        if not session:
            self.error("Session not found", 404)
            return None
        model_id = d.get("model") or session["model"]
        if not isinstance(model_id, str):
            raise ValueError("model must be text")
        content = d.get("content") or ""
        if not isinstance(content, str):
            raise ValueError("content must be text")
        content = content.strip()
        prov, model = self.app.resolve(model_id)
        model_id = f"{prov['id']}::{model}"
        sid = session["id"]
        refs = images.existing(self.app.user_dir, d.get("image_refs"))
        if d.get("images") or refs:
            if not allow_images:
                raise ValueError("Tools (MCP) cannot look at images yet. Switch them off to ask about the image.")
            if self.app.vision(prov, model) is False:
                raise ValueError(f"{model} cannot see images. Pick a model with vision: on the Models page e.g. "
                                 "qwen2.5vl, gemma3 or llama3.2-vision, or Claude.")
            if len(refs) + len(d.get("images") or []) > images.MAX_IMAGES:
                raise ValueError(f"At most {images.MAX_IMAGES} images per message")
        names = refs + images.save(self.app.user_dir, d.get("images"))
        self.sent_images = bool(names)
        if d.get("truncate_from"):
            from_id = d["truncate_from"]
            # only a message of this chat; anything else would silently wipe the chat
            if isinstance(from_id, bool) or not isinstance(from_id, int) or from_id not in {m["id"] for m in session["messages"]}:
                raise ValueError("That message is not part of this chat (reload the page)")
            db.truncate_messages(sid, from_id)
            self.app.clean_images()
        if content or names:
            db.add_message(sid, "user", content, meta={"images": names} if names else None)
        session = db.get_session(sid)
        if not session["messages"] or session["messages"][-1]["role"] != "user":
            self.error("Nothing to answer")
            return None
        updates = {"model": model_id}
        for k in ("use_kb", "use_web"):
            if k in d:
                updates[k] = session[k] = self.flag(d, k)
        if "persona" in d:
            updates["persona"] = session["persona"] = str(d["persona"] or "")
        if session["title"] == "New chat":
            # name the chat after the question, not after attached files (File `x`: ``` … ```)
            first_msg = session["messages"][0]["content"]
            first = ((ATTACHED_RE.sub("", first_msg).strip() or first_msg.strip()).splitlines() or ["Image"])[0]
            updates["title"] = (first[:57] + "…") if len(first) > 58 else first
        db.update_session(sid, **updates)
        return session, prov, model, model_id, updates.get("title", session["title"])

    def chat(self):
        """POST /api/chat: store the user message, stream the answer, store it.

        `truncate_from` deletes that message and everything after it first (regenerate / edit).
        `use_kb` switches the knowledge base on or off for this chat, `persona` picks a persona id
        (both are stored with the chat).
        Events: start, sources (knowledge base only), think, text, done | error.
        A partial answer is kept if the stream breaks."""
        d = self.body()
        db = self.app.db
        prepared = self.prepare_chat(d, allow_images=True)
        if not prepared:
            return
        session, prov, model, model_id, title = prepared
        sid = session["id"]

        extras, meta = [], {}
        if session["use_kb"]:
            # search with the last two questions so follow-ups ("and in 2023?") keep their topic
            asked = [m["content"] for m in session["messages"] if m["role"] == "user"][-2:]
            found = knowledge.retrieve(db, "\n".join(reversed(asked)))
            if found:
                extras.append(knowledge.context(found))
            meta["sources"] = knowledge.sources(found)
        vision = True
        if any(m["meta"].get("images") for m in session["messages"] if m["role"] == "user"):
            vision = self.app.vision(prov, model) is not False
        self.start_stream()
        self.emit({"type": "start", "title": title, "model": model_id})
        if "sources" in meta:
            self.emit({"type": "sources", "sources": meta["sources"]})
        if session["use_web"]:
            web = self.web_search(prov, model, session["messages"])
            if web:
                extras.append(web[0])
                meta["web"] = web[1]
        messages = self.app.build_messages(session, session["messages"], "\n\n".join(extras), with_images=True, vision=vision, abilities=True)
        meta = meta or None
        chunks = []

        def save():
            """Store the (possibly partial) answer; the chat may have been deleted meanwhile."""
            text = stream_to_text(chunks)
            if text:
                try:
                    db.add_message(sid, "assistant", text, model_id, meta)
                except sqlite3.IntegrityError:
                    pass

        try:
            for kind, c in providers.chat_stream(prov, model, messages, self.app.options()):
                chunks.append((kind, c))
                self.emit({"type": kind, "t": c})
        except (BrokenPipeError, ConnectionResetError):  # the browser went away (Stop button)
            return save()
        except Exception as e:  # noqa: BLE001 - keep the partial answer and tell the browser
            save()
            if isinstance(e, providers.ProviderError):
                log_app.warning("Model %s: %s", model_id, str(e)[:200])
            else:
                log_app.error("Unexpected error while answering with %s", model_id, exc_info=True)
            hint = ""
            if self.sent_images and not chunks and prov["type"] == "openai":
                hint = " (If this model cannot see images, pick one with vision.)"
            return self.emit({"type": "error", "error": str(e) + hint})
        save()
        self.emit({"type": "done"})

    def web_search(self, prov, model, history):
        """Search the web for the latest question (emits status and `web` events).
        Returns (context for the system prompt, [{title, url}]) or None."""
        last = ATTACHED_RE.sub("", history[-1]["content"]).strip()
        if not last:
            self.emit({"type": "status", "t": "Nothing to search for: the message has no text."})
            return None
        query = " ".join(last.split())[:300]
        if len(history) > 1:  # follow-ups ("and in Berlin?") need the conversation to make sense
            convo = "\n\n".join(f"{m['role']}: {providers.strip_think(ATTACHED_RE.sub('', m['content']))[:600]}"
                                 for m in history[-5:])
            self.emit({"type": "status", "t": "Thinking of a search query…"})
            try:
                q = providers.chat_once(prov, model, [
                    {"role": "system", "content": "Write ONE short web search query (at most 10 words) that finds "
                     "current information for the user's latest message. Use the earlier messages only to "
                     "resolve references like 'it' or 'there'. Reply with the query only, no quotes."},
                    {"role": "user", "content": convo}], {"temperature": 0})
                query = research.clean_queries(q, query, limit=1)[0][:300]
            except providers.ProviderError:
                pass
        self.emit({"type": "status", "t": f"Searching the web: {query}"})
        try:
            pages = research.gather(query)
        except research.SearchError as e:
            log_app.warning("Web search failed: %s", e)
            self.emit({"type": "status", "t": f"Web search failed ({e}), answering without it."})
            return None
        except Exception as e:  # noqa: BLE001 - anything else: answer without the web
            log_app.warning("Web search failed: %s", type(e).__name__)
            self.emit({"type": "status", "t": f"Web search failed ({type(e).__name__}), answering without it."})
            return None
        if not pages:
            self.emit({"type": "status", "t": "The web search found nothing readable, answering without it."})
            return None
        sources = [{"title": p["title"], "url": p["url"]} for p in pages]
        self.emit({"type": "web", "query": query, "sources": sources})
        return research.web_context(query, pages, time.strftime("%Y-%m-%d")), {"query": query, "sources": sources}

    # tools (MCP) in the chat ------------------------------------------
    def tools_allowed(self):
        """MCP servers run programs on this computer: from other devices they need a password.
        Sends the error and returns False otherwise."""
        if not self.is_direct_local() and not self.app.auth_required():
            self.error("Tools (MCP) from another device need a password. Set one in Settings → Security.", 403)
            return False
        return True

    def tools_chat(self):
        """POST /api/tools: like /api/chat, but the model works with the tools of the enabled MCP servers
        (see sunak/toolrun.py).

        Events: start (with `run`), think, text, step, confirm (answer with /api/tools/confirm),
        step_done, notice, ping, done | error. The answer is stored with its steps in meta.tools."""
        d = self.body()
        if not self.tools_allowed():
            return
        if not any(c.get("enabled") for c in self.app.mcp_servers()):
            raise ValueError("No MCP server is switched on. Add one in Settings → Tools (MCP).")
        prepared = self.prepare_chat(d)
        if not prepared:
            return
        session, prov, model, model_id, title = prepared
        sid, db = session["id"], self.app.db
        allowed = self.app.tool_runs.allowed(sid)

        def save():
            if run and run.parts:
                try:
                    db.add_message(sid, "assistant", run.text(), model_id, {"tools": {"parts": run.parts}})
                except sqlite3.IntegrityError:
                    pass

        run = None
        run_id = toolrun.new_run_id()
        try:
            self.start_stream()
            self.emit({"type": "start", "title": title, "model": model_id, "run": run_id, "allowed": sorted(allowed)})
            tools, errors = self.app.mcp.tools(
                self.app.mcp_servers(), lambda name: self.emit({"type": "notice", "t": f"Starting MCP server {name} …"}))
            for name, err in errors.items():
                self.emit({"type": "notice", "t": f"MCP server {name}: {err}"})
            if not tools:
                return self.emit({"type": "error", "error": "None of the MCP servers is available."})
            run = toolrun.ToolRun(prov, model, self.app.build_messages(session, session["messages"], abilities=True), self.emit,
                                  self.app.options(), allowed, tools, run_id)
            self.app.tool_runs.add(run)
            run.run()
        except (BrokenPipeError, ConnectionResetError):  # the browser went away
            if run:
                run.cancel()
            return save()
        except toolrun.Cancelled:
            pass
        except Exception as e:  # noqa: BLE001 - keep what was done and tell the browser
            save()
            if isinstance(e, providers.ProviderError):
                log_app.warning("Model %s: %s", model_id, str(e)[:200])
            else:
                log_app.error("Unexpected error while answering with %s", model_id, exc_info=True)
            return self.emit({"type": "error", "error": str(e)})
        finally:
            if run:
                self.app.tool_runs.remove(run)
        save()
        self.emit({"type": "done", "stopped": run.cancelled.is_set()})

    def tools_confirm(self):
        """POST /api/tools/confirm: {run, id, decision: allow | always | deny} for a waiting step."""
        if not self.tools_allowed():
            return
        d = self.body()
        decision = self.text(d, "decision")
        if decision not in ("allow", "always", "deny"):
            raise ValueError("decision must be allow, always or deny")
        run = self.app.tool_runs.get(self.text(d, "run"))
        if not run or not run.decide(self.text(d, "id"), decision):
            return self.error("Nothing is waiting for this answer any more", 404)
        self.send_json({"ok": True})

    def tools_cancel(self):
        """POST /api/tools/cancel: {run} stops the answer with tools."""
        run = self.app.tool_runs.get(self.text(self.body(), "run"))
        if run:
            run.cancel()
        self.send_json({"ok": True})

    def tools_revoke(self):
        """POST /api/tools/revoke: {session_id} forgets "Allow in this chat" for that chat."""
        self.app.tool_runs.revoke(self.text(self.body(), "session_id"))
        self.send_json({"ok": True})

    def mcp_test(self):
        """POST /api/mcp/test: {server} (as in the settings form, not yet saved) is started once; returns its tools."""
        if not self.tools_allowed():
            return
        d = self.body()
        if not isinstance(d.get("server"), dict):
            raise ValueError("server must be an object")
        config = mcp.clean([d["server"]], self.app.mcp_servers())[0]
        try:
            tools = mcp.test(config)
        except mcp.MCPError as e:
            raise ValueError(str(e)) from None
        self.send_json({"tools": [{"name": t["name"], "description": str(t.get("description") or "")[:300]} for t in tools]})

    def compare(self):
        """POST /api/compare: stream one prompt to 2-4 models in parallel. Events carry `i`, the model index."""
        d = self.body()
        prompt = d.get("prompt") if isinstance(d.get("prompt"), str) else ""
        prompt = prompt.strip()
        model_ids = d.get("models") if isinstance(d.get("models"), list) else []
        model_ids = [m for m in model_ids if isinstance(m, str)]
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
        threads = [usage.thread(run, i, p, m) for i, (p, m) in enumerate(targets)]
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
        question = self.text(d, "question").strip()
        if not question:
            raise ValueError("Enter a question")
        prov, model = self.app.resolve(d.get("model"))
        self.start_stream()
        try:
            self.emit({"type": "status", "t": "Planning search queries…"})
            try:
                plan = providers.chat_once(prov, model, [
                    {"role": "system", "content": "Return 3 short web search queries (one per line, no numbering, "
                                                  "no quotes) that together answer the user's question."},
                    {"role": "user", "content": question},
                ], {"temperature": 0.2})
            except providers.ProviderError as e:
                log_app.warning("Research: the model could not plan queries (%s), searching for the question itself", str(e)[:150])
                plan = ""
            plain = " ".join(question.split())[:200]
            queries = research.clean_queries(plan, question)
            log_app.info("Research: %d search queries (model answer: %d characters%s)", len(queries), len(plan),
                         ", used the question itself" if queries == [plain] else "")
            fallback = plain not in queries  # last resort when the model's queries find nothing
            if fallback:
                queries.append(plain)
            results, seen, problems, answered = [], set(), [], False
            for i, qy in enumerate(queries):
                if fallback and results and i == len(queries) - 1:
                    break
                self.emit({"type": "status", "t": f"Searching: {qy}"})
                try:
                    found = research.search(qy, limit=4)
                    answered = True
                    for r in found:
                        if r["url"] not in seen:
                            seen.add(r["url"])
                            results.append(r)
                except research.SearchError as e:
                    problems.append(str(e))
                    self.emit({"type": "status", "t": f"Search failed ({e})"})
                except Exception as e:  # noqa: BLE001
                    problems.append(type(e).__name__)
                    self.emit({"type": "status", "t": f"Search failed ({type(e).__name__})"})
            if not results:
                if answered:
                    log_app.info("Research: the search engines answered but found nothing")
                    return self.emit({"type": "error", "error": "The web search found nothing for this question. Try asking it differently."})
                log_app.warning("Research: no search engine usable: %s", (problems or ["?"])[0][:300])
                return self.emit({"type": "error", "error": "The web search is not working: " + (problems or ["no answer"])[0]
                                  + ". Check the internet connection, or set SEARXNG_URL to your own search server."})
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
        self.send_json(self.app.db.save_document(None, self.text(d, "title") or "Untitled", self.text(d, "content")))

    def get_document(self, did):
        """GET /api/documents/<id>"""
        doc = self.app.db.get_document(did)
        return self.send_json(doc) if doc else self.error("Not found", 404)

    def put_document(self, did):
        """PUT /api/documents/<id>"""
        d = self.body()
        self.send_json(self.app.db.save_document(did, self.text(d, "title") or "Untitled", self.text(d, "content")))

    def delete_document(self, did):
        """DELETE /api/documents/<id>"""
        self.app.db.delete_document(did)
        self.send_json({"ok": True})

    def document_ai(self):
        """POST /api/documents/ai: stream a rewrite of the document or of `selection` following `instruction`."""
        d = self.body()
        instruction = self.text(d, "instruction").strip()
        if not instruction:
            raise ValueError("Tell the AI what to do")
        prov, model = self.app.resolve(d.get("model"))
        selection = self.text(d, "selection")
        content = self.text(d, "content")
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
        content = d.get("content") if isinstance(d.get("content"), str) else ""
        content = content.strip()
        if not content:
            raise ValueError("Note is empty")
        self.send_json(self.app.db.add_note(content, self.flag(d, "is_memory")))

    def patch_note(self, nid):
        """PATCH /api/notes/<id>: change text or memory flag."""
        d = self.body()
        if d.get("content") is not None and (not isinstance(d["content"], str) or not d["content"].strip()):
            raise ValueError("Note must be non-empty text")
        self.app.db.update_note(nid, d.get("content"), self.flag(d, "is_memory") if "is_memory" in d else None)
        self.send_json({"ok": True})

    def delete_note(self, nid):
        """DELETE /api/notes/<id>"""
        self.app.db.delete_note(nid)
        self.send_json({"ok": True})

    def remember(self, sid):
        """POST /api/sessions/<id>/remember: after an answer, let the chat's model pick lasting facts about
        the user from the last exchange and store them as memory notes (see memory.py). Runs when memory
        is on and either automatic memory is on or the user asked for something to be remembered; not
        after tool runs or pictures. Returns {added: [notes]} (and `error` when the model failed)."""
        db, s = self.app.db, self.app.settings()
        session = db.get_session(sid)
        if not session:
            return self.error("Session not found", 404)
        msgs = session["messages"]
        if (not s["use_memory"] or len(msgs) < 2 or msgs[-1]["role"] != "assistant" or msgs[-2]["role"] != "user"
                or msgs[-1]["meta"].get("tools") or msgs[-1]["meta"].get("agent") or msgs[-1]["meta"].get("imagegen")):
            return self.send_json({"added": []})
        history = [{"role": m["role"], "content": ATTACHED_RE.sub("", m["content"]).strip() if m["role"] == "user"
                    else m["content"]} for m in msgs[-3:]]
        explicit = memory.is_explicit(history[-2]["content"])
        if not history[-2]["content"] or not (s["auto_memory"] or explicit):
            return self.send_json({"added": []})
        try:
            prov, model = self.app.resolve(session["model"] or None)
            facts = memory.extract(prov, model, history, db.memories(), explicit)
        except providers.ProviderError as e:
            return self.send_json({"added": [], "error": str(e)})
        self.send_json({"added": [db.add_note(f, True, sid) for f in facts]})

    # knowledge base
    def file_upload(self):
        """Decode an upload {name, data (base64)} and return (name, bytes, text). Raises ValueError."""
        d = self.body()
        name = d.get("name") if isinstance(d.get("name"), str) else ""
        name = re.sub(r"[\\/\x00-\x1f]", "_", name.strip())[-200:]
        if not name:
            raise ValueError("File name missing")
        try:
            data = base64.b64decode(d.get("data") or "", validate=True)
        except (binascii.Error, ValueError, TypeError):
            raise ValueError("Upload is damaged, please try again") from None
        text = extract.extract_text(name, data).strip()
        if not text:
            raise ValueError(f"{name}: the file contains no text")
        return name, data, text

    def kb_list(self):
        """GET /api/knowledge: files, total size, and whether full-text search (FTS5) is available."""
        db = self.app.db
        self.send_json({"files": db.kb_files(), "chars": db.kb_total_chars(), "fts": db.fts})

    def kb_upload(self):
        """POST /api/knowledge {name, data}: extract the text, chunk and index it. Same name replaces."""
        name, data, text = self.file_upload()
        self.send_json(self.app.db.kb_add(name, len(data), knowledge.chunk(text)))

    def kb_get(self, fid):
        """GET /api/knowledge/<id>: one file with its extracted text."""
        f = self.app.db.kb_file(fid)
        return self.send_json(f) if f else self.error("Not found", 404)

    def kb_delete(self, fid):
        """DELETE /api/knowledge/<id>"""
        self.app.db.kb_delete(fid)
        self.send_json({"ok": True})

    def kb_search(self):
        """GET /api/knowledge/search?q=: matching chunks with a short snippet."""
        q = parse_qs(urlparse(self.path).query).get("q", [""])[0]
        words = knowledge.terms(q)
        hits = knowledge.search(self.app.db, q, 20)
        self.send_json([{"file_id": h["file_id"], "name": h["name"], "idx": h["idx"],
                         "snippet": knowledge.snippet(h["text"], words)} for h in hits])

    # image generation ---------------------------------------------------
    def imagegen_test(self):
        """POST /api/imagegen/test {type, url, model} (the settings form, not saved yet): the backend's models."""
        cfg = imagegen.config(self.app.settings(), self.body())
        if cfg["type"] not in imagegen.BACKENDS:
            raise ValueError("Choose Automatic1111 or ComfyUI first")
        try:
            self.send_json({"models": imagegen.models(cfg)})
        except imagegen.ImageGenError as e:
            raise ValueError(str(e)) from None

    def local_images(self):
        """GET /api/imagegen/local: Sunak's own image program (installed?) and the image models."""
        eng = {k: v for k, v in sdcpp.engine_info(self.app.data_dir).items() if k != "path"}
        self.send_json({"engine": eng, "models": sdcpp.listing(self.app.data_dir, self.app.ram, self.app.gpu)})

    def engine_options(self):
        """GET /api/imagegen/engine: the stable-diffusion.cpp release files that fit this computer, best first."""
        try:
            rel = sdcpp.latest_release()
        except sdcpp.SdError as e:
            raise ValueError(str(e)) from None
        opts = sdcpp.rank_assets(rel["assets"], gpu_info=self.app.gpu)
        if not opts:
            raise ValueError("stable-diffusion.cpp has no ready-made program for this computer. Use ComfyUI or Automatic1111 instead.")
        self.send_json({"tag": rel["tag"], "options": [{k: o[k] for k in ("name", "size", "kind")} for o in opts]})

    def stream_download(self, work):
        """Run a download with NDJSON progress events (done, total in bytes). Closing the connection stops it;
        the next try continues where it stopped."""
        self.start_stream()

        def progress(done, total, *_):
            self.emit({"type": "progress", "completed": done, "total": total})
        try:
            result = work(progress)
        except sdcpp.SdError as e:
            return self.emit({"type": "error", "error": str(e)})
        except ConnectionError:  # the browser went away (Cancel)
            return None
        except OSError as e:  # disk full, no permission, a file locked by another program
            return self.emit({"type": "error", "error": f"File error: {e.strerror or e}"})
        self.emit({"type": "done", **(result or {})})

    def engine_install(self):
        """POST /api/imagegen/engine/install {name}: download and unpack one of the listed release files.
        Only names from the GitHub release are accepted, never an address from the browser."""
        name = self.text(self.body(), "name")
        try:
            rel = sdcpp.latest_release()
        except sdcpp.SdError as e:
            raise ValueError(str(e)) from None
        asset = next((o for o in sdcpp.rank_assets(rel["assets"], gpu_info=self.app.gpu) if o["name"] == name), None)
        if not asset:
            raise ValueError("Pick one of the listed program files")

        def work(progress):
            info = sdcpp.install_engine(self.app.data_dir, asset, rel["tag"], progress)
            return {"engine": {k: v for k, v in info.items() if k != "path"}}
        self.stream_download(work)

    def engine_remove(self):
        """POST /api/imagegen/engine/remove: delete the image program (the models stay)."""
        sdcpp.remove_engine(self.app.data_dir)
        self.send_json({"ok": True})

    def image_model_pull(self):
        """POST /api/imagegen/models/pull {id} (catalog) or {repo, path} (a file from the search): download it."""
        d = self.body()
        if d.get("repo"):
            try:
                info = modelsearch.hf_files(self.text(d, "repo"), "image")
            except modelsearch.SearchError as e:
                raise ValueError(f"Hugging Face is not reachable ({e})") from None
            f = next((f for f in info["files"] if f["path"] == self.text(d, "path")), None)
            if not f:
                raise ValueError("That file is not in the repository")
            try:
                m = sdcpp.custom_entry(info["repo"], f["path"], f["size"], info["license"], info["gated"])
            except sdcpp.SdError as e:
                raise ValueError(str(e)) from None
        else:
            m = next((m for m in sdcpp.CATALOG if m["id"] == self.text(d, "id")), None)
            if not m:
                raise ValueError("Unknown image model")
        self.stream_download(lambda progress: (sdcpp.pull(self.app.data_dir, m, progress), {"id": m["id"]})[1])

    def image_model_delete(self):
        """POST /api/imagegen/models/delete {id}: delete a downloaded image model."""
        try:
            sdcpp.delete_model(self.app.data_dir, self.text(self.body(), "id"))
        except sdcpp.SdError as e:
            raise ValueError(str(e)) from None
        self.send_json({"ok": True})

    def model_search(self):
        """GET /api/models/search?q=&kind=chat|image: the Ollama library and Hugging Face. A site that cannot be
        reached is left out (listed in `unreachable`), so the page simply shows fewer results."""
        qs = parse_qs(urlparse(self.path).query)
        q = (qs.get("q", [""])[0]).strip()[:100]
        kind = qs.get("kind", ["chat"])[0]
        if not q:
            raise ValueError("Type what to search for")
        out = {"ollama": [], "huggingface": [], "unreachable": []}
        jobs = {"huggingface": lambda: modelsearch.hf_search(q, "image" if kind == "image" else "chat")}
        if kind != "image":
            jobs["ollama"] = lambda: modelsearch.ollama_search(q)
        results = {}

        def run(key, fn):
            try:
                results[key] = fn()
            except modelsearch.SearchError:
                pass
        threads = [threading.Thread(target=run, args=item, daemon=True) for item in jobs.items()]
        for t in threads:
            t.start()
        for t in threads:
            t.join(15)
        for key in jobs:
            if key in results:
                out[key] = results[key]
            else:
                out["unreachable"].append(key)
        self.send_json(out)

    def model_files(self):
        """GET /api/models/files?repo=&kind=chat|image: files of a Hugging Face repository with size and license."""
        qs = parse_qs(urlparse(self.path).query)
        try:
            self.send_json(modelsearch.hf_files(qs.get("repo", [""])[0], qs.get("kind", ["chat"])[0]))
        except modelsearch.SearchError as e:
            raise ValueError(f"Hugging Face is not reachable ({e})") from None

    def assistant_intent(self):
        """POST /api/assistant/intent {text, where}: does this chat message ask to prepare a calendar event or an e-mail?
        Answer: {action: "event" | "mail" | ""}. Rules only (sunak/intent.py), no model call. Nothing is saved or sent:
        the browser prepares the event / draft and waits for a click."""
        text = self.text(self.body(), "text").strip()
        kind = intent.action(text)
        log_assist.info("Assistant request check (chat): %s", kind or "not an event or mail request")
        self.send_json({"action": kind})

    def assistant_check(self):
        """POST /api/assistant/check {kind: event|mail, json, now}: the chat model answered with a ```sunak-event``` or
        ```sunak-mail``` block (intent.abilities); check its JSON the way the other endpoints do and return the draft for the
        card ({summary, start, end, all_day, location, description} or {to, to_name, subject, body, account}). No model call;
        nothing is saved or sent."""
        d = self.body()
        kind, raw = self.text(d, "kind"), self.text(d, "json")[:20000]
        if kind == "event":
            try:
                now = datetime.datetime.fromisoformat(str(d.get("now") or "").replace("Z", "+00:00"))
            except ValueError:
                raise ValueError("now must be an ISO date-time") from None
            if now.tzinfo is None:
                raise ValueError("now needs a time zone")
            out = cal.parse_answer(raw, now)
        elif kind == "mail":
            accounts = self.app.mail_accounts()
            if not accounts:
                raise ValueError("Add a mail account first")
            try:
                out = {**mail.parse_draft(raw), "account": accounts[0]["id"]}
            except mail.MailError as e:
                raise ValueError(str(e)) from None
        else:
            raise ValueError("kind must be event or mail")
        log_assist.info("Card from the chat model's answer: %s", kind)
        self.send_json(out)

    def assistant_mail(self):
        """POST /api/assistant/mail {text, account, model}: write a new e-mail from a chat request ("write Anna that I am late").
        Answer: {to, to_name, subject, body, account}; `account` is the linked account the draft is for (the given one, else the
        first). Nothing is sent: the browser opens the compose form with the draft. Without a linked account: 400 with a hint."""
        d = self.body()
        text = self.text(d, "text").strip()
        if not text:
            raise ValueError("Say what the e-mail should be about")
        accounts = self.app.mail_accounts()
        if not accounts:
            raise ValueError("Add a mail account first")
        acc = self.app.mail_account(d["account"]) if d.get("account") else accounts[0]
        memories = self.app.db.memories() if self.app.settings()["use_memory"] else []
        prov, model = self.app.resolve(d.get("model"))
        answer = providers.chat_once(prov, model, mail.draft_messages(text[:4000], acc, memories), {"temperature": 0.3})
        try:
            draft = mail.parse_draft(answer, intent.addresses(text))
        except mail.MailError as e:
            raise ValueError(str(e)) from None
        log_assist.info("E-mail draft from a chat request: %s", "recipient known" if draft["to"] else "no recipient address")
        self.send_json({**draft, "account": acc["id"]})

    def imagine_intent(self):
        """POST /api/imagine/intent {text, model, quick, where}: does this chat message ask for a picture? Answer: {image, subject, via}.
        A clear request (rules "yes") is painted without asking anyone. Any other message is put to the chat model when pictures
        are set up (and `ai_image_detect` is on): a short YES/NO question about the last message only (`via` "model"); only
        YES makes a picture. Without that, or when the model does not answer in time, is busy with other requests or fails,
        the message is a normal one (`via` "rules"). `quick` skips the model."""
        d = self.body()
        text = self.text(d, "text").strip()
        verdict = intent.classify(text)
        out = {"image": verdict == "yes", "via": "rules"}
        s = self.app.settings()
        ready = s["image_gen"] != "off" and not sdcpp.status(self.app.data_dir, s)["problem"]
        if verdict != "yes" and ready and s["ai_image_detect"] and not self.flag(d, "quick") and 2 < len(text) <= intent.MAX_LENGTH:
            answer = self.app.ask_intent(d.get("model") or s["default_model"], text)
            if answer is not None:
                out.update(image=answer, via="model")
        out["subject"] = intent.subject(text) if out["image"] else ""
        where = self.text(d, "where").strip()[:20] or "chat"
        log_image.info("Picture request check (%s): %s (%s%s)", where, "recognised" if out["image"] else "not a picture request", out["via"],
                       "" if ready else ", pictures are not set up")
        self.send_json(out)

    def imagine(self):
        """POST /api/imagine {session_id, prompt, negative, aspect, seed, improve, model, fallback}: make a
        picture with the image generator and store it in the chat (user message = prompt, assistant message
        = picture). With `improve` the prompt is a request in the user's words ("make me a picture of ..."):
        the chat model `model` first turns it into a prompt for the image model (`fallback`, the plain
        description, is used when that fails). Both steps wait their turn in the queues (jobqueue.py).
        Events: start, status, queued {position}, prompt {prompt}, progress {p (0..1 or null)}, done | error.
        Closing the connection stops the backend."""
        d = self.body()
        db = self.app.db
        s = self.app.settings()
        cfg = imagegen.config(s)
        if cfg["type"] == "off":
            raise ValueError("No image generator is set up. Choose one in Settings → Image generation.")
        session = db.get_session(str(d.get("session_id") or ""))
        if not session:
            return self.error("Session not found", 404)
        request = self.text(d, "prompt").strip()
        if not request:
            raise ValueError("Describe the picture first")
        if len(request) > 4000:
            raise ValueError("The description is too long")
        improve = self.flag(d, "improve")
        prov = model = None
        if improve:
            model_id = d.get("model") or session["model"]
            try:
                prov, model = self.app.resolve(model_id)
            except providers.ProviderError:
                prov = None  # no chat model: the description goes to the image model as it is
        negative = self.text(d, "negative").strip()[:2000]
        aspect = self.text(d, "aspect", "square")
        if aspect == "auto":
            aspect = imagegen.aspect_from_text(request)
        if aspect not in imagegen.ASPECTS:
            raise ValueError("aspect must be one of: " + ", ".join(imagegen.ASPECTS))
        seed = d.get("seed")
        if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2 ** 32):
            raise ValueError("seed must be a whole number from 0 to 4294967295")
        if seed is None:
            seed = random.randrange(2 ** 32)
        width, height = imagegen.dimensions(aspect, s["image_gen_size"])
        sid = session["id"]
        imagine_meta = {"aspect": aspect, **({"negative": negative} if negative else {}), **({"improved": True} if improve else {})}
        db.add_message(sid, "user", request, meta={"imagine": imagine_meta})
        title = session["title"]
        if title == "New chat":
            title = (request[:55] + "…") if len(request) > 56 else request
            db.update_session(sid, title=title)
        self.start_stream()
        self.emit({"type": "start", "title": title})
        gone = threading.Event()

        def progress(p):
            if gone.is_set():
                return
            try:
                self.emit({"type": "progress", "p": p})
            except OSError:  # the browser went away (Stop button)
                gone.set()

        prompt = request
        began = time.monotonic()
        log_image.info("Picture requested (%s, %s%s)", cfg["type"], aspect, ", prompt improved by the chat model" if improve else "")
        if improve and prov is not None:
            fallback = self.text(d, "fallback").strip()[:4000] or request
            prompt = fallback
            try:
                self.emit({"type": "status", "t": "Improving the description for the image model…"})
                answer = providers.chat_once(prov, model, imagegen.improve_messages(request), {"temperature": 0.7})
                prompt = imagegen.clean_prompt(answer, fallback)
                log_image.info("Prompt written by %s::%s in %.1fs%s", prov["id"], model, time.monotonic() - began,
                               "" if prompt != fallback else " (not usable, the plain description is used)")
            except providers.ProviderError as e:
                log_image.warning("Prompt improvement failed (%s), the plain description is used", str(e)[:200])
            except OSError:  # the browser went away while waiting
                return
        elif improve:
            prompt = self.text(d, "fallback").strip()[:4000] or request
        try:
            self.emit({"type": "prompt", "prompt": prompt})
            self.emit({"type": "status", "t": "Painting the picture…"})
        except OSError:
            return

        painting = time.monotonic()
        try:
            with jobqueue.slot("image"):
                painting = time.monotonic()
                if cfg["type"] == "local":
                    data, info = sdcpp.generate(self.app.data_dir, cfg["model"], prompt, negative,
                                                lambda size: imagegen.dimensions(aspect, size), seed,
                                                progress=progress, cancelled=gone.is_set)
                else:
                    data, info = imagegen.generate(cfg, prompt, negative, width, height, s["image_gen_steps"], seed,
                                                   progress=progress, cancelled=gone.is_set)
            name = images.store(self.app.user_dir, data)
        except jobqueue.Cancelled:
            return
        except jobqueue.Timeout:
            return self.emit({"type": "error", "error": "The image generator was busy with other requests for too long. Please try again."})
        except (imagegen.ImageGenError, sdcpp.SdError, ValueError) as e:
            if gone.is_set():
                log_image.info("Picture stopped by the user after %.1fs", time.monotonic() - painting)
                return
            log_image.warning("Picture failed after %.1fs: %s", time.monotonic() - painting, str(e)[:300])
            return self.emit({"type": "error", "error": str(e)})
        log_image.info("Picture done in %.1fs (%dx%d, %s, %s)", time.monotonic() - painting, info.get("width", 0), info.get("height", 0),
                       info.get("steps", "?"), info.get("model") or cfg["type"])
        info["prompt"] = prompt
        if improve:
            info["request"] = request
        if negative:
            info["negative"] = negative
        text = f"[Picture made with {imagegen.BACKENDS.get(cfg['type'], 'stable-diffusion.cpp')}{' (' + info['model'] + ')' if info['model'] else ''}: {prompt}]"
        try:
            db.add_message(sid, "assistant", text, "", {"images": [name], "imagegen": info})
        except sqlite3.IntegrityError:  # the chat was deleted meanwhile
            return
        if not gone.is_set():
            try:
                self.emit({"type": "done", "image": name, "info": info})
            except OSError:
                pass

    def transcribe(self):
        """POST /api/transcribe {audio (base64 WAV)}: speech to text with the local Whisper server."""
        url = self.app.settings()["whisper_url"]
        if not url:
            raise ValueError("No Whisper server set up. Add its address in Settings → Voice.")
        d = self.body()
        audio = self.text(d, "audio")
        try:
            wav = base64.b64decode(audio, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("Upload is damaged, please try again") from None
        s = self.app.settings()
        self.send_json({"text": speech.transcribe(url, wav, s["whisper_model"], self.text(d, "language"))})

    def extract_file(self):
        """POST /api/extract {name, data}: plain text of a file, for attaching it to a chat message."""
        name, _, text = self.file_upload()
        self.send_json({"name": name, "text": text})

    # mail
    def query(self, key, default=""):
        """One query-string parameter."""
        return parse_qs(urlparse(self.path).query).get(key, [default])[0]

    # calendar -------------------------------------------------------
    def calendar_info(self):
        """GET /api/calendar: the calendars (Sunak's own first, no passwords), CalDAV presets and the linked
        mail accounts with the matching CalDAV preset."""
        def preset(a):  # by address, else by mail server (own domain at GMX, iCloud…)
            return mail.preset_for(a["email"]) or next((k for k, p in mail.PRESETS.items() if p["imap_host"] == a.get("imap_host")), "")
        mails = [{"id": a["id"], "email": a["email"], "preset": preset(a)} for a in self.app.mail_accounts()]
        self.send_json({"sources": [self.app.LOCAL_CALENDAR] + [cal.public(c) for c in self.app.calendars()],
                        "presets": cal.PRESETS, "ics_only": cal.ICS_ONLY, "mail_accounts": mails})

    def calendar_save_source(self):
        """POST /api/calendar/sources {source}: add or change a calendar account. CalDAV calendars are looked
        up on the server (which ones are shown is kept); an ICS address is read once to check it."""
        sources = self.app.calendars()
        mails = self.app.mail_accounts()
        src = cal.clean_source(self.body().get("source"), sources, mails)
        sent = {c["href"]: c for c in src.get("calendars", [])}
        try:
            if src["type"] == "caldav":
                user, pw = cal.login(src, mails)
                if not pw:
                    raise ValueError("Enter the password (or an app password)")
                src["calendars"] = [dict(c, enabled=sent.get(c["href"], {}).get("enabled", True))
                                    for c in cal.discover(src["url"], user, pw)]
            else:
                cal.forget_ics(src["url"])
                cal.fetch_ics(src["url"])
        except cal.CalendarError as e:
            raise ValueError(str(e)) from None
        sources = [src if c["id"] == src["id"] else c for c in sources]
        if not any(c["id"] == src["id"] for c in sources):
            sources.append(src)
        self.app.db.set_setting("calendars", sources)
        self.send_json(cal.public(src))

    def calendar_delete_source(self, sid):
        """DELETE /api/calendar/sources/<id>: remove a calendar account (nothing on its server changes)."""
        self.app.db.set_setting("calendars", [c for c in self.app.calendars() if c["id"] != sid])
        self.send_json({"ok": True})

    def calendar_range(self):
        start, end = (self.query(k) for k in ("start", "end"))
        try:
            start, end = (datetime.datetime.fromisoformat(v.replace("Z", "+00:00")) for v in (start, end))
        except ValueError:
            raise ValueError("start and end must be ISO date-times with a time zone") from None
        if start.tzinfo is None or end.tzinfo is None or not start < end:
            raise ValueError("start and end must be ISO date-times with a time zone, start before end")
        if end - start > datetime.timedelta(days=cal.MAX_RANGE_DAYS):
            raise ValueError("At most about a year at once")
        return start, end

    def calendar_events(self):
        """GET /api/calendar/events?start=…&end=… (ISO with the device's offset): the events of all shown
        calendars in that span, recurring ones expanded. A calendar that fails is listed in `errors`."""
        start, end = self.calendar_range()
        events, errors = self.app.calendar_load(start, end)
        self.send_json({"events": events, "errors": errors})

    def calendar_target(self, d):
        """(source, user, password) of the calendar an event belongs to ("local": (None, None, None))."""
        sid = d.get("source") or "local"
        if sid == "local":
            return None, None, None
        src = next((c for c in self.app.calendars() if c["id"] == sid), None)
        if not src:
            raise ValueError("That calendar no longer exists. Reload the page.")
        if src["type"] != "caldav":
            raise ValueError("Subscribed calendars (ICS) are read-only")
        user, pw = cal.login(src, self.app.mail_accounts())
        return src, user, pw

    def calendar_create(self):
        """POST /api/calendar/events {source, calendar (CalDAV collection), event}: create an event."""
        d = self.body()
        ev = cal.clean_event(d.get("event"))
        src, user, pw = self.calendar_target(d)
        uid = cal.new_uid()
        text = cal.build_event(uid, ev["summary"], ev["start"], ev["end"], ev["all_day"], ev["location"], ev["description"], ev["repeat"], ev.get("reminder"))
        if src is None:
            self.app.db.cal_put(uid, text)
        else:
            coll = d.get("calendar")
            if not any(c["href"] == coll for c in src.get("calendars", [])):
                raise ValueError("Pick one of the calendars of this account")
            try:
                cal.caldav_put(coll.rstrip("/") + "/" + uid.replace("@", "-") + ".ics", user, pw, text)
            except cal.CalendarError as e:
                raise ValueError(str(e)) from None
        self.app.reminders.invalidate(self.app.profile)
        self.send_json({"ok": True, "uid": uid})

    def calendar_update(self):
        """PUT /api/calendar/events {source, uid, href, etag, recurring, event}: change an event. For a
        repeating one only title, place and notes change (the times belong to the whole series)."""
        d = self.body()
        ev = cal.clean_event(d.get("event"))
        uid = d.get("uid")
        if not isinstance(uid, str) or not uid:
            raise ValueError("uid is missing")
        src, user, pw = self.calendar_target(d)
        times = not d.get("recurring")
        try:
            if src is None:
                text = self.app.db.cal_get(uid)
                if text is None:
                    raise ValueError("The event was not found any more. Reload the calendar.")
                self.app.db.cal_put(uid, cal.update_event(text, uid, ev, times))
            else:
                href = self.calendar_href(src, d.get("href"))
                _, text = cal.caldav_get(href, user, pw)
                cal.caldav_put(href, user, pw, cal.update_event(text, uid, ev, times), d.get("etag") or None)
        except cal.CalendarError as e:
            raise ValueError(str(e)) from None
        self.app.reminders.invalidate(self.app.profile)
        self.send_json({"ok": True})

    def calendar_href(self, src, href):
        """An event address must lie inside one of the account's calendars (never another server)."""
        if not isinstance(href, str) or "/.." in href or "\\" in href or \
                not any(href.startswith(c["href"].rstrip("/") + "/") and href != c["href"] for c in src.get("calendars", [])):
            raise ValueError("Unknown event address. Reload the calendar.")
        return href

    def calendar_delete(self):
        """POST /api/calendar/events/delete {source, uid, href, etag}: delete an event (a repeating one
        with all its dates)."""
        d = self.body()
        src, user, pw = self.calendar_target(d)
        if src is None:
            self.app.db.cal_delete(str(d.get("uid") or ""))
        else:
            try:
                cal.caldav_delete(self.calendar_href(src, d.get("href")), user, pw, d.get("etag") or None)
            except cal.CalendarError as e:
                raise ValueError(str(e)) from None
        self.app.reminders.invalidate(self.app.profile)
        self.send_json({"ok": True})

    def reminders_poll(self):
        """GET /api/reminders: the calendar reminders of this profile that are due and that no page has been given yet,
        as {items}. Each reminder is handed out once."""
        self.send_json({"items": self.app.reminders.page_items(self.app, self.app.profile)})

    def reminders_test(self):
        """POST /api/reminders/test {ntfy_url, ntfy_topic, lang} (all optional, else the saved ones): send a test push
        message to the ntfy topic, if there is one. The page shows its own test notification. The server address is
        a setting of the installation: only admins may try another one than the saved one."""
        d = self.body()
        s = self.app.settings()
        url = _check_pref("ntfy_url", d.get("ntfy_url", s["ntfy_url"]), "") if self.profile.get("admin") else s["ntfy_url"]
        topic = _check_pref("ntfy_topic", d.get("ntfy_topic", s["ntfy_topic"]), "")
        lang = _check_pref("reminder_lang", d.get("lang", s["reminder_lang"]), "")
        text = reminders.TEXTS[lang]
        if topic:
            log.add_secret(topic)
            reminders.send_ntfy(url, topic, text["test_title"], text["test"])
        self.send_json({"ok": True, "pushed": bool(topic), "title": text["test_title"], "text": text["test"]})

    def calendar_parse(self):
        """POST /api/calendar/parse {text, now (device time with offset), model}: the model reads an event
        out of a sentence or an e-mail; the answer fills the event form (nothing is saved)."""
        d = self.body()
        text = d.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Type what the event is, e.g. “Dentist next Tuesday 10am”")
        try:
            now = datetime.datetime.fromisoformat(str(d.get("now") or "").replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("now must be an ISO date-time") from None
        if now.tzinfo is None:
            raise ValueError("now needs a time zone")
        prov, model = self.app.resolve(d.get("model"))
        answer = providers.chat_once(prov, model, cal.parse_messages(text.strip()[:20000], now), {"temperature": 0})
        self.send_json(cal.parse_answer(answer, now))

    def mail_list_accounts(self):
        """GET /api/mail/accounts: linked accounts without passwords, and the provider presets."""
        self.send_json({"accounts": [mail.public(a) for a in self.app.mail_accounts()], "presets": mail.PRESETS})

    def mail_save_account(self):
        """POST /api/mail/accounts {account}: add an account, or update the one with the same id.
        An empty password keeps the saved one (same user name and servers only)."""
        accounts = self.app.mail_accounts()
        acc = mail.clean_account(self.body().get("account"), accounts, new_id)
        if any(a["email"].lower() == acc["email"].lower() and a["id"] != acc["id"] for a in accounts):
            raise ValueError(f"{acc['email']} is already linked")
        if any(a["id"] == acc["id"] for a in accounts):
            accounts = [acc if a["id"] == acc["id"] else a for a in accounts]
        else:
            accounts.append(acc)
        self.app.db.set_setting("mail_accounts", accounts)
        self.send_json(mail.public(acc))

    def mail_delete_account(self, aid):
        """DELETE /api/mail/accounts/<id>: unlink an account (nothing on the mail server changes)."""
        self.app.db.set_setting("mail_accounts", [a for a in self.app.mail_accounts() if a["id"] != aid])
        self.send_json({"ok": True})

    def mail_test(self):
        """POST /api/mail/test {account}: try IMAP and SMTP with the settings from the form, before saving."""
        acc = mail.clean_account(self.body().get("account"), self.app.mail_accounts())
        self.send_json(mail.test_account(acc))

    def mail_folders(self, aid):
        """GET /api/mail/<id>/folders"""
        self.send_json(mail.list_folders(self.app.mail_account(aid)))

    def mail_messages(self, aid):
        """GET /api/mail/<id>/messages?folder=&q=&unread=1&before=<uid>: newest messages, read-only."""
        before = self.query("before")
        self.send_json(mail.list_messages(self.app.mail_account(aid), self.query("folder", "INBOX"), self.query("q"),
                                          self.query("unread") == "1", int(before) if before.isdigit() else None))

    def mail_message(self, aid):
        """GET /api/mail/<id>/message?folder=&uid=: one message as text (not marked as read)."""
        uid = self.query("uid")
        if not uid.isdigit():
            raise ValueError("uid missing")
        self.send_json(mail.get_message(self.app.mail_account(aid), self.query("folder", "INBOX"), int(uid)))

    def mail_attachment(self, aid):
        """GET /api/mail/<id>/attachment?folder=&uid=&i=: download one attachment."""
        uid, i = self.query("uid"), self.query("i")
        if not uid.isdigit() or not i.isdigit():
            raise ValueError("uid and i are needed")
        name, data = mail.get_attachment(self.app.mail_account(aid), self.query("folder", "INBOX"), int(uid), int(i))
        name = re.sub(r"[\\/\x00-\x1f]", "_", name)[-200:] or "attachment"
        self.send_download(data, name, "application/octet-stream")  # never shown inline in the browser

    def mail_send(self, aid):
        """POST /api/mail/<id>/send {to, cc, bcc, subject, body, in_reply_to, references, attachments: [{name, data
        (base64)}], forward: {folder, uid, attachments: [index]}}: only on the Send click."""
        self.send_json(mail.send(self.app.mail_account(aid), self.body()))

    def mail_draft(self, aid):
        """POST /api/mail/<id>/draft {…same as send}: save in the Drafts folder."""
        self.send_json({"ok": True, "folder": mail.save_draft(self.app.mail_account(aid), self.body())})

    def mail_move(self, aid):
        """POST /api/mail/<id>/move {folder, uids, target}: move messages to another folder."""
        d = self.body()
        uids = d.get("uids") if isinstance(d.get("uids"), list) else []
        self.send_json({"ok": True, "folder": mail.move(self.app.mail_account(aid), self.text(d, "folder"), uids,
                                                        self.text(d, "target"))})

    def mail_delete(self, aid):
        """POST /api/mail/<id>/delete {folder, uids, permanent}: into the Trash; for good only from the Trash
        (or without one) and with permanent: true, which the page asks for first."""
        d = self.body()
        uids = d.get("uids") if isinstance(d.get("uids"), list) else []
        self.send_json(dict(mail.delete(self.app.mail_account(aid), self.text(d, "folder"), uids,
                                        d.get("permanent") is True), ok=True))

    def mail_new(self):
        """GET /api/mail/new: unread mail in the Inbox of every account (for the new-mail notice), read-only.
        An account that cannot be reached gets an error instead."""
        def one(acc):
            try:
                return dict(mail.check_new(acc), id=acc["id"], email=acc["email"], error="")
            except mail.MailError as e:
                return {"id": acc["id"], "email": acc["email"], "error": str(e)}
        accounts = self.app.mail_accounts()
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.send_json({"accounts": list(pool.map(one, accounts))})

    def mail_ai(self):
        """POST /api/mail/ai {task: summarize|reply|overview, text, instruction, account, model}: stream the result.
        Nothing is sent: a reply only fills the compose form."""
        d = self.body()
        text = d.get("text") if isinstance(d.get("text"), str) else ""
        if not text.strip():
            raise ValueError("No e-mail to work with")
        instruction = d.get("instruction") if isinstance(d.get("instruction"), str) else ""
        acc = self.app.mail_account(d["account"]) if d.get("account") else None
        memories = self.app.db.memories() if self.app.settings()["use_memory"] else []
        messages = mail.ai_messages(d.get("task"), acc, text[:40000], instruction.strip()[:2000], memories)
        prov, model = self.app.resolve(d.get("model"))
        self.start_stream()
        try:
            for kind, c in providers.chat_stream(prov, model, messages, {"temperature": 0.3}):
                self.emit({"type": kind, "t": c})
            self.emit({"type": "done"})
        except providers.ProviderError as e:
            self.emit({"type": "error", "error": str(e)})

    # model management (Ollama)
    def pull(self):
        """POST /api/models/pull: download an Ollama model and stream its progress.

        Progress of all layers is summed so the bar moves smoothly from 0 to 100 %.
        Closing the request (Cancel in the UI) stops the download; Ollama resumes it next time."""
        d = self.body()
        prov = self.app.provider(d["provider"]) if d.get("provider") else self.app.ollama_provider()
        if prov["type"] != "ollama":
            raise ValueError("Downloading models only works with Ollama")
        name = self.text(d, "model").strip()
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
        self.send_json(ollama.status(self.app.ollama_provider(), self.app.ram, self.app.gpu))

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
        try:
            for line in proc.stdout:
                if line.strip():
                    self.emit({"type": "status", "t": line.rstrip()[-300:]})
        except OSError:  # the browser went away: let the installer finish on its own, don't block it
            threading.Thread(target=lambda: (proc.stdout.read(), proc.wait()), daemon=True).start()
            raise
        if proc.wait() != 0:
            return self.emit({"type": "error", "error": f"Installer exited with code {proc.returncode}"})
        self.emit({"type": "done"})

    def delete_model(self):
        """POST /api/models/delete: remove an Ollama model from disk."""
        d = self.body()
        if not self.text(d, "model"):
            raise ValueError("Which model? Send {\"model\": \"ollama::name\"}")
        prov, model = self.app.resolve(d["model"])
        if prov["type"] != "ollama":
            raise ValueError("Deleting models only works with Ollama")
        providers.ollama_delete(prov, model)
        self.send_json({"ok": True})


ID = r"([a-f0-9]{16})"
ROUTES = [
    (r"/api/profiles", "POST", Handler.profile_create),
    (r"/api/profiles/([a-z0-9]{1,16})", "PATCH", Handler.profile_update),
    (r"/api/profiles/([a-z0-9]{1,16})", "DELETE", Handler.profile_delete),
    (r"/api/settings", "GET", Handler.get_settings),
    (r"/api/settings", "PUT", Handler.put_settings),
    (r"/api/update", "GET", Handler.update_get),
    (r"/api/update", "POST", Handler.update_apply),
    (r"/api/update/check", "POST", Handler.update_check),
    (r"/api/usage", "GET", Handler.usage_get),
    (r"/api/reports", "GET", Handler.reports_get),
    (r"/api/reports/token", "POST", Handler.reports_token),
    (r"/api/reports/check", "POST", Handler.reports_check),
    (r"/api/reports/send", "POST", Handler.reports_send),
    (r"/api/reports/dismiss", "POST", Handler.reports_dismiss),
    (r"/api/reports/sample", "POST", Handler.reports_sample),
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
    (rf"/api/sessions/{ID}/export", "GET", Handler.export_session),
    (r"/api/search", "GET", Handler.search),
    (r"/api/export", "GET", Handler.export_all),
    (r"/api/import", "POST", Handler.import_data),
    (r"/api/chat", "POST", Handler.chat),
    (r"/api/lan", "GET", Handler.lan_get),
    (r"/api/lan", "POST", Handler.lan_set),
    (r"/api/images/([a-f0-9]{16}\.(?:png|jpg|gif|webp))", "GET", Handler.get_image),
    (r"/api/tools", "POST", Handler.tools_chat),
    (r"/api/tools/confirm", "POST", Handler.tools_confirm),
    (r"/api/tools/cancel", "POST", Handler.tools_cancel),
    (r"/api/tools/revoke", "POST", Handler.tools_revoke),
    (r"/api/mcp/test", "POST", Handler.mcp_test),
    (r"/api/compare", "POST", Handler.compare),
    (r"/api/research", "POST", Handler.research),
    (r"/api/documents", "GET", Handler.list_documents),
    (r"/api/documents", "POST", Handler.create_document),
    (r"/api/documents/ai", "POST", Handler.document_ai),
    (rf"/api/documents/{ID}", "GET", Handler.get_document),
    (rf"/api/documents/{ID}", "PUT", Handler.put_document),
    (rf"/api/documents/{ID}", "DELETE", Handler.delete_document),
    (r"/api/knowledge", "GET", Handler.kb_list),
    (r"/api/knowledge", "POST", Handler.kb_upload),
    (r"/api/knowledge/search", "GET", Handler.kb_search),
    (rf"/api/knowledge/{ID}", "GET", Handler.kb_get),
    (rf"/api/knowledge/{ID}", "DELETE", Handler.kb_delete),
    (r"/api/extract", "POST", Handler.extract_file),
    (r"/api/transcribe", "POST", Handler.transcribe),
    (r"/api/assistant/intent", "POST", Handler.assistant_intent),
    (r"/api/assistant/mail", "POST", Handler.assistant_mail),
    (r"/api/assistant/check", "POST", Handler.assistant_check),
    (r"/api/imagine/intent", "POST", Handler.imagine_intent),
    (r"/api/imagine", "POST", Handler.imagine),
    (r"/api/imagegen/test", "POST", Handler.imagegen_test),
    (r"/api/imagegen/local", "GET", Handler.local_images),
    (r"/api/imagegen/engine", "GET", Handler.engine_options),
    (r"/api/imagegen/engine/install", "POST", Handler.engine_install),
    (r"/api/imagegen/engine/remove", "POST", Handler.engine_remove),
    (r"/api/imagegen/models/pull", "POST", Handler.image_model_pull),
    (r"/api/imagegen/models/delete", "POST", Handler.image_model_delete),
    (r"/api/models/search", "GET", Handler.model_search),
    (r"/api/models/files", "GET", Handler.model_files),
    (r"/api/calendar", "GET", Handler.calendar_info),
    (r"/api/calendar/sources", "POST", Handler.calendar_save_source),
    (r"/api/calendar/sources/([a-f0-9]{12})", "DELETE", Handler.calendar_delete_source),
    (r"/api/calendar/events", "GET", Handler.calendar_events),
    (r"/api/calendar/events", "POST", Handler.calendar_create),
    (r"/api/calendar/events", "PUT", Handler.calendar_update),
    (r"/api/calendar/events/delete", "POST", Handler.calendar_delete),
    (r"/api/reminders", "GET", Handler.reminders_poll),
    (r"/api/reminders/test", "POST", Handler.reminders_test),
    (r"/api/calendar/parse", "POST", Handler.calendar_parse),
    (r"/api/mail/accounts", "GET", Handler.mail_list_accounts),
    (r"/api/mail/accounts", "POST", Handler.mail_save_account),
    (rf"/api/mail/accounts/{ID}", "DELETE", Handler.mail_delete_account),
    (r"/api/mail/test", "POST", Handler.mail_test),
    (r"/api/mail/ai", "POST", Handler.mail_ai),
    (rf"/api/mail/{ID}/folders", "GET", Handler.mail_folders),
    (rf"/api/mail/{ID}/messages", "GET", Handler.mail_messages),
    (rf"/api/mail/{ID}/message", "GET", Handler.mail_message),
    (rf"/api/mail/{ID}/attachment", "GET", Handler.mail_attachment),
    (rf"/api/mail/{ID}/send", "POST", Handler.mail_send),
    (rf"/api/mail/{ID}/draft", "POST", Handler.mail_draft),
    (rf"/api/mail/{ID}/move", "POST", Handler.mail_move),
    (rf"/api/mail/{ID}/delete", "POST", Handler.mail_delete),
    (r"/api/mail/new", "GET", Handler.mail_new),
    (r"/api/notes", "GET", Handler.list_notes),
    (r"/api/notes", "POST", Handler.create_note),
    (rf"/api/notes/{ID}", "PATCH", Handler.patch_note),
    (rf"/api/notes/{ID}", "DELETE", Handler.delete_note),
    (rf"/api/sessions/{ID}/remember", "POST", Handler.remember),
]


# what only admin profiles may do: things that change the installation or reach beyond one profile's data
ADMIN_ONLY = {(m, p) for p, m, _ in ROUTES if (m, p) in {
    ("POST", r"/api/profiles"), ("DELETE", r"/api/profiles/([a-z0-9]{1,16})"), ("POST", r"/api/update"), ("POST", r"/api/update/check"),
    ("GET", r"/api/reports"), ("POST", r"/api/reports/token"), ("POST", r"/api/reports/check"), ("POST", r"/api/reports/send"),
    ("POST", r"/api/reports/dismiss"), ("POST", r"/api/reports/sample"),
    ("POST", r"/api/models/pull"), ("POST", r"/api/models/delete"), ("POST", r"/api/ollama/start"),
    ("POST", r"/api/ollama/install"), ("POST", r"/api/lan"), ("POST", r"/api/tools"), ("POST", r"/api/tools/confirm"),
    ("POST", r"/api/mcp/test"), ("POST", r"/api/imagegen/test"), ("GET", r"/api/imagegen/engine"),
    ("POST", r"/api/imagegen/engine/install"), ("POST", r"/api/imagegen/engine/remove"),
    ("POST", r"/api/imagegen/models/pull"), ("POST", r"/api/imagegen/models/delete")}}


def make_server(host, port, data_dir):
    """Create a threaded HTTP server bound to host:port with its own App for `data_dir`."""
    app = App(data_dir)
    reports.attach(app)
    handler = type("BoundHandler", (Handler,), {"app": app})
    srv = Server((host, port), handler)
    app.host, app.port, app.handler = host, srv.server_address[1], handler
    return srv
