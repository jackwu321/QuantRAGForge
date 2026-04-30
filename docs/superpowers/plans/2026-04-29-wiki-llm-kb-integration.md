# Wiki LLM KB Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an agent-first compiled wiki layer (`wiki/concepts/` + `wiki/sources/`) plus CLI ingest extension to web URLs and PDFs; wire wiki maintenance/retrieval tools into the LangGraph agent and rebuild brainstorm to retrieve compact concept memory first.

**Architecture:** Per-article enrichment unchanged. New `compile_wiki` step writes mechanical source summaries plus LLM-synthesized concept articles. A structured machine-readable wiki state file tracks freshness, confidence, importance, conflicts, source hashes, and retrieval hints. Wiki entries embed into the same ChromaDB collection with a `kb_layer` metadata field. Brainstorm retrieves selective concept memory first, complementary raw articles second.

**Product stance:** The wiki layer is primarily for agent operations, not human browsing. Human effort should focus on providing valuable raw materials and reviewing brainstorm/research outputs. The agent should maintain the wiki autonomously, surface only exceptions that affect research quality, and avoid requiring Obsidian or routine manual concept curation.

**Machine-memory principles:** Adopt the agent-memory lessons from `docs/superpowers/Why Karpathy’s Second Brain Breaks.txt`: selective injection, structured retrieval, scoring, conflict resolution, decay/staleness handling, and deterministic updates. Markdown remains the inspectable interface; structured JSON metadata is the operational substrate.

**Tech Stack:** Python 3.10+, langchain-core (`@tool`), LangGraph ReAct agent, ChromaDB, OpenAI-compatible LLM (existing kb_shared helpers). New deps: `trafilatura`, `readability-lxml`, `pypdf`, `pdfplumber`. Tests use `unittest` (per existing convention — `python3 -m unittest tests.test_<name> -v`).

**Spec:** [docs/superpowers/specs/2026-04-29-wiki-llm-kb-integration-design.md](../specs/2026-04-29-wiki-llm-kb-integration-design.md)

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `wiki_schemas.py` | Concept article + source summary frontmatter schemas, parse/serialize helpers, INDEX schema |
| `wiki_state.py` | Machine-readable wiki state manifest: source hashes, concept scores, freshness, conflicts, retrieval hints |
| `wiki_seed.py` | Seed taxonomy (7 concepts) and bootstrap function |
| `wiki_compile.py` | `compile_wiki` orchestrator — incremental + rebuild modes |
| `wiki_compile_llm.py` | `assign_concepts` and `recompile_concept` LLM prompts and callers |
| `wiki_index.py` | INDEX.md generator |
| `wiki_lint.py` | Agent-facing wiki health checks: stale concepts, unsupported claims, duplicate concepts, conflicts, orphan links |
| `_wechat.py` | WeChat-specific extraction (extracted from `ingest_wechat_article.py`, no behavior change) |
| `_web_extract.py` | Generic web extraction (trafilatura → readability fallback) |
| `_pdf_extract.py` | PDF extraction (pypdf → pdfplumber fallback) |
| `_code_math.py` | Code-block and LaTeX-math preservation utilities (used by all extractors) |
| `ingest_source.py` | Renamed entrypoint, dispatches WeChat / web / PDF / HTML |
| `tests/test_wiki_schemas.py` | Schema round-trip tests |
| `tests/test_wiki_seed.py` | Seed taxonomy + bootstrap tests |
| `tests/test_wiki_state.py` | State manifest hash/freshness/scoring/decay tests |
| `tests/test_wiki_compile.py` | compile_wiki idempotency, rebuild, status lifecycle tests |
| `tests/test_wiki_index.py` | INDEX generation tests |
| `tests/test_wiki_lint.py` | Wiki health check and conflict reporting tests |
| `tests/test_web_extract.py` | trafilatura mocked + readability fallback tests |
| `tests/test_pdf_extract.py` | pypdf + pdfplumber tests using small fixtures |
| `tests/test_code_math.py` | code/math preservation tests |
| `tests/test_ingest_source.py` | Dispatcher tests (extends/replaces test_ingest_wechat_article.py) |
| `tests/test_brainstorm_with_wiki.py` | Brainstorm retrieves concepts first, fallback when wiki sparse |
| `tests/fixtures/sample.pdf` | Tiny PDF for extraction tests |
| `tests/fixtures/sample-with-math.html` | HTML with LaTeX + code blocks |

### Modified files

| Path | Change |
|---|---|
| `requirements.txt` | Add 4 deps |
| `kb_shared.py` | Add wiki path constants, `kb_layer` field, `WIKI_DIR` |
| `ingest_wechat_article.py` | Becomes a one-line backward-compat shim importing from `ingest_source` |
| `embed_knowledge_base.py` | Index `wiki/concepts/` + `wiki/sources/` with `kb_layer` metadata |
| `brainstorm_from_kb.py` | Concept-first retrieval, fallback to pure-vector |
| `agent/tools.py` | Wiki maintenance/retrieval tools, `embed_knowledge`/`ingest_article` updated |
| `agent/prompts.py` | Add wiki-layer guidance |
| `README.md` | Reflect agent-first wiki tool surface, new pipeline step, new ingest sources |

### Removed files

| Path | Reason |
|---|---|
| `tests/test_ingest_wechat_article.py` | Replaced by `tests/test_ingest_source.py` (its WeChat cases are preserved verbatim there) |

---

## Phase 0: Setup

### Task 0.1: Add new dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Append the four new deps**

```
requests>=2.28.0
beautifulsoup4>=4.12.0
chromadb>=0.4.0
langgraph>=0.2.0
langchain-core>=0.3.0
langchain-community>=0.3.0
langchain-openai>=0.3.0
python-dotenv>=1.0.0
trafilatura>=1.12.0
readability-lxml>=0.8.1
pypdf>=4.0.0
pdfplumber>=0.11.0
```

- [ ] **Step 2: Install**

Run: `pip install -r requirements.txt`
Expected: all four new packages install without error.

- [ ] **Step 3: Verify importability**

Run: `python3 -c "import trafilatura, readability, pypdf, pdfplumber; print('ok')"`
Expected output: `ok`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "Add deps for wiki integration: trafilatura, readability-lxml, pypdf, pdfplumber"
```

---

## Phase A: Wiki Foundation

### Task A1: Wiki path constants in `kb_shared.py`

**Files:**
- Modify: `kb_shared.py:24` (add after `DEFAULT_SOURCE_DIRS`)

- [ ] **Step 1: Write failing test**

Create `tests/test_wiki_paths.py`:

```python
import unittest
from pathlib import Path

import kb_shared


class WikiPathsTests(unittest.TestCase):
    def test_wiki_dir_constant(self) -> None:
        self.assertEqual(kb_shared.WIKI_DIR, kb_shared.ROOT / "wiki")

    def test_wiki_concepts_dir_constant(self) -> None:
        self.assertEqual(kb_shared.WIKI_CONCEPTS_DIR, kb_shared.ROOT / "wiki" / "concepts")

    def test_wiki_sources_dir_constant(self) -> None:
        self.assertEqual(kb_shared.WIKI_SOURCES_DIR, kb_shared.ROOT / "wiki" / "sources")

    def test_wiki_index_path_constant(self) -> None:
        self.assertEqual(kb_shared.WIKI_INDEX_PATH, kb_shared.ROOT / "wiki" / "INDEX.md")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_wiki_paths -v`
Expected: FAIL — `AttributeError: module 'kb_shared' has no attribute 'WIKI_DIR'`

- [ ] **Step 3: Add constants**

In `kb_shared.py`, after the line `DEFAULT_SOURCE_DIRS = ("reviewed", "high-value")`:

```python
WIKI_DIR = ROOT / "wiki"
WIKI_CONCEPTS_DIR = WIKI_DIR / "concepts"
WIKI_SOURCES_DIR = WIKI_DIR / "sources"
WIKI_INDEX_PATH = WIKI_DIR / "INDEX.md"
WIKI_STATE_PATH = WIKI_DIR / "state.json"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_wiki_paths -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add kb_shared.py tests/test_wiki_paths.py
git commit -m "Add wiki path constants to kb_shared"
```

---

### Task A1.5: Machine-readable wiki state manifest

**Files:**
- Create: `wiki_state.py`
- Create: `tests/test_wiki_state.py`

**Purpose:** Markdown files are the inspectable artifact, but the agent needs structured, cheap, deterministic state for repeated use. Do not make the agent parse whole concept pages just to decide whether memory is fresh, trusted, or worth injecting.

- [ ] **Step 1: Add `WikiState` schema**

Create a JSON-backed manifest at `wiki/state.json` with this shape:

```json
{
  "schema_version": "wiki-state-v1",
  "sources": {
    "articles/high-value/example/article.md": {
      "content_hash": "sha256...",
      "last_seen": "2026-04-29",
      "feeds_concepts": ["momentum-strategies"]
    }
  },
  "concepts": {
    "momentum-strategies": {
      "status": "stable",
      "confidence": 0.82,
      "importance": 0.75,
      "freshness": 0.91,
      "last_compiled": "2026-04-29",
      "compile_version": 3,
      "source_count": 8,
      "conflicts": [],
      "retrieval_hints": ["momentum", "trend following", "ETF rotation"]
    }
  }
}
```

- [ ] **Step 2: Implement helpers**

Required helpers:

- `load_wiki_state(path: Path) -> WikiState`
- `save_wiki_state(state: WikiState, path: Path) -> None`
- `source_content_hash(article_path: Path) -> str`
- `concept_memory_score(confidence, importance, freshness, source_count) -> float`
- `is_source_changed(state, article_path) -> bool`
- `update_source_entry(state, article_path, feeds_concepts, last_seen) -> None`
- `update_concept_entry(state, concept_article) -> None`

- [ ] **Step 3: Tests**

Cover:

- Missing state file returns empty v1 state.
- Source hash changes when article content changes.
- Memory score ranks high-confidence/fresh concepts above stale concepts.
- Invalid JSON is handled as an empty state plus a warning, not a crash.

- [ ] **Step 4: Commit**

```bash
git add wiki_state.py tests/test_wiki_state.py kb_shared.py
git commit -m "Add machine-readable wiki state manifest"
```

---

### Task A2: Wiki schemas (concept article frontmatter)

**Files:**
- Create: `wiki_schemas.py`
- Create: `tests/test_wiki_schemas.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_wiki_schemas.py`:

```python
import unittest

import wiki_schemas


class ConceptArticleSchemaTests(unittest.TestCase):
    def test_serialize_concept_minimal(self) -> None:
        concept = wiki_schemas.ConceptArticle(
            title="Momentum Factor",
            slug="momentum-factor",
            aliases=["momentum", "动量因子"],
            status="stable",
            related_concepts=["factor-timing"],
            sources=["articles/reviewed/2026-03-22_华泰_趋势.../article.md"],
            content_types=["methodology"],
            last_compiled="2026-04-28",
            compile_version=1,
            synthesis="One paragraph synthesis.",
            definition="Canonical definition.",
            key_idea_blocks=["Idea 1"],
            variants=["Variant 1"],
            common_combinations=["[[factor-timing]]"],
            transfer_targets=["Crypto"],
            failure_modes=["Trend reversals"],
            open_questions=["Is residual momentum better?"],
            source_basenames=["2026-03-22_华泰_趋势"],
        )
        text = wiki_schemas.serialize_concept(concept)
        self.assertIn("title: Momentum Factor", text)
        self.assertIn("slug: momentum-factor", text)
        self.assertIn("status: stable", text)
        self.assertIn("## Synthesis", text)
        self.assertIn("## Sources", text)
        self.assertIn("[[2026-03-22_华泰_趋势]]", text)

    def test_round_trip_concept(self) -> None:
        original = wiki_schemas.ConceptArticle(
            title="Risk Parity",
            slug="risk-parity",
            aliases=["风险平价"],
            status="stable",
            related_concepts=[],
            sources=[],
            content_types=["allocation"],
            last_compiled="2026-04-28",
            compile_version=2,
            synthesis="S",
            definition="D",
            key_idea_blocks=[],
            variants=[],
            common_combinations=[],
            transfer_targets=[],
            failure_modes=[],
            open_questions=[],
            source_basenames=[],
        )
        text = wiki_schemas.serialize_concept(original)
        parsed = wiki_schemas.parse_concept(text)
        self.assertEqual(parsed.title, "Risk Parity")
        self.assertEqual(parsed.slug, "risk-parity")
        self.assertEqual(parsed.status, "stable")
        self.assertEqual(parsed.compile_version, 2)
        self.assertEqual(parsed.aliases, ["风险平价"])
        self.assertEqual(parsed.content_types, ["allocation"])

    def test_invalid_status_rejected(self) -> None:
        with self.assertRaises(ValueError):
            wiki_schemas.ConceptArticle(
                title="X", slug="x", aliases=[], status="invalid",
                related_concepts=[], sources=[], content_types=[],
                last_compiled="2026-04-28", compile_version=1,
                synthesis="", definition="", key_idea_blocks=[],
                variants=[], common_combinations=[], transfer_targets=[],
                failure_modes=[], open_questions=[], source_basenames=[],
            )

    def test_slug_must_be_kebab_case(self) -> None:
        with self.assertRaises(ValueError):
            wiki_schemas.ConceptArticle(
                title="X", slug="Bad_Slug", aliases=[], status="stable",
                related_concepts=[], sources=[], content_types=[],
                last_compiled="2026-04-28", compile_version=1,
                synthesis="", definition="", key_idea_blocks=[],
                variants=[], common_combinations=[], transfer_targets=[],
                failure_modes=[], open_questions=[], source_basenames=[],
            )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_wiki_schemas -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wiki_schemas'`

- [ ] **Step 3: Implement `wiki_schemas.py` (concept article half)**

Create `wiki_schemas.py`:

```python
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
        "sources:",
        *[f"  - {s}" for s in c.sources] or ["  []"],
        f"content_types: {_yaml_list(c.content_types)}",
        f"last_compiled: {c.last_compiled}",
        f"compile_version: {c.compile_version}",
        "---",
    ]
    if not c.sources:
        fm_lines[fm_lines.index("sources:")] = "sources: []"
        # Remove the "  []" placeholder line we added
        fm_lines = [line for line in fm_lines if line != "  []"]

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
```

