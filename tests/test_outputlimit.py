"""The answer limit: Ollama gets a context window that fits it, OpenAI-compatible servers a max_tokens
they accept (renamed, clamped or dropped when they refuse it)."""

import unittest
from unittest import mock

from sunak import providers
from sunak.providers import ProviderError

OLLAMA = {"id": "o", "type": "ollama", "base_url": "http://ollama.test"}
OPENAI = {"id": "x", "type": "openai", "base_url": "http://openai.test/v1"}


class OllamaOptionsTest(unittest.TestCase):
    def setUp(self):
        providers._CONTEXT_LENGTH.clear()

    def test_window_fits_the_limit(self):
        with mock.patch.object(providers, "ollama_context_length", return_value=None):
            o = providers.ollama_options(OLLAMA, "m", {"temperature": 0.5, "max_tokens": 32768})
        self.assertEqual(o, {"temperature": 0.5, "num_predict": 32768, "num_ctx": 32768 + providers.PROMPT_HEADROOM})

    def test_window_is_clamped_to_the_model(self):
        with mock.patch.object(providers, "ollama_context_length", return_value=8192):
            o = providers.ollama_options(OLLAMA, "m", {"max_tokens": 32768})
        self.assertEqual((o["num_ctx"], o["num_predict"]), (8192, 8192))

    def test_no_limit_leaves_the_window_alone(self):
        self.assertEqual(providers.ollama_options(OLLAMA, "m", {"temperature": 0}), {"temperature": 0})


class OpenAILimitTest(unittest.TestCase):
    def setUp(self):
        providers._OUTPUT_FIX.clear()

    def run_with(self, errors):
        sent = []

        def fake(p, path, payload):
            sent.append(dict(payload))
            if errors:
                raise ProviderError(errors.pop(0))
            return "resp"
        with mock.patch.object(providers, "_open_openai_stream", fake):
            resp = providers.open_openai_stream(OPENAI, "/chat/completions", {"model": "m", "max_tokens": 32768})
        return resp, sent

    def test_accepted_as_is(self):
        resp, sent = self.run_with([])
        self.assertEqual((resp, len(sent), sent[0]["max_tokens"]), ("resp", 1, 32768))

    def test_renamed(self):
        _, sent = self.run_with(["HTTP 400: Unsupported parameter: 'max_tokens'. Use 'max_completion_tokens' instead."])
        self.assertEqual(sent[1], {"model": "m", "max_completion_tokens": 32768})

    def test_clamped_and_remembered(self):
        _, sent = self.run_with(["HTTP 400: max_tokens is too large: 32768. This model supports at most 16384 max_tokens."])
        self.assertEqual(sent[1]["max_tokens"], 16384)
        _, sent = self.run_with([])  # the next request starts with the accepted value
        self.assertEqual(sent[0]["max_tokens"], 16384)

    def test_dropped_when_unknown(self):
        _, sent = self.run_with(["HTTP 400: unknown field max_tokens"])
        self.assertNotIn("max_tokens", sent[1])

    def test_other_errors_pass_through(self):
        with self.assertRaises(ProviderError):
            self.run_with(["HTTP 400: model not found"])


if __name__ == "__main__":
    unittest.main()
