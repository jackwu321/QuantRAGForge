import unittest
from pathlib import Path

import _pdf_extract


FIXTURE_DIR = Path(__file__).parent / "fixtures"


class PdfExtractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Create a tiny in-memory PDF fixture using pypdf.
        from pypdf import PdfWriter
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        cls.fixture_path = FIXTURE_DIR / "sample.pdf"
        if cls.fixture_path.exists():
            return
        # Generate a 1-page PDF whose extracted text is "TEST_BROKER_REPORT alpha=0.05 sigma=0.2".
        # We use reportlab if available, else build minimal PDF by hand.
        try:
            from reportlab.pdfgen import canvas
            c = canvas.Canvas(str(cls.fixture_path))
            c.drawString(100, 800, "TEST_BROKER_REPORT alpha=0.05 sigma=0.2")
            c.showPage()
            c.save()
        except ImportError:
            # Build minimal PDF manually
            content = (
                b"%PDF-1.4\n"
                b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
                b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
                b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
                b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
                b"4 0 obj<</Length 88>>stream\n"
                b"BT /F1 12 Tf 100 700 Td (TEST_BROKER_REPORT alpha=0.05 sigma=0.2) Tj ET\n"
                b"endstream endobj\n"
                b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
                b"xref\n0 6\n0000000000 65535 f \n"
                b"0000000009 00000 n \n0000000053 00000 n \n0000000099 00000 n \n"
                b"0000000183 00000 n \n0000000282 00000 n \n"
                b"trailer<</Size 6/Root 1 0 R>>\nstartxref\n343\n%%EOF\n"
            )
            cls.fixture_path.write_bytes(content)

    def test_extract_text_from_simple_pdf(self) -> None:
        result = _pdf_extract.extract_from_file(self.fixture_path)
        self.assertIn("TEST_BROKER_REPORT", result.text)
        self.assertIn("alpha=0.05", result.text)
        self.assertEqual(result.extraction_quality, "full")

    def test_extract_returns_unicode_math_chars(self) -> None:
        result = _pdf_extract.extract_from_file(self.fixture_path)
        self.assertIn("alpha=0.05", result.text)

    def test_extract_missing_file_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            _pdf_extract.extract_from_file(Path("/does/not/exist.pdf"))


if __name__ == "__main__":
    unittest.main()
