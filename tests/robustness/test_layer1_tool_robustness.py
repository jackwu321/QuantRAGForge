"""Layer 1: Tool-level robustness tests — edge cases and malformed inputs."""
from __future__ import annotations

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


# ===========================================================================
# set_article_status
# ===========================================================================


class TestSetArticleStatusRobust(RobustTestBase):

    def test_empty_article_paths_list(self):
        from agent.tools import set_article_status
        result = set_article_status.invoke({"article_paths": [], "status": "reviewed"})
        self.assertIn("0", result)

    def test_nonexistent_directory(self):
        from agent.tools import set_article_status
        result = set_article_status.invoke(
            {"article_paths": ["/nonexistent/path/xyz"], "status": "reviewed"}
        )
        self.assertIn("Not found", result)

    def test_article_without_status_line(self):
        """Frontmatter exists but has no status: field — tests insert branch."""
        from agent.tools import set_article_status

        article_dir = self.tmp_root / "raw" / "no_status"
        article_dir.mkdir(parents=True)
        (article_dir / "article.md").write_text(
            "---\ntitle: No Status Article\ncontent_type: methodology\n---\n\nBody\n",
            encoding="utf-8",
        )
        result = set_article_status.invoke(
            {"article_paths": [str(article_dir)], "status": "reviewed"}
        )
        content = (article_dir / "article.md").read_text(encoding="utf-8")
        self.assertIn("status: reviewed", content)
        self.assertIn("title: No Status Article", content)

    def test_article_with_no_frontmatter(self):
        """File has no --- delimiters at all."""
        from agent.tools import set_article_status

        article_dir = self.tmp_root / "raw" / "no_fm"
        article_dir.mkdir(parents=True)
        (article_dir / "article.md").write_text("Just plain text, no frontmatter.\n")
        result = set_article_status.invoke(
            {"article_paths": [str(article_dir)], "status": "reviewed"}
        )
        # Should not crash — either updates or reports
        self.assertIsInstance(result, str)

    def test_duplicate_status_update_idempotent(self):
        """Setting status to the same value twice should not duplicate the line."""
        from agent.tools import set_article_status

        article_dir = ArticleFixtureFactory.create_raw_article(
            self.tmp_root, "idem", status="raw"
        )
        set_article_status.invoke(
            {"article_paths": [str(article_dir)], "status": "reviewed"}
        )
        set_article_status.invoke(
            {"article_paths": [str(article_dir)], "status": "reviewed"}
        )
        content = (article_dir / "article.md").read_text(encoding="utf-8")
        self.assertIn("status: reviewed", content)
        self.assertEqual(content.count("status:"), 1)

    def test_status_update_different_values(self):
        """Setting status twice to different values should update correctly."""
        from agent.tools import set_article_status

        article_dir = ArticleFixtureFactory.create_raw_article(
            self.tmp_root, "diff", status="raw"
        )
        set_article_status.invoke(
            {"article_paths": [str(article_dir)], "status": "reviewed"}
        )
        set_article_status.invoke(
            {"article_paths": [str(article_dir)], "status": "high_value"}
        )
        content = (article_dir / "article.md").read_text(encoding="utf-8")
        self.assertIn("status: high_value", content)
        self.assertNotIn("status: reviewed", content)

    def test_unicode_chinese_path(self):
        from agent.tools import set_article_status

        article_dir = ArticleFixtureFactory.create_raw_article(
            self.tmp_root, "量化策略研究", title="中文标题文章"
        )
        result = set_article_status.invoke(
            {"article_paths": [str(article_dir)], "status": "reviewed"}
        )
        content = (article_dir / "article.md").read_text(encoding="utf-8")
        self.assertIn("status: reviewed", content)
        self.assertIn("title: 中文标题文章", content)


# ===========================================================================
# list_articles
# ===========================================================================


class TestListArticlesRobust(RobustTestBase):

    def test_empty_knowledge_base(self):
        from agent.tools import list_articles
        result = list_articles.invoke({"source_dir": "raw"})
        self.assertIn("0 articles", result)

    def test_article_md_missing(self):
        """Directory exists but article.md is absent."""
        from agent.tools import list_articles

        (self.tmp_root / "raw" / "empty_dir").mkdir(parents=True)
        result = list_articles.invoke({"source_dir": "raw"})
        # Should not crash; directory without article.md is skipped
        self.assertIn("0 articles", result)

    def test_nonexistent_source_dir(self):
        from agent.tools import list_articles
        result = list_articles.invoke({"source_dir": "nonexistent_stage"})
        self.assertIn("0 articles", result)

    def test_mixed_populated_and_empty_dirs(self):
        from agent.tools import list_articles

        ArticleFixtureFactory.create_raw_article(self.tmp_root, "real_article", title="Real Article")
        (self.tmp_root / "raw" / "empty_dir").mkdir()
        result = list_articles.invoke({"source_dir": "raw"})
        self.assertIn("Real Article", result)
        self.assertIn("1 articles", result)


