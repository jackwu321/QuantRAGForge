from __future__ import annotations

from collections import defaultdict
from datetime import date
from pathlib import Path

from wiki_schemas import parse_concept


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _load_concepts(concepts_dir: Path) -> list:
    concepts = []
    if not concepts_dir.exists():
        return concepts
    for md in sorted(concepts_dir.glob("*.md")):
        try:
            concepts.append(parse_concept(md.read_text(encoding="utf-8")))
        except Exception:
            continue
    return concepts


def generate_index(wiki_dir: Path) -> str:
    concepts_dir = wiki_dir / "concepts"
    sources_dir = wiki_dir / "sources"
    concepts = _load_concepts(concepts_dir)
    source_count = len(list(sources_dir.glob("*.md"))) if sources_dir.exists() else 0
    today = date.today().isoformat()

    lines = [
        "# Knowledge Base Index",
        "",
        f"_Last compiled: {today} · {len([c for c in concepts if c.status == 'stable'])} stable concepts · {source_count} source articles_",
        "",
    ]

    stable = [c for c in concepts if c.status == "stable"]
    proposed = [c for c in concepts if c.status == "proposed"]

    if stable:
        lines.append("## Stable Concepts")
        lines.append("")
        by_ct: dict[str, list] = defaultdict(list)
        for c in stable:
            ct = c.content_types[0] if c.content_types else "uncategorized"
            by_ct[ct].append(c)
        for ct in sorted(by_ct.keys()):
            lines.append(f"### {ct}")
            for c in sorted(by_ct[ct], key=lambda x: x.slug):
                count = len(c.sources)
                lines.append(f"- [[concepts/{c.slug}]] — {count} source(s)")
            lines.append("")

    if proposed:
        lines.append("## Proposed Concepts (awaiting review)")
        lines.append("")
        for c in sorted(proposed, key=lambda x: x.slug):
            lines.append(f"- [[concepts/{c.slug}]] — proposed {c.last_compiled} from {len(c.sources)} source(s)")
        lines.append("")

    return "\n".join(lines)


def write_index(wiki_dir: Path) -> Path:
    out = wiki_dir / "INDEX.md"
    _atomic_write(out, generate_index(wiki_dir))
    return out
