# Wiki LLM KB Integration — Design Spec

**Date:** 2026-04-27
**Status:** Approved (agent-first revision)
**Inspired by:** Andrej Karpathy's "LLM Knowledge Bases" tweet
**Prior art in this repo:** `PLAN.md` (idea-blocks enrichment), `README.md` (current pipeline)

## Goal

Add an agent-first compiled wiki layer between raw articles and queries, plus extend the CLI ingest pipeline to handle generic web URLs and PDFs. Give the LangGraph agent wiki maintenance, health-audit, and selective retrieval tools without breaking the existing brainstorm + rethink pipeline.

The wiki is a hybrid memory system: Markdown remains the inspectable interface, while `wiki/state.json`, Chroma metadata, and lint reports are the machine-facing substrate. Queries traverse high-scoring concept memory when concepts apply, and fall back to vector RAG when they do not. Brainstorm is rebuilt to pull compact concept memory first, complementary raw articles second.

Human users should mainly provide valuable raw materials and review brainstorm/research outputs. Routine wiki maintenance should be handled by the agent.

## Non-Goals

These are intentionally deferred (see §10):

- Image / chart ingest and OCR.
- True LaTeX extraction from PDF math (Mathpix / Nougat).
- GitHub repo ingest.
- Output rendering (Marp slides, matplotlib, Mermaid) and filing rendered outputs back into the wiki.
- Wiki search engine UI.
- Synthetic data generation and fine-tuning.
- Obsidian Web Clipper integration and Obsidian-specific browsing workflows (explicitly out of scope; CLI/agent-first).

## Architecture

### Data flow

```
                    ┌─ ingest_source ─────────────┐
                    │  • WeChat URL (existing)    │
   sources ────────►│  • Generic web URL (new)    │
   (web/pdf/HTML)   │  • Local HTML (existing)    │
                    │  • PDF (new)                │
                    └────────────┬────────────────┘
                                 │
                                 ▼
                         articles/raw/<dir>/article.md
                                 │
                                 ▼ enrich_articles (unchanged)
                         articles/raw/<dir>/article.md  (frontmatter filled)
                                 │
                                 ▼ sync_articles (unchanged)
                         articles/{reviewed,high-value}/<dir>/article.md
                                 │
                                 ▼ compile_wiki (NEW)
                                 │
                          ┌──────┴──────┐
                          ▼             ▼
                 wiki/sources/      wiki/concepts/
                 <article>.md       <concept>.md
                 (per-article       (LLM-synthesized,
                  short summary)     seeded + auto-grown)
                          │             │
                          └──────┬──────┘
                                 ▼
                            wiki/state.json
                          (scores, hashes, freshness,
                           conflicts, retrieval hints)
                                 │
                                 ▼ embed_knowledge (extended)
                          ChromaDB index
                                 │
                                 ▼
                          ┌──────┴──────┐
                          ▼             ▼
                     query_kb         agent (extended)
                  (brainstorm uses    + read_wiki / list_concepts
                   wiki concepts      / set_concept_status
                   first, vector      / compile_wiki tools
                   for complementary)
```

### Layers

- **Sources layer** (`articles/`): unchanged — raw and curated source documents with enriched frontmatter.
- **Wiki layer** (`wiki/`, NEW): LLM-written summaries and concept articles plus structured state. The KB's compiled memory form.
- **Index layer** (ChromaDB): vector index over both `articles/` and `wiki/`, with a `kb_layer` metadata field distinguishing them.
- **Agent layer** (`agent/`): existing tools plus wiki compile, audit, concept listing/status override, and selective wiki reads.

### Tech stack additions

- `trafilatura` — primary web extraction with formatting preservation.
- `readability-lxml` — fallback when trafilatura returns empty.
- `pypdf` — primary PDF text extraction.
- `pdfplumber` — fallback for columnar PDF layouts.
- No new vector store, no new model, no paid APIs, no system-level deps.

## File Layout

