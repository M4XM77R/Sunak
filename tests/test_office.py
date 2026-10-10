"""Office documents (sunak/office.py, POST /api/office, /api/assistant/doc and the ```sunak-doc``` block): Markdown becomes
.docx, .odt, .xlsx and .ods with the standard library, PDF goes through LibreOffice when it is installed.
Run:  python -m unittest discover tests"""

import io
import json
import pathlib
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock
import xml.etree.ElementTree as ET
import zipfile
from unittest import mock

from sunak import office
from sunak.server import make_server

MD = """# Wochenplan für **Max**

Ein *kurzer* Absatz mit `code`, einem [Link](https://example.com) und snake_case_name.
Zweite Zeile.

## Einkauf
- Milch
- **Brot** frisch
  weiter
1. Eins
2. Zwei

- Danach

## Zahlen
| Name | Menge | Preis |
|---|---|---|
| Äpfel | 3 | 1.5 |
| Birnen & Co | 007 | -2 |
| <x> | | 1e5 |

```
code  block
  indented
```
## Zahlen
| A | B |
|---|---|
| 1 | 2 |
"""
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main", "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "t": "urn:oasis:names:tc:opendocument:xmlns:table:1.0", "o": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
      "x": "urn:oasis:names:tc:opendocument:xmlns:text:1.0"}


def unzip(data):
    z = zipfile.ZipFile(io.BytesIO(data))
    assert z.testzip() is None
    return z


def text_of(el):
    return "".join(el.itertext())


class ParseTest(unittest.TestCase):
    def test_blocks(self):
        blocks = office.parse(MD)
        self.assertEqual([b[0] for b in blocks], ["h", "p", "h", "list", "list", "list", "h", "table", "code", "h", "table"])
        self.assertEqual(blocks[0][1], 1)
        self.assertEqual(office.plain(blocks[0][2]), "Wochenplan für Max")
        self.assertEqual(blocks[0][2][1][1:], (True, False, False))  # bold
        para = office.plain(blocks[1][1])
        self.assertIn("einem Link (https://example.com) und snake_case_name. Zweite Zeile.", para)  # soft line break, no italics in snake_case
        self.assertEqual(blocks[3], ("list", False, [[("Milch", False, False, False)], [("Brot", True, False, False), (" frisch weiter", False, False, False)]]))
        self.assertEqual([b[1] for b in blocks if b[0] == "list"], [False, True, False])
        self.assertEqual(blocks[7][1][2], ["Birnen & Co", "007", "-2"])
        self.assertEqual(blocks[7][1][3], ["<x>", "", "1e5"])
        self.assertEqual(blocks[8], ("code", "code  block\n  indented"))
        self.assertEqual(office.title_of(blocks), "Wochenplan für Max")

    def test_ragged_tables_and_escaped_bars(self):
        t = office.parse("a | b\n--|--\n1 | 2 | 3\nonly \\| one |\n")[0]
        self.assertEqual(t[1], [["a", "b", ""], ["1", "2", "3"], ["only | one", "", ""]])

    def test_refused(self):
        for bad in ("", "  \n ", None, 5):
            with self.assertRaises(office.OfficeError):
                office.parse(bad)
        with self.assertRaises(office.OfficeError):
            office.parse("x" * (office.MAX_CHARS + 1))
        with self.assertRaises(office.OfficeError):
            office.parse("\n".join(["| " + " | ".join("c" * 3 for _ in range(100)) + " |", "|" + "---|" * 100] + ["| " + " | ".join("1" for _ in range(100)) + " |"] * 2100))

    def test_sheet_names(self):
        names = [n for n, _ in office.sheets_of(office.parse(MD))]
        self.assertEqual(names, ["Zahlen", "Zahlen (2)"])
        md = "## A/B:C?*[x]\n|a|\n|-|\n|1|\n\n## " + "L" * 50 + "\n|a|\n|-|\n|1|\n\n|a|\n|-|\n|1|\n"
        names = [n for n, _ in office.sheets_of(office.parse(md))]
        self.assertEqual(names[0], "A B C x")
        self.assertEqual(len(names[1]), 31)
        self.assertEqual(names[2], "Sheet 3")


