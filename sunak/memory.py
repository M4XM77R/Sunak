"""Automatic memory: after an answer the chat's model picks lasting facts about the user from the
latest exchange; they become memory notes (see db.add_note), which build_messages puts into every chat.

An explicit request ("remember that …", "merk dir …") is always looked at, even with automatic
memory switched off. Secrets (passwords, keys, card numbers) are never stored."""

import json
import re

from . import providers

MAX_NEW = 3       # facts per answer
MAX_LEN = 200     # characters per fact

EXPLICIT_RE = re.compile(
    r"\b(remember|don'?t forget|keep in mind|note that|merk(e)? dir|merken sie sich|vergiss nicht|"
    r"denk(e)? dran|behalte? im hinterkopf)\b", re.I)

# things that must never end up in a prompt that is sent with every chat
SECRET_RE = re.compile(
    r"(passw(or)?(d|t)|kennwort|\bpin\b|\bpins?code|api[ _-]?key|secret|token|private key|privater schlüssel|"
    r"\bsk-[a-z0-9_-]{8,}|\b(ghp|gho|xox[abp])_?[a-z0-9-]{8,}|\biban\b|\b[a-z]{2}\d{2}(?: ?[a-z0-9]{4}){3,}|"
    r"\b(?:\d[ -]?){13,19}\b|\bcvv\b|\bcvc\b|\btan\b)", re.I)

PROMPT = """You maintain a short list of lasting facts about the user of a chat assistant.
Read the latest exchange and list NEW facts worth remembering in future chats: the user's name, job,
location, family, long-term projects, tools they use, and preferences about how answers should be
(language, length, tone, format).

Rules:
- Only facts the USER states about themselves or asks to be remembered. Never facts from the assistant's answer alone.
- Leave out anything temporary (today's mood, the current task, one-off questions) and general knowledge.
- Never include passwords, PINs, keys, tokens, account or card numbers, or other secrets.
- Leave out what the list of known facts below already says, even in other words.
- {explicit}
- Write each fact as one short sentence about the user in the language the user writes in, e.g. "Name is Max." or "Prefers short answers."
- At most {max} facts.

Reply with a JSON array of strings only, e.g. ["Name is Max."], or [] when there is nothing new."""


def is_explicit(text):
    """True when the user asks for something to be remembered."""
    return bool(EXPLICIT_RE.search(text or ""))


def _norm(s):
    return re.sub(r"[\W_]+", " ", s.lower()).strip()


def parse(reply):
    """Facts from the model's reply: a JSON array of strings, or a list of "- " lines as a fallback."""
    reply = providers.strip_think(reply or "").strip()
    start, end = reply.find("["), reply.rfind("]")
    items = None
    if start >= 0 and end > start:
        try:
            items = json.loads(reply[start:end + 1])
        except ValueError:
            items = None
    if not isinstance(items, list):
        items = [ln.strip()[2:] for ln in reply.splitlines() if ln.strip().startswith(("- ", "* "))]
    return [" ".join(x.split()) for x in items if isinstance(x, str) and x.strip()]


def clean(facts, known):
    """Drop secrets, overlong facts and duplicates (of `known` and of each other); at most MAX_NEW."""
    seen = {_norm(k) for k in known}
    out = []
    for f in facts:
        f = f.strip(" \"'`")
        n = _norm(f)
        if not n or len(f) > MAX_LEN or SECRET_RE.search(f) or n in seen:
            continue
        seen.add(n)
        out.append(f)
    return out[:MAX_NEW]


def extract(prov, model, history, known, explicit=False):
    """New facts about the user from the last exchange of `history` ([{role, content}]), given the
    `known` memory texts. Raises providers.ProviderError when the model cannot be reached."""
    last_user = next((i for i in range(len(history) - 1, -1, -1) if history[i]["role"] == "user"), None)
    if last_user is None:
        return []
    user_text = history[last_user]["content"]
    if SECRET_RE.search(user_text) and not explicit:
        return []  # a message about passwords or keys is no place to learn from
    exchange = history[max(0, last_user - 1):last_user + 2]
    convo = "\n\n".join(f"{m['role'].upper()}: {providers.strip_think(m['content'])[:2000]}" for m in exchange)
    known_txt = "\n".join(f"- {k}" for k in known) or "(none)"
    rule = ("The user explicitly asks you to remember something: include it (unless it is a secret or already known)."
            if explicit else "When in doubt, leave it out: most exchanges contain nothing worth remembering.")
    reply = providers.chat_once(prov, model, [
        {"role": "system", "content": PROMPT.format(explicit=rule, max=MAX_NEW)},
        {"role": "user", "content": f"Known facts:\n{known_txt}\n\nLatest exchange:\n{convo}"},
    ], {"temperature": 0})
    return clean(parse(reply), known)