```
wiki/
├── INDEX.md                          # compact agent routing index
├── state.json                        # source hashes, concept scores, freshness, conflicts, retrieval hints
├── lint_report.json                  # latest wiki health report
├── concepts/
│   ├── factor-models.md              # status: stable (seed)
│   ├── factor-timing.md              # status: stable (seed)
│   ├── regime-detection.md           # status: stable (seed)
│   ├── momentum-strategies.md        # status: stable (seed)
│   ├── etf-rotation.md               # status: stable (seed)
│   ├── risk-parity.md                # status: stable (seed)
│   ├── volatility-targeting.md       # status: stable (seed)
│   ├── macro-momentum.md             # status: proposed (auto-suggested)
│   └── ...
└── sources/
    ├── 2026-03-22_华泰_红利因子择时.md  # 1:1 with articles/{reviewed,high-value}/
    └── ...
```

`wiki/` is committed to git (open question §11 confirmed: yes — version the LLM-written knowledge and structured memory state alongside sources).

## Schemas

### Concept article (`wiki/concepts/<slug>.md`)

```yaml
---
title: Momentum Factor
slug: momentum-factor
aliases: [momentum, 动量因子, momentum-investing]
status: stable                  # stable | proposed | deprecated
related_concepts: [factor-timing, etf-rotation, regime-detection]
sources:
  - articles/high-value/2025-03-04_中金_低频策略.../article.md
  - articles/reviewed/2026-03-22_华泰金工_趋势拐点.../article.md
content_types: [methodology, strategy]
last_compiled: 2026-04-27
compile_version: 3
---

# Momentum Factor

## Synthesis
[1–3 paragraphs, LLM-written. The "story" the corpus tells about this concept.]

## Definition
[1 paragraph: canonical definition + brief context.]

## Key Idea Blocks
- [aggregated from `idea_blocks` of source articles, deduped, with citations]

## Variants & Implementations
- [how different sources implement it]

## Common Combinations
- [aggregated from `combination_hooks`, links to other concept articles]

## Transfer Targets
- [aggregated from `transfer_targets`]

## Failure Modes
- [aggregated from `failure_modes`]

## Open Questions
- [aggregated from `followup_questions`]

## Sources
- [[2026-03-22_华泰金工_趋势拐点]] — primary
- [[2025-03-04_中金_低频策略]] — supporting
```

Cross-references in `Common Combinations` and `Sources` use lightweight `[[wikilinks]]` because they are easy for both humans and agents to parse. Obsidian compatibility is incidental, not a product requirement. `related_concepts:` plus `wiki/state.json` are the source of truth for agent traversal.

**Wikilink convention** (used everywhere in this spec):
- Concept references inside concept articles: `[[<slug>]]` (slug-only, e.g. `[[momentum-factor]]`).
- Source references inside concept articles: `[[<source_basename>]]` (article directory basename, e.g. `[[2026-03-22_华泰金工_趋势拐点]]`).
- All references inside `INDEX.md`: full relative path with subdirectory, e.g. `[[concepts/momentum-factor]]`, `[[sources/2026-04-25_xxx]]` — used to avoid basename collisions across `concepts/` and `sources/`.

Slug ↔ basename collisions are prevented by reserving slugs to kebab-case ASCII and source basenames to the existing `<YYYY-MM-DD>_<...>` format (always starts with a digit).

**Status enum:**
- `stable` — used by brainstorm/Q&A, recompiled when sources change.
- `proposed` — low-confidence exception queue; not used by brainstorm/Q&A until stabilized by the agent or explicit override.
- `deprecated` — kept on disk for traceability of past outputs; excluded from INDEX, retrieval, and recompile.

### Source summary (`wiki/sources/<article_id>.md`)

Compiled mechanically from the source article's frontmatter (no extra LLM call):

```yaml
---
source_path: articles/high-value/2026-03-22_华泰金工_趋势拐点.../article.md
title: 基于趋势和拐点的市值因子择时模型
content_type: methodology
brainstorm_value: high
feeds_concepts: [factor-timing, momentum-factor, regime-detection]
ingested: 2026-03-22
last_compiled: 2026-04-27
---

# 基于趋势和拐点的市值因子择时模型 — Source Summary

**One-line takeaway:** [from `core_hypothesis` or `tldr` frontmatter]

**Idea Blocks (top 3):**
- [first 3 idea_blocks]

**Why it's in the KB:** [from `brainstorm_value` reasoning, 1 sentence]

**Feeds concepts:** [[momentum-factor]], [[factor-timing]], [[regime-detection]]
```

