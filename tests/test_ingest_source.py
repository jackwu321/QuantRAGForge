import unittest
from unittest.mock import MagicMock, patch

import ingest_source


class DispatcherTests(unittest.TestCase):
    @patch("ingest_source._is_wechat_url")
    @patch("ingest_source._dispatch_wechat")
    def test_url_routing_wechat(self, mock_we, mock_is_we) -> None:
        mock_is_we.return_value = True
        mock_we.return_value = "/tmp/out"
        result = ingest_source.dispatch_url("https://mp.weixin.qq.com/s/abc")
        mock_we.assert_called_once()
        self.assertEqual(result, "/tmp/out")

    @patch("ingest_source._is_wechat_url", return_value=False)
    @patch("ingest_source._is_pdf_url", return_value=True)
    @patch("ingest_source._dispatch_pdf_url")
    def test_url_routing_pdf(self, mock_pdf, *_) -> None:
        mock_pdf.return_value = "/tmp/pdf"
        ingest_source.dispatch_url("https://example.com/paper.pdf")
        mock_pdf.assert_called_once()

    @patch("ingest_source._is_wechat_url", return_value=False)
    @patch("ingest_source._is_pdf_url", return_value=False)
    @patch("ingest_source._dispatch_web")
    def test_url_routing_generic_web(self, mock_web, *_) -> None:
        mock_web.return_value = "/tmp/web"
        ingest_source.dispatch_url("https://example.com/blog/post")
        mock_web.assert_called_once()

    def test_is_wechat_url(self) -> None:
        self.assertTrue(ingest_source._is_wechat_url("https://mp.weixin.qq.com/s/x"))
        self.assertFalse(ingest_source._is_wechat_url("https://substack.com/p/x"))

    def test_is_pdf_url_extension(self) -> None:
        self.assertTrue(ingest_source._is_pdf_url("https://example.com/paper.pdf"))
        self.assertFalse(ingest_source._is_pdf_url("https://example.com/blog"))


class WriteWebArticleTests(unittest.TestCase):
    def test_write_web_article_creates_directory(self) -> None:
        import tempfile
        from pathlib import Path
        from _web_extract import ExtractedArticle

        with tempfile.TemporaryDirectory() as tmp:
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
            out_dir = ingest_source.write_web_article(article, articles_root=Path(tmp))
            self.assertTrue((out_dir / "article.md").exists())
            self.assertTrue((out_dir / "source.json").exists())
            text = (out_dir / "article.md").read_text(encoding="utf-8")
            self.assertIn("source_type: web", text)
            self.assertIn("extraction_quality: full", text)


if __name__ == "__main__":
    unittest.main()
