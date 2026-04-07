# Rethink Layer Design

Post-generation validation layer for the brainstorm pipeline. Checks idea novelty against the existing knowledge base and scores idea quality before final output.

## Motivation

The brainstorm pipeline generates new investment strategy ideas by combining retrieved KB articles via LLM. Currently there is no validation between generation and output — ideas may duplicate existing KB content, lack proper source attribution, or be too vague to act on. The rethink layer fills this gap.

## Scope

- Applies to `brainstorm` mode only (not `ask` mode)
- One new module: `rethink_layer.py`
- Integration into `brainstorm_from_kb.py` and `agent/tools.py`
- New test file: `tests/test_rethink_layer.py`

## Design

### 1. Idea Parsing

The brainstorm LLM outputs ideas in a structured format with fields: Idea Title, Inspired By, Core Combination Logic, What Is New, Why It Might Make Sense, What Could Break, Possible Variants.

The rethink layer parses this into a list of `BrainstormIdea` dataclasses by splitting on the "Idea Title" heading pattern. Each field is extracted via section matching. If parsing fails (unstructured output), the rethink layer skips gracefully and returns the original output with a warning.

**Data structure:**

```python
@dataclass
class BrainstormIdea:
    title: str
    inspired_by: str
    core_logic: str
    what_is_new: str
    why_it_might_work: str
    what_could_break: str
    possible_variants: str
    raw_text: str  # original unparsed text for this idea
```

### 2. Novelty Check (Vector Similarity)

For each parsed idea:

1. Concatenate "Core Combination Logic" + "What Is New" as the novelty fingerprint
2. Call `kb_shared.embed_text()` to get the embedding
3. Query the existing ChromaDB collection for top-5 nearest neighbors
4. Score as `1.0 - distance` — if any result scores >= 0.75, flag as "similar to existing"
5. Attach matched article titles, paths, and similarity scores

Reuses existing vector store and embedding infrastructure. The 0.75 threshold is a module-level constant (`NOVELTY_THRESHOLD`).

**Data structure:**

```python
@dataclass
class NoveltyResult:
    is_novel: bool
    top_match_title: str        # empty if novel
    top_match_path: str         # empty if novel
    top_match_score: float      # 0.0 if novel
    all_matches: list[dict]     # [{"title": ..., "path": ..., "score": ...}]
```

### 3. Quality Scoring

Three dimensions, composite score:

**Traceability (heuristic, 0.0-1.0):**
- "Inspired By" field is non-empty: +0.4
- Cited sources exist in the retrieved blocks: +0.4
- "Core Combination Logic" references multiple sources: +0.2

**Coherence (LLM-as-judge, 0.0-1.0):**
- Does combining these sources make logical sense? Are there contradictions?

**Actionability (LLM-as-judge, 0.0-1.0):**
- Is this concrete enough to design a follow-up experiment or backtest?

**LLM scoring call:**
- One batched call for all ideas
- Returns JSON: `[{"idea_index": 0, "coherence": 0.8, "actionability": 0.6, "reasoning": "..."}, ...]`
- If the LLM call fails, default both scores to 0.5 with a warning

**Composite:** `0.3 * traceability + 0.35 * coherence + 0.35 * actionability`

**Data structure:**

```python
@dataclass
class QualityScore:
    traceability: float
    coherence: float
    actionability: float
    composite: float
    coherence_reasoning: str
    actionability_reasoning: str
```

### 4. Rethink Report Format

Appended to the brainstorm output as a separate section:

```markdown
## Rethink Report

### Idea 1: [Idea Title]
- **Quality Score**: 0.78 (Traceability: 0.8 | Coherence: 0.85 | Actionability: 0.7)
- **Novelty**: Warning — Similar to existing — "Title" (0.82) in articles/reviewed/path/
- **Coherence Note**: Sources share compatible assumptions about regime persistence
- **Actionability Note**: Concrete enough to design a factor backtest

### Idea 2: [Idea Title]
- **Quality Score**: 0.91 (Traceability: 1.0 | Coherence: 0.9 | Actionability: 0.85)
- **Novelty**: Novel — no close matches found
- **Coherence Note**: ...
- **Actionability Note**: ...
```

### 5. Integration Points

**`brainstorm_from_kb.py`:** After `call_llm_chat()` returns, before `write_output()`:

```python
rethink_result = rethink(raw_llm_output, retrieved_blocks, query, vector_store_dir)
# rethink_result is the original output + appended Rethink Report
```

**`agent/tools.py` `query_knowledge_base`:** Same insertion point — after the LLM call, append rethink report to the result string.

**New file `rethink_layer.py`:**

| Function | Purpose |
|----------|---------|
| `parse_ideas(llm_output)` | Parse LLM output into `list[BrainstormIdea]` |
| `check_novelty(ideas, vector_store_dir)` | Vector similarity check, returns `list[NoveltyResult]` |
| `score_traceability(idea, retrieved_blocks)` | Heuristic traceability score, returns `float` |
| `score_coherence_actionability(ideas)` | Batched LLM call, returns `list[dict]` |
| `build_rethink_report(ideas, novelty_results, quality_scores)` | Format report markdown |
| `rethink(llm_output, retrieved_blocks, query, vector_store_dir)` | Main entry point, returns full output string |

**Graceful degradation:**
- If idea parsing fails: return original output + warning
- If vector store unavailable: skip novelty check, report "novelty check skipped"
- If LLM scoring call fails: default coherence/actionability to 0.5 with warning

### 6. Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `NOVELTY_THRESHOLD` | 0.75 | Similarity score above which an idea is flagged |
| `NOVELTY_TOP_K` | 5 | Number of nearest neighbors to check |
| `TRACEABILITY_WEIGHT` | 0.3 | Weight in composite score |
| `COHERENCE_WEIGHT` | 0.35 | Weight in composite score |
| `ACTIONABILITY_WEIGHT` | 0.35 | Weight in composite score |
| `DEFAULT_SCORE_ON_FAILURE` | 0.5 | Default coherence/actionability if LLM call fails |

### 7. Tests

New `tests/test_rethink_layer.py` covering:
- Idea parsing from well-formed and malformed LLM output
- Traceability heuristic scoring with various citation patterns
- Novelty result construction
- Report formatting
- Graceful failure when parsing fails
- Graceful failure when vector store is unavailable
