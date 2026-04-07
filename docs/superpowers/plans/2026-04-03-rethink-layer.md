# Rethink Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a post-generation rethink layer that checks brainstorm idea novelty against the vector store and scores quality (traceability, coherence, actionability) before appending a Rethink Report to the output.

**Architecture:** A new `rethink_layer.py` module with a single entry point `rethink()` that parses LLM brainstorm output into ideas, checks each for novelty via ChromaDB embedding similarity, scores quality via heuristics + one LLM call, and returns the original output with an appended Rethink Report section. Integrated at two call sites: `brainstorm_from_kb.py:main()` and `agent/tools.py:query_knowledge_base()`.

**Tech Stack:** Python 3, ChromaDB (optional — graceful degradation), OpenAI-compatible LLM API via `kb_shared.py`, unittest.

---

## File Structure

| File | Responsibility |
|------|---------------|
| `rethink_layer.py` (create) | Idea parsing, novelty check, quality scoring, report building, `rethink()` entry point |
| `tests/test_rethink_layer.py` (create) | Unit tests for all rethink_layer functions |
| `brainstorm_from_kb.py` (modify lines 394-396) | Call `rethink()` after LLM generation in brainstorm mode |
| `agent/tools.py` (modify lines 375-387) | Call `rethink()` after LLM generation in brainstorm mode |

---

### Task 1: Idea Parsing — Tests

**Files:**
- Create: `tests/test_rethink_layer.py`

- [ ] **Step 1: Write tests for `parse_ideas()`**

```python
import unittest

from rethink_layer import BrainstormIdea, parse_ideas


class ParseIdeasTests(unittest.TestCase):
    WELL_FORMED = (
        "### Idea Title\n动量+波动率组合策略\n\n"
        "**Inspired By**\n[Context 1] 动量因子, [Context 2] 波动率择时\n\n"
        "**Core Combination Logic**\n将动量信号与波动率状态结合\n\n"
        "**What Is New**\n之前没有将两者在择时维度组合\n\n"
        "**Why It Might Make Sense**\n动量在低波时更稳定\n\n"
        "**What Could Break**\n高波环境下动量反转\n\n"
        "**Possible Variants**\n可以换成其他趋势信号\n"
    )

    TWO_IDEAS = (
        "### Idea Title\n想法A\n\n"
        "**Inspired By**\n来源A\n\n"
        "**Core Combination Logic**\n逻辑A\n\n"
        "**What Is New**\n新点A\n\n"
        "**Why It Might Make Sense**\n理由A\n\n"
        "**What Could Break**\n风险A\n\n"
        "**Possible Variants**\n变体A\n\n"
        "### Idea Title\n想法B\n\n"
        "**Inspired By**\n来源B\n\n"
        "**Core Combination Logic**\n逻辑B\n\n"
        "**What Is New**\n新点B\n\n"
        "**Why It Might Make Sense**\n理由B\n\n"
        "**What Could Break**\n风险B\n\n"
        "**Possible Variants**\n变体B\n"
    )

    def test_parse_single_idea(self) -> None:
        ideas = parse_ideas(self.WELL_FORMED)
        self.assertEqual(len(ideas), 1)
        self.assertEqual(ideas[0].title, "动量+波动率组合策略")
        self.assertEqual(ideas[0].inspired_by, "[Context 1] 动量因子, [Context 2] 波动率择时")
        self.assertEqual(ideas[0].core_logic, "将动量信号与波动率状态结合")
        self.assertEqual(ideas[0].what_is_new, "之前没有将两者在择时维度组合")

    def test_parse_multiple_ideas(self) -> None:
        ideas = parse_ideas(self.TWO_IDEAS)
        self.assertEqual(len(ideas), 2)
        self.assertEqual(ideas[0].title, "想法A")
        self.assertEqual(ideas[1].title, "想法B")

    def test_parse_empty_returns_empty(self) -> None:
        ideas = parse_ideas("")
        self.assertEqual(ideas, [])

    def test_parse_unstructured_returns_empty(self) -> None:
        ideas = parse_ideas("This is just a paragraph with no structure.")
        self.assertEqual(ideas, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/ubuntu/project/knowledge && .venv/bin/python3 -m unittest tests.test_rethink_layer -v`
Expected: `ModuleNotFoundError: No module named 'rethink_layer'`

---

### Task 2: Idea Parsing — Implementation

**Files:**
- Create: `rethink_layer.py`

- [ ] **Step 1: Implement `BrainstormIdea` and `parse_ideas()`**

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import chromadb
except ImportError:
    chromadb = None

