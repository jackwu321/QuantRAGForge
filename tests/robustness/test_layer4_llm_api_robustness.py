"""Layer 4: LLM API connection resilience tests.

Tests post_llm_json, call_llm_chat, embed_text, and get_llm_config under
adverse network/API conditions. All API calls are mocked — no real requests.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests as requests_lib

from tests.robustness.conftest import (
    RobustTestBase,
    ArticleFixtureFactory,
    MockLLMFactory,
)


def _mock_get_llm_config():
    return ("fake-test-key", "https://fake.api.url/v4", "test-model")


def _make_mock_response(status_code=200, json_data=None, raise_for_status=None):
    """Create a mock requests.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    if raise_for_status:
        resp.raise_for_status.side_effect = raise_for_status
    else:
        resp.raise_for_status.return_value = None
    return resp


# ===========================================================================
# Connection & Network Failure Tests
# ===========================================================================


@patch.dict(
    os.environ,
    {"LLM_MIN_INTERVAL_SECONDS": "0", "LLM_MAX_RETRIES": "2"},
    clear=False,
)
class TestConnectionFailures(unittest.TestCase):
    """Test post_llm_json behavior under network failures."""

    def setUp(self):
        import quant_llm_wiki.shared as kb_shared
        kb_shared._last_llm_call_ts = 0.0

    @patch("quant_llm_wiki.shared.get_llm_config", side_effect=_mock_get_llm_config)
    @patch("quant_llm_wiki.shared.time.sleep")
    @patch("quant_llm_wiki.shared.requests.post")
    def test_connection_timeout(self, mock_post, mock_sleep, mock_config):
        from quant_llm_wiki.shared import post_llm_json

        mock_post.side_effect = requests_lib.exceptions.ConnectTimeout("Connection timed out")

        with self.assertRaises(requests_lib.exceptions.ConnectTimeout):
            post_llm_json("/chat/completions", {"model": "test", "messages": []})

        # Default max_retries=2 → 3 total attempts
        self.assertEqual(mock_post.call_count, 3)

    @patch("quant_llm_wiki.shared.get_llm_config", side_effect=_mock_get_llm_config)
    @patch("quant_llm_wiki.shared.time.sleep")
    @patch("quant_llm_wiki.shared.requests.post")
    def test_read_timeout(self, mock_post, mock_sleep, mock_config):
        from quant_llm_wiki.shared import post_llm_json

        mock_post.side_effect = requests_lib.exceptions.ReadTimeout("Read timed out")

        with self.assertRaises(requests_lib.exceptions.ReadTimeout):
            post_llm_json("/chat/completions", {"model": "test", "messages": []})

        self.assertEqual(mock_post.call_count, 3)

    @patch("quant_llm_wiki.shared.get_llm_config", side_effect=_mock_get_llm_config)
    @patch("quant_llm_wiki.shared.time.sleep")
    @patch("quant_llm_wiki.shared.requests.post")
    def test_connection_refused(self, mock_post, mock_sleep, mock_config):
        from quant_llm_wiki.shared import post_llm_json

        mock_post.side_effect = requests_lib.exceptions.ConnectionError("Connection refused")

        with self.assertRaises(requests_lib.exceptions.ConnectionError):
            post_llm_json("/chat/completions", {"model": "test", "messages": []})

        self.assertEqual(mock_post.call_count, 3)

    @patch("quant_llm_wiki.shared.get_llm_config", side_effect=_mock_get_llm_config)
    @patch("quant_llm_wiki.shared.time.sleep")
    @patch("quant_llm_wiki.shared.requests.post")
    def test_dns_resolution_failure(self, mock_post, mock_sleep, mock_config):
        from quant_llm_wiki.shared import post_llm_json

        mock_post.side_effect = requests_lib.exceptions.ConnectionError(
            "Name or service not known"
        )

        with self.assertRaises(requests_lib.exceptions.ConnectionError) as ctx:
            post_llm_json("/chat/completions", {"model": "test", "messages": []})

        self.assertIn("Name or service not known", str(ctx.exception))

    @patch("quant_llm_wiki.shared.get_llm_config", side_effect=_mock_get_llm_config)
    @patch("quant_llm_wiki.shared.time.sleep")
    @patch("quant_llm_wiki.shared.requests.post")
    def test_ssl_error(self, mock_post, mock_sleep, mock_config):
        from quant_llm_wiki.shared import post_llm_json

        mock_post.side_effect = requests_lib.exceptions.SSLError("SSL certificate verify failed")

        with self.assertRaises(requests_lib.exceptions.SSLError):
            post_llm_json("/chat/completions", {"model": "test", "messages": []})

        self.assertEqual(mock_post.call_count, 3)


