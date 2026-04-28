from __future__ import annotations

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