from kb_shared import (
    ROOT,
    KnowledgeBlock,
    call_llm_chat,
    embed_text,
    get_llm_config,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NOVELTY_THRESHOLD = 0.75
NOVELTY_TOP_K = 5
TRACEABILITY_WEIGHT = 0.30
COHERENCE_WEIGHT = 0.35
ACTIONABILITY_WEIGHT = 0.35
DEFAULT_SCORE_ON_FAILURE = 0.5
VECTOR_STORE_DIR = ROOT / "vector_store"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class BrainstormIdea:
    title: str
    inspired_by: str
    core_logic: str
    what_is_new: str
    why_it_might_work: str
    what_could_break: str
    possible_variants: str
    raw_text: str


@dataclass
class NoveltyResult:
    is_novel: bool
    top_match_title: str = ""
    top_match_path: str = ""
    top_match_score: float = 0.0
    all_matches: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class QualityScore:
    traceability: float
    coherence: float
    actionability: float
    composite: float
    coherence_reasoning: str = ""
    actionability_reasoning: str = ""


# ---------------------------------------------------------------------------
# Idea parsing
# ---------------------------------------------------------------------------

_IDEA_SPLIT_RE = re.compile(r"(?=^###\s+Idea\s+Title\b)", re.MULTILINE)

_FIELD_PATTERNS: list[tuple[str, str]] = [
    ("title", r"###\s+Idea\s+Title\s*\n(.+?)(?:\n|$)"),
    ("inspired_by", r"\*\*Inspired\s+By\*\*\s*\n([\s\S]+?)(?=\n\*\*|$)"),
    ("core_logic", r"\*\*Core\s+Combination\s+Logic\*\*\s*\n([\s\S]+?)(?=\n\*\*|$)"),
    ("what_is_new", r"\*\*What\s+Is\s+New\*\*\s*\n([\s\S]+?)(?=\n\*\*|$)"),
    ("why_it_might_work", r"\*\*Why\s+It\s+Might\s+Make\s+Sense\*\*\s*\n([\s\S]+?)(?=\n\*\*|$)"),
    ("what_could_break", r"\*\*What\s+Could\s+Break\*\*\s*\n([\s\S]+?)(?=\n\*\*|$)"),
    ("possible_variants", r"\*\*Possible\s+Variants\*\*\s*\n([\s\S]+?)$"),
]


def parse_ideas(llm_output: str) -> list[BrainstormIdea]:
    """Parse brainstorm LLM output into a list of BrainstormIdea objects."""
    chunks = _IDEA_SPLIT_RE.split(llm_output.strip())
    chunks = [c for c in chunks if c.strip()]
    ideas: list[BrainstormIdea] = []
    for chunk in chunks:
        fields: dict[str, str] = {}
        for name, pattern in _FIELD_PATTERNS:
            match = re.search(pattern, chunk)
            fields[name] = match.group(1).strip() if match else ""
        if not fields.get("title"):
            continue
        ideas.append(
            BrainstormIdea(
                title=fields["title"],
                inspired_by=fields["inspired_by"],
                core_logic=fields["core_logic"],
                what_is_new=fields["what_is_new"],
                why_it_might_work=fields["why_it_might_work"],
                what_could_break=fields["what_could_break"],
                possible_variants=fields["possible_variants"],
                raw_text=chunk.strip(),
            )
        )
    return ideas
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd /home/ubuntu/project/knowledge && .venv/bin/python3 -m unittest tests.test_rethink_layer -v`
Expected: All 4 tests PASS

- [ ] **Step 3: Commit**

```bash
git add rethink_layer.py tests/test_rethink_layer.py
git commit -m "feat: add idea parsing for rethink layer (TDD)"
```

---

### Task 3: Novelty Check — Tests

**Files:**
- Modify: `tests/test_rethink_layer.py`

- [ ] **Step 1: Add tests for `check_novelty()`**

Append to `tests/test_rethink_layer.py`:

```python
from unittest.mock import patch, MagicMock
from rethink_layer import NoveltyResult, check_novelty, NOVELTY_THRESHOLD


class CheckNoveltyTests(unittest.TestCase):
    def _make_idea(self, title="Test Idea", core_logic="some logic", what_is_new="something new"):
        return BrainstormIdea(
            title=title,
            inspired_by="source",
            core_logic=core_logic,
            what_is_new=what_is_new,
            why_it_might_work="reason",
            what_could_break="risk",
            possible_variants="variant",
            raw_text="raw",
        )

    def test_novel_idea_returns_is_novel_true(self) -> None:
        idea = self._make_idea()
        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "ids": [["id1"]],
            "documents": [["some doc"]],
            "metadatas": [[{"article_dir": "/path/a", "block_type": "summary"}]],
            "distances": [[0.5]],  # score = 0.5, below threshold
        }
        with patch("rethink_layer.embed_text", return_value=[0.1] * 10):
            with patch("rethink_layer._open_rethink_collection", return_value=mock_collection):
                results = check_novelty([idea])
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].is_novel)

    def test_similar_idea_returns_is_novel_false(self) -> None:
        idea = self._make_idea()
        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "ids": [["id1"]],
            "documents": [["very similar doc"]],
            "metadatas": [[{"article_dir": "/path/a", "block_type": "idea_blocks"}]],
            "distances": [[0.1]],  # score = 0.9, above threshold
        }
        with patch("rethink_layer.embed_text", return_value=[0.1] * 10):
            with patch("rethink_layer._open_rethink_collection", return_value=mock_collection):
                results = check_novelty([idea])
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].is_novel)
        self.assertGreaterEqual(results[0].top_match_score, NOVELTY_THRESHOLD)

    def test_no_vector_store_returns_novel_with_empty_matches(self) -> None:
        idea = self._make_idea()
        with patch("rethink_layer._open_rethink_collection", side_effect=RuntimeError("no store")):
            results = check_novelty([idea])
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].is_novel)
        self.assertEqual(results[0].all_matches, [])
