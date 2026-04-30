"""Machine-readable wiki state manifest.

Markdown files are the inspectable artifact for humans; this module is the
operational substrate for the agent. It tracks per-source content hashes (for
content-hash idempotency, no `mtime`/date guessing) and per-concept scoring
metadata (confidence, importance, freshness, conflicts, retrieval hints) used
to rerank concept memory at brainstorm time.

Schema is JSON-backed at `WIKI_STATE_PATH`. Schema version is `wiki-state-v1`.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "wiki-state-v1"
FRESHNESS_HALFLIFE_DAYS = 60.0


@dataclass
class SourceEntry:
    content_hash: str = ""
    last_seen: str = ""
    feeds_concepts: list[str] = field(default_factory=list)


@dataclass
class ConceptEntry:
    status: str = "stable"
    confidence: float = 0.0
    importance: float = 0.0
    freshness: float = 0.0
    last_compiled: str = ""
    compile_version: int = 0
    source_count: int = 0
    conflicts: list[str] = field(default_factory=list)
    retrieval_hints: list[str] = field(default_factory=list)


@dataclass
class WikiState:
    schema_version: str = SCHEMA_VERSION
    sources: dict[str, SourceEntry] = field(default_factory=dict)
    concepts: dict[str, ConceptEntry] = field(default_factory=dict)


def _empty() -> WikiState:
    return WikiState()


def load_wiki_state(path: Path) -> WikiState:
    """Load state from disk. Missing file or invalid JSON → empty v1 state."""
    if not path.exists():
        return _empty()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _empty()
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        return _empty()

    state = WikiState()
    raw_sources = data.get("sources") or {}
    raw_concepts = data.get("concepts") or {}
    if isinstance(raw_sources, dict):
        for path_str, entry in raw_sources.items():
            if not isinstance(entry, dict):
                continue
            state.sources[path_str] = SourceEntry(
                content_hash=str(entry.get("content_hash", "")),
                last_seen=str(entry.get("last_seen", "")),
                feeds_concepts=[str(c) for c in entry.get("feeds_concepts", []) if c],
            )
    if isinstance(raw_concepts, dict):
        for slug, entry in raw_concepts.items():
            if not isinstance(entry, dict):
                continue
            state.concepts[slug] = ConceptEntry(
                status=str(entry.get("status", "stable")),
                confidence=float(entry.get("confidence", 0.0) or 0.0),
                importance=float(entry.get("importance", 0.0) or 0.0),
                freshness=float(entry.get("freshness", 0.0) or 0.0),
                last_compiled=str(entry.get("last_compiled", "")),
                compile_version=int(entry.get("compile_version", 0) or 0),
                source_count=int(entry.get("source_count", 0) or 0),
                conflicts=[str(c) for c in entry.get("conflicts", []) if c],
                retrieval_hints=[str(h) for h in entry.get("retrieval_hints", []) if h],
            )
    return state


def save_wiki_state(state: WikiState, path: Path) -> None:
    """Atomically write state to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "sources": {
            p: {
                "content_hash": s.content_hash,
                "last_seen": s.last_seen,
                "feeds_concepts": s.feeds_concepts,
            }
            for p, s in state.sources.items()
        },
        "concepts": {
            slug: {
                "status": c.status,
                "confidence": c.confidence,
                "importance": c.importance,
                "freshness": c.freshness,
                "last_compiled": c.last_compiled,
                "compile_version": c.compile_version,
                "source_count": c.source_count,
                "conflicts": c.conflicts,
                "retrieval_hints": c.retrieval_hints,
            }
            for slug, c in state.concepts.items()
        },
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def source_content_hash(article_path: Path) -> str:
    """Return sha256 hex digest of the article file's bytes."""
    return hashlib.sha256(article_path.read_bytes()).hexdigest()


def is_source_changed(state: WikiState, article_path: Path) -> bool:
    """Return True if the article content hash differs from what's recorded.

    Returns True for unknown sources (never seen before).
    """
    key = str(article_path)
    if key not in state.sources:
        return True
    return state.sources[key].content_hash != source_content_hash(article_path)


def update_source_entry(
    state: WikiState,
    article_path: Path,
    feeds_concepts: list[str],
    last_seen: str | None = None,
) -> None:
    """Record source hash + feeds_concepts + last_seen for an article."""
    key = str(article_path)
    state.sources[key] = SourceEntry(
        content_hash=source_content_hash(article_path),
        last_seen=last_seen or date.today().isoformat(),
        feeds_concepts=list(feeds_concepts),
    )


def _freshness_from_date(last_compiled: str, now_ts: float | None = None) -> float:
    """Map a compile date to a 0..1 freshness score with exponential half-life decay."""
    if not last_compiled:
        return 0.0
    try:
        d = date.fromisoformat(last_compiled).toordinal()
    except ValueError:
        return 0.0
    today = (now_ts or time.time())
    today_ord = date.fromtimestamp(today).toordinal()
    age_days = max(0, today_ord - d)
    return math.exp(-math.log(2.0) * age_days / FRESHNESS_HALFLIFE_DAYS)


def concept_memory_score(
    confidence: float,
    importance: float,
    freshness: float,
    source_count: int,
    conflict_count: int = 0,
) -> float:
    """Composite memory score for ranking concepts at retrieval time.

    Used as the non-similarity portion of the rerank: vector_sim is added at
    retrieval time. Range: roughly 0..1 (clamped to non-negative).
    """
    coverage = 1.0 - math.exp(-source_count / 4.0) if source_count > 0 else 0.0
    score = (
        0.35 * confidence
        + 0.25 * importance
        + 0.20 * freshness
        + 0.20 * coverage
        - 0.15 * min(conflict_count, 3)
    )
    return max(0.0, score)


def update_concept_entry(state: WikiState, concept) -> None:
    """Record/update a concept's scoring metadata from a ConceptArticle.

    `concept` is a `wiki_schemas.ConceptArticle`. We pass duck-typed to avoid an
    import cycle.
    """
    slug = concept.slug
    existing = state.concepts.get(slug, ConceptEntry())
    source_count = len(concept.sources)

    # Confidence: bullets without source anchors lower confidence.
    from wiki_schemas import bullet_sources
    bullet_pool: list[str] = (
        list(concept.key_idea_blocks)
        + list(concept.variants)
        + list(concept.failure_modes)
        + list(concept.transfer_targets)
    )
    if bullet_pool:
        anchored = sum(1 for b in bullet_pool if bullet_sources(b))
        confidence = anchored / len(bullet_pool)
    else:
        # Seed stub with no bullets — neither high nor zero confidence
        confidence = 0.5 if source_count > 0 else 0.1

    # Importance: scaled by number of sources, capped.
    importance = min(1.0, source_count / 5.0)

    # Freshness: derived from last_compiled.
    freshness = _freshness_from_date(concept.last_compiled)

    # Retrieval hints: aliases + the concept title (lowercased) — used by
    # the lexical fallback when Chroma is unavailable.
    hints = list(concept.aliases) + [concept.title]
    seen: set[str] = set()
    deduped_hints: list[str] = []
    for h in hints:
        h2 = h.strip()
        if h2 and h2.lower() not in seen:
            seen.add(h2.lower())
            deduped_hints.append(h2)

    state.concepts[slug] = ConceptEntry(
        status=concept.status,
        confidence=confidence,
        importance=importance,
        freshness=freshness,
        last_compiled=concept.last_compiled,
        compile_version=concept.compile_version,
        source_count=source_count,
        conflicts=existing.conflicts,  # set by lint, not by recompile
        retrieval_hints=deduped_hints,
    )