Note: the existing `parse_frontmatter` in `kb_shared` only handles single-line `key: value` pairs. The `sources:` block-list serialization will need handling — for now, sources are serialized in the body's `## Sources` section as `[[basename]]` links, and the frontmatter `sources:` field uses YAML inline list when small. The block-list form in §"Concept article frontmatter" of the spec is tolerated but parsed via the `## Sources` section which is the source of truth in our parser. The test in step 1 covers the inline case; block-list is set as a follow-up note in Task A3.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_wiki_schemas -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add wiki_schemas.py tests/test_wiki_schemas.py
git commit -m "Add ConceptArticle schema with serialize/parse round-trip"
```

---

### Task A3: Source summary schema

**Files:**
- Modify: `wiki_schemas.py` (append SourceSummary)
- Modify: `tests/test_wiki_schemas.py` (append tests)

- [ ] **Step 1: Append failing tests**

Append to `tests/test_wiki_schemas.py` before `if __name__`:

```python
class SourceSummarySchemaTests(unittest.TestCase):
    def test_serialize_source_summary(self) -> None:
        summary = wiki_schemas.SourceSummary(
            source_path="articles/reviewed/2026-03-22_华泰_趋势/article.md",
            title="基于趋势和拐点的市值因子择时模型",
            content_type="methodology",
            brainstorm_value="high",
            feeds_concepts=["factor-timing", "momentum-factor"],
            ingested="2026-03-22",
            last_compiled="2026-04-28",
            takeaway="市值因子可基于趋势拐点择时。",
            top_idea_blocks=["趋势识别", "拐点过滤"],
            why_in_kb="High brainstorm value methodology.",
        )
        text = wiki_schemas.serialize_source_summary(summary)
        self.assertIn("title: 基于趋势和拐点的市值因子择时模型", text)
        self.assertIn("[[factor-timing]]", text)
        self.assertIn("**One-line takeaway:**", text)

    def test_round_trip_source_summary(self) -> None:
        original = wiki_schemas.SourceSummary(
            source_path="articles/high-value/x/article.md",
            title="X",
            content_type="strategy",
            brainstorm_value="medium",
            feeds_concepts=["etf-rotation"],
            ingested="2026-04-01",
            last_compiled="2026-04-28",
            takeaway="T",
            top_idea_blocks=["A", "B", "C"],
            why_in_kb="W",
        )
        text = wiki_schemas.serialize_source_summary(original)
        parsed = wiki_schemas.parse_source_summary(text)
        self.assertEqual(parsed.title, "X")
        self.assertEqual(parsed.feeds_concepts, ["etf-rotation"])
        self.assertEqual(parsed.top_idea_blocks, ["A", "B", "C"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_wiki_schemas -v`
Expected: FAIL — `AttributeError: module 'wiki_schemas' has no attribute 'SourceSummary'`

- [ ] **Step 3: Append SourceSummary to `wiki_schemas.py`**

Append to `wiki_schemas.py`:

```python
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
        "**Feeds concepts:** " + ", ".join(f"[[{c}]]" for c in s.feeds_concepts) if s.feeds_concepts else "**Feeds concepts:** _none_",
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_wiki_schemas -v`
Expected: PASS, 6 tests total.

- [ ] **Step 5: Commit**

```bash
git add wiki_schemas.py tests/test_wiki_schemas.py
git commit -m "Add SourceSummary schema with serialize/parse round-trip"
```

---

### Task A4: Seed taxonomy and bootstrap

**Files:**
- Create: `wiki_seed.py`
- Create: `tests/test_wiki_seed.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_wiki_seed.py`:

```python
import tempfile
import unittest
from pathlib import Path

import wiki_seed
import wiki_schemas


class WikiSeedTests(unittest.TestCase):
    def test_seed_taxonomy_has_seven_concepts(self) -> None:
        slugs = [seed.slug for seed in wiki_seed.SEED_CONCEPTS]
        self.assertEqual(len(slugs), 7)
        self.assertEqual(len(set(slugs)), 7)

    def test_seed_slugs_are_kebab_case(self) -> None:
        for seed in wiki_seed.SEED_CONCEPTS:
            self.assertRegex(seed.slug, r"^[a-z0-9]+(-[a-z0-9]+)*$")

    def test_bootstrap_creates_seed_stubs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp) / "wiki"
            wiki_seed.bootstrap_wiki(wiki_root)
            self.assertTrue((wiki_root / "concepts").is_dir())
            self.assertTrue((wiki_root / "sources").is_dir())
            for seed in wiki_seed.SEED_CONCEPTS:
                stub_path = wiki_root / "concepts" / f"{seed.slug}.md"
                self.assertTrue(stub_path.exists(), f"missing stub: {stub_path}")
                concept = wiki_schemas.parse_concept(stub_path.read_text(encoding="utf-8"))
                self.assertEqual(concept.status, "stable")
                self.assertEqual(concept.sources, [])

    def test_bootstrap_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp) / "wiki"
            wiki_seed.bootstrap_wiki(wiki_root)
            stub = wiki_root / "concepts" / wiki_seed.SEED_CONCEPTS[0].slug
            stub_path = stub.with_suffix(".md")
            mtime_first = stub_path.stat().st_mtime_ns
            # Run again — should not overwrite existing stub
            wiki_seed.bootstrap_wiki(wiki_root)
            self.assertEqual(stub_path.stat().st_mtime_ns, mtime_first)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_wiki_seed -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wiki_seed'`

- [ ] **Step 3: Implement `wiki_seed.py`**

Create `wiki_seed.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from wiki_schemas import ConceptArticle, serialize_concept


@dataclass(frozen=True)
class SeedConcept:
    slug: str
    title: str
    aliases: tuple[str, ...]
    content_types: tuple[str, ...]
    definition: str


SEED_CONCEPTS: tuple[SeedConcept, ...] = (
    SeedConcept(
        slug="factor-models",
        title="Factor Models",
        aliases=("因子模型", "多因子"),
        content_types=("methodology",),
        definition="Multi-factor frameworks describing cross-sectional return drivers.",
    ),
    SeedConcept(
        slug="factor-timing",
        title="Factor Timing",
        aliases=("因子择时",),
        content_types=("methodology",),
        definition="Methods that vary factor exposure over time based on signals or regime.",
    ),
    SeedConcept(
        slug="regime-detection",
        title="Regime Detection",
        aliases=("风格切换", "状态识别"),
        content_types=("methodology",),
        definition="Identification of market states that change which strategies work.",
    ),
    SeedConcept(
        slug="momentum-strategies",
        title="Momentum Strategies",
        aliases=("动量策略", "momentum"),
        content_types=("strategy",),
        definition="Trading rules that buy past winners or trend assets.",
    ),
    SeedConcept(
        slug="etf-rotation",
        title="ETF Rotation",
        aliases=("etf轮动", "行业轮动"),
        content_types=("strategy", "allocation"),
        definition="Periodic rebalancing across ETFs/sectors based on a ranking signal.",
    ),
    SeedConcept(
        slug="risk-parity",
        title="Risk Parity",
        aliases=("风险平价",),
        content_types=("allocation", "risk_control"),
        definition="Portfolio construction that allocates by risk contribution rather than capital weight.",
    ),
    SeedConcept(
        slug="volatility-targeting",
        title="Volatility Targeting",
        aliases=("波动率择时", "风险预算"),
        content_types=("risk_control",),
        definition="Position sizing based on rolling realized or implied volatility.",
    ),
)


def _seed_to_concept(seed: SeedConcept, today: str) -> ConceptArticle:
    return ConceptArticle(
        title=seed.title,
        slug=seed.slug,
        aliases=list(seed.aliases),
        status="stable",
        related_concepts=[],
        sources=[],
        content_types=list(seed.content_types),
        last_compiled=today,
        compile_version=0,
        synthesis="_pending: no sources yet_",
        definition=seed.definition,
        key_idea_blocks=[],
        variants=[],
        common_combinations=[],
        transfer_targets=[],
        failure_modes=[],
        open_questions=[],
        source_basenames=[],
    )


def bootstrap_wiki(wiki_dir: Path) -> list[Path]:
    """Create wiki/{concepts,sources}/ and write stubs for each seed concept.

    Idempotent: existing concept stubs are NOT overwritten.
    Returns the list of files actually created.
    """
    concepts_dir = wiki_dir / "concepts"
    sources_dir = wiki_dir / "sources"
    concepts_dir.mkdir(parents=True, exist_ok=True)
    sources_dir.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    created: list[Path] = []
    for seed in SEED_CONCEPTS:
        path = concepts_dir / f"{seed.slug}.md"
        if path.exists():
            continue
        concept = _seed_to_concept(seed, today)
        path.write_text(serialize_concept(concept), encoding="utf-8")
        created.append(path)
    return created
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_wiki_seed -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add wiki_seed.py tests/test_wiki_seed.py
git commit -m "Add seed taxonomy (7 concepts) and idempotent bootstrap"
```

---

## Phase B: Ingest Extension

### Task B1: Code/math preservation utilities

**Files:**
- Create: `_code_math.py`
- Create: `tests/test_code_math.py`
- Create: `tests/fixtures/sample-with-math.html`

- [ ] **Step 1: Create test fixture**

Create `tests/fixtures/sample-with-math.html`:

```html
<!DOCTYPE html>
<html><body>
<h1>Sample Article</h1>
<p>Inline math: $E = mc^2$ and display: $$\sum_{i=1}^n x_i$$</p>
<p>KaTeX: <span class="katex"><annotation encoding="application/x-tex">\alpha + \beta</annotation></span></p>
<pre><code class="language-python">def momentum(prices, window=12):
    return prices.pct_change(window)
</code></pre>
<p>And inline <code>vol_target</code> here.</p>
</body></html>
```

- [ ] **Step 2: Write failing tests**

Create `tests/test_code_math.py`:

```python
import unittest
from pathlib import Path

import _code_math


FIXTURE = Path(__file__).parent / "fixtures" / "sample-with-math.html"


class CodeMathTests(unittest.TestCase):
    def test_extract_code_blocks_with_language(self) -> None:
        html = FIXTURE.read_text(encoding="utf-8")
        blocks = _code_math.extract_code_blocks(html)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].language, "python")
        self.assertIn("def momentum", blocks[0].content)

    def test_preserve_inline_math_dollar(self) -> None:
        html = "<p>Equation: $a + b = c$ here.</p>"
        out = _code_math.preserve_math_to_markdown(html)
        self.assertIn("$a + b = c$", out)

    def test_preserve_display_math_dollar(self) -> None:
        html = "<p>Display: $$\\sum x_i$$ here.</p>"
        out = _code_math.preserve_math_to_markdown(html)
        self.assertIn("$$\\sum x_i$$", out)

    def test_preserve_katex_annotation(self) -> None:
        html = '<span><annotation encoding="application/x-tex">\\alpha + \\beta</annotation></span>'
        out = _code_math.preserve_math_to_markdown(html)
        self.assertIn("$\\alpha + \\beta$", out)

    def test_detect_has_code_and_math(self) -> None:
        html = FIXTURE.read_text(encoding="utf-8")
        flags = _code_math.detect_content_flags(html)
        self.assertTrue(flags["has_code"])
        self.assertTrue(flags["has_math"])

    def test_no_code_no_math_html(self) -> None:
        flags = _code_math.detect_content_flags("<p>just text</p>")
        self.assertFalse(flags["has_code"])
        self.assertFalse(flags["has_math"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python3 -m unittest tests.test_code_math -v`
Expected: FAIL — `ModuleNotFoundError: No module named '_code_math'`

- [ ] **Step 4: Implement `_code_math.py`**

Create `_code_math.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = None


@dataclass
class CodeBlock:
    language: str
    content: str


_LANG_CLASS_RE = re.compile(r"language-([a-zA-Z0-9_+-]+)")
_TEX_ANNOTATION_RE = re.compile(
    r'<annotation\s+encoding=["\']application/x-tex["\']>(.*?)</annotation>',
    re.DOTALL,
)
_LEGACY_MATHTEX_RE = re.compile(
    r'<script\s+type=["\']math/tex(?:; mode=display)?["\']>(.*?)</script>',
    re.DOTALL,
)
_INLINE_MATH_RE = re.compile(r"\$[^$\n]+?\$")
_DISPLAY_MATH_RE = re.compile(r"\$\$[^$]+?\$\$")
_PAREN_MATH_RE = re.compile(r"\\\((.*?)\\\)", re.DOTALL)
_BRACKET_MATH_RE = re.compile(r"\\\[(.*?)\\\]", re.DOTALL)


def extract_code_blocks(html: str) -> list[CodeBlock]:
    """Walk the source HTML for <pre><code> elements; return code blocks with language hint."""
    if BeautifulSoup is None:
        return []
    soup = BeautifulSoup(html, "html.parser")
    blocks: list[CodeBlock] = []
    for pre in soup.find_all("pre"):
        code = pre.find("code")
        target = code if code is not None else pre
        lang = ""
        classes = target.get("class") or []
        for cls in classes:
            m = _LANG_CLASS_RE.match(cls)
            if m:
                lang = m.group(1)
                break
        content = target.get_text("", strip=False).rstrip()
        if content:
            blocks.append(CodeBlock(language=lang, content=content))
    return blocks


def preserve_math_to_markdown(html: str) -> str:
    """Best-effort math preservation: rewrite KaTeX/MathJax annotations to $...$ / $$...$$.

    Returns the HTML with math regions converted to standard markdown/MathJax delimiters.
    `$...$` and `$$...$$` already in source are preserved as-is.
    """
    text = html
    text = _TEX_ANNOTATION_RE.sub(lambda m: f"${m.group(1).strip()}$", text)
    text = _LEGACY_MATHTEX_RE.sub(lambda m: f"${m.group(1).strip()}$", text)
    text = _PAREN_MATH_RE.sub(lambda m: f"${m.group(1).strip()}$", text)
    text = _BRACKET_MATH_RE.sub(lambda m: f"$${m.group(1).strip()}$$", text)
    return text


def detect_content_flags(html: str) -> dict[str, bool]:
    """Return {'has_code': bool, 'has_math': bool} for an HTML source."""
    has_code = bool(extract_code_blocks(html))
    has_math = bool(
        _TEX_ANNOTATION_RE.search(html)
        or _LEGACY_MATHTEX_RE.search(html)
        or _INLINE_MATH_RE.search(html)
        or _DISPLAY_MATH_RE.search(html)
        or _PAREN_MATH_RE.search(html)
        or _BRACKET_MATH_RE.search(html)
    )
    return {"has_code": has_code, "has_math": has_math}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m unittest tests.test_code_math -v`
Expected: PASS, 6 tests.

- [ ] **Step 6: Commit**

```bash
git add _code_math.py tests/test_code_math.py tests/fixtures/sample-with-math.html
git commit -m "Add code/math preservation utilities for ingest"
```

---

### Task B2: Generic web extractor

**Files:**
- Create: `_web_extract.py`
- Create: `tests/test_web_extract.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_web_extract.py`:

```python
import unittest
from unittest.mock import patch

import _web_extract


SAMPLE_HTML = """<!DOCTYPE html>
<html><body>
<article>
<h1>Momentum Reversal Effect</h1>
<p>By Jane Doe · 2026-04-01</p>
<p>The momentum factor exhibits reversal at long horizons.</p>
<pre><code class="language-python">x = 1</code></pre>
<p>Equation: $r_t = \\beta x_t$.</p>
</article>
</body></html>"""


class WebExtractTests(unittest.TestCase):
    def test_extract_returns_text_with_code_and_math(self) -> None:
        result = _web_extract.extract_from_html(SAMPLE_HTML, source_url="https://example.com/x")
        self.assertIn("Momentum Reversal Effect", result.title)
        self.assertIn("momentum factor", result.text)
        self.assertTrue(result.has_code)
        self.assertTrue(result.has_math)
        self.assertIn("```python", result.markdown)
        self.assertIn("$r_t", result.markdown)
        self.assertEqual(result.extraction_quality, "full")

    def test_paywall_detection(self) -> None:
        paywalled = "<html><body><p>Subscribe to read this article. Please subscribe.</p></body></html>"
        result = _web_extract.extract_from_html(paywalled, source_url="https://example.com/p")
        self.assertTrue(result.paywalled)

    def test_empty_html_returns_text_only(self) -> None:
        result = _web_extract.extract_from_html("", source_url="https://example.com/empty")
        self.assertEqual(result.extraction_quality, "text_only")
        self.assertEqual(result.text, "")

    @patch("_web_extract._fetch_url_text")
    def test_extract_from_url_calls_fetch(self, mock_fetch) -> None:
        mock_fetch.return_value = SAMPLE_HTML
        result = _web_extract.extract_from_url("https://example.com/x")
        self.assertEqual(result.title, "Momentum Reversal Effect")
        mock_fetch.assert_called_once_with("https://example.com/x")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_web_extract -v`
Expected: FAIL — `ModuleNotFoundError: No module named '_web_extract'`

- [ ] **Step 3: Implement `_web_extract.py`**

Create `_web_extract.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

try:
    import trafilatura
except ImportError:  # pragma: no cover
    trafilatura = None

try:
    from readability import Document as ReadabilityDocument
except ImportError:  # pragma: no cover
    ReadabilityDocument = None

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

from _code_math import detect_content_flags, extract_code_blocks, preserve_math_to_markdown


_PAYWALL_KEYWORDS = ("subscribe to read", "please subscribe", "paywall", "subscribe to continue")


@dataclass
class ExtractedArticle:
    title: str
    text: str
    markdown: str
    has_code: bool
    has_math: bool
    paywalled: bool
    extraction_quality: Literal["full", "partial", "text_only"]
    source_url: str


