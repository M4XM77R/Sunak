"""Sunak's own image generator: stable-diffusion.cpp (a ready-made program from its GitHub releases, no
Python packages) plus image models from Hugging Face. Everything is downloaded only after a click, into
<data>/imagegen: `engine/` (the program) and `models/<id>/` (the model files). Downloads continue where they
stopped (`.part` files and HTTP Range)."""

import http.client
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

GITHUB_API = "https://api.github.com"
ENGINE_REPO = "leejet/stable-diffusion.cpp"
HF = "https://huggingface.co"
EXE_NAMES = ("sd-cli", "sd")
CHUNK = 1024 * 1024
POLL = 0.5  # seconds between progress updates while a picture is made
UA = "Sunak (stable-diffusion.cpp downloader)"

# Curated image models: every file is downloaded from Hugging Face (repo, path). `role` is the
# stable-diffusion.cpp option the file is passed with. size_gb is the download size, roughly.
CATALOG = [
    {"id": "sd-turbo", "title": "SD-Turbo", "size_gb": 5.2, "ram_gb": 6, "tags": ["fast"],
     "description": "Pictures in 1 to 4 steps, good for slower computers. 512 px.",
     "license": "Stability AI Community License (free for non-commercial use and small companies)",
     "license_url": "https://huggingface.co/stabilityai/sd-turbo/blob/main/LICENSE.md",
     "files": [{"role": "model", "repo": "stabilityai/sd-turbo", "path": "sd_turbo.safetensors"}],
     "defaults": {"size": 512, "steps": 4, "cfg": 1.0, "sampler": "euler_a"}},
    {"id": "sd15", "title": "Stable Diffusion 1.5", "size_gb": 4.3, "ram_gb": 6, "tags": ["classic"],
     "description": "The classic model with countless styles. 512 px, about 25 steps.",
     "license": "CreativeML Open RAIL-M (use restrictions apply)",
     "license_url": "https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5/blob/main/README.md",
     "files": [{"role": "model", "repo": "stable-diffusion-v1-5/stable-diffusion-v1-5", "path": "v1-5-pruned-emaonly.safetensors"}],
     "defaults": {"size": 512, "steps": 25, "cfg": 7.0, "sampler": "euler_a"}},
    {"id": "sdxl-turbo", "title": "SDXL-Turbo", "size_gb": 6.9, "ram_gb": 10, "tags": ["fast"],
     "description": "Sharper than SD-Turbo, still only 1 to 4 steps. 512 px.",
     "license": "Stability AI Community License (free for non-commercial use and small companies)",
     "license_url": "https://huggingface.co/stabilityai/sdxl-turbo/blob/main/LICENSE.md",
     "files": [{"role": "model", "repo": "stabilityai/sdxl-turbo", "path": "sd_xl_turbo_1.0_fp16.safetensors"}],
     "defaults": {"size": 512, "steps": 4, "cfg": 1.0, "sampler": "euler_a"}},
    {"id": "sdxl", "title": "Stable Diffusion XL", "size_gb": 7.3, "ram_gb": 12, "tags": ["quality"],
     "description": "Detailed 1024 px pictures. Best with a graphics card with 8 GB or more.",
     "license": "CreativeML Open RAIL++-M (use restrictions apply)",
     "license_url": "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/main/LICENSE.md",
     "files": [{"role": "model", "repo": "stabilityai/stable-diffusion-xl-base-1.0", "path": "sd_xl_base_1.0.safetensors"},
               {"role": "vae", "repo": "madebyollin/sdxl-vae-fp16-fix", "path": "sdxl_vae.safetensors"}],
     "defaults": {"size": 1024, "steps": 25, "cfg": 7.0, "sampler": "euler_a"}},
]
CUSTOM_DEFAULTS = {"size": 512, "steps": 25, "cfg": 7.0, "sampler": "euler_a"}
ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
REPO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*")
MODEL_FILE_RE = re.compile(r"[^/\\]+\.(?:safetensors|ckpt|gguf)", re.I)


