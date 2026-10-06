"""Images in the chat: upload checks, storage, what each backend receives, models without vision."""

import base64
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from sunak import images, providers
from sunak.server import make_server

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 40


def b64(data):
    return base64.b64encode(data).decode()


class Backend(BaseHTTPRequestHandler):
    bodies = {}

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).bodies[self.path] = body
        if self.path == "/api/show":
            caps = {"vis:1b": ["completion", "vision"], "tiny:1b": ["completion"]}.get(body["model"])
            out = json.dumps({"capabilities": caps} if caps else {"details": {}}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            return self.wfile.write(out)
        if self.path == "/v1/chat/completions" and body["model"] == "blind":
            self.send_response(400)
            out = b'{"error": {"message": "image input not supported"}}'
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            return self.wfile.write(out)
        self.send_response(200)
        self.end_headers()
        if self.path == "/api/chat":
            self.wfile.write(json.dumps({"message": {"content": "A cat"}, "done": True}).encode() + b"\n")
        elif self.path == "/v1/chat/completions":
            self.wfile.write(b'data: {"choices": [{"delta": {"content": "A dog"}}]}\n\ndata: [DONE]\n\n')
        else:
            self.wfile.write(b'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "A bird"}}\n\n'
                             b'data: {"type": "message_stop"}\n\n')


class VisionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
        threading.Thread(target=cls.backend.serve_forever, daemon=True).start()
        b = f"http://127.0.0.1:{cls.backend.server_address[1]}"
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.srv = make_server("127.0.0.1", 0, cls.tmp.name)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        cls.call("PUT", "/api/settings", {"providers": [
            {"id": "ollama", "name": "Ollama", "type": "ollama", "base_url": b},
            {"id": "cloud", "name": "Cloud", "type": "openai", "base_url": b + "/v1"},
            {"id": "claude", "name": "Claude", "type": "anthropic", "base_url": b + "/anthropic", "api_key": "sk-x"}]})

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.backend.shutdown()
        cls.tmp.cleanup()

    @classmethod
    def call(cls, method, path, body=None, raw=False):
        req = urllib.request.Request(cls.base + path, data=json.dumps(body).encode() if body is not None else None,
                                     method=method, headers={"Content-Type": "application/json", "X-Requested-With": "sunak"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = r.read()
            if raw:
                return r, data
        text = data.decode()
        if "\n{" in text or text.startswith('{"type"'):
            return [json.loads(x) for x in text.splitlines() if x.strip()]
        return json.loads(text)

    def chat(self, model, content="What is this?", pics=(PNG,), **extra):
        s = self.call("POST", "/api/sessions", {})
        ev = self.call("POST", "/api/chat", {"session_id": s["id"], "model": model, "content": content,
                                             "images": [{"name": "p.png", "data": b64(p)} for p in pics], **extra})
        return s["id"], ev

    def error_of(self, body):
        try:
            self.call("POST", "/api/chat", body)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)["error"]
        self.fail("no error")

    def test_ollama_gets_the_image_and_it_is_stored(self):
        sid, ev = self.chat("ollama::vis:1b")
        self.assertEqual(ev[-1]["type"], "done")
        sent = Backend.bodies["/api/chat"]["messages"][-1]
        self.assertEqual((sent["content"], sent["images"]), ("What is this?", [b64(PNG)]))
        msg = self.call("GET", f"/api/sessions/{sid}")["messages"][0]
        name = msg["meta"]["images"][0]
        self.assertRegex(name, r"^[a-f0-9]{16}\.png$")
        r, data = self.call("GET", f"/api/images/{name}", raw=True)
        self.assertEqual((data, r.headers["Content-Type"]), (PNG, "image/png"))
        md = self.call("GET", f"/api/sessions/{sid}/export?format=md", raw=True)[1].decode()
        self.assertIn(f"[Image: {name}]", md)

    def test_claude_and_openai_formats(self):
        self.chat("claude::claude-opus-5-5", pics=(JPG,))
        content = Backend.bodies["/anthropic/v1/messages"]["messages"][-1]["content"]
        self.assertEqual(content[0], {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64(JPG)}})
        self.assertEqual(content[1], {"type": "text", "text": "What is this?"})
        self.chat("cloud::gpt-x")
        parts = Backend.bodies["/v1/chat/completions"]["messages"][-1]["content"]
        self.assertEqual(parts[1], {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64(PNG)}})

    def test_image_without_text_and_title(self):
        sid, ev = self.chat("ollama::vis:1b", content="")
        self.assertEqual(ev[0]["title"], "Image")
        self.assertEqual(Backend.bodies["/api/chat"]["messages"][-1]["content"], "")

    def test_model_without_vision_is_refused_before_anything_is_stored(self):
        s = self.call("POST", "/api/sessions", {})
        code, err = self.error_of({"session_id": s["id"], "model": "ollama::tiny:1b", "content": "x",
                                   "images": [{"name": "p.png", "data": b64(PNG)}]})
        self.assertEqual(code, 400)
        self.assertIn("cannot see images", err)
        self.assertEqual(self.call("GET", f"/api/sessions/{s['id']}")["messages"], [])
        # an Ollama that does not report capabilities is simply tried
        _, ev = self.chat("ollama::old:1b")
        self.assertEqual(ev[-1]["type"], "done")

    def test_openai_error_gets_a_hint(self):
        _, ev = self.chat("cloud::blind")
        self.assertEqual(ev[-1]["type"], "error")
        self.assertIn("pick one with vision", ev[-1]["error"])

    def test_history_images_for_a_blind_model_become_a_note(self):
        sid, _ = self.chat("ollama::vis:1b")
        self.call("POST", "/api/chat", {"session_id": sid, "model": "ollama::tiny:1b", "content": "and now?"})
        first = [m for m in Backend.bodies["/api/chat"]["messages"] if m["role"] == "user"][0]
        self.assertNotIn("images", first)
        self.assertIn("cannot see images", first["content"])

    def test_only_recent_images_are_sent(self):
        s = self.call("POST", "/api/sessions", {})
        for i in range(images.RECENT + 1):
            self.call("POST", "/api/chat", {"session_id": s["id"], "model": "ollama::vis:1b", "content": f"q{i}",
                                            "images": [{"name": "p.png", "data": b64(PNG)}]})
        users = [m for m in Backend.bodies["/api/chat"]["messages"] if m["role"] == "user"]
        self.assertEqual([("images" in m) for m in users], [False] + [True] * images.RECENT)
        self.assertIn("no longer shown", users[0]["content"])

    def test_edit_keeps_images_and_bad_uploads_are_rejected(self):
        sid, _ = self.chat("ollama::vis:1b")
        msg = self.call("GET", f"/api/sessions/{sid}")["messages"][0]
        self.call("POST", "/api/chat", {"session_id": sid, "model": "ollama::vis:1b", "content": "edited",
                                        "truncate_from": msg["id"], "image_refs": msg["meta"]["images"] + ["../x.png", "zz"]})
        msgs = self.call("GET", f"/api/sessions/{sid}")["messages"]
        self.assertEqual((msgs[0]["content"], msgs[0]["meta"]["images"]), ("edited", msg["meta"]["images"]))
        for pics, text in (([b"GIF87a" * 2 + b"x"], None), ([b"<svg/>"], "only PNG"), ([PNG] * 5, "At most 4")):
            body = {"session_id": sid, "model": "ollama::vis:1b", "content": "x",
                    "images": [{"name": "a", "data": b64(p)} for p in pics]}
            if text:
                self.assertIn(text, self.error_of(body)[1])
        self.assertIn("damaged", self.error_of({"session_id": sid, "model": "ollama::vis:1b",
                                                "images": [{"name": "a", "data": "%%%"}]})[1])

    def test_agent_mode_refuses_images(self):
        s = self.call("POST", "/api/sessions", {})
        os.makedirs(Path(self.tmp.name).parent / "sunak-vision-proj", exist_ok=True)
        self.call("PUT", "/api/settings", {"agent_enabled": True})
        try:
            code, err = None, None
            try:
                self.call("POST", "/api/agent", {"session_id": s["id"], "model": "ollama::vis:1b", "content": "x",
                                                 "folder": str(Path(self.tmp.name).parent / "sunak-vision-proj"),
                                                 "images": [{"name": "p", "data": b64(PNG)}]})
            except urllib.error.HTTPError as e:
                code, err = e.code, json.load(e)["error"]
            self.assertEqual(code, 400)
            self.assertIn("cannot look at images", err)
        finally:
            self.call("PUT", "/api/settings", {"agent_enabled": False})
            os.rmdir(Path(self.tmp.name).parent / "sunak-vision-proj")

    def test_unused_images_are_cleaned_up(self):
        sid, _ = self.chat("ollama::vis:1b")
        name = self.call("GET", f"/api/sessions/{sid}")["messages"][0]["meta"]["images"][0]
        path = Path(self.tmp.name) / "images" / name
        self.call("DELETE", f"/api/sessions/{sid}")
        self.assertTrue(path.exists())  # too new: it could belong to a message being sent right now
        old = time.time() - 7200
        os.utime(path, (old, old))
        self.srv.RequestHandlerClass.app.clean_images()
        self.assertFalse(path.exists())
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.call("GET", f"/api/images/{name}")
        self.assertEqual(e.exception.code, 404)


class UnitTest(unittest.TestCase):
    def test_sniff(self):
        self.assertEqual([images.sniff(x) for x in (PNG, JPG, b"GIF89a..", b"RIFF\0\0\0\0WEBPVP8 ", b"<svg")],
                         ["png", "jpg", "gif", "webp", None])

    def test_anthropic_merges_turns_with_images(self):
        msgs = [{"role": "user", "content": "a"},
                {"role": "user", "content": "b", "images": [{"type": "image/png", "data": "AA=="}]}]
        payload, _ = providers.anthropic_payload({"api_key": "k", "base_url": "http://x"}, "claude-haiku-4-5", msgs)
        self.assertEqual([b["type"] for b in payload["messages"][0]["content"]], ["text", "image", "text"])

    def test_messages_without_images_pass_unchanged(self):
        msgs = [{"role": "user", "content": "x", "tool_calls": [1]}]
        self.assertEqual(providers._with_images(msgs, "openai"), msgs)


if __name__ == "__main__":
    unittest.main()
