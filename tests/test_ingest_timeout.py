import io
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import quant_llm_wiki.ingest.source as ingest_source


def _slow_dispatch(*_args, **_kwargs):
    time.sleep(3)
    return "/should/not/reach"


def _fast_dispatch(*_args, **_kwargs):
    return "/tmp/fake/out"


class IngestUrlTimeoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev_env = os.environ.get("INGEST_URL_TIMEOUT")
        os.environ["INGEST_URL_TIMEOUT"] = "1"

    def tearDown(self) -> None:
        if self._prev_env is None:
            os.environ.pop("INGEST_URL_TIMEOUT", None)
        else:
            os.environ["INGEST_URL_TIMEOUT"] = self._prev_env

    def test_timeout_helper_raises(self) -> None:
        from concurrent.futures import TimeoutError as FuturesTimeoutError
        with self.assertRaises(FuturesTimeoutError):
            ingest_source._run_with_timeout(_slow_dispatch, "https://x")

    def test_timeout_helper_passthrough(self) -> None:
        out = ingest_source._run_with_timeout(_fast_dispatch, "https://x")
        self.assertEqual(out, "/tmp/fake/out")

    def test_url_list_skips_on_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            list_path = Path(tmp) / "urls.txt"
            list_path.write_text(
                "https://example.com/a\nhttps://example.com/b\n", encoding="utf-8"
            )
            buf = io.StringIO()
            with patch("quant_llm_wiki.ingest.source.dispatch_url", side_effect=_slow_dispatch):
                with patch.object(sys, "argv", ["ingest_source", "--url-list", str(list_path)]):
                    with redirect_stdout(buf):
                        rc = ingest_source.main()
            output = buf.getvalue()
            self.assertEqual(rc, 0)
            self.assertEqual(output.count("TIMEOUT"), 2)
            self.assertIn("https://example.com/a", output)
            self.assertIn("https://example.com/b", output)

    def test_url_list_normal_path_no_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            list_path = Path(tmp) / "urls.txt"
            list_path.write_text("https://example.com/x\n", encoding="utf-8")
            buf = io.StringIO()
            with patch("quant_llm_wiki.ingest.source.dispatch_url", side_effect=_fast_dispatch):
                with patch.object(sys, "argv", ["ingest_source", "--url-list", str(list_path)]):
                    with redirect_stdout(buf):
                        rc = ingest_source.main()
            output = buf.getvalue()
            self.assertEqual(rc, 0)
            self.assertNotIn("TIMEOUT", output)
            self.assertIn("Ingested:", output)

    def test_single_url_timeout_returns_nonzero(self) -> None:
        buf = io.StringIO()
        with patch("quant_llm_wiki.ingest.source.dispatch_url", side_effect=_slow_dispatch):
            with patch.object(sys, "argv", ["ingest_source", "--url", "https://example.com/z"]):
                with redirect_stdout(buf):
                    rc = ingest_source.main()
        self.assertEqual(rc, 2)
        self.assertIn("TIMEOUT", buf.getvalue())
        self.assertIn("https://example.com/z", buf.getvalue())

    def test_pdf_url_timeout_returns_nonzero(self) -> None:
        buf = io.StringIO()
        with patch("quant_llm_wiki.ingest.source._dispatch_pdf_url", side_effect=_slow_dispatch):
            with patch.object(sys, "argv", ["ingest_source", "--pdf-url", "https://example.com/p.pdf"]):
                with redirect_stdout(buf):
                    rc = ingest_source.main()
        self.assertEqual(rc, 2)
        self.assertIn("TIMEOUT", buf.getvalue())

    def test_default_timeout_when_env_invalid(self) -> None:
        os.environ["INGEST_URL_TIMEOUT"] = "not-a-number"
        self.assertEqual(
            ingest_source._ingest_url_timeout(),
            ingest_source.DEFAULT_INGEST_URL_TIMEOUT,
        )


if __name__ == "__main__":
    unittest.main()
