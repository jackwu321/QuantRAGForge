from __future__ import annotations

from datetime import date
from pathlib import Path

from kb_shared import parse_frontmatter
from wiki_schemas import SourceSummary, serialize_source_summary


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _read_article_frontmatter(article_dir: Path) -> dict:
    article_md = article_dir / "article.md"
    fm, _ = parse_frontmatter(article_md.read_text(encoding="utf-8"))
    return fm


def _top_idea_blocks(fm: dict, n: int = 3) -> list[str]:
    blocks = fm.get("idea_blocks", [])
    if isinstance(blocks, list):
        return [str(b) for b in blocks[:n]]
    if isinstance(blocks, str) and blocks.strip():
        return [blocks.strip()]
    return []


def write_source_summary(
    article_dir: Path,
    wiki_dir: Path,
    feeds_concepts: list[str],
    today: str | None = None,
) -> Path:
    """Generate wiki/sources/<basename>.md from article frontmatter (no LLM call)."""
    fm = _read_article_frontmatter(article_dir)
    today = today or date.today().isoformat()
    takeaway = (
        str(fm.get("core_hypothesis", "")).strip()
        or str(fm.get("tldr", "")).strip()
        or str(fm.get("summary", "")).strip()[:140]
    )
    why = ""
    bv = str(fm.get("brainstorm_value", "")).strip()
    if bv:
        why = f"Brainstorm value: {bv}."

    summary = SourceSummary(
        source_path=str(article_dir / "article.md"),
        title=str(fm.get("title", article_dir.name)),
        content_type=str(fm.get("content_type", "")),
        brainstorm_value=bv,
        feeds_concepts=feeds_concepts,
        ingested=str(fm.get("ingested", today)),
        last_compiled=today,
        takeaway=takeaway,
        top_idea_blocks=_top_idea_blocks(fm),
        why_in_kb=why,
    )
    out_path = wiki_dir / "sources" / f"{article_dir.name}.md"
    _atomic_write(out_path, serialize_source_summary(summary))
    return out_path
