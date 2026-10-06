"""Speech input: settings, and the recording passed on to a (simulated) Whisper server of both kinds."""

import base64
import email.parser
import email.policy
import json
import struct
import tempfile
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sunak import speech
from sunak.server import make_server

import test_server


def wav(seconds=0.2, rate=16000):
    n = int(seconds * rate)
    return (b"RIFF" + struct.pack("<I", 36 + n * 2) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
            + b"data" + struct.pack("<I", n * 2) + b"\x00\x00" * n)


class Whisper(BaseHTTPRequestHandler):
    """whisper.cpp (/inference) and OpenAI-compatible (/v1/audio/transcriptions) servers in one."""
    requests = []
    answer = None  # raw body instead of the normal answer

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
            b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + body)
        parts = {p.get_param("name", header="content-disposition"): p for p in msg.iter_parts()}
        Whisper.requests.append({"path": self.path, "fields": {k: p.get_content() for k, p in parts.items() if k != "file"},
                                 "file": parts["file"].get_content(), "filename": parts["file"].get_filename()})
        if self.path not in ("/inference", "/v1/audio/transcriptions"):
            self.send_response(404)
            self.end_headers()
            return
        out = Whisper.answer if Whisper.answer is not None else json.dumps({"text": "  Hallo   Welt \n"}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


class SpeechTest(unittest.TestCase):
    call = classmethod(test_server.SunakTest.call.__func__)

    @classmethod
    def setUpClass(cls):
        cls.whisper = ThreadingHTTPServer(("127.0.0.1", 0), Whisper)
        threading.Thread(target=cls.whisper.serve_forever, daemon=True).start()
        cls.wurl = f"http://127.0.0.1:{cls.whisper.server_address[1]}"
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.srv = make_server("127.0.0.1", 0, cls.tmp.name)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        cls.defaults = cls.call("GET", "/api/settings")

    @classmethod
    def tearDownClass(cls):
        for s in (cls.srv, cls.whisper):
            s.shutdown()
            s.server_close()
        cls.tmp.cleanup()

    def setUp(self):
        Whisper.requests.clear()
        Whisper.answer = None
        self.call("PUT", "/api/settings", {"speech_input": "local", "whisper_url": "", "whisper_model": ""})

    def error(self, *args):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.call(*args)
        return e.exception.code, json.loads(e.exception.read())["error"]

    def transcribe(self, audio=None):
        return self.call("POST", "/api/transcribe", {"audio": base64.b64encode(audio or wav()).decode()})

    def test_endpoint_forms(self):
        self.assertEqual(speech.endpoint("http://h:8080/inference/"), ("http://h:8080/inference", "whispercpp"))
        self.assertEqual(speech.endpoint(" http://h:8000/v1 "), ("http://h:8000/v1/audio/transcriptions", "openai"))
        self.assertEqual(speech.endpoint("https://h/x/v1/audio/transcriptions"), ("https://h/x/v1/audio/transcriptions", "openai"))
        for bad in ("http://h:8080", "ftp://h/inference", "localhost:8080/inference", "http:///inference"):
            with self.assertRaises(ValueError):
                speech.endpoint(bad)

    def test_settings(self):
        s = self.defaults
        self.assertEqual((s["speech_input"], s["whisper_url"], s["whisper_model"]), ("local", "", ""))
        self.assertEqual(self.call("PUT", "/api/settings", {"whisper_url": f" {self.wurl}/v1 ", "speech_input": "browser"})["whisper_url"],
                         f"{self.wurl}/v1")
        self.assertEqual(self.error("PUT", "/api/settings", {"speech_input": "cloud"})[0], 400)
        code, err = self.error("PUT", "/api/settings", {"whisper_url": "http://localhost:8080"})
        self.assertIn("full Whisper address", err)
        self.assertEqual(self.call("GET", "/api/settings")["speech_input"], "browser")  # nothing saved by the failed call

    def test_whisper_cpp(self):
        self.call("PUT", "/api/settings", {"whisper_url": f"{self.wurl}/inference"})
        audio = wav()
        self.assertEqual(self.transcribe(audio), {"text": "Hallo Welt"})
        r = Whisper.requests[-1]
        self.assertEqual((r["path"], r["file"], r["filename"]), ("/inference", audio, "speech.wav"))
        self.assertEqual(r["fields"], {"response_format": "json"})

    def test_openai_compatible_with_model(self):
        self.call("PUT", "/api/settings", {"whisper_url": f"{self.wurl}/v1", "whisper_model": "Systran/faster-whisper-small"})
        self.assertEqual(self.call("POST", "/api/transcribe", {"audio": base64.b64encode(wav()).decode(), "language": "de"}),
                         {"text": "Hallo Welt"})
        r = Whisper.requests[-1]
        self.assertEqual(r["path"], "/v1/audio/transcriptions")
        self.assertEqual(r["fields"], {"response_format": "json", "model": "Systran/faster-whisper-small", "language": "de"})
        self.call("PUT", "/api/settings", {"whisper_model": ""})
        self.transcribe()
        self.assertEqual(Whisper.requests[-1]["fields"]["model"], "whisper-1")

    def test_errors(self):
        self.assertIn("No Whisper server", self.error("POST", "/api/transcribe", {"audio": base64.b64encode(wav()).decode()})[1])
        self.call("PUT", "/api/settings", {"whisper_url": f"{self.wurl}/inference"})
        self.assertIn("not a WAV", self.error("POST", "/api/transcribe", {"audio": base64.b64encode(b"OggS" * 30).decode()})[1])
        self.assertIn("damaged", self.error("POST", "/api/transcribe", {"audio": "%%%"})[1])
        self.assertIn("must be text", self.error("POST", "/api/transcribe", {"audio": 5})[1])
        Whisper.answer = b"<html>oops</html>"
        self.assertIn("unexpected answer", self.error("POST", "/api/transcribe", {"audio": base64.b64encode(wav()).decode()})[1])
        Whisper.answer = None
        self.call("PUT", "/api/settings", {"whisper_url": f"{self.wurl}/other/v1"})
        self.assertIn("HTTP 404", self.error("POST", "/api/transcribe", {"audio": base64.b64encode(wav()).decode()})[1])
        self.call("PUT", "/api/settings", {"whisper_url": "http://127.0.0.1:9/inference"})
        self.assertIn("Cannot reach the Whisper server", self.error("POST", "/api/transcribe", {"audio": base64.b64encode(wav()).decode()})[1])
        with self.assertRaises(ValueError):
            speech.transcribe("http://127.0.0.1:9/inference", wav()[:44] + b"\x00" * (speech.MAX_BYTES - 43))

    def test_multipart_layout(self):
        body, ctype = speech.multipart({"a": "1"}, "x.wav", b"\x00\r\n--x", "audio/wav")
        boundary = ctype.split("boundary=")[1]
        self.assertTrue(body.startswith(f"--{boundary}\r\n".encode()) and body.endswith(f"--{boundary}--\r\n".encode()))
        self.assertNotIn(boundary.encode(), b"\x00\r\n--x")


if __name__ == "__main__":
    unittest.main()
