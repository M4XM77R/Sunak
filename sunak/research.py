"""Deep Research light: web search (DuckDuckGo, no API key), read the top
pages, let the model write a cited report."""

import html
import json
import os
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
MAX_PAGE_BYTES = 400_000
MAX_PAGE_CHARS = 6000


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "aside"}

    def __init__(self):
        super().__init__()
        self.parts, self.depth, self.title, self._in_title = [], 0, "", False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in ("p", "br", "li", "h1", "h2", "h3", "h4", "tr", "div"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.depth:
            self.parts.append(data)

    def text(self):
        t = "".join(self.parts)
        t = re.sub(r"[ \t\r\f\v]+", " ", t)
        t = re.sub(r"\n\s*\n+", "\n\n", t)
        return t.strip()


def html_to_text(raw):
    p = _TextExtractor()
    p.feed(raw)
    return p.title.strip(), p.text()


def _get(url, data=None, timeout=10):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept-Language": "en,de;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        ctype = r.headers.get("Content-Type", "")
        raw = r.read(MAX_PAGE_BYTES)
        charset = r.headers.get_content_charset() or "utf-8"
    return ctype, raw.decode(charset, "replace")


def parse_ddg(page):
    results = []
    for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
        href, title = html.unescape(m.group(1)), re.sub(r"<[^>]+>", "", html.unescape(m.group(2))).strip()
        if "uddg=" in href:
            href = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg", [href])[0]
        if href.startswith("//"):
            href = "https:" + href
        if href.startswith("http") and "duckduckgo.com/y.js" not in href:
            results.append({"title": title, "url": href})
    return results


def search_searxng(base, query):
    url = base.rstrip("/") + "/search?" + urllib.parse.urlencode({"q": query, "format": "json"})
    _, raw = _get(url)
    return [{"title": r.get("title", ""), "url": r["url"]} for r in json.loads(raw).get("results", []) if r.get("url")]


def search(query, limit=6):
    """Search with your own SearXNG (env SEARXNG_URL) or DuckDuckGo (no setup)."""
    if os.environ.get("SEARXNG_URL"):
        found = search_searxng(os.environ["SEARXNG_URL"], query)
    else:
        found = parse_ddg(_ddg(query))
    seen, out = set(), []
    for r in found:
        if r["url"] not in seen:
            seen.add(r["url"])
            out.append(r)
        if len(out) >= limit:
            break
    return out


def _ddg(query):
    _, page = _get("https://html.duckduckgo.com/html/", urllib.parse.urlencode({"q": query}).encode())
    return page


def read_page(url):
    ctype, raw = _get(url)
    if "html" not in ctype and "text" not in ctype:
        return "", ""
    title, text = html_to_text(raw) if "html" in ctype else ("", raw)
    return title, text[:MAX_PAGE_CHARS]


def report_prompt(question, sources):
    blocks = "\n\n".join(f"[{i + 1}] {s['title']} ({s['url']})\n{s['text']}" for i, s in enumerate(sources))
    return [
        {
            "role": "system",
            "content": "You are a careful research assistant. Write a well-structured Markdown report "
            "that answers the question using ONLY the numbered sources. Cite sources inline like [1] or [2][3]. "
            "Start with a short summary, then details with headings. Say clearly when the sources disagree "
            "or do not answer something. Answer in the language of the question.",
        },
        {"role": "user", "content": f"Question: {question}\n\nSources:\n\n{blocks}"},
    ]
