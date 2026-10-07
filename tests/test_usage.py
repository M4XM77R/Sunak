"""Token counter (sunak/usage.py): one test per provider adapter with a mocked answer, missing numbers stay empty,
counting never breaks a request, kinds, one counter per profile, the endpoint.
Run:  python -m unittest discover tests"""

import json
import os
import tempfile
import threading
import time
import unittest
import urllib.request
from unittest import mock

from sunak import providers, toolrun, usage
from sunak.db import DB
from sunak.server import make_server, usage_kind

import test_server
from test_server import FakeBackend


class FakeResponse:
    """What providers._request returns: lines to iterate over, usable as a context manager."""
    def __init__(self, lines, pause=0.0):
        self.lines, self.pause = lines, pause

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        for line in self.lines:
            if self.pause:
                time.sleep(self.pause)
            yield line


def ndjson(*objs):
    return [json.dumps(o).encode() + b"\n" for o in objs]


def sse(*objs, done=False):
    return [b"data: " + json.dumps(o).encode() + b"\n" for o in objs] + ([b"data: [DONE]\n"] if done else [])


OLLAMA = {"id": "ollama", "type": "ollama", "base_url": "http://127.0.0.1:1"}
OPENAI = {"id": "cloud", "type": "openai", "base_url": "http://127.0.0.1:2/v1", "api_key": "k"}
CLAUDE = {"id": "claude", "type": "anthropic", "base_url": "http://127.0.0.1:3", "api_key": "k"}
MSGS = [{"role": "user", "content": "hi"}]


def drain(gen):
    """All chunks of a Turns generator and what it returned."""
    out = []
    try:
        while True:
            out.append(next(gen))
    except StopIteration as e:
        return out, e.value


class CounterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = DB(os.path.join(self.tmp.name, "u.db"))
        usage.bind(self.db, "default", "chat")
        self.addCleanup(usage.unbind)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.db.close)

    def rows(self):
        return self.db._q("SELECT * FROM usage ORDER BY id")

    def chat(self, p, lines, pause=0.0):
        with mock.patch.object(providers, "_request", return_value=FakeResponse(lines, pause)):
            return list(providers.chat_stream(p, "m", MSGS))

    # one test per adapter ------------------------------------------------
    def test_ollama(self):
        chunks = self.chat(OLLAMA, ndjson({"message": {"content": "Hel"}}, {"message": {"content": "lo"}, "done": True,
                           "prompt_eval_count": 26, "eval_count": 298, "eval_duration": 4_000_000_000}))
        self.assertEqual("".join(c for _, c in chunks), "Hello")
        (r,) = self.rows()
        self.assertEqual((r["provider"], r["model"], r["kind"], r["ok"]), ("ollama", "m", "chat", 1))
        self.assertEqual((r["input_tokens"], r["output_tokens"]), (26, 298))
        self.assertIsNone(r["cache_read_tokens"])  # Ollama does not report a cache: empty, not 0
        self.assertIsNone(r["cache_creation_tokens"])
        self.assertEqual(r["tokens_per_second"], 74.5)  # eval_count / eval_duration * 1e9
        self.assertGreaterEqual(r["seconds"], 0)

    def test_openai_compatible(self):
        chunks = self.chat(OPENAI, sse({"choices": [{"delta": {"content": "Hi"}}]},
                                       {"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 40,
                                                                 "prompt_tokens_details": {"cached_tokens": 60}}}, done=True), pause=0.06)
        self.assertEqual(chunks, [("text", "Hi")])
        (r,) = self.rows()
        self.assertEqual((r["input_tokens"], r["output_tokens"], r["cache_read_tokens"]), (40, 40, 60))  # cached ones are not input twice
        self.assertEqual(usage.total(r), 140)
        self.assertEqual(self.db.usage_sums()["all"], 140)

    def test_anthropic(self):
        events = sse({"type": "message_start", "message": {"usage": {"input_tokens": 12, "cache_read_input_tokens": 300,
                                                                        "cache_creation_input_tokens": 50, "output_tokens": 1}}},
                     {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "A"}},
                     {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "B"}},
                     {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 77}},
                     {"type": "message_stop"})
        chunks = self.chat(CLAUDE, events, pause=0.1)
        self.assertEqual("".join(c for _, c in chunks), "AB")
        (r,) = self.rows()
        self.assertEqual((r["input_tokens"], r["output_tokens"], r["cache_read_tokens"], r["cache_creation_tokens"]), (12, 77, 300, 50))
        # no eval_duration: measured between the first and the last output chunk (about 0.1 s, the clock of a CI machine is
        # not exact) → several hundred tok/s, and never more than the 77 tokens in the time of one pause
        self.assertTrue(50 < r["tokens_per_second"] < 77 / 0.05, r["tokens_per_second"])

    def test_anthropic_stopped_stream_keeps_no_placeholder_output(self):
        events = sse({"type": "message_start", "message": {"usage": {"input_tokens": 12, "output_tokens": 1}}},
                     {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "A"}},
                     {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "B"}})
        with mock.patch.object(providers, "_request", return_value=FakeResponse(events)):
            gen = providers.chat_stream(CLAUDE, "m", MSGS)
            next(gen)
            gen.close()  # stopped before message_delta (Stop button, the picture check, a broken connection)
        (r,) = self.rows()
        self.assertEqual((r["input_tokens"], r["output_tokens"], r["ok"]), (12, None, 0))  # the 1 of message_start is a placeholder

    def test_anthropic_zero_in_message_delta_does_not_replace_real_numbers(self):
        events = sse({"type": "message_start", "message": {"usage": {"input_tokens": 12, "cache_read_input_tokens": 300}}},
                     {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "A"}},
                     {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
                      "usage": {"input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 5}},
                     {"type": "message_stop"})
        self.chat(CLAUDE, events)
        (r,) = self.rows()
        self.assertEqual((r["input_tokens"], r["cache_read_tokens"], r["output_tokens"], r["ok"]), (12, 300, 5, 1))

    def test_odd_usage_objects_never_reach_the_stream(self):
        lines = sse({"choices": [{"delta": {"content": "Hi"}}], "usage": {"prompt_tokens": 7, "completion_tokens": 2,
                                                                          "prompt_tokens_details": "unexpected"}}, done=True)
        self.assertEqual(self.chat(OPENAI, lines), [("text", "Hi")])
        (r,) = self.rows()
        self.assertEqual((r["input_tokens"], r["output_tokens"], r["cache_read_tokens"]), (7, 2, None))
        for bad in ("text", 5, [1], {"prompt_tokens": "x", "completion_tokens": {}}):
            usage.openai_usage(usage.Meter(OPENAI, "m"), bad)  # no exception
            usage.anthropic_usage(usage.Meter(CLAUDE, "m"), bad)
            usage.ollama_usage(usage.Meter(OLLAMA, "m"), bad)
        usage.ollama_usage(usage.Meter(OLLAMA, "m"), {"eval_count": "many"})
        usage.anthropic_usage(None, {"input_tokens": 1})  # even a broken meter

    # the tool loop has its own streams ---------------------------------------
    def test_tools_ollama_turn(self):
        t = toolrun.OllamaTurns(OLLAMA, "m", MSGS, {}, [])
        lines = ndjson({"message": {"content": "x"}}, {"message": {}, "done": True, "prompt_eval_count": 5, "eval_count": 7, "eval_duration": 1_000_000_000})
        with mock.patch.object(providers, "_request", return_value=FakeResponse(lines)):
            drain(t.turn())
        (r,) = self.rows()
        self.assertEqual((r["input_tokens"], r["output_tokens"], r["tokens_per_second"]), (5, 7, 7.0))

    def test_tools_openai_turn(self):
        t = toolrun.OpenAITurns(OPENAI, "m", MSGS, {}, [])
        lines = sse({"choices": [{"delta": {"content": "x"}}]}, {"choices": [], "usage": {"prompt_tokens": 9, "completion_tokens": 3}}, done=True)
        with mock.patch.object(providers, "_request", return_value=FakeResponse(lines)):
            drain(t.turn())
        (r,) = self.rows()
        self.assertEqual((r["input_tokens"], r["output_tokens"], r["cache_read_tokens"]), (9, 3, None))

    def test_tools_claude_tool_call_counts_as_output_for_the_speed(self):
        t = toolrun.ClaudeTurns(CLAUDE, "claude-x", MSGS, {}, [])
        lines = sse({"type": "message_start", "message": {"usage": {"input_tokens": 4}}},
                    {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "t1", "name": "Fake__echo"}},
                    {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": "{\"path\":"}},
                    {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": "\"a\"}"}},
                    {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 50}},
                    {"type": "message_stop"})
        with mock.patch.object(providers, "_request", return_value=FakeResponse(lines, pause=0.1)):
            drain(t.turn())
        (r,) = self.rows()
        self.assertEqual((r["output_tokens"], r["ok"]), (50, 1))
        self.assertIsNotNone(r["tokens_per_second"])  # the tool arguments streamed for a while: that is output time too

    def test_tools_claude_turn(self):
        t = toolrun.ClaudeTurns(CLAUDE, "claude-x", MSGS, {}, [])
        lines = sse({"type": "message_start", "message": {"usage": {"input_tokens": 4}}},
                    {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}},
                    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "x"}},
                    {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 2}},
                    {"type": "message_stop"})
        with mock.patch.object(providers, "_request", return_value=FakeResponse(lines)):
            drain(t.turn())
        (r,) = self.rows()
        self.assertEqual((r["model"], r["input_tokens"], r["output_tokens"]), ("claude-x", 4, 2))

    # rules -----------------------------------------------------------------
    def test_missing_numbers_are_empty_not_guessed(self):
        self.chat(OPENAI, sse({"choices": [{"delta": {"content": "Hi"}}]}, done=True))
        (r,) = self.rows()
        self.assertEqual([r[k] for k in usage.FIELDS], [None] * 4)
        self.assertIsNone(r["tokens_per_second"])
        self.assertEqual(usage.total(r), 0)

    def test_a_failing_counter_never_fails_the_request(self):
        with mock.patch.object(DB, "add_usage", side_effect=RuntimeError("disk full")):
            chunks = self.chat(OLLAMA, ndjson({"message": {"content": "ok"}, "done": True, "eval_count": 1}))
        self.assertEqual(chunks, [("text", "ok")])

    def test_failed_and_stopped_requests_are_counted(self):
        lines = ndjson({"message": {"content": "a"}}, {"error": "model crashed"})
        with mock.patch.object(providers, "_request", return_value=FakeResponse(lines)):
            with self.assertRaises(providers.ProviderError):
                list(providers.chat_stream(OLLAMA, "m", MSGS))
        self.assertEqual([r["ok"] for r in self.rows()], [0])
        lines = ndjson({"message": {"content": "a"}}, {"message": {"content": "b"}}, {"message": {}, "done": True, "eval_count": 9})
        with mock.patch.object(providers, "_request", return_value=FakeResponse(lines)):
            gen = providers.chat_stream(OLLAMA, "m", MSGS)
            next(gen)
            gen.close()  # the reader stops early (the picture check does this)
        self.assertEqual([r["ok"] for r in self.rows()], [0, 1])

    def test_nothing_is_stored_without_a_profile_or_without_an_answer(self):
        usage.unbind()
        self.chat(OLLAMA, ndjson({"message": {"content": "x"}, "done": True, "eval_count": 1}))
        usage.bind(self.db, "default", "chat")
        self.chat(OLLAMA, [])
        self.assertEqual(self.rows(), [])

    def test_stream_options_are_dropped_for_servers_that_refuse_them(self):
        calls = []

        def fake(url, data=None, api_key="", **kw):
            calls.append(dict(data))
            if "stream_options" in data:
                raise providers.ProviderError("HTTP 400: Unrecognized request argument: stream_options")
            return FakeResponse(sse({"choices": [{"delta": {"content": "x"}}]}, done=True))
        p = dict(OPENAI, base_url="http://127.0.0.1:99/v1")
        providers._NO_STREAM_USAGE.discard("http://127.0.0.1:99/v1")
        self.addCleanup(providers._NO_STREAM_USAGE.discard, "http://127.0.0.1:99/v1")
        with mock.patch.object(providers, "_request", side_effect=fake):
            self.assertEqual(list(providers.chat_stream(p, "m", MSGS)), [("text", "x")])
            self.assertEqual(list(providers.chat_stream(p, "m", MSGS)), [("text", "x")])
        self.assertEqual(["stream_options" in c for c in calls], [True, False, False])  # asked once, then remembered

    def test_other_errors_are_not_retried(self):
        for msg in ("HTTP 401: bad key", "HTTP 400: This model's maximum context length is 8192 tokens", "HTTP 422: model not found",
                    "HTTP 400: tools are not supported"):
            with mock.patch.object(providers, "_request", side_effect=providers.ProviderError(msg)) as req:
                with self.assertRaises(providers.ProviderError) as cm:
                    list(providers.chat_stream(dict(OPENAI, base_url="http://127.0.0.1:98/v1"), "m", MSGS))
            self.assertEqual((req.call_count, str(cm.exception)), (1, msg))  # a real error is passed on at once, once
        self.assertNotIn("http://127.0.0.1:98/v1", providers._NO_STREAM_USAGE)

    def test_sums_and_last(self):
        for kind, i, o, c in (("chat", 10, 20, 5), ("memory", 1, 2, None), ("chat", 100, 50, 25)):
            self.db.add_usage({"ts": time.time(), "provider": "p", "model": "m", "kind": kind, "input_tokens": i, "output_tokens": o,
                               "cache_read_tokens": c, "cache_creation_tokens": None, "seconds": 1.0, "tokens_per_second": 5.0, "ok": 1})
        s = usage.summary(self.db)
        self.assertEqual((s["total"]["requests"], s["total"]["all"], s["total"]["cache_read_tokens"]), (3, 213, 30))
        self.assertEqual(s["background"]["all"], 3)
        self.assertEqual(s["last"]["input_tokens"], 100)
        self.db._q("DELETE FROM usage WHERE id = 3")
        self.assertEqual(usage.summary(self.db)["last"]["input_tokens"], 10)  # a background request is never "the last request"
        self.assertNotIn("goal", s)

    def test_kinds_by_path(self):
        want = {"/api/chat": "chat", "/api/tools": "tools", "/api/research": "research", "/api/compare": "compare",
                "/api/documents/ai": "document", "/api/mail/ai": "mail", "/api/calendar/parse": "calendar",
                "/api/imagine": "image_prompt", "/api/imagine/intent": "image_check", "/api/sessions/abc123/remember": "memory",
                "/api/settings": "other"}
        for path, kind in want.items():
            self.assertEqual(usage_kind(path), kind, path)
        self.assertTrue({"image_prompt", "image_check", "memory"} <= set(usage.BACKGROUND))

    def test_threads_keep_the_context(self):
        usage.bind(self.db, "default", "image_check")
        t = usage.thread(lambda: list(providers.chat_stream(OLLAMA, "m", MSGS)))
        with mock.patch.object(providers, "_request", return_value=FakeResponse(ndjson({"message": {"content": "x"}, "done": True, "eval_count": 3}))):
            t.start()
            t.join()
        self.assertEqual([r["kind"] for r in self.rows()], ["image_check"])


class UsageEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        cls.backend = ThreadingHTTPServer(("127.0.0.1", 0), FakeBackend)
        threading.Thread(target=cls.backend.serve_forever, daemon=True).start()
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.srv = make_server("127.0.0.1", 0, os.path.join(cls.tmp.name, "data"))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.app = cls.srv.RequestHandlerClass.app
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        cls.call = classmethod(test_server.SunakTest.call.__func__)
        cls.call("PUT", "/api/settings", {"providers": [
            {"id": "ollama", "name": "Ollama", "type": "ollama", "base_url": f"http://127.0.0.1:{cls.backend.server_address[1]}"}]})

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.backend.shutdown()
        cls.tmp.cleanup()

    def req(self, method, path, body=None, cookie=None):
        h = {"Content-Type": "application/json", "X-Requested-With": "sunak"}
        if cookie:
            h["Cookie"] = cookie
        r = urllib.request.Request(self.base + path, json.dumps(body).encode() if body is not None else None, h, method=method)
        with urllib.request.urlopen(r, timeout=10) as resp:
            return json.loads(resp.read() or b"null")

    def test_chat_is_counted_and_each_profile_has_its_own_counter(self):
        empty = self.req("GET", "/api/usage")
        self.assertEqual((empty["last"], empty["total"]["all"]), (None, 0))
        s = self.call("POST", "/api/sessions", {})
        self.call("POST", "/api/chat", {"session_id": s["id"], "model": "ollama::tiny:1b", "content": "Hey"})
        now = self.req("GET", "/api/usage")
        self.assertEqual(now["total"]["requests"], 1)
        self.assertEqual((now["last"]["kind"], now["last"]["model"], now["last"]["provider"]), ("chat", "tiny:1b", "ollama"))
        self.assertEqual(now["installation"], now["total"]["all"])
        # a second profile starts at zero and cannot see the first one's numbers
        kid = self.req("POST", "/api/profiles", {"name": "Kid", "emoji": "🦄", "pin": "1234"})
        resp = urllib.request.Request(self.base + "/api/profiles/select", json.dumps({"id": kid["id"], "pin": "1234"}).encode(),
                                      {"Content-Type": "application/json", "X-Requested-With": "sunak"}, method="POST")
        with urllib.request.urlopen(resp, timeout=10) as r:
            cookie = r.headers.get("Set-Cookie", "").split(";")[0]
        theirs = self.req("GET", "/api/usage", cookie=cookie)
        self.assertEqual((theirs["last"], theirs["total"]["requests"]), (None, 0))
        self.assertNotIn("installation", theirs)  # only an admin sees the sum of everyone
        self.app.close_profile(kid["id"])
        self.app.main.set_setting("profiles", [])


if __name__ == "__main__":
    unittest.main()
