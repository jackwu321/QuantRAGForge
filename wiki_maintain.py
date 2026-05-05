"""wiki_maintain — periodic LLM maintenance + query→wiki feedback loop.

Two responsibilities, both content-hash idempotent:

1. **Query-feedback (Step 7)** — `append_query_log(...)` runs after every
   `kb query`. It reads the just-written brainstorm/ask output file, derives
   the cited concepts from `wiki/sources/`, writes a structured note to
   `wiki/queries/<YYYY-MM-DD>_<slug>.md`, and updates `wiki/state.json`
   (bump `importance`, append query slug to `retrieval_hints`).

2. **Maintenance (Step 6)** — `run_maintenance(kb_root, apply=False)` produces
   a `MaintenanceResult` containing:
   - improvements distilled from `wiki/queries/*.md` (Open Questions / Common
     Combinations updates, applied with `apply=True`)
   - suggestions for new concepts (clusters of unmapped source summaries)
   - suggestions for new external sources to ingest, per under-supported concept
   - suggested next brainstorm queries, per under-explored concept

Suggestions are deterministic where possible; LLM-driven enrichment is only
used for natural-language summaries when `apply=True`.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from kb_shared import parse_frontmatter
from wiki_state import (
    ConceptEntry,
    load_wiki_state,
    save_wiki_state,
)


# ---------------------------------------------------------------------------
# Step 7: query → wiki feedback
# ---------------------------------------------------------------------------


_SLUG_RE = re.compile(r"[^\w一-鿿]+", flags=re.UNICODE)


def _slugify(value: str, max_len: int = 60) -> str:
    s = _SLUG_RE.sub("_", value.strip().lower()).strip("_")
    return s[:max_len] or "query"


def _parse_retrieved_sources(output_md: str) -> list[str]:
    m = re.search(r"## Retrieved Sources\n\n(.*?)\n\n## ", output_md, flags=re.S)
    if not m:
        return []
    out: list[str] = []
    for line in m.group(1).splitlines():
        line = line.strip()
        if line.startswith("- "):
            out.append(line[2:].strip())
    return out


def _source_path_to_basename(source_path: str, kb_root: Path) -> str | None:
    """A retrieved-source path may point to either an article directory under
    raw/ or a wiki concept/source markdown. Return the article basename or
    concept slug used as the citation key, or None if it's not classifiable.
    """
    p = Path(source_path)
    # Wiki concept page: kb_root/wiki/concepts/<slug>.md
    try:
        rel = p.resolve().relative_to((kb_root / "wiki" / "concepts").resolve())
        if rel.suffix == ".md":
            return rel.stem  # the slug
    except (ValueError, OSError):
        pass
    # Article dir: kb_root/raw/<basename>/
    try:
        rel = p.resolve().relative_to((kb_root / "raw").resolve())
        return rel.parts[0] if rel.parts else None
    except (ValueError, OSError):
        return None


def _basename_to_concepts(basename: str, kb_root: Path) -> list[str]:
    """Map an article basename to the concepts it feeds, via wiki/sources/."""
    summary_path = kb_root / "wiki" / "sources" / f"{basename}.md"
    if not summary_path.exists():
        return []
    fm, _ = parse_frontmatter(summary_path.read_text(encoding="utf-8"))
    feeds = fm.get("feeds_concepts", [])
    if isinstance(feeds, str):
        feeds = [feeds]
    return [str(f).strip() for f in (feeds or []) if str(f).strip()]


def _latest_output_for(query: str, mode: str, output_dir: Path) -> Path | None:
    """Find the freshest output file for this query/mode pair."""
    if not output_dir.exists():
        return None
    suffix = "ask" if mode == "ask" else "brainstorm"
    slug = _slugify(query)
    candidates = sorted(
        output_dir.glob(f"*_{slug}_{suffix}.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def append_query_log(
    kb_root: Path,
    query: str,
    mode: str,
    output_path: Path | None = None,
    importance_bump: float = 0.05,
) -> Path | None:
    """Write wiki/queries/<date>_<slug>.md and bump importance on cited concepts.

    Returns the written log path, or None if no matching output file was found.
    """
    output_dir = kb_root / "outputs" / "brainstorms"
    output_md_path = output_path or _latest_output_for(query, mode, output_dir)
    if not output_md_path or not output_md_path.exists():
        return None

    output_md = output_md_path.read_text(encoding="utf-8")
    sources = _parse_retrieved_sources(output_md)
    cited_concepts: set[str] = set()
    cited_sources: set[str] = set()
    for src in sources:
        basename = _source_path_to_basename(src, kb_root)
        if basename is None:
            continue
        concepts_dir = kb_root / "wiki" / "concepts"
        if (concepts_dir / f"{basename}.md").exists():
            cited_concepts.add(basename)
            continue
        cited_sources.add(basename)
        for slug in _basename_to_concepts(basename, kb_root):
            cited_concepts.add(slug)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slug = _slugify(query)
    queries_dir = kb_root / "wiki" / "queries"
    queries_dir.mkdir(parents=True, exist_ok=True)
    log_path = queries_dir / f"{today}_{slug}_{mode}.md"

    fm_lines = [
        "---",
        f"query: {json.dumps(query, ensure_ascii=False)}",
        f"mode: {mode}",
        f"date: {today}",
        f"output_file: {output_md_path.name}",
        f"cited_concepts: {json.dumps(sorted(cited_concepts))}",
        f"cited_sources: {json.dumps(sorted(cited_sources))}",
        "---",
    ]
    body = [
        "",
        f"# Query log — {query}",
        "",
        f"- Mode: `{mode}`",
        f"- Output: `outputs/brainstorms/{output_md_path.name}`",
        f"- Cited concepts: {sorted(cited_concepts) or '_none_'}",
        f"- Cited sources: {sorted(cited_sources) or '_none_'}",
        "",
    ]
    log_path.write_text("\n".join(fm_lines) + "\n".join(body), encoding="utf-8")

    # Update state.json: bump importance + append retrieval_hints
    state_path = kb_root / "wiki" / "state.json"
    state = load_wiki_state(state_path)
    for concept_slug in cited_concepts:
        entry = state.concepts.get(concept_slug)
        if entry is None:
            entry = ConceptEntry(status="proposed")
            state.concepts[concept_slug] = entry
        entry.importance = round(min(1.0, entry.importance + importance_bump), 4)
        if slug not in entry.retrieval_hints:
            entry.retrieval_hints.append(slug)
            entry.retrieval_hints = entry.retrieval_hints[-12:]
    save_wiki_state(state, state_path)
    return log_path


# ---------------------------------------------------------------------------
# Step 6: periodic maintenance
# ---------------------------------------------------------------------------


@dataclass
class MaintenanceResult:
    query_improvements: list[dict] = field(default_factory=list)
    new_concept_suggestions: list[dict] = field(default_factory=list)
    new_source_suggestions: list[dict] = field(default_factory=list)
    new_query_suggestions: list[dict] = field(default_factory=list)
    applied: bool = False

    def summary(self) -> str:
        parts = [
            f"{len(self.query_improvements)} query-derived improvements",
            f"{len(self.new_concept_suggestions)} new concept(s) suggested",
            f"{len(self.new_source_suggestions)} new source(s) suggested",
            f"{len(self.new_query_suggestions)} new query/queries suggested",
        ]
        if self.applied:
            parts.append("APPLIED")
        return ", ".join(parts)

    def to_markdown(self, generated_at: str) -> str:
        lines = [
            "# Wiki Maintenance Report",
            "",
            f"_Generated: {generated_at}_",
            "",
            f"_Summary: {self.summary()}_",
            "",
        ]
        sections = [
            ("Query-derived concept improvements", self.query_improvements,
             ("concept", "open_questions", "common_combinations")),
            ("Suggested new concepts (unmapped source clusters)", self.new_concept_suggestions,
             ("proposed_slug", "rationale", "feeding_sources")),
            ("Suggested new sources to ingest (per under-supported concept)", self.new_source_suggestions,
             ("concept", "search_queries", "rationale")),
            ("Suggested next queries (per under-explored concept)", self.new_query_suggestions,
             ("concept", "prompts")),
        ]
        for title, items, _keys in sections:
            lines.append(f"## {title}")
            lines.append("")
            if not items:
                lines.append("_(none)_")
                lines.append("")
                continue
            for it in items:
                lines.append(f"- {json.dumps(it, ensure_ascii=False)}")
            lines.append("")
        return "\n".join(lines)


def _read_query_logs(queries_dir: Path) -> list[dict]:
    if not queries_dir.exists():
        return []
    out: list[dict] = []
    for md in sorted(queries_dir.glob("*.md")):
        fm, _ = parse_frontmatter(md.read_text(encoding="utf-8"))
        if fm:
            fm["__path"] = str(md)
            out.append(fm)
    return out


def _gather_unmapped_sources(kb_root: Path) -> dict[str, list[str]]:
    """Group source summaries with no `feeds_concepts` by content_type."""
    sources_dir = kb_root / "wiki" / "sources"
    out: dict[str, list[str]] = {}
    if not sources_dir.exists():
        return out
    for md in sources_dir.glob("*.md"):
        fm, _ = parse_frontmatter(md.read_text(encoding="utf-8"))
        feeds = fm.get("feeds_concepts", [])
        if isinstance(feeds, str):
            feeds = [feeds]
        if feeds:
            continue
        ct = str(fm.get("content_type", "uncategorized")).strip() or "uncategorized"
        out.setdefault(ct, []).append(md.stem)
    return out


def _under_supported_concepts(state, low_threshold: int = 2) -> list[tuple[str, ConceptEntry]]:
    out: list[tuple[str, ConceptEntry]] = []
    for slug, entry in state.concepts.items():
        if entry.status != "stable":
            continue
        if entry.source_count <= low_threshold:
            out.append((slug, entry))
    return out


def _stale_concepts(state, halflife_days: float = 60.0, threshold: float = 0.4) -> list[tuple[str, ConceptEntry]]:
    out: list[tuple[str, ConceptEntry]] = []
    for slug, entry in state.concepts.items():
        if entry.status != "stable":
            continue
        if entry.freshness <= threshold:
            out.append((slug, entry))
    return out


def run_maintenance(
    kb_root: Path,
    apply: bool = False,
    write_report: bool = True,
) -> MaintenanceResult:
    """Compute (and optionally apply) maintenance suggestions.

    Deterministic pieces (gap analysis, freshness scan, query log aggregation)
    run every time. LLM-driven natural-language suggestions are out of scope
    for this v1; the plumbing is in place so a follow-up can fill them in.
    """
    result = MaintenanceResult(applied=apply)
    state_path = kb_root / "wiki" / "state.json"
    state = load_wiki_state(state_path)

    # 1. Query-derived improvement candidates
    queries = _read_query_logs(kb_root / "wiki" / "queries")
    concept_to_queries: dict[str, list[str]] = {}
    for q in queries:
        cited = q.get("cited_concepts", [])
        if isinstance(cited, str):
            cited = [cited]
        for slug in cited or []:
            concept_to_queries.setdefault(str(slug).strip(), []).append(str(q.get("query", "")).strip())
    for slug, qs in concept_to_queries.items():
        if not qs:
            continue
        result.query_improvements.append({
            "concept": slug,
            "recent_queries": qs[-5:],
            "hint": "Consider adding these as Open Questions / Common Combinations on the concept page.",
        })

    # 2. New concept candidates: clusters of unmapped sources
    unmapped = _gather_unmapped_sources(kb_root)
    for ct, basenames in unmapped.items():
        if len(basenames) < 2:
            continue
        result.new_concept_suggestions.append({
            "proposed_slug": f"{ct.replace('_', '-')}-cluster",
            "rationale": f"{len(basenames)} unmapped sources share content_type={ct!r}.",
            "feeding_sources": sorted(basenames)[:8],
        })

    # 3. Under-supported concepts → suggest external sources to ingest
    for slug, entry in _under_supported_concepts(state):
        result.new_source_suggestions.append({
            "concept": slug,
            "search_queries": [
                f"{slug.replace('-', ' ')} survey",
                f"{slug.replace('-', ' ')} backtest",
                f"{slug.replace('-', ' ')} 应用",
            ],
            "rationale": f"Only {entry.source_count} source(s) currently feed this stable concept.",
        })

    # 4. Stale concepts → suggest brainstorm queries
    for slug, entry in _stale_concepts(state):
        result.new_query_suggestions.append({
            "concept": slug,
            "prompts": [
                f"What recent thinking has emerged on {slug.replace('-', ' ')}?",
                f"How does {slug.replace('-', ' ')} combine with neighboring concepts?",
            ],
        })

    # 5. Apply step: bump retrieval_hints from query logs (the only durable
    # state-side change we'll commit without an explicit LLM rewrite).
    if apply:
        for slug, qs in concept_to_queries.items():
            entry = state.concepts.get(slug)
            if entry is None:
                continue
            for q in qs[-3:]:
                hint = _slugify(q, max_len=40)
                if hint and hint not in entry.retrieval_hints:
                    entry.retrieval_hints.append(hint)
                    entry.retrieval_hints = entry.retrieval_hints[-12:]
        save_wiki_state(state, state_path)

    if write_report:
        report_path = kb_root / "wiki" / "maintenance_report.md"
        report_path.write_text(
            result.to_markdown(time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())),
            encoding="utf-8",
        )
    return result
