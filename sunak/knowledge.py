"""Local knowledge base: uploaded files are split into chunks, indexed with SQLite FTS5
and the best-matching chunks are added to the chat prompt (retrieval-augmented generation
without embeddings, so it works with every model and needs nothing extra)."""

import math
import re

CHUNK_CHARS = 1000      # target chunk size
SMALL_KB_CHARS = 8000   # a knowledge base this small is sent whole (good for "summarize this")
MAX_CONTEXT_CHARS = 7000
MAX_CHUNKS = 6

STOPWORDS = set("""
a about above after again all also am an and any are as at be because been before being below between both but by
can could did do does doing down during each few for from further had has have having he her here hers him his how
i if in into is it its itself just me more most my no nor not now of off on once only or other our out over own
same she should so some such than that the their them then there these they this those through to too under until
up very was we were what when where which while who whom why will with would you your yours
aber alle allem allen aller alles als also am an ander andere anderem anderen anderer anderes auch auf aus bei bin
bis bist da damit dann das dass dein deine dem den der des dessen dich die dies diese diesem diesen dieser dieses
dir doch dort du durch ein eine einem einen einer eines er es etwas euch euer für gegen gewesen hab habe haben hat
hatte hier hin hinter ich ihm ihn ihnen ihr ihre im in indem ins ist jede jedem jeden jeder jedes jetzt kann kein
keine können könnte man manche mein meine mich mir mit muss musste nach nicht nichts noch nun nur ob oder ohne sehr
sein seine sich sie sind so solche soll sollte sondern sonst über um und uns unser unter viel vom von vor war waren
warum was weil welche welchem welchen welcher welches wenn wer werde werden wie wieder will wir wird wo wollen zu
zum zur zwischen bitte gib sag erkläre erklär explain tell please show give what's
""".split())


def chunk(text, size=CHUNK_CHARS):
    """Split text into chunks of about `size` characters at paragraph, line or sentence borders."""
    text = re.sub(r"\n{3,}", "\n\n", text.replace("\r\n", "\n")).strip()
    pieces = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        while len(para) > size * 1.5:  # a very long paragraph: cut at a sentence or line end
            cut = max(para.rfind(". ", 0, size), para.rfind("\n", 0, size))
            cut = cut + 1 if cut > size // 3 else size
            pieces.append(para[:cut].strip())
            para = para[cut:].strip()
        if para:
            pieces.append(para)
    out, cur = [], ""
    for p in pieces:
        if cur and len(cur) + len(p) + 2 > size:
            out.append(cur)
            cur = p
        else:
            cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        out.append(cur)
    return out


def terms(text, limit=16):
    """Search words of a question: lower case, without stop words, unique, in order."""
    out = []
    for w in re.findall(r"\w+", text.casefold()):
        w = w.strip("_")
        keep = len(w) >= 3 if w.isdigit() else len(w) >= 2 and w not in STOPWORDS
        if keep and w not in out:
            out.append(w)
    return out[:limit]


def fts_query(words):
    """FTS5 query that matches any of the words; longer words also match as prefix (Handbuch → Handbuchs)."""
    return " OR ".join(f'"{w}"*' if len(w) >= 4 else f'"{w}"' for w in words)


def _scan(chunks, words, limit):
    """Fallback ranking without FTS5: tf-idf over prefix matches."""
    texts = [c["text"].casefold() for c in chunks]
    scored = []
    for w in words:
        pat = re.compile(r"\b" + re.escape(w) + (r"\w*" if len(w) >= 4 else r"\b"))
        counts = [len(pat.findall(t)) for t in texts]
        df = sum(1 for n in counts if n)
        if not df:
            continue
        idf = math.log(1 + len(texts) / df)
        scored.append([(1 + math.log(n)) * idf if n else 0 for n in counts])
    totals = [sum(col) for col in zip(*scored)] if scored else []
    ranked = sorted((i for i, s in enumerate(totals) if s > 0), key=lambda i: -totals[i])
    return [chunks[i] for i in ranked[:limit]]


def search(db, query, limit=MAX_CHUNKS):
    """Best-matching chunks for a query (empty list when nothing matches)."""
    words = terms(query)
    if not words:
        return []
    if db.fts:
        return db.kb_match(fts_query(words), limit)
    return _scan(db.kb_chunks(), words, limit)


def retrieve(db, query):
    """Chunks to show the model: the whole knowledge base when it is small, else the best matches
    (up to MAX_CONTEXT_CHARS)."""
    if db.kb_total_chars() <= SMALL_KB_CHARS:
        return db.kb_chunks()
    out, used = [], 0
    for c in search(db, query, MAX_CHUNKS * 2):
        if used + len(c["text"]) > MAX_CONTEXT_CHARS and out:
            break
        out.append(c)
        used += len(c["text"])
        if len(out) >= MAX_CHUNKS:
            break
    return out


def context(chunks):
    """System-prompt section with the excerpts."""
    parts = [f"[{c['name']}]\n{c['text']}" for c in chunks]
    return ("The user's knowledge base contains these excerpts. Use them to answer when they are relevant and "
            "cite the file name in square brackets, e.g. [report.pdf]. If they do not contain the answer, say so "
            "and answer from general knowledge.\n\n" + "\n\n---\n\n".join(parts))


def sources(chunks):
    """Unique files of the chunks, in order: [{"id", "name"}]."""
    seen, out = set(), []
    for c in chunks:
        if c["file_id"] not in seen:
            seen.add(c["file_id"])
            out.append({"id": c["file_id"], "name": c["name"]})
    return out


def snippet(text, words, width=160):
    """Short excerpt around the first matching word."""
    low = text.casefold()
    hits = [low.find(w) for w in words if low.find(w) >= 0]
    start = max(0, min(hits) - width // 3) if hits else 0
    if start:  # begin at a word boundary
        space = text.find(" ", start, start + 20)
        start = space + 1 if space >= 0 else start
    s = text[start:start + width].replace("\n", " ").strip()
    return ("…" if start else "") + s + ("…" if start + width < len(text) else "")