# ===========================================================================
# HTTP Error Response Tests
# ===========================================================================


@patch.dict(
    os.environ,
    {"LLM_MIN_INTERVAL_SECONDS": "0", "LLM_MAX_RETRIES": "2"},
    clear=False,
)
class TestHTTPErrors(unittest.TestCase):
    """Test post_llm_json behavior with HTTP error responses."""

    def setUp(self):
        import quant_llm_wiki.shared as kb_shared
        kb_shared._last_llm_call_ts = 0.0

    @patch("quant_llm_wiki.shared.get_llm_config", side_effect=_mock_get_llm_config)
    @patch("quant_llm_wiki.shared.time.sleep")
    @patch("quant_llm_wiki.shared.requests.post")
    def test_http_401_unauthorized(self, mock_post, mock_sleep, mock_config):
        from quant_llm_wiki.shared import post_llm_json

        http_error = requests_lib.exceptions.HTTPError("401 Unauthorized")
        mock_post.return_value = _make_mock_response(401, raise_for_status=http_error)

        with self.assertRaises(requests_lib.exceptions.HTTPError):
            post_llm_json("/chat/completions", {"model": "test", "messages": []})

    @patch("quant_llm_wiki.shared.get_llm_config", side_effect=_mock_get_llm_config)
    @patch("quant_llm_wiki.shared.time.sleep")
    @patch("quant_llm_wiki.shared.requests.post")
    def test_http_429_rate_limit(self, mock_post, mock_sleep, mock_config):
        from quant_llm_wiki.shared import post_llm_json

        http_error = requests_lib.exceptions.HTTPError("429 Too Many Requests")
        mock_post.return_value = _make_mock_response(429, raise_for_status=http_error)

        with self.assertRaises(requests_lib.exceptions.HTTPError):
            post_llm_json("/chat/completions", {"model": "test", "messages": []})

        # Should retry
        self.assertEqual(mock_post.call_count, 3)

    @patch("quant_llm_wiki.shared.get_llm_config", side_effect=_mock_get_llm_config)
    @patch("quant_llm_wiki.shared.time.sleep")
    @patch("quant_llm_wiki.shared.requests.post")
    def test_http_500_server_error(self, mock_post, mock_sleep, mock_config):
        from quant_llm_wiki.shared import post_llm_json

        http_error = requests_lib.exceptions.HTTPError("500 Internal Server Error")
        mock_post.return_value = _make_mock_response(500, raise_for_status=http_error)

        with self.assertRaises(requests_lib.exceptions.HTTPError):
            post_llm_json("/chat/completions", {"model": "test", "messages": []})

        self.assertEqual(mock_post.call_count, 3)

    @patch("quant_llm_wiki.shared.get_llm_config", side_effect=_mock_get_llm_config)
    @patch("quant_llm_wiki.shared.time.sleep")
    @patch("quant_llm_wiki.shared.requests.post")
    def test_http_502_bad_gateway(self, mock_post, mock_sleep, mock_config):
        from quant_llm_wiki.shared import post_llm_json

        http_error = requests_lib.exceptions.HTTPError("502 Bad Gateway")
        mock_post.return_value = _make_mock_response(502, raise_for_status=http_error)

        with self.assertRaises(requests_lib.exceptions.HTTPError):
            post_llm_json("/chat/completions", {"model": "test", "messages": []})

        self.assertEqual(mock_post.call_count, 3)

    @patch("quant_llm_wiki.shared.get_llm_config", side_effect=_mock_get_llm_config)
    @patch("quant_llm_wiki.shared.time.sleep")
    @patch("quant_llm_wiki.shared.requests.post")
    def test_http_503_service_unavailable(self, mock_post, mock_sleep, mock_config):
        from quant_llm_wiki.shared import post_llm_json

        http_error = requests_lib.exceptions.HTTPError("503 Service Unavailable")
        mock_post.return_value = _make_mock_response(503, raise_for_status=http_error)

        with self.assertRaises(requests_lib.exceptions.HTTPError):
            post_llm_json("/chat/completions", {"model": "test", "messages": []})

        self.assertEqual(mock_post.call_count, 3)


