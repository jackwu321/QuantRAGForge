"""Schemas for the LLM-maintained wiki layer.

Frontmatter parsing uses `parse_yaml_frontmatter` (PyYAML-backed), so block-list
fields like `sources:` round-trip cleanly. Both `ConceptArticle.sources`
(full paths) and `source_basenames` (article directory basenames rendered
as `[[basename]]` wikilinks under `## Sources`) round-trip independently.

Bullet anchors:
Bullets in `## Key Idea Blocks`, `## Variants & Implementations`,
`## Common Combinations`, `## Transfer Targets`, `## Failure Modes`,
`## Open Questions` are stored as strings of the form
`<text> [<source_basename>[, <source_basename>...]]`. Helpers `bullet_text` and
`bullet_sources` extract the components; `wiki_lint` uses `bullet_sources` to
flag unsupported (un-anchored) claims.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

import yaml

CONCEPT_STATUS = ("stable", "proposed", "deprecated")
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_BULLET_ANCHOR_RE = re.compile(r"^(?P<text>.+?)\s*\[(?P<sources>[^\]]*)\]\s*$")


def parse_yaml_frontmatter(text: str) -> tuple[dict, str]:
    """Parse a markdown file with YAML frontmatter delimited by `---` lines.

    Returns (frontmatter_dict, body_text). If frontmatter is missing or invalid,
    returns ({}, full_text).
    """
    if not text.startswith("---\n"):
        return {}, text
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        return {}, text
    frontmatter_text, body = parts[1], parts[2]
    try:
        data = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError:
        return {}, text
    if not isinstance(data, dict):
        return {}, text
    return data, body


def bullet_text(bullet: str) -> str:
    """Return the bullet text without its trailing `[anchor1, anchor2]` suffix."""
    m = _BULLET_ANCHOR_RE.match(bullet.strip())
    return m.group("text").strip() if m else bullet.strip()


def bullet_sources(bullet: str) -> list[str]:
    """Return the list of source basenames cited by the bullet's anchor suffix.

    Returns [] if the bullet has no `[...]` suffix or the suffix is empty.
    """
    m = _BULLET_ANCHOR_RE.match(bullet.strip())
    if not m:
        return []
    raw = m.group("sources").strip()
    if not raw:
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


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


def _str_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def parse_concept(text: str) -> ConceptArticle:
    """Parse a concept article markdown file back to a ConceptArticle."""
    fm, body = parse_yaml_frontmatter(text)

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
        aliases=_str_list(fm.get("aliases", [])),
        status=str(fm.get("status", "proposed")),
        related_concepts=_str_list(fm.get("related_concepts", [])),
        sources=_str_list(fm.get("sources", [])),
        content_types=_str_list(fm.get("content_types", [])),
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
    fm, body = parse_yaml_frontmatter(text)
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
        feeds_concepts=_str_list(fm.get("feeds_concepts", [])),
        ingested=str(fm.get("ingested", "")),
        last_compiled=str(fm.get("last_compiled", "")),
        takeaway=takeaway_match.group(1).strip() if takeaway_match else "",
        top_idea_blocks=top_blocks,
        why_in_kb=why_match.group(1).strip() if why_match else "",
    )
