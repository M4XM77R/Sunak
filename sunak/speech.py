"""Speech input through a local Whisper server. The browser records and sends 16 kHz mono WAV; Sunak
passes it on to whisper.cpp's server (…/inference) or an OpenAI-compatible one (…/v1/audio/transcriptions,
e.g. Speaches / faster-whisper-server or LocalAI) and returns the text. Reading aloud happens entirely
in the browser."""

import json
import secrets
import urllib.error
import urllib.parse
import urllib.request

from . import providers

MODES = ("local", "browser", "off")   # speech input: only on this computer / browser recognition allowed / off
MAX_BYTES = 25 * 1024 * 1024          # about 13 minutes of 16 kHz mono WAV
TIMEOUT = 300                         # Whisper on a CPU can take a while for long recordings


def endpoint(url):
    """(full URL, kind) for a Whisper server address; kind is "whispercpp" or "openai". Raises ValueError."""
    url = url.strip().rstrip("/")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("The Whisper address must start with http:// or https://")
    path = parsed.path
    if path.endswith("/inference"):
        return url, "whispercpp"
    if path.endswith("/audio/transcriptions"):
        return url, "openai"
    if path.endswith("/v1"):
        return url + "/audio/transcriptions", "openai"
    raise ValueError("Enter the full Whisper address, e.g. http://localhost:8080/inference (whisper.cpp) "
                     "or http://localhost:8000/v1 (Speaches, faster-whisper-server, LocalAI)")


def multipart(fields, filename, data, ctype):
    """multipart/form-data body with text `fields` and one file named "file"; returns (body, content type)."""
    boundary = "sunak" + secrets.token_hex(12)
    out = []
    for k, v in fields.items():
        out.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    out.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
               f"Content-Type: {ctype}\r\n\r\n".encode() + data + b"\r\n")
    out.append(f"--{boundary}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={boundary}"


def is_wav(data):
    return len(data) > 44 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def transcribe(url, wav, model="", language=""):
    """Text of a WAV recording, from the Whisper server at `url`. Raises ValueError or ProviderError."""
    if not is_wav(wav):
        raise ValueError("The recording is not a WAV file")
    if len(wav) > MAX_BYTES:
        raise ValueError("The recording is too long (max 25 MB, about 13 minutes)")
    full, kind = endpoint(url)
    fields = {"response_format": "json"}
    if kind == "openai":
        fields["model"] = model.strip() or "whisper-1"
    if language:
        fields["language"] = language
    body, ctype = multipart(fields, "speech.wav", wav, "audio/wav")
    req = urllib.request.Request(full, data=body, method="POST", headers={"Content-Type": ctype, "User-Agent": "sunak"})
    opener = providers._DIRECT if providers._is_local(full) else providers._DEFAULT
    try:
        with opener.open(req, timeout=TIMEOUT) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300].strip()
        raise providers.ProviderError(f"Whisper server: HTTP {e.code} {detail}".strip()) from None
    except (urllib.error.URLError, OSError) as e:
        raise providers.ProviderError(f"Cannot reach the Whisper server at {full}: {getattr(e, 'reason', e)}") from None
    try:
        text = json.loads(raw)["text"]
    except (ValueError, KeyError, TypeError):
        raise providers.ProviderError("The Whisper server sent an unexpected answer") from None
    if not isinstance(text, str):
        raise providers.ProviderError("The Whisper server sent an unexpected answer")
    return " ".join(text.split())
