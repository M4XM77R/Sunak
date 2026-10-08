"""Tests for text extraction (PDF, Office) and the knowledge-base helpers.
The test files are built here, so the repository needs no binary fixtures."""

import io
import tempfile
import unittest
import zipfile
import zlib

from sunak import knowledge
from sunak.db import DB
from sunak.extract import ExtractError, extract_text, parse_cmap


def stream_obj(num, data, extra="", compress=True):
    if compress:
        data = zlib.compress(data)
        extra += " /Filter /FlateDecode"
    return b"%d 0 obj\n<< /Length %d%s >>\nstream\n" % (num, len(data), extra.encode()) + data + b"\nendstream\nendobj\n"


def plain_obj(num, body):
    return b"%d 0 obj\n%s\nendobj\n" % (num, body.encode())


def make_pdf():
    """Two pages: a Type1 font with literal strings, TJ kerning, a form XObject and inherited
    resources; then a Type0 font with a ToUnicode CMap whose objects sit in an object stream."""
    page1 = (b"BT /F1 12 Tf 72 720 Td (Hello \\(World\\)) Tj 0 -14 Td [(Sec) 20 (ond) -400 (line)] TJ "
             b"T* (Gr\\366\\337e) Tj ET\nq /X1 Do Q")
    form = b"BT /F1 10 Tf 1 0 0 1 72 600 Tm (Footer text) Tj ET"
    cmap = (b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
            b"1 begincodespacerange <0000> <FFFF> endcodespacerange\n"
            b"1 beginbfchar <0001> <0048> endbfchar\n"
            b"2 beginbfrange <0002> <0003> <00E9> <0004> <0005> [<20AC> <0021>] endbfrange\n"
            b"endcmap CMapName currentdict /CMap defineresource pop end end")
    page2 = b"BT /F2 12 Tf 72 700 Td <000100020004> Tj 0 -14 Td <00030005> Tj ET"
    # objects 6 (page 2) and 7 (its font) live in object stream 12
    o6 = b"<< /Type /Page /Parent 2 0 R /Contents 8 0 R /Resources << /Font << /F2 7 0 R >> >> >>"
    o7 = b"<< /Type /Font /Subtype /Type0 /BaseFont /Fake /Encoding /Identity-H /ToUnicode 9 0 R >>"
    head = b"6 0 7 %d " % (len(o6) + 1)
    objstm = head + o6 + b"\n" + o7
    parts = [
        b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n",
        plain_obj(1, "<< /Type /Catalog /Pages 2 0 R >>"),
        plain_obj(2, "<< /Type /Pages /Kids [3 0 R 6 0 R] /Count 2 /Resources << /Font << /F1 5 0 R >> "
                     "/XObject << /X1 10 0 R >> >> >>"),
        plain_obj(3, "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents [4 0 R] >>"),
        stream_obj(4, page1),
        plain_obj(5, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"),
        stream_obj(8, page2, compress=False),
        stream_obj(9, cmap),
        stream_obj(10, form, " /Type /XObject /Subtype /Form /Resources << /Font << /F1 5 0 R >> >>"),
        stream_obj(12, objstm, " /Type /ObjStm /N 2 /First %d" % len(head)),
        b"trailer\n<< /Root 1 0 R >>\n%%EOF\n",
    ]
    return b"".join(parts)


def make_zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'


class ExtractTest(unittest.TestCase):
    def test_pdf(self):
        text = extract_text("t.pdf", make_pdf())
        self.assertEqual(text, "Hello (World)\nSecond line\nGröße\nFooter text\n\nHé€\nê!")

    def test_encrypted_pdf_is_refused(self):
        data = make_pdf().replace(b"<< /Root 1 0 R >>", b"<< /Root 1 0 R /Encrypt 11 0 R >>")
        with self.assertRaises(ExtractError):
            extract_text("t.pdf", data)

    def test_pdf_without_text(self):
        data = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [] >>\nendobj\n"
        with self.assertRaisesRegex(ExtractError, "no text"):
            extract_text("scan.pdf", data)

    def test_docx(self):
        doc = (f'<w:document {W}><w:body><w:p><w:r><w:t>Title</w:t></w:r></w:p>'
               '<w:p><w:r><w:t xml:space="preserve">A </w:t></w:r><w:r><w:t>b</w:t><w:tab/><w:t>c</w:t></w:r></w:p>'
               '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cell</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')
        self.assertEqual(extract_text("a.docx", make_zip({"word/document.xml": doc})), "Title\nA b\tc\nCell")

    def test_odt(self):
        xml = ('<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
               'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:text>'
               '<text:h>Head</text:h><text:p>Para <text:span>one</text:span></text:p></office:text></office:body>'
               '</office:document-content>')
        self.assertEqual(extract_text("a.odt", make_zip({"content.xml": xml})), "Head\nPara one")

    def test_pptx_slides_in_order(self):
        def slide(t):
            return f'<p:sld xmlns:p="x" {A}><a:p><a:r><a:t>{t}</a:t></a:r></a:p></p:sld>'
        data = make_zip({"ppt/slides/slide10.xml": slide("ten"), "ppt/slides/slide2.xml": slide("two")})
        self.assertEqual(extract_text("a.pptx", data), "Slide 1\ntwo\n\nSlide 2\nten")

    def test_text_html_and_binary(self):
        self.assertEqual(extract_text("a.md", "# Hi ü".encode()), "# Hi ü")
        self.assertEqual(extract_text("a.txt", "Grüße".encode("cp1252")), "Grüße")
        self.assertIn("World", extract_text("a.html", b"<html><body><p>World</p><script>x</script></body></html>"))
        with self.assertRaises(ExtractError):
            extract_text("a.exe", b"MZ\x00\x00\x01")
        with self.assertRaises(ExtractError):
            extract_text("a.docx", b"not a zip")

    def test_hostile_files_fail_cleanly(self):
        """Damaged or malicious files raise ExtractError quickly, never anything else."""
        deep_kids = "".join(f"{i} 0 obj\n<< /Type /Pages /Kids [{i + 1} 0 R] >>\nendobj\n" for i in range(2, 1500))
        cases = {
            "deep.pdf": b"%PDF-1.4\n1 0 obj\n" + b"[" * 5000 + b"\nendobj\n",
            "kids.pdf": ("%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n" + deep_kids).encode(),
            "key.pdf": b"%PDF-1.4\n1 0 obj\n<< [1] 2 /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Kids 5 >>\nendobj\n",
            "missing.docx": make_zip({"other.xml": "<x/>"}),
            "badxml.docx": make_zip({"word/document.xml": "<w:document"}),
            "trunc.pptx": make_zip({"ppt/slides/slide1.xml": "x" * 100})[:60],
        }
        for name, data in cases.items():
            with self.assertRaises(ExtractError, msg=name):
                extract_text(name, data)

    def test_decompression_bombs_are_bounded(self):
        import time
        bomb = zlib.compress(b"\x00" * (200 * 1024 * 1024), 9)  # ~200 KB that unpack to 200 MB
        pdf = (b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] >>\nendobj\n"
               b"3 0 obj\n<< /Type /Page /Contents 4 0 R >>\nendobj\n" + stream_obj(4, b"", compress=False).replace(b"<< /Length 0", b"<< /Length %d /Filter /FlateDecode" % len(bomb)).replace(b"stream\n\n", b"stream\n" + bomb + b"\n"))
        t = time.time()
        with self.assertRaises(ExtractError):
            extract_text("bomb.pdf", pdf)
        self.assertLess(time.time() - t, 20)
        ranges = " ".join("<0000> <FFFF> <0041>" for _ in range(50))
        t = time.time()
        parse_cmap(f"1 begincodespacerange <0000> <FFFF> endcodespacerange 50 beginbfrange {ranges} endbfrange".encode())
        self.assertLess(time.time() - t, 2)

    def test_parse_cmap(self):
        mapping, n = parse_cmap(b"1 begincodespacerange <00> <FF> endcodespacerange "
                                b"1 beginbfrange <41> <43> <0061> endbfrange")
        self.assertEqual((mapping, n), ({0x41: "a", 0x42: "b", 0x43: "c"}, 1))


