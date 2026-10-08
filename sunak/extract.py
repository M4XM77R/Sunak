"""Turn uploaded files into plain text: PDF, Word (.docx), OpenDocument (.odt),
PowerPoint (.pptx), HTML and any text format. Standard library only.

The PDF reader is deliberately small: it decodes Flate/ASCII85 streams (also inside
object streams), follows the page tree, maps glyphs to Unicode with each font's
ToUnicode CMap and understands the text operators. Scanned PDFs (images only) and
encrypted PDFs have no extractable text."""

import base64
import io
import re
import zipfile
import zlib
from xml.etree import ElementTree

from .research import html_to_text

TEXT_EXTENSIONS = {
    "txt", "md", "markdown", "csv", "tsv", "json", "yaml", "yml", "toml", "ini", "cfg", "log", "xml", "rst",
    "py", "js", "ts", "tsx", "jsx", "java", "c", "h", "cpp", "hpp", "cs", "go", "rs", "rb", "php", "swift",
    "kt", "sh", "bat", "ps1", "sql", "css", "scss", "tex", "srt", "vtt",
}
SUPPORTED = sorted(TEXT_EXTENSIONS | {"pdf", "docx", "odt", "pptx", "html", "htm"})
MAX_UNZIPPED = 60 * 1024 * 1024    # total text XML read from an Office file
MAX_STREAM = 32 * 1024 * 1024      # one decompressed PDF stream
MAX_DECODED = 256 * 1024 * 1024    # all decompressed PDF streams together
MAX_NESTING = 64                   # nested PDF arrays / dictionaries / page-tree levels
MAX_CMAP = 200_000                 # entries of one ToUnicode map


class ExtractError(ValueError):
    pass


def extract_text(name, data):
    """Plain text of a file. Raises ExtractError with a message for the user.
    Damaged or hostile files never raise anything else."""
    try:
        return _extract(name, data)
    except ExtractError:
        raise
    except (Exception, RecursionError) as e:  # noqa: BLE001 - zipfile, XML and PDF errors of all kinds
        raise ExtractError(f"{name}: the file could not be read (damaged or unsupported: {type(e).__name__})") from None


def _extract(name, data):
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext == "pdf" or data[:5] == b"%PDF-":
        text = pdf_text(data)
        if not text.strip():
            raise ExtractError(f"{name}: no text found (scanned PDFs without a text layer are not supported)")
        return text
    if ext in ("docx", "odt", "pptx"):
        return office_text(data, ext)
    if ext in ("html", "htm"):
        return html_to_text(_decode(data))[1]
    if ext in TEXT_EXTENSIONS or b"\x00" not in data[:4096]:
        return _decode(data)
    raise ExtractError(f"{name}: unsupported file type. Supported: {', '.join(SUPPORTED)}")