```

- [ ] **Step 2: Run tests to verify the new tests fail**

Run: `cd /home/ubuntu/project/knowledge && .venv/bin/python3 -m unittest tests.test_rethink_layer.CheckNoveltyTests -v`
Expected: FAIL (functions not defined yet)

---

### Task 4: Novelty Check — Implementation

**Files:**
- Modify: `rethink_layer.py`

- [ ] **Step 1: Add `_open_rethink_collection()` and `check_novelty()`**

Append to `rethink_layer.py` after the `parse_ideas` function:

```python
# ---------------------------------------------------------------------------
# Novelty check
# ---------------------------------------------------------------------------

def _open_rethink_collection(vector_store_dir: Path | None = None):
    """Open the ChromaDB knowledge_blocks collection for novelty queries."""
    if chromadb is None:
        raise RuntimeError("chromadb is required for novelty checking")
    store_dir = vector_store_dir or VECTOR_STORE_DIR
    if not store_dir.exists():
        raise RuntimeError(f"vector store directory not found: {store_dir}")
    client = chromadb.PersistentClient(path=str(store_dir))
    return client.get_collection("knowledge_blocks")


def _idea_fingerprint(idea: BrainstormIdea) -> str:
    """Combine core_logic and what_is_new as the novelty fingerprint."""
    return f"{idea.core_logic}\n{idea.what_is_new}".strip()


def check_novelty(
    ideas: list[BrainstormIdea],
    vector_store_dir: Path | None = None,
) -> list[NoveltyResult]:
    """Check each idea for novelty against the existing vector store."""
    try:
        collection = _open_rethink_collection(vector_store_dir)
    except Exception:
        return [NoveltyResult(is_novel=True) for _ in ideas]

    total = collection.count()
    if total <= 0:
        return [NoveltyResult(is_novel=True) for _ in ideas]

    results: list[NoveltyResult] = []
    for idea in ideas:
        fingerprint = _idea_fingerprint(idea)
        if not fingerprint:
            results.append(NoveltyResult(is_novel=True))
            continue

        try:
            query_embedding = embed_text(fingerprint)
            n_results = min(NOVELTY_TOP_K, total)
            query_result = collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            results.append(NoveltyResult(is_novel=True))
            continue

        ids = query_result.get("ids", [[]])[0]
        documents = query_result.get("documents", [[]])[0]
        metadatas = query_result.get("metadatas", [[]])[0]
        distances = query_result.get("distances", [[]])[0]

        matches: list[dict[str, Any]] = []
        for _doc_id, _text, meta, dist in zip(ids, documents, metadatas, distances):
            score = max(0.0, 1.0 - float(dist))
            matches.append({
                "title": str(meta.get("article_dir", "")).split("/")[-1],
                "path": str(meta.get("article_dir", "")),
                "score": round(score, 3),
            })

        matches.sort(key=lambda m: m["score"], reverse=True)
        top = matches[0] if matches else None
        is_novel = top is None or top["score"] < NOVELTY_THRESHOLD

        results.append(
            NoveltyResult(
                is_novel=is_novel,
                top_match_title=top["title"] if top and not is_novel else "",
                top_match_path=top["path"] if top and not is_novel else "",
                top_match_score=top["score"] if top and not is_novel else 0.0,
                all_matches=matches,
            )
        )

    return results
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd /home/ubuntu/project/knowledge && .venv/bin/python3 -m unittest tests.test_rethink_layer.CheckNoveltyTests -v`
Expected: All 3 tests PASS

- [ ] **Step 3: Commit**

```bash
git add rethink_layer.py tests/test_rethink_layer.py
git commit -m "feat: add novelty check via vector similarity"
```

---

### Task 5: Quality Scoring — Traceability Tests

**Files:**
- Modify: `tests/test_rethink_layer.py`

- [ ] **Step 1: Add tests for `score_traceability()`**

Append to `tests/test_rethink_layer.py`:

```python
from rethink_layer import score_traceability, QualityScore
from kb_shared import KnowledgeNote, KnowledgeBlock


