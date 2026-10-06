"""Image generation with a local Stable Diffusion server: Automatic1111 (also Forge and SD.Next,
started with --api) or ComfyUI. Only the standard library; Sunak sends the prompt and stores the
picture, the models run in the other program."""

import base64
import binascii
import json
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .images import sniff

BACKENDS = {"automatic1111": "Automatic1111", "comfyui": "ComfyUI"}
DEFAULT_URLS = {"automatic1111": "http://127.0.0.1:7860", "comfyui": "http://127.0.0.1:8188"}
ASPECTS = {"square": (1, 1), "portrait": (2, 3), "landscape": (3, 2)}
SIZES = (512, 768, 1024)
MAX_STEPS = 100
MAX_BYTES = 40 * 1024 * 1024
TIMEOUT = 900  # seconds for one picture (a slow CPU can take minutes)
POLL = 1.0     # seconds between progress checks


class ImageGenError(Exception):
    """A message for the user (backend not reachable, no model, …)."""


def dimensions(aspect, size):
    """(width, height) for an aspect ('square', 'portrait', 'landscape') with `size` as the shorter side
    of a square's area, both multiples of 64."""
    a, b = ASPECTS.get(aspect, (1, 1))
    side = size if size in SIZES else 512
    scale = (side * side / (a * b)) ** 0.5
    return max(64, round(a * scale / 64) * 64), max(64, round(b * scale / 64) * 64)


def _url(cfg, path):
    return cfg["url"].rstrip("/") + path


def _request(cfg, method, path, body=None, timeout=30, raw=False):
    name = BACKENDS[cfg["type"]]
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(_url(cfg, path), data, {"Content-Type": "application/json"} if data else {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        detail = e.read(4000).decode("utf-8", "replace")
        try:
            j = json.loads(detail)
            err = j.get("error")
            detail = (err.get("message") if isinstance(err, dict) else err) or j.get("detail") or j.get("errors") or detail
        except (ValueError, AttributeError):
            pass
        if e.code == 404 and cfg["type"] == "automatic1111":
            raise ImageGenError(f"{name} answered 404: start it with the --api option") from None
        raise ImageGenError(f"{name}: {str(detail)[:300] or f'HTTP {e.code}'}") from None
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise ImageGenError(f"Cannot reach {name} at {cfg['url']} ({reason}). Is it running?") from None
    if len(out) > MAX_BYTES:
        raise ImageGenError(f"{name} sent too much data")
    if raw:
        return out
    try:
        return json.loads(out)
    except ValueError:
        raise ImageGenError(f"{name} sent an unexpected answer. Is {cfg['url']} the right address?") from None


def config(settings, override=None):
    """{type, url, model} from Sunak's settings (image_gen, image_gen_url, image_gen_model); `override`
    (the settings form, not saved yet) wins."""
    o = override or {}
    kind = o.get("type", settings.get("image_gen", "off"))
    if kind not in ("off", *BACKENDS):
        raise ValueError("Unknown image generator")
    url = str(o.get("url", settings.get("image_gen_url", "")) or "").strip() or DEFAULT_URLS.get(kind, "")
    if kind != "off" and not url.startswith(("http://", "https://")):
        raise ValueError("The image generator address must start with http:// or https://")
    return {"type": kind, "url": url, "model": str(o.get("model", settings.get("image_gen_model", "")) or "").strip()}


def models(cfg):
    """The checkpoints the backend offers."""
    if cfg["type"] == "automatic1111":
        return [m.get("title") or m.get("model_name") for m in _request(cfg, "GET", "/sdapi/v1/sd-models") if isinstance(m, dict)]
    info = _request(cfg, "GET", "/object_info/CheckpointLoaderSimple")
    try:
        return list(info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0])
    except (KeyError, IndexError, TypeError):
        raise ImageGenError("ComfyUI did not list its models") from None


def comfy_workflow(prompt, negative, width, height, steps, seed, model):
    """The standard text-to-image graph of ComfyUI (API format)."""
    return {
        "3": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": steps, "cfg": 7, "sampler_name": "euler",
              "scheduler": "normal", "denoise": 1, "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
              "latent_image": ["5", 0]}},
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": model}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["4", 1]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "sunak", "images": ["8", 0]}},
    }


