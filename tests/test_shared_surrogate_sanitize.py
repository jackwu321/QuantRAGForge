"""Tests for lone UTF-16 surrogate sanitization in LLM responses."""
from __future__ import annotations

import unittest

from quant_llm_wiki.shared import (
    _sanitize_lone_surrogates,
    _sanitize_response_strings,
)

# Replacement character U+FFFD — used in all "expected after sanitization" assertions.
_REPL = "\ufffd"


class SanitizeLoneSurrogatesTests(unittest.TestCase):
    def test_passthrough_on_clean_text(self):
        self.assertEqual(_sanitize_lone_surrogates("hello world"), "hello world")

    def test_passthrough_on_cjk_and_emoji(self):
        # Valid emoji (single code point U+1F600) and CJK must be untouched.
        text = "你好 \U0001F600 quant"
        self.assertEqual(_sanitize_lone_surrogates(text), text)

    def test_replaces_high_surrogate(self):
        text = "before\ud83dafter"
        self.assertEqual(_sanitize_lone_surrogates(text), "before" + _REPL + "after")

    def test_replaces_low_surrogate(self):
        text = "x\udcffy"
        self.assertEqual(_sanitize_lone_surrogates(text), "x" + _REPL + "y")

    def test_replaces_consecutive_pair_of_lone_surrogates(self):
        # The 5470-5471 pattern from the original bug: an LLM provider emitted
        # the UTF-16 surrogate pair for 🙏 as two raw Python code points
        # (\uD83D + \uDE4F) instead of the single code point U+1F64F. Both are
        # lone surrogates in Python and must each be replaced with U+FFFD.
        text = "a\uD83D\uDE4Fb"
        self.assertEqual(_sanitize_lone_surrogates(text), "a" + _REPL + _REPL + "b")

    def test_result_is_utf8_encodable(self):
        text = "x\ud83dy"
        # The whole point: result must round-trip through UTF-8.
        _sanitize_lone_surrogates(text).encode("utf-8")  # must not raise


class SanitizeResponseStringsTests(unittest.TestCase):
    def test_walks_nested_dict(self):
        payload = {
            "choices": [
                {"message": {"content": "hi\ud83dthere"}},
            ],
            "model": "glm-4",
        }
        result = _sanitize_response_strings(payload)
        self.assertEqual(
            result["choices"][0]["message"]["content"], "hi" + _REPL + "there"
        )
        self.assertEqual(result["model"], "glm-4")

    def test_preserves_non_string_leaves(self):
        payload = {"data": [{"embedding": [0.1, 0.2, 0.3]}], "usage": {"tokens": 42}}
        result = _sanitize_response_strings(payload)
        self.assertEqual(result["data"][0]["embedding"], [0.1, 0.2, 0.3])
        self.assertEqual(result["usage"]["tokens"], 42)

    def test_handles_dict_keys_with_surrogates(self):
        # Defensive: even if a provider puts surrogates in a key, sanitize.
        payload = {"k\ud83dey": "value"}
        result = _sanitize_response_strings(payload)
        self.assertIn("k" + _REPL + "ey", result)

    def test_clean_payload_is_returned_unchanged_in_value(self):
        payload = {"choices": [{"message": {"content": "clean"}}]}
        result = _sanitize_response_strings(payload)
        self.assertEqual(result["choices"][0]["message"]["content"], "clean")


if __name__ == "__main__":
    unittest.main()