def _fetch_url_text(url: str) -> str:
    if requests is None:
        raise RuntimeError("requests is required for URL fetching")
    response = requests.get(url, timeout=(10, 30), headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    return response.text


def _detect_paywall(text: str) -> bool:
    lowered = text.lower()
    if not lowered.strip():
        return False
    if len(lowered) < 400 and any(kw in lowered for kw in _PAYWALL_KEYWORDS):
        return True
    return any(kw in lowered for kw in _PAYWALL_KEYWORDS)


def _extract_title(html: str) -> str:
    if trafilatura is not None:
        meta = trafilatura.extract_metadata(html)
        if meta and meta.title:
            return meta.title.strip()
    if ReadabilityDocument is not None:
        try:
            return ReadabilityDocument(html).short_title().strip()
        except Exception:
            pass
    return ""


def _markdown_with_code_and_math(html: str, base_text: str) -> str:
    blocks = extract_code_blocks(html)
    text_with_math = preserve_math_to_markdown(base_text)
    if not blocks:
        return text_with_math
    parts = [text_with_math, ""]
    parts.append("## Code Blocks")
    parts.append("")
    for block in blocks:
        fence_lang = block.language if block.language else ""
        parts.append(f"```{fence_lang}")
        parts.append(block.content)
        parts.append("```")
        parts.append("")
    return "\n".join(parts)


def extract_from_html(html: str, source_url: str = "") -> ExtractedArticle:
    """Extract an article from raw HTML using trafilatura → readability fallback."""
    if not html.strip():
        return ExtractedArticle(
            title="",
            text="",
            markdown="",
            has_code=False,
            has_math=False,
            paywalled=False,
            extraction_quality="text_only",
            source_url=source_url,
        )

    title = _extract_title(html)
    text = ""
    quality: Literal["full", "partial", "text_only"] = "text_only"

    if trafilatura is not None:
        try:
            text = trafilatura.extract(
                html,
                include_formatting=True,
                include_links=True,
                favor_recall=True,
            ) or ""
            if text.strip():
                quality = "full"
        except Exception:
            text = ""

    if not text.strip() and ReadabilityDocument is not None:
        try:
            doc = ReadabilityDocument(html)
            text = doc.summary()
            if text.strip():
                quality = "partial"
        except Exception:
            text = ""

    flags = detect_content_flags(html)
    markdown = _markdown_with_code_and_math(html, text)
    paywalled = _detect_paywall(text)
    return ExtractedArticle(
        title=title,
        text=text,
        markdown=markdown,
        has_code=flags["has_code"],
        has_math=flags["has_math"],
        paywalled=paywalled,
        extraction_quality=quality,
        source_url=source_url,
    )


def extract_from_url(url: str) -> ExtractedArticle:
    html = _fetch_url_text(url)
    return extract_from_html(html, source_url=url)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_web_extract -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add _web_extract.py tests/test_web_extract.py
git commit -m "Add generic web extractor (trafilatura primary, readability fallback)"
```

---

### Task B3: PDF extractor

**Files:**
- Create: `_pdf_extract.py`
- Create: `tests/test_pdf_extract.py`
- Create: `tests/fixtures/sample.pdf` (generated by test setup, see Step 1)

- [ ] **Step 1: Write failing tests** (creates fixture in `setUpClass`)

Create `tests/test_pdf_extract.py`:

```python
import unittest
from pathlib import Path

import _pdf_extract


FIXTURE_DIR = Path(__file__).parent / "fixtures"


class PdfExtractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Create a tiny in-memory PDF fixture using pypdf.
        from pypdf import PdfWriter
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        cls.fixture_path = FIXTURE_DIR / "sample.pdf"
        if cls.fixture_path.exists():
            return
        # Generate a 1-page PDF whose extracted text is "TEST_BROKER_REPORT alpha=0.05 sigma=0.2".
        # We use reportlab if available, else build minimal PDF by hand.
        try:
            from reportlab.pdfgen import canvas
            c = canvas.Canvas(str(cls.fixture_path))
            c.drawString(100, 800, "TEST_BROKER_REPORT alpha=0.05 sigma=0.2")
            c.showPage()
            c.save()
        except ImportError:
            # Build minimal PDF manually
            content = (
                b"%PDF-1.4\n"
                b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
                b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
                b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
                b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
                b"4 0 obj<</Length 88>>stream\n"
                b"BT /F1 12 Tf 100 700 Td (TEST_BROKER_REPORT alpha=0.05 sigma=0.2) Tj ET\n"
                b"endstream endobj\n"
                b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
                b"xref\n0 6\n0000000000 65535 f \n"
                b"0000000009 00000 n \n0000000053 00000 n \n0000000099 00000 n \n"
                b"0000000183 00000 n \n0000000282 00000 n \n"
                b"trailer<</Size 6/Root 1 0 R>>\nstartxref\n343\n%%EOF\n"
            )
            cls.fixture_path.write_bytes(content)

    def test_extract_text_from_simple_pdf(self) -> None:
        result = _pdf_extract.extract_from_file(self.fixture_path)
        self.assertIn("TEST_BROKER_REPORT", result.text)
        self.assertIn("alpha=0.05", result.text)
        self.assertEqual(result.extraction_quality, "full")

    def test_extract_returns_unicode_math_chars(self) -> None:
        result = _pdf_extract.extract_from_file(self.fixture_path)
        self.assertIn("alpha=0.05", result.text)

    def test_extract_missing_file_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            _pdf_extract.extract_from_file(Path("/does/not/exist.pdf"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_pdf_extract -v`
Expected: FAIL — `ModuleNotFoundError: No module named '_pdf_extract'`

- [ ] **Step 3: Implement `_pdf_extract.py`**

Create `_pdf_extract.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

try:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
except ImportError:  # pragma: no cover
    PdfReader = None
    PdfReadError = Exception

try:
    import pdfplumber
except ImportError:  # pragma: no cover
    pdfplumber = None


@dataclass
class ExtractedPdf:
    text: str
    page_count: int
    has_code: bool
    has_math: bool
    extraction_quality: Literal["full", "partial", "text_only"]
    source_path: str


_MATH_UNICODE = set("∑∫σμρ²³αβθλπδ∂≥≤≠∞")


def _looks_like_code_block(lines: list[str]) -> bool:
    """Heuristic: ≥80% of non-empty lines start with whitespace AND contain code-pattern chars."""
    non_empty = [ln for ln in lines if ln.strip()]
    if len(non_empty) < 3:
        return False
    code_like = sum(
        1 for ln in non_empty
        if (ln.startswith((" ", "\t")) and any(c in ln for c in "(){}[]=+-*/<>"))
    )
    return code_like / len(non_empty) >= 0.8


def _wrap_code_blocks(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        # Look ahead for runs of indented code-pattern lines
        run_end = i
        while run_end < len(lines) and (lines[run_end].startswith((" ", "\t")) or not lines[run_end].strip()):
            run_end += 1
        if run_end - i >= 3 and _looks_like_code_block(lines[i:run_end]):
            out.append("```")
            out.extend(lines[i:run_end])
            out.append("```")
            i = run_end
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


def _extract_pypdf(path: Path) -> tuple[str, int]:
    if PdfReader is None:
        raise RuntimeError("pypdf is required for PDF extraction")
    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages), len(reader.pages)


def _extract_pdfplumber(path: Path) -> tuple[str, int]:
    if pdfplumber is None:
        raise RuntimeError("pdfplumber is required for PDF fallback")
    with pdfplumber.open(str(path)) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
        return "\n\n".join(pages), len(pdf.pages)


def extract_from_file(path: Path) -> ExtractedPdf:
    """Extract text from a PDF, with pypdf primary and pdfplumber fallback."""
    if not path.exists():
        raise FileNotFoundError(str(path))

    text = ""
    page_count = 0
    quality: Literal["full", "partial", "text_only"] = "text_only"
    try:
        text, page_count = _extract_pypdf(path)
        if text.strip():
            quality = "full"
    except (PdfReadError, Exception):  # pragma: no cover - relies on system pdf
        text = ""

    # Heuristic: if pypdf returns < 100 chars/page on a 5+ page doc, try pdfplumber
    if page_count >= 5 and (len(text) / max(1, page_count)) < 100:
        try:
            text2, page_count2 = _extract_pdfplumber(path)
            if len(text2) > len(text):
                text = text2
                page_count = page_count2
                quality = "partial"
        except Exception:
            pass

    has_code = "def " in text or "class " in text or "import " in text
    has_math = any(ch in _MATH_UNICODE for ch in text)
    text = _wrap_code_blocks(text)

    return ExtractedPdf(
        text=text,
        page_count=page_count,
        has_code=has_code,
        has_math=has_math,
        extraction_quality=quality,
        source_path=str(path),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_pdf_extract -v`
Expected: PASS, 3 tests.

- [ ] **Step 5: Commit**

```bash
git add _pdf_extract.py tests/test_pdf_extract.py tests/fixtures/sample.pdf
git commit -m "Add PDF extractor (pypdf primary, pdfplumber fallback)"
```

---

### Task B4: WeChat module split

**Files:**
- Create: `_wechat.py` (extracted from `ingest_wechat_article.py`)
- The split is a *refactor*: same behavior, just relocated. Test by running existing WeChat tests after the split (they will be in `tests/test_ingest_source.py` after Task B5; for now keep `tests/test_ingest_wechat_article.py` passing).

- [ ] **Step 1: Verify existing WeChat tests pass before split**

Run: `python3 -m unittest tests.test_ingest_wechat_article -v`
Expected: PASS (record count for comparison).

- [ ] **Step 2: Create `_wechat.py` with the WeChat-specific extraction**

Create `_wechat.py` containing the WeChat-specific functions from `ingest_wechat_article.py`. The functions to move (verbatim, with `from __future__ import annotations` at top):

- `WECHAT_BLOCK_PATTERNS`, `DEFAULT_HEADERS` (constants)
- `ExtractedCodeBlock` (dataclass)
- `detect_blocked_wechat_page`
- `extract_article_data`
- `fetch_html`
- `download_binary`
- `infer_extension`
- `download_images`
- All other WeChat-specific helpers used by the above

Imports from existing top-level modules stay the same paths (e.g. `from kb_shared import ...`). Run grep:

```bash
grep -n "^def \|^class " ingest_wechat_article.py | head -60
```

Use the output to identify the WeChat-specific functions; copy them into `_wechat.py`. Keep `ArticleData`, `BatchResult`, `DuplicateArticleError`, `write_article`, `ingest_single_url`, `load_url_list`, `parse_args`, `main` in the original file for now (they will be reorganized in Task B5).

- [ ] **Step 3: In `ingest_wechat_article.py`, replace the moved functions with imports**

At the top of `ingest_wechat_article.py`, after existing imports:

```python
from _wechat import (
    WECHAT_BLOCK_PATTERNS,
    DEFAULT_HEADERS,
    ExtractedCodeBlock,
    detect_blocked_wechat_page,
    extract_article_data,
    fetch_html,
    download_binary,
    infer_extension,
    download_images,
)
```

Then delete the original definitions from `ingest_wechat_article.py`.

- [ ] **Step 4: Run existing tests to verify no behavior change**

Run: `python3 -m unittest tests.test_ingest_wechat_article -v`
Expected: PASS — same test count as Step 1.

- [ ] **Step 5: Commit**

```bash
git add _wechat.py ingest_wechat_article.py
git commit -m "Extract WeChat-specific extraction into _wechat.py module"
```

---

### Task B5: ingest_source.py dispatcher

**Files:**
- Create: `ingest_source.py`
- Create: `tests/test_ingest_source.py`
- Modify: `ingest_wechat_article.py` (becomes a one-line shim)

- [ ] **Step 1: Write failing dispatcher tests**

Create `tests/test_ingest_source.py`:

```python
import unittest
from unittest.mock import MagicMock, patch

import ingest_source


class DispatcherTests(unittest.TestCase):
    @patch("ingest_source._is_wechat_url")
    @patch("ingest_source._dispatch_wechat")
    def test_url_routing_wechat(self, mock_we, mock_is_we) -> None:
        mock_is_we.return_value = True
        mock_we.return_value = "/tmp/out"
        result = ingest_source.dispatch_url("https://mp.weixin.qq.com/s/abc")
        mock_we.assert_called_once()
        self.assertEqual(result, "/tmp/out")

    @patch("ingest_source._is_wechat_url", return_value=False)
    @patch("ingest_source._is_pdf_url", return_value=True)
    @patch("ingest_source._dispatch_pdf_url")
    def test_url_routing_pdf(self, mock_pdf, *_) -> None:
        mock_pdf.return_value = "/tmp/pdf"
        ingest_source.dispatch_url("https://example.com/paper.pdf")
        mock_pdf.assert_called_once()

    @patch("ingest_source._is_wechat_url", return_value=False)
    @patch("ingest_source._is_pdf_url", return_value=False)
    @patch("ingest_source._dispatch_web")
    def test_url_routing_generic_web(self, mock_web, *_) -> None:
        mock_web.return_value = "/tmp/web"
        ingest_source.dispatch_url("https://example.com/blog/post")
        mock_web.assert_called_once()

    def test_is_wechat_url(self) -> None:
        self.assertTrue(ingest_source._is_wechat_url("https://mp.weixin.qq.com/s/x"))
        self.assertFalse(ingest_source._is_wechat_url("https://substack.com/p/x"))

    def test_is_pdf_url_extension(self) -> None:
        self.assertTrue(ingest_source._is_pdf_url("https://example.com/paper.pdf"))
        self.assertFalse(ingest_source._is_pdf_url("https://example.com/blog"))


class WriteWebArticleTests(unittest.TestCase):
    def test_write_web_article_creates_directory(self) -> None:
        import tempfile
        from pathlib import Path
        from _web_extract import ExtractedArticle

        with tempfile.TemporaryDirectory() as tmp:
            article = ExtractedArticle(
                title="Test Post",
                text="Body.",
                markdown="# Test\n\nBody.",
                has_code=False,
                has_math=False,
                paywalled=False,
                extraction_quality="full",
                source_url="https://example.com/test-post",
            )
            out_dir = ingest_source.write_web_article(article, articles_root=Path(tmp))
            self.assertTrue((out_dir / "article.md").exists())
            self.assertTrue((out_dir / "source.json").exists())
            text = (out_dir / "article.md").read_text(encoding="utf-8")
            self.assertIn("source_type: web", text)
            self.assertIn("extraction_quality: full", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_ingest_source -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingest_source'`

- [ ] **Step 3: Implement `ingest_source.py`**

Create `ingest_source.py`:

```python
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from kb_shared import ROOT
import _web_extract
import _pdf_extract


ARTICLES_RAW_DIR = ROOT / "articles" / "raw"


def _is_wechat_url(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    return host.endswith("mp.weixin.qq.com")


def _is_pdf_url(url: str) -> bool:
    return url.lower().split("?", 1)[0].endswith(".pdf")


def _slugify(text: str, max_len: int = 60) -> str:
    text = re.sub(r"[^a-zA-Z0-9一-鿿]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:max_len].lower() or "untitled"


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _dispatch_wechat(url: str, content_type: str | None = None, force: bool = False) -> str:
    """Delegate to existing WeChat ingest pipeline."""
    from ingest_wechat_article import ingest_single_url
    args = argparse.Namespace(title=None, content_type=content_type, dry_run=False, force=force)
    result = ingest_single_url(url, args)
    if result.success:
        return result.output_dir
    raise RuntimeError(result.error or "wechat ingest failed")


def write_web_article(
    article: _web_extract.ExtractedArticle,
    articles_root: Path = ARTICLES_RAW_DIR,
    content_type: str = "methodology",
) -> Path:
    host = urlparse(article.source_url).hostname or "unknown"
    slug = _slugify(article.title or "untitled")
    out_dir = articles_root / f"{_today()}_{host}_{slug}"
    out_dir.mkdir(parents=True, exist_ok=True)

    fm = [
        "---",
        f"title: {article.title}",
        f"source_url: {article.source_url}",
        f"source_type: web",
        f"content_type: {content_type}",
        f"has_code: {str(article.has_code).lower()}",
        f"has_math: {str(article.has_math).lower()}",
        f"has_formula_images: false",
        f"extraction_quality: {article.extraction_quality}",
        f"paywalled: {str(article.paywalled).lower()}",
        f"status: raw",
        "---",
        "",
        f"# {article.title}",
        "",
        "## Main Content",
        "",
        article.markdown,
        "",
    ]
    (out_dir / "article.md").write_text("\n".join(fm), encoding="utf-8")
    (out_dir / "source.json").write_text(
        json.dumps(
            {
                "source_url": article.source_url,
                "source_type": "web",
                "ingested_at": datetime.now().isoformat(timespec="seconds"),
                "llm_enriched": False,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return out_dir


def write_pdf_article(
    pdf: _pdf_extract.ExtractedPdf,
    pdf_path: Path,
    articles_root: Path = ARTICLES_RAW_DIR,
    content_type: str = "methodology",
) -> Path:
    slug = _slugify(pdf_path.stem)
    out_dir = articles_root / f"{_today()}_{slug}"
    out_dir.mkdir(parents=True, exist_ok=True)
    target_pdf = out_dir / "source.pdf"
    if pdf_path.resolve() != target_pdf.resolve():
        target_pdf.write_bytes(pdf_path.read_bytes())

    fm = [
        "---",
        f"title: {pdf_path.stem}",
        f"source_path: {pdf_path}",
        f"source_type: pdf",
        f"content_type: {content_type}",
        f"has_code: {str(pdf.has_code).lower()}",
        f"has_math: {str(pdf.has_math).lower()}",
        f"has_formula_images: false",
        f"extraction_quality: {pdf.extraction_quality}",
        f"page_count: {pdf.page_count}",
        f"status: raw",
        "---",
        "",
        f"# {pdf_path.stem}",
        "",
        "## Main Content",
        "",
        pdf.text,
        "",
    ]
    (out_dir / "article.md").write_text("\n".join(fm), encoding="utf-8")
    (out_dir / "source.json").write_text(
        json.dumps(
            {
                "source_path": str(pdf_path),
                "source_type": "pdf",
                "ingested_at": datetime.now().isoformat(timespec="seconds"),
                "llm_enriched": False,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return out_dir


def _dispatch_web(url: str, content_type: str | None = None, force: bool = False) -> str:
    article = _web_extract.extract_from_url(url)
    if not article.text.strip():
        raise RuntimeError(f"web extraction returned empty: {url}")
    out_dir = write_web_article(article, content_type=content_type or "methodology")
    return str(out_dir)


def _dispatch_pdf_url(url: str, content_type: str | None = None, force: bool = False) -> str:
    import requests
    response = requests.get(url, timeout=(10, 60))
    response.raise_for_status()
    tmp_path = ARTICLES_RAW_DIR / "_tmp.pdf"
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.write_bytes(response.content)
    try:
        pdf = _pdf_extract.extract_from_file(tmp_path)
        return str(write_pdf_article(pdf, tmp_path, content_type=content_type or "methodology"))
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def dispatch_url(url: str, content_type: str | None = None, force: bool = False) -> str:
    if _is_wechat_url(url):
        return _dispatch_wechat(url, content_type=content_type, force=force)
    if _is_pdf_url(url):
        return _dispatch_pdf_url(url, content_type=content_type, force=force)
    return _dispatch_web(url, content_type=content_type, force=force)


def dispatch_pdf_file(path: str, content_type: str | None = None) -> str:
    p = Path(path).expanduser().resolve()
    pdf = _pdf_extract.extract_from_file(p)
    return str(write_pdf_article(pdf, p, content_type=content_type or "methodology"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest a source (WeChat URL, web URL, PDF URL, PDF file, HTML file).")
    parser.add_argument("--url", help="Single URL (auto-detected: wechat / pdf / web)")
    parser.add_argument("--url-list", help="File with one URL per line")
    parser.add_argument("--html-file", help="Local HTML file path")
    parser.add_argument("--pdf-file", help="Local PDF file path")
    parser.add_argument("--pdf-url", help="Remote PDF URL")
    parser.add_argument("--content-type", help="Content type override")
    parser.add_argument("--force", action="store_true", help="Override duplicate detection")
    args = parser.parse_args()

    if args.url:
        out = dispatch_url(args.url, content_type=args.content_type, force=args.force)
        print(f"Ingested: {out}")
        return 0
    if args.pdf_file:
        out = dispatch_pdf_file(args.pdf_file, content_type=args.content_type)
        print(f"Ingested PDF: {out}")
        return 0
    if args.pdf_url:
        out = _dispatch_pdf_url(args.pdf_url, content_type=args.content_type, force=args.force)
        print(f"Ingested PDF: {out}")
        return 0
    if args.html_file:
        from ingest_wechat_article import extract_article_data, write_article
        html = Path(args.html_file).expanduser().read_text(encoding="utf-8")
        article = extract_article_data(html, "", None)
        if args.content_type:
            article.content_type = args.content_type
        out_dir = write_article(article, force=args.force)
        print(f"Ingested HTML: {out_dir}")
        return 0
    if args.url_list:
        for url in [line.strip() for line in Path(args.url_list).read_text(encoding="utf-8").splitlines() if line.strip()]:
            try:
                out = dispatch_url(url, content_type=args.content_type, force=args.force)
                print(f"Ingested: {out}")
            except Exception as exc:
                print(f"FAILED {url}: {exc}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_ingest_source -v`
Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add ingest_source.py tests/test_ingest_source.py
git commit -m "Add ingest_source dispatcher for WeChat / web / PDF / HTML"
```

---

### Task B6: Backward-compat for `ingest_wechat_article.py`

**Files:**
- Modify: `ingest_wechat_article.py` (no shim removal yet — both stay functional; agent tool keeps importing the old name)

- [ ] **Step 1: Verify both old and new entrypoints still work**

Run: `python3 -m unittest tests.test_ingest_wechat_article tests.test_ingest_source -v`
Expected: PASS for both.

- [ ] **Step 2: Add a deprecation note (not removal) at top of `ingest_wechat_article.py`**

Insert after the existing `from __future__ import annotations` line, before any other imports:

```python
# This module is preserved for backward compatibility. New code should import
# from ingest_source for the unified WeChat / web / PDF / HTML dispatcher.
```

- [ ] **Step 3: Commit**

```bash
git add ingest_wechat_article.py
git commit -m "Mark ingest_wechat_article as backward-compat entrypoint"
```

---

### Task B7: Update `ingest_article` agent tool for new dispatch

**Files:**
- Modify: `agent/tools.py:35-143` (the `ingest_article` tool)

- [ ] **Step 1: Write failing test in `tests/test_agent_tools.py`**

Append to `tests/test_agent_tools.py` (create if it doesn't exist):

```python
import unittest
from unittest.mock import patch

from agent.tools import ingest_article


class IngestArticleDispatchTests(unittest.TestCase):
    @patch("ingest_source.dispatch_url")
    def test_url_routes_through_dispatch_url_for_pdf(self, mock_dispatch) -> None:
        mock_dispatch.return_value = "/tmp/out"
        result = ingest_article.invoke({"url": "https://example.com/paper.pdf"})
        mock_dispatch.assert_called_once()
        self.assertIn("Ingested", result)

    @patch("ingest_source.dispatch_pdf_file")
    def test_pdf_file_param_routes_to_pdf_dispatcher(self, mock_pdf) -> None:
        mock_pdf.return_value = "/tmp/out"
        result = ingest_article.invoke({"pdf_file": "/tmp/x.pdf"})
        mock_pdf.assert_called_once_with("/tmp/x.pdf", content_type=None)
        self.assertIn("Ingested", result)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_agent_tools.IngestArticleDispatchTests -v`
Expected: FAIL — current `ingest_article` does not accept `pdf_file` parameter.

- [ ] **Step 3: Update `ingest_article` in `agent/tools.py`**

Replace the `ingest_article` function body (the `@tool` decorated function, currently at lines 35–143) with:

```python
@tool
def ingest_article(
    url: Optional[str] = None,
    urls: Optional[str] = None,
    url_list_file: Optional[str] = None,
    html_file: Optional[str] = None,
    pdf_file: Optional[str] = None,
    pdf_url: Optional[str] = None,
    content_type: Optional[str] = None,
    force: bool = False,
) -> str:
    """Ingest articles into the knowledge base from various sources.

    Accepts ONE of the following (in priority order):
    - url: A single URL (auto-detected: WeChat / web / PDF)
    - urls: Multiple URLs (newline/comma separated; each auto-detected)
    - url_list_file: Path to a .txt file with one URL per line
    - html_file: Path to a locally saved HTML file (WeChat-style only)
    - pdf_file: Path to a local PDF file
    - pdf_url: A direct URL to a PDF document

    Set force=True to re-ingest articles that already exist.
    """
    import ingest_source
    from ingest_wechat_article import (
        extract_article_data, write_article, detect_blocked_wechat_page,
        DuplicateArticleError,
    )

    # Single PDF file
    if pdf_file:
        try:
            out = ingest_source.dispatch_pdf_file(pdf_file, content_type=content_type)
            return f"Ingested PDF: {out}"
        except Exception as exc:
            return f"Error ingesting PDF file {pdf_file}: {exc}"

    # Single PDF URL
    if pdf_url:
        try:
            out = ingest_source._dispatch_pdf_url(pdf_url, content_type=content_type, force=force)
            return f"Ingested PDF: {out}"
        except Exception as exc:
            return f"Error ingesting PDF URL {pdf_url}: {exc}"

    # Single HTML file (WeChat-style)
    if html_file and not url and not urls and not url_list_file:
        try:
            html_path = Path(html_file).expanduser().resolve()
            html = html_path.read_text(encoding="utf-8")
            detect_blocked_wechat_page(html)
            article = extract_article_data(html, "", None)
            if content_type:
                article.content_type = content_type
            out_dir = write_article(article, force=force)
            return f"Ingested HTML file successfully: {out_dir}"
        except DuplicateArticleError as exc:
            return f"Skipped (already exists): {exc}. Use force=True to re-ingest."
        except Exception as exc:
            return f"Error ingesting HTML file {html_file}: {exc}"

    # Collect URLs
    url_list: list[str] = []
    if url_list_file:
        try:
            url_list = [
                ln.strip() for ln in Path(url_list_file).expanduser().read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.strip().startswith("#")
            ]
        except Exception as exc:
            return f"Error reading URL list file {url_list_file}: {exc}"
        if not url_list:
            return f"No valid URLs found in {url_list_file}"
    elif urls:
        raw = urls.replace(",", "\n").replace(";", "\n").replace("，", "\n").replace("；", "\n")
        url_list = [u.strip() for u in raw.splitlines() if u.strip()]
    elif url:
        url_list = [url]
    else:
        return "Please provide one of: url, urls, url_list_file, html_file, pdf_file, pdf_url."

    results: list[str] = []
    success_count = 0
    rejected_warnings: list[str] = []
    for i, u in enumerate(url_list, start=1):
        rejected = find_rejected_source(source_url=u)
        if rejected and not force:
            reason = rejected.get("reason", "low value")
            results.append(
                f"[{i}/{len(url_list)}] WARNING — previously rejected: \"{rejected.get('title', '?')}\" "
                f"(reason: {reason}). Use force=True to re-ingest."
            )
            rejected_warnings.append(u)
            continue
        try:
            out = ingest_source.dispatch_url(u, content_type=content_type, force=force)
            success_count += 1
            results.append(f"[{i}/{len(url_list)}] OK: {out}")
        except Exception as exc:
            results.append(f"[{i}/{len(url_list)}] FAILED {u}: {exc}")

    fail_count = len(url_list) - success_count - len(rejected_warnings)
    parts = [f"{success_count} ingested"]
    if rejected_warnings:
        parts.append(f"{len(rejected_warnings)} previously rejected")
    if fail_count:
        parts.append(f"{fail_count} failed")
    return f"Result: {', '.join(parts)} (total {len(url_list)})\n" + "\n".join(results)
```

- [ ] **Step 4: Run all tool tests**

Run: `python3 -m unittest tests.test_agent_tools -v`
Expected: PASS for `IngestArticleDispatchTests`.

- [ ] **Step 5: Commit**

```bash
git add agent/tools.py tests/test_agent_tools.py
git commit -m "Extend ingest_article tool with pdf_file/pdf_url and dispatcher routing"
```

---

## Phase C: Wiki Compilation

### Task C0: Agent-first compile semantics

Before implementing the detailed compile tasks below, apply these semantics across `wiki_compile.py`, `wiki_compile_llm.py`, `wiki_index.py`, and tests:

- Wiki compilation is autonomous by default. The agent may create, merge, deprecate, or ignore concepts based on confidence/importance/freshness scores in `wiki/state.json`.
- Human approval is not part of the normal wiki maintenance path. Human review should happen on raw-material quality and final brainstorm/research outputs.
- Proposed concepts are an exception queue, not a required routine workflow. A concept should only remain `proposed` when confidence is too low, sources conflict, or the agent detects a taxonomy/merge ambiguity.
- High-confidence new concepts may become `stable` automatically when the LLM assignment result passes deterministic checks: valid slug, at least one source, confidence >= threshold, no conflicting existing concept, and no lint errors.
- Incremental idempotency must use source content hashes from `wiki_state.py`, not file mtime or `last_compiled` dates.
- Concept recompilation must update structured state: source count, source hashes, confidence, importance, freshness, conflict list, and retrieval hints.
- `wiki/INDEX.md` is a compact agent-readable routing index. Do not optimize it for Obsidian graph browsing.

Acceptance for this task is mostly behavioral: running `compile_wiki` twice with unchanged articles should produce zero LLM calls; adding one valuable source should recompile only affected concepts; low-confidence concept creation should appear in the exception queue returned by the agent, not block normal operation.

### Task C1: Source summary generator (mechanical, no LLM)

**Files:**
- Create: `wiki_compile.py` (initial version with source summary helper only)
- Create: `tests/test_wiki_compile.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_wiki_compile.py`:

```python
import tempfile
import unittest
from pathlib import Path

import wiki_compile


class SourceSummaryGenerationTests(unittest.TestCase):
    def _make_article(self, root: Path, dir_name: str, frontmatter: dict, body: str = "") -> Path:
        article_dir = root / "articles" / "reviewed" / dir_name
        article_dir.mkdir(parents=True, exist_ok=True)
        fm_lines = ["---"]
        for k, v in frontmatter.items():
            if isinstance(v, list):
                fm_lines.append(f"{k}: [{', '.join(str(x) for x in v)}]")
            else:
                fm_lines.append(f"{k}: {v}")
        fm_lines.append("---")
        (article_dir / "article.md").write_text("\n".join(fm_lines) + "\n\n" + body, encoding="utf-8")
        return article_dir

    def test_source_summary_generated_from_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            article_dir = self._make_article(root, "2026-03-22_test_article", {
                "title": "Test Article",
                "content_type": "methodology",
                "brainstorm_value": "high",
                "core_hypothesis": "Momentum predicts returns.",
                "summary": "A study of momentum factors.",
                "idea_blocks": ["Idea1", "Idea2", "Idea3"],
            })
            wiki_dir = root / "wiki"
            (wiki_dir / "sources").mkdir(parents=True)
            wiki_compile.write_source_summary(
                article_dir=article_dir,
                wiki_dir=wiki_dir,
                feeds_concepts=["momentum-strategies", "factor-models"],
            )
            summary_path = wiki_dir / "sources" / "2026-03-22_test_article.md"
            self.assertTrue(summary_path.exists())
            text = summary_path.read_text(encoding="utf-8")
            self.assertIn("title: Test Article", text)
            self.assertIn("Momentum predicts returns.", text)
            self.assertIn("[[momentum-strategies]]", text)
            self.assertIn("brainstorm_value: high", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_wiki_compile -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wiki_compile'`

- [ ] **Step 3: Implement `wiki_compile.py` with `write_source_summary`**

Create `wiki_compile.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_wiki_compile -v`
Expected: PASS, 1 test.

- [ ] **Step 5: Commit**

```bash
git add wiki_compile.py tests/test_wiki_compile.py
git commit -m "Add mechanical source summary generator (no LLM)"
```

---

### Task C2: assign_concepts LLM caller

**Files:**
- Create: `wiki_compile_llm.py`
- Modify: `tests/test_wiki_compile.py` (append tests)

- [ ] **Step 1: Append failing tests**

Append to `tests/test_wiki_compile.py`:

```python
class AssignConceptsTests(unittest.TestCase):
    def test_assign_concepts_parses_existing_and_proposed(self) -> None:
        from unittest.mock import patch
        import wiki_compile_llm

        fake_response = """{
  "existing_concepts": ["momentum-strategies", "factor-timing"],
  "proposed_new_concepts": [
    {
      "slug": "macro-momentum",
      "title": "Macro Momentum",
      "aliases": ["宏观动量"],
      "rationale": "Article applies momentum to macro factors specifically.",
      "draft_synthesis": "Momentum applied across macro signals."
    }
  ]
}"""
        with patch("wiki_compile_llm.call_llm_chat", return_value=fake_response):
            result = wiki_compile_llm.assign_concepts(
                article_frontmatter={"title": "X", "content_type": "methodology", "idea_blocks": ["a", "b"]},
                index_text="- momentum-strategies — Trading rules using past returns.",
            )
        self.assertEqual(result.existing_concepts, ["momentum-strategies", "factor-timing"])
        self.assertEqual(len(result.proposed_new_concepts), 1)
        self.assertEqual(result.proposed_new_concepts[0].slug, "macro-momentum")

    def test_assign_concepts_handles_invalid_json(self) -> None:
        from unittest.mock import patch
        import wiki_compile_llm

        with patch("wiki_compile_llm.call_llm_chat", return_value="not json"):
            result = wiki_compile_llm.assign_concepts(
                article_frontmatter={"title": "X"},
                index_text="",
            )
        self.assertEqual(result.existing_concepts, [])
        self.assertEqual(result.proposed_new_concepts, [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_wiki_compile.AssignConceptsTests -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wiki_compile_llm'`

- [ ] **Step 3: Implement `wiki_compile_llm.py`**

Create `wiki_compile_llm.py`:

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from kb_shared import call_llm_chat


@dataclass
class ProposedConcept:
    slug: str
    title: str
    aliases: list[str]
    rationale: str
    draft_synthesis: str


@dataclass
class ConceptAssignment:
    existing_concepts: list[str]
    proposed_new_concepts: list[ProposedConcept]


_ASSIGN_SYSTEM = """你是知识库概念分类助手。
你的任务是将一篇文章映射到现有概念列表，或在没有匹配时提出最多1个新概念。
输出严格 JSON，不要使用 markdown 代码块包装。"""


def _build_assign_prompt(article_fm: dict, index_text: str) -> str:
    title = article_fm.get("title", "")
    ct = article_fm.get("content_type", "")
    summary = article_fm.get("summary", "") or article_fm.get("core_hypothesis", "")
    ideas = article_fm.get("idea_blocks", [])
    if not isinstance(ideas, list):
        ideas = [str(ideas)]
    idea_text = "\n".join(f"- {i}" for i in ideas[:5])

    return f"""现有概念清单:
{index_text or '(空)'}

待分类文章:
title: {title}
content_type: {ct}
summary: {summary}
idea_blocks:
{idea_text or '(无)'}

输出 JSON schema:
{{
  "existing_concepts": ["<slug>", ...],
  "proposed_new_concepts": [
    {{
      "slug": "<kebab-case-slug>",
      "title": "<Title Case>",
      "aliases": ["<alias>", ...],
      "rationale": "<为什么需要新概念>",
      "draft_synthesis": "<1-2句话的概念定义>"
    }}
  ]
}}

规则:
- 优先匹配现有概念，最多列出 3 个
- 仅当没有合适现有概念且本文有独特视角时才提议新概念，最多 1 个
- proposed_new_concepts 的 slug 使用 kebab-case ASCII"""


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = text.rsplit("```", 1)[0]
    return text.strip()


def assign_concepts(article_frontmatter: dict, index_text: str) -> ConceptAssignment:
    prompt = _build_assign_prompt(article_frontmatter, index_text)
    messages = [
        {"role": "system", "content": _ASSIGN_SYSTEM},
        {"role": "user", "content": prompt},
    ]
    try:
        raw = call_llm_chat(messages, temperature=0.1)
    except Exception:
        return ConceptAssignment(existing_concepts=[], proposed_new_concepts=[])

    try:
        data = json.loads(_strip_json_fences(raw))
    except json.JSONDecodeError:
        return ConceptAssignment(existing_concepts=[], proposed_new_concepts=[])

    existing = [str(s) for s in data.get("existing_concepts", []) if s]
    proposed = []
    for p in data.get("proposed_new_concepts", []):
        if not isinstance(p, dict):
            continue
        slug = str(p.get("slug", "")).strip()
        if not slug:
            continue
        proposed.append(ProposedConcept(
            slug=slug,
            title=str(p.get("title", slug)),
            aliases=[str(a) for a in p.get("aliases", []) if a],
            rationale=str(p.get("rationale", "")),
            draft_synthesis=str(p.get("draft_synthesis", "")),
        ))
    return ConceptAssignment(existing_concepts=existing, proposed_new_concepts=proposed)
```

- [ ] **Step 4: Run tests**

Run: `python3 -m unittest tests.test_wiki_compile.AssignConceptsTests -v`
Expected: PASS, 2 tests.

- [ ] **Step 5: Commit**

```bash
git add wiki_compile_llm.py tests/test_wiki_compile.py
git commit -m "Add assign_concepts LLM caller with JSON parsing"
```

---

### Task C3: recompile_concept LLM caller

**Files:**
- Modify: `wiki_compile_llm.py` (append `recompile_concept`)
- Modify: `tests/test_wiki_compile.py` (append tests)

- [ ] **Step 1: Append failing tests**

Append to `tests/test_wiki_compile.py`:

```python
class RecompileConceptTests(unittest.TestCase):
    def test_recompile_returns_structured_sections(self) -> None:
        from unittest.mock import patch
        import wiki_compile_llm

        fake = """{
  "synthesis": "Momentum is best at 12-month horizons.",
  "definition": "Buy past winners.",
  "key_idea_blocks": ["12-1 momentum", "Risk-adjusted variant"],
  "variants": ["Time-series", "Cross-sectional"],
  "common_combinations": ["[[regime-detection]]", "[[risk-parity]]"],
  "transfer_targets": ["Crypto", "Fixed income"],
  "failure_modes": ["Reversals at long horizons"],
  "open_questions": ["Optimal lookback?"],
  "related_concepts": ["regime-detection", "risk-parity"]
}"""
        with patch("wiki_compile_llm.call_llm_chat", return_value=fake):
            r = wiki_compile_llm.recompile_concept(
                concept_slug="momentum-strategies",
                concept_title="Momentum Strategies",
                source_articles=[{"title": "S1", "idea_blocks": ["12-1"]}],
            )
        self.assertIn("12-month", r.synthesis)
        self.assertEqual(r.related_concepts, ["regime-detection", "risk-parity"])
        self.assertEqual(len(r.key_idea_blocks), 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_wiki_compile.RecompileConceptTests -v`
Expected: FAIL — `recompile_concept` not defined.

- [ ] **Step 3: Append `recompile_concept` to `wiki_compile_llm.py`**

```python
@dataclass
class RecompileResult:
    synthesis: str
    definition: str
    key_idea_blocks: list[str]
    variants: list[str]
    common_combinations: list[str]
    transfer_targets: list[str]
    failure_modes: list[str]
    open_questions: list[str]
    related_concepts: list[str]


_RECOMPILE_SYSTEM = """你是量化投研知识库的概念合成助手。
你的任务是基于多篇来源文章合成一篇概念文章的各个章节。
输出严格 JSON，每个字段独立。Synthesis 是 1-3 段叙事，其它是项目列表。"""


def _format_source_articles(sources: list[dict]) -> str:
    parts = []
    for i, s in enumerate(sources, 1):
        title = s.get("title", "")
        ct = s.get("content_type", "")
        ideas = s.get("idea_blocks", [])
        if not isinstance(ideas, list):
            ideas = [str(ideas)]
        ideas_text = "\n  ".join(f"- {x}" for x in ideas[:5])
        parts.append(f"[Source {i}] {title} ({ct})\n  {ideas_text}")
    return "\n\n".join(parts) or "(no sources)"


def recompile_concept(
    concept_slug: str,
    concept_title: str,
    source_articles: list[dict],
) -> RecompileResult:
    user_prompt = f"""概念 slug: {concept_slug}
概念 title: {concept_title}

来源文章列表:
{_format_source_articles(source_articles)}

输出 JSON schema:
{{
  "synthesis": "<1-3 段，描述这些来源对该概念合起来说了什么>",
  "definition": "<1 段经典定义>",
  "key_idea_blocks": ["<由源文章 idea_blocks 聚合后去重>", ...],
  "variants": ["<不同来源的实现/变体>", ...],
  "common_combinations": ["<可与之组合的概念，使用 [[slug]] 格式>", ...],
  "transfer_targets": ["<可迁移到的市场/资产/周期>", ...],
  "failure_modes": ["<研究失效边界，不要写风控规则>", ...],
  "open_questions": ["<延伸研究问题>", ...],
  "related_concepts": ["<相关概念 slug，无 [[]]>", ...]
}}"""
    messages = [
        {"role": "system", "content": _RECOMPILE_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]
    try:
        raw = call_llm_chat(messages, temperature=0.2)
    except Exception:
        return RecompileResult("", "", [], [], [], [], [], [], [])

    try:
        data = json.loads(_strip_json_fences(raw))
    except json.JSONDecodeError:
        return RecompileResult("", "", [], [], [], [], [], [], [])

    def _list(key: str) -> list[str]:
        v = data.get(key, [])
        return [str(x) for x in v] if isinstance(v, list) else []

    return RecompileResult(
        synthesis=str(data.get("synthesis", "")),
        definition=str(data.get("definition", "")),
        key_idea_blocks=_list("key_idea_blocks"),
        variants=_list("variants"),
        common_combinations=_list("common_combinations"),
        transfer_targets=_list("transfer_targets"),
        failure_modes=_list("failure_modes"),
        open_questions=_list("open_questions"),
        related_concepts=_list("related_concepts"),
    )
```

- [ ] **Step 4: Run tests**

Run: `python3 -m unittest tests.test_wiki_compile.RecompileConceptTests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add wiki_compile_llm.py tests/test_wiki_compile.py
git commit -m "Add recompile_concept LLM caller"
```

---

### Task C4: INDEX.md generator

**Files:**
- Create: `wiki_index.py`
- Create: `tests/test_wiki_index.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_wiki_index.py`:

```python
import tempfile
import unittest
from pathlib import Path

import wiki_index
import wiki_seed


class WikiIndexTests(unittest.TestCase):
    def test_generate_index_groups_concepts_by_content_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            wiki_seed.bootstrap_wiki(wiki_dir)
            text = wiki_index.generate_index(wiki_dir)
            self.assertIn("# Knowledge Base Index", text)
            self.assertIn("## Stable Concepts", text)
            self.assertIn("[[concepts/momentum-strategies]]", text)

    def test_generate_index_lists_proposed_concepts_separately(self) -> None:
        from wiki_schemas import ConceptArticle, serialize_concept
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            (wiki_dir / "concepts").mkdir(parents=True)
            (wiki_dir / "sources").mkdir(parents=True)
            proposed = ConceptArticle(
                title="Macro Momentum", slug="macro-momentum", aliases=[],
                status="proposed", related_concepts=[], sources=[],
                content_types=["methodology"], last_compiled="2026-04-28",
                compile_version=0, synthesis="d", definition="x",
                key_idea_blocks=[], variants=[], common_combinations=[],
                transfer_targets=[], failure_modes=[], open_questions=[],
                source_basenames=[],
            )
            (wiki_dir / "concepts" / "macro-momentum.md").write_text(
                serialize_concept(proposed), encoding="utf-8"
            )
            text = wiki_index.generate_index(wiki_dir)
            self.assertIn("## Proposed Concepts", text)
            self.assertIn("[[concepts/macro-momentum]]", text)

    def test_write_index_creates_file_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            wiki_seed.bootstrap_wiki(wiki_dir)
            path = wiki_index.write_index(wiki_dir)
            self.assertTrue(path.exists())
            self.assertEqual(path, wiki_dir / "INDEX.md")
            content = path.read_text(encoding="utf-8")
            self.assertIn("# Knowledge Base Index", content)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_wiki_index -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wiki_index'`

- [ ] **Step 3: Implement `wiki_index.py`**

Create `wiki_index.py`:

```python
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
        lines.append("## Proposed Concepts (low-confidence exceptions)")
        lines.append("")
        for c in sorted(proposed, key=lambda x: x.slug):
            lines.append(f"- [[concepts/{c.slug}]] — proposed {c.last_compiled} from {len(c.sources)} source(s)")
        lines.append("")

    return "\n".join(lines)


def write_index(wiki_dir: Path) -> Path:
    out = wiki_dir / "INDEX.md"
    _atomic_write(out, generate_index(wiki_dir))
    return out
```

- [ ] **Step 4: Run tests**

Run: `python3 -m unittest tests.test_wiki_index -v`
Expected: PASS, 3 tests.

- [ ] **Step 5: Commit**

```bash
git add wiki_index.py tests/test_wiki_index.py
git commit -m "Add INDEX.md generator (mechanical, no LLM)"
```

---

### Task C5: compile_wiki orchestrator

**Files:**
- Modify: `wiki_compile.py` (append orchestrator)
- Modify: `tests/test_wiki_compile.py` (append tests)

- [ ] **Step 1: Append failing tests**

Append to `tests/test_wiki_compile.py`:

```python
class CompileOrchestratorTests(unittest.TestCase):
    def _setup_corpus(self, root: Path) -> None:
        from wiki_seed import bootstrap_wiki
        bootstrap_wiki(root / "wiki")
        article_dir = root / "articles" / "reviewed" / "2026-03-22_test_article"
        article_dir.mkdir(parents=True, exist_ok=True)
        (article_dir / "article.md").write_text(
            "---\n"
            "title: Test Article\n"
            "content_type: methodology\n"
            "brainstorm_value: high\n"
            "core_hypothesis: Momentum predicts.\n"
            "idea_blocks: [Idea A, Idea B]\n"
            "summary: A study.\n"
            "status: reviewed\n"
            "---\n\n## Main Content\n\nBody.\n",
            encoding="utf-8",
        )

    def test_incremental_compile_writes_source_summary(self) -> None:
        from unittest.mock import patch
        import wiki_compile
        import wiki_compile_llm

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._setup_corpus(root)

            assignment = wiki_compile_llm.ConceptAssignment(
                existing_concepts=["momentum-strategies"],
                proposed_new_concepts=[],
            )
            recompile = wiki_compile_llm.RecompileResult(
                synthesis="S", definition="D",
                key_idea_blocks=["k"], variants=[], common_combinations=[],
                transfer_targets=[], failure_modes=[], open_questions=[],
                related_concepts=[],
            )
            with patch("wiki_compile.assign_concepts", return_value=assignment), \
                 patch("wiki_compile.recompile_concept", return_value=recompile):
                report = wiki_compile.compile_wiki(
                    kb_root=root,
                    mode="incremental",
                )
            self.assertGreaterEqual(report.sources_written, 1)
            summary_path = root / "wiki" / "sources" / "2026-03-22_test_article.md"
            self.assertTrue(summary_path.exists())
            momentum_path = root / "wiki" / "concepts" / "momentum-strategies.md"
            text = momentum_path.read_text(encoding="utf-8")
            self.assertIn("articles/reviewed/2026-03-22_test_article/article.md", text)

    def test_incremental_idempotent_skips_unchanged(self) -> None:
        from unittest.mock import patch
        import wiki_compile
        import wiki_compile_llm

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._setup_corpus(root)
            assignment = wiki_compile_llm.ConceptAssignment(["momentum-strategies"], [])
            recompile = wiki_compile_llm.RecompileResult("S", "D", [], [], [], [], [], [], [])
            with patch("wiki_compile.assign_concepts", return_value=assignment) as ma, \
                 patch("wiki_compile.recompile_concept", return_value=recompile) as mr:
                wiki_compile.compile_wiki(kb_root=root, mode="incremental")
                first_calls = ma.call_count + mr.call_count

                # Run again — nothing changed
                wiki_compile.compile_wiki(kb_root=root, mode="incremental")
                second_calls = ma.call_count + mr.call_count - first_calls
                self.assertEqual(second_calls, 0)

    def test_proposed_concept_lands_with_status_proposed(self) -> None:
        from unittest.mock import patch
        import wiki_compile
        import wiki_compile_llm
        from wiki_schemas import parse_concept

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._setup_corpus(root)
            proposed = wiki_compile_llm.ProposedConcept(
                slug="macro-momentum", title="Macro Momentum",
                aliases=["宏观动量"], rationale="r", draft_synthesis="ds",
            )
            assignment = wiki_compile_llm.ConceptAssignment([], [proposed])
            recompile = wiki_compile_llm.RecompileResult("S", "D", [], [], [], [], [], [], [])
            with patch("wiki_compile.assign_concepts", return_value=assignment), \
                 patch("wiki_compile.recompile_concept", return_value=recompile):
                wiki_compile.compile_wiki(kb_root=root, mode="incremental")
            path = root / "wiki" / "concepts" / "macro-momentum.md"
            self.assertTrue(path.exists())
            concept = parse_concept(path.read_text(encoding="utf-8"))
            self.assertEqual(concept.status, "proposed")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_wiki_compile.CompileOrchestratorTests -v`
Expected: FAIL — `compile_wiki` is not defined.

- [ ] **Step 3: Append orchestrator to `wiki_compile.py`**

Append to `wiki_compile.py`:

```python
from dataclasses import dataclass, field
from datetime import date

from kb_shared import ROOT, DEFAULT_SOURCE_DIRS, parse_frontmatter
from wiki_schemas import ConceptArticle, parse_concept, serialize_concept
from wiki_compile_llm import (
    ConceptAssignment, ProposedConcept, RecompileResult,
    assign_concepts, recompile_concept,
)
from wiki_index import write_index
from wiki_seed import bootstrap_wiki
from wiki_state import load_wiki_state, save_wiki_state, update_source_entry, update_concept_entry


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


def _source_changed(article_dir: Path, wiki_state) -> bool:
    """Return True if the article content hash differs from wiki/state.json."""
    from wiki_state import is_source_changed
    return is_source_changed(wiki_state, article_dir / "article.md")


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
    wiki_state = load_wiki_state(wiki_dir / "state.json")

    if mode == "rebuild":
        cdir = wiki_dir / "concepts"
        for md in cdir.glob("*.md"):
            md.unlink()
        bootstrap_wiki(wiki_dir)
        idx = wiki_dir / "INDEX.md"
        if idx.exists():
            idx.unlink()

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

        # Idempotency: skip if source hash is unchanged AND source summary exists.
        # Do not use file mtimes or last_compiled dates for agent memory freshness.
        existing_summary = wiki_dir / "sources" / f"{article_dir.name}.md"
        prior_concepts = [
            c for c in (_load_concept(wiki_dir, slug) for slug in _peek_existing_assignments(article_dir, wiki_dir))
            if c is not None
        ]
        if mode == "incremental" and existing_summary.exists() and prior_concepts and not _source_changed(article_dir, wiki_state):
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
            update_source_entry(wiki_state, article_dir / "article.md", feeds_concepts=feeds, last_seen=today)
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
            update_concept_entry(wiki_state, new_concept)

    if not dry_run:
        save_wiki_state(wiki_state, wiki_dir / "state.json")
        write_index(wiki_dir)

    return report


_ASSIGNMENT_CACHE_FILE = "_assignment_cache.json"


def _peek_existing_assignments(article_dir: Path, wiki_dir: Path) -> list[str]:
    """Look up the concepts an article was previously assigned to (from cache file)."""
    import json
    cache = wiki_dir / _ASSIGNMENT_CACHE_FILE
    if not cache.exists():
        return []
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data.get(str(article_dir), [])


def _record_assignment(article_dir: Path, wiki_dir: Path, slugs: list[str]) -> None:
    import json
    cache = wiki_dir / _ASSIGNMENT_CACHE_FILE
    try:
        data = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    except Exception:
        data = {}
    data[str(article_dir)] = slugs
    _atomic_write(cache, json.dumps(data, ensure_ascii=False, indent=2))
```

- [ ] **Step 4: Run tests**

Run: `python3 -m unittest tests.test_wiki_compile.CompileOrchestratorTests -v`
Expected: PASS, 3 tests.

- [ ] **Step 5: Commit**

```bash
git add wiki_compile.py tests/test_wiki_compile.py
git commit -m "Add compile_wiki orchestrator with incremental + rebuild modes"
```

---

### Task C6: Wiki lint and autonomous health reporting

**Files:**
- Create: `wiki_lint.py`
- Create: `tests/test_wiki_lint.py`
- Modify: `wiki_compile.py`
- Modify: `agent/tools.py`

**Purpose:** The wiki layer should improve without drifting. The agent needs a cheap health report it can use after compile and before brainstorm. This replaces routine human concept review.

- [ ] **Step 1: Implement lint checks**

`wiki_lint.py` must expose:

```python
def lint_wiki(kb_root: Path = ROOT) -> WikiLintReport: ...
```

Minimum checks:

- `stale_concepts`: stable concepts whose source hashes changed since last compile.
- `unsupported_claims`: concept sections with no source citations or empty `sources`.
- `duplicate_or_near_duplicate_concepts`: same aliases, same retrieval hints, or very high embedding similarity.
- `conflicting_claims`: source summaries under the same concept with opposing `failure_modes`, `constraints`, or `core_hypothesis` fields.
- `orphan_sources`: source summaries that feed no stable concept.
- `orphan_concepts`: stable concepts with zero sources except seed stubs.
- `oversized_concepts`: concept pages whose compiled text exceeds the token budget for default retrieval.

- [ ] **Step 2: Structured report**

Return both human-readable text and machine-readable severity:

```python
@dataclass
class WikiLintIssue:
    severity: Literal["info", "warning", "error"]
    kind: str
    path: str
    message: str
    suggested_action: str

@dataclass
class WikiLintReport:
    issues: list[WikiLintIssue]
    def ok_for_brainstorm(self) -> bool: ...
    def summary(self) -> str: ...
```

- [ ] **Step 3: Integrate into compile**

After `compile_wiki`, run lint automatically and write `wiki/lint_report.json`. Do not block normal use on warnings. Block only on errors that would make brainstorm misleading, such as concept parse failures or source-hash corruption.

- [ ] **Step 4: Add agent tool**

Add `audit_wiki()` to `agent/tools.py`. It returns the latest lint summary and suggested maintenance actions. This is agent-facing operational telemetry; it is not a human review workflow.

- [ ] **Step 5: Tests**

Cover stale source hash, orphan concept, duplicate alias, unsupported concept with no sources, and `ok_for_brainstorm()`.

- [ ] **Step 6: Commit**

```bash
git add wiki_lint.py tests/test_wiki_lint.py wiki_compile.py agent/tools.py
git commit -m "Add wiki lint health checks for agent memory"
```

---

## Phase D: Agent Tool Surface

The wiki tools are for agent operation. They should support autonomous maintenance, selective memory retrieval, and health reporting. They should not create a routine human approval loop inside the wiki layer.

### Task D1: `compile_wiki` agent tool

**Files:**
- Modify: `agent/tools.py` (append tool)
- Modify: `tests/test_agent_tools.py` (append tests)

- [ ] **Step 1: Write failing test**

Append to `tests/test_agent_tools.py`:

```python
class CompileWikiToolTests(unittest.TestCase):
    def test_compile_wiki_invokes_orchestrator(self) -> None:
        from unittest.mock import patch
        from agent.tools import compile_wiki as compile_wiki_tool
        import wiki_compile

        fake_report = wiki_compile.CompileReport(
            sources_written=2, concepts_assigned=2, concepts_recompiled=1,
        )
        with patch("wiki_compile.compile_wiki", return_value=fake_report):
            result = compile_wiki_tool.invoke({"mode": "incremental"})
        self.assertIn("2 sources", result)
        self.assertIn("1 concepts recompiled", result)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_agent_tools.CompileWikiToolTests -v`
Expected: FAIL — `compile_wiki` tool not exported.

- [ ] **Step 3: Append `compile_wiki` tool to `agent/tools.py`**

Append before `ALL_TOOLS = [...]`:

```python
@tool
def compile_wiki(mode: str = "incremental", dry_run: bool = False) -> str:
    """Compile or update the LLM-maintained wiki from reviewed/high-value articles.

    Modes:
    - 'incremental' (default): only update concepts whose sources changed.
    - 'rebuild': wipe non-seed concepts and recompile from scratch.

    Set dry_run=True to plan without writing files.
    """
    import wiki_compile
    if mode not in ("incremental", "rebuild"):
        return f"Invalid mode '{mode}'. Must be 'incremental' or 'rebuild'."
    try:
        report = wiki_compile.compile_wiki(kb_root=KB_ROOT, mode=mode, dry_run=dry_run)
    except Exception as exc:
        return f"Error during compile_wiki: {exc}"
    summary = report.summary()
    if getattr(report, "lint_summary", ""):
        summary += f"\n\nWiki health:\n{report.lint_summary}"
    if report.concepts_proposed:
        summary += (
            f"\n\n{report.concepts_proposed} low-confidence concept(s) were placed in the exception queue. "
            "They are excluded from brainstorm until the agent can merge, stabilize, or deprecate them."
        )
    return summary
```

- [ ] **Step 4: Run tests**

Run: `python3 -m unittest tests.test_agent_tools.CompileWikiToolTests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/tools.py tests/test_agent_tools.py
git commit -m "Add compile_wiki agent tool"
```

---

### Task D2: `list_concepts` agent tool

**Files:**
- Modify: `agent/tools.py`
- Modify: `tests/test_agent_tools.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_agent_tools.py`:

```python
class ListConceptsToolTests(unittest.TestCase):
    def test_list_concepts_filters_by_status(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from agent.tools import list_concepts as list_concepts_tool
        from wiki_seed import bootstrap_wiki

        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            bootstrap_wiki(wiki_dir)
            with patch("agent.tools.KB_ROOT", Path(tmp)):
                result = list_concepts_tool.invoke({"status": "stable"})
            self.assertIn("momentum-strategies", result)
            self.assertIn("(stable)", result)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_agent_tools.ListConceptsToolTests -v`
Expected: FAIL — `list_concepts` not exported.

- [ ] **Step 3: Append `list_concepts` tool**

Append to `agent/tools.py`:

```python
@tool
def list_concepts(status: str = "all") -> str:
    """List wiki concepts grouped by status.

    Status filter: 'all' (default), 'stable', 'proposed', or 'deprecated'.
    Returns a markdown list of concept slugs with title and source count.
    """
    from wiki_schemas import parse_concept
    if status not in ("all", "stable", "proposed", "deprecated"):
        return f"Invalid status filter '{status}'."
    cdir = KB_ROOT / "wiki" / "concepts"
    if not cdir.exists():
        return "Wiki not initialized — run compile_wiki first."

    rows: list[str] = []
    for md in sorted(cdir.glob("*.md")):
        try:
            c = parse_concept(md.read_text(encoding="utf-8"))
        except Exception:
            continue
        if status != "all" and c.status != status:
            continue
        rows.append(f"- {c.slug} — {c.title} ({c.status}) — {len(c.sources)} source(s)")
    if not rows:
        return f"No concepts match status='{status}'."
    return "\n".join(rows)
```

- [ ] **Step 4: Run tests**

Run: `python3 -m unittest tests.test_agent_tools.ListConceptsToolTests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/tools.py tests/test_agent_tools.py
git commit -m "Add list_concepts agent tool"
```

---

### Task D3: `set_concept_status` agent tool (escape hatch, not normal workflow)

**Files:**
- Modify: `agent/tools.py`
- Modify: `tests/test_agent_tools.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_agent_tools.py`:

```python
class SetConceptStatusToolTests(unittest.TestCase):
    def test_approve_proposed_to_stable(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from agent.tools import set_concept_status as set_status_tool
        from wiki_schemas import ConceptArticle, parse_concept, serialize_concept

        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            (wiki_dir / "concepts").mkdir(parents=True)
            (wiki_dir / "sources").mkdir(parents=True)
            proposed = ConceptArticle(
                title="X", slug="x-test", aliases=[], status="proposed",
                related_concepts=[], sources=[], content_types=[],
                last_compiled="2026-04-28", compile_version=0,
                synthesis="", definition="", key_idea_blocks=[], variants=[],
                common_combinations=[], transfer_targets=[], failure_modes=[],
                open_questions=[], source_basenames=[],
            )
            (wiki_dir / "concepts" / "x-test.md").write_text(serialize_concept(proposed), encoding="utf-8")

            with patch("agent.tools.KB_ROOT", Path(tmp)):
                result = set_status_tool.invoke(
                    {"slug": "x-test", "status": "stable", "reason": "approved"}
                )
            self.assertIn("stable", result)
            updated = parse_concept((wiki_dir / "concepts" / "x-test.md").read_text(encoding="utf-8"))
            self.assertEqual(updated.status, "stable")

    def test_delete_status_removes_file(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from agent.tools import set_concept_status as set_status_tool
        from wiki_schemas import ConceptArticle, serialize_concept

        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            (wiki_dir / "concepts").mkdir(parents=True)
            c = ConceptArticle(
                title="X", slug="x-test", aliases=[], status="proposed",
                related_concepts=[], sources=[], content_types=[],
                last_compiled="2026-04-28", compile_version=0,
                synthesis="", definition="", key_idea_blocks=[], variants=[],
                common_combinations=[], transfer_targets=[], failure_modes=[],
                open_questions=[], source_basenames=[],
            )
            (wiki_dir / "concepts" / "x-test.md").write_text(serialize_concept(c), encoding="utf-8")

            with patch("agent.tools.KB_ROOT", Path(tmp)):
                set_status_tool.invoke({"slug": "x-test", "status": "deleted", "reason": "rejected"})
            self.assertFalse((wiki_dir / "concepts" / "x-test.md").exists())

    def test_missing_slug_returns_error(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from agent.tools import set_concept_status as set_status_tool

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "wiki" / "concepts").mkdir(parents=True)
            with patch("agent.tools.KB_ROOT", Path(tmp)):
                result = set_status_tool.invoke({"slug": "missing", "status": "stable", "reason": "x"})
            self.assertIn("not found", result.lower())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_agent_tools.SetConceptStatusToolTests -v`
Expected: FAIL.

- [ ] **Step 3: Append `set_concept_status` tool**

Append to `agent/tools.py`:

```python
@tool
def set_concept_status(slug: str, status: str, reason: str = "") -> str:
    """Override a wiki concept status by slug.

    status:
    - 'stable'     — force a proposed concept into active use
    - 'deprecated' — mark concept as no longer used; kept on disk for traceability
    - 'deleted'    — remove the concept file entirely

    This is an admin/agent escape hatch. Normal wiki maintenance is handled by
    compile_wiki + audit_wiki using confidence, freshness, conflict, and source-hash checks.
    """
    from wiki_schemas import parse_concept, serialize_concept
    if status not in ("stable", "deprecated", "deleted"):
        return f"Invalid status '{status}'. Must be 'stable', 'deprecated', or 'deleted'."

    path = KB_ROOT / "wiki" / "concepts" / f"{slug}.md"
    if not path.exists():
        return f"Concept not found: {slug}"

    if status == "deleted":
        path.unlink()
        return f"Deleted concept: {slug}. Reason: {reason or '(none)'}"

    try:
        concept = parse_concept(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return f"Failed to parse concept: {exc}"
    concept.status = status
    path.write_text(serialize_concept(concept), encoding="utf-8")
    return f"Concept {slug} → {status}. Reason: {reason or '(none)'}"
```

- [ ] **Step 4: Run tests**

Run: `python3 -m unittest tests.test_agent_tools.SetConceptStatusToolTests -v`
Expected: PASS, 3 tests.

- [ ] **Step 5: Commit**

```bash
git add agent/tools.py tests/test_agent_tools.py
git commit -m "Add set_concept_status agent tool"
```

---

### Task D3.5: `audit_wiki` agent tool

**Files:**
- Modify: `agent/tools.py`
- Modify: `tests/test_agent_tools.py`

- [ ] **Step 1: Add tests**

Add a test that patches `wiki_lint.lint_wiki` and verifies `audit_wiki.invoke({})` returns the report summary.

- [ ] **Step 2: Implement tool**

Append to `agent/tools.py`:

```python
@tool
def audit_wiki() -> str:
    """Return the wiki health report used by the agent before relying on compiled memory."""
    import wiki_lint
    try:
        report = wiki_lint.lint_wiki(KB_ROOT)
    except Exception as exc:
        return f"Wiki audit failed: {exc}"
    return report.summary()
```

- [ ] **Step 3: Commit**

```bash
git add agent/tools.py tests/test_agent_tools.py
git commit -m "Add audit_wiki agent tool"
```

---

### Task D4: `read_wiki` agent tool

**Files:**
- Modify: `agent/tools.py`
- Modify: `tests/test_agent_tools.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_agent_tools.py`:

```python
class ReadWikiToolTests(unittest.TestCase):
    def test_read_index(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from agent.tools import read_wiki as read_wiki_tool
        from wiki_seed import bootstrap_wiki
        from wiki_index import write_index

        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            bootstrap_wiki(wiki_dir)
            write_index(wiki_dir)
            with patch("agent.tools.KB_ROOT", Path(tmp)):
                result = read_wiki_tool.invoke({"target": "index"})
            self.assertIn("# Knowledge Base Index", result)

    def test_read_concept_by_slug(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from agent.tools import read_wiki as read_wiki_tool
        from wiki_seed import bootstrap_wiki

        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            bootstrap_wiki(wiki_dir)
            with patch("agent.tools.KB_ROOT", Path(tmp)):
                result = read_wiki_tool.invoke({"target": "momentum-strategies"})
            self.assertIn("Momentum Strategies", result)

    def test_read_unknown_target(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from agent.tools import read_wiki as read_wiki_tool

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "wiki").mkdir(parents=True)
            with patch("agent.tools.KB_ROOT", Path(tmp)):
                result = read_wiki_tool.invoke({"target": "nonexistent"})
            self.assertIn("not found", result.lower())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_agent_tools.ReadWikiToolTests -v`
Expected: FAIL.

- [ ] **Step 3: Append `read_wiki` tool**

Append to `agent/tools.py`:

```python
@tool
def read_wiki(target: str) -> str:
    """Read a wiki entry by name.

    target:
    - 'index' — return the wiki INDEX.md
    - <concept-slug> — return wiki/concepts/<slug>.md
    - <source-id> — return wiki/sources/<source-id>.md (the article basename)
    """
    wiki_dir = KB_ROOT / "wiki"
    if not wiki_dir.exists():
        return "Wiki not initialized — run compile_wiki first."
    if target == "index":
        idx = wiki_dir / "INDEX.md"
        return idx.read_text(encoding="utf-8") if idx.exists() else "INDEX.md not found — run compile_wiki."

    concept_path = wiki_dir / "concepts" / f"{target}.md"
    if concept_path.exists():
        return concept_path.read_text(encoding="utf-8")

    source_path = wiki_dir / "sources" / f"{target}.md"
    if source_path.exists():
        return source_path.read_text(encoding="utf-8")

    return f"Wiki entry not found: {target}"
```

- [ ] **Step 4: Run tests**

Run: `python3 -m unittest tests.test_agent_tools.ReadWikiToolTests -v`
Expected: PASS, 3 tests.

- [ ] **Step 5: Commit**

```bash
git add agent/tools.py tests/test_agent_tools.py
git commit -m "Add read_wiki agent tool"
```

---

### Task D5: Register new tools and update prompts

**Files:**
- Modify: `agent/tools.py` (`ALL_TOOLS`)
- Modify: `agent/prompts.py`

- [ ] **Step 1: Add new tools to `ALL_TOOLS`**

In `agent/tools.py`, replace the `ALL_TOOLS` list at the bottom:

```python
ALL_TOOLS = [
    ingest_article,
    enrich_articles,
    list_articles,
    review_articles,
    set_article_status,
    sync_articles,
    embed_knowledge,
    query_knowledge_base,
    compile_wiki,
    audit_wiki,
    list_concepts,
    set_concept_status,
    read_wiki,
]
```

- [ ] **Step 2: Update `agent/prompts.py`**

Replace the contents of `agent/prompts.py` with:

```python
SYSTEM_PROMPT = """你是量化投研知识库管理助手。你管理一个完整的知识库流水线，包括文章抓取、LLM结构化增强、文章质量审核、向量索引、Wiki概念合成、Wiki健康审计和RAG问答/脑暴。

系统定位：
- 人类主要负责提供高价值原始材料，并评审最终脑暴/研究结果。
- Wiki层是给 agent 使用的结构化长期记忆，不要求用户在 Obsidian 中浏览或手动维护。
- 除非用户明确要求，或者 audit_wiki 报告严重冲突，不要把概念维护变成人工审批流程。

你可以使用以下工具：

1. **ingest_article** — 抓取文章并保存到 articles/raw/。支持多种输入：
   - url: 单个URL（自动识别 WeChat / 通用网页 / PDF）
   - urls: 多个URL（换行/逗号分隔）
   - url_list_file: URL 列表文件
   - html_file: 本地 HTML 文件（WeChat 风格）
   - pdf_file: 本地 PDF 文件
   - pdf_url: 远程 PDF URL
2. **enrich_articles** — 对原始文章进行 LLM 结构化增强（生成 idea_blocks 等字段）
3. **list_articles** — 列出各阶段文章
4. **review_articles** — 展示待审核文章
5. **set_article_status** — 批量更新文章状态
6. **sync_articles** — 根据状态移动文章
7. **embed_knowledge** — 构建/更新 ChromaDB 向量索引（同时索引 wiki/）
8. **query_knowledge_base** — 问答(ask) / 脑暴(brainstorm)。Brainstorm 自动优先使用 wiki 概念记忆
9. **compile_wiki** — 由文章合成 wiki 概念文章和 source 摘要。模式: incremental（默认）/ rebuild
10. **audit_wiki** — 检查 wiki 记忆健康度、冲突、过期、孤立概念和低置信异常
11. **list_concepts** — 列出 wiki 概念，按状态筛选（stable / proposed / deprecated）
12. **set_concept_status** — 管理员/agent 兜底工具：强制稳定 / 弃用 / 删除概念
13. **read_wiki** — 读取 INDEX、概念文章或 source 摘要

## Wiki 层使用指南

- **"解释 X" / "梳理 Y" / "总结知识库对 Z 怎么说"** → 优先使用 query_knowledge_base 或 read_wiki 读取相关概念；不要把整篇 wiki 无选择地塞入上下文
- **"脑暴" / "组合想法" / "新策略"** → query_knowledge_base(mode='brainstorm')。它会自动优先检索高分 wiki 概念，再找互补文章
- **"wiki 状态" / "记忆健康" / "是否漂移"** → audit_wiki
- **"找包含 X 的文章" / "做新颖度检查"** → query_knowledge_base(mode='ask')

## 典型工作流

### 完整入库流程
ingest_article → enrich_articles → review_articles → set_article_status → sync_articles → compile_wiki → embed_knowledge

注意：compile_wiki 在 sync_articles 之后运行，它读取 reviewed/ 与 high-value/ 下的文章。embed_knowledge 在 compile_wiki 之后运行，使新合成的 wiki 内容也进入向量索引。

### Wiki 自维护流程
compile_wiki 后自动运行 audit_wiki。正常情况下，agent 自主处理高置信概念合成、低价值概念忽略、重复概念合并建议和过期概念降权。只有当 audit_wiki 出现 error 级别问题，或用户明确要求人工干预时，才使用 list_concepts / set_concept_status。

## 规则
- 用用户使用的语言回复（中文或英文）
- 报告结果时清晰简洁，不要编造
- 链式操作时，每步完成后报告结果再继续下一步
- 当用户请求完整入库、同步、重建索引或脑暴时，可以自动执行必要链路，但要在关键步骤报告结果
"""
```

- [ ] **Step 3: Run agent graph tests to ensure no regression**

Run: `python3 -m unittest tests.test_agent_graph -v`
Expected: PASS (or no new failures vs baseline).

- [ ] **Step 4: Commit**

```bash
git add agent/tools.py agent/prompts.py
git commit -m "Register wiki memory tools and update agent system prompt"
```

---

### Task D6: Embed wiki into ChromaDB

**Files:**
- Modify: `embed_knowledge_base.py` (extend to also index wiki/)
- Modify: `tests/test_embed_knowledge_base.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_embed_knowledge_base.py`:

```python
class EmbedWikiTests(unittest.TestCase):
    def test_block_metadata_includes_kb_layer(self) -> None:
        from kb_shared import KnowledgeNote, KnowledgeBlock
        note = KnowledgeNote(
            article_dir=Path("a"), source_dir="reviewed",
            frontmatter={"content_type": "methodology", "brainstorm_value": "high"},
            body="",
        )
        block = KnowledgeBlock(note=note, block_type="summary", text="t", score=0.0)
        meta = mod.block_metadata(block, kb_layer="article")
        self.assertEqual(meta["kb_layer"], "article")

    def test_iter_wiki_blocks_yields_concept_and_source(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            from wiki_seed import bootstrap_wiki
            wiki_dir = Path(tmp) / "wiki"
            bootstrap_wiki(wiki_dir)
            blocks = list(mod.iter_wiki_blocks(wiki_dir))
            # 7 seed concepts, each yields at least 1 block (definition/synthesis)
            self.assertGreaterEqual(len(blocks), 7)
            kinds = {b.block_type for b in blocks}
            self.assertIn("wiki_concept", kinds)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_embed_knowledge_base.EmbedWikiTests -v`
Expected: FAIL.

- [ ] **Step 3: Update `embed_knowledge_base.py`**

Modify `block_metadata` to accept `kb_layer`:

```python
def block_metadata(block: KnowledgeBlock, kb_layer: str = "article") -> dict[str, str]:
    frontmatter = block.note.frontmatter
    return {
        "article_dir": str(block.note.article_dir),
        "source_dir": block.note.source_dir,
        "content_type": str(frontmatter.get("content_type", "")),
        "brainstorm_value": str(frontmatter.get("brainstorm_value", "")),
        "block_type": block.block_type,
        "kb_layer": kb_layer,
    }
```

Add a wiki block iterator at the bottom of `embed_knowledge_base.py`:

```python
def iter_wiki_blocks(wiki_dir: Path):
    """Yield KnowledgeBlock objects for each wiki concept article and source summary."""
    from kb_shared import KnowledgeNote
    from wiki_schemas import parse_concept, parse_source_summary

    cdir = wiki_dir / "concepts"
    if cdir.exists():
        for md in sorted(cdir.glob("*.md")):
            try:
                concept = parse_concept(md.read_text(encoding="utf-8"))
            except Exception:
                continue
            note = KnowledgeNote(
                article_dir=md,
                source_dir="wiki_concepts",
                frontmatter={
                    "title": concept.title,
                    "content_type": concept.content_types[0] if concept.content_types else "",
                    "brainstorm_value": "high",
                    "slug": concept.slug,
                },
                body="",
            )
            text = "\n\n".join(filter(None, [
                concept.synthesis,
                concept.definition,
                "\n".join(concept.key_idea_blocks),
                "\n".join(concept.variants),
                "\n".join(concept.common_combinations),
                "\n".join(concept.transfer_targets),
                "\n".join(concept.failure_modes),
            ]))
            if text.strip():
                yield KnowledgeBlock(note=note, block_type="wiki_concept", text=text, score=0.0)

    sdir = wiki_dir / "sources"
    if sdir.exists():
        for md in sorted(sdir.glob("*.md")):
            try:
                summary = parse_source_summary(md.read_text(encoding="utf-8"))
            except Exception:
                continue
            note = KnowledgeNote(
                article_dir=md,
                source_dir="wiki_sources",
                frontmatter={
                    "title": summary.title,
                    "content_type": summary.content_type,
                    "brainstorm_value": summary.brainstorm_value,
                },
                body="",
            )
            text = " · ".join(filter(None, [summary.takeaway] + summary.top_idea_blocks))
            if text.strip():
                yield KnowledgeBlock(note=note, block_type="wiki_source", text=text, score=0.0)
```

Then in `main()` (after the article loop, before `save_manifest`), add wiki indexing:

```python
    # Index wiki/ entries
    from kb_shared import WIKI_DIR
    wiki_dir = WIKI_DIR if Path(WIKI_DIR).exists() else None
    if wiki_dir and not args.dry_run and collection is not None:
        for block in iter_wiki_blocks(wiki_dir):
            try:
                wiki_id = make_block_id(kb_root, block, 0)
                collection.upsert(
                    ids=[wiki_id],
                    documents=[block.text],
                    metadatas=[block_metadata(block, kb_layer=block.block_type)],
                    embeddings=[embed_text(block.text)],
                )
            except Exception as exc:
                failures.append({"article_dir": str(block.note.article_dir), "error": str(exc)})
```

- [ ] **Step 4: Run tests**

Run: `python3 -m unittest tests.test_embed_knowledge_base -v`
Expected: PASS for all tests.

- [ ] **Step 5: Commit**

```bash
git add embed_knowledge_base.py tests/test_embed_knowledge_base.py
git commit -m "Embed wiki concepts and source summaries into ChromaDB with kb_layer metadata"
```

---

## Phase E: Brainstorm Integration

Brainstorm retrieval must be token-aware and score-aware. Do not load whole wiki pages when a compact concept memory block is enough. The normal path should be:

1. Retrieve `wiki_concept` blocks from Chroma filtered by `kb_layer=wiki_concept` and `status=stable`.
2. Re-rank using `wiki/state.json` memory score: semantic similarity + confidence + importance + freshness - conflict penalty.
3. Inject only compact concept sections needed for the query.
4. Retrieve complementary article blocks, excluding raw sources already represented by selected concepts unless the query asks for source-level detail.
5. Fall back to article-only hybrid retrieval when the wiki is sparse or unhealthy.

### Task E1: Concept-first retrieval in brainstorm_from_kb.py

**Files:**
- Modify: `brainstorm_from_kb.py`
- Create: `tests/test_brainstorm_with_wiki.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_brainstorm_with_wiki.py`:

```python
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import brainstorm_from_kb


class BrainstormWithWikiTests(unittest.TestCase):
    def test_retrieve_concepts_first_when_wiki_has_stable(self) -> None:
        from wiki_seed import bootstrap_wiki

        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            bootstrap_wiki(wiki_dir)
            with patch.object(brainstorm_from_kb, "WIKI_DIR", wiki_dir):
                concepts = brainstorm_from_kb._retrieve_concept_articles(
                    "How to combine momentum and regime detection?",
                    top_k=2,
                )
            self.assertGreater(len(concepts), 0)
            self.assertTrue(all("title" in c for c in concepts))

    def test_retrieve_concepts_returns_empty_when_wiki_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(brainstorm_from_kb, "WIKI_DIR", Path(tmp) / "no-wiki"):
                concepts = brainstorm_from_kb._retrieve_concept_articles("query", top_k=3)
            self.assertEqual(concepts, [])

    def test_format_context_distinguishes_wiki_from_article(self) -> None:
        from kb_shared import KnowledgeBlock, KnowledgeNote
        wiki_block = KnowledgeBlock(
            note=KnowledgeNote(
                article_dir=Path("wiki/concepts/momentum.md"),
                source_dir="wiki_concepts",
                frontmatter={"title": "Momentum", "kb_layer": "wiki_concept"},
                body="",
            ),
            block_type="wiki_concept", text="t", score=0.0,
        )
        article_block = KnowledgeBlock(
            note=KnowledgeNote(
                article_dir=Path("articles/reviewed/x"),
                source_dir="reviewed",
                frontmatter={"title": "X"},
                body="",
            ),
            block_type="idea_blocks", text="t", score=0.0,
        )
        ctx = brainstorm_from_kb.format_context([wiki_block, article_block])
        self.assertIn("[Wiki Concept]", ctx)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_brainstorm_with_wiki -v`
Expected: FAIL.

- [ ] **Step 3: Modify `brainstorm_from_kb.py`**

Near the top, add the import:

```python
from kb_shared import WIKI_DIR
from wiki_schemas import parse_concept
```

Add the concept retrieval helper (place it before `retrieve_blocks`):

```python
DEFAULT_CONCEPT_TOP_K = 3


def _retrieve_concept_articles(query: str, top_k: int = DEFAULT_CONCEPT_TOP_K) -> list[dict]:
    """Retrieve top-K stable wiki concepts.

    Preferred path: Chroma vector search filtered to kb_layer=wiki_concept,
    reranked by wiki/state.json memory_score. Fallback: query-vs-title/aliases
    lexical match when Chroma or state is unavailable.

    Returns compact dicts: {slug, title, sources, body_text, memory_score}.
    """
    cdir = WIKI_DIR / "concepts"
    if not cdir.exists():
        return []
    candidates = []
    for md in cdir.glob("*.md"):
        try:
            c = parse_concept(md.read_text(encoding="utf-8"))
        except Exception:
            continue
        if c.status != "stable":
            continue
        candidates.append(c)
    if not candidates:
        return []

    # Fallback lexical retrieval. Keep this path small and deterministic for tests;
    # production retrieval should use vector + state reranking when available.
    q_tokens = tokenize(query)
    scored = []
    for c in candidates:
        text_for_score = " ".join([c.title] + c.aliases + [c.definition[:200]])
        c_tokens = tokenize(text_for_score)
        overlap = len(q_tokens & c_tokens)
        if overlap > 0:
            scored.append((overlap, c))
    scored.sort(key=lambda kv: kv[0], reverse=True)

    out = []
    for _, c in scored[:top_k]:
        body = "\n\n".join(filter(None, [
            c.synthesis,
            c.definition,
            "\n".join(c.key_idea_blocks),
            "Combinations: " + "; ".join(c.common_combinations) if c.common_combinations else "",
            "Transfer Targets: " + "; ".join(c.transfer_targets) if c.transfer_targets else "",
            "Failure Modes: " + "; ".join(c.failure_modes) if c.failure_modes else "",
        ]))
        out.append({
            "slug": c.slug,
            "title": c.title,
            "sources": c.sources,
            "body_text": body,
        })
    return out
```

Then modify `format_context` to handle wiki blocks (replace existing function):

```python
def format_context(blocks: list[KnowledgeBlock]) -> str:
    chunks: list[str] = []
    for index, block in enumerate(blocks, start=1):
        is_wiki = block.block_type in ("wiki_concept", "wiki_source")
        label = "Wiki Concept" if block.block_type == "wiki_concept" else (
            "Wiki Source Summary" if block.block_type == "wiki_source" else "Article"
        )
        chunks.append(
            "\n".join(
                [
                    f"[Context {index}] [{label}]",
                    f"Title: {block.note.title}",
                    f"Path: {block.note.article_dir}",
                    f"Block Type: {block.block_type}",
                    f"Content: {block.text}",
                ]
            )
        )
    return "\n\n".join(chunks)
```

- [ ] **Step 4: Run tests**

Run: `python3 -m unittest tests.test_brainstorm_with_wiki -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add brainstorm_from_kb.py tests/test_brainstorm_with_wiki.py
git commit -m "Add concept-first retrieval and wiki-aware context formatting"
```

---

### Task E2: Wire concept retrieval into `query_knowledge_base`

**Files:**
- Modify: `brainstorm_from_kb.py` (add `_concepts_to_blocks`, modify retrieve_blocks for brainstorm path)
- Modify: `tests/test_brainstorm_with_wiki.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_brainstorm_with_wiki.py`:

```python
class BrainstormFlowTests(unittest.TestCase):
    def test_brainstorm_uses_concepts_when_wiki_has_stable(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from wiki_seed import bootstrap_wiki
        import brainstorm_from_kb

        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            bootstrap_wiki(wiki_dir)
            with patch.object(brainstorm_from_kb, "WIKI_DIR", wiki_dir):
                blocks = brainstorm_from_kb._concepts_to_blocks(
                    "momentum risk", top_k=2,
                )
            self.assertGreater(len(blocks), 0)
            self.assertEqual(blocks[0].block_type, "wiki_concept")

    def test_brainstorm_falls_back_to_pure_vector_when_wiki_empty(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import brainstorm_from_kb

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(brainstorm_from_kb, "WIKI_DIR", Path(tmp) / "no-wiki"):
                blocks = brainstorm_from_kb._concepts_to_blocks("q", top_k=3)
            self.assertEqual(blocks, [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_brainstorm_with_wiki.BrainstormFlowTests -v`
Expected: FAIL.

- [ ] **Step 3: Append `_concepts_to_blocks` and integrate**

Append to `brainstorm_from_kb.py`:

```python
def _concepts_to_blocks(query: str, top_k: int = DEFAULT_CONCEPT_TOP_K) -> list[KnowledgeBlock]:
    """Convert retrieved concept articles to KnowledgeBlock objects for context."""
    concepts = _retrieve_concept_articles(query, top_k=top_k)
    if not concepts:
        return []
    blocks: list[KnowledgeBlock] = []
    for c in concepts:
        note = KnowledgeNote(
            article_dir=WIKI_DIR / "concepts" / f"{c['slug']}.md",
            source_dir="wiki_concepts",
            frontmatter={"title": c["title"], "content_type": ""},
            body="",
        )
        blocks.append(KnowledgeBlock(
            note=note,
            block_type="wiki_concept",
            text=c["body_text"],
            score=1.0,
        ))
    return blocks
```

Modify `retrieve_blocks` to prepend wiki concept blocks when `command == "brainstorm"`. Locate the existing `retrieve_blocks` function and replace its body with:

```python
def retrieve_blocks(
    notes: list[KnowledgeNote],
    query: str,
    top_k: int,
    command: str,
    retrieval_mode: str,
    vector_store_dir: Path | None = None,
) -> tuple[list[KnowledgeBlock], str, str | None]:
    candidate_k = max(top_k * 2, top_k)
    keyword_blocks = _keyword_candidates(notes, query, candidate_k, command)

    # Brainstorm: try wiki-concept-first retrieval
    wiki_blocks: list[KnowledgeBlock] = []
    if command == "brainstorm":
        wiki_blocks = _concepts_to_blocks(query, top_k=DEFAULT_CONCEPT_TOP_K)

    # Determine excluded source paths (already covered by retrieved wiki concepts)
    excluded_articles: set[str] = set()
    if wiki_blocks:
        # Each wiki block's note.article_dir points to the concept md, but
        # the concept's `sources` field lists actual article paths.
        for c in _retrieve_concept_articles(query, top_k=DEFAULT_CONCEPT_TOP_K):
            for src_path in c["sources"]:
                excluded_articles.add(str(Path(src_path).parent))

    if retrieval_mode == "keyword":
        article_blocks = [
            b for b in keyword_blocks
            if str(b.note.article_dir) not in excluded_articles
        ][:max(0, top_k - len(wiki_blocks))]
        return wiki_blocks + article_blocks, "keyword", None

    store_dir = vector_store_dir or VECTOR_STORE_DIR
    try:
        vector_blocks = _vector_retrieve(notes, query, candidate_k, command, store_dir)
    except Exception as exc:
        warning = f"{retrieval_mode} retrieval fell back to keyword: {exc}"
        article_blocks = [
            b for b in keyword_blocks
            if str(b.note.article_dir) not in excluded_articles
        ][:max(0, top_k - len(wiki_blocks))]
        return wiki_blocks + article_blocks, "keyword", warning

    # Filter vector blocks to exclude already-cited sources
    vector_blocks = [b for b in vector_blocks if str(b.note.article_dir) not in excluded_articles]

    if retrieval_mode == "vector":
        if vector_blocks:
            sliced = vector_blocks[:max(0, top_k - len(wiki_blocks))]
            return wiki_blocks + sliced, "vector", None
        return wiki_blocks + keyword_blocks[:top_k], "keyword", "vector retrieval returned no results; fell back to keyword"

    if not vector_blocks:
        return wiki_blocks + keyword_blocks[:max(0, top_k - len(wiki_blocks))], "keyword", \
            "hybrid retrieval fell back to keyword because vector retrieval returned no results"

    fused = _rrf_fusion(keyword_blocks, vector_blocks, max(0, top_k - len(wiki_blocks)))
    if not fused:
        return wiki_blocks + keyword_blocks[:max(0, top_k - len(wiki_blocks))], "keyword", \
            "hybrid retrieval fell back to keyword because fusion returned no results"
    return wiki_blocks + fused, "hybrid", None
```

- [ ] **Step 4: Run tests**

Run: `python3 -m unittest tests.test_brainstorm_with_wiki -v`
Expected: PASS.

Run also: `python3 -m unittest tests.test_brainstorm_from_kb -v` (existing test file)
Expected: PASS — no regression in existing brainstorm tests.

- [ ] **Step 5: Commit**

```bash
git add brainstorm_from_kb.py tests/test_brainstorm_with_wiki.py
git commit -m "Wire concept-first retrieval into brainstorm with source exclusion"
```

---

## Phase F: Documentation & Acceptance

### Task F1: Update README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the Architecture section**

In the "Pipeline Flow" code block (around line 42-68), insert a new step after `[5. Sync]` and before `[6. Embed]`:

```
  [5.5 Compile Wiki] ──> wiki/concepts/<concept>.md + wiki/sources/<article>.md + wiki/state.json
        |               (agent-maintained memory: hashes, scores, freshness, conflicts)
        v
  [6. Embed]  ──> Build ChromaDB vector index (articles + wiki entries with kb_layer metadata)
```

- [ ] **Step 2: Update Agent Layer table**

Replace the existing 8-row table with 13 rows:

```markdown
| Tool | Description |
|------|-------------|
| `ingest_article` | Ingest from URL (auto-detects WeChat/web/PDF), batch URLs, URL list, HTML, PDF file, or PDF URL |
| `enrich_articles` | LLM-powered structured enrichment (concurrent, with `limit` support) |
| `list_articles` | List articles by stage (raw/reviewed/high-value) |
| `review_articles` | Show enriched articles ready for review (filters unenriched by default) |
| `set_article_status` | Batch update article status (`reviewed`, `high_value`, or `rejected`) |
| `sync_articles` | Move articles based on frontmatter status; deletes rejected articles |
| `embed_knowledge` | Build/update ChromaDB vector index over articles + wiki |
| `query_knowledge_base` | RAG Q&A or brainstorm with Rethink Layer (brainstorm uses wiki concepts first) |
| `compile_wiki` | Compile/update LLM-maintained wiki (incremental or rebuild) |
| `audit_wiki` | Report wiki memory health, stale concepts, conflicts, orphan links, and low-confidence exceptions |
| `list_concepts` | List wiki concepts by status (stable / proposed / deprecated) |
| `set_concept_status` | Admin/agent escape hatch to stabilize, deprecate, or delete a concept |
| `read_wiki` | Read INDEX, a concept article, or a source summary |
```

- [ ] **Step 3: Add a "Wiki Layer" section after "Rethink Layer"**

Insert a new section before "## File Structure":

```markdown
### Wiki Layer

The wiki layer is an agent-maintained memory system synthesized from your articles. Markdown files remain inspectable, but the operational memory lives in `wiki/state.json` and Chroma metadata.

- `wiki/concepts/<slug>.md` — concept articles (e.g. `momentum-strategies.md`) that synthesize across multiple sources. Each has a `## Synthesis`, `## Definition`, and structured sections (Idea Blocks, Combinations, Transfer Targets, Failure Modes, etc.).
- `wiki/sources/<article-id>.md` — short summaries of each raw article (mechanically derived from frontmatter; no extra LLM calls).
- `wiki/state.json` — machine-readable state: source hashes, concept confidence, importance, freshness, conflict list, retrieval hints, and memory scores.
- `wiki/INDEX.md` — compact routing index for the agent.
- `wiki/lint_report.json` — latest health report from `audit_wiki`.

**Lifecycle:** `compile_wiki` runs after `sync_articles`. New articles either map to existing concepts or create/merge/deprecate concepts autonomously based on confidence, source support, and lint checks. `proposed` is reserved for low-confidence exceptions, not routine human approval. The seed taxonomy seeds 7 starter concepts (factor-models, factor-timing, regime-detection, momentum-strategies, etf-rotation, risk-parity, volatility-targeting).

**Brainstorm impact:** When you run brainstorm queries, the agent retrieves high-scoring concept memory first, then complementary raw-article chunks via vector search. It excludes sources already represented by selected concepts unless source-level evidence is needed. If the wiki is sparse, stale, or unhealthy, brainstorm falls back to the pure-vector article path.
```

- [ ] **Step 4: Update File Structure tree**

Add the new top-level files and the wiki directory to the tree near line 96-141:

```
QuantRAGForge/
├── agent/
├── articles/
├── wiki/                          # LLM-maintained synthesized knowledge
│   ├── INDEX.md
│   ├── state.json
│   ├── lint_report.json
│   ├── concepts/                  # one .md per concept
│   └── sources/                   # one .md per raw article (short summary)
├── _wechat.py                     # WeChat extraction (used by ingest_source)
├── _web_extract.py                # Generic web extraction (trafilatura)
├── _pdf_extract.py                # PDF extraction (pypdf)
├── _code_math.py                  # Code/math preservation utilities
├── ingest_source.py               # Unified ingest entrypoint
├── wiki_schemas.py                # ConceptArticle, SourceSummary schemas
├── wiki_seed.py                   # Seed taxonomy + bootstrap
├── wiki_compile.py                # compile_wiki orchestrator
├── wiki_compile_llm.py            # assign_concepts, recompile_concept
├── wiki_index.py                  # INDEX.md generator
├── wiki_state.py                  # machine-readable memory state
├── wiki_lint.py                   # health checks and conflict reporting
├── ...
```

- [ ] **Step 5: Update the example agent workflow**

Replace the example workflow block (around line 232-254) with:

```
You: ingest these articles: url1, url2, url3
Agent: 3/3 ingested.

You: enrich them
Agent: [1/3] ok  [2/3] ok  [3/3] ok — Enriched 3/3 articles.

You: review the new articles
Agent: [shows enriched articles]

You: set 1 and 3 as high_value, 2 as rejected
Agent: Updated 3 articles.

You: sync, compile wiki, then embed
Agent: Synced 2 (1 deleted).
       compile_wiki: 2 sources, 2 concepts recompiled, 0 blocking issues.
       audit_wiki: ok for brainstorm; 1 low-confidence concept kept out of active retrieval.
       Embedded 2 articles + 8 wiki entries.

You: brainstorm: how to combine momentum and regime detection
Agent: [generates ideas, citing wiki/concepts/momentum-strategies.md and wiki/concepts/regime-detection.md plus 2 complementary articles]
```

- [ ] **Step 6: Add design principles bullet**

In "## Design Principles" near line 319, add:

```markdown
- **Agent-first compiled wiki layer** — LLM synthesizes raw articles into scored concept memory; brainstorm queries pull selective, high-confidence concepts first
- **CLI-first ingest** — Web, WeChat, and PDF sources all ingest via the same CLI / agent tool, no browser extension required
- **Human focus stays downstream** — humans supply valuable raw material and review brainstorm/research outputs; routine wiki maintenance is automated
```

- [ ] **Step 7: Commit**

```bash
git add README.md
git commit -m "Update README for agent-first wiki layer and multi-source ingest"
```

---

### Task F2: Manual acceptance test

**Files:**
- Create: `docs/superpowers/plans/acceptance-checklist.md`

- [ ] **Step 1: Write the acceptance checklist**

Create `docs/superpowers/plans/acceptance-checklist.md`:

```markdown
# Wiki LLM KB Integration — Acceptance Checklist

Run this checklist after the implementation is complete and tests pass. The checks focus on agent usability and memory correctness, not Obsidian visualization or routine human concept curation.

## Setup
- [ ] `pip install -r requirements.txt` succeeds
- [ ] `python3 -m unittest discover -s tests -p 'test_*.py' -v` passes

## 1. Bootstrap wiki
- [ ] Run: `python3 -c "from wiki_seed import bootstrap_wiki; from kb_shared import WIKI_DIR; bootstrap_wiki(WIKI_DIR)"`
- [ ] Verify: `ls wiki/concepts/` shows 7 .md files
- [ ] Verify: each stub has `status: stable` and `compile_version: 0`

## 2. Compile wiki over existing corpus
- [ ] Run: `python3 -c "import wiki_compile; r = wiki_compile.compile_wiki(); print(r.summary())"`
- [ ] Verify: ≥ 5 of the 7 seed concepts have non-empty `## Synthesis` sections
- [ ] Verify: ≥ 80% of articles in `articles/{reviewed,high-value}/` have a `wiki/sources/<basename>.md` file
- [ ] Verify: `wiki/state.json` contains source hashes, concept scores, freshness, confidence, and retrieval hints
- [ ] Verify: `wiki/lint_report.json` exists and `audit_wiki` reports whether the wiki is ok for brainstorm
- [ ] Verify: `wiki/INDEX.md` is a compact routing index for the agent

## 3. New web URL ingest
- [ ] Pick a non-WeChat blog post about momentum (e.g. an arxiv abstract page or quant blog)
- [ ] Run: `python3 ingest_source.py --url "<URL>"`
- [ ] Verify: `articles/raw/<dir>/article.md` exists with `source_type: web`
- [ ] Run agent flow: enrich → review article quality → set high_value → sync → compile_wiki → audit_wiki
- [ ] Verify: the new article is added to `momentum-strategies.md`'s sources list

## 4. PDF ingest
- [ ] Pick a broker report PDF (or the test fixture)
- [ ] Run: `python3 ingest_source.py --pdf-file <path>`
- [ ] Verify: `articles/raw/<dir>/article.md` with `source_type: pdf`, `has_code` and `has_math` set appropriately
- [ ] Verify: `source.pdf` is preserved alongside

## 5. Brainstorm improvement
- [ ] Run: `python3 brainstorm_from_kb.py brainstorm --query "How to combine momentum factor with regime detection for ETF rotation?"`
- [ ] Verify output includes `[Wiki Concept]` markers in retrieved sources
- [ ] Verify ≥ 2 high-scoring wiki concepts cited in `Inspired By`
- [ ] Verify selected concepts are compact enough for context and do not dump entire wiki pages
- [ ] Verify rethink layer still produces novelty + quality scores

## 6. Autonomous concept lifecycle
- [ ] Ingest an article on a topic outside the seed taxonomy (e.g. "options volatility surface")
- [ ] Run compile_wiki
- [ ] Verify high-confidence concepts are stabilized automatically when source-supported
- [ ] Verify low-confidence or conflicting concepts are excluded from active retrieval and reported by `audit_wiki`
- [ ] Verify `set_concept_status` is only needed as an explicit override, not as a normal approval step

## 7. Idempotency
- [ ] Run compile_wiki twice with no article changes
- [ ] Verify the second run reports 0 LLM calls
- [ ] Change one article and rerun compile_wiki
- [ ] Verify only affected concepts are recompiled according to `wiki/state.json` source hashes
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/acceptance-checklist.md
git commit -m "Add manual acceptance checklist"
```

---

## Final Verification

- [ ] **Step 1: Run full test suite**

Run: `python3 -m unittest discover -s tests -p 'test_*.py' -v`
Expected: all tests pass.

- [ ] **Step 2: Run robustness suite**

Run: `python3 -m unittest discover -s tests/robustness -p 'test_*.py' -v`
Expected: all tests pass.

- [ ] **Step 3: Smoke test the agent CLI**

Run: `python3 agent_cli.py --query "audit wiki memory health"`
Expected: agent invokes `audit_wiki` and returns whether compiled memory is safe for brainstorm.

- [ ] **Step 4: Final commit if any docs/cleanup**

If anything was tweaked during smoke test, commit it now.
