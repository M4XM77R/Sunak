"""Native Ollama integration: model catalog, finding / starting / installing
the local Ollama, and its status."""

import os
import platform
import shutil
import subprocess
import time
import urllib.parse
from pathlib import Path

from . import providers

# Curated starter models (Ollama tags). size_gb is the approximate download size.
CATALOG = [
    {"name": "qwen3:1.7b", "title": "Qwen3 1.7B", "size_gb": 1.4, "tags": ["chat", "reasoning"],
     "description": "Tiny and fast. Runs on almost any computer."},
    {"name": "qwen3:4b", "title": "Qwen3 4B", "size_gb": 2.6, "tags": ["chat", "reasoning"],
     "description": "Best small all-rounder, thinks before answering."},
    {"name": "qwen3:8b", "title": "Qwen3 8B", "size_gb": 5.2, "tags": ["chat", "reasoning"],
     "description": "Great everyday model for 16 GB RAM."},
    {"name": "qwen3:14b", "title": "Qwen3 14B", "size_gb": 9.3, "tags": ["chat", "reasoning"],
     "description": "Smarter answers, needs a strong machine."},
    {"name": "qwen3:30b", "title": "Qwen3 30B (MoE)", "size_gb": 19, "tags": ["chat", "reasoning"],
     "description": "Large mixture-of-experts model, surprisingly fast."},
    {"name": "gemma3:1b", "title": "Gemma 3 1B", "size_gb": 0.8, "tags": ["chat"],
     "description": "Google's smallest model. Very light."},
    {"name": "gemma3:4b", "title": "Gemma 3 4B", "size_gb": 3.3, "tags": ["chat"],
     "description": "Friendly writer, good in many languages."},
    {"name": "gemma3:12b", "title": "Gemma 3 12B", "size_gb": 8.1, "tags": ["chat"],
     "description": "Strong writing and multilingual quality."},
    {"name": "gemma3:27b", "title": "Gemma 3 27B", "size_gb": 17, "tags": ["chat"],
     "description": "Google's largest open Gemma 3."},
    {"name": "llama3.2:3b", "title": "Llama 3.2 3B", "size_gb": 2.0, "tags": ["chat"],
     "description": "Meta's compact model, quick replies."},
    {"name": "llama3.1:8b", "title": "Llama 3.1 8B", "size_gb": 4.9, "tags": ["chat"],
     "description": "Popular, well-rounded 8B model."},
    {"name": "phi4-mini", "title": "Phi-4 mini", "size_gb": 2.5, "tags": ["chat", "reasoning"],
     "description": "Microsoft's small model, good at logic and math."},
    {"name": "phi4", "title": "Phi-4 14B", "size_gb": 9.1, "tags": ["chat", "reasoning"],
     "description": "Microsoft's 14B model, strong reasoning."},
    {"name": "mistral", "title": "Mistral 7B", "size_gb": 4.1, "tags": ["chat"],
     "description": "Classic fast 7B model."},
    {"name": "deepseek-r1:8b", "title": "DeepSeek-R1 8B", "size_gb": 5.2, "tags": ["reasoning"],
     "description": "Reasoning model that shows its thinking."},
    {"name": "deepseek-r1:14b", "title": "DeepSeek-R1 14B", "size_gb": 9.0, "tags": ["reasoning"],
     "description": "Bigger reasoning model for hard problems."},
    {"name": "qwen2.5-coder:7b", "title": "Qwen2.5 Coder 7B", "size_gb": 4.7, "tags": ["coding"],
     "description": "Writes and explains code."},
    {"name": "qwen2.5-coder:14b", "title": "Qwen2.5 Coder 14B", "size_gb": 9.0, "tags": ["coding"],
     "description": "Stronger coding assistant."},
    {"name": "gpt-oss:20b", "title": "gpt-oss 20B", "size_gb": 14, "tags": ["chat", "reasoning"],
     "description": "OpenAI's open-weight model, needs 16 GB+ VRAM or lots of RAM."},
]


def fits(size_gb, ram_gb):
    """True when a model of `size_gb` should run comfortably with `ram_gb` of memory."""
    return ram_gb is None or ram_gb >= size_gb * 1.3 + 2


def catalog(ram_gb):
    """The catalog with a `fits` flag for this machine."""
    return [dict(m, fits=fits(m["size_gb"], ram_gb)) for m in CATALOG]


def find_binary():
    """Path of the ollama executable, or None."""
    found = shutil.which("ollama")
    if found:
        return found
    candidates = [
        "/usr/local/bin/ollama",
        "/opt/homebrew/bin/ollama",
        "/Applications/Ollama.app/Contents/Resources/ollama",
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"),
    ]
    return next((c for c in candidates if c and Path(c).is_file()), None)


def is_local(provider):
    """True when the provider points at this computer (only then Sunak can start Ollama)."""
    host = urllib.parse.urlparse(provider["base_url"]).hostname or ""
    return host in ("localhost", "127.0.0.1", "::1")


def install_method():
    """How Ollama can be installed on this machine: (method, command shown to the user)."""
    system = platform.system()
    if system == "Windows" and shutil.which("winget"):
        return "winget", "winget install -e --id Ollama.Ollama"
    if system == "Darwin":
        if shutil.which("brew"):
            return "brew", "brew install ollama"
        return "download", "https://ollama.com/download/mac"
    if system == "Linux":
        return "script", "curl -fsSL https://ollama.com/install.sh | sh"
    return "download", "https://ollama.com/download"


def install_command(method):
    """Argument list for methods Sunak can run itself (no admin password needed)."""
    if method == "winget":
        return ["winget", "install", "-e", "--id", "Ollama.Ollama",
                "--accept-package-agreements", "--accept-source-agreements"]
    if method == "brew":
        return ["brew", "install", "ollama"]
    return None


def status(provider, ram_gb):
    """Everything the Models page needs in one call."""
    binary = find_binary()
    method, command = install_method()
    out = {
        "base_url": provider["base_url"],
        "local": is_local(provider),
        "installed": bool(binary),
        "running": False,
        "version": None,
        "models": [],
        "install": {"method": method, "command": command, "automatic": install_command(method) is not None},
        "ram_gb": ram_gb,
        "catalog": catalog(ram_gb),
    }
    try:
        out["version"] = providers.ollama_version(provider)
        out["running"] = True
        out["installed"] = True
        out["models"] = providers.ollama_tags(provider)
    except providers.ProviderError:
        pass
    return out


def start(provider, timeout=15):
    """Start the local Ollama server in the background and wait until it answers."""
    if not is_local(provider):
        raise providers.ProviderError("Ollama runs on another computer. Start it there.")
    binary = find_binary()
    if not binary:
        raise providers.ProviderError("Ollama is not installed yet.")
    app = Path("/Applications/Ollama.app")
    if platform.system() == "Darwin" and app.exists():
        subprocess.Popen(["open", "-a", str(app)])
    else:
        env = dict(os.environ)
        port = urllib.parse.urlparse(provider["base_url"]).port or 11434
        env["OLLAMA_HOST"] = f"127.0.0.1:{port}"
        kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL, "env": env}
        if platform.system() == "Windows":
            kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen([binary, "serve"], **kwargs)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            return providers.ollama_version(provider)
        except providers.ProviderError:
            time.sleep(0.5)
    raise providers.ProviderError("Ollama did not start. Try starting the Ollama app yourself.")
