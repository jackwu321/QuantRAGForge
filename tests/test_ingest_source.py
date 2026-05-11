import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import quant_llm_wiki.ingest.source as ingest_source


class DispatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._kb_root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @patch("quant_llm_wiki.ingest.source._is_wechat_url")
    @patch("quant_llm_wiki.ingest.source._dispatch_wechat")
    def test_url_routing_wechat(self, mock_we, mock_is_we) -> None:
        mock_is_we.return_value = True
        mock_we.return_value = "/tmp/out"
        result = ingest_source.dispatch_url("https://mp.weixin.qq.com/s/abc", kb_root=self._kb_root)
        mock_we.assert_called_once()
        self.assertEqual(result, "/tmp/out")

    @patch("quant_llm_wiki.ingest.source._is_wechat_url", return_value=False)
    @patch("quant_llm_wiki.ingest.source._is_pdf_url", return_value=True)
    @patch("quant_llm_wiki.ingest.source._dispatch_pdf_url")
    def test_url_routing_pdf(self, mock_pdf, *_) -> None:
        mock_pdf.return_value = "/tmp/pdf"
        ingest_source.dispatch_url("https://example.com/paper.pdf", kb_root=self._kb_root)
        mock_pdf.assert_called_once()

    @patch("quant_llm_wiki.ingest.source._is_wechat_url", return_value=False)
    @patch("quant_llm_wiki.ingest.source._is_pdf_url", return_value=False)
    @patch("quant_llm_wiki.ingest.source._dispatch_web")
    def test_url_routing_generic_web(self, mock_web, *_) -> None:
        mock_web.return_value = "/tmp/web"
        ingest_source.dispatch_url("https://example.com/blog/post", kb_root=self._kb_root)
        mock_web.assert_called_once()

    def test_is_wechat_url(self) -> None:
        self.assertTrue(ingest_source._is_wechat_url("https://mp.weixin.qq.com/s/x"))
        self.assertFalse(ingest_source._is_wechat_url("https://substack.com/p/x"))

    def test_is_pdf_url_extension(self) -> None:
        self.assertTrue(ingest_source._is_pdf_url("https://example.com/paper.pdf"))
        self.assertFalse(ingest_source._is_pdf_url("https://example.com/blog"))


class WriteWebArticleTests(unittest.TestCase):
    def test_write_web_article_creates_directory(self) -> None:
        from quant_llm_wiki.ingest.web import ExtractedArticle

        with tempfile.TemporaryDirectory() as tmp:
            kb_root = Path(tmp)
            article = ExtractedArticle(
                title="Test Post",
                text="Body.",
                markdown="# Test\n\nBody.",
                has_code=False,
                has_math=False,
                paywalled=False,
                extraction_quality="full",
                source_url="https://example.com/test-post",
            )
            out_dir = ingest_source.write_web_article(article, kb_root=kb_root)
            self.assertTrue((out_dir / "article.md").exists())
            self.assertTrue((out_dir / "source.json").exists())
            text = (out_dir / "article.md").read_text(encoding="utf-8")
            self.assertIn("source_type: web", text)
            self.assertIn("extraction_quality: full", text)


if __name__ == "__main__":
    unittest.main()
