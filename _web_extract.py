from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

try:
    import trafilatura
except ImportError:  # pragma: no cover
    trafilatura = None

try:
    from readability import Document as ReadabilityDocument
except ImportError:  # pragma: no cover
    ReadabilityDocument = None

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

from _code_math import detect_content_flags, extract_code_blocks, preserve_math_to_markdown


_PAYWALL_KEYWORDS = ("subscribe to read", "please subscribe", "paywall", "subscribe to continue")


@dataclass
class ExtractedArticle:
    title: str
    text: str
    markdown: str
    has_code: bool
    has_math: bool
    paywalled: bool
    extraction_quality: Literal["full", "partial", "text_only"]
    source_url: str


def _fetch_url_text(url: str) -> str:
    if requests is None:
        raise RuntimeError("requests is required for URL fetching")
    response = requests.get(url, timeout=(10, 30), headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    return response.text


def _detect_paywall(text: str) -> bool:
    lowered = text.lower()
    if not lowered.strip():
        return False
    if len(lowered) < 400 and any(kw in lowered for kw in _PAYWALL_KEYWORDS):
        return True
    return any(kw in lowered for kw in _PAYWALL_KEYWORDS)


def _extract_title(html: str) -> str:
    if trafilatura is not None:
        meta = trafilatura.extract_metadata(html)
        if meta and meta.title:
            return meta.title.strip()
    if ReadabilityDocument is not None:
        try:
            return ReadabilityDocument(html).short_title().strip()
        except Exception:
            pass
    return ""


def _markdown_with_code_and_math(html: str, base_text: str) -> str:
    blocks = extract_code_blocks(html)
    text_with_math = preserve_math_to_markdown(base_text)
    if not blocks:
        return text_with_math
    parts = [text_with_math, ""]
    parts.append("## Code Blocks")
    parts.append("")
    for block in blocks:
        fence_lang = block.language if block.language else ""
        parts.append(f"```{fence_lang}")
        parts.append(block.content)
        parts.append("```")
        parts.append("")
    return "\n".join(parts)


def extract_from_html(html: str, source_url: str = "") -> ExtractedArticle:
    """Extract an article from raw HTML using trafilatura -> readability fallback."""
    if not html.strip():
        return ExtractedArticle(
            title="",
            text="",
            markdown="",
            has_code=False,
            has_math=False,
            paywalled=False,
            extraction_quality="text_only",
            source_url=source_url,
        )

    title = _extract_title(html)
    text = ""
    quality: Literal["full", "partial", "text_only"] = "text_only"

    if trafilatura is not None:
        try:
            text = trafilatura.extract(
                html,
                include_formatting=True,
                include_links=True,
                favor_recall=True,
            ) or ""
            if text.strip():
                quality = "full"
        except Exception:
            text = ""

    if not text.strip() and ReadabilityDocument is not None:
        try:
            doc = ReadabilityDocument(html)
            text = doc.summary()
            if text.strip():
                quality = "partial"
        except Exception:
            text = ""

    flags = detect_content_flags(html)
    markdown = _markdown_with_code_and_math(html, text)
    paywalled = _detect_paywall(text)
    return ExtractedArticle(
        title=title,
        text=text,
        markdown=markdown,
        has_code=flags["has_code"],
        has_math=flags["has_math"],
        paywalled=paywalled,
        extraction_quality=quality,
        source_url=source_url,
    )


def extract_from_url(url: str) -> ExtractedArticle:
    html = _fetch_url_text(url)
    return extract_from_html(html, source_url=url)