def _decode(data):
    for enc in ("utf-8-sig", "utf-16") if data[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig",):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("cp1252", "replace")


# Office formats -------------------------------------------------------------

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
TEXT_NS = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"


def _zip_read(z, member, budget):
    """Read one member; `budget` (a one-item list) limits the total unpacked size (zip bombs)."""
    try:
        info = z.getinfo(member)
    except KeyError:
        raise ExtractError(f"The document is incomplete ({member} is missing)") from None
    budget[0] -= info.file_size
    if budget[0] < 0:
        raise ExtractError("The document is too large when unpacked")
    data = z.read(member)
    if len(data) > info.file_size:  # the size in the archive header lied
        raise ExtractError("The document is damaged")
    return data


def office_text(data, ext):
    """Text of .docx (paragraphs, tables), .odt (paragraphs, headings) or .pptx (slide by slide)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ExtractError("The file is damaged or not a real Office document") from None
    budget = [MAX_UNZIPPED]
    with z:
        if ext == "docx":
            root = ElementTree.fromstring(_zip_read(z, "word/document.xml", budget))
            paras = []
            for p in root.iter(W + "p"):
                parts = []
                for node in p.iter():
                    if node.tag == W + "t" and node.text:
                        parts.append(node.text)
                    elif node.tag == W + "tab":
                        parts.append("\t")
                    elif node.tag in (W + "br", W + "cr"):
                        parts.append("\n")
                paras.append("".join(parts))
            return "\n".join(paras).strip()
        if ext == "odt":
            root = ElementTree.fromstring(_zip_read(z, "content.xml", budget))
            paras = ["".join(el.itertext()) for el in root.iter() if el.tag in (TEXT_NS + "p", TEXT_NS + "h")]
            return "\n".join(paras).strip()
        slides = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                        key=lambda n: int(re.search(r"\d+", n.rsplit("/", 1)[1]).group()))
        out = []
        for i, n in enumerate(slides, 1):
            root = ElementTree.fromstring(_zip_read(z, n, budget))
            paras = ["".join(t.text or "" for t in p.iter(A + "t")) for p in root.iter(A + "p")]
            out.append(f"Slide {i}\n" + "\n".join(x for x in paras if x.strip()))
        return "\n\n".join(out).strip()


# PDF -------------------------------------------------------------------------

class Ref:
    __slots__ = ("num",)

    def __init__(self, num):
        self.num = num


class Name(str):
    pass


class Op(str):
    """A content-stream operator such as Tj."""


DELIMS = b"()<>[]{}/%"
WS = b" \t\r\n\f\x00"
_NUM_RE = re.compile(rb"[+-]?(\d+\.?\d*|\.\d+)")
_OBJ_RE = re.compile(rb"(?<!\d)(\d+)\s+(\d+)\s+obj\b")  # the lookbehind keeps a long run of digits from being retried at every digit
_STREAM_RE = re.compile(rb"stream(\r\n|\n|\r)")
_SKIP_RE = re.compile(rb"(?:[ \t\r\n\f\x00]+|%[^\r\n]*)+")


class Lexer:
    """Tokenizer for PDF objects and content streams."""

    def __init__(self, data, pos=0):
        self.d, self.i = data, pos
        self.depth = 0

    def _nest(self):
        self.depth += 1
        if self.depth > MAX_NESTING:
            raise ExtractError("The PDF is damaged (nested too deeply)")

    def skip_ws(self):
        m = _SKIP_RE.match(self.d, self.i)  # whitespace and % comments
        if m:
            self.i = m.end()

    def value(self):
        """Next value; returns Op for bare keywords. None at the end."""
        self.skip_ws()
        d, i = self.d, self.i
        if i >= len(d):
            return None
        c = d[i:i + 1]
        if c == b"/":
            j = i + 1
            while j < len(d) and d[j] not in WS and d[j] not in DELIMS:
                j += 1
            self.i = j
            raw = d[i + 1:j]
            return Name(re.sub(rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), raw).decode("latin-1"))
        if c == b"(":
            return self._literal()
        if d[i:i + 2] == b"<<":
            self.i += 2
            out = {}
            self._nest()
            while True:
                k = self.value()
                if k is None or k == Op(">>"):
                    self.depth -= 1
                    return out
                v = self.value()
                if isinstance(k, str):  # keys are names; anything else is junk
                    out[k] = v
        if d[i:i + 2] == b">>":
            self.i += 2
            return Op(">>")
        if c == b"<":
            j = d.find(b">", i)
            j = len(d) if j < 0 else j
            hexs = re.sub(rb"[^0-9A-Fa-f]", b"", d[i + 1:j])
            if len(hexs) % 2:
                hexs += b"0"
            self.i = j + 1
            return bytes.fromhex(hexs.decode())
        if c == b"[":
            self.i += 1
            arr = []
            self._nest()
            while True:
                v = self.value()
                if v is None or v == Op("]"):
                    self.depth -= 1
                    return arr
                arr.append(v)
        if c in (b"]", b"{", b"}"):
            self.i += 1
            return Op(c.decode())
        m = _NUM_RE.match(d, i)
        if m and (m.end() >= len(d) or d[m.end()] in WS or d[m.end()] in DELIMS):
            self.i = m.end()
            num = float(m.group()) if b"." in m.group() else int(m.group())
            # "n g R" is a reference
            save = self.i
            m2 = re.compile(rb"\s+(\d+)\s+R(?![^\s\[\]<>/()])").match(d, self.i)
            if m2 and isinstance(num, int):
                self.i = m2.end()
                return Ref(num)
            self.i = save
            return num
        j = i
        while j < len(d) and d[j] not in WS and d[j] not in DELIMS:
            j += 1
        if j == i:
            j = i + 1
        self.i = j
        word = d[i:j].decode("latin-1")
        if word in ("true", "false"):
            return word == "true"
        return Op(word)  # also "null": None would end dicts and arrays early

    def _literal(self):
        d, i, depth, out = self.d, self.i + 1, 1, bytearray()
        esc = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}
        while i < len(d):
            c = d[i]
            if c == 0x5C:  # backslash
                i += 1
                if i >= len(d):
                    break
                c = d[i]
                if c in esc:
                    out.append(esc[c])
                elif 0x30 <= c <= 0x37:
                    j = i
                    while j < len(d) and j < i + 3 and 0x30 <= d[j] <= 0x37:
                        j += 1
                    out.append(int(d[i:j], 8) & 0xFF)
                    i = j - 1
                elif c in (13, 10):  # line continuation
                    if c == 13 and i + 1 < len(d) and d[i + 1] == 10:
                        i += 1
                else:
                    out.append(c)
            elif c == 0x28:
                depth += 1
                out.append(c)
            elif c == 0x29:
                depth -= 1
                if depth == 0:
                    i += 1
                    break
                out.append(c)
            else:
                out.append(c)
            i += 1
        self.i = i
        return bytes(out)


def _decode_stream(sdict, raw):
    """Decoded stream bytes (at most MAX_STREAM); b"" for filters without text (images)."""
    filters = sdict.get("Filter")
    filters = filters if isinstance(filters, list) else [filters] if filters else []
    for f in filters:
        if f in ("FlateDecode", "Fl"):
            try:
                raw = zlib.decompressobj().decompress(raw, MAX_STREAM)
            except zlib.error:
                return b""
        elif f in ("ASCII85Decode", "A85"):
            raw = raw.strip()
            raw = raw[2:] if raw.startswith(b"<~") else raw
            raw = raw[:-2] if raw.endswith(b"~>") else raw
            try:
                raw = base64.a85decode(raw)
            except ValueError:
                return b""
        elif f in ("ASCIIHexDecode", "AHx"):
            raw = bytes.fromhex(re.sub(rb"[^0-9A-Fa-f]", b"", raw.split(b">")[0]).decode())
        else:
            return b""  # images (DCT, JBIG2, …) and LZW carry no text we can read
    return raw


class PDF:
    def __init__(self, data):
        self.data = data
        self.raw = {}       # num -> ("stream", dict, bytes) or ("bytes", bytes), parsed lazily
        self.cache = {}
        self.fonts = {}     # font object number -> Font, shared by all pages
        self.decoded = 0    # bytes decompressed so far (limit: MAX_DECODED)
        self._scan()

    def decode(self, sdict, raw):
        """_decode_stream with a limit on the total output (decompression bombs)."""
        out = _decode_stream(sdict, raw)
        self.decoded += len(out)
        if self.decoded > MAX_DECODED:
            raise ExtractError("The PDF is too large when unpacked")
        return out

    def font(self, ref):
        """Font for a reference, parsed once per document."""
        key = ref.num if isinstance(ref, Ref) else id(ref)
        if key not in self.fonts:
            self.fonts[key] = Font(self, ref)
        return self.fonts[key]

    def _scan(self):
        d, pos = self.data, 0
        no_endstream = len(d) + 1  # no "endstream" at or after this position (saves rescanning the file)
        while True:
            m = _OBJ_RE.search(d, pos)
            if not m:
                break
            num, start = int(m.group(1)), m.end()
            end = d.find(b"endobj", start)
            if end < 0:
                break
            s = _STREAM_RE.search(d, start, end + 6)
            if s and d.rfind(b">>", start, s.start()) >= 0:
                lex = Lexer(d[start:s.start()])
                obj = lex.value()
                stream_start = s.end()
                length = obj.get("Length") if isinstance(obj, dict) else None
                stop = d.find(b"endstream", stream_start) if stream_start < no_endstream else -1
                if stop < 0:
                    no_endstream = min(no_endstream, stream_start)
                if isinstance(length, int) and 0 <= length and d[stream_start + length:stream_start + length + 30].lstrip().startswith(b"endstream"):
                    raw = d[stream_start:stream_start + length]
                else:  # broken file: up to endstream, or without one up to this object's endobj
                    raw = d[stream_start:stop if stop >= 0 else max(end, stream_start)].rstrip(b"\r\n")
                self.raw[num] = ("stream", obj, raw)
                after = stop if stop >= 0 else stream_start
                end = d.find(b"endobj", after)
                pos = (end if end >= 0 else len(d)) + 6
            else:
                self.raw[num] = ("bytes", d[start:end])
                pos = end + 6
        # objects packed inside object streams (PDF 1.5+)
        for num, entry in list(self.raw.items()):
            if entry[0] == "stream" and isinstance(entry[1], dict) and entry[1].get("Type") == "ObjStm":
                sd, data = entry[1], self.decode(entry[1], entry[2])
                first, n = sd.get("First", 0), sd.get("N", 0)
                if not isinstance(first, int) or not isinstance(n, int):
                    continue
                head = re.findall(rb"\d+", data[:first])
                pairs = [(int(head[k]), int(head[k + 1])) for k in range(0, min(len(head), 2 * n) - 1, 2)]
                pairs.sort(key=lambda p: p[1])  # by offset: slices never overlap, so they add up to at most len(data)
                for k, (onum, off) in enumerate(pairs):
                    stop = first + pairs[k + 1][1] if k + 1 < len(pairs) else len(data)
                    self.raw.setdefault(onum, ("bytes", data[first + off:stop]))

    def get(self, num):
        if num in self.cache:
            return self.cache[num]
        entry = self.raw.get(num)
        if entry is None:
            val = None
        elif entry[0] == "stream":
            val = entry[1] if isinstance(entry[1], dict) else {}
        else:
            val = Lexer(entry[1]).value()
        self.cache[num] = val
        return val

    def resolve(self, v, depth=0):
        while isinstance(v, Ref) and depth < 20:
            v = self.get(v.num)
            depth += 1
        return v

    def stream_of(self, v):
        """Decoded bytes of a stream given by reference."""
        if isinstance(v, Ref) and self.raw.get(v.num, ("",))[0] == "stream":
            _, sd, raw = self.raw[v.num]
            if isinstance(sd.get("Length"), Ref):  # indirect length: trust the endstream scan
                pass
            return self.decode({k: self.resolve(x) for k, x in sd.items()}, raw)
        return b""

    def pages(self):
        root = None
        for num in sorted(self.raw):
            o = self.get(num)
            if isinstance(o, dict) and o.get("Type") == "Catalog":
                root = o
        out, seen = [], set()

        def walk(node_ref, inherited, depth):
            node = self.resolve(node_ref)
            if not isinstance(node, dict) or id(node) in seen or depth > MAX_NESTING:
                return
            seen.add(id(node))
            res = node.get("Resources", inherited)
            if node.get("Type") == "Pages" or "Kids" in node:
                kids = self.resolve(node.get("Kids"))
                for kid in kids if isinstance(kids, list) else []:
                    walk(kid, res, depth + 1)
            else:
                out.append((node, res))

        if root:
            walk(root.get("Pages"), None, 0)
        if not out:  # broken page tree: take every page object
            out = [(o, o.get("Resources")) for o in (self.get(n) for n in sorted(self.raw))
                   if isinstance(o, dict) and o.get("Type") == "Page"]
        return out


def parse_cmap(data):
    """ToUnicode CMap -> (code -> text, code length in bytes)."""
    mapping, nbytes, work = {}, 1, 0
    text = data.decode("latin-1")
    cs = re.search(r"begincodespacerange\s*<([0-9A-Fa-f]+)>", text)
    if cs:
        nbytes = max(1, len(cs.group(1)) // 2)

    def u(h):
        b = bytes.fromhex(h if len(h) % 2 == 0 else h + "0")
        try:
            return b.decode("utf-16-be")
        except UnicodeDecodeError:
            return ""

    for block in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", block):
            mapping[int(src, 16)] = u(dst)
            nbytes = max(nbytes, len(src) // 2) if not cs else nbytes
    for block in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
        for lo, hi, rest in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(\[[^\]]*\]|<[0-9A-Fa-f]+>)", block):
            lo_i, hi_i = int(lo, 16), int(hi, 16)
            if hi_i - lo_i > 65535 or hi_i < lo_i:
                continue
            work += hi_i - lo_i + 1
            if work > MAX_CMAP:  # hostile map: stop instead of burning CPU
                break
            if rest.startswith("["):
                for k, h in enumerate(re.findall(r"<([0-9A-Fa-f]*)>", rest)):
                    mapping[lo_i + k] = u(h)
            else:
                start = bytes.fromhex(rest[1:-1] if len(rest[1:-1]) % 2 == 0 else rest[1:-1] + "0")
                for k in range(hi_i - lo_i + 1):
                    b = start[:-1] + bytes([(start[-1] + k) & 0xFF]) if start else b""
                    try:
                        mapping[lo_i + k] = b.decode("utf-16-be")
                    except UnicodeDecodeError:
                        pass
    return mapping, nbytes


class Font:
    def __init__(self, pdf, ref):
        f = pdf.resolve(ref) or {}
        self.cmap, self.nbytes = None, 1
        tu = f.get("ToUnicode") if isinstance(f, dict) else None
        if isinstance(tu, Ref):
            data = pdf.stream_of(tu)
            if data:
                self.cmap, self.nbytes = parse_cmap(data)
        self.two_byte = isinstance(f, dict) and f.get("Subtype") == "Type0"
        if self.two_byte and self.cmap is not None:
            self.nbytes = 2
        enc = pdf.resolve(f.get("Encoding")) if isinstance(f, dict) else None
        self.codec = "mac_roman" if enc == "MacRomanEncoding" else "cp1252"

    def decode(self, s):
        if self.cmap is not None:
            n, out = self.nbytes, []
            for k in range(0, len(s) - n + 1, n):
                out.append(self.cmap.get(int.from_bytes(s[k:k + n], "big"), ""))
            return "".join(out)
        if self.two_byte:
            return ""  # glyph ids without a map: not readable
        return s.decode(self.codec, "replace")


def _content_text(pdf, data, resources, depth=0):
    res = pdf.resolve(resources) or {}
    font_refs = pdf.resolve(res.get("Font")) if isinstance(res, dict) else None
    font_refs = font_refs if isinstance(font_refs, dict) else {}
    xobjects = pdf.resolve(res.get("XObject")) if isinstance(res, dict) else None
    xobjects = xobjects if isinstance(xobjects, dict) else {}
    fonts, font, out, stack = {}, None, [], []
    # Text position, to tell a word gap from a run that merely continues the same word:
    # line_x/line_y = start of the current text line (user space), scale = Tm's x scale,
    # size = font size, chars = characters drawn since the line start.
    pos = {"x": None, "y": None, "scale": 1.0, "size": 10.0, "chars": 0}
    lex = Lexer(data)

    def emit(t):
        if t:
            out.append(t)
            pos["chars"] += len(t)

    def newline():
        if out and not out[-1].endswith("\n"):
            out.append("\n")

    def move(dx, same_line):
        """New line start dx (text space) to the right of the old one."""
        if not same_line:
            newline()
        elif out and not out[-1].endswith((" ", "\n")):
            # glyphs are ~0.5 em wide on average; a clearly larger jump is a gap between words
            if dx > (pos["chars"] * 0.5 + 0.3) * pos["size"] or dx < 0:
                out.append(" ")
        pos["chars"] = 0

    while True:
        v = lex.value()
        if v is None:
            break
        if not isinstance(v, Op):
            stack.append(v)
            continue
        op = str(v)
        num = len(stack) >= 2 and all(isinstance(x, (int, float)) for x in stack[-2:])
        if op == "Tf" and len(stack) >= 2 and isinstance(stack[-2], str):
            name = stack[-2]
            if name not in fonts:
                fonts[name] = pdf.font(font_refs.get(name))
            font = fonts[name]
            if isinstance(stack[-1], (int, float)) and stack[-1]:
                pos["size"] = abs(stack[-1])
        elif op in ("Tj", "'", '"') and stack and isinstance(stack[-1], bytes) and font:
            if op != "Tj":
                newline()
                pos["chars"] = 0
            emit(font.decode(stack[-1]))
        elif op == "TJ" and stack and isinstance(stack[-1], list) and font:
            for item in stack[-1]:
                if isinstance(item, bytes):
                    emit(font.decode(item))
                elif isinstance(item, (int, float)) and item < -250 and out and not out[-1].endswith((" ", "\n")):
                    out.append(" ")
        elif op in ("Td", "TD") and num:
            dx, dy = stack[-2], stack[-1]
            move(dx, abs(dy) <= 0.5)
            if pos["x"] is not None:
                pos["x"] += dx * pos["scale"]
                pos["y"] += dy * pos["scale"]
        elif op == "Tm" and len(stack) >= 6 and all(isinstance(x, (int, float)) for x in stack[-6:]):
            a, e, f = stack[-6], stack[-2], stack[-1]
            if pos["x"] is None:
                newline()
                pos["chars"] = 0
            else:
                scale = abs(a) or 1.0
                move((e - pos["x"]) / scale, abs(f - pos["y"]) <= 0.5 * scale)
            pos.update(x=e, y=f, scale=abs(a) or 1.0)
        elif op == "T*":
            newline()
        elif op == "ET":
            pass
        elif op == "BI":  # inline image: skip binary data up to EI
            j = lex.d.find(b"ID", lex.i)
            k = re.compile(rb"\sEI(\s|$)").search(lex.d, j + 2 if j >= 0 else lex.i)
            lex.i = k.end() if k else len(lex.d)
        elif op == "Do" and stack and isinstance(stack[-1], str) and depth < 3:
            ref = xobjects.get(stack[-1])
            xo = pdf.resolve(ref)
            if isinstance(xo, dict) and xo.get("Subtype") == "Form" and isinstance(ref, Ref):
                newline()
                out.append(_content_text(pdf, pdf.stream_of(ref), xo.get("Resources", resources), depth + 1))
                newline()
        stack.clear()
    return "".join(out)


def pdf_text(data):
    """Text of all pages, pages separated by blank lines."""
    if b"/Encrypt" in data[-4096:] or re.search(rb"/Encrypt\s+\d+\s+\d+\s+R", data):
        raise ExtractError("This PDF is password-protected or encrypted; save an unprotected copy first")
    pdf = PDF(data)
    pages = []
    for page, resources in pdf.pages():
        contents = page.get("Contents")
        refs = pdf.resolve(contents)
        refs = refs if isinstance(refs, list) else [contents]
        stream = b"\n".join(pdf.stream_of(r) for r in refs if isinstance(r, Ref))
        text = _content_text(pdf, stream, resources)
        text = re.sub(r"[ \t ]+", " ", text)
        text = re.sub(r" *\n *", "\n", text).strip()
        pages.append(text)
    return "\n\n".join(p for p in pages if p)