class FilesTest(unittest.TestCase):
    @mock.patch.object(office, "_now", return_value="2026-01-01T00:00:00Z")  # a second boundary between two renders made this flaky
    def test_docx(self, _now):
        data, ctype = office.render("docx", MD)
        self.assertEqual(ctype, office.FORMATS["docx"])
        z = unzip(data)
        for n in z.namelist():
            ET.fromstring(z.read(n))  # every part is well-formed XML
        self.assertEqual(z.namelist()[0], "[Content_Types].xml")
        doc = ET.fromstring(z.read("word/document.xml"))
        paras = ["".join(p.itertext()) for p in doc.iter(f"{{{NS['w']}}}p")]
        self.assertIn("Wochenplan für Max", paras)
        self.assertEqual(len(list(doc.iter(f"{{{NS['w']}}}tbl"))), 2)
        self.assertEqual(len(list(doc.iter(f"{{{NS['w']}}}tr"))), 4 + 2)
        styles = [e.get(f"{{{NS['w']}}}val") for e in doc.iter(f"{{{NS['w']}}}pStyle")]
        self.assertEqual(styles.count("Heading1"), 1)
        self.assertEqual(styles.count("Heading2"), 3)
        nums = [e.get(f"{{{NS['w']}}}val") for e in doc.iter(f"{{{NS['w']}}}numId")]
        self.assertEqual(nums, ["1", "1", "2", "2", "1"])  # bullets, then the one numbered list, then bullets again
        numbering = z.read("word/numbering.xml").decode()
        self.assertIn('w:numId="2"', numbering)
        self.assertEqual(office.render("docx", MD)[0], data)  # the same text gives the same file

    def test_odt(self):
        data, ctype = office.render("odt", MD)
        self.assertEqual(ctype, office.FORMATS["odt"])
        z = unzip(data)
        self.assertEqual(z.namelist()[0], "mimetype")
        self.assertEqual(z.getinfo("mimetype").compress_type, zipfile.ZIP_STORED)
        self.assertEqual(z.read("mimetype").decode(), office.FORMATS["odt"])
        for n in z.namelist():
            if n != "mimetype":
                ET.fromstring(z.read(n))
        content = ET.fromstring(z.read("content.xml"))
        self.assertEqual(len(list(content.iter(f"{{{NS['t']}}}table"))), 2)
        heads = [text_of(h) for h in content.iter(f"{{{NS['x']}}}h")]
        self.assertEqual(heads, ["Wochenplan für Max", "Einkauf", "Zahlen", "Zahlen"])
        self.assertIn("manifest:full-path=\"content.xml\"", z.read("META-INF/manifest.xml").decode())

    def test_xlsx(self):
        data, ctype = office.render("xlsx", MD)
        self.assertEqual(ctype, office.FORMATS["xlsx"])
        z = unzip(data)
        for n in z.namelist():
            ET.fromstring(z.read(n))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        self.assertEqual([s.get("name") for s in wb.iter(f"{{{NS['s']}}}sheet")], ["Zahlen", "Zahlen (2)"])
        rows = ET.fromstring(z.read("xl/worksheets/sheet1.xml")).iter(f"{{{NS['s']}}}row")
        cells = {c.get("r"): (c.get("t"), text_of(c)) for r in rows for c in r}
        self.assertEqual(cells["A1"], ("inlineStr", "Name"))
        self.assertEqual(cells["B2"], (None, "3"))          # a number is a number
        self.assertEqual(cells["C2"], (None, "1.5"))
        self.assertEqual(cells["B3"], ("inlineStr", "007"))  # but not "007" and not "1e5"
        self.assertEqual(cells["C4"], ("inlineStr", "1e5"))
        self.assertNotIn("B4", cells)                        # an empty cell is left out
        self.assertEqual(cells["A3"], ("inlineStr", "Birnen & Co"))

    def test_ods(self):
        data, ctype = office.render("ods", MD)
        self.assertEqual(ctype, office.FORMATS["ods"])
        z = unzip(data)
        self.assertEqual((z.namelist()[0], z.getinfo("mimetype").compress_type), ("mimetype", zipfile.ZIP_STORED))
        for n in z.namelist():
            if n != "mimetype":
                ET.fromstring(z.read(n))
        content = ET.fromstring(z.read("content.xml"))
        tables = list(content.iter(f"{{{NS['t']}}}table"))
        self.assertEqual([t.get(f"{{{NS['t']}}}name") for t in tables], ["Zahlen", "Zahlen (2)"])
        values = [c.get(f"{{{NS['o']}}}value") for c in tables[0].iter(f"{{{NS['t']}}}table-cell") if c.get(f"{{{NS['o']}}}value-type") == "float"]
        self.assertEqual(values, ["3", "1.5", "-2"])

    def test_hostile_text_stays_valid(self):
        evil = "# T\u0000itle & <b>\n\nA\x0b\x1fB \ud800 </w:t><w:x/> ]]>  \n\n| \"a\" | 'b' |\n|---|---|\n| <script> | &amp; \x07 |\n"
        for fmt in ("docx", "odt", "xlsx", "ods"):
            z = unzip(office.render(fmt, evil)[0])
            for n in z.namelist():
                if n != "mimetype":
                    ET.fromstring(z.read(n))
            joined = b"".join(z.read(n) for n in z.namelist() if n != "mimetype").decode()
            self.assertNotIn("<script>", joined)
            self.assertNotIn("\x00", joined)

    def test_formulas_stay_text(self):
        z = unzip(office.render("xlsx", "|a|b|\n|-|-|\n|=1+1|@SUM(A1)|\n")[0])
        sheet = z.read("xl/worksheets/sheet1.xml").decode()
        self.assertNotIn("<f>", sheet)
        self.assertIn('t="inlineStr"', sheet)

    def test_errors(self):
        with self.assertRaises(office.OfficeError):
            office.render("xlsx", "Nur Text, keine Tabelle")
        with self.assertRaises(office.OfficeError):
            office.render("exe", "x")
        with self.assertRaises(office.OfficeError):
            office.render("docx", "   ")

    def test_formats_follow_the_text_and_libreoffice(self):
        with mock.patch("sunak.office.soffice_path", return_value=None):
            self.assertEqual(office.formats("Nur Text"), ["docx", "odt"])
            self.assertEqual(office.formats(MD), ["docx", "odt", "xlsx", "ods"])
        with mock.patch("sunak.office.soffice_path", return_value="/usr/bin/soffice"):
            self.assertEqual(office.formats("Nur Text"), ["docx", "odt", "pdf"])

    def test_pdf_needs_libreoffice(self):
        with mock.patch("sunak.office.soffice_path", return_value=None), self.assertRaises(office.OfficeError):
            office.render("pdf", MD)
        proc = mock.Mock(pid=4242)
        with mock.patch("sunak.office.soffice_path", return_value="/x/soffice"), mock.patch("sunak.office.subprocess.Popen", return_value=proc) as popen:
            with self.assertRaises(office.OfficeError):  # the program ran but made no file
                office.render("pdf", MD)
        cmd = popen.call_args[0][0]
        self.assertIn("--headless", cmd)
        self.assertTrue(any(a.startswith("-env:UserInstallation=file:///") for a in cmd))
        self.assertTrue(popen.call_args[1].get("start_new_session") or popen.call_args[1].get("creationflags"))  # a group of its own
        with mock.patch("sunak.office.soffice_path", return_value="/x/soffice"), mock.patch("sunak.office.subprocess.Popen", side_effect=OSError):
            with self.assertRaises(office.OfficeError):
                office.render("pdf", MD)

    def test_a_timeout_ends_the_whole_process_group(self):
        proc = mock.Mock(pid=4242)
        proc.wait.side_effect = [subprocess.TimeoutExpired("soffice", 1), None]
        with mock.patch("sunak.office.soffice_path", return_value="/x/soffice"), mock.patch("sunak.office.subprocess.Popen", return_value=proc), \
                mock.patch("sunak.office.os.killpg", create=True) as killpg, mock.patch("sunak.office.subprocess.run") as run:
            with self.assertRaises(office.OfficeError) as cm:
                office.render("pdf", MD)
        self.assertIn("in time", str(cm.exception))
        self.assertTrue(killpg.called or run.called)  # killpg (Linux, macOS) or taskkill /T (Windows)
        proc.kill.assert_called()