# ===========================================================================
# review_articles
# ===========================================================================


class TestReviewArticlesRobust(RobustTestBase):

    def test_summary_truncation(self):
        from agent.tools import review_articles

        long_summary = "A" * 200
        ArticleFixtureFactory.create_raw_article(
            self.tmp_root, "long_summary", summary=long_summary
        )
        result = review_articles.invoke({"source_dir": "raw"})
        self.assertIn("...", result)
        self.assertNotIn("A" * 200, result)

    def test_missing_frontmatter_fields(self):
        from agent.tools import review_articles

        article_dir = self.tmp_root / "raw" / "minimal"
        article_dir.mkdir(parents=True)
        (article_dir / "article.md").write_text(
            "---\ntitle: Minimal\n---\n\nBody\n", encoding="utf-8"
        )
        (article_dir / "source.json").write_text('{"llm_enriched": true}', encoding="utf-8")
        result = review_articles.invoke({"source_dir": "raw"})
        self.assertIn("Minimal", result)
        self.assertIsInstance(result, str)


# ===========================================================================
# ingest_article
# ===========================================================================


class TestIngestArticleRobust(RobustTestBase):

    def test_no_input_provided(self):
        from agent.tools import ingest_article
        result = ingest_article.invoke({})
        self.assertIn("provide", result.lower())

    def test_empty_urls_string(self):
        from agent.tools import ingest_article
        result = ingest_article.invoke({"urls": ""})
        self.assertIn("provide", result.lower())

    def test_html_file_not_found(self):
        from agent.tools import ingest_article
        result = ingest_article.invoke({"html_file": "/nonexistent/file.html"})
        self.assertIn("Error", result)

    def test_url_list_file_not_found(self):
        from agent.tools import ingest_article
        result = ingest_article.invoke({"url_list_file": "/nonexistent/urls.txt"})
        self.assertIn("Error", result)

    @patch("ingest_wechat_article.fetch_html", return_value="<html><body><h1>Test</h1><p>Content here for testing purposes.</p></body></html>")
    @patch("ingest_wechat_article.download_binary", return_value=(b"", "image/png"))
    def test_duplicate_url_skipped(self, mock_download, mock_fetch):
        """Second ingestion of same URL should be skipped."""
        from agent.tools import ingest_article
        import ingest_wechat_article as ingest_mod

        original_raw_dir = ingest_mod.ARTICLES_RAW_DIR
        ingest_mod.ARTICLES_RAW_DIR = self.tmp_root / "raw"
        try:
            # First ingest
            result1 = ingest_article.invoke({"url": "https://mp.weixin.qq.com/s/article1"})
            self.assertIn("1 ingested", result1)

            # Second ingest of same URL — should skip
            result2 = ingest_article.invoke({"url": "https://mp.weixin.qq.com/s/article1"})
            self.assertIn("skipped", result2.lower())
            self.assertIn("already exist", result2.lower())
        finally:
            ingest_mod.ARTICLES_RAW_DIR = original_raw_dir

    @patch("ingest_wechat_article.fetch_html", return_value="<html><body><h1>Test</h1><p>Content here for testing purposes.</p></body></html>")
    @patch("ingest_wechat_article.download_binary", return_value=(b"", "image/png"))
    def test_duplicate_url_force_reingest(self, mock_download, mock_fetch):
        """With force=True, duplicate should be re-ingested."""
        from agent.tools import ingest_article
        import ingest_wechat_article as ingest_mod

        original_raw_dir = ingest_mod.ARTICLES_RAW_DIR
        ingest_mod.ARTICLES_RAW_DIR = self.tmp_root / "raw"
        try:
            # First ingest
            result1 = ingest_article.invoke({"url": "https://mp.weixin.qq.com/s/article1"})
            self.assertIn("1 ingested", result1)

            # Force re-ingest
            result2 = ingest_article.invoke({"url": "https://mp.weixin.qq.com/s/article1", "force": True})
            self.assertIn("1 ingested", result2)
            self.assertNotIn("skipped", result2.lower())
        finally:
            ingest_mod.ARTICLES_RAW_DIR = original_raw_dir

    @patch("ingest_wechat_article.fetch_html", return_value="<html><body><h1>Test</h1><p>Content here for testing purposes.</p></body></html>")
    @patch("ingest_wechat_article.download_binary", return_value=(b"", "image/png"))
    def test_duplicate_detected_in_raw(self, mock_download, mock_fetch):
        """Article already in raw/ should be detected as duplicate on re-ingest."""
        from agent.tools import ingest_article
        import ingest_wechat_article as ingest_mod

        original_raw_dir = ingest_mod.ARTICLES_RAW_DIR
        ingest_mod.ARTICLES_RAW_DIR = self.tmp_root / "raw"
        try:
            # First ingest writes to raw/
            result1 = ingest_article.invoke({"url": "https://mp.weixin.qq.com/s/article2"})
            self.assertIn("1 ingested", result1)

            # Second ingest of the same URL should detect the existing article in raw/
            result2 = ingest_article.invoke({"url": "https://mp.weixin.qq.com/s/article2"})
            self.assertIn("skipped", result2.lower())
        finally:
            ingest_mod.ARTICLES_RAW_DIR = original_raw_dir