class SdError(Exception):
    """A message for the user."""


def root(data_dir):
    return Path(data_dir) / "imagegen"


# ---------------------------------------------------------------- downloads
_active = set()
_active_lock = threading.Lock()


def _open(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise SdError(f"{url} needs a login. On Hugging Face this usually means you have to accept the model's "
                          "license on its page first; Sunak can only download models that are free to download.") from None
        if e.code == 404:
            raise SdError(f"Not found: {url}") from None
        if e.code == 416:
            raise
        raise SdError(f"Download failed: HTTP {e.code} from {urllib.parse.urlsplit(url).netloc}") from None
    except (urllib.error.URLError, OSError) as e:
        raise SdError(f"Cannot reach {urllib.parse.urlsplit(url).netloc} ({getattr(e, 'reason', e)}). "
                      "Are you online?") from None


def get_json(url, timeout=20):
    with _open(url, {"Accept": "application/json"}, timeout) as r:
        try:
            return json.loads(r.read(20 * 1024 * 1024))
        except ValueError:
            raise SdError(f"Unexpected answer from {urllib.parse.urlsplit(url).netloc}") from None


def download(url, dest, progress=None, expected_size=None):
    """Download `url` to `dest`, continuing a `.part` file from an earlier try. `progress(done, total)` is
    called now and then; an exception from it (the browser went away) stops the download and keeps the part."""
    dest = Path(dest)
    part = dest.with_name(dest.name + ".part")
    key = str(dest)
    with _active_lock:
        if key in _active:
            raise SdError(f"{dest.name} is already downloading")
        _active.add(key)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        have = part.stat().st_size if part.exists() else 0
        try:
            r = _open(url, {"Range": f"bytes={have}-"} if have else {}, timeout=60)
        except urllib.error.HTTPError as e:  # 416: the part is already complete (or bigger than the file)
            if e.code == 416 and have and (expected_size is None or have == expected_size):
                part.replace(dest)
                return dest
            part.unlink(missing_ok=True)
            raise SdError("The download did not match the file on the server; it starts over next time.") from None
        with r:
            if r.status == 206:
                m = re.match(r"bytes (\d+)-\d+/(\d+)", r.headers.get("Content-Range", ""))
                if not m or int(m.group(1)) != have:
                    raise SdError("The server sent the wrong part of the file. Try again.")
                total = int(m.group(2))
                mode = "ab"
            else:
                have, mode = 0, "wb"
                total = int(r.headers.get("Content-Length") or 0) or None
            if expected_size and total and total != expected_size:
                raise SdError(f"{dest.name} has an unexpected size on the server ({total} instead of {expected_size} bytes)")
            done, last = have, 0.0
            with open(part, mode) as f:
                while True:
                    try:
                        chunk = r.read(CHUNK)
                    except (http.client.HTTPException, OSError):
                        chunk = b""  # the connection broke: checked against the size below
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if progress and now - last > 0.25:
                        last = now
                        progress(done, total)
        if total and done != total:
            raise SdError(f"The download of {dest.name} broke off. Click Download again to continue.")
        if progress:
            progress(done, total)
        part.replace(dest)
        return dest
    finally:
        with _active_lock:
            _active.discard(key)


def downloading():
    with _active_lock:
        return set(_active)


# ---------------------------------------------------------------- the program (engine)
def _platform():
    system = platform.system()
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64" if machine in ("x86_64", "amd64", "x64") else machine
    return system, arch


def rank_assets(assets, system=None, arch=None, gpu_info=None):
    """The release files that can run here, best first: [{name, size, url, kind}]. kind is cuda, vulkan,
    rocm, metal, cpu or other; with an NVIDIA card CUDA comes first, with another graphics card Vulkan."""
    if system is None or arch is None:
        system, arch = _platform()
    g = gpu_info or {}
    vendor = g.get("vendor") if g.get("usable") else None
    os_words = {"Windows": ("win",), "Darwin": ("darwin", "macos", "osx"), "Linux": ("linux", "ubuntu")}.get(system, ())
    arch_words = {"x64": ("x64", "x86_64", "amd64"), "arm64": ("arm64", "aarch64")}.get(arch, (arch,))
    out = []
    # the CUDA runtime comes as its own archive on Windows; it is unpacked next to the program
    cudart = next((a for a in assets if a.get("name", "").lower().startswith("cudart") and a["name"].lower().endswith(".zip")), None)
    for a in assets:
        name = a.get("name", "")
        low = name.lower()
        if low.startswith("cudart") or not low.endswith(".zip") or not any(re.search(rf"(?<![a-z]){w}(?:dows)?(?![a-z])" if w == "win" else w, low) for w in os_words):
            continue
        if not any(w in low for w in arch_words) and not (system == "Darwin" and arch == "arm64" and "x64" not in low and "x86_64" not in low):
            continue
        kind = next((k for k in ("cuda", "vulkan", "rocm", "hip", "sycl", "metal", "opencl") if k in low), "cpu")
        kind = "rocm" if kind == "hip" else kind
        if system == "Darwin":
            kind = "metal"  # the macOS builds use the GPU through Metal
        item = {"name": name, "size": a.get("size") or 0, "zip_size": a.get("size") or 0, "url": a.get("browser_download_url", ""), "kind": kind}
        if kind == "cuda" and system == "Windows" and cudart:
            item["extra"] = {"name": cudart["name"], "zip_size": cudart.get("size") or 0, "url": cudart.get("browser_download_url", "")}
            item["size"] += item["extra"]["zip_size"]
        out.append(item)

    def score(a):
        prefer = {"nvidia": ["cuda", "vulkan"], "amd": ["vulkan", "rocm"]}.get(vendor, ["vulkan"] if vendor else [])
        order = prefer + ["metal", "cpu"]
        pos = order.index(a["kind"]) if a["kind"] in order else len(order) + 1
        avx = 0 if "avx2" in a["name"].lower() else 1 if "avx" not in a["name"].lower() else 2
        return pos, avx, a["name"]
    return sorted(out, key=score)


def latest_release():
    """The newest release of stable-diffusion.cpp: {tag, assets}."""
    d = get_json(f"{GITHUB_API}/repos/{ENGINE_REPO}/releases/latest")
    if not isinstance(d, dict) or "assets" not in d:
        raise SdError("GitHub did not list the stable-diffusion.cpp release")
    return {"tag": d.get("tag_name") or "", "assets": d["assets"]}


def engine_info(data_dir):
    """{installed, tag, asset, kind, exe} of the installed program, or {installed: False}."""
    try:
        info = json.loads((root(data_dir) / "engine" / "engine.json").read_text(encoding="utf-8"))
        exe = root(data_dir) / "engine" / info["exe"]
        if exe.is_file():
            return dict(info, installed=True, path=str(exe))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {"installed": False}


def _find_exe(folder):
    names = [n + (".exe" if os.name == "nt" else "") for n in EXE_NAMES]
    for name in names:
        for p in sorted(Path(folder).rglob(name)):
            if p.is_file():
                return p
    return None


def install_engine(data_dir, asset, tag="", progress=None):
    """Download a release file (from rank_assets, with its `extra` CUDA runtime), unpack it and remember the program."""
    base = root(data_dir)
    parts = [asset] + ([asset["extra"]] if asset.get("extra") else [])
    for p in parts:
        if not str(p.get("url", "")).startswith(("https://", "http://")) or not p.get("name", "").lower().endswith(".zip"):
            raise SdError("Pick one of the listed program files")
    zips = []
    total = sum(p.get("zip_size") or 0 for p in parts) or None
    offset = 0
    for p in parts:
        prog = (lambda d, t, o=offset: progress(o + d, total or t)) if progress else None
        zips.append(download(p["url"], base / "downloads" / Path(p["name"]).name, prog, p.get("zip_size") or None))
        offset += p.get("zip_size") or 0
    new = base / "engine.new"
    shutil.rmtree(new, ignore_errors=True)
    new.mkdir(parents=True)
    for zpath in zips:
        try:
            with zipfile.ZipFile(zpath) as z:
                for member in z.infolist():
                    target = (new / member.filename).resolve()
                    if new.resolve() not in target.parents and target != new.resolve():
                        raise SdError("The program archive contains unsafe paths")
                z.extractall(new)
        except zipfile.BadZipFile:
            zpath.unlink(missing_ok=True)
            shutil.rmtree(new, ignore_errors=True)
            raise SdError("The downloaded program archive is damaged. Click Install again.") from None
    exe = _find_exe(new)
    if not exe:
        shutil.rmtree(new, ignore_errors=True)
        raise SdError(f"No stable-diffusion.cpp program found in {asset['name']}. Pick another file.")
    if os.name != "nt":
        for p in new.rglob("*"):
            if p.is_file() and (p == exe or p.suffix in ("", ".so", ".dylib") or ".so." in p.name):
                p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    info = {"tag": tag, "asset": asset["name"], "kind": asset.get("kind", ""), "exe": str(exe.relative_to(new))}
    (new / "engine.json").write_text(json.dumps(info), encoding="utf-8")
    old = base / "engine"
    shutil.rmtree(old, ignore_errors=True)
    new.replace(old)
    for zpath in zips:
        zpath.unlink(missing_ok=True)
    return engine_info(data_dir)


def remove_engine(data_dir):
    shutil.rmtree(root(data_dir) / "engine", ignore_errors=True)


# ---------------------------------------------------------------- models
def _folder(data_dir, mid):
    return root(data_dir) / "models" / mid


def custom_models(data_dir):
    """Models downloaded from a Hugging Face search: [{id, title, repo, path, license, size_gb}]."""
    out = []
    base = root(data_dir) / "models"
    if not base.is_dir():
        return out
    for meta in sorted(base.glob("*/model.json")):
        try:
            m = json.loads(meta.read_text(encoding="utf-8"))
            if m.get("custom") and ID_RE.fullmatch(m.get("id", "")):
                out.append(m)
        except (OSError, ValueError):
            pass
    return out


def find(data_dir, mid):
    m = next((m for m in CATALOG if m["id"] == mid), None)
    return m or next((m for m in custom_models(data_dir) if m["id"] == mid), None)


def file_path(data_dir, mid, f):
    return _folder(data_dir, mid) / Path(f["path"]).name


def model_state(data_dir, m):
    """installed (all files there), partial (some bytes downloaded), downloading."""
    paths = [file_path(data_dir, m["id"], f) for f in m["files"]]
    active = downloading()
    return {"installed": all(p.is_file() for p in paths),
            "partial": any(p.with_name(p.name + ".part").exists() for p in paths),
            "downloading": any(str(p) in active for p in paths)}


def listing(data_dir, ram_gb=None, gpu_info=None):
    """Catalog and custom models with their state and whether they fit this computer."""
    g = gpu_info or {}
    vram = g.get("vram_gb") if g.get("usable") and not g.get("unified") else None
    out = []
    for m in CATALOG + custom_models(data_dir):
        need = m.get("ram_gb") or round(m.get("size_gb", 4) * 1.5 + 1)
        item = {k: v for k, v in m.items() if k != "files"}
        item.update(model_state(data_dir, m), files=[f["path"] for f in m["files"]],
                    fits=ram_gb is None or ram_gb >= need or bool(vram and vram >= m.get("size_gb", 4) + 1),
                    gpu=bool(vram and vram >= m.get("size_gb", 4) + 1) or bool(g.get("unified") and g.get("usable")))
        out.append(item)
    return out


def status(data_dir, settings):
    """What stops the picture button from working with Sunak's own program: {problem, model}. problem is '' when all is fine (or
    another image generator is chosen), 'setup' (nothing set up yet), 'no_engine' (chosen, but the program is
    gone), 'no_model' (no usable model chosen or downloaded), or 'choose' (program and a model are there but
    the generator is still off; `model` is the one to use)."""
    kind = settings.get("image_gen", "off")
    if kind not in ("off", "local"):
        return {"problem": "", "model": ""}
    eng = engine_info(data_dir)["installed"]
    mid = settings.get("image_gen_model", "") if kind == "local" else ""
    chosen = find(data_dir, mid) if mid else None
    ready = [m for m in CATALOG + custom_models(data_dir) if model_state(data_dir, m)["installed"]]
    if kind == "off":
        if not eng and not ready:
            return {"problem": "", "model": ""}  # nobody asked for pictures yet: stay quiet
        if eng and ready:
            return {"problem": "choose", "model": ready[0]["id"]}
        return {"problem": "no_model" if eng else "no_engine", "model": ""}
    if not eng:
        return {"problem": "no_engine", "model": ""}
    if not chosen or not model_state(data_dir, chosen)["installed"]:
        return {"problem": "choose", "model": ready[0]["id"]} if ready else {"problem": "no_model", "model": ""}
    return {"problem": "", "model": mid}


def hf_url(repo, path):
    return f"{HF}/{repo}/resolve/main/{urllib.parse.quote(path)}"


def pull(data_dir, m, progress=None):
    """Download all files of model `m` (catalog entry or custom). progress(done, total, file_index, files)."""
    files = m["files"]
    for i, f in enumerate(files):
        dest = file_path(data_dir, m["id"], f)
        if dest.is_file():
            continue
        download(hf_url(f["repo"], f["path"]), dest,
                 (lambda d, t, i=i: progress(d, t, i, len(files))) if progress else None, f.get("size"))
    if m.get("custom"):
        (_folder(data_dir, m["id"]) / "model.json").write_text(json.dumps(m), encoding="utf-8")


def custom_entry(repo, path, size=None, license_name="", gated=False):
    """A model entry for one checkpoint file of a Hugging Face repository (from the search)."""
    if not REPO_RE.fullmatch(repo or "") or ".." in repo:
        raise SdError("Invalid repository name")
    if not MODEL_FILE_RE.fullmatch(Path(path or "").name) or ".." in (path or "") or path.startswith("/"):
        raise SdError("Only .safetensors, .ckpt and .gguf files can be used")
    stem = re.sub(r"[^a-z0-9._-]+", "-", f"{repo.split('/')[1]}-{Path(path).stem}".lower()).strip("-.")[:60]
    size_gb = round(size / 1e9, 1) if size else None
    return {"id": "hf-" + stem, "title": f"{repo.split('/')[1]} ({Path(path).name})", "custom": True,
            "size_gb": size_gb or 4, "tags": ["Hugging Face"], "description": f"From huggingface.co/{repo}",
            "license": license_name or "see the model page", "license_url": f"{HF}/{repo}", "gated": bool(gated),
            "files": [{"role": "model", "repo": repo, "path": path, **({"size": size} if size else {})}],
            "defaults": dict(CUSTOM_DEFAULTS, size=1024 if re.search(r"xl|1024", repo + path, re.I) else 512)}


def delete_model(data_dir, mid):
    if not ID_RE.fullmatch(mid or ""):
        raise SdError("Unknown model")
    folder = _folder(data_dir, mid)
    if any(folder in Path(p).parents for p in downloading()):
        raise SdError("The model is still downloading. Cancel the download first.")
    shutil.rmtree(folder, ignore_errors=True)


# ---------------------------------------------------------------- making a picture
STEP_RE = re.compile(rb"(\d+)/(\d+)\s*-")


def command(exe, data_dir, m, prompt, negative, width, height, steps, seed, out_file):
    d = m.get("defaults") or CUSTOM_DEFAULTS
    cmd = [str(exe)]
    for f in m["files"]:
        flag = {"model": "-m", "vae": "--vae", "diffusion_model": "--diffusion-model", "clip_l": "--clip_l",
                "t5xxl": "--t5xxl"}[f["role"]]
        cmd += [flag, str(file_path(data_dir, m["id"], f))]
    cmd += ["-p", prompt, "-W", str(width), "-H", str(height), "--steps", str(steps), "--cfg-scale", str(d["cfg"]),
            "--sampling-method", d["sampler"], "-s", str(seed), "-o", str(out_file)]
    if negative:
        cmd += ["-n", negative]
    return cmd


def generate(data_dir, mid, prompt, negative, aspect_dims, seed, progress=None, cancelled=None, timeout=1800):
    """Run stable-diffusion.cpp once. `aspect_dims(size)` turns the model's picture size into (width, height).
    Returns (png bytes, info)."""
    eng = engine_info(data_dir)
    if not eng["installed"]:
        raise SdError("The image program is not set up yet. Set it up on the Models page under Image models.")
    m = find(data_dir, mid) if mid else None
    if not m:
        raise SdError("Choose an image model in Settings → Image generation.")
    if not model_state(data_dir, m)["installed"]:
        raise SdError(f"{m['title']} is not downloaded yet. Download it on the Models page under Image models.")
    d = m.get("defaults") or CUSTOM_DEFAULTS
    width, height = aspect_dims(d["size"])
    out_dir = root(data_dir) / "tmp"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{os.getpid()}-{threading.get_ident()}-{seed}.png"
    cmd = command(eng["path"], data_dir, m, prompt, negative, width, height, d["steps"], seed, out_file)
    progress = progress or (lambda f: None)
    cancelled = cancelled or (lambda: False)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                cwd=str(Path(eng["path"]).parent), creationflags=flags)
    except OSError as e:
        raise SdError(f"The image program could not start ({e}). Set it up again on the Models page.") from None
    tail = []
    state = {"p": None}

    def read():
        buf = b""
        while True:
            chunk = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(4096)
            if not chunk:
                break
            buf += chunk
            parts = re.split(rb"[\r\n]", buf)
            buf = parts.pop()
            for line in parts:
                if line.strip():
                    tail.append(line.decode("utf-8", "replace").strip())
                    del tail[:-20]
                for a, b in STEP_RE.findall(line):
                    if int(b):
                        state["p"] = min(1.0, int(a) / int(b))
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    started = time.monotonic()
    try:
        while proc.poll() is None:
            if cancelled():
                proc.kill()
                raise SdError("Stopped")
            if time.monotonic() - started > timeout:
                proc.kill()
                raise SdError("The image program took too long")
            progress(state["p"])
            time.sleep(POLL)
        reader.join(5)
        if proc.returncode != 0 or not out_file.is_file():
            # the program's own words: its error lines, else its last lines (a missing library, too little memory, …)
            lines = [t for t in tail if re.search(r"error|fail|cannot|can't|not found|out of memory|unknown|invalid", t, re.I)]
            last = " | ".join((lines or tail)[-3:])
            hint = " Try a smaller model or picture size, or the CPU build of the image program." if re.search(r"memory|alloc|cuda|vulkan", last, re.I) else ""
            raise SdError(f"The image program failed (exit code {proc.returncode}){': ' + last[:500] if last else ''}.{hint}")
        data = out_file.read_bytes()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(10)
        reader.join(5)
        proc.stdout.close()
        out_file.unlink(missing_ok=True)
    return data, {"backend": "local", "model": m["title"], "seed": seed, "width": width, "height": height, "steps": d["steps"]}
