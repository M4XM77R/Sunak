"""Token counter: one record per model request in the profile's database (table `usage`).

`providers.chat_stream` and the agent's own streams create a `Meter`, the adapters tell it what the backend reports
(Ollama: prompt_eval_count/eval_count/eval_duration, Anthropic: usage in message_start/message_delta, OpenAI-compatible:
usage with `stream_options`), and it writes the record when the request ends. A value the backend does not report is
stored as NULL, never guessed. Nothing here may make a model request fail: every error is logged quietly and dropped."""

import contextvars
import logging
import threading
import time

log = logging.getLogger("sunak.usage")

GOAL = 1_000_000_000  # the mark the progress bar counts towards
# What a request was for. Background requests are work Sunak does for the user by itself; they count too, but are told apart.
FOREGROUND = ("chat", "agent", "research", "compare", "document", "mail", "calendar", "other")
BACKGROUND = ("image_prompt", "image_check", "memory")
FIELDS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens")

_ctx = contextvars.ContextVar("sunak_usage", default=None)  # (database, profile id, kind) of the request being served


def bind(db, profile, kind):
    """Tell the counter which database and kind the model requests of this thread belong to."""
    _ctx.set((db, profile, kind))


def unbind():
    _ctx.set(None)


def thread(target, *args):
    """A daemon thread that keeps the counter's context (profile, kind) of the calling thread."""
    ctx = contextvars.copy_context()
    return threading.Thread(target=ctx.run, args=(target, *args), daemon=True)


def _count(v):
    """A token count from a backend value: a non-negative whole number, else None."""
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


class Meter:
    """Collects the numbers of one model request; `finish()` stores them (once)."""

    def __init__(self, p, model):
        self.p, self.model = p or {}, model
        self.target = _ctx.get()
        self.t0 = time.monotonic()
        self.first = self.last = None
        self.v = {}
        self.done = False

    def tick(self):
        """An output chunk (text or reasoning) arrived."""
        now = time.monotonic()
        if self.first is None:
            self.first = now
        self.last = now

    def put(self, **values):
        """Numbers the backend reported: input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens, eval_ns.
        Later values replace earlier ones (Anthropic repeats the output count); anything that is not a count is ignored."""
        for k, v in values.items():
            v = _count(v)
            if v is not None:
                self.v[k] = v

    def row(self, ok=True):
        out = self.v.get("output_tokens")
        eval_ns, span = self.v.get("eval_ns"), (self.last - self.first) if self.first is not None else 0
        if out and eval_ns:
            rate = out / eval_ns * 1e9
        elif out and span > 0.05:
            rate = out / span
        else:
            rate = None
        return {"ts": time.time(), "provider": str(self.p.get("id") or self.p.get("type") or ""), "model": str(self.model or ""),
                "kind": self.target[2] if self.target else "other", **{k: self.v.get(k) for k in FIELDS},
                "seconds": round(time.monotonic() - self.t0, 3), "tokens_per_second": round(rate, 2) if rate else None,
                "ok": 1 if ok else 0}

    def finish(self, ok=True):
        """Store the record. Called when the request ends, also when it fails or is stopped; never raises."""
        if self.done:
            return
        self.done = True
        try:
            if not self.target or not (self.v or self.first is not None):
                return  # no profile (a test, a script) or nothing came back at all
            self.target[0].add_usage(self.row(ok))
        except Exception:  # noqa: BLE001 - counting must never break a model request
            log.debug("Could not store the token count", exc_info=True)


class _NoMeter:
    """Stands in when nobody counts (a call without a profile)."""
    def tick(self): pass
    def put(self, **values): pass
    def finish(self, ok=True): pass


NONE = _NoMeter()


def anthropic_usage(meter, u):
    """Numbers from a Claude `usage` object (message_start, message_delta)."""
    if isinstance(u, dict):
        meter.put(input_tokens=u.get("input_tokens"), output_tokens=u.get("output_tokens"),
                  cache_read_tokens=u.get("cache_read_input_tokens"), cache_creation_tokens=u.get("cache_creation_input_tokens"))


def openai_usage(meter, u):
    """Numbers from an OpenAI-style `usage` object. prompt_tokens includes the cached ones, so they are taken out of the
    input count (cache reads are counted on their own)."""
    if not isinstance(u, dict):
        return
    prompt, cached = _count(u.get("prompt_tokens")), _count((u.get("prompt_tokens_details") or {}).get("cached_tokens"))
    meter.put(input_tokens=prompt - cached if prompt is not None and cached is not None and cached <= prompt else prompt,
              output_tokens=u.get("completion_tokens"), cache_read_tokens=cached)


def ollama_usage(meter, obj):
    """Numbers from the last (done) message of Ollama: prompt_eval_count, eval_count, eval_duration (nanoseconds)."""
    meter.put(input_tokens=obj.get("prompt_eval_count"), output_tokens=obj.get("eval_count"), eval_ns=obj.get("eval_duration"))


def total(row):
    """All tokens of a record or of the sums: input, output and cache (reads and writes)."""
    return sum(row.get(k) or 0 for k in FIELDS)


def summary(db):
    """What the counter shows: {last, total: {...}, background: {...}, goal}. `last` is the latest request that was not
    a background one."""
    try:
        return {"last": db.usage_last(BACKGROUND), "total": db.usage_sums(), "background": db.usage_sums(BACKGROUND),
                "goal": GOAL}
    except Exception:  # noqa: BLE001
        log.debug("Could not read the token count", exc_info=True)
        return {"last": None, "total": _empty(), "background": _empty(), "goal": GOAL}


def _empty():
    return {"requests": 0, **{k: 0 for k in FIELDS}, "all": 0}
