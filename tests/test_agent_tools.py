from __future__ import annotations

import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestSetArticleStatus(unittest.TestCase):
    """Test set_article_status frontmatter rewriting."""

    def _make_article(self, tmp: Path, status: str = "raw") -> Path:
        article_dir = tmp / "test_article"
        article_dir.mkdir()
        md = textwrap.dedent(f"""\
            ---
            title: Test Article
            status: {status}
            content_type: methodology
            brainstorm_value: high
            ---

            ## Main Content

            Some content here.
        """)
        (article_dir / "article.md").write_text(md, encoding="utf-8")
        return article_dir

    def test_update_status_to_reviewed(self):
        from agent.tools import set_article_status

        with tempfile.TemporaryDirectory() as tmp:
            article_dir = self._make_article(Path(tmp), "raw")
            result = set_article_status.invoke(
                {"article_paths": [str(article_dir)], "status": "reviewed"}
            )
            self.assertIn("reviewed", result)
            content = (article_dir / "article.md").read_text(encoding="utf-8")
            self.assertIn("status: reviewed", content)
            self.assertNotIn("status: raw", content)

    def test_update_status_to_high_value(self):
        from agent.tools import set_article_status

        with tempfile.TemporaryDirectory() as tmp:
            article_dir = self._make_article(Path(tmp), "raw")
            result = set_article_status.invoke(
                {"article_paths": [str(article_dir)], "status": "high_value"}
            )
            self.assertIn("high_value", result)
            content = (article_dir / "article.md").read_text(encoding="utf-8")
            self.assertIn("status: high_value", content)

    def test_invalid_status_rejected(self):
        from agent.tools import set_article_status

        result = set_article_status.invoke(
            {"article_paths": ["/nonexistent"], "status": "invalid"}
        )
        self.assertIn("Invalid status", result)

    def test_preserves_other_frontmatter(self):
        from agent.tools import set_article_status

        with tempfile.TemporaryDirectory() as tmp:
            article_dir = self._make_article(Path(tmp), "raw")
            set_article_status.invoke(
                {"article_paths": [str(article_dir)], "status": "reviewed"}
            )
            content = (article_dir / "article.md").read_text(encoding="utf-8")
            self.assertIn("title: Test Article", content)
            self.assertIn("content_type: methodology", content)
            self.assertIn("brainstorm_value: high", content)
            self.assertIn("## Main Content", content)

    def test_missing_article_md(self):
        from agent.tools import set_article_status

        with tempfile.TemporaryDirectory() as tmp:
            result = set_article_status.invoke(
                {"article_paths": [tmp], "status": "reviewed"}
            )
            self.assertIn("Not found", result)


class TestListArticles(unittest.TestCase):
    """Test list_articles tool."""

    @patch("agent.tools.discover_article_dirs")
    @patch("agent.tools.parse_frontmatter")
    def test_list_articles_output(self, mock_fm, mock_discover):
        from agent.tools import list_articles

        tmp = Path("/tmp/test_kb")
        article_dir = tmp / "articles" / "raw" / "test_article"
        mock_discover.return_value = [("raw", article_dir)]

        mock_fm.return_value = (
            {"title": "Test Article", "content_type": "methodology", "brainstorm_value": "high"},
            "body",
        )
        with patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.read_text", return_value="---\ntitle: Test\n---\nbody"):
            result = list_articles.invoke({"source_dir": "raw"})
        self.assertIn("raw", result)

    def test_no_articles(self):
        from agent.tools import list_articles

        with patch("agent.tools.discover_article_dirs", return_value=[]):
            result = list_articles.invoke({"source_dir": "nonexistent"})
            self.assertIn("0 articles", result)


class TestReviewArticles(unittest.TestCase):
    """Test review_articles tool."""

    def test_no_articles_found(self):
        from agent.tools import review_articles

        with patch("agent.tools.discover_article_dirs", return_value=[]):
            result = review_articles.invoke({"source_dir": "raw"})
            self.assertIn("No articles", result)

    def test_review_output_format(self):
        from agent.tools import review_articles

        with tempfile.TemporaryDirectory() as tmp:
            article_dir = Path(tmp) / "test_article"
            article_dir.mkdir()
            md = textwrap.dedent("""\
                ---
                title: Test Strategy
                status: raw
                content_type: strategy
                brainstorm_value: high
                summary: A momentum strategy for A-shares.
                ---

                ## Main Content

                Content here.
            """)
            (article_dir / "article.md").write_text(md, encoding="utf-8")
            (article_dir / "source.json").write_text('{"llm_enriched": true}', encoding="utf-8")

            with patch("agent.tools.discover_article_dirs", return_value=[("raw", article_dir)]):
                result = review_articles.invoke({"source_dir": "raw"})
                self.assertIn("Test Strategy", result)
                self.assertIn("strategy", result)
                self.assertIn("high", result)
                self.assertIn("1.", result)


class TestToolsReturnStrings(unittest.TestCase):
    """Verify all tools return strings on error conditions."""

    def test_ingest_article_bad_url(self):
        from agent.tools import ingest_article

        with patch("ingest_wechat_article.fetch_html", side_effect=Exception("Network error")):
            result = ingest_article.invoke({"url": "https://bad.url"})
            self.assertIsInstance(result, str)
            self.assertIn("failed", result.lower())

    def test_query_no_articles(self):
        from agent.tools import query_knowledge_base

        with patch("agent.tools.load_notes", return_value=[]):
            result = query_knowledge_base.invoke({"query": "test", "mode": "ask"})
            self.assertIsInstance(result, str)
            self.assertIn("No candidate", result)


if __name__ == "__main__":
    unittest.main()
