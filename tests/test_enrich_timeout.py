import io
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from quant_llm_wiki import enrich
from quant_llm_wiki.enrich import ProcessResult


def _slow_process(article_dir, *, status_filter, force, dry_run):
    time.sleep(3)
    return ProcessResult(article_dir=str(article_dir), success=True)


def _fast_process(article_dir, *, status_filter, force, dry_run):
    return ProcessResult(article_dir=str(article_dir), success=True)


def _fail_process(article_dir, *, status_filter, force, dry_run):
    return ProcessResult(article_dir=str(article_dir), success=False, error="boom")


class ArticleTimeoutHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev = os.environ.get("LLM_ARTICLE_TIMEOUT")
        os.environ.pop("LLM_ARTICLE_TIMEOUT", None)

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("LLM_ARTICLE_TIMEOUT", None)
        else:
            os.environ["LLM_ARTICLE_TIMEOUT"] = self._prev

    def test_default_when_unset(self) -> None:
        self.assertEqual(enrich._article_timeout(), enrich.DEFAULT_ARTICLE_TIMEOUT)

    def test_env_override(self) -> None:
        os.environ["LLM_ARTICLE_TIMEOUT"] = "42"
        self.assertEqual(enrich._article_timeout(), 42)

    def test_invalid_env_falls_back(self) -> None:
        os.environ["LLM_ARTICLE_TIMEOUT"] = "abc"
        self.assertEqual(enrich._article_timeout(), enrich.DEFAULT_ARTICLE_TIMEOUT)


class ProcessWithTimeoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev = os.environ.get("LLM_ARTICLE_TIMEOUT")
        os.environ["LLM_ARTICLE_TIMEOUT"] = "1"
        self._kwargs = dict(status_filter="raw", force=False, dry_run=False)

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("LLM_ARTICLE_TIMEOUT", None)
        else:
            os.environ["LLM_ARTICLE_TIMEOUT"] = self._prev

    def test_passthrough_returns_inner_result(self) -> None:
        buf = io.StringIO()
        with patch("quant_llm_wiki.enrich.process_article_dir", side_effect=_fast_process):
            with patch.object(sys, "stderr", buf):
                result = enrich._process_with_timeout(Path("/tmp/sampleA"), **self._kwargs)
        self.assertTrue(result.success)
        self.assertIn("[enrich] start sampleA", buf.getvalue())
        self.assertIn("[enrich] done", buf.getvalue())

    def test_timeout_returns_failure_result(self) -> None:
        buf = io.StringIO()
        with patch("quant_llm_wiki.enrich.process_article_dir", side_effect=_slow_process):
            with patch.object(sys, "stderr", buf):
                result = enrich._process_with_timeout(Path("/tmp/sampleB"), **self._kwargs)
        self.assertFalse(result.success)
        self.assertTrue(result.error.startswith("timeout:"))
        self.assertIn("TIMEOUT sampleB", buf.getvalue())


class RunEnrichBatchTimeoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev = os.environ.get("LLM_ARTICLE_TIMEOUT")
        os.environ["LLM_ARTICLE_TIMEOUT"] = "1"
        self._kwargs = dict(status_filter="raw", force=False, dry_run=False)

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("LLM_ARTICLE_TIMEOUT", None)
        else:
            os.environ["LLM_ARTICLE_TIMEOUT"] = self._prev

    def _mixed_processor(self, article_dir, *, status_filter, force, dry_run):
        if "slow" in str(article_dir):
            time.sleep(3)
            return ProcessResult(article_dir=str(article_dir), success=True)
        return ProcessResult(article_dir=str(article_dir), success=True)

    def test_serial_skips_timeout_and_continues(self) -> None:
        progress: list[tuple[int, int, ProcessResult]] = []
        with patch("quant_llm_wiki.enrich.process_article_dir", side_effect=self._mixed_processor):
            with patch.object(sys, "stderr", io.StringIO()):
                results = enrich.run_enrich_batch(
                    [Path("/tmp/slow_one"), Path("/tmp/fast_two")],
                    **self._kwargs,
                    concurrency=1,
                    progress_callback=lambda i, t, r: progress.append((i, t, r)),
                )
        self.assertEqual(len(results), 2)
        self.assertFalse(results[0].success)
        self.assertTrue(results[0].error.startswith("timeout:"))
        self.assertTrue(results[1].success)
        self.assertEqual(len(progress), 2)
        self.assertEqual(progress[0][0], 1)
        self.assertEqual(progress[1][0], 2)

    def test_concurrent_skips_timeout_and_returns_all(self) -> None:
        progress: list[tuple[int, int, ProcessResult]] = []
        with patch("quant_llm_wiki.enrich.process_article_dir", side_effect=self._mixed_processor):
            with patch.object(sys, "stderr", io.StringIO()):
                results = enrich.run_enrich_batch(
                    [Path("/tmp/slow_a"), Path("/tmp/fast_b"), Path("/tmp/fast_c")],
                    **self._kwargs,
                    concurrency=3,
                    progress_callback=lambda i, t, r: progress.append((i, t, r)),
                )
        self.assertEqual(len(results), 3)
        slow_results = [r for r in results if "slow_a" in r.article_dir]
        fast_results = [r for r in results if "fast" in r.article_dir]
        self.assertEqual(len(slow_results), 1)
        self.assertFalse(slow_results[0].success)
        self.assertTrue(slow_results[0].error.startswith("timeout:"))
        self.assertEqual(len(fast_results), 2)
        for r in fast_results:
            self.assertTrue(r.success)
        self.assertEqual(len(progress), 3)


class RetryLogTests(unittest.TestCase):
    """post_llm_json should print a [llm-retry] line to stderr before each backoff sleep."""

    def test_retry_logs_on_429(self) -> None:
        from quant_llm_wiki import shared

        class FakeHTTPError(Exception):
            def __init__(self, status):
                self.response = type("R", (), {
                    "status_code": status,
                    "headers": {},
                })()

        # Map onto the real exception subclass so isinstance match works.
        import requests
        http_err = requests.exceptions.HTTPError()
        fake_response = type("R", (), {
            "status_code": 429,
            "headers": {},
            "raise_for_status": lambda self: (_ for _ in ()).throw(http_err),
            "json": lambda self: {"ok": True},
        })()
        http_err.response = fake_response

        attempts = {"n": 0}

        def fake_post(url, headers=None, json=None, timeout=None):
            attempts["n"] += 1
            if attempts["n"] <= 2:
                resp = type("R", (), {
                    "status_code": 429,
                    "headers": {},
                })()
                err = requests.exceptions.HTTPError()
                err.response = resp
                raise err
            return type("R", (), {
                "status_code": 200,
                "headers": {},
                "raise_for_status": lambda self: None,
                "json": lambda self: {"ok": True},
            })()

        buf = io.StringIO()
        with patch("quant_llm_wiki.shared.requests.post", side_effect=fake_post):
            with patch("quant_llm_wiki.shared.time.sleep"):  # don't actually sleep
                with patch("quant_llm_wiki.shared.get_llm_config",
                           return_value=("k", "https://x", "model")):
                    with patch.object(sys, "stderr", buf):
                        result = shared.post_llm_json("/chat/completions", {"x": 1})
        self.assertEqual(result, {"ok": True})
        out = buf.getvalue()
        self.assertIn("[llm-retry]", out)
        self.assertIn("attempt 1/", out)
        self.assertIn("attempt 2/", out)
        self.assertIn("status=429", out)


if __name__ == "__main__":
    unittest.main()
