"""CHANGELOG.md: read the entries between the installed version and a newer one.

The file has one section per version, newest first: `## [0.14.0] – 2026-10-07`, followed by short Markdown
points. The update check reads the file from the remote (`git show @{u}:CHANGELOG.md`), so the entries can be
shown before anything is installed. A missing or broken file is never an error: it just yields no entries."""

import re

MAX_CHARS = 400_000   # a changelog bigger than this is not read at all
MAX_ENTRIES = 100
HEADING = re.compile(r"^##[ \t]+\[?(\d{1,4}\.\d{1,5}\.\d{1,6})\]?[ \t]*(?:[–—-][ \t]*(.*?))?[ \t]*$")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def version_key(version):
    """(0, 14, 0) for "0.14.0"; None when it is not a plain a.b.c version."""
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", str(version).strip())
    return tuple(int(x) for x in m.groups()) if m else None


def parse(text):
    """Sections of a changelog as [{"version", "date", "body"}] in file order. Anything before the first
    version heading is ignored; so is a second section of the same version."""
    if not isinstance(text, str) or len(text) > MAX_CHARS:
        return []
    entries, seen, current = [], set(), None
    for line in text.lstrip("﻿").splitlines():
        m = HEADING.match(line.rstrip())
        if m:
            version = m.group(1)
            current = None
            if version not in seen and len(entries) < MAX_ENTRIES:
                seen.add(version)
                date = (m.group(2) or "").strip()
                current = {"version": version, "date": date if DATE.fullmatch(date) else "", "lines": []}
                entries.append(current)
        elif current is not None:
            current["lines"].append(line.rstrip())
    return [{"version": e["version"], "date": e["date"], "body": "\n".join(e["lines"]).strip()} for e in entries]


def between(entries, current, newest=""):
    """Entries newer than `current` and not newer than `newest` (empty = no upper limit), newest first."""
    low, high = version_key(current), version_key(newest)
    picked = [e for e in entries if version_key(e["version"]) and (low is None or version_key(e["version"]) > low)
              and (high is None or version_key(e["version"]) <= high)]
    return sorted(picked, key=lambda e: version_key(e["version"]), reverse=True)


def to_text(entries):
    """Entries as plain text for the terminal: a heading per version, the points below."""
    blocks = []
    for e in entries:
        head = f"Sunak {e['version']}" + (f" ({e['date']})" if e["date"] else "")
        body = []
        for line in e["body"].splitlines():
            line = re.sub(r"^#{3,6}[ \t]+(.*)$", r"\1:", line)  # ### Neu → Neu:
            body.append(line.replace("`", "").replace("**", ""))
        blocks.append(head + "\n" + "\n".join(body).strip())
    return "\n\n".join(blocks)
