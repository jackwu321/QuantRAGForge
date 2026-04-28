import unittest
from pathlib import Path

import _code_math


FIXTURE = Path(__file__).parent / "fixtures" / "sample-with-math.html"


class CodeMathTests(unittest.TestCase):
    def test_extract_code_blocks_with_language(self) -> None:
        html = FIXTURE.read_text(encoding="utf-8")
        blocks = _code_math.extract_code_blocks(html)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].language, "python")
        self.assertIn("def momentum", blocks[0].content)

    def test_preserve_inline_math_dollar(self) -> None:
        html = "<p>Equation: $a + b = c$ here.</p>"
        out = _code_math.preserve_math_to_markdown(html)
        self.assertIn("$a + b = c$", out)

    def test_preserve_display_math_dollar(self) -> None:
        html = "<p>Display: $$\\sum x_i$$ here.</p>"
        out = _code_math.preserve_math_to_markdown(html)
        self.assertIn("$$\\sum x_i$$", out)

    def test_preserve_katex_annotation(self) -> None:
        html = '<span><annotation encoding="application/x-tex">\\alpha + \\beta</annotation></span>'
        out = _code_math.preserve_math_to_markdown(html)
        self.assertIn("$\\alpha + \\beta$", out)

    def test_detect_has_code_and_math(self) -> None:
        html = FIXTURE.read_text(encoding="utf-8")
        flags = _code_math.detect_content_flags(html)
        self.assertTrue(flags["has_code"])
        self.assertTrue(flags["has_math"])

    def test_no_code_no_math_html(self) -> None:
        flags = _code_math.detect_content_flags("<p>just text</p>")
        self.assertFalse(flags["has_code"])
        self.assertFalse(flags["has_math"])


if __name__ == "__main__":
    unittest.main()