class HostileInputTest(unittest.TestCase):
    """Huge or hostile inputs must stay fast (these used to take seconds to minutes)."""

    def test_pdf_scan_with_a_long_run_of_digits(self):
        import time
        from sunak import extract
        start = time.monotonic()
        self.assertIsNone(extract._OBJ_RE.search(b"1" * 100_000))
        self.assertEqual(extract._OBJ_RE.search(b"x 12 0 obj").groups(), (b"12", b"0"))
        self.assertLess(time.monotonic() - start, 10)  # it took minutes before; generous for slow CI runners

    def test_search_words_and_chunks_of_a_huge_text(self):
        import time
        start = time.monotonic()
        words = knowledge.terms(" ".join(f"word{i}x" for i in range(50_000)), limit=5)
        self.assertEqual(words, [f"word{i}x" for i in range(5)])
        chunks = knowledge.chunk("a" * 2_000_000, 1000)
        self.assertEqual(sum(map(len, chunks)), 2_000_000)
        self.assertLess(time.monotonic() - start, 10)


class KnowledgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = DB(self.tmp.name + "/t.db")

    def tearDown(self):
        self.db.conn.close()
        self.tmp.cleanup()

    def test_chunk(self):
        text = "\n\n".join(f"Paragraph {i} " + "word " * 60 for i in range(10))
        chunks = knowledge.chunk(text, 1000)
        self.assertTrue(all(len(c) <= 1000 for c in chunks))
        self.assertEqual(" ".join(" ".join(chunks).split()), " ".join(text.split()))
        long = "x" * 3500
        self.assertEqual("".join(knowledge.chunk(long, 1000)), long)

    def test_terms(self):
        self.assertEqual(knowledge.terms("Was ist die Hauptstadt von Atlantis im Jahr 2024?"),
                         ["hauptstadt", "atlantis", "jahr", "2024"])
        self.assertEqual(knowledge.fts_query(["hauptstadt", "eu"]), '"hauptstadt"* OR "eu"')

    def _fill(self):
        filler = "\n\n".join(f"Filler paragraph {i} about gardening and tomatoes. " * 8 for i in range(40))
        self.db.kb_add("garden.txt", 10, knowledge.chunk(filler))
        self.db.kb_add("atlantis.md", 10, knowledge.chunk("Die Hauptstadt von Atlantis heißt Poseidonia."))

    def test_search_fts_and_fallback(self):
        self._fill()
        for fts in (self.db.fts, False):
            self.db.fts = fts
            hits = knowledge.search(self.db, "Wie heißt die Hauptstadt?")
            self.assertEqual(hits[0]["name"], "atlantis.md", fts)
            self.assertEqual(knowledge.search(self.db, "der die das"), [])

    def test_retrieve_small_kb_sends_everything(self):
        self.db.kb_add("a.txt", 5, ["alpha"])
        self.db.kb_add("b.txt", 5, ["beta"])
        self.assertEqual([c["text"] for c in knowledge.retrieve(self.db, "unrelated")], ["alpha", "beta"])

    def test_retrieve_large_kb_and_replace_delete(self):
        self._fill()
        found = knowledge.retrieve(self.db, "Hauptstadt von Atlantis")
        self.assertEqual(found[0]["name"], "atlantis.md")
        self.assertLessEqual(sum(len(c["text"]) for c in found), knowledge.MAX_CONTEXT_CHARS)
        self.assertIn("[atlantis.md]", knowledge.context(found))
        # same name replaces the old file, delete removes it from the index
        self.db.kb_add("atlantis.md", 10, ["Neue Hauptstadt: Atlantika."])
        self.assertEqual(len([f for f in self.db.kb_files() if f["name"] == "atlantis.md"]), 1)
        self.assertIn("Atlantika", knowledge.search(self.db, "Hauptstadt")[0]["text"])
        fid = self.db.kb_files()[0]["id"]
        self.db.kb_delete(fid)
        self.assertEqual(knowledge.search(self.db, "Hauptstadt"), [])
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM kb_chunks WHERE file_id = ?", (fid,)).fetchone()[0], 0)

    def test_old_database_is_migrated(self):
        import sqlite3
        path = self.tmp.name + "/old.db"
        c = sqlite3.connect(path)
        c.executescript("CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT NOT NULL, model TEXT NOT NULL DEFAULT '', "
                        "system TEXT NOT NULL DEFAULT '', created REAL NOT NULL, updated REAL NOT NULL);"
                        "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, "
                        "role TEXT NOT NULL, content TEXT NOT NULL, model TEXT NOT NULL DEFAULT '', created REAL NOT NULL);"
                        "INSERT INTO sessions VALUES ('abc', 'Old', '', '', 1, 1);"
                        "INSERT INTO messages(session_id, role, content, created) VALUES ('abc', 'user', 'hi', 1);")
        c.commit()
        c.close()
        db = DB(path)
        s = db.get_session("abc")
        self.assertEqual((s["use_kb"], s["messages"][0]["meta"]), (False, {}))
        db.conn.close()

    def test_fts_index_is_rebuilt_when_it_was_missing(self):
        path = self.tmp.name + "/moved.db"
        db = DB(path)
        db.fts = False  # as if this Python had no FTS5
        db.kb_add("z.txt", 5, ["zebra crossing"])
        db.conn.execute("DELETE FROM kb_fts")
        db.conn.commit()
        db.conn.close()
        db = DB(path)
        if db.fts:
            self.assertEqual(knowledge.search(db, "zebra")[0]["name"], "z.txt")
        db.conn.close()

    def test_snippet(self):
        text = "a" * 300 + " Poseidonia is here " + "b" * 300
        s = knowledge.snippet(text, ["poseidonia"])
        self.assertTrue(s.startswith("…") and s.endswith("…") and "Poseidonia" in s)


if __name__ == "__main__":
    unittest.main()
