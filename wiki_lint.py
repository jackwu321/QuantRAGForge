"""Wiki health checks. Agent-facing operational telemetry.

Replaces routine human review of the wiki: the agent calls audit_wiki before
trusting compiled memory for brainstorm. The lint report is JSON for machine
use plus a human-readable summary.

Severity model:
- info     — observation, no action needed
- warning  — drift signal, agent should consider remediation
- error    — blocks brainstorm; pure-vector fallback is safer

Lint rules (order matters — short-circuit logic in ok_for_brainstorm):
1. unsupported_bullets — bullets without [anchor] in structured sections
2. unsupported_claims — stable concept with empty sources but populated synthesis
3. stale_concepts — recorded source hash differs from disk
4. orphan_concepts — stable concept with zero sources (seeds excluded)
5. orphan_sources — source summary feeds no stable concept
6. duplicate_aliases — two concepts share an alias / retrieval hint
7. oversized_concepts — concept page too large for default retrieval budget
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from quant_llm_wiki.shared import ROOT, WIKI_DIR, WIKI_LINT_PATH, WIKI_STATE_PATH
from wiki_schemas import (
    ConceptArticle,
    bullet_sources,
    parse_concept,
    parse_source_summary,
)
from wiki_state import load_wiki_state, source_content_hash


SEVERITY = Literal["info", "warning", "error"]
DEFAULT_OVERSIZED_BYTES = 8192  # ≈ 1500-2000 tokens; conservative budget

VALID_BRAINSTORM_VALUE = {"low", "medium", "high", ""}
VALID_CONCEPT_STATUS = {"stable", "proposed", "deprecated"}
REQUIRED_CONCEPT_SECTIONS = (
    "Synthesis",
    "Definition",
    "Key Idea Blocks",
    "Variants & Implementations",
    "Common Combinations",
    "Transfer Targets",
    "Failure Modes",
    "Open Questions",
    "Sources",
)
REQUIRED_SOURCE_SECTIONS = (
    "One-line takeaway",
    "Idea Blocks",
    "Why it's in the KB",
    "Feeds concepts",
)


@dataclass
class WikiLintIssue:
    severity: str
    kind: str
    path: str
    message: str
    suggested_action: str = ""


@dataclass
class WikiLintReport:
    issues: list[WikiLintIssue] = field(default_factory=list)

    def ok_for_brainstorm(self) -> bool:
        """Brainstorm is safe iff no error-severity issues are present."""
        return not any(i.severity == "error" for i in self.issues)

    def by_severity(self) -> dict[str, list[WikiLintIssue]]:
        out: dict[str, list[WikiLintIssue]] = defaultdict(list)
        for issue in self.issues:
            out[issue.severity].append(issue)
        return out

    def summary(self) -> str:
        if not self.issues:
            return "Wiki health: ok (0 issues)"
        bs = self.by_severity()
        lines = [
            f"Wiki health: {len(self.issues)} issue(s) — "
            f"{len(bs.get('error', []))} error, "
            f"{len(bs.get('warning', []))} warning, "
            f"{len(bs.get('info', []))} info"
        ]
        for sev in ("error", "warning", "info"):
            for issue in bs.get(sev, [])[:10]:  # cap per-severity output
                lines.append(f"  [{sev}] {issue.kind} ({issue.path}): {issue.message}")
        if not self.ok_for_brainstorm():
            lines.append("BRAINSTORM SHOULD FALL BACK TO ARTICLE-ONLY RETRIEVAL.")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"issues": [asdict(i) for i in self.issues]}


# ---------------------------------------------------------------------------
# Individual rules
# ---------------------------------------------------------------------------


def _structured_sections(c: ConceptArticle) -> dict[str, list[str]]:
    return {
        "key_idea_blocks": c.key_idea_blocks,
        "variants": c.variants,
        "common_combinations": c.common_combinations,
        "transfer_targets": c.transfer_targets,
        "failure_modes": c.failure_modes,
        "open_questions": c.open_questions,
    }


def _check_unsupported_bullets(c: ConceptArticle, path: Path) -> list[WikiLintIssue]:
    issues: list[WikiLintIssue] = []
    if c.status != "stable":
        return issues  # proposed/deprecated are not used by brainstorm; skip
    for section_name, bullets in _structured_sections(c).items():
        for bullet in bullets:
            if not bullet_sources(bullet):
                issues.append(WikiLintIssue(
                    severity="warning",
                    kind="unsupported_bullets",
                    path=str(path),
                    message=f"{section_name} bullet without [source] anchor: {bullet[:80]}",
                    suggested_action="Recompile concept; ensure recompile_concept prompt produces anchored bullets.",
                ))
    return issues


def _check_unsupported_claims(c: ConceptArticle, path: Path) -> list[WikiLintIssue]:
    if c.status != "stable":
        return []
    synthesis = c.synthesis.strip()
    is_placeholder = synthesis.startswith("_pending") or not synthesis
    has_body_content = not is_placeholder
    if has_body_content and not c.sources:
        return [WikiLintIssue(
            severity="error",
            kind="unsupported_claims",
            path=str(path),
            message="Stable concept has populated synthesis but no sources. Prevents traceability.",
            suggested_action="Recompile from at least one source, or set status=proposed.",
        )]
    return []


def _check_orphan_concept(c: ConceptArticle, path: Path) -> list[WikiLintIssue]:
    if c.status != "stable":
        return []
    if not c.sources:
        # Seed stub before any ingest — not an issue, just info
        if c.compile_version == 0:
            return [WikiLintIssue(
                severity="info",
                kind="seed_stub",
                path=str(path),
                message="Seed concept has no sources yet; awaiting ingest.",
            )]
        return [WikiLintIssue(
            severity="warning",
            kind="orphan_concepts",
            path=str(path),
            message="Stable concept lost all sources after recompile.",
            suggested_action="Either deprecate, or merge with another concept.",
        )]
    return []


def _check_oversized(c: ConceptArticle, path: Path, byte_limit: int) -> list[WikiLintIssue]:
    if not path.exists():
        return []
    size = path.stat().st_size
    if size > byte_limit:
        return [WikiLintIssue(
            severity="warning",
            kind="oversized_concepts",
            path=str(path),
            message=f"Concept file is {size} bytes (>{byte_limit} budget). Increases retrieval token cost.",
            suggested_action="Split into sub-concepts or trim variants/idea-blocks.",
        )]
    return []


def _check_stale_sources(state, kb_root: Path) -> list[WikiLintIssue]:
    issues: list[WikiLintIssue] = []
    for path_str, entry in state.sources.items():
        article_path = Path(path_str)
        if not article_path.exists():
            issues.append(WikiLintIssue(
                severity="warning",
                kind="orphan_sources",
                path=path_str,
                message="Source recorded in state.json no longer exists on disk.",
                suggested_action="Run compile_wiki --rebuild to clean up references.",
            ))
            continue
        try:
            actual_hash = source_content_hash(article_path)
        except OSError:
            continue
        if actual_hash != entry.content_hash:
            issues.append(WikiLintIssue(
                severity="warning",
                kind="stale_concepts",
                path=path_str,
                message=f"Source content changed since last compile (feeds: {entry.feeds_concepts}).",
                suggested_action="Run compile_wiki to refresh affected concepts.",
            ))
    return issues


def _check_duplicate_aliases(concepts: list[ConceptArticle]) -> list[WikiLintIssue]:
    alias_to_slugs: dict[str, list[str]] = defaultdict(list)
    for c in concepts:
        if c.status != "stable":
            continue
        for alias in c.aliases:
            alias_to_slugs[alias.lower().strip()].append(c.slug)
    issues: list[WikiLintIssue] = []
    for alias, slugs in alias_to_slugs.items():
        if len(set(slugs)) > 1:
            issues.append(WikiLintIssue(
                severity="warning",
                kind="duplicate_aliases",
                path=",".join(sorted(set(slugs))),
                message=f"Alias '{alias}' is shared by multiple concepts: {sorted(set(slugs))}.",
                suggested_action="Merge concepts or remove the duplicate alias from one.",
            ))
    return issues


def _check_concept_sections(c: ConceptArticle, raw_text: str, path: Path) -> list[WikiLintIssue]:
    """Schema-compliance: every concept page must contain the required section headers.

    Seed stubs (compile_version=0) are exempt from "empty synthesis/definition" checks —
    they're awaiting ingest. The existing seed_stub info-issue covers that case.
    """
    if c.status == "deprecated":
        return []
    issues: list[WikiLintIssue] = []
    for section in REQUIRED_CONCEPT_SECTIONS:
        # Anchored: a real section header begins a line and is followed by newline.
        marker = f"\n## {section}\n"
        if marker not in raw_text and not raw_text.startswith(f"## {section}\n"):
            issues.append(WikiLintIssue(
                severity="warning",
                kind="schema_missing_section",
                path=str(path),
                message=f"Required concept section '{section}' is missing.",
                suggested_action="Recompile the concept (kb compile or kb lint --fix).",
            ))
    if c.status == "stable" and c.compile_version > 0:
        if not c.synthesis.strip() or c.synthesis.strip().startswith("_pending"):
            issues.append(WikiLintIssue(
                severity="warning",
                kind="schema_empty_synthesis",
                path=str(path),
                message="Stable concept has empty Synthesis section.",
                suggested_action="Recompile the concept; synthesis is the load-bearing wiki-first answer.",
            ))
        if not c.definition.strip() or c.definition.strip().startswith("_pending"):
            issues.append(WikiLintIssue(
                severity="warning",
                kind="schema_empty_definition",
                path=str(path),
                message="Stable concept has empty Definition section.",
                suggested_action="Recompile the concept.",
            ))
    return issues


def _check_source_summary_schema(summary, raw_text: str, path: Path) -> list[WikiLintIssue]:
    """Schema-compliance: source summaries must have valid enums and the required sections."""
    issues: list[WikiLintIssue] = []
    if summary.brainstorm_value and summary.brainstorm_value not in VALID_BRAINSTORM_VALUE:
        issues.append(WikiLintIssue(
            severity="warning",
            kind="schema_invalid_enum",
            path=str(path),
            message=(
                f"brainstorm_value={summary.brainstorm_value!r} is not in "
                f"{sorted(v for v in VALID_BRAINSTORM_VALUE if v)}."
            ),
            suggested_action="Re-enrich the source article or correct the field manually.",
        ))
    for section in REQUIRED_SOURCE_SECTIONS:
        # Source summaries use bold-prefix markers, not ## headers.
        if f"**{section}" not in raw_text:
            issues.append(WikiLintIssue(
                severity="info",
                kind="schema_missing_section",
                path=str(path),
                message=f"Source summary section '{section}' marker is missing.",
                suggested_action="Re-run compile_wiki to regenerate the summary.",
            ))
    return issues


def _check_orphan_sources(wiki_dir: Path, concepts: list[ConceptArticle]) -> list[WikiLintIssue]:
    sources_dir = wiki_dir / "sources"
    if not sources_dir.exists():
        return []
    stable_slugs = {c.slug for c in concepts if c.status == "stable"}
    issues: list[WikiLintIssue] = []
    for md in sources_dir.glob("*.md"):
        try:
            summary = parse_source_summary(md.read_text(encoding="utf-8"))
        except Exception:
            continue
        feeds = set(summary.feeds_concepts)
        if not feeds & stable_slugs:
            issues.append(WikiLintIssue(
                severity="info",
                kind="orphan_sources",
                path=str(md),
                message=f"Source summary feeds no stable concept (feeds={summary.feeds_concepts}).",
                suggested_action="Approve a proposed concept this article feeds, or accept as informational source.",
            ))
    return issues


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def lint_wiki(
    kb_root: Path = ROOT,
    *,
    oversized_byte_limit: int = DEFAULT_OVERSIZED_BYTES,
) -> WikiLintReport:
    """Run all lint checks against the wiki at kb_root/wiki/. Returns a report.

    Writes wiki/lint_report.json as a side effect (for the agent's audit_wiki tool).
    """
    wiki_dir = kb_root / "wiki"
    state_path = kb_root / "wiki" / "state.json"
    lint_path = kb_root / "wiki" / "lint_report.json"

    report = WikiLintReport()
    if not wiki_dir.exists():
        return report

    concepts: list[ConceptArticle] = []
    cdir = wiki_dir / "concepts"
    if cdir.exists():
        for md in sorted(cdir.glob("*.md")):
            raw_text = md.read_text(encoding="utf-8")
            try:
                concept = parse_concept(raw_text)
            except Exception as exc:
                report.issues.append(WikiLintIssue(
                    severity="error",
                    kind="malformed_concept",
                    path=str(md),
                    message=f"Failed to parse: {exc}",
                    suggested_action="Inspect the file or rerun compile_wiki --rebuild.",
                ))
                continue
            concepts.append(concept)
            report.issues.extend(_check_unsupported_bullets(concept, md))
            report.issues.extend(_check_unsupported_claims(concept, md))
            report.issues.extend(_check_orphan_concept(concept, md))
            report.issues.extend(_check_oversized(concept, md, oversized_byte_limit))
            report.issues.extend(_check_concept_sections(concept, raw_text, md))

    sources_dir = wiki_dir / "sources"
    if sources_dir.exists():
        for md in sorted(sources_dir.glob("*.md")):
            raw_text = md.read_text(encoding="utf-8")
            try:
                summary = parse_source_summary(raw_text)
            except Exception as exc:
                report.issues.append(WikiLintIssue(
                    severity="warning",
                    kind="malformed_source_summary",
                    path=str(md),
                    message=f"Failed to parse: {exc}",
                    suggested_action="Re-run compile_wiki to regenerate.",
                ))
                continue
            report.issues.extend(_check_source_summary_schema(summary, raw_text, md))

    state = load_wiki_state(state_path)
    report.issues.extend(_check_stale_sources(state, kb_root))
    report.issues.extend(_check_duplicate_aliases(concepts))
    report.issues.extend(_check_orphan_sources(wiki_dir, concepts))

    # Persist for audit_wiki and external introspection
    try:
        lint_path.parent.mkdir(parents=True, exist_ok=True)
        lint_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass

    return report


# ---------------------------------------------------------------------------
# Auto-fix — LLM-driven repair pass for schema-noncompliant concepts
# ---------------------------------------------------------------------------


_FIXABLE_KINDS = {
    "unsupported_bullets",
    "unsupported_claims",
    "schema_missing_section",
    "schema_empty_synthesis",
    "schema_empty_definition",
}


def auto_fix(kb_root: Path, report: WikiLintReport) -> int:
    """Attempt to auto-repair schema-noncompliant concepts by recompiling them.

    Recompile uses schema/-injected prompts (see wiki_compile_llm), so the LLM
    is told the required sections and source-anchor invariant. Returns the
    number of concept slugs the fix pass attempted to repair.
    """
    offenders: dict[str, Path] = {}
    for issue in report.issues:
        if issue.kind not in _FIXABLE_KINDS:
            continue
        path = Path(issue.path)
        if path.suffix != ".md" or path.parent.name != "concepts":
            continue
        offenders[path.stem] = path
    if not offenders:
        return 0

    from wiki_compile import load_schema_context, _save_concept
    from wiki_compile_llm import recompile_concept
    from wiki_state import load_wiki_state, save_wiki_state, update_concept_entry
    from wiki_schemas import ConceptArticle, parse_concept
    from quant_llm_wiki.shared import parse_frontmatter

    schema_text = load_schema_context(kb_root / "schema")
    state = load_wiki_state(kb_root / "wiki" / "state.json")
    raw_dir = kb_root / "raw"

    fixed = 0
    for slug, concept_path in offenders.items():
        try:
            concept = parse_concept(concept_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        # Gather source articles whose recorded feeds_concepts include this slug.
        source_dicts: list[dict] = []
        for path_str, entry in state.sources.items():
            if slug not in entry.feeds_concepts:
                continue
            article_md = Path(path_str)
            if not article_md.exists():
                continue
            fm, _ = parse_frontmatter(article_md.read_text(encoding="utf-8"))
            source_dicts.append({**fm, "_basename": article_md.parent.name})
        if not source_dicts:
            continue

        kwargs = {
            "concept_slug": slug,
            "concept_title": concept.title,
            "source_articles": source_dicts,
        }
        if schema_text:
            kwargs["schema_text"] = schema_text
        try:
            result = recompile_concept(**kwargs)
        except Exception:
            continue
        if result.error:
            continue

        new_concept = ConceptArticle(
            title=concept.title,
            slug=concept.slug,
            aliases=concept.aliases,
            status=concept.status,
            related_concepts=result.related_concepts or concept.related_concepts,
            sources=concept.sources,
            content_types=concept.content_types,
            last_compiled=concept.last_compiled,
            compile_version=concept.compile_version + 1,
            synthesis=result.synthesis,
            definition=result.definition,
            key_idea_blocks=result.key_idea_blocks,
            variants=result.variants,
            common_combinations=result.common_combinations,
            transfer_targets=result.transfer_targets,
            failure_modes=result.failure_modes,
            open_questions=result.open_questions,
            source_basenames=concept.source_basenames,
        )
        _save_concept(kb_root / "wiki", new_concept)
        update_concept_entry(state, new_concept)
        fixed += 1

    save_wiki_state(state, kb_root / "wiki" / "state.json")
    return fixed
