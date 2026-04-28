from __future__ import annotations

"""Schemas for the LLM-maintained wiki layer.

Note on `ConceptArticle.sources` vs `source_basenames`:
- `sources` holds full paths to article.md files (e.g. `articles/reviewed/<dir>/article.md`).
  It is serialized to the frontmatter as a YAML block-list for human readability.
- `source_basenames` holds article directory basenames (e.g. `2026-03-22_华泰_趋势`),
  rendered as `[[basename]]` Obsidian wikilinks under the `## Sources` body section.

`source_basenames` is the **authoritative round-trip field**. The frontmatter `sources:`
block-list does NOT round-trip through `parse_concept` — `kb_shared.parse_frontmatter`
only handles single-line `key: value` pairs. Callers that need full source paths
must keep them in the `ConceptArticle` instance they construct (e.g. compile_wiki
re-derives them from the corresponding article.md mtimes); they cannot be recovered
from the on-disk concept file alone.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from kb_shared import parse_frontmatter

CONCEPT_STATUS = ("stable", "proposed", "deprecated")
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


@dataclass
class ConceptArticle:
    title: str
    slug: str
    aliases: list[str]
    status: Literal["stable", "proposed", "deprecated"]
    related_concepts: list[str]
    sources: list[str]
    content_types: list[str]
    last_compiled: str
    compile_version: int
    synthesis: str
    definition: str
    key_idea_blocks: list[str]
    variants: list[str]
    common_combinations: list[str]
    transfer_targets: list[str]
    failure_modes: list[str]
    open_questions: list[str]
    source_basenames: list[str]

    def __post_init__(self) -> None:
        if self.status not in CONCEPT_STATUS:
            raise ValueError(f"invalid status: {self.status!r}; must be one of {CONCEPT_STATUS}")
        if not SLUG_RE.match(self.slug):
            raise ValueError(f"invalid slug: {self.slug!r}; must be kebab-case ASCII")


def _yaml_list(values: list[str]) -> str:
    if not values:
        return "[]"
    return "[" + ", ".join(values) + "]"


def _md_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- _none_"


def serialize_concept(c: ConceptArticle) -> str:
    fm_lines = [
        "---",
        f"title: {c.title}",
        f"slug: {c.slug}",
        f"aliases: {_yaml_list(c.aliases)}",
        f"status: {c.status}",
        f"related_concepts: {_yaml_list(c.related_concepts)}",
    ]
    if c.sources:
        fm_lines.append("sources:")
        fm_lines.extend(f"  - {s}" for s in c.sources)
    else:
        fm_lines.append("sources: []")
    fm_lines.extend([
        f"content_types: {_yaml_list(c.content_types)}",
        f"last_compiled: {c.last_compiled}",
        f"compile_version: {c.compile_version}",
        "---",
    ])

    body = [
        f"# {c.title}",
        "",
        "## Synthesis",
        "",
        c.synthesis or "_pending_",
        "",
        "## Definition",
        "",
        c.definition or "_pending_",
        "",
        "## Key Idea Blocks",
        "",
        _md_list(c.key_idea_blocks),
        "",
        "## Variants & Implementations",
        "",
        _md_list(c.variants),
        "",
        "## Common Combinations",
        "",
        _md_list(c.common_combinations),
        "",
        "## Transfer Targets",
        "",
        _md_list(c.transfer_targets),
        "",
        "## Failure Modes",
        "",
        _md_list(c.failure_modes),
        "",
        "## Open Questions",
        "",
        _md_list(c.open_questions),
        "",
        "## Sources",
        "",
        _md_list([f"[[{b}]]" for b in c.source_basenames]),
        "",
    ]
    return "\n".join(fm_lines) + "\n\n" + "\n".join(body)


def _parse_yaml_list(value: str) -> list[str]:
    value = value.strip()
    if value in ("", "[]"):
        return []
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1]
        return [v.strip() for v in inner.split(",") if v.strip()]
    return [value]


def parse_concept(text: str) -> ConceptArticle:
    """Parse a concept article markdown file back to a ConceptArticle.

    The on-disk YAML `sources:` block-list is NOT round-tripped — `source_basenames`
    (from `## Sources` wikilinks) is the authoritative field. See module docstring.
    """
    fm, body = parse_frontmatter(text)
    sources = fm.get("sources", [])
    if isinstance(sources, str):
        sources = _parse_yaml_list(sources)

    def _section(name: str) -> str:
        m = re.search(rf"## {re.escape(name)}\n\n(.*?)(?=\n## |\Z)", body, flags=re.S)
        return m.group(1).strip() if m else ""

    def _section_list(name: str) -> list[str]:
        section = _section(name)
        if not section or section == "_none_":
            return []
        items = []
        for line in section.splitlines():
            line = line.strip()
            if line.startswith("- ") and line[2:].strip() != "_none_":
                items.append(line[2:].strip())
        return items

    src_basenames = []
    for item in _section_list("Sources"):
        m = re.match(r"\[\[(.+?)\]\]", item)
        if m:
            src_basenames.append(m.group(1))

    return ConceptArticle(
        title=str(fm.get("title", "")),
        slug=str(fm.get("slug", "")),
        aliases=fm.get("aliases", []) if isinstance(fm.get("aliases"), list) else _parse_yaml_list(str(fm.get("aliases", ""))),
        status=str(fm.get("status", "proposed")),
        related_concepts=fm.get("related_concepts", []) if isinstance(fm.get("related_concepts"), list) else _parse_yaml_list(str(fm.get("related_concepts", ""))),
        sources=sources if isinstance(sources, list) else [],
        content_types=fm.get("content_types", []) if isinstance(fm.get("content_types"), list) else _parse_yaml_list(str(fm.get("content_types", ""))),
        last_compiled=str(fm.get("last_compiled", "")),
        compile_version=int(fm.get("compile_version", 0) or 0),
        synthesis=_section("Synthesis"),
        definition=_section("Definition"),
        key_idea_blocks=_section_list("Key Idea Blocks"),
        variants=_section_list("Variants & Implementations"),
        common_combinations=_section_list("Common Combinations"),
        transfer_targets=_section_list("Transfer Targets"),
        failure_modes=_section_list("Failure Modes"),
        open_questions=_section_list("Open Questions"),
        source_basenames=src_basenames,
    )


@dataclass
class SourceSummary:
    source_path: str
    title: str
    content_type: str
    brainstorm_value: str
    feeds_concepts: list[str]
    ingested: str
    last_compiled: str
    takeaway: str
    top_idea_blocks: list[str]
    why_in_kb: str


def serialize_source_summary(s: SourceSummary) -> str:
    fm_lines = [
        "---",
        f"source_path: {s.source_path}",
        f"title: {s.title}",
        f"content_type: {s.content_type}",
        f"brainstorm_value: {s.brainstorm_value}",
        f"feeds_concepts: {_yaml_list(s.feeds_concepts)}",
        f"ingested: {s.ingested}",
        f"last_compiled: {s.last_compiled}",
        "---",
    ]
    feeds_line = (
        "**Feeds concepts:** " + ", ".join(f"[[{c}]]" for c in s.feeds_concepts)
        if s.feeds_concepts else "**Feeds concepts:** _none_"
    )
    body = [
        f"# {s.title} — Source Summary",
        "",
        f"**One-line takeaway:** {s.takeaway or '_none_'}",
        "",
        "**Idea Blocks (top 3):**",
        "",
        _md_list(s.top_idea_blocks[:3]),
        "",
        f"**Why it's in the KB:** {s.why_in_kb or '_none_'}",
        "",
        feeds_line,
        "",
    ]
    return "\n".join(fm_lines) + "\n\n" + "\n".join(body)


def parse_source_summary(text: str) -> SourceSummary:
    fm, body = parse_frontmatter(text)
    feeds = fm.get("feeds_concepts", [])
    if isinstance(feeds, str):
        feeds = _parse_yaml_list(feeds)
    takeaway_match = re.search(r"\*\*One-line takeaway:\*\* (.*)", body)
    why_match = re.search(r"\*\*Why it's in the KB:\*\* (.*)", body)
    blocks_match = re.search(r"\*\*Idea Blocks \(top 3\):\*\*\s*\n\s*\n((?:- .+\n?)+)", body)
    top_blocks: list[str] = []
    if blocks_match:
        for line in blocks_match.group(1).splitlines():
            line = line.strip()
            if line.startswith("- ") and line[2:].strip() != "_none_":
                top_blocks.append(line[2:].strip())
    return SourceSummary(
        source_path=str(fm.get("source_path", "")),
        title=str(fm.get("title", "")),
        content_type=str(fm.get("content_type", "")),
        brainstorm_value=str(fm.get("brainstorm_value", "")),
        feeds_concepts=feeds if isinstance(feeds, list) else [],
        ingested=str(fm.get("ingested", "")),
        last_compiled=str(fm.get("last_compiled", "")),
        takeaway=takeaway_match.group(1).strip() if takeaway_match else "",
        top_idea_blocks=top_blocks,
        why_in_kb=why_match.group(1).strip() if why_match else "",
    )
