"""Image generation with simulated Automatic1111 and ComfyUI servers: the requests Sunak sends, the picture
stored in the chat, progress, errors and stopping."""

import base64
import http.client
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from sunak import imagegen, images
from sunak.server import make_server

PNG = b"\x89PNG\r\n\x1a\n" + b"fake picture" * 10


class FakeBackend(BaseHTTPRequestHandler):
    """Answers like Automatic1111 (/sdapi/…) and ComfyUI (/prompt, /history, /view) at once."""
    log = []
    comfy_polls = 0
    comfy_mode = "ok"      # ok | error | never
    a1111_delay = 0.0

    def log_message(self, *a):
        pass

    def send(self, obj, code=200, raw=None):
        data = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "image/png" if raw is not None else "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        cls, path = type(self), urlparse(self.path).path
        cls.log.append(("GET", self.path, None))
        if path == "/sdapi/v1/sd-models":
            return self.send([{"title": "dreamshaper_8.safetensors [879db523c3]", "model_name": "dreamshaper_8"}])
        if path == "/sdapi/v1/progress":
            return self.send({"progress": 0.5})
        if path == "/object_info/CheckpointLoaderSimple":
            return self.send({"CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["sdxl.safetensors", "v15.ckpt"]]}}}})
        if path.startswith("/history/"):
            cls.comfy_polls += 1
            pid = path.rsplit("/", 1)[1]
            if cls.comfy_polls < 2 or cls.comfy_mode == "never":
                return self.send({})
            if cls.comfy_mode == "error":
                return self.send({pid: {"status": {"status_str": "error", "completed": False, "messages": [
                    ["execution_start", {}], ["execution_error", {"exception_message": "CUDA out of memory"}]]}, "outputs": {}}})
            return self.send({pid: {"status": {"status_str": "success", "completed": True}, "outputs": {
                "9": {"images": [{"filename": "sunak_00001_.png", "subfolder": "", "type": "output"}]}}}})
        if path == "/view":
            q = parse_qs(urlparse(self.path).query)
            return self.send(None, raw=PNG if q.get("filename") == ["sunak_00001_.png"] else b"")
        self.send({"detail": "Not Found"}, 404)

    def do_POST(self):
        cls, path = type(self), urlparse(self.path).path
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"null")
        cls.log.append(("POST", path, body))
        if path == "/sdapi/v1/txt2img":
            time.sleep(cls.a1111_delay)
            return self.send({"images": [base64.b64encode(PNG).decode()], "info": json.dumps({"seed": body["seed"], "sd_model_name": "dreamshaper_8"})})
        if path in ("/sdapi/v1/interrupt", "/interrupt", "/queue"):
            return self.send({})
        if path == "/prompt":
            return self.send({"prompt_id": "job-1", "number": 1, "node_errors": {}})
        self.send({"detail": "Not Found"}, 404)


class ImageGenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        imagegen.POLL = 0.05
        cls.fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeBackend)
        threading.Thread(target=cls.fake.serve_forever, daemon=True).start()
        cls.fake_url = f"http://127.0.0.1:{cls.fake.server_address[1]}"
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.data = os.path.join(cls.tmp.name, "data")
        cls.srv = make_server("127.0.0.1", 0, cls.data)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.port = cls.srv.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        imagegen.POLL = 1.0
        for s in (cls.srv, cls.fake):
            s.shutdown()
            s.server_close()
        cls.tmp.cleanup()

    def setUp(self):
        FakeBackend.log = []
        FakeBackend.comfy_polls = 0
        FakeBackend.comfy_mode = "ok"
        FakeBackend.a1111_delay = 0.0

    def call(self, method, path, body=None):
        r = urllib.request.Request(self.base + path, json.dumps(body).encode() if body is not None else None,
                                   {"Content-Type": "application/json", "X-Requested-With": "sunak"}, method=method)
        with urllib.request.urlopen(r, timeout=20) as resp:
            text = resp.read()
            if resp.headers.get("Content-Type", "").startswith("application/x-ndjson"):
                return [json.loads(x) for x in text.decode().splitlines() if x.strip()]
            return json.loads(text) if resp.headers.get("Content-Type", "").startswith("application/json") else text

    def error(self, *a):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.call(*a)
        return e.exception.code, json.loads(e.exception.read())["error"]

    def setup_backend(self, kind, **kw):
        self.call("PUT", "/api/settings", {"image_gen": kind, "image_gen_url": self.fake_url, "image_gen_model": "",
                                           "image_gen_size": 512, "image_gen_steps": 20, **kw})

    def test_dimensions(self):
        self.assertEqual(imagegen.dimensions("square", 512), (512, 512))
        self.assertEqual(imagegen.dimensions("portrait", 512), (448, 640))
        self.assertEqual(imagegen.dimensions("landscape", 1024), (1280, 832))
        self.assertEqual(imagegen.dimensions("nonsense", 999), (512, 512))

    def test_settings_are_checked(self):
        for body in ({"image_gen": "midjourney"}, {"image_gen_size": 600}, {"image_gen_steps": 0},
                     {"image_gen_url": "ftp://x"}):
            self.assertEqual(self.error("PUT", "/api/settings", body)[0], 400, body)
        self.call("PUT", "/api/settings", {"image_gen": "off"})
        s = self.call("POST", "/api/sessions", {})
        self.assertIn("Settings", self.error("POST", "/api/imagine", {"session_id": s["id"], "prompt": "a cat"})[1])

    def test_automatic1111(self):
        self.setup_backend("automatic1111", image_gen_model="dreamshaper_8.safetensors [879db523c3]")
        self.assertEqual(self.call("POST", "/api/imagegen/test", {"type": "automatic1111", "url": self.fake_url})["models"],
                         ["dreamshaper_8.safetensors [879db523c3]"])
        FakeBackend.a1111_delay = 0.3
        s = self.call("POST", "/api/sessions", {})
        events = self.call("POST", "/api/imagine", {"session_id": s["id"], "prompt": "a lighthouse at dusk",
                                                    "negative": "blurry", "aspect": "landscape", "seed": 42})
        self.assertEqual(events[0], {"type": "start", "title": "a lighthouse at dusk"})
        self.assertIn({"type": "progress", "p": 0.5}, events)
        done = events[-1]
        self.assertEqual(done["type"], "done", events)
        self.assertEqual(done["info"], {"backend": "automatic1111", "model": "dreamshaper_8", "seed": 42, "width": 640,
                                        "height": 448, "steps": 20, "prompt": "a lighthouse at dusk", "negative": "blurry"})
        sent = next(b for m, p, b in FakeBackend.log if p == "/sdapi/v1/txt2img")
        self.assertEqual((sent["prompt"], sent["negative_prompt"], sent["width"], sent["height"], sent["steps"], sent["seed"]),
                         ("a lighthouse at dusk", "blurry", 640, 448, 20, 42))
        self.assertEqual(sent["override_settings"], {"sd_model_checkpoint": "dreamshaper_8.safetensors [879db523c3]"})
        self.assertEqual(self.call("GET", f"/api/images/{done['image']}"), PNG)
        msgs = self.call("GET", f"/api/sessions/{s['id']}")["messages"]
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant"])
        self.assertEqual(msgs[0]["content"], "a lighthouse at dusk")
        self.assertEqual(msgs[1]["meta"]["images"], [done["image"]])
        self.assertIn("a lighthouse at dusk", msgs[1]["content"])
        md = self.call("GET", f"/api/sessions/{s['id']}/export?format=md")
        self.assertIn(f"*[Image: {done['image']}]*", md.decode() if isinstance(md, bytes) else str(md))

    def test_comfyui(self):
        self.setup_backend("comfyui")
        self.assertEqual(self.call("POST", "/api/imagegen/test", {"type": "comfyui", "url": self.fake_url})["models"],
                         ["sdxl.safetensors", "v15.ckpt"])
        s = self.call("POST", "/api/sessions", {})
        events = self.call("POST", "/api/imagine", {"session_id": s["id"], "prompt": "a red fox", "aspect": "portrait"})
        self.assertEqual(events[-1]["type"], "done", events)
        self.assertEqual((events[-1]["info"]["model"], events[-1]["info"]["width"], events[-1]["info"]["height"]),
                         ("sdxl.safetensors", 448, 640))
        wf = next(b for m, p, b in FakeBackend.log if p == "/prompt")["prompt"]
        self.assertEqual(wf["4"]["inputs"]["ckpt_name"], "sdxl.safetensors")
        self.assertEqual(wf["6"]["inputs"]["text"], "a red fox")
        self.assertEqual(wf["3"]["inputs"]["seed"], events[-1]["info"]["seed"])
        self.assertEqual(self.call("GET", f"/api/images/{events[-1]['image']}"), PNG)
        # an error inside ComfyUI reaches the user, the chat keeps only the prompt
        FakeBackend.comfy_polls = 0
        FakeBackend.comfy_mode = "error"
        s2 = self.call("POST", "/api/sessions", {})
        events = self.call("POST", "/api/imagine", {"session_id": s2["id"], "prompt": "x"})
        self.assertEqual(events[-1], {"type": "error", "error": "ComfyUI: CUDA out of memory"})
        self.assertEqual([m["role"] for m in self.call("GET", f"/api/sessions/{s2['id']}")["messages"]], ["user"])

    def test_unreachable_and_wrong_backend(self):
        self.call("PUT", "/api/settings", {"image_gen": "automatic1111", "image_gen_url": "http://127.0.0.1:9"})
        s = self.call("POST", "/api/sessions", {})
        ev = self.call("POST", "/api/imagine", {"session_id": s["id"], "prompt": "x"})[-1]
        self.assertEqual(ev["type"], "error")
        self.assertIn("Cannot reach Automatic1111 at http://127.0.0.1:9", ev["error"])
        # a server that is not Automatic1111 with --api answers 404
        code, err = self.error("POST", "/api/imagegen/test", {"type": "automatic1111", "url": self.fake_url + "/nothing"})
        self.assertEqual((code, "--api" in err), (400, True))

    def test_stop_interrupts_the_backend(self):
        self.setup_backend("comfyui", image_gen_model="v15.ckpt")
        FakeBackend.comfy_mode = "never"
        s = self.call("POST", "/api/sessions", {})
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/api/imagine", json.dumps({"session_id": s["id"], "prompt": "slow"}),
                     {"Content-Type": "application/json", "X-Requested-With": "sunak"})
        resp = conn.getresponse()
        self.assertEqual(json.loads(resp.readline())["type"], "start")
        json.loads(resp.readline())  # a progress event
        resp.close()
        conn.close()  # Stop button
        for _ in range(100):
            if any(p == "/interrupt" for m, p, b in FakeBackend.log):
                break
            time.sleep(0.05)
        self.assertIn(("POST", "/queue", {"delete": ["job-1"]}), FakeBackend.log)
        self.assertTrue(any(p == "/interrupt" for m, p, b in FakeBackend.log))

    def test_stop_interrupts_automatic1111(self):
        self.setup_backend("automatic1111")
        FakeBackend.a1111_delay = 2
        s = self.call("POST", "/api/sessions", {})
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/api/imagine", json.dumps({"session_id": s["id"], "prompt": "slow"}),
                     {"Content-Type": "application/json", "X-Requested-With": "sunak"})
        resp = conn.getresponse()
        json.loads(resp.readline())
        resp.close()
        conn.close()
        for _ in range(60):
            if any(p == "/sdapi/v1/interrupt" for m, p, b in FakeBackend.log):
                break
            time.sleep(0.05)
        self.assertTrue(any(p == "/sdapi/v1/interrupt" for m, p, b in FakeBackend.log))

    def test_generated_pictures_are_not_sent_to_the_model(self):
        name = images.store(self.data, PNG)
        hist = [{"role": "user", "content": "a cat", "meta": {"imagine": {}}},
                {"role": "assistant", "content": "[Picture made with ComfyUI: a cat]", "meta": {"images": [name]}}]
        msgs = images.attach(self.data, hist, [dict(m) for m in hist])
        self.assertNotIn("images", msgs[1])
        self.assertEqual(msgs[1]["content"], "[Picture made with ComfyUI: a cat]")


if __name__ == "__main__":
    unittest.main()
