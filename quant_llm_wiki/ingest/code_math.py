from __future__ import annotations

import re
from dataclasses import dataclass

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = None


@dataclass
class CodeBlock:
    language: str
    content: str


_LANG_CLASS_RE = re.compile(r"language-([a-zA-Z0-9_+-]+)")
_TEX_ANNOTATION_RE = re.compile(
    r'<annotation\s+encoding=["\']application/x-tex["\']>(.*?)</annotation>',
    re.DOTALL,
)
_LEGACY_MATHTEX_RE = re.compile(
    r'<script\s+type=["\']math/tex(?:; mode=display)?["\']>(.*?)</script>',
    re.DOTALL,
)
_INLINE_MATH_RE = re.compile(r"\$[^$\n]+?\$")
_DISPLAY_MATH_RE = re.compile(r"\$\$[^$]+?\$\$")
_PAREN_MATH_RE = re.compile(r"\\\((.*?)\\\)", re.DOTALL)
_BRACKET_MATH_RE = re.compile(r"\\\[(.*?)\\\]", re.DOTALL)


def extract_code_blocks(html: str) -> list[CodeBlock]:
    """Walk the source HTML for <pre><code> elements; return code blocks with language hint."""
    if BeautifulSoup is None:
        return []
    soup = BeautifulSoup(html, "html.parser")
    blocks: list[CodeBlock] = []
    for pre in soup.find_all("pre"):
        code = pre.find("code")
        target = code if code is not None else pre
        lang = ""
        classes = target.get("class") or []
        for cls in classes:
            m = _LANG_CLASS_RE.match(cls)
            if m:
                lang = m.group(1)
                break
        content = target.get_text("", strip=False).rstrip()
        if content:
            blocks.append(CodeBlock(language=lang, content=content))
    return blocks


def preserve_math_to_markdown(html: str) -> str:
    """Best-effort math preservation: rewrite KaTeX/MathJax annotations to $...$ / $$...$$

    Returns the HTML with math regions converted to markdown delimiters that Obsidian renders.
    `$...$` and `$$...$$` already in source are preserved as-is.
    """
    text = html
    text = _TEX_ANNOTATION_RE.sub(lambda m: f"${m.group(1).strip()}$", text)
    text = _LEGACY_MATHTEX_RE.sub(lambda m: f"${m.group(1).strip()}$", text)
    text = _PAREN_MATH_RE.sub(lambda m: f"${m.group(1).strip()}$", text)
    text = _BRACKET_MATH_RE.sub(lambda m: f"$${m.group(1).strip()}$$", text)
    return text


def detect_content_flags(html: str) -> dict[str, bool]:
    """Return {'has_code': bool, 'has_math': bool} for an HTML source."""
    has_code = bool(extract_code_blocks(html))
    has_math = bool(
        _TEX_ANNOTATION_RE.search(html)
        or _LEGACY_MATHTEX_RE.search(html)
        or _INLINE_MATH_RE.search(html)
        or _DISPLAY_MATH_RE.search(html)
        or _PAREN_MATH_RE.search(html)
        or _BRACKET_MATH_RE.search(html)
    )
    return {"has_code": has_code, "has_math": has_math}