# ===========================================================================
# Retry Behavior Tests
# ===========================================================================


@patch.dict(
    os.environ,
    {"LLM_MIN_INTERVAL_SECONDS": "0"},
    clear=False,
)
class TestRetryBehavior(unittest.TestCase):
    """Test retry mechanics of post_llm_json."""

    def setUp(self):
        import quant_llm_wiki.shared as kb_shared
        kb_shared._last_llm_call_ts = 0.0

    @patch("quant_llm_wiki.shared.get_llm_config", side_effect=_mock_get_llm_config)
    @patch("quant_llm_wiki.shared.time.sleep")
    @patch("quant_llm_wiki.shared.requests.post")
    @patch.dict(os.environ, {"LLM_MAX_RETRIES": "3"})
    def test_retry_count_matches_config(self, mock_post, mock_sleep, mock_config):
        from quant_llm_wiki.shared import post_llm_json

        mock_post.side_effect = requests_lib.exceptions.ConnectionError("fail")

        with self.assertRaises(requests_lib.exceptions.ConnectionError):
            post_llm_json("/chat/completions", {"model": "test", "messages": []})

        # 3 retries + 1 initial = 4 attempts
        self.assertEqual(mock_post.call_count, 4)

    @patch("quant_llm_wiki.shared.get_llm_config", side_effect=_mock_get_llm_config)
    @patch("quant_llm_wiki.shared.time.sleep")
    @patch("quant_llm_wiki.shared.requests.post")
    def test_retry_succeeds_on_second_attempt(self, mock_post, mock_sleep, mock_config):
        from quant_llm_wiki.shared import post_llm_json

        success_response = _make_mock_response(200, {"result": "ok"})
        mock_post.side_effect = [
            requests_lib.exceptions.ConnectionError("temp failure"),
            success_response,
        ]

        result = post_llm_json("/chat/completions", {"model": "test", "messages": []})
        self.assertEqual(result, {"result": "ok"})
        self.assertEqual(mock_post.call_count, 2)

    @patch("quant_llm_wiki.shared.random.uniform", return_value=0.0)
    @patch("quant_llm_wiki.shared.get_llm_config", side_effect=_mock_get_llm_config)
    @patch("quant_llm_wiki.shared.time.sleep")
    @patch("quant_llm_wiki.shared.requests.post")
    @patch.dict(os.environ, {"LLM_MAX_RETRIES": "2"})
    def test_retry_backoff_timing(self, mock_post, mock_sleep, mock_config, mock_uniform):
        from quant_llm_wiki.shared import post_llm_json

        mock_post.side_effect = requests_lib.exceptions.ConnectionError("fail")

        with self.assertRaises(requests_lib.exceptions.ConnectionError):
            post_llm_json("/chat/completions", {"model": "test", "messages": []})

        # 2 retries → 2 backoff sleeps. Network errors use base=1, no jitter (mocked to 0).
        # Expected: 1*2^0=1, 1*2^1=2.
        self.assertEqual(mock_sleep.call_count, 2)
        calls = [c[0][0] for c in mock_sleep.call_args_list]
        self.assertAlmostEqual(calls[0], 1.0, places=2)
        self.assertAlmostEqual(calls[1], 2.0, places=2)

    @patch("quant_llm_wiki.shared.get_llm_config", side_effect=_mock_get_llm_config)
    @patch("quant_llm_wiki.shared.time.sleep")
    @patch("quant_llm_wiki.shared.requests.post")
    @patch.dict(os.environ, {"LLM_MAX_RETRIES": "0"})
    def test_zero_retries_fails_immediately(self, mock_post, mock_sleep, mock_config):
        from quant_llm_wiki.shared import post_llm_json

        mock_post.side_effect = requests_lib.exceptions.ConnectionError("fail")

        with self.assertRaises(requests_lib.exceptions.ConnectionError):
            post_llm_json("/chat/completions", {"model": "test", "messages": []})

        self.assertEqual(mock_post.call_count, 1)
        mock_sleep.assert_not_called()

    @patch("quant_llm_wiki.shared.get_llm_config", side_effect=_mock_get_llm_config)
    @patch("quant_llm_wiki.shared.time.sleep")
    @patch("quant_llm_wiki.shared.requests.post")
    def test_error_message_includes_url_and_attempts(self, mock_post, mock_sleep, mock_config):
        """Verify error messages include the target URL and attempt count."""
        from quant_llm_wiki.shared import post_llm_json

        mock_post.side_effect = requests_lib.exceptions.ConnectionError("Connection refused")

        with self.assertRaises(requests_lib.exceptions.ConnectionError) as ctx:
            post_llm_json("/chat/completions", {"model": "test", "messages": []})

        error_msg = str(ctx.exception)
        self.assertIn("https://fake.api.url/v4/chat/completions", error_msg)
        self.assertIn("attempt", error_msg)
        self.assertIn("Connection refused", error_msg)

    @patch("quant_llm_wiki.shared.random.uniform", return_value=0.0)
    @patch("quant_llm_wiki.shared.get_llm_config", side_effect=_mock_get_llm_config)
    @patch("quant_llm_wiki.shared.time.sleep")
    @patch("quant_llm_wiki.shared.requests.post")
    @patch.dict(os.environ, {"LLM_MAX_RETRIES": "1"})
    def test_429_uses_longer_backoff_than_network_errors(
        self, mock_post, mock_sleep, mock_config, mock_uniform
    ):
        """429 uses base=5s; network errors use base=1s."""
        from quant_llm_wiki.shared import post_llm_json

        # 429 case
        http_429 = requests_lib.exceptions.HTTPError("429")
        resp_429 = _make_mock_response(429, raise_for_status=http_429)
        resp_429.headers = {}  # no Retry-After
        http_429.response = resp_429
        mock_post.return_value = resp_429

        with self.assertRaises(requests_lib.exceptions.HTTPError):
            post_llm_json("/chat/completions", {"model": "test", "messages": []})

        # 1 retry → 1 backoff sleep at attempt=0 with base=5: 5*2^0=5
        sleeps_429 = [c[0][0] for c in mock_sleep.call_args_list]
        self.assertEqual(len(sleeps_429), 1)
        self.assertAlmostEqual(sleeps_429[0], 5.0, places=2)

    @patch("quant_llm_wiki.shared.get_llm_config", side_effect=_mock_get_llm_config)
    @patch("quant_llm_wiki.shared.time.sleep")
    @patch("quant_llm_wiki.shared.requests.post")
    @patch.dict(os.environ, {"LLM_MAX_RETRIES": "1"})
    def test_429_honors_retry_after_header(self, mock_post, mock_sleep, mock_config):
        """When the server sends Retry-After, use that exact value (capped at 60s)."""
        from quant_llm_wiki.shared import post_llm_json

        http_429 = requests_lib.exceptions.HTTPError("429 Too Many Requests")
        resp = _make_mock_response(429, raise_for_status=http_429)
        resp.headers = {"Retry-After": "7"}
        http_429.response = resp
        mock_post.return_value = resp

        with self.assertRaises(requests_lib.exceptions.HTTPError):
            post_llm_json("/chat/completions", {"model": "test", "messages": []})

        sleeps = [c[0][0] for c in mock_sleep.call_args_list]
        self.assertEqual(len(sleeps), 1)
        self.assertAlmostEqual(sleeps[0], 7.0, places=2)

    @patch("quant_llm_wiki.shared.get_llm_config", side_effect=_mock_get_llm_config)
    @patch("quant_llm_wiki.shared.time.sleep")
    @patch("quant_llm_wiki.shared.requests.post")
    @patch.dict(os.environ, {"LLM_MAX_RETRIES": "1"})
    def test_429_caps_retry_after_at_60_seconds(self, mock_post, mock_sleep, mock_config):
        """A pathologically large Retry-After value is capped at 60s."""
        from quant_llm_wiki.shared import post_llm_json

        http_429 = requests_lib.exceptions.HTTPError("429")
        resp = _make_mock_response(429, raise_for_status=http_429)
        resp.headers = {"Retry-After": "9999"}
        http_429.response = resp
        mock_post.return_value = resp

        with self.assertRaises(requests_lib.exceptions.HTTPError):
            post_llm_json("/chat/completions", {"model": "test", "messages": []})

        sleeps = [c[0][0] for c in mock_sleep.call_args_list]
        self.assertEqual(len(sleeps), 1)
        self.assertAlmostEqual(sleeps[0], 60.0, places=2)