# ===========================================================================
# embed_knowledge
# ===========================================================================


class TestEmbedKnowledgeRobust(RobustTestBase):

    def test_no_articles_to_embed(self):
        from agent.tools import embed_knowledge
        result = embed_knowledge.invoke({})
        self.assertIn("No articles", result)

    @patch("quant_llm_wiki.shared.embed_text")
    @patch("quant_llm_wiki.shared.get_llm_config", return_value=("fake-key", "https://fake.url/v4", "glm-4.7"))
    def test_single_article_embed(self, mock_config, mock_embed):
        from agent.tools import embed_knowledge

        mock_embed.side_effect = lambda text, model=None: MockLLMFactory.make_embed_text_mock()(text, model)
        ArticleFixtureFactory.create_reviewed_article(
            self.tmp_root, "embed_test",
            title="Embed Test Article",
            summary="Test embedding summary",
            body_content="Paragraph about momentum strategies.",
        )
        result = embed_knowledge.invoke({"force": True})
        self.assertIn("1 indexed", result)
        self.assertIn("0 failed", result)

    @patch("quant_llm_wiki.shared.embed_text")
    @patch("quant_llm_wiki.shared.get_llm_config", return_value=("fake-key", "https://fake.url/v4", "glm-4.7"))
    def test_force_reindex(self, mock_config, mock_embed):
        from agent.tools import embed_knowledge

        mock_embed.side_effect = lambda text, model=None: MockLLMFactory.make_embed_text_mock()(text, model)
        ArticleFixtureFactory.create_reviewed_article(
            self.tmp_root, "reindex_test", title="Reindex Article"
        )
        # First embed
        result1 = embed_knowledge.invoke({"force": False})
        self.assertIn("1 indexed", result1)

        # Second embed without force — should skip
        result2 = embed_knowledge.invoke({"force": False})
        self.assertIn("1 skipped", result2)
        self.assertIn("0 indexed", result2)

        # Third embed with force — should re-index
        result3 = embed_knowledge.invoke({"force": True})
        self.assertIn("1 indexed", result3)

    @patch("quant_llm_wiki.shared.embed_text")
    @patch("quant_llm_wiki.shared.get_llm_config", return_value=("fake-key", "https://fake.url/v4", "glm-4.7"))
    def test_embedding_failure_mid_batch(self, mock_config, mock_embed):
        from agent.tools import embed_knowledge

        call_count = [0]

        def embed_with_failure(text, model=None):
            call_count[0] += 1
            if call_count[0] > 5:
                raise RuntimeError("Simulated embedding failure")
            return MockLLMFactory.make_embed_text_mock()(text, model)

        mock_embed.side_effect = embed_with_failure

        ArticleFixtureFactory.create_reviewed_article(
            self.tmp_root, "success_article", title="Will Succeed"
        )
        ArticleFixtureFactory.create_reviewed_article(
            self.tmp_root, "fail_article", title="Will Fail",
            body_content="Long content " * 20,
        )
        result = embed_knowledge.invoke({"force": True})
        self.assertIn("failed", result.lower())


# ===========================================================================
# query_knowledge_base
# ===========================================================================


class TestQueryKnowledgeBaseRobust(RobustTestBase):

    def test_invalid_mode(self):
        from agent.tools import query_knowledge_base
        result = query_knowledge_base.invoke({"query": "test", "mode": "invalid"})
        self.assertIn("Invalid mode", result)

    def test_no_matching_filters(self):
        from agent.tools import query_knowledge_base

        ArticleFixtureFactory.create_reviewed_article(
            self.tmp_root, "method_article", content_type="methodology"
        )
        result = query_knowledge_base.invoke({
            "query": "test",
            "mode": "ask",
            "content_type": "strategy",
        })
        self.assertIn("No candidate", result)

    def test_empty_query(self):
        from agent.tools import query_knowledge_base
        result = query_knowledge_base.invoke({"query": "", "mode": "ask"})
        self.assertIsInstance(result, str)


if __name__ == "__main__":
    unittest.main()