class SpeedTest(unittest.TestCase):
    """Hostile Markdown must cost time in proportion to its size (it used to backtrack quadratically)."""
    LIMIT = 5.0

    def timed(self, text, fmt="docx"):
        t = time.monotonic()
        office.render(fmt, text)
        took = time.monotonic() - t
        self.assertLess(took, self.LIMIT, text[:20])
        return took

    def test_open_marks_without_partners(self):
        for unit in ("*a ", "**a ", "_a ", "__a ", "[a", "`a ", "[a](", "![](", "*a** ", "**a* ", "_*_*"):
            self.timed(unit * (office.MAX_CHARS // len(unit) - 1))

    def test_many_paragraphs_headings_cells_and_lists(self):
        self.timed("word *x\n\n" * 30000)
        self.timed("# " + "a " * 100000)
        self.timed("#  " + " " * 300000 + "x")
        self.timed("- *a\n" * 60000)
        self.timed("| *a | **b |\n|---|---|\n" + "| *x | _y |\n" * 20000, "xlsx")
        self.timed("[a](b c) " * 40000)
        self.timed("|" * 300000)
        self.timed("- " * 150000)

    def test_a_huge_paragraph_stays_plain_text(self):
        runs = office.inline("**x** " * 10000)
        self.assertEqual(len(runs), 1)  # past MAX_INLINE nothing is looked for
        self.assertEqual(runs[0][1:], (False, False, False))

    def test_the_check_endpoint_takes_a_whole_answer(self):
        self.timed("word " * 70000)  # 350,000 characters are fine


class InlineTest(unittest.TestCase):
    def test_marks(self):
        runs = office.inline("a **b *c* d** e `f` [g](https://x.y) _h_ snake_case 2*3*4")
        self.assertEqual(runs, [("a ", False, False, False), ("b ", True, False, False), ("c", True, True, False), (" d", True, False, False),
                                (" e ", False, False, False), ("f", False, False, True), (" ", False, False, False), ("g", False, False, False),
                                (" (https://x.y)", False, False, False), (" ", False, False, False), ("h", False, True, False),
                                (" snake_case 2*3*4", False, False, False)])
        self.assertEqual(office.inline("**a *b"), [("**a *b", False, False, False)])
        self.assertEqual(office.inline("* a * b"), [("* a * b", False, False, False)])
        self.assertEqual(office.inline("[](x) [a]( b) [a](c d)"), [("[](x) [a]( b) [a](c d)", False, False, False)])
        self.assertEqual(office.plain(office.inline("a\nb **c**")), "a b c")


    @unittest.skipUnless(office.soffice_path(), "LibreOffice is not installed")
    def test_real_libreoffice_opens_every_file(self):
        """The strongest check: LibreOffice itself converts each file (to PDF) without complaint."""
        pdf = office.render("pdf", MD)[0]
        self.assertTrue(pdf.startswith(b"%PDF"))
        for fmt in ("docx", "odt", "xlsx", "ods"):
            with tempfile.TemporaryDirectory(prefix="sunak-t-") as tmp:
                path = f"{tmp}/f.{fmt}"
                with open(path, "wb") as f:
                    f.write(office.render(fmt, MD)[0])
                subprocess.run([office.soffice_path(), f"-env:UserInstallation={pathlib.Path(tmp, 'p').as_uri()}", "--headless", "--convert-to", "pdf", "--outdir", tmp, path],
                               capture_output=True, timeout=120, check=False)
                with open(f"{tmp}/f.pdf", "rb") as f:
                    self.assertTrue(f.read().startswith(b"%PDF"), fmt)


class AnswerTest(unittest.TestCase):
    def test_block_and_answer_parsing(self):
        d = office.parse_block("# Brief\n\nHallo Anna,\n\n- eins\n")
        self.assertEqual((d["title"], d["markdown"].splitlines()[0]), ("Brief", "# Brief"))
        d = office.parse_block(json.dumps({"title": "Mein Titel", "markdown": "Text"}))
        self.assertEqual((d["title"], d["markdown"]), ("Mein Titel", "Text"))
        for bad in ("", "{}", '{"markdown": ""}', "{broken"):
            if bad == "{broken":
                self.assertEqual(office.parse_block(bad)["markdown"], bad)  # not JSON: it is text
            else:
                with self.assertRaises(office.OfficeError):
                    office.parse_block(bad)
        self.assertEqual(office.parse_answer("<think>hm</think>\n```markdown\n# A\n\ntext\n```"), "# A\n\ntext")
        self.assertEqual(office.parse_answer("# A\n\n```py\nx\n```"), "# A\n\n```py\nx\n```")  # an inner fence stays
        with self.assertRaises(office.OfficeError):
            office.parse_answer("<think>only thoughts")


class EndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.srv = make_server("127.0.0.1", 0, cls.tmp.name)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def post(self, path, body, headers=None):
        h = {"Content-Type": "application/json", "X-Requested-With": "sunak", **(headers or {})}
        r = urllib.request.Request(self.base + path, json.dumps(body).encode(), h, method="POST")
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def test_download(self):
        with mock.patch("sunak.server.providers.chat_once", side_effect=AssertionError("no model")), \
                mock.patch("sunak.server.providers.chat_stream", side_effect=AssertionError("no model")):
            status, headers, data = self.post("/api/office", {"markdown": MD, "title": "Plan: Woche/1", "format": "docx"})
            self.assertEqual(status, 200)
            self.assertEqual(headers["Content-Type"], office.FORMATS["docx"])
            self.assertIn("attachment", headers["Content-Disposition"])
            self.assertIn("Plan Woche1.docx", headers["Content-Disposition"])  # no slash or colon in a file name
            self.assertTrue(zipfile.is_zipfile(io.BytesIO(data)))
            status, headers, data = self.post("/api/office", {"markdown": MD, "format": "ods"})
            self.assertEqual((status, "Wochenplan f" in headers["Content-Disposition"] or "Wochenplan" in headers["Content-Disposition"]), (200, True))
            self.assertEqual(self.post("/api/office", {"markdown": "# ", "title": "!!!", "format": "odt"})[0], 200)
            self.assertIn("document.odt", self.post("/api/office", {"markdown": "Text", "title": "!!!", "format": "odt"})[1]["Content-Disposition"])

    def test_errors_are_clear(self):
        for body in ({"markdown": MD, "format": "exe"}, {"markdown": "", "format": "docx"}, {"markdown": "Text", "format": "xlsx"}, {"markdown": 5, "format": "docx"},
                     {"markdown": MD}):
            status, _, data = self.post("/api/office", body)
            self.assertEqual(status, 400, body)
            self.assertTrue(json.loads(data)["error"])
        self.assertIn("table", json.loads(self.post("/api/office", {"markdown": "Text", "format": "ods"})[2])["error"])
        self.assertEqual(self.post("/api/office", {"markdown": MD, "format": "docx"}, {"X-Requested-With": ""})[0], 403)  # CSRF guard like every POST

    def test_the_model_writes_the_document(self):
        seen = []

        def fake(prov, model, messages, options=None):
            seen.append(messages)
            return "<think>ok</think>```markdown\n# Mahnung\n\nSehr geehrte Damen und Herren,\n\n| Posten | Betrag |\n|---|---|\n| A | 5 |\n```"
        with mock.patch("sunak.server.providers.chat_once", fake):
            status, _, data = self.post("/api/assistant/doc", {"text": "eine Mahnung als Tabelle", "model": "ollama::tiny:1b"})
        r = json.loads(data)
        self.assertEqual(status, 200)
        self.assertEqual((r["title"], r["markdown"].splitlines()[0]), ("Mahnung", "# Mahnung"))
        self.assertIn("xlsx", r["formats"])
        self.assertIn("Markdown", seen[0][0]["content"])
        self.assertEqual(seen[0][1]["content"], "eine Mahnung als Tabelle")
        self.assertEqual(self.post("/api/assistant/doc", {"text": " "})[0], 400)
        with mock.patch("sunak.server.providers.chat_once", return_value="<think>only"):
            self.assertEqual(self.post("/api/assistant/doc", {"text": "x", "model": "ollama::tiny:1b"})[0], 400)

    def test_the_block_of_the_chat_model_and_the_answer_as_document(self):
        status, _, data = self.post("/api/assistant/check", {"kind": "doc", "json": "# Liste\n\n- a\n- b\n"})
        r = json.loads(data)
        self.assertEqual((status, r["title"], r["formats"][:2]), (200, "Liste", ["docx", "odt"]))
        self.assertEqual(self.post("/api/assistant/check", {"kind": "doc", "json": "  "})[0], 400)
        self.assertEqual(self.post("/api/assistant/check", {"kind": "other", "json": "x"})[0], 400)

    def test_the_model_is_told_about_documents(self):
        from sunak import intent
        import datetime
        note = intent.abilities(datetime.datetime(2026, 10, 9, 12, 0, tzinfo=datetime.timezone.utc))
        self.assertIn("```sunak-doc", note)
        self.assertIn("document", note)


if __name__ == "__main__":
    unittest.main()