### INDEX.md

Auto-regenerated on every compile:

```markdown
# Knowledge Base Index

_Last compiled: 2026-04-27 · 14 concepts · 87 source articles_

## Stable Concepts

### methodology
- [[concepts/momentum-factor]] — 12 sources
- [[concepts/factor-timing]] — 8 sources

### strategy
- [[concepts/etf-rotation]] — 9 sources

### allocation
- [[concepts/risk-parity]] — 6 sources

## Proposed Concepts (low-confidence exceptions)
- [[concepts/macro-momentum]] — auto-proposed 2026-04-27 from 3 sources

## Recent Source Additions (last 7 days)
- [[sources/2026-04-25_xxx]] → feeds momentum-factor, regime-detection
```

### Article frontmatter additions

`article.md` frontmatter (and the `source.json` companion) gain:

```yaml
source_type: wechat | web | pdf | html
has_code: true | false
has_math: true | false
has_formula_images: true | false
extraction_quality: full | partial | text_only
paywalled: true | false   # web only, when paywall heuristic triggers
```

## Seed Taxonomy

Bootstrapped before any ingest, ~7 stable concepts mapped to existing `content_type` values:

| Slug | Aliases (CN/EN) | Source content_type filter |
|---|---|---|
| `factor-models` | 因子模型, 多因子 | methodology |
| `factor-timing` | 因子择时 | methodology |
| `regime-detection` | 风格切换, 状态识别 | methodology |
| `momentum-strategies` | 动量策略, momentum | strategy |
| `etf-rotation` | etf轮动, 行业轮动 | strategy, allocation |
| `risk-parity` | 风险平价 | allocation, risk_control |
| `volatility-targeting` | 波动率择时, 风险预算 | risk_control |

Concepts beyond these are created or merged autonomously when confidence/source support is high. `proposed` is reserved for low-confidence exceptions, conflicts, or ambiguous taxonomy decisions; `set_concept_status` is an override tool, not the normal workflow.

## Wiki Compilation Flow

### Two modes

- **Incremental** (default): runs after `sync_articles` whenever new articles enter `reviewed/` or `high-value/`. Per-article cost. Skips concepts whose source content hashes in `wiki/state.json` did not change.
- **Rebuild** (`--rebuild`): wipes `wiki/concepts/*.md` (re-creates seed stubs from taxonomy), wipes `wiki/INDEX.md`, then treats every article in `articles/{reviewed,high-value}/` as newly-synced. Used when seed taxonomy changes or wiki has clearly drifted.

### Incremental algorithm

For each newly-synced article:

```
1. Build/update wiki/sources/<article_id>.md
   - Mechanical, no LLM call. Reads article frontmatter, writes summary file.

2. Concept assignment (LLM call #1: assign_concepts)
   - Input: article frontmatter + idea_blocks + INDEX.md (concept list with one-line definitions)
   - Output: {
       existing_concepts: [slug, ...],
       proposed_new_concepts: [{slug, title, aliases, rationale, draft_synthesis}]
     }
   - Existing assignments accepted automatically; the article path is added to those concepts'
     sources list and they are queued for recompile in step 3.
   - High-confidence new concepts → stable concept files if deterministic validation passes.
   - Low-confidence or conflicting concepts → status `proposed`, listed as exceptions, excluded from brainstorm/Q&A until stabilized.

3. For each affected existing concept C (parallel, LLM call #2..N: recompile_concept):
   - Read all sources currently feeding C (incl. the new one).
   - Read current wiki/concepts/C.md.
   - Rewrite the concept article. Bump compile_version, update last_compiled, sources,
     content_types, related_concepts.

4. Update `wiki/state.json` with source hashes, confidence, importance, freshness, conflicts, and retrieval hints.
5. Run `wiki_lint` and write `wiki/lint_report.json`.
6. Regenerate wiki/INDEX.md from current state of wiki/concepts/*.
```

