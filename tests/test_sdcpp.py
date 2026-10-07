"""Sunak's own image generator (stable-diffusion.cpp) and the model search, against simulated GitHub,
Hugging Face and ollama.com servers and a stand-in for the sd program."""

import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from sunak import modelsearch, sdcpp
from sunak.server import make_server

PNG = b"\x89PNG\r\n\x1a\n" + b"local picture" * 20
EXE = "sd.exe" if os.name == "nt" else "sd"
# stands in for stable-diffusion.cpp: prints a progress bar like it and writes the picture given with -o
FAKE_SD = f"""#!{sys.executable}
import sys, time
a = sys.argv[1:]
arg = lambda f: a[a.index(f) + 1]
if "fail" in arg("-p"):
    print("[ERROR] stable-diffusion.cpp:123  - load model failed", flush=True)
    sys.exit(1)
steps = int(arg("--steps"))
for i in range(1, steps + 1):
    sys.stdout.write("\\r  |=====>     | %d/%d - 0.10s/it" % (i, steps)); sys.stdout.flush()
    time.sleep(3 if "slow" in arg("-p") else 0.05)
open(sys.argv[0] + ".args", "w").write("\\n".join(a))
open(arg("-o"), "wb").write({PNG!r})
"""


def make_zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
    return buf.getvalue()


ENGINE_ZIP = make_zip({f"bin/{EXE}": FAKE_SD, "bin/libstable-diffusion.so": b"lib"})
CUDART_ZIP = make_zip({"cudart64_12.dll": b"dll"})
MODEL = b"weights" * 100_000  # 700 kB
OLLAMA_HTML = """<ul><li x-test-model class="flex"><a href="/library/qwen3" class="group">
<span x-test-search-response-title>qwen3</span><p class="max-w-lg">Qwen3 &amp; friends: dense and MoE models.</p>
<span x-test-capability>tools</span><span x-test-capability>thinking</span><span x-test-size>4b</span><span x-test-size>8b</span>
</a></li><li x-test-model><a href="/library/qwen2.5vl"><span x-test-search-response-title>qwen2.5vl</span>
<p>Vision model.</p><span x-test-capability>vision</span><span x-test-size>7b</span></a></li></ul>"""


class Fake(BaseHTTPRequestHandler):
    hits = []
    cut_after = None  # simulate a broken connection after n bytes of the model

    def log_message(self, *a):
        pass

    def send(self, data, code=200, ctype="application/json", headers=None):
        data = json.dumps(data).encode() if not isinstance(data, bytes) else data
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def file(self, data):
        rng = self.headers.get("Range")
        start = int(rng[6:-1]) if rng else 0
        type(self).hits.append((self.path, start))
        if start >= len(data):
            return self.send(b"", 416)
        body = data[start:]
        cut = type(self).cut_after
        self.send_response(206 if rng else 200)
        self.send_header("Content-Length", str(len(body)))
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
        self.end_headers()
        if cut and not rng:
            self.wfile.write(body[:cut])
            self.wfile.flush()
            self.connection.close()
            return
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        base = f"http://127.0.0.1:{self.server.server_address[1]}"
        if u.path == "/repos/leejet/stable-diffusion.cpp/releases/latest":
            names = ["sd-master-abc-bin-win-avx2-x64.zip", "sd-master-abc-bin-win-cuda12-x64.zip",
                     "sd-master-abc-bin-win-vulkan-x64.zip", "cudart-sd-bin-win-cu12-x64.zip",
                     "sd-master-abc-bin-Darwin-macOS-15.0-arm64.zip", "sd-master-abc-bin-Linux-Ubuntu-24.04-x86_64.zip",
                     "sd-master-abc-bin-Linux-Ubuntu-24.04-x86_64-vulkan.zip", "source.tar.gz"]
            return self.send({"tag_name": "master-abc", "assets": [
                {"name": n, "size": len(CUDART_ZIP if n.startswith("cudart") else ENGINE_ZIP),
                 "browser_download_url": f"{base}/dl/{n}"} for n in names]})
        if u.path.startswith("/dl/"):
            return self.file(CUDART_ZIP if "cudart" in u.path else ENGINE_ZIP)
        if "/resolve/main/" in u.path:
            return self.file(MODEL) if "missing" not in u.path else self.send({"error": "Entry not found"}, 404)
        if u.path == "/api/models":
            q = parse_qs(u.query)
            type(self).hits.append(("search", q))
            if q.get("pipeline_tag") == ["text-to-image"]:
                return self.send([{"id": "someone/dreamy-xl", "downloads": 50, "likes": 3, "pipeline_tag": "text-to-image"}])
            return self.send([{"id": "unsloth/Qwen3-4B-GGUF", "downloads": 900, "likes": 40, "tags": ["gguf"],
                               "pipeline_tag": "text-generation"}, {"id": "bad id"}])
        if u.path in ("/api/models/unsloth/Qwen3-4B-GGUF", "/api/models/someone/dreamy-xl"):
            return self.send({"cardData": {"license": "apache-2.0"}, "gated": False})
        if u.path == "/api/models/unsloth/Qwen3-4B-GGUF/tree/main":
            return self.send([{"type": "file", "path": "Qwen3-4B-Q8_0.gguf", "size": 4_280_000_000},
                              {"type": "file", "path": "Qwen3-4B-Q4_K_M.gguf", "size": 2_500_000_000, "lfs": {"size": 2_500_000_000}},
                              {"type": "file", "path": "mmproj-F16.gguf", "size": 800_000_000},
                              {"type": "file", "path": "big-00001-of-00002.gguf", "size": 9},
                              {"type": "file", "path": "README.md", "size": 10}, {"type": "directory", "path": "x"}])
        if u.path == "/api/models/someone/dreamy-xl/tree/main":
            return self.send([{"type": "file", "path": "dreamy_xl.safetensors", "size": len(MODEL), "lfs": {"size": 6_900_000_000}},
                              {"type": "file", "path": "small.safetensors", "size": 1000}])
        if u.path == "/search":
            return self.send(OLLAMA_HTML.encode(), ctype="text/html")
        self.send({"error": "nope"}, 404)


class SdCppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.fake.serve_forever, daemon=True).start()
        fake_url = f"http://127.0.0.1:{cls.fake.server_address[1]}"
        cls.saved = (sdcpp.GITHUB_API, sdcpp.HF, modelsearch.HF, modelsearch.OLLAMA_WEB)
        sdcpp.GITHUB_API = sdcpp.HF = modelsearch.HF = modelsearch.OLLAMA_WEB = fake_url
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.data = os.path.join(cls.tmp.name, "data")
        cls.srv = make_server("127.0.0.1", 0, cls.data)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        cls.app = cls.srv.RequestHandlerClass.app
        sdcpp.POLL = 0.02

    @classmethod
    def tearDownClass(cls):
        sdcpp.GITHUB_API, sdcpp.HF, modelsearch.HF, modelsearch.OLLAMA_WEB = cls.saved
        sdcpp.POLL = 0.5
        for s in (cls.srv, cls.fake):
            s.shutdown()
            s.server_close()
        cls.tmp.cleanup()

    def setUp(self):
        Fake.hits = []
        Fake.cut_after = None

    def call(self, method, path, body=None):
        r = urllib.request.Request(self.base + path, json.dumps(body).encode() if body is not None else None,
                                   {"Content-Type": "application/json", "X-Requested-With": "sunak"}, method=method)
        with urllib.request.urlopen(r, timeout=30) as resp:
            text = resp.read()
            if resp.headers.get("Content-Type", "").startswith("application/x-ndjson"):
                return [json.loads(x) for x in text.decode().splitlines() if x.strip()]
            return json.loads(text) if resp.headers.get("Content-Type", "").startswith("application/json") else text

    def error(self, *a):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.call(*a)
        return e.exception.code, json.loads(e.exception.read())["error"]

    def test_release_files_for_each_computer(self):
        assets = [{"name": n, "size": 1, "browser_download_url": "u"} for n in (
            "sd-master-abc-bin-win-avx2-x64.zip", "sd-master-abc-bin-win-avx-x64.zip", "sd-master-abc-bin-win-cuda12-x64.zip",
            "sd-master-abc-bin-win-vulkan-x64.zip", "cudart-sd-bin-win-cu12-x64.zip", "sd-master-abc-bin-Darwin-macOS-15.0-arm64.zip",
            "sd-master-abc-bin-Linux-Ubuntu-24.04-x86_64.zip", "sd-master-abc-bin-Linux-Ubuntu-24.04-x86_64-vulkan.zip")]
        names = lambda *a, **kw: [x["name"] for x in sdcpp.rank_assets(assets, *a, **kw)]
        nvidia = {"usable": True, "vendor": "nvidia", "vram_gb": 8}
        win = names("Windows", "x64", gpu_info=nvidia)
        self.assertEqual(win[0], "sd-master-abc-bin-win-cuda12-x64.zip")
        self.assertEqual(win[1:], ["sd-master-abc-bin-win-vulkan-x64.zip", "sd-master-abc-bin-win-avx2-x64.zip",
                                   "sd-master-abc-bin-win-avx-x64.zip"])
        cuda = sdcpp.rank_assets(assets, "Windows", "x64", gpu_info=nvidia)[0]
        self.assertEqual((cuda["extra"]["name"], cuda["size"]), ("cudart-sd-bin-win-cu12-x64.zip", 2))
        self.assertEqual(names("Windows", "x64", gpu_info={"usable": True, "vendor": "amd"})[0], "sd-master-abc-bin-win-vulkan-x64.zip")
        self.assertEqual(names("Windows", "x64")[0], "sd-master-abc-bin-win-avx2-x64.zip")  # no graphics card: CPU
        self.assertEqual(names("Darwin", "arm64"), ["sd-master-abc-bin-Darwin-macOS-15.0-arm64.zip"])
        self.assertEqual(names("Linux", "x64"), ["sd-master-abc-bin-Linux-Ubuntu-24.04-x86_64.zip",
                                                 "sd-master-abc-bin-Linux-Ubuntu-24.04-x86_64-vulkan.zip"])
        self.assertEqual(names("Linux", "arm64"), [])

    def test_install_download_and_generate(self):
        # nothing is set up yet: the picture button stays away, nothing is "missing"
        self.assertEqual(self.call("GET", "/api/settings")["image_status"], {"problem": "", "model": ""})
        local = self.call("GET", "/api/imagegen/local")
        self.assertEqual(local["engine"], {"installed": False})
        self.assertEqual([m["id"] for m in local["models"]], [m["id"] for m in sdcpp.CATALOG])
        self.assertTrue(all("license" in m and not m["installed"] for m in local["models"]))
        # the program: only names from the release are accepted
        opts = self.call("GET", "/api/imagegen/engine")
        self.assertEqual(opts["tag"], "master-abc")
        self.assertTrue(opts["options"])
        self.assertNotIn("url", opts["options"][0])
        self.assertEqual(self.error("POST", "/api/imagegen/engine/install", {"name": "http://evil/x.zip"})[0], 400)
        ev = self.call("POST", "/api/imagegen/engine/install", {"name": opts["options"][0]["name"]})
        self.assertEqual(ev[-1]["type"], "done", ev)
        self.assertTrue(ev[-1]["engine"]["installed"])
        self.assertTrue(self.call("GET", "/api/imagegen/local")["engine"]["installed"])
        # the program alone cannot make pictures: Sunak says a model is missing (this was the reported dead end)
        self.assertEqual(self.call("GET", "/api/settings")["image_status"], {"problem": "no_model", "model": ""})
        # a model: the download breaks off and continues with Range on the next click
        Fake.cut_after = 300_000
        ev = self.call("POST", "/api/imagegen/models/pull", {"id": "sd-turbo"})
        self.assertEqual(ev[-1]["type"], "error", ev)
        self.assertIn("Click Download again", ev[-1]["error"])
        m = next(m for m in self.call("GET", "/api/imagegen/local")["models"] if m["id"] == "sd-turbo")
        self.assertEqual((m["installed"], m["partial"]), (False, True))
        Fake.cut_after = None
        ev = self.call("POST", "/api/imagegen/models/pull", {"id": "sd-turbo"})
        self.assertEqual(ev[-1], {"type": "done", "id": "sd-turbo"})
        self.assertEqual(Fake.hits[-1][1], 300_000)
        self.assertEqual(ev[-2]["completed"], len(MODEL))
        path = os.path.join(self.data, "imagegen", "models", "sd-turbo", "sd_turbo.safetensors")
        with open(path, "rb") as f:
            self.assertEqual(f.read(), MODEL)
        self.assertEqual(self.error("POST", "/api/imagegen/models/pull", {"id": "../../etc"})[0], 400)
        # program and model are there but pictures are still off: choose the model for the user
        self.assertEqual(self.call("GET", "/api/settings")["image_status"], {"problem": "choose", "model": "sd-turbo"})
        if os.name == "nt":
            return  # the stand-in program is a Python script, which Windows cannot start by itself
        # make a picture with the model's own settings (SD-Turbo: 4 steps, cfg 1, 512 px)
        st = self.call("PUT", "/api/settings", {"image_gen": "local", "image_gen_model": "sd-turbo"})["image_status"]
        self.assertEqual(st, {"problem": "", "model": "sd-turbo"})
        s = self.call("POST", "/api/sessions", {})
        ev = self.call("POST", "/api/imagine", {"session_id": s["id"], "prompt": "a red boat", "negative": "fog",
                                                 "aspect": "portrait", "seed": 7})
        self.assertEqual(ev[-1]["type"], "done", ev)
        self.assertEqual(ev[-1]["info"], {"backend": "local", "model": "SD-Turbo", "seed": 7, "width": 448, "height": 640,
                                          "steps": 4, "prompt": "a red boat", "negative": "fog"})
        self.assertTrue(any(e["type"] == "progress" and e["p"] for e in ev))
        self.assertEqual(self.call("GET", f"/api/images/{ev[-1]['image']}"), PNG)
        exe = os.path.join(self.data, "imagegen", "engine", "bin", EXE)
        with open(exe + ".args") as f:
            args = f.read().split("\n")
        self.assertEqual(args[:2], ["-m", path])
        for flag, val in (("--steps", "4"), ("--cfg-scale", "1.0"), ("-W", "448"), ("-H", "640"), ("-s", "7"), ("-n", "fog")):
            self.assertEqual(args[args.index(flag) + 1], val)
        ev = self.call("POST", "/api/imagine", {"session_id": s["id"], "prompt": "fail please"})
        self.assertEqual(ev[-1]["type"], "error")
        self.assertIn("load model failed", ev[-1]["error"])
        # a model that is not downloaded
        self.call("PUT", "/api/settings", {"image_gen_model": "sdxl"})
        ev = self.call("POST", "/api/imagine", {"session_id": s["id"], "prompt": "x"})
        self.assertIn("is not downloaded yet", ev[-1]["error"])
        self.assertEqual(self.call("GET", "/api/settings")["image_status"], {"problem": "choose", "model": "sd-turbo"})
        # delete
        self.call("POST", "/api/imagegen/models/delete", {"id": "sd-turbo"})
        self.assertFalse(os.path.exists(path))
        self.assertEqual(self.call("GET", "/api/settings")["image_status"]["problem"], "no_model")
        self.call("POST", "/api/imagegen/engine/remove")
        self.assertEqual(self.call("GET", "/api/settings")["image_status"]["problem"], "no_engine")

    def test_model_from_the_search(self):
        res = self.call("GET", "/api/models/search?q=dreamy&kind=image")
        self.assertEqual(res, {"ollama": [], "huggingface": [{"repo": "someone/dreamy-xl", "downloads": 50, "likes": 3,
                                                              "pipeline": "text-to-image", "vision": False}], "unreachable": []})
        files = self.call("GET", "/api/models/files?repo=someone/dreamy-xl&kind=image")
        self.assertEqual(files["files"], [{"path": "dreamy_xl.safetensors", "size": 6_900_000_000, "quant": ""}])
        self.assertEqual(files["license"], "apache-2.0")
        self.assertEqual(self.error("POST", "/api/imagegen/models/pull", {"repo": "someone/dreamy-xl", "path": "other.safetensors"})[0], 400)
        sdcpp.custom_entry("someone/dreamy-xl", "dreamy_xl.safetensors")  # valid
        with self.assertRaises(sdcpp.SdError):
            sdcpp.custom_entry("someone/dreamy-xl", "../x.safetensors")
        with self.assertRaises(sdcpp.SdError):
            sdcpp.custom_entry("someone/dreamy-xl", "setup.exe")

    def test_search_chat_models(self):
        res = self.call("GET", "/api/models/search?q=qwen")
        self.assertEqual(res["unreachable"], [])
        self.assertEqual(res["ollama"], [
            {"name": "qwen3", "description": "Qwen3 & friends: dense and MoE models.", "sizes": ["4b", "8b"], "capabilities": ["tools", "thinking"]},
            {"name": "qwen2.5vl", "description": "Vision model.", "sizes": ["7b"], "capabilities": ["vision"]}])
        self.assertEqual([r["repo"] for r in res["huggingface"]], ["unsloth/Qwen3-4B-GGUF"])
        search = next(q for p, q in Fake.hits if p == "search")
        self.assertEqual((search["filter"], search["sort"], search["search"]), (["gguf"], ["downloads"], ["qwen"]))
        files = self.call("GET", "/api/models/files?repo=unsloth/Qwen3-4B-GGUF")
        self.assertEqual(files["files"], [
            {"path": "Qwen3-4B-Q4_K_M.gguf", "size": 2_500_000_000, "quant": "Q4_K_M", "ollama": "hf.co/unsloth/Qwen3-4B-GGUF:Q4_K_M"},
            {"path": "Qwen3-4B-Q8_0.gguf", "size": 4_280_000_000, "quant": "Q8_0", "ollama": "hf.co/unsloth/Qwen3-4B-GGUF:Q8_0"}])
        self.assertEqual(self.error("GET", "/api/models/files?repo=../../x")[0], 400)
        self.assertEqual(modelsearch.approx_gb("8b"), 5.1)
        self.assertEqual(modelsearch.quant("model.IQ4_XS.gguf"), "IQ4_XS")

    def test_search_offline_falls_back_quietly(self):
        saved = (modelsearch.HF, modelsearch.OLLAMA_WEB)
        modelsearch.HF = modelsearch.OLLAMA_WEB = "http://127.0.0.1:9"
        try:
            res = self.call("GET", "/api/models/search?q=qwen")
        finally:
            modelsearch.HF, modelsearch.OLLAMA_WEB = saved
        self.assertEqual((res["ollama"], res["huggingface"], sorted(res["unreachable"])), ([], [], ["huggingface", "ollama"]))


if __name__ == "__main__":
    unittest.main()