# ===========================================================================
# Inter-Call Rate Limiter Tests
# ===========================================================================


class TestMinIntervalRateLimiter(unittest.TestCase):
    """Test that LLM_MIN_INTERVAL_SECONDS spaces calls apart."""

    def setUp(self):
        import quant_llm_wiki.shared as kb_shared
        kb_shared._last_llm_call_ts = 0.0

    @patch("quant_llm_wiki.shared.get_llm_config", side_effect=_mock_get_llm_config)
    @patch("quant_llm_wiki.shared.time.sleep")
    @patch("quant_llm_wiki.shared.requests.post")
    @patch.dict(os.environ, {"LLM_MIN_INTERVAL_SECONDS": "0.4"}, clear=False)
    def test_second_call_waits_for_min_interval(self, mock_post, mock_sleep, mock_config):
        from quant_llm_wiki.shared import post_llm_json

        mock_post.return_value = _make_mock_response(200, {"ok": True})

        post_llm_json("/chat/completions", {"model": "test", "messages": []})
        post_llm_json("/chat/completions", {"model": "test", "messages": []})

        # First call: _last_llm_call_ts is 0 so wait <= 0, no sleep.
        # Second call: ~0s elapsed, so wait ≈ 0.4s, one sleep call.
        sleeps = [c[0][0] for c in mock_sleep.call_args_list]
        self.assertEqual(len(sleeps), 1)
        self.assertGreater(sleeps[0], 0.3)
        self.assertLessEqual(sleeps[0], 0.4)

    @patch("quant_llm_wiki.shared.get_llm_config", side_effect=_mock_get_llm_config)
    @patch("quant_llm_wiki.shared.time.sleep")
    @patch("quant_llm_wiki.shared.requests.post")
    @patch.dict(os.environ, {"LLM_MIN_INTERVAL_SECONDS": "0"}, clear=False)
    def test_zero_interval_disables_rate_limiter(self, mock_post, mock_sleep, mock_config):
        from quant_llm_wiki.shared import post_llm_json

        mock_post.return_value = _make_mock_response(200, {"ok": True})

        post_llm_json("/chat/completions", {"model": "test", "messages": []})
        post_llm_json("/chat/completions", {"model": "test", "messages": []})

        mock_sleep.assert_not_called()


