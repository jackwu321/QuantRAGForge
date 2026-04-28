import unittest
from unittest.mock import patch

import _web_extract


SAMPLE_HTML = """<!DOCTYPE html>
<html><body>
<article>
<h1>Momentum Reversal Effect</h1>
<p>By Jane Doe · 2026-04-01</p>
<p>The momentum factor exhibits reversal at long horizons.</p>
<pre><code class="language-python">x = 1</code></pre>
<p>Equation: $r_t = \\beta x_t$.</p>
</article>
</body></html>"""


class WebExtractTests(unittest.TestCase):
    def test_extract_returns_text_with_code_and_math(self) -> None:
        result = _web_extract.extract_from_html(SAMPLE_HTML, source_url="https://example.com/x")
        self.assertIn("Momentum Reversal Effect", result.title)
        self.assertIn("momentum factor", result.text)
        self.assertTrue(result.has_code)
        self.assertTrue(result.has_math)
        self.assertIn("```python", result.markdown)
        self.assertIn("$r_t", result.markdown)
        self.assertEqual(result.extraction_quality, "full")

    def test_paywall_detection(self) -> None:
        paywalled = "<html><body><p>Subscribe to read this article. Please subscribe.</p></body></html>"
        result = _web_extract.extract_from_html(paywalled, source_url="https://example.com/p")
        self.assertTrue(result.paywalled)

    def test_empty_html_returns_text_only(self) -> None:
        result = _web_extract.extract_from_html("", source_url="https://example.com/empty")
        self.assertEqual(result.extraction_quality, "text_only")
        self.assertEqual(result.text, "")

    @patch("_web_extract._fetch_url_text")
    def test_extract_from_url_calls_fetch(self, mock_fetch) -> None:
        mock_fetch.return_value = SAMPLE_HTML
        result = _web_extract.extract_from_url("https://example.com/x")
        self.assertEqual(result.title, "Momentum Reversal Effect")
        mock_fetch.assert_called_once_with("https://example.com/x")


if __name__ == "__main__":
    unittest.main()