def generate(cfg, prompt, negative="", width=512, height=512, steps=25, seed=None, progress=None, cancelled=None,
             poll=None, timeout=TIMEOUT):
    """Make one picture. Returns (image bytes, info {backend, model, seed, width, height, steps}).
    `progress(fraction or None)` is called while waiting; `cancelled()` True stops the backend."""
    poll = POLL if poll is None else poll
    if cfg.get("type") not in BACKENDS:
        raise ImageGenError("No image generator is set up. Choose one in Settings → Image generation.")
    seed = seed if isinstance(seed, int) and 0 <= seed < 2 ** 32 else random.randrange(2 ** 32)
    steps = max(1, min(MAX_STEPS, int(steps)))
    progress = progress or (lambda f: None)
    cancelled = cancelled or (lambda: False)
    if cfg["type"] == "automatic1111":
        data, model = _a1111(cfg, prompt, negative, width, height, steps, seed, progress, cancelled, poll, timeout)
    else:
        data, model = _comfy(cfg, prompt, negative, width, height, steps, seed, progress, cancelled, poll, timeout)
    if not sniff(data):
        raise ImageGenError(f"{BACKENDS[cfg['type']]} did not send a picture")
    return data, {"backend": cfg["type"], "model": model, "seed": seed, "width": width, "height": height, "steps": steps}


def _a1111(cfg, prompt, negative, width, height, steps, seed, progress, cancelled, poll, timeout):
    body = {"prompt": prompt, "negative_prompt": negative, "width": width, "height": height, "steps": steps,
            "seed": seed, "cfg_scale": 7, "batch_size": 1, "n_iter": 1}
    if cfg.get("model"):
        body["override_settings"] = {"sd_model_checkpoint": cfg["model"]}
        body["override_settings_restore_afterwards"] = False
    result = {}

    def run():
        try:
            result["out"] = _request(cfg, "POST", "/sdapi/v1/txt2img", body, timeout=timeout)
        except Exception as e:  # noqa: BLE001 - handed to the waiting thread
            result["error"] = e

    t = threading.Thread(target=run, daemon=True)
    t.start()
    started = time.monotonic()
    while t.is_alive():
        t.join(poll)
        if not t.is_alive():
            break
        if cancelled():
            try:
                _request(cfg, "POST", "/sdapi/v1/interrupt", {}, timeout=5)
            except ImageGenError:
                pass
            raise ImageGenError("Stopped")
        if time.monotonic() - started > timeout:
            raise ImageGenError("The image generator took too long")
        try:
            p = _request(cfg, "GET", "/sdapi/v1/progress?skip_current_image=true", timeout=5)
            progress(float(p.get("progress") or 0))
        except (ImageGenError, TypeError, ValueError, AttributeError):
            progress(None)
    if "error" in result:
        raise result["error"]
    out = result["out"]
    pics = out.get("images") if isinstance(out, dict) else None
    if not pics:
        raise ImageGenError("Automatic1111 did not send a picture")
    try:
        data = base64.b64decode(pics[0].split(",", 1)[-1])
    except (binascii.Error, ValueError, AttributeError):
        raise ImageGenError("Automatic1111 sent a damaged picture") from None
    model = cfg.get("model") or ""
    try:
        info = json.loads(out.get("info") or "{}")
        model = info.get("sd_model_name") or model
    except (ValueError, TypeError, AttributeError):
        pass
    return data, model


def _comfy(cfg, prompt, negative, width, height, steps, seed, progress, cancelled, poll, timeout):
    model = cfg.get("model")
    if not model:
        found = models(cfg)
        if not found:
            raise ImageGenError("ComfyUI has no model. Put a checkpoint into ComfyUI/models/checkpoints.")
        model = found[0]
    sent = _request(cfg, "POST", "/prompt", {"prompt": comfy_workflow(prompt, negative, width, height, steps, seed, model),
                                             "client_id": "sunak"})
    pid = sent.get("prompt_id") if isinstance(sent, dict) else None
    if not pid:
        raise ImageGenError(f"ComfyUI refused the job: {str(sent.get('node_errors') or sent)[:300]}")
    started = time.monotonic()
    while True:
        if cancelled():
            for path, body in (("/queue", {"delete": [pid]}), ("/interrupt", {})):
                try:
                    _request(cfg, "POST", path, body, timeout=5)
                except ImageGenError:
                    pass
            raise ImageGenError("Stopped")
        if time.monotonic() - started > timeout:
            raise ImageGenError("The image generator took too long")
        hist = _request(cfg, "GET", f"/history/{urllib.parse.quote(pid)}", timeout=10)
        job = hist.get(pid) if isinstance(hist, dict) else None
        if job:
            status = job.get("status") or {}
            if status.get("status_str") == "error":
                msgs = [m[1].get("exception_message") for m in status.get("messages", [])
                        if isinstance(m, list) and len(m) > 1 and m[0] == "execution_error" and isinstance(m[1], dict)]
                raise ImageGenError(f"ComfyUI: {(msgs and msgs[0]) or 'the job failed'}")
            for out in (job.get("outputs") or {}).values():
                for img in out.get("images") or []:
                    q = urllib.parse.urlencode({"filename": img.get("filename", ""), "subfolder": img.get("subfolder", ""),
                                                "type": img.get("type", "output")})
                    return _request(cfg, "GET", f"/view?{q}", timeout=60, raw=True), model
            if status.get("completed"):
                raise ImageGenError("ComfyUI finished without a picture")
        progress(None)
        time.sleep(poll)
