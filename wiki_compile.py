from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from kb_shared import parse_frontmatter, ROOT, DEFAULT_SOURCE_DIRS
from wiki_schemas import SourceSummary, serialize_source_summary, ConceptArticle, parse_concept, serialize_concept
from wiki_compile_llm import (
    ConceptAssignment, ProposedConcept, RecompileResult,
    assign_concepts, recompile_concept,
)
from wiki_index import write_index
from wiki_seed import bootstrap_wiki
from wiki_state import (
    WikiState, load_wiki_state, save_wiki_state,
    is_source_changed, update_source_entry, update_concept_entry,
)

DEFAULT_SCHEMA_FILES = (
    "wiki-structure.md",
    "concept-schema.md",
    "source-schema.md",
    "operations.md",
)


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
    assign_failed: int = 0
    recompile_failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    lint_summary: str = ""
    lint_ok: bool = True

    def summary(self) -> str:
        parts = [
            f"{self.sources_written} sources, {self.concepts_recompiled} concepts recompiled",
            f"{self.concepts_proposed} proposed",
            f"{self.skipped} skipped",
        ]
        if self.assign_failed or self.recompile_failed:
            parts.append(f"{self.assign_failed} assignment failed, {self.recompile_failed} recompile failed")
        if self.errors:
            parts.append(f"{len(self.errors)} errors")
        return ", ".join(parts)


def _list_articles(kb_root: Path, source_dirs: tuple[str, ...]) -> list[Path]:
    """All article dirs under kb_root/raw/. `source_dirs` retained for API
    compatibility but ignored — frontmatter `status` is the source of truth and
    every article lives flat under `raw/`.
    """
    raw_dir = kb_root / "raw"
    if not raw_dir.exists():
        return []
    return [
        d for d in sorted(raw_dir.iterdir())
        if d.is_dir() and (d / "article.md").exists()
    ]


def load_schema_context(schema_dir: Path) -> str:
    """Return compact LLM-readable wiki organization rules."""
    chunks: list[str] = []
    for name in DEFAULT_SCHEMA_FILES:
        path = schema_dir / name
        if not path.exists():
            continue
        try:
            chunks.append(f"## {name}\n{path.read_text(encoding='utf-8').strip()}")
        except OSError:
            continue
    return "\n\n".join(chunks)


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


def _vprint(verbose: bool, message: str) -> None:
    if verbose:
        print(message, flush=True)


def _source_sort_key(path_str: str, affected_paths: set[str]) -> tuple[int, str]:
    return (0 if path_str in affected_paths else 1, path_str)