# ===========================================================================
# Malformed API Response Tests
# ===========================================================================


@patch.dict(os.environ, {"LLM_MIN_INTERVAL_SECONDS": "0"}, clear=False)
class TestMalformedResponses(unittest.TestCase):
    """Test handling of unexpected API response formats."""

    def setUp(self):
        import quant_llm_wiki.shared as kb_shared
        kb_shared._last_llm_call_ts = 0.0

    @patch("quant_llm_wiki.shared.get_llm_config", side_effect=_mock_get_llm_config)
    @patch("quant_llm_wiki.shared.requests.post")
    def test_invalid_json_response(self, mock_post, mock_config):
        from quant_llm_wiki.shared import post_llm_json

        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.side_effect = json.JSONDecodeError("Expecting value", "", 0)
        mock_post.return_value = resp

        with self.assertRaises(json.JSONDecodeError):
            post_llm_json("/chat/completions", {"model": "test", "messages": []})

    @patch("quant_llm_wiki.shared.get_llm_config", side_effect=_mock_get_llm_config)
    @patch("quant_llm_wiki.shared.requests.post")
    def test_missing_choices_key(self, mock_post, mock_config):
        from quant_llm_wiki.shared import call_llm_chat

        mock_post.return_value = _make_mock_response(200, {"data": "unexpected"})

        with self.assertRaises(KeyError):
            call_llm_chat([{"role": "user", "content": "test"}])

    @patch("quant_llm_wiki.shared.get_llm_config", side_effect=_mock_get_llm_config)
    @patch("quant_llm_wiki.shared.requests.post")
    def test_missing_embedding_data(self, mock_post, mock_config):
        from quant_llm_wiki.shared import embed_text

        mock_post.return_value = _make_mock_response(200, {"choices": []})

        with self.assertRaises((KeyError, IndexError)):
            embed_text("test text")

    @patch("quant_llm_wiki.shared.get_llm_config", side_effect=_mock_get_llm_config)
    @patch("quant_llm_wiki.shared.requests.post")
    def test_truncated_embedding_vector(self, mock_post, mock_config):
        from quant_llm_wiki.shared import embed_text

        short_embedding = [0.1, 0.2, 0.3]
        mock_post.return_value = _make_mock_response(
            200, {"data": [{"embedding": short_embedding}]}
        )

        result = embed_text("test text")
        # embed_text does no dimension validation — returns as-is
        self.assertEqual(result, short_embedding)

    @patch("quant_llm_wiki.shared.get_llm_config", side_effect=_mock_get_llm_config)
    @patch("quant_llm_wiki.shared.requests.post")
    def test_empty_chat_response_content(self, mock_post, mock_config):
        from quant_llm_wiki.shared import call_llm_chat

        mock_post.return_value = _make_mock_response(
            200, {"choices": [{"message": {"content": ""}}]}
        )

        result = call_llm_chat([{"role": "user", "content": "test"}])
        self.assertEqual(result, "")