class ScoreTraceabilityTests(unittest.TestCase):
    def _make_idea(self, inspired_by="", core_logic=""):
        return BrainstormIdea(
            title="Test",
            inspired_by=inspired_by,
            core_logic=core_logic,
            what_is_new="new",
            why_it_might_work="reason",
            what_could_break="risk",
            possible_variants="variant",
            raw_text="raw",
        )

    def _make_block(self, title="Article A", article_dir="a"):
        note = KnowledgeNote(
            article_dir=Path(article_dir),
            source_dir="reviewed",
            frontmatter={"title": title, "status": "reviewed"},
            body="",
        )
        return KnowledgeBlock(note=note, block_type="summary", text="content", score=0.5)

    def test_full_traceability_scores_1(self) -> None:
        blocks = [self._make_block(title="Article A"), self._make_block(title="Article B", article_dir="b")]
        idea = self._make_idea(
            inspired_by="Article A, Article B",
            core_logic="combining Article A and Article B",
        )
        score = score_traceability(idea, blocks)
        self.assertAlmostEqual(score, 1.0)

    def test_empty_inspired_by_scores_0(self) -> None:
        blocks = [self._make_block()]
        idea = self._make_idea(inspired_by="", core_logic="no references")
        score = score_traceability(idea, blocks)
        self.assertAlmostEqual(score, 0.0)

    def test_partial_traceability(self) -> None:
        blocks = [self._make_block(title="Article A")]
        idea = self._make_idea(
            inspired_by="Article A",
            core_logic="only one source",
        )
        score = score_traceability(idea, blocks)
        self.assertGreater(score, 0.0)
        self.assertLess(score, 1.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/ubuntu/project/knowledge && .venv/bin/python3 -m unittest tests.test_rethink_layer.ScoreTraceabilityTests -v`
Expected: FAIL

---

### Task 6: Quality Scoring — Traceability Implementation

**Files:**
- Modify: `rethink_layer.py`

- [ ] **Step 1: Implement `score_traceability()`**

Append to `rethink_layer.py`:

```python
# ---------------------------------------------------------------------------
# Quality scoring — traceability (heuristic)
# ---------------------------------------------------------------------------

def score_traceability(idea: BrainstormIdea, retrieved_blocks: list[KnowledgeBlock]) -> float:
    """Score how well an idea traces back to its source articles.

    - inspired_by non-empty: +0.4
    - cited sources found in retrieved blocks: +0.4
    - core_logic references multiple sources: +0.2
    """
    score = 0.0

    # Check inspired_by is non-empty
    if idea.inspired_by.strip():
        score += 0.4

    # Check if cited sources exist in retrieved blocks
    source_titles = {block.note.title for block in retrieved_blocks}
    cited_found = sum(1 for title in source_titles if title in idea.inspired_by)
    if cited_found > 0:
        score += 0.4

    # Check if core_logic references multiple sources
    multi_ref_count = sum(1 for title in source_titles if title in idea.core_logic)
    if multi_ref_count >= 2:
        score += 0.2

    return min(score, 1.0)
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd /home/ubuntu/project/knowledge && .venv/bin/python3 -m unittest tests.test_rethink_layer.ScoreTraceabilityTests -v`
Expected: All 3 tests PASS

- [ ] **Step 3: Commit**

```bash
git add rethink_layer.py tests/test_rethink_layer.py
git commit -m "feat: add traceability heuristic scoring"
```

---

### Task 7: Quality Scoring — Coherence & Actionability Tests

**Files:**
- Modify: `tests/test_rethink_layer.py`

- [ ] **Step 1: Add tests for `score_coherence_actionability()`**

Append to `tests/test_rethink_layer.py`:

```python
from rethink_layer import score_coherence_actionability


class ScoreCoherenceActionabilityTests(unittest.TestCase):
    def _make_idea(self, title="Test", core_logic="logic", what_is_new="new"):
        return BrainstormIdea(
            title=title,
            inspired_by="source",
            core_logic=core_logic,
            what_is_new=what_is_new,
            why_it_might_work="reason",
            what_could_break="risk",
            possible_variants="variant",
            raw_text="raw",
        )

    def test_returns_scores_for_each_idea(self) -> None:
        ideas = [self._make_idea(title="A"), self._make_idea(title="B")]
        mock_response = json.dumps([
            {"idea_index": 0, "coherence": 0.8, "actionability": 0.7, "coherence_reasoning": "ok", "actionability_reasoning": "ok"},
            {"idea_index": 1, "coherence": 0.6, "actionability": 0.9, "coherence_reasoning": "so-so", "actionability_reasoning": "great"},
        ])
        with patch("rethink_layer.call_llm_chat", return_value=mock_response):
            results = score_coherence_actionability(ideas)
        self.assertEqual(len(results), 2)
        self.assertAlmostEqual(results[0]["coherence"], 0.8)
        self.assertAlmostEqual(results[1]["actionability"], 0.9)

    def test_llm_failure_returns_defaults(self) -> None:
        ideas = [self._make_idea()]
        with patch("rethink_layer.call_llm_chat", side_effect=RuntimeError("API down")):
            results = score_coherence_actionability(ideas)
        self.assertEqual(len(results), 1)
        self.assertAlmostEqual(results[0]["coherence"], 0.5)
        self.assertAlmostEqual(results[0]["actionability"], 0.5)

    def test_malformed_json_returns_defaults(self) -> None:
        ideas = [self._make_idea()]
        with patch("rethink_layer.call_llm_chat", return_value="not json"):
            results = score_coherence_actionability(ideas)
        self.assertEqual(len(results), 1)
        self.assertAlmostEqual(results[0]["coherence"], 0.5)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/ubuntu/project/knowledge && .venv/bin/python3 -m unittest tests.test_rethink_layer.ScoreCoherenceActionabilityTests -v`
Expected: FAIL

---

### Task 8: Quality Scoring — Coherence & Actionability Implementation

**Files:**
- Modify: `rethink_layer.py`

- [ ] **Step 1: Implement `score_coherence_actionability()`**

Append to `rethink_layer.py`:

```python
# ---------------------------------------------------------------------------
# Quality scoring — coherence & actionability (LLM-as-judge)
# ---------------------------------------------------------------------------

RETHINK_JUDGE_SYSTEM_PROMPT = """你是量化投研想法质量评审员。
对每个想法打分（0到1），评估两个维度：
- coherence（连贯性）：组合这些来源的逻辑是否自洽？有无矛盾？
- actionability（可操作性）：这个想法是否足够具体，可以设计后续实验或回测？还是只是泛泛而谈？

返回严格JSON数组，每个元素包含：
{"idea_index": 0, "coherence": 0.8, "actionability": 0.7, "coherence_reasoning": "简要说明", "actionability_reasoning": "简要说明"}

只返回JSON，不要markdown代码块。"""


def _build_judge_prompt(ideas: list[BrainstormIdea]) -> str:
    parts: list[str] = []
    for i, idea in enumerate(ideas):
        parts.append(
            f"--- Idea {i} ---\n"
            f"Title: {idea.title}\n"
            f"Inspired By: {idea.inspired_by}\n"
            f"Core Logic: {idea.core_logic}\n"
            f"What Is New: {idea.what_is_new}\n"
            f"Why It Might Work: {idea.why_it_might_work}\n"
            f"What Could Break: {idea.what_could_break}\n"
        )
    return "\n".join(parts)


def _parse_judge_response(raw: str) -> list[dict[str, Any]]:
    """Parse JSON from LLM response, handling optional markdown fences."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return json.loads(text)


def _default_scores(count: int) -> list[dict[str, Any]]:
    return [
        {
            "idea_index": i,
            "coherence": DEFAULT_SCORE_ON_FAILURE,
            "actionability": DEFAULT_SCORE_ON_FAILURE,
            "coherence_reasoning": "evaluation unavailable",
            "actionability_reasoning": "evaluation unavailable",
        }
        for i in range(count)
    ]


def score_coherence_actionability(ideas: list[BrainstormIdea]) -> list[dict[str, Any]]:
    """Score ideas on coherence and actionability via a single LLM call."""
    if not ideas:
        return []
    try:
        messages = [
            {"role": "system", "content": RETHINK_JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": _build_judge_prompt(ideas)},
        ]
        raw = call_llm_chat(messages, temperature=0.1)
        parsed = _parse_judge_response(raw)
        if not isinstance(parsed, list) or len(parsed) != len(ideas):
            return _default_scores(len(ideas))
        # Normalize scores to 0-1 range
        for entry in parsed:
            entry["coherence"] = max(0.0, min(1.0, float(entry.get("coherence", DEFAULT_SCORE_ON_FAILURE))))
            entry["actionability"] = max(0.0, min(1.0, float(entry.get("actionability", DEFAULT_SCORE_ON_FAILURE))))
            entry.setdefault("coherence_reasoning", "")
            entry.setdefault("actionability_reasoning", "")
        return parsed
    except Exception:
        return _default_scores(len(ideas))
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd /home/ubuntu/project/knowledge && .venv/bin/python3 -m unittest tests.test_rethink_layer.ScoreCoherenceActionabilityTests -v`
Expected: All 3 tests PASS

- [ ] **Step 3: Commit**

```bash
git add rethink_layer.py tests/test_rethink_layer.py
git commit -m "feat: add LLM-based coherence and actionability scoring"
```

---

### Task 9: Report Building — Tests

**Files:**
- Modify: `tests/test_rethink_layer.py`

- [ ] **Step 1: Add tests for `build_rethink_report()`**

Append to `tests/test_rethink_layer.py`:

```python
from rethink_layer import build_rethink_report


class BuildRethinkReportTests(unittest.TestCase):
    def _make_idea(self, title="Test Idea"):
        return BrainstormIdea(
            title=title, inspired_by="src", core_logic="logic",
            what_is_new="new", why_it_might_work="reason",
            what_could_break="risk", possible_variants="variant",
            raw_text="raw",
        )

    def test_report_contains_section_header(self) -> None:
        ideas = [self._make_idea()]
        novelty = [NoveltyResult(is_novel=True)]
        quality = [QualityScore(traceability=0.8, coherence=0.9, actionability=0.7,
                                composite=0.8, coherence_reasoning="good", actionability_reasoning="concrete")]
        report = build_rethink_report(ideas, novelty, quality)
        self.assertIn("## Rethink Report", report)

    def test_novel_idea_shows_checkmark(self) -> None:
        ideas = [self._make_idea()]
        novelty = [NoveltyResult(is_novel=True)]
        quality = [QualityScore(traceability=0.8, coherence=0.9, actionability=0.7,
                                composite=0.8, coherence_reasoning="good", actionability_reasoning="ok")]
        report = build_rethink_report(ideas, novelty, quality)
        self.assertIn("Novel", report)
        self.assertNotIn("Similar to existing", report)

    def test_similar_idea_shows_warning(self) -> None:
        ideas = [self._make_idea()]
        novelty = [NoveltyResult(is_novel=False, top_match_title="existing-idea",
                                 top_match_path="/path/to/article", top_match_score=0.82)]
        quality = [QualityScore(traceability=0.5, coherence=0.6, actionability=0.4,
                                composite=0.5, coherence_reasoning="weak", actionability_reasoning="vague")]
        report = build_rethink_report(ideas, novelty, quality)
        self.assertIn("Similar to existing", report)
        self.assertIn("existing-idea", report)
        self.assertIn("0.82", report)

    def test_empty_ideas_returns_empty_report(self) -> None:
        report = build_rethink_report([], [], [])
        self.assertEqual(report, "")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/ubuntu/project/knowledge && .venv/bin/python3 -m unittest tests.test_rethink_layer.BuildRethinkReportTests -v`
Expected: FAIL

---

### Task 10: Report Building — Implementation

**Files:**
- Modify: `rethink_layer.py`

- [ ] **Step 1: Implement `build_rethink_report()`**

Append to `rethink_layer.py`:

```python
# ---------------------------------------------------------------------------
# Report building
# ---------------------------------------------------------------------------

def _compute_composite(traceability: float, coherence: float, actionability: float) -> float:
    return round(
        TRACEABILITY_WEIGHT * traceability
        + COHERENCE_WEIGHT * coherence
        + ACTIONABILITY_WEIGHT * actionability,
        2,
    )


def build_rethink_report(
    ideas: list[BrainstormIdea],
    novelty_results: list[NoveltyResult],
    quality_scores: list[QualityScore],
) -> str:
    """Build the Rethink Report markdown section."""
    if not ideas:
        return ""

    lines: list[str] = ["## Rethink Report", ""]
    for i, (idea, novelty, quality) in enumerate(zip(ideas, novelty_results, quality_scores), start=1):
        lines.append(f"### Idea {i}: {idea.title}")
        lines.append(
            f"- **Quality Score**: {quality.composite:.2f} "
            f"(Traceability: {quality.traceability:.1f} | "
            f"Coherence: {quality.coherence:.1f} | "
            f"Actionability: {quality.actionability:.1f})"
        )
        if novelty.is_novel:
            lines.append("- **Novelty**: Novel — no close matches found")
        else:
            lines.append(
                f"- **Novelty**: Similar to existing — "
                f"\"{novelty.top_match_title}\" ({novelty.top_match_score:.2f}) "
                f"in {novelty.top_match_path}"
            )
        if quality.coherence_reasoning:
            lines.append(f"- **Coherence Note**: {quality.coherence_reasoning}")
        if quality.actionability_reasoning:
            lines.append(f"- **Actionability Note**: {quality.actionability_reasoning}")
        lines.append("")

    return "\n".join(lines)
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd /home/ubuntu/project/knowledge && .venv/bin/python3 -m unittest tests.test_rethink_layer.BuildRethinkReportTests -v`
Expected: All 4 tests PASS

- [ ] **Step 3: Commit**

```bash
git add rethink_layer.py tests/test_rethink_layer.py
git commit -m "feat: add rethink report builder"
```

---

### Task 11: Main Entry Point — Tests

**Files:**
- Modify: `tests/test_rethink_layer.py`

- [ ] **Step 1: Add tests for `rethink()`**

Append to `tests/test_rethink_layer.py`:

```python
from rethink_layer import rethink


class RethinkEntryPointTests(unittest.TestCase):
    BRAINSTORM_OUTPUT = (
        "### Idea Title\n动量+波动率组合策略\n\n"
        "**Inspired By**\nArticle A, Article B\n\n"
        "**Core Combination Logic**\n将Article A和Article B的方法结合\n\n"
        "**What Is New**\n之前没有将两者组合\n\n"
        "**Why It Might Make Sense**\n互补逻辑\n\n"
        "**What Could Break**\n市场环境变化\n\n"
        "**Possible Variants**\n可替换信号\n"
    )

    def _make_blocks(self):
        note = KnowledgeNote(
            article_dir=Path("a"), source_dir="reviewed",
            frontmatter={"title": "Article A", "status": "reviewed"}, body="",
        )
        return [KnowledgeBlock(note=note, block_type="summary", text="content", score=0.5)]

    def test_rethink_appends_report_to_output(self) -> None:
        blocks = self._make_blocks()
        mock_judge = json.dumps([
            {"idea_index": 0, "coherence": 0.8, "actionability": 0.7,
             "coherence_reasoning": "ok", "actionability_reasoning": "ok"},
        ])
        with patch("rethink_layer._open_rethink_collection", side_effect=RuntimeError("no store")):
            with patch("rethink_layer.call_llm_chat", return_value=mock_judge):
                result = rethink(self.BRAINSTORM_OUTPUT, blocks, "test query")
        self.assertIn("## Rethink Report", result)
        self.assertIn("动量+波动率组合策略", result)

    def test_rethink_returns_original_on_parse_failure(self) -> None:
        blocks = self._make_blocks()
        unstructured = "This is just plain text with no ideas."
        result = rethink(unstructured, blocks, "test query")
        self.assertEqual(result, unstructured)

    def test_rethink_returns_original_on_empty_output(self) -> None:
        blocks = self._make_blocks()
        result = rethink("", blocks, "test query")
        self.assertEqual(result, "")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/ubuntu/project/knowledge && .venv/bin/python3 -m unittest tests.test_rethink_layer.RethinkEntryPointTests -v`
Expected: FAIL

---

### Task 12: Main Entry Point — Implementation

**Files:**
- Modify: `rethink_layer.py`

- [ ] **Step 1: Implement `rethink()`**

Append to `rethink_layer.py`:

```python
# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def rethink(
    llm_output: str,
    retrieved_blocks: list[KnowledgeBlock],
    query: str,
    vector_store_dir: Path | None = None,
) -> str:
    """Run the rethink layer on brainstorm output.

    Returns the original output with an appended Rethink Report section.
    If parsing fails or there are no ideas, returns the original output unchanged.
    """
    if not llm_output.strip():
        return llm_output

    ideas = parse_ideas(llm_output)
    if not ideas:
        return llm_output

    # Novelty check
    novelty_results = check_novelty(ideas, vector_store_dir)

    # Traceability scoring (heuristic)
    traceability_scores = [score_traceability(idea, retrieved_blocks) for idea in ideas]

    # Coherence + actionability scoring (LLM call)
    ca_scores = score_coherence_actionability(ideas)

    # Assemble quality scores
    quality_scores: list[QualityScore] = []
    for i, idea in enumerate(ideas):
        t = traceability_scores[i]
        ca = ca_scores[i] if i < len(ca_scores) else {
            "coherence": DEFAULT_SCORE_ON_FAILURE,
            "actionability": DEFAULT_SCORE_ON_FAILURE,
            "coherence_reasoning": "evaluation unavailable",
            "actionability_reasoning": "evaluation unavailable",
        }
        c = ca["coherence"]
        a = ca["actionability"]
        quality_scores.append(
            QualityScore(
                traceability=round(t, 2),
                coherence=round(c, 2),
                actionability=round(a, 2),
                composite=_compute_composite(t, c, a),
                coherence_reasoning=ca.get("coherence_reasoning", ""),
                actionability_reasoning=ca.get("actionability_reasoning", ""),
            )
        )

    report = build_rethink_report(ideas, novelty_results, quality_scores)
    if not report:
        return llm_output

    return llm_output.rstrip() + "\n\n" + report
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd /home/ubuntu/project/knowledge && .venv/bin/python3 -m unittest tests.test_rethink_layer.RethinkEntryPointTests -v`
Expected: All 3 tests PASS

- [ ] **Step 3: Commit**

```bash
git add rethink_layer.py tests/test_rethink_layer.py
git commit -m "feat: add rethink() main entry point"
```

---

### Task 13: Integration — brainstorm_from_kb.py

**Files:**
- Modify: `brainstorm_from_kb.py:394-396`

- [ ] **Step 1: Add rethink import and call**

At the top of `brainstorm_from_kb.py`, add to imports (after line 29):

```python
from rethink_layer import rethink
```

Replace lines 394-396:

```python
    result = call_zhipu_chat(build_messages(args.command, args.query, context))
    output_path = Path(args.output_file).expanduser().resolve() if args.output_file else default_output_path(args.command, args.query)
    saved = write_output(output_path, args.query, args.command, retrieved, result)
```

With:

```python
    result = call_zhipu_chat(build_messages(args.command, args.query, context))
    if args.command == "brainstorm":
        result = rethink(result, retrieved, args.query, VECTOR_STORE_DIR)
    output_path = Path(args.output_file).expanduser().resolve() if args.output_file else default_output_path(args.command, args.query)
    saved = write_output(output_path, args.query, args.command, retrieved, result)
```

- [ ] **Step 2: Run existing brainstorm tests to verify no regressions**

Run: `cd /home/ubuntu/project/knowledge && .venv/bin/python3 -m unittest tests.test_brainstorm_from_kb -v`
Expected: All existing tests PASS

- [ ] **Step 3: Commit**

```bash
git add brainstorm_from_kb.py
git commit -m "feat: integrate rethink layer into brainstorm CLI"
```

---

### Task 14: Integration — agent/tools.py

**Files:**
- Modify: `agent/tools.py:375-387`

- [ ] **Step 1: Add rethink call to query_knowledge_base tool**

In `agent/tools.py`, inside the `query_knowledge_base` function, replace lines 375-387:

```python
    try:
        result = call_zhipu_chat(messages)
    except Exception as exc:
        return f"LLM error: {exc}"

    try:
        output_path = default_output_path(mode, query)
        write_output(output_path, query, mode, retrieved, result)
    except Exception:
        pass  # non-critical: output file write failure

    warning_text = f"\n(Warning: {warning})" if warning else ""
    return f"{result}{warning_text}"
```

With:

```python
    try:
        result = call_zhipu_chat(messages)
    except Exception as exc:
        return f"LLM error: {exc}"

    if mode == "brainstorm":
        from rethink_layer import rethink
        result = rethink(result, retrieved, query, VECTOR_STORE_DIR)

    try:
        output_path = default_output_path(mode, query)
        write_output(output_path, query, mode, retrieved, result)
    except Exception:
        pass  # non-critical: output file write failure

    warning_text = f"\n(Warning: {warning})" if warning else ""
    return f"{result}{warning_text}"
```

- [ ] **Step 2: Run existing agent tool tests to verify no regressions**

Run: `cd /home/ubuntu/project/knowledge && .venv/bin/python3 -m unittest tests.test_agent_tools -v`
Expected: All existing tests PASS

- [ ] **Step 3: Commit**

```bash
git add agent/tools.py
git commit -m "feat: integrate rethink layer into agent query tool"
```

---

### Task 15: Full Test Suite Verification

**Files:** None (verification only)

- [ ] **Step 1: Run all tests**

Run: `cd /home/ubuntu/project/knowledge && .venv/bin/python3 -m unittest discover -s tests -p 'test_*.py' -v`
Expected: All tests PASS, including new `test_rethink_layer.py` tests

- [ ] **Step 2: Verify rethink_layer.py has no syntax errors**

Run: `cd /home/ubuntu/project/knowledge && .venv/bin/python3 -c "import rethink_layer; print('OK')""`
Expected: `OK`

- [ ] **Step 3: Final commit with any fixes if needed**

```bash
git add -A
git commit -m "chore: final verification of rethink layer integration"
```
