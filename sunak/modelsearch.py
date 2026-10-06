"""Model search beyond Sunak's own catalogs: the Ollama library (ollama.com) and Hugging Face. Only used when
the user searches; every function raises SearchError when the site cannot be reached, and the page then
quietly shows just the local results."""

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request

OLLAMA_WEB = "https://ollama.com"
HF = "https://huggingface.co"
UA = "Sunak model search"
QUANT_RE = re.compile(r"(?:^|[-_.])((?:I?Q\d(?:_[A-Z0-9]+)*)|BF16|F16|F32)(?=[-_.]|$)", re.I)
SPLIT_RE = re.compile(r"-\d{5}-of-\d{5}\.gguf$", re.I)
REPO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*")
MAX_RESULTS = 20


class SearchError(Exception):
    pass


def _get(url, timeout=12, limit=4 * 1024 * 1024):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json, text/html"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(limit).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise SearchError(str(getattr(e, "reason", e))) from None


def _json(url):
    try:
        return json.loads(_get(url))
    except ValueError:
        raise SearchError("unexpected answer") from None


def _text(fragment):
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def approx_gb(params):
    """Rough download size of a 4-bit model with `params` like '8b', '1.5b', '270m'."""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([bm])", params.lower())
    if not m:
        return None
    billions = float(m.group(1)) / (1000 if m.group(2) == "m" else 1)
    return round(billions * 0.6 + 0.3, 1)


def ollama_search(query):
    """Models of the Ollama library matching `query`: [{name, description, sizes, capabilities}]."""
    page = _get(f"{OLLAMA_WEB}/search?q={urllib.parse.quote(query)}")
    blocks = re.split(r"<li\b[^>]*x-test-model", page)[1:] or re.split(r'(?=<a\s[^>]*href="/library/)', page)[1:]
    out, seen = [], set()
    for b in blocks:
        m = re.search(r'href="/library/([A-Za-z0-9._-]+)"', b)
        if not m or m.group(1) in seen:
            continue
        name = m.group(1)
        seen.add(name)
        title = re.search(r"x-test-search-response-title[^>]*>(.*?)<", b, re.S)
        desc = re.search(r"<p\b[^>]*>(.*?)</p>", b, re.S)
        sizes = [_text(s) for s in re.findall(r"x-test-size[^>]*>(.*?)<", b, re.S)]
        caps = [_text(s) for s in re.findall(r"x-test-capability[^>]*>(.*?)<", b, re.S)]
        out.append({"name": _text(title.group(1)) if title else name, "description": _text(desc.group(1))[:300] if desc else "",
                    "sizes": [s for s in sizes if re.fullmatch(r"[0-9.]+[bmBM]|e?[0-9.]+[bB]", s)][:8],
                    "capabilities": [c for c in caps if c][:6]})
        if len(out) >= MAX_RESULTS:
            break
    return out


def hf_search(query, kind="chat"):
    """Hugging Face repositories for `query`: GGUF models for chat (Ollama can download those),
    text-to-image models for pictures. [{repo, downloads, likes, tags}]."""
    params = {"search": query, "sort": "downloads", "direction": "-1", "limit": str(MAX_RESULTS)}
    if kind == "image":
        params["pipeline_tag"] = "text-to-image"
    else:
        params["filter"] = "gguf"
    data = _json(f"{HF}/api/models?{urllib.parse.urlencode(params)}")
    if not isinstance(data, list):
        raise SearchError("unexpected answer")
    out = []
    for m in data:
        repo = m.get("id") or m.get("modelId") if isinstance(m, dict) else None
        if repo and REPO_RE.fullmatch(repo):
            out.append({"repo": repo, "downloads": m.get("downloads") or 0, "likes": m.get("likes") or 0,
                        "pipeline": m.get("pipeline_tag") or "",
                        "vision": "image-text-to-text" == m.get("pipeline_tag") or "vision" in " ".join(m.get("tags") or [])})
    return out


def quant(filename):
    m = QUANT_RE.findall(filename.rsplit(".", 1)[0])
    return m[-1].upper() if m else ""


def hf_files(repo, kind="chat"):
    """The usable files of a repository with size, quantization and license.
    chat: GGUF files, each with the Ollama name `hf.co/<repo>:<quant>`; image: single checkpoint files."""
    if not REPO_RE.fullmatch(repo or ""):
        raise ValueError("Invalid repository name")
    info = _json(f"{HF}/api/models/{repo}")
    tree = _json(f"{HF}/api/models/{repo}/tree/main")
    if not isinstance(info, dict) or not isinstance(tree, list):
        raise SearchError("unexpected answer")
    card = info.get("cardData") or {}
    lic = card.get("license") or next((t[8:] for t in info.get("tags") or [] if t.startswith("license:")), "")
    if isinstance(lic, list):
        lic = ", ".join(map(str, lic))
    files = []
    for f in tree:
        if not isinstance(f, dict) or f.get("type") != "file":
            continue
        path = f.get("path", "")
        size = (f.get("lfs") or {}).get("size") or f.get("size") or 0
        low = path.lower()
        if kind == "image":
            if low.endswith((".safetensors", ".ckpt", ".gguf")) and "/" not in path and size > 500_000_000:
                files.append({"path": path, "size": size, "quant": quant(path) if low.endswith(".gguf") else ""})
        elif low.endswith(".gguf") and "mmproj" not in low and not SPLIT_RE.search(low):
            q = quant(path)
            files.append({"path": path, "size": size, "quant": q, "ollama": f"hf.co/{repo}:{q}" if q else f"hf.co/{repo}"})
    files.sort(key=lambda x: x["size"])
    return {"repo": repo, "license": str(lic)[:80], "gated": bool(info.get("gated")), "files": files,
            "url": f"{HF}/{repo}"}