# ===========================================================================
# Configuration Robustness Tests
# ===========================================================================


@patch.dict(os.environ, {"LLM_MIN_INTERVAL_SECONDS": "0"}, clear=False)
class TestConfigurationRobustness(unittest.TestCase):
    """Test get_llm_config and related config functions under edge conditions."""

    def setUp(self):
        import quant_llm_wiki.shared as kb_shared
        kb_shared._last_llm_call_ts = 0.0

    @patch.dict(
        os.environ,
        {"LLM_API_KEY": "", "ZHIPU_API_KEY": ""},
        clear=False,
    )
    def test_missing_api_key_raises(self):
        from quant_llm_wiki.shared import get_llm_config

        with self.assertRaises(RuntimeError) as ctx:
            get_llm_config()
        self.assertIn("API key is required", str(ctx.exception))

    @patch.dict(os.environ, {"LLM_API_KEY": "env-key-999"}, clear=False)
    def test_api_key_from_env(self):
        from quant_llm_wiki.shared import get_llm_config

        api_key, _, _ = get_llm_config()
        self.assertEqual(api_key, "env-key-999")

    @patch.dict(
        os.environ,
        {"LLM_API_KEY": "", "ZHIPU_API_KEY": "zhipu-legacy-key"},
        clear=False,
    )
    def test_legacy_zhipu_env_fallback(self):
        from quant_llm_wiki.shared import get_llm_config

        api_key, _, _ = get_llm_config()
        self.assertEqual(api_key, "zhipu-legacy-key")

    @patch("quant_llm_wiki.shared.get_llm_config", side_effect=_mock_get_llm_config)
    @patch("quant_llm_wiki.shared.time.sleep")
    @patch("quant_llm_wiki.shared.requests.post")
    @patch.dict(os.environ, {"LLM_CONNECT_TIMEOUT": "5", "LLM_READ_TIMEOUT": "30"}, clear=False)
    def test_custom_timeout_from_env(self, mock_post, mock_sleep, mock_config):
        from quant_llm_wiki.shared import post_llm_json

        mock_post.return_value = _make_mock_response(200, {"result": "ok"})

        post_llm_json("/chat/completions", {"model": "test", "messages": []})

        # Verify timeout was passed to requests.post
        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs["timeout"], (5, 30))