def compile_wiki(
    kb_root: Path = ROOT,
    mode: str = "incremental",
    dry_run: bool = False,
    source_dirs: tuple[str, ...] = DEFAULT_SOURCE_DIRS,
    max_sources_per_concept: int = 8,
    verbose: bool = False,
) -> CompileReport:
    """Compile or update the wiki from articles in {reviewed, high-value}/.

    Idempotency is content-hash based via wiki/state.json. Articles whose hashes
    are unchanged since the last compile are skipped entirely (no LLM calls).
    """
    if mode not in ("incremental", "rebuild"):
        raise ValueError(f"invalid mode: {mode!r}")

    wiki_dir = kb_root / "wiki"
    schema_dir = kb_root / "schema"
    state_path = wiki_dir / "state.json"
    bootstrap_wiki(wiki_dir)
    schema_text = load_schema_context(schema_dir)

    if mode == "rebuild":
        cdir = wiki_dir / "concepts"
        for md in cdir.glob("*.md"):
            md.unlink()
        bootstrap_wiki(wiki_dir)
        idx = wiki_dir / "INDEX.md"
        if idx.exists():
            idx.unlink()
        if state_path.exists():
            state_path.unlink()
        # Legacy cleanup: drop the assignment cache from older builds.
        legacy_cache = wiki_dir / "_assignment_cache.json"
        if legacy_cache.exists():
            legacy_cache.unlink()

    state = load_wiki_state(state_path)
    today = date.today().isoformat()
    report = CompileReport()
    articles = _list_articles(kb_root, source_dirs)

    affected_concept_slugs: set[str] = set()
    article_to_concepts: dict[Path, list[str]] = {}

    for article_index, article_dir in enumerate(articles, start=1):
        article_md = article_dir / "article.md"
        existing_summary = wiki_dir / "sources" / f"{article_dir.name}.md"
        _vprint(verbose, f"assign [{article_index}/{len(articles)}] {article_dir.name}")

        # Content-hash idempotency. Skip if we have a prior entry with matching
        # hash AND a source summary on disk. Orphans (feeds=[]) also count as
        # "already tried" — re-running assign_concepts on the same content will
        # produce the same empty result, so we shouldn't burn LLM calls on it.
        source_key = str(article_md)
        prior_entry = state.sources.get(source_key)
        if (
            mode == "incremental"
            and prior_entry is not None
            and existing_summary.exists()
            and not is_source_changed(state, article_md)
        ):
            report.skipped += 1
            article_to_concepts[article_dir] = list(prior_entry.feeds_concepts)
            continue

        index_text = _build_index_text(wiki_dir)
        try:
            article_md_text = article_md.read_text(encoding="utf-8")
            fm, _ = parse_frontmatter(article_md_text)
        except Exception as exc:
            report.errors.append(f"{article_dir}: read failed — {exc}")
            continue

        assign_kwargs = {"article_frontmatter": fm, "index_text": index_text}
        if schema_text:
            assign_kwargs["schema_text"] = schema_text
        assignment = assign_concepts(**assign_kwargs)
        report.concepts_assigned += 1
        if assignment.error:
            report.assign_failed += 1
            report.errors.append(f"{article_dir}: assign_concepts failed — {assignment.error}")

        for p in assignment.proposed_new_concepts:
            if not dry_run:
                _create_proposed_concept(wiki_dir, p, article_dir, today)
            report.concepts_proposed += 1

        feeds = list(assignment.existing_concepts) + [
            p.slug for p in assignment.proposed_new_concepts
        ]
        if not dry_run:
            write_source_summary(article_dir, wiki_dir, feeds_concepts=feeds, today=today)
            if not assignment.error:
                update_source_entry(state, article_md, feeds_concepts=feeds, last_seen=today)
                save_wiki_state(state, state_path)
        report.sources_written += 1

        if not assignment.error:
            for slug in assignment.existing_concepts:
                affected_concept_slugs.add(slug)
            article_to_concepts[article_dir] = feeds
        else:
            article_to_concepts[article_dir] = []

    if not dry_run:
        save_wiki_state(state, state_path)

    # Recompile each affected concept
    sorted_slugs = sorted(affected_concept_slugs)
    for concept_index, slug in enumerate(sorted_slugs, start=1):
        _vprint(verbose, f"recompile [{concept_index}/{len(sorted_slugs)}] {slug}")
        concept = _load_concept(wiki_dir, slug)
        if concept is None:
            continue
        sources_for_concept = [
            ad for ad, slugs in article_to_concepts.items() if slug in slugs
        ]
        existing_paths = set(concept.sources)
        for ad in sources_for_concept:
            existing_paths.add(str(ad / "article.md"))
        all_paths = sorted(existing_paths)
        affected_paths = {str(ad / "article.md") for ad in sources_for_concept}
        prompt_paths = sorted(all_paths, key=lambda p: _source_sort_key(p, affected_paths))
        if max_sources_per_concept > 0:
            prompt_paths = prompt_paths[:max_sources_per_concept]

        source_dicts = []
        for path_str in prompt_paths:
            ap = Path(path_str)
            if not ap.exists():
                continue
            try:
                fm, _ = parse_frontmatter(ap.read_text(encoding="utf-8"))
                fm["source_basename"] = ap.parent.name
                source_dicts.append(fm)
            except Exception:
                continue

        recompile_kwargs = {
            "concept_slug": slug,
            "concept_title": concept.title,
            "source_articles": source_dicts,
        }
        if schema_text:
            recompile_kwargs["schema_text"] = schema_text
        result = recompile_concept(**recompile_kwargs)
        if result.error:
            report.recompile_failed += 1
            report.errors.append(f"{slug}: recompile_concept failed — {result.error}")
            continue
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
            update_concept_entry(state, new_concept)
            save_wiki_state(state, state_path)

    if not dry_run:
        # Update state for proposed concepts so they have entries with their (low) confidence.
        for cmd_path in (wiki_dir / "concepts").glob("*.md"):
            try:
                c = parse_concept(cmd_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if c.status == "proposed" and c.slug not in state.concepts:
                update_concept_entry(state, c)
        save_wiki_state(state, state_path)
        write_index(wiki_dir)

        # Run lint after compile so the agent can decide whether to trust memory.
        try:
            from wiki_lint import lint_wiki
            lint = lint_wiki(kb_root)
            report.lint_summary = lint.summary()
            report.lint_ok = lint.ok_for_brainstorm()
        except Exception as exc:
            report.errors.append(f"lint failed: {exc}")

    return report
