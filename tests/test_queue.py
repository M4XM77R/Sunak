"""First in, first out queue for model requests (sunak/jobqueue.py) and the automatic picture request that
uses it (/api/imagine with `improve`).
Run:  python -m unittest discover tests"""

import http.client
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from sunak import imagegen, jobqueue
from sunak.server import make_server
from test_imagegen import FakeBackend as ImageBackend
from test_server import FakeBackend as ChatBackend, serve


class GateTest(unittest.TestCase):
    def setUp(self):
        self.poll = jobqueue.POLL
        jobqueue.POLL = 0.02

    def tearDown(self):
        jobqueue.POLL = self.poll

    def test_first_in_first_out_with_places(self):
        order, places = [], {}

        def worker(i):
            seen = []
            with jobqueue.slot("fifo", 1, notify=seen.append):
                order.append(i)
                time.sleep(0.15)
            places[i] = seen
        threads = []
        for i in range(4):
            t = threading.Thread(target=worker, args=(i,))
            t.start()
            threads.append(t)
            time.sleep(0.03)
        for t in threads:
            t.join()
        self.assertEqual(order, [0, 1, 2, 3])
        self.assertEqual(places[0], [])                  # was served at once
        self.assertEqual(places[3][0], 3)                # told its place, then moved up
        self.assertEqual(places[3][-1], 0)               # 0 = its turn
        self.assertEqual(places[3], sorted(places[3], reverse=True))
        self.assertEqual(jobqueue.gate("fifo").snapshot(), (0, 0))

    def test_several_slots_run_side_by_side(self):
        running, peak, lock = [0], [0], threading.Lock()

        def worker():
            with jobqueue.slot("wide", 2):
                with lock:
                    running[0] += 1
                    peak[0] = max(peak[0], running[0])
                time.sleep(0.1)
                with lock:
                    running[0] -= 1
        threads = [threading.Thread(target=worker) for _ in range(4)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(peak[0], 2)

    def test_a_request_whose_browser_left_leaves_the_queue(self):
        g = jobqueue.gate("gone", 1)
        g.acquire()  # somebody is being served

        def left(place):
            raise BrokenPipeError
        with self.assertRaises(jobqueue.Cancelled):
            with jobqueue.slot("gone", 1, notify=left):
                self.fail("must not get a place")
        self.assertEqual(g.snapshot(), (1, 0))
        flag = threading.Event()
        flag.set()
        with self.assertRaises(jobqueue.Cancelled):
            with jobqueue.slot("gone", 1, cancelled=flag.is_set):
                self.fail("must not get a place")
        self.assertEqual(g.snapshot(), (1, 0))
        g.release()
        self.assertEqual(g.snapshot(), (0, 0))

    def test_waiting_too_long_gives_up(self):
        g = jobqueue.gate("slow", 1)
        g.acquire()
        with self.assertRaises(jobqueue.Timeout):
            g.acquire(timeout=0.1)
        self.assertEqual(g.snapshot(), (1, 0))
        g.release()

    def test_asking_again_inside_does_not_wait_for_itself(self):
        with jobqueue.slot("again", 1):
            with jobqueue.slot("again", 1):
                pass
        self.assertEqual(jobqueue.gate("again").snapshot(), (0, 0))

    def test_slots_setting(self):
        old = os.environ.get("SUNAK_MODEL_SLOTS")
        try:
            os.environ["SUNAK_MODEL_SLOTS"] = "3"
            self.assertEqual(jobqueue.local_slots(), 3)
            os.environ["SUNAK_MODEL_SLOTS"] = "nonsense"
            self.assertEqual(jobqueue.local_slots(), 1)
        finally:
            os.environ.pop("SUNAK_MODEL_SLOTS", None)
            if old is not None:
                os.environ["SUNAK_MODEL_SLOTS"] = old


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        imagegen.POLL = 0.05
        cls.poll = jobqueue.POLL
        jobqueue.POLL = 0.05
        cls.chat = serve(ThreadingHTTPServer(("127.0.0.1", 0), ChatBackend))
        cls.image = serve(ThreadingHTTPServer(("127.0.0.1", 0), ImageBackend))
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.app = serve(make_server("127.0.0.1", 0, os.path.join(cls.tmp.name, "data")))
        cls.port = cls.app.server_address[1]
        cls.call("PUT", "/api/settings", {
            "providers": [{"id": "ollama", "name": "Ollama", "type": "ollama",
                           "base_url": f"http://127.0.0.1:{cls.chat.server_address[1]}"}],
            "image_gen": "automatic1111", "image_gen_url": f"http://127.0.0.1:{cls.image.server_address[1]}",
            "image_gen_model": "", "image_gen_size": 512, "image_gen_steps": 20})

    @classmethod
    def tearDownClass(cls):
        imagegen.POLL = 1.0
        jobqueue.POLL = cls.poll
        for s in (cls.app, cls.chat, cls.image):
            s.shutdown()
            s.server_close()
        cls.tmp.cleanup()

    @classmethod
    def call(cls, method, path, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{cls.port}{path}", data=json.dumps(body).encode() if body is not None else None,
                                     method=method, headers={"Content-Type": "application/json", "X-Requested-With": "sunak"})
        with urllib.request.urlopen(req, timeout=20) as r:
            text = r.read().decode()
        if r.headers.get("Content-Type", "").startswith("application/x-ndjson"):
            return [json.loads(x) for x in text.splitlines() if x.strip()]
        return json.loads(text)

    def setUp(self):
        ImageBackend.log = []

    def test_picture_request_is_improved_by_the_chat_model_then_painted(self):
        s = self.call("POST", "/api/sessions", {})
        ev = self.call("POST", "/api/imagine", {"session_id": s["id"], "prompt": "Mach mir ein Bild von einem Leuchtturm im Querformat",
                                                "improve": True, "model": "ollama::tiny:1b", "fallback": "einem Leuchtturm", "aspect": "auto"})
        types = [e["type"] for e in ev]
        self.assertEqual(types[0], "start")
        self.assertIn("prompt", types)
        self.assertEqual(types[-1], "done")
        self.assertLess(types.index("prompt"), types.index("done"))
        improved = next(e for e in ev if e["type"] == "prompt")["prompt"]
        self.assertEqual(improved, "Hello from Ollama")  # what the (fake) chat model answered
        system = ChatBackend.last_body["messages"][0]
        self.assertEqual(system["role"], "system")
        self.assertIn("Stable Diffusion", system["content"])
        sent = next(b for m, p, b in ImageBackend.log if p == "/sdapi/v1/txt2img")
        self.assertEqual(sent["prompt"], "Hello from Ollama")
        self.assertGreater(sent["width"], sent["height"])  # "Querformat" was understood
        msgs = self.call("GET", f"/api/sessions/{s['id']}")["messages"]
        self.assertEqual(msgs[0]["content"], "Mach mir ein Bild von einem Leuchtturm im Querformat")  # the user's own words
        gen = msgs[1]["meta"]["imagegen"]
        self.assertEqual((gen["prompt"], gen["request"]), ("Hello from Ollama", msgs[0]["content"]))

    def test_without_a_usable_chat_model_the_plain_description_is_painted(self):
        s = self.call("POST", "/api/sessions", {})
        ev = self.call("POST", "/api/imagine", {"session_id": s["id"], "prompt": "Bild von einer Katze", "improve": True,
                                                "model": "nope::x", "fallback": "einer Katze"})
        self.assertEqual(next(e for e in ev if e["type"] == "prompt")["prompt"], "einer Katze")
        self.assertEqual(ev[-1]["type"], "done")

    def test_clean_prompt(self):
        self.assertEqual(imagegen.clean_prompt('Prompt: "A cat on a roof, golden hour"\n\nThis prompt…', "x"), "A cat on a roof, golden hour")
        self.assertEqual(imagegen.clean_prompt("", "fallback"), "fallback")
        self.assertEqual(imagegen.clean_prompt("y" * 900, "fallback"), "fallback")
        self.assertEqual(imagegen.aspect_from_text("a portrait of a cat"), "portrait")
        self.assertEqual(imagegen.aspect_from_text("ein Bild"), "square")

    def read_events(self, conn, until):
        """Lines of an NDJSON response until an event of type `until`."""
        resp = conn.getresponse()
        events = []
        while True:
            line = resp.readline()
            if not line:
                break
            events.append(json.loads(line))
            if events[-1]["type"] == until:
                break
        return events

    def test_chat_waits_in_line_when_the_model_is_busy(self):
        s = self.call("POST", "/api/sessions", {"model": "ollama::tiny:1b"})
        key = "chat:ollama"
        g = jobqueue.gate(key, 1)
        g.acquire()  # another user's request is being answered
        try:
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            conn.request("POST", "/api/chat", json.dumps({"session_id": s["id"], "content": "Hi", "model": "ollama::tiny:1b"}),
                         {"Content-Type": "application/json", "X-Requested-With": "sunak"})
            resp = conn.getresponse()
            self.assertEqual(json.loads(resp.readline())["type"], "start")
            ev = json.loads(resp.readline())
            self.assertEqual((ev["type"], ev["position"]), ("queued", 1))
            g.release()
            rest = []
            while True:
                line = resp.readline()
                if not line:
                    break
                rest.append(json.loads(line))
            types = [e["type"] for e in rest]
            self.assertIn(("queued", 0), [(e["type"], e.get("position")) for e in rest])
            self.assertEqual(types[-1], "done")
            self.assertEqual("".join(e["t"] for e in rest if e["type"] == "text"), "Hello from Ollama")
        finally:
            if g.snapshot()[0]:
                g.release()
        self.assertEqual(g.snapshot(), (0, 0))

    def test_a_closed_browser_frees_the_place_in_line(self):
        s = self.call("POST", "/api/sessions", {"model": "ollama::tiny:1b"})
        g = jobqueue.gate("chat:ollama", 1)
        g.acquire()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            conn.request("POST", "/api/chat", json.dumps({"session_id": s["id"], "content": "Hi", "model": "ollama::tiny:1b"}),
                         {"Content-Type": "application/json", "X-Requested-With": "sunak"})
            resp = conn.getresponse()
            resp.readline()
            resp.readline()  # queued
            self.assertEqual(g.snapshot(), (1, 1))
            resp.close()
            conn.close()  # the Stop button
            for _ in range(100):
                if g.snapshot()[1] == 0:
                    break
                time.sleep(0.1)
            self.assertEqual(g.snapshot(), (1, 0))
        finally:
            g.release()


if __name__ == "__main__":
    unittest.main()
