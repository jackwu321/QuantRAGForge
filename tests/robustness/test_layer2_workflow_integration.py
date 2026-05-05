"""Layer 2: Workflow integration tests — multi-step pipelines with real FS + ChromaDB."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.robustness.conftest import (
    RobustTestBase,
    ArticleFixtureFactory,
    MockLLMFactory,
)


class TestFullPipelineReviewToQuery(RobustTestBase):
    """End-to-end: create raw article → review → set status → embed → query.
    Articles stay in raw/; the frontmatter status field decides their stage."""

    @patch("kb_shared.embed_text")
    @patch("kb_shared.post_llm_json")
    @patch("kb_shared.get_llm_config", return_value=("fake-key", "https://fake.url/v4", "glm-4.7"))
    def test_full_pipeline(self, mock_config, mock_post, mock_embed):
        from agent.tools import (
            review_articles,
            set_article_status,
            embed_knowledge,
            query_knowledge_base,
        )

        mock_embed.side_effect = lambda text, model=None: MockLLMFactory.make_embed_text_mock()(text, model)
        mock_post.return_value = {
            "choices": [{"message": {"content": "The momentum strategy works by combining signals."}}]
        }

        # 1. Create raw article
        article_dir = ArticleFixtureFactory.create_raw_article(
            self.tmp_root, "momentum_strategy",
            title="Momentum Strategy Research",
            content_type="strategy",
            summary="A momentum-based trading strategy for A-shares.",
            body_content="This article explores momentum factor in Chinese markets.",
        )

        # 2. Review — verify article appears
        review_result = review_articles.invoke({"source_dir": "raw"})
        self.assertIn("Momentum Strategy Research", review_result)
        self.assertIn("strategy", review_result)

        # 3. Set status to reviewed (frontmatter only; article stays in raw/)
        status_result = set_article_status.invoke(
            {"article_paths": [str(article_dir)], "status": "reviewed"}
        )
        self.assertIn("reviewed", status_result)
        self.assertTrue(article_dir.exists(), "Article stays in raw/ after status change")

        # 4. Embed
        embed_result = embed_knowledge.invoke({"force": True})
        self.assertIn("1 indexed", embed_result)

        # 6. Query — use keyword mode to avoid vector search
        query_result = query_knowledge_base.invoke({
            "query": "momentum strategies",
            "mode": "ask",
            "retrieval": "keyword",
        })
        # The mocked chat returns the response
        self.assertIn("momentum", query_result.lower())


class TestPipelineMultipleArticles(RobustTestBase):
    """Multiple articles with different target statuses."""

    @patch("kb_shared.embed_text")
    @patch("kb_shared.get_llm_config", return_value=("fake-key", "https://fake.url/v4", "glm-4.7"))
    def test_multiple_articles_different_statuses(self, mock_config, mock_embed):
        from agent.tools import set_article_status, embed_knowledge

        mock_embed.side_effect = lambda text, model=None: MockLLMFactory.make_embed_text_mock()(text, model)

        # Create 3 raw articles
        a1 = ArticleFixtureFactory.create_raw_article(
            self.tmp_root, "article_1", title="Article One", content_type="methodology"
        )
        a2 = ArticleFixtureFactory.create_raw_article(
            self.tmp_root, "article_2", title="Article Two", content_type="strategy"
        )
        a3 = ArticleFixtureFactory.create_raw_article(
            self.tmp_root, "article_3", title="Article Three", content_type="allocation"
        )

        # Set statuses — articles all stay flat in raw/, status lives in frontmatter
        set_article_status.invoke(
            {"article_paths": [str(a1), str(a2)], "status": "high_value"}
        )
        set_article_status.invoke(
            {"article_paths": [str(a3)], "status": "reviewed"}
        )

        # All three still under raw/
        self.assertTrue((self.tmp_root / "raw" / "article_1").exists())
        self.assertTrue((self.tmp_root / "raw" / "article_2").exists())
        self.assertTrue((self.tmp_root / "raw" / "article_3").exists())

        # Embed all
        embed_result = embed_knowledge.invoke({"force": True})
        self.assertIn("3 indexed", embed_result)


class TestPipelineErrorRecoveryEmbedPartial(RobustTestBase):
    """Embed partially fails — one article succeeds, another fails."""

    @patch("kb_shared.embed_text")
    @patch("kb_shared.get_llm_config", return_value=("fake-key", "https://fake.url/v4", "glm-4.7"))
    def test_partial_embed_failure(self, mock_config, mock_embed):
        from agent.tools import embed_knowledge

        # Track which article is being embedded by text content
        succeeded_articles = set()
        call_count = [0]

        def embed_with_selective_failure(text, model=None):
            call_count[0] += 1
            # Let first several calls succeed (first article), then fail
            if "Bad Article" in text or call_count[0] > 8:
                raise RuntimeError("Simulated API timeout")
            return MockLLMFactory.make_embed_text_mock()(text, model)

        mock_embed.side_effect = embed_with_selective_failure

        ArticleFixtureFactory.create_reviewed_article(
            self.tmp_root, "good_article", title="Good Article",
            summary="Good summary",
        )
        ArticleFixtureFactory.create_reviewed_article(
            self.tmp_root, "bad_article", title="Bad Article",
            summary="Bad Article details",
        )

        result = embed_knowledge.invoke({"force": True})
        # Should have some failures
        self.assertIn("failed", result.lower())
        # At least one should succeed
        self.assertNotIn("0 indexed, 0 skipped, 0 failed", result)


class TestIdempotentEmbed(RobustTestBase):
    """Embedding twice without force should skip on second run."""

    @patch("kb_shared.embed_text")
    @patch("kb_shared.get_llm_config", return_value=("fake-key", "https://fake.url/v4", "glm-4.7"))
    def test_idempotent(self, mock_config, mock_embed):
        from agent.tools import embed_knowledge

        mock_embed.side_effect = lambda text, model=None: MockLLMFactory.make_embed_text_mock()(text, model)

        ArticleFixtureFactory.create_reviewed_article(
            self.tmp_root, "idem_article", title="Idempotent Article"
        )

        # First run — indexes
        r1 = embed_knowledge.invoke({"force": False})
        self.assertIn("1 indexed", r1)

        # Second run — skips
        r2 = embed_knowledge.invoke({"force": False})
        self.assertIn("1 skipped", r2)
        self.assertIn("0 indexed", r2)


class TestSyncThenEmbedRoundtrip(RobustTestBase):
    """Create reviewed articles directly, embed, verify index populated."""

    @patch("kb_shared.embed_text")
    @patch("kb_shared.get_llm_config", return_value=("fake-key", "https://fake.url/v4", "glm-4.7"))
    def test_roundtrip(self, mock_config, mock_embed):
        from agent.tools import embed_knowledge, list_articles

        mock_embed.side_effect = lambda text, model=None: MockLLMFactory.make_embed_text_mock()(text, model)

        # Create articles directly in reviewed/
        ArticleFixtureFactory.create_reviewed_article(
            self.tmp_root, "direct_1", title="Direct Article 1"
        )
        ArticleFixtureFactory.create_reviewed_article(
            self.tmp_root, "direct_2", title="Direct Article 2"
        )

        # List to verify they're visible
        list_result = list_articles.invoke({"source_dir": "reviewed"})
        self.assertIn("2 articles", list_result)

        # Embed
        embed_result = embed_knowledge.invoke({"force": True})
        self.assertIn("2 indexed", embed_result)

        # Verify manifest exists
        manifest_path = self.tmp_root / "vector_store" / "index_manifest.json"
        self.assertTrue(manifest_path.exists())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["articles"]), 2)


if __name__ == "__main__":
    unittest.main()