Concurrency uses existing `LLM_CONCURRENCY` setting.

### Cost model

| Step | LLM? | Calls per ingest |
|---|---|---|
| Source summary | No | 0 |
| `assign_concepts` | Yes | 1 per new article |
| `recompile_concept` | Yes | 1 per affected concept (concurrent) |
| `INDEX.md` regen | No | 0 |
| Embed wiki into ChromaDB | Embedding API only | N chunks |

Typical incremental compile of 5 new articles touching 3 distinct concepts: 5 + 3 = 8 LLM calls.
Rebuild of a 100-article corpus over ~15 concepts: ~115 LLM calls.

## Ingest Extension

### Source dispatch

`ingest_wechat_article.py` is renamed `ingest_source.py`; the original filename is kept as a one-line shim importing from the new module for backward compatibility with any existing CLI invocations.

```
ingest_source --url <URL>          # auto-detect: WeChat / generic web / PDF
ingest_source --html-file <path>   # local HTML
ingest_source --pdf-file <path>    # local PDF
ingest_source --pdf-url <URL>      # remote PDF download then parse
ingest_source --url-list <file>    # batch, mixed types via auto-detect
```

URL auto-detection rules:
1. Host matches `mp.weixin.qq.com` → existing WeChat path (preserved verbatim, moved to `_wechat.py` submodule).
2. URL ends in `.pdf` OR response `Content-Type` is `application/pdf` → PDF path.
3. Otherwise → generic web extraction path.

### Generic web extraction

Primary: `trafilatura` with `include_formatting=True, include_links=True`.
Fallback: `readability-lxml` when trafilatura returns empty.

Output layout:
- `articles/raw/<YYYY-MM-DD>_<host>_<slug>/article.md`
- `articles/raw/<YYYY-MM-DD>_<host>_<slug>/source.json` (with `source_type: web`)

### PDF extraction

Primary: `pypdf`.
Fallback: `pdfplumber` when `pypdf` returns < 100 chars per page on a 5+ page doc.

Output layout:
- `articles/raw/<YYYY-MM-DD>_<filename_slug>/article.md`
- `articles/raw/<YYYY-MM-DD>_<filename_slug>/source.pdf` (original preserved for chart pages)
- `articles/raw/<YYYY-MM-DD>_<filename_slug>/source.json` (with `source_type: pdf`)

### Code and math handling

**Web URLs:**
- Walk source HTML for `<pre><code class="language-X">` and emit fenced code blocks with language hint preserved.
- Inline `<code>` preserved as backticks.
- Math: scan original HTML for `$...$`, `$$...$$`, `\(...\)`, `\[...\]`, `<script type="math/tex">`, `<annotation encoding="application/x-tex">` and preserve verbatim into standard markdown/MathJax-compatible delimiters.

**WeChat:**
- Code: heuristic — contiguous `<p>` runs with monospace style or high-density code-pattern text → fenced block (no language hint).
- Math: WeChat formulas are typically uploaded images. Image saved into article directory; markdown references it as `![formula](image-N.png)`. `has_formula_images: true` flag set in frontmatter so the agent knows textual content is incomplete.

**PDFs:**
- Code: post-extraction heuristic — blocks where ≥80% of lines start with whitespace + look like code → fenced block (no language hint).
- Math (Tier 1, default): pypdf preserves Unicode math chars (∑ ∫ σ μ ρ²). LaTeX structure is lost. Acceptable for ~70% of broker-report formulas (simple inline expressions).
- Math (Tier 2): `--ocr-formulas` flag stub for future Mathpix/Nougat integration. Out of scope this plan.

### Failure handling (ingest)

| Failure | Behavior |
|---|---|
| trafilatura empty + readability-lxml empty | Skip URL, log warning with URL and HTTP status. No partial article directory. |
| PDF unreadable (encrypted, scanned without OCR) | Skip with explicit message; no partial article. |
| URL paywalled | Detected via length heuristic + "subscribe"/"paywall" text. Save what was extracted, mark `paywalled: true`. |
| Network failure on `--url-list` | Skip individual URL with logged error, continue list (existing batch behavior). |