# ===========================================================================
# End-to-End API Failure in Tools
# ===========================================================================


class TestToolAPIFailures(RobustTestBase):
    """Test that tools gracefully handle API failures and return error strings."""

    @patch("quant_llm_wiki.enrich.get_llm_config", return_value=("fake-key", "https://fake.url/v4", "glm-4.7"))
    @patch("quant_llm_wiki.shared.get_llm_config", return_value=("fake-key", "https://fake.url/v4", "glm-4.7"))
    @patch("quant_llm_wiki.shared.post_llm_json")
    def test_enrich_articles_api_failure(self, mock_post, mock_config, mock_enrich_config):
        from agent.tools import enrich_articles

        mock_post.side_effect = requests_lib.exceptions.ConnectionError("API unreachable")

        ArticleFixtureFactory.create_raw_article(
            self.tmp_root, "api_fail_article", title="API Fail Test", llm_enriched=False
        )
        result = enrich_articles.invoke({"status_filter": "raw"})
        self.assertIsInstance(result, str)
        # Should report failure, not crash
        self.assertTrue(
            "failed" in result.lower() or "error" in result.lower() or "0/" in result,
            f"Expected failure indication in: {result}"
        )

    @patch("quant_llm_wiki.shared.call_llm_chat")
    @patch("quant_llm_wiki.shared.get_llm_config", return_value=("fake-key", "https://fake.url/v4", "glm-4.7"))
    def test_query_kb_api_failure(self, mock_config, mock_chat):
        from agent.tools import query_knowledge_base

        mock_chat.side_effect = requests_lib.exceptions.ReadTimeout("Read timed out")

        ArticleFixtureFactory.create_reviewed_article(
            self.tmp_root, "query_fail_article", title="Query Fail Test"
        )
        result = query_knowledge_base.invoke({
            "query": "test query",
            "mode": "ask",
            "retrieval": "keyword",
        })
        self.assertIsInstance(result, str)
        self.assertTrue(
            "error" in result.lower() or "timed out" in result.lower(),
            f"Expected error in: {result}"
        )

    @patch("quant_llm_wiki.shared.embed_text")
    @patch("quant_llm_wiki.shared.get_llm_config", return_value=("fake-key", "https://fake.url/v4", "glm-4.7"))
    def test_embed_knowledge_api_failure(self, mock_config, mock_embed):
        from agent.tools import embed_knowledge

        mock_embed.side_effect = requests_lib.exceptions.HTTPError("503 Service Unavailable")

        ArticleFixtureFactory.create_reviewed_article(
            self.tmp_root, "embed_fail_article", title="Embed Fail Test"
        )
        result = embed_knowledge.invoke({"force": True})
        self.assertIsInstance(result, str)
        self.assertIn("1 failed", result)


if __name__ == "__main__":
    unittest.main()
