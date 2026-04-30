from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from datetime import datetime as _dt
import json
from pathlib import Path

from kb_shared import parse_frontmatter, ROOT, DEFAULT_SOURCE_DIRS
from wiki_schemas import SourceSummary, serialize_source_summary, ConceptArticle, parse_concept, serialize_concept
from wiki_compile_llm import (
    ConceptAssignment, ProposedConcept, RecompileResult,
    assign_concepts, recompile_concept,
)
from wiki_index import write_index
from wiki_seed import bootstrap_wiki


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


@dataclass
class CompileReport:
    sources_written: int = 0
    concepts_assigned: int = 0
    concepts_recompiled: int = 0
    concepts_proposed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [
            f"{self.sources_written} sources, {self.concepts_recompiled} concepts recompiled",
            f"{self.concepts_proposed} proposed",
            f"{self.skipped} skipped",
        ]
        if self.errors:
            parts.append(f"{len(self.errors)} errors")
        return ", ".join(parts)


def _list_articles(kb_root: Path, source_dirs: tuple[str, ...]) -> list[Path]:
    out: list[Path] = []
    for sd in source_dirs:
        d = kb_root / "articles" / sd
        if not d.exists():
            continue
        for article_dir in sorted(d.iterdir()):
            if article_dir.is_dir() and (article_dir / "article.md").exists():
                out.append(article_dir)
    return out


def _build_index_text(wiki_dir: Path) -> str:
    """Build a concise concept list suitable for `assign_concepts` LLM prompt."""
    cdir = wiki_dir / "concepts"
    if not cdir.exists():
        return ""
    lines = []
    for md in sorted(cdir.glob("*.md")):
        try:
            c = parse_concept(md.read_text(encoding="utf-8"))
        except Exception:
            continue
        if c.status != "stable":
            continue
        lines.append(f"- {c.slug} — {c.definition[:120]}")
    return "\n".join(lines)


