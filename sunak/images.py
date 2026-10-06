"""Images attached to chat messages: stored as files in <data>/images, named in the message's
meta ({"images": ["<id>.png", ...]}), and sent along to vision models."""

import base64
import binascii
import re
import time
from pathlib import Path

from .db import new_id

MAX_IMAGES = 4                 # per message
MAX_BYTES = 5 * 1024 * 1024    # per image (Claude's limit; the browser shrinks photos before sending)
RECENT = 3                     # images of the last 3 user messages that had some are sent to the model
NAME_RE = re.compile(r"[a-f0-9]{16}\.(?:png|jpg|gif|webp)")
TYPES = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}
OMITTED = "[An image was attached here; it is no longer shown to you.]"
NO_VISION = "[An image was attached here, but the current model cannot see images.]"


def folder(data_dir):
    return Path(data_dir) / "images"


def sniff(data):
    """File type from the first bytes ('png', 'jpg', 'gif', 'webp') or None. The name is not trusted."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def save(data_dir, items):
    """Store uploaded images [{"data": base64, "name": ...}] and return their file names. Raises ValueError."""
    if not items:
        return []
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise ValueError("images must be a list of {name, data}")
    if len(items) > MAX_IMAGES:
        raise ValueError(f"At most {MAX_IMAGES} images per message")
    decoded = []
    for item in items:
        label = item.get("name") if isinstance(item.get("name"), str) else "image"
        try:
            data = base64.b64decode(item.get("data") or "", validate=True)
        except (binascii.Error, ValueError, TypeError):
            raise ValueError(f"{label}: the upload is damaged, please try again") from None
        kind = sniff(data)
        if not kind:
            raise ValueError(f"{label}: only PNG, JPEG, GIF and WebP images can be sent")
        if len(data) > MAX_BYTES:
            raise ValueError(f"{label} is too big (max 5 MB)")
        decoded.append((kind, data))
    target = folder(data_dir)
    target.mkdir(parents=True, exist_ok=True)
    names = []
    for kind, data in decoded:
        name = f"{new_id()}.{kind}"
        (target / name).write_bytes(data)
        names.append(name)
    return names


def store(data_dir, data):
    """Store one picture (e.g. a generated one, any size) and return its file name. Raises ValueError."""
    kind = sniff(data)
    if not kind:
        raise ValueError("Not a PNG, JPEG, GIF or WebP picture")
    target = folder(data_dir)
    target.mkdir(parents=True, exist_ok=True)
    name = f"{new_id()}.{kind}"
    (target / name).write_bytes(data)
    return name


def existing(data_dir, refs):
    """The names in `refs` that are stored images (for re-sending an edited message with its images)."""
    if not isinstance(refs, list):
        return []
    return [r for r in refs[:MAX_IMAGES] if isinstance(r, str) and NAME_RE.fullmatch(r) and (folder(data_dir) / r).is_file()]


def load(data_dir, name):
    """(bytes, media type) of a stored image, or None."""
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        return None
    try:
        return (folder(data_dir) / name).read_bytes(), TYPES[name.rsplit(".", 1)[1]]
    except OSError:
        return None


def attach(data_dir, history, messages, vision=True):
    """Add the images of `history` (stored messages) to `messages` (the model's copy of them, same
    order at the end) as message["images"] = [{"type", "data" (base64)}]. Only the last RECENT user
    messages with images carry them; older ones and models without vision get a short note instead.
    Generated pictures (on assistant messages) are not sent: their text says what they show."""
    offset = len(messages) - len(history)
    with_images = [i for i, m in enumerate(history) if m.get("role") == "user" and (m.get("meta") or {}).get("images")]
    recent = set(with_images[-RECENT:])
    for i in with_images:
        msg = messages[offset + i]
        loaded = [x for x in (load(data_dir, n) for n in history[i]["meta"]["images"]) if x]
        if not loaded:
            continue
        if not vision or i not in recent:
            msg["content"] = (msg["content"] + "\n\n" + (OMITTED if vision else NO_VISION)).strip()
            continue
        msg["images"] = [{"type": t, "data": base64.b64encode(b).decode()} for b, t in loaded]
    return messages


def cleanup(data_dir, referenced, min_age=3600):
    """Delete stored images no message refers to any more (older than `min_age` seconds, so an image
    that is being sent right now is never removed). Returns how many were deleted."""
    target = folder(data_dir)
    if not target.is_dir():
        return 0
    now, count = time.time(), 0
    for f in target.iterdir():
        if NAME_RE.fullmatch(f.name) and f.name not in referenced:
            try:
                if now - f.stat().st_mtime >= min_age:
                    f.unlink()
                    count += 1
            except OSError:
                pass
    return count
