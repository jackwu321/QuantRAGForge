from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

try:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
except ImportError:  # pragma: no cover
    PdfReader = None
    PdfReadError = Exception

try:
    import pdfplumber
except ImportError:  # pragma: no cover
    pdfplumber = None


@dataclass
class ExtractedPdf:
    text: str
    page_count: int
    has_code: bool
    has_math: bool
    extraction_quality: Literal["full", "partial", "text_only"]
    source_path: str


_MATH_UNICODE = set("∑∫σμρ²³αβθλπδ∂≥≤≠∞")


def _looks_like_code_block(lines: list[str]) -> bool:
    """Heuristic: ≥80% of non-empty lines start with whitespace AND contain code-pattern chars."""
    non_empty = [ln for ln in lines if ln.strip()]
    if len(non_empty) < 3:
        return False
    code_like = sum(
        1 for ln in non_empty
        if (ln.startswith((" ", "\t")) and any(c in ln for c in "(){}[]=+-*/<>"))
    )
    return code_like / len(non_empty) >= 0.8


def _wrap_code_blocks(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        # Look ahead for runs of indented code-pattern lines
        run_end = i
        while run_end < len(lines) and (lines[run_end].startswith((" ", "\t")) or not lines[run_end].strip()):
            run_end += 1
        if run_end - i >= 3 and _looks_like_code_block(lines[i:run_end]):
            out.append("```")
            out.extend(lines[i:run_end])
            out.append("```")
            i = run_end
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


def _extract_pypdf(path: Path) -> tuple[str, int]:
    if PdfReader is None:
        raise RuntimeError("pypdf is required for PDF extraction")
    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages), len(reader.pages)


def _extract_pdfplumber(path: Path) -> tuple[str, int]:
    if pdfplumber is None:
        raise RuntimeError("pdfplumber is required for PDF fallback")
    with pdfplumber.open(str(path)) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
        return "\n\n".join(pages), len(pdf.pages)


def extract_from_file(path: Path) -> ExtractedPdf:
    """Extract text from a PDF, with pypdf primary and pdfplumber fallback."""
    if not path.exists():
        raise FileNotFoundError(str(path))

    text = ""
    page_count = 0
    quality: Literal["full", "partial", "text_only"] = "text_only"
    try:
        text, page_count = _extract_pypdf(path)
        if text.strip():
            quality = "full"
    except (PdfReadError, Exception):  # pragma: no cover - relies on system pdf
        text = ""

    # Heuristic: if pypdf returns < 100 chars/page on a 5+ page doc, try pdfplumber
    if page_count >= 5 and (len(text) / max(1, page_count)) < 100:
        try:
            text2, page_count2 = _extract_pdfplumber(path)
            if len(text2) > len(text):
                text = text2
                page_count = page_count2
                quality = "partial"
        except Exception:
            pass

    has_code = "def " in text or "class " in text or "import " in text
    has_math = any(ch in _MATH_UNICODE for ch in text)
    text = _wrap_code_blocks(text)

    return ExtractedPdf(
        text=text,
        page_count=page_count,
        has_code=has_code,
        has_math=has_math,
        extraction_quality=quality,
        source_path=str(path),
    )