def _load_concept(wiki_dir: Path, slug: str) -> ConceptArticle | None:
    p = wiki_dir / "concepts" / f"{slug}.md"
    if not p.exists():
        return None
    try:
        return parse_concept(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_concept(wiki_dir: Path, concept: ConceptArticle) -> None:
    p = wiki_dir / "concepts" / f"{concept.slug}.md"
    _atomic_write(p, serialize_concept(concept))


def _newer(article_dir: Path, concept: ConceptArticle | None) -> bool:
    """Return True if the article was modified after the concept was last compiled."""
    if concept is None or not concept.last_compiled:
        return True
    art_mtime = (article_dir / "article.md").stat().st_mtime
    try:
        compiled_ord = date.fromisoformat(concept.last_compiled).toordinal()
    except ValueError:
        return True
    art_day = _dt.fromtimestamp(art_mtime).date().toordinal()
    return art_day > compiled_ord


def _create_proposed_concept(
    wiki_dir: Path, p: ProposedConcept, article_dir: Path, today: str,
) -> None:
    if (wiki_dir / "concepts" / f"{p.slug}.md").exists():
        return
    concept = ConceptArticle(
        title=p.title,
        slug=p.slug,
        aliases=p.aliases,
        status="proposed",
        related_concepts=[],
        sources=[str(article_dir / "article.md")],
        content_types=[],
        last_compiled=today,
        compile_version=0,
        synthesis=p.draft_synthesis,
        definition=p.rationale,
        key_idea_blocks=[],
        variants=[],
        common_combinations=[],
        transfer_targets=[],
        failure_modes=[],
        open_questions=[],
        source_basenames=[article_dir.name],
    )
    _save_concept(wiki_dir, concept)


_ASSIGNMENT_CACHE_FILE = "_assignment_cache.json"


def _peek_existing_assignments(article_dir: Path, wiki_dir: Path) -> list[str]:
    """Look up the concepts an article was previously assigned to (from cache file)."""
    cache = wiki_dir / _ASSIGNMENT_CACHE_FILE
    if not cache.exists():
        return []
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data.get(str(article_dir), [])


def _record_assignment(article_dir: Path, wiki_dir: Path, slugs: list[str]) -> None:
    cache = wiki_dir / _ASSIGNMENT_CACHE_FILE
    try:
        data = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    except Exception:
        data = {}
    data[str(article_dir)] = slugs
    _atomic_write(cache, json.dumps(data, ensure_ascii=False, indent=2))


def compile_wiki(
    kb_root: Path = ROOT,
    mode: str = "incremental",
    dry_run: bool = False,
    source_dirs: tuple[str, ...] = DEFAULT_SOURCE_DIRS,
) -> CompileReport:
    """Compile or update the wiki from articles in {reviewed, high-value}/."""
    if mode not in ("incremental", "rebuild"):
        raise ValueError(f"invalid mode: {mode!r}")

    wiki_dir = kb_root / "wiki"
    bootstrap_wiki(wiki_dir)

    if mode == "rebuild":
        cdir = wiki_dir / "concepts"
        for md in cdir.glob("*.md"):
            md.unlink()
        bootstrap_wiki(wiki_dir)
        idx = wiki_dir / "INDEX.md"
        if idx.exists():
            idx.unlink()
        cache = wiki_dir / _ASSIGNMENT_CACHE_FILE
        if cache.exists():
            cache.unlink()

    today = date.today().isoformat()
    report = CompileReport()
    articles = _list_articles(kb_root, source_dirs)

    affected_concept_slugs: set[str] = set()
    article_to_concepts: dict[Path, list[str]] = {}

    for article_dir in articles:
        index_text = _build_index_text(wiki_dir)
        try:
            article_md_text = (article_dir / "article.md").read_text(encoding="utf-8")
            fm, _ = parse_frontmatter(article_md_text)
        except Exception as exc:
            report.errors.append(f"{article_dir}: read failed — {exc}")
            continue

        # Idempotency: skip if all concepts already up-to-date AND source summary exists
        existing_summary = wiki_dir / "sources" / f"{article_dir.name}.md"
        prior_slugs = _peek_existing_assignments(article_dir, wiki_dir)
        prior_concepts = [
            c for c in (_load_concept(wiki_dir, slug) for slug in prior_slugs)
            if c is not None
        ]
        if mode == "incremental" and existing_summary.exists() and prior_concepts and all(
            not _newer(article_dir, c) for c in prior_concepts
        ):
            report.skipped += 1
            article_to_concepts[article_dir] = [c.slug for c in prior_concepts]
            continue

        assignment = assign_concepts(article_frontmatter=fm, index_text=index_text)
        report.concepts_assigned += 1

        # Proposed new concepts
        for p in assignment.proposed_new_concepts:
            if not dry_run:
                _create_proposed_concept(wiki_dir, p, article_dir, today)
            report.concepts_proposed += 1

        # Source summary
        feeds = list(assignment.existing_concepts) + [p.slug for p in assignment.proposed_new_concepts]
        if not dry_run:
            write_source_summary(article_dir, wiki_dir, feeds_concepts=feeds, today=today)
            _record_assignment(article_dir, wiki_dir, feeds)
        report.sources_written += 1

        for slug in assignment.existing_concepts:
            affected_concept_slugs.add(slug)
        article_to_concepts[article_dir] = feeds

    # Recompile each affected concept
    for slug in sorted(affected_concept_slugs):
        concept = _load_concept(wiki_dir, slug)
        if concept is None:
            continue
        sources_for_concept = [
            ad for ad, slugs in article_to_concepts.items() if slug in slugs
        ]
        # Merge with existing sources from concept
        existing_paths = set(concept.sources)
        for ad in sources_for_concept:
            existing_paths.add(str(ad / "article.md"))
        all_paths = sorted(existing_paths)

        source_dicts = []
        for path_str in all_paths:
            ap = Path(path_str)
            if not ap.exists():
                continue
            try:
                fm, _ = parse_frontmatter(ap.read_text(encoding="utf-8"))
                fm["source_basename"] = ap.parent.name
                source_dicts.append(fm)
            except Exception:
                continue

        result = recompile_concept(
            concept_slug=slug,
            concept_title=concept.title,
            source_articles=source_dicts,
        )
        report.concepts_recompiled += 1

        new_concept = ConceptArticle(
            title=concept.title,
            slug=concept.slug,
            aliases=concept.aliases,
            status="stable",
            related_concepts=result.related_concepts,
            sources=all_paths,
            content_types=concept.content_types,
            last_compiled=today,
            compile_version=concept.compile_version + 1,
            synthesis=result.synthesis,
            definition=result.definition or concept.definition,
            key_idea_blocks=result.key_idea_blocks,
            variants=result.variants,
            common_combinations=result.common_combinations,
            transfer_targets=result.transfer_targets,
            failure_modes=result.failure_modes,
            open_questions=result.open_questions,
            source_basenames=[Path(p).parent.name for p in all_paths],
        )
        if not dry_run:
            _save_concept(wiki_dir, new_concept)

    if not dry_run:
        write_index(wiki_dir)

    return report