## Agent Tool Surface

13 tools total. Existing article tools remain; wiki tools are for agent memory maintenance and selective retrieval.

| # | Tool | Status | Notes |
|---|---|---|---|
| 1 | `ingest_article` | Extended | Now dispatches WeChat / generic web / PDF / HTML. Adds `pdf_file`, `pdf_url` params. |
| 2 | `enrich_articles` | Unchanged | |
| 3 | `list_articles` | Unchanged | |
| 4 | `review_articles` | Unchanged | |
| 5 | `set_article_status` | Unchanged | |
| 6 | `sync_articles` | Unchanged | |
| 7 | `embed_knowledge` | Extended | Also indexes `wiki/concepts/*` and `wiki/sources/*` with `kb_layer` metadata. |
| 8 | `query_knowledge_base` | Extended | Internally retrieves wiki concepts first (see §8.1). External signature unchanged. |
| 9 | `compile_wiki` | NEW | Params: `mode: incremental \| rebuild` (default incremental), `dry_run: bool`. |
| 10 | `audit_wiki` | NEW | Returns memory health, stale concepts, conflicts, orphan links, and low-confidence exceptions. |
| 11 | `list_concepts` | NEW | Params: `status: all \| stable \| proposed \| deprecated` (default all). |
| 12 | `set_concept_status` | NEW | Admin/agent override. Params: `slug: str`, `status: stable \| deprecated \| deleted`, `reason: str`. |
| 13 | `read_wiki` | NEW | Params: `target: 'index' \| <concept_slug> \| <source_id>`. |

### Agent prompt additions

`agent/prompts.py` system prompt gains a "Wiki layer" section teaching:

- "Explain X" / "what's the state of Y" / "summarize what we know about Z" → retrieve selective concept memory first; use `read_wiki` only when a full concept/source page is needed.
- "Brainstorm" / "combine ideas" / "generate new strategy" → `query_knowledge_base` (incorporates wiki internally; agent doesn't orchestrate).
- "Find articles about X" / "novelty check on Y" → `query_knowledge_base` (vector path).
- After ingest, the canonical pipeline is: `enrich_articles` → article quality review/status → `sync_articles` → `compile_wiki` → `audit_wiki` → `embed_knowledge`.
- Proposed concepts are low-confidence exceptions. Surface only errors or research-quality risks; do not ask humans for routine concept approval.

## Brainstorm + Q&A Integration

### Brainstorm flow (the highest-leverage integration)

```
Query: "How to combine momentum factor with regime detection for ETF rotation?"

Step 1: Concept retrieval (NEW)
  - Vector similarity over wiki/concepts/* embeddings (filtered to status=stable).
  - Rerank using wiki/state.json: semantic similarity + confidence + importance + freshness - conflict penalty.
  - Pull compact concept memory blocks, not full pages by default. Default K=3.
  - This query → [momentum-factor, regime-detection, etf-rotation].

Step 2: Complementary article retrieval
  - For each retrieved concept, identify its sources: list.
  - Vector-search over articles/* (kb_layer=article), EXCLUDING already-cited sources,
    for complementary chunks. Default 3 chunks.

Step 3: Brainstorm prompt (modified)
  - Feed LLM: 3 compact concept memory blocks + 3 complementary chunks (vs. current 8 raw chunks).
  - Same brainstorm prompt structure (Idea Title, Inspired By, etc.).
  - Citations distinguish wiki concept articles from raw articles.

Step 4: Rethink layer (UNCHANGED)
  - Same novelty check (cosine over ChromaDB) and quality scoring.
  - Citations validated against ChromaDB exactly as today.
```

### Why this should produce better ideas

- LLM sees compact synthesized concept memory instead of 8 raw chunks of varying relevance — less needle-in-haystack, lower token cost, more crystallized inputs.
- `combination_hooks` and `transfer_targets` sections in concept articles literally tell the LLM what combinations are productive.
- Complementary articles still come in for novelty/detail, but at lower volume.

### Fallback (no regression risk)

If `wiki/concepts/` has < 3 stable concepts, no concepts match the query, or `audit_wiki` reports blocking errors, brainstorm falls back to current pure-vector retrieval. Logged in output. Existing users who never compile the wiki see no behavior change.

### Q&A flow ("explain X")

When the agent calls `read_wiki` with target=`<slug>`:
1. Read `wiki/concepts/<slug>.md` directly. Return body to the agent.
2. Agent decides whether to also fetch source summaries (via further `read_wiki` calls) before answering.

When target=`'index'`: return INDEX.md.
When target=`<source_id>`: return `wiki/sources/<source_id>.md`.

No LLM call inside `read_wiki` itself — pure file read.

## Error Handling

Following the existing "self-healing vector store" / "graceful degradation" principle:

| Failure | Behavior |
|---|---|
| `wiki/` doesn't exist | Wiki tools return "wiki not initialized — run `compile_wiki` first"; brainstorm falls back to pure-vector retrieval. |
| `assign_concepts` fails for an article | `wiki/sources/<id>.md` still written; assignment retried on next compile; logged as `pending_assignment`. |
| `recompile_concept` fails for one concept | That concept's `last_compiled` stays old; other concepts complete; failed concept logged and retryable. |
| `set_concept_status` on missing slug | Clear error, no partial change. |
| `audit_wiki` reports blocking errors | Brainstorm falls back to article-only retrieval and surfaces the reason. |
| Source hash mismatch | Affected concepts are marked stale in `wiki/state.json` and recompiled on next compile. |
| PDF parse fails (encrypted/scanned) | Skip with explicit message; no partial article directory. |
| Malformed `wiki/concepts/<slug>.md` (frontmatter parse error) | Concept skipped during INDEX regen, logged; doesn't break compile of other concepts. |
| Embed step encounters wiki file with no body | Skipped; warning logged. |
| Compile interrupted mid-run | Each `wiki/concepts/<slug>.md` write goes to `<slug>.md.tmp` then atomically renamed; partial writes never visible. Rerun resumes via idempotency check. |
| ChromaDB corruption during wiki embed | Existing self-healing path triggers (clean + rebuild). |

No silent failures. Every degraded path produces a log line and surfaces in the agent response.

## Test Plan

### Unit tests

- `test_ingest_source.py` — replaces and extends `test_ingest_wechat_article.py`. Cases: WeChat (existing); generic web (mock trafilatura); PDF text-only fixture; PDF with formulas preserves Unicode math chars; code block preservation across all source types; paywall detection; scanned PDF rejection.
- `test_compile_wiki.py` — NEW. Cases: source summary generation from frontmatter (no LLM); concept assignment with mocked LLM; incremental compile produces no LLM calls when no source hash changed (idempotency); rebuild from empty state; high-confidence concept stabilizes automatically; low-confidence/conflicting concept remains proposed; seed concept stubs created on first run; INDEX regeneration is deterministic.
- `test_wiki_state.py` — NEW. Cases: content-hash tracking, memory score ranking, freshness decay, invalid state recovery.
- `test_wiki_lint.py` — NEW. Cases: stale concepts, unsupported claims, duplicate aliases, orphan concepts/sources, blocking health report.
- `test_wiki_schemas.py` — NEW. Validates concept article frontmatter, source summary frontmatter, INDEX format. Round-trip parse/serialize.
- `test_brainstorm_with_wiki.py` — NEW. Cases: brainstorm retrieves concept articles when wiki exists; falls back to pure-vector when wiki is empty; complementary article retrieval excludes already-cited sources; citations distinguish wiki vs article.
- `test_agent_tools.py` — extended with `compile_wiki`, `audit_wiki`, `list_concepts`, `set_concept_status`, `read_wiki` tool tests.
- `test_agent_graph.py` — extended with one routing test per new tool ("explain momentum factor" → `read_wiki`).

### Robustness tests

- `test_layer1_tool_robustness.py` — extend with malformed inputs to new tools.
- `test_layer2_workflow_integration.py` — add end-to-end test: ingest 5 articles (mix of WeChat + web + PDF) → enrich → sync → compile_wiki → embed → brainstorm → verify rethink layer still scores.
- `test_layer4_llm_api_robustness.py` — extend with `assign_concepts` and `recompile_concept` LLM failure modes.

### Acceptance test (manual)

1. Bootstrap: empty `wiki/`, run `compile_wiki` over the existing corpus in `articles/{reviewed,high-value}/`. Verify ≥ 5 stable seed concepts get filled, ≥ 80% of articles produce non-empty source summaries, `wiki/state.json` has hashes/scores, and `audit_wiki` is ok for brainstorm.
2. Ingest a new web article (non-WeChat) about momentum, run pipeline through `compile_wiki`. Verify it gets assigned to `momentum-strategies` and the concept article shows the new source.
3. Ingest a PDF broker report. Verify code/math handling per ingest section.
4. Brainstorm query "combine momentum and regime detection". Compare output against current system: should cite ≥ 2 high-scoring wiki concepts in `Inspired By` without dumping full pages.
5. Ingest an outlier article (e.g. options volatility surface). Verify high-confidence concepts stabilize automatically, while low-confidence/conflicting concepts are excluded from retrieval and surfaced by `audit_wiki`.

## Out of Scope (Deferred)

These are real Karpathy capabilities to revisit after this integration lands:

- Image / chart ingest (auto-download images during web clip, OCR captioning of PDF charts). Foreshadowed by `has_formula_images` flag.
- Math OCR for PDFs (Mathpix / Nougat). Foreshadowed by `--ocr-formulas` flag stub.
- GitHub repo ingest (clone + extract README/docs into `articles/raw/`).
- Output rendering (Marp slides, matplotlib visualizations, Mermaid diagrams) and "filing back" generated outputs into the wiki.
- Wiki search engine (web UI / CLI search over wiki for human use).
- Synthetic data + fine-tuning.
- Obsidian Web Clipper integration or Obsidian-dependent workflows.

## Open Questions

These don't block planning but need a call during implementation:

- `wiki/` in `.gitignore` or committed? Recommendation: committed (version LLM-written knowledge alongside sources). Confirm during first commit.
- Default value for retrieval `K` in brainstorm Step 1 (concepts) and Step 2 (complementary articles). Proposed K=3 each; tune after acceptance test #4.
- `--dry-run` on `compile_wiki`: recommended, costs nothing to add.

## Public Interfaces (for downstream plan)

These interfaces are stable contracts the implementation plan will assume:

### Concept article frontmatter (required keys)

```yaml
title: str
slug: str                       # kebab-case, used as filename
aliases: list[str]
status: 'stable' | 'proposed' | 'deprecated'
related_concepts: list[str]     # list of slugs
sources: list[str]              # list of paths under articles/
content_types: list[str]        # subset of methodology|strategy|allocation|risk_control|market_review
last_compiled: ISO8601 date
compile_version: int
```

### Source summary frontmatter (required keys)

```yaml
source_path: str                # path under articles/
title: str
content_type: str
brainstorm_value: 'low' | 'medium' | 'high'
feeds_concepts: list[str]       # list of slugs
ingested: ISO8601 date
last_compiled: ISO8601 date
```

### Article frontmatter additions

```yaml
source_type: 'wechat' | 'web' | 'pdf' | 'html'
has_code: bool
has_math: bool
has_formula_images: bool
extraction_quality: 'full' | 'partial' | 'text_only'
paywalled: bool                 # web only
```

### Agent tool signatures (new)

```python
compile_wiki(mode: Literal['incremental', 'rebuild'] = 'incremental',
             dry_run: bool = False) -> CompileReport

list_concepts(status: Literal['all', 'stable', 'proposed', 'deprecated'] = 'all'
              ) -> list[ConceptSummary]

set_concept_status(slug: str,
                   status: Literal['stable', 'deprecated', 'deleted'],
                   reason: str) -> StatusUpdate

audit_wiki() -> WikiLintReport

read_wiki(target: str) -> WikiContent   # target ∈ {'index', concept_slug, source_id}
```
