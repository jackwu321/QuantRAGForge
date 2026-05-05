# QuantRAGForge: AI-Powered Quant Research Knowledge Base & Brainstorm Agent

<p align="center">
  <a href="#features">Features</a> |
  <a href="#architecture">Architecture</a> |
  <a href="#quick-start">Quick Start</a> |
  <a href="#agent-usage">Agent Usage</a> |
  <a href="#configuration">Configuration</a> |
  <a href="#running-tests">Tests</a> |
  <a href="#contributing">Contributing</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License">
  <img src="https://img.shields.io/badge/LLM-OpenAI_Compatible-orange.svg" alt="LLM">
  <img src="https://img.shields.io/badge/vector_store-ChromaDB-purple.svg" alt="ChromaDB">
</p>

---

**QuantRAGForge** is an open-source AI agent that turns WeChat articles and research reports into a structured, searchable knowledge base for quantitative investment research. It ingests articles, enriches them with LLM-generated metadata, builds a vector index, and supports RAG-based Q&A and brainstorming for new strategy ideas — with a built-in **Rethink Layer** that validates idea novelty and quality before output.

> The goal is **research inspiration and cross-document idea combination**, not producing trade-ready strategies.

## Features

- **Multi-source Ingestion** — Ingest from single URLs, batch URL lists, or local HTML files; warns on re-ingesting previously rejected sources
- **LLM Enrichment** — Automatically extract structured fields: idea blocks, transfer targets, combination hooks, failure modes, and more. Concurrent processing with configurable parallelism
- **Hybrid RAG Retrieval** — Keyword + vector + RRF fusion retrieval across your knowledge base
- **Brainstorm Mode** — Generate new strategy ideas by combining insights from multiple articles
- **Rethink Layer** — Post-generation validation that checks idea novelty (via vector similarity) and scores quality (traceability, coherence, actionability)
- **Article Quality Control** — Mark articles as `rejected` to remove from KB and prevent re-ingestion; review tool shows only enriched articles
- **Interactive Agent** — LangGraph ReAct agent with 8 tools for full pipeline management, with real-time progress streaming
- **Provider-Agnostic** — Works with any OpenAI-compatible LLM API (Zhipu GLM, DeepSeek, Moonshot, Qwen, OpenAI, Ollama, etc.)
- **Local-First** — All data stored locally as Markdown files + ChromaDB vectors

## Architecture

QuantRAGForge follows Andrej Karpathy's [LLM-built knowledge base method](https://karpathy.bearblog.dev/) prescription with three durable layers and three operational verbs. Vector RAG is preserved as supporting substrate, not the primary retrieval path.

### Layout

```
raw/      — incoming source articles (one dir per article: article.md + source.json + images/)
wiki/     — LLM-built Markdown memory (the primary query surface)
            ├── INDEX.md          — auto-maintained table of contents
            ├── state.json        — content hashes, concept scores, retrieval hints
            ├── lint_report.json  — last health audit
            ├── concepts/<slug>.md
            ├── sources/<basename>.md
            ├── queries/<date>_<slug>_<mode>.md   — query → wiki feedback log
            └── maintenance_report.md             — last `kb lint --maintain` output
schema/   — rules the LLM and tools follow:
            concept-schema.md, source-schema.md, wiki-structure.md, operations.md
vector_store/  — ChromaDB substrate, used as fallback only
```

Articles live **flat** under `raw/`. The frontmatter `status` field (`raw`, `reviewed`, `high_value`, `rejected`) is the source of truth — there is no directory-as-status convention.

### Three operations

```
                                              ┌──> wiki/concepts/<slug>.md
                                              ├──> wiki/sources/<basename>.md
WeChat URL / Web URL / PDF / HTML             ├──> wiki/INDEX.md
        |                                     ├──> wiki/state.json
        v                                     │    (hashes, scores, freshness, retrieval hints)
  [kb ingest] ──> raw/<dir>/article.md + source.json
        |                                     ▲
        v                                     │
  [kb compile]  ── schema/-injected LLM ──────┘
  (auto after ingest)
        |
        v
  [kb embed]  ── ChromaDB substrate over raw/ + wiki/
  (auto after compile)
        |
        v
  [kb query]  ── wiki-first retrieval (INDEX → matched concepts → source summaries)
        |        RAG runs ONLY when wiki has no relevant concept or audit reports degradation
        |        (mode: ask | brainstorm; brainstorm runs Rethink Layer post-generation)
        |
        v
  ┌─ outputs/brainstorms/<date>_<slug>_<mode>.md
  └─ wiki/queries/<date>_<slug>_<mode>.md  ── append_query_log:
                                              cited concepts get importance bump
                                              + retrieval_hints append in state.json

  [kb lint]              ── schema-compliance audit (frontmatter, sections, source anchors)
  [kb lint --fix]        ── LLM auto-repair of schema-noncompliant concepts
  [kb lint --maintain]   ── gap analysis: unmapped source clusters, under-supported concepts,
                            stale concepts → suggested ingestion queries / new brainstorm prompts
                            (writes wiki/maintenance_report.md)
  [kb lint --maintain --apply]  ── apply query-derived state updates idempotently
```

### Wiki-first retrieval (load-bearing invariant)

`brainstorm_from_kb.retrieve_blocks` gates on `_should_use_wiki_memory(notes) and _wiki_is_healthy_for_query(kb_root)`. There is **no** `command == "brainstorm"` check — both `ask` and `brainstorm` pull `kb_layer=wiki_concept` blocks first (Chroma-filtered → state-score reranked → lexical fallback), then fill remaining slots with complementary article chunks excluding sources already cited by the surfaced concepts. Pure-vector retrieval is the fallback, not the default.

### Query → wiki feedback

Every `kb query` (unless `--no-file-back`) files a structured note into `wiki/queries/<date>_<slug>_<mode>.md` and bumps `state.json:concepts.<slug>.importance` + `retrieval_hints` for cited concepts. `kb lint --maintain` later distills these query logs into proposed concept-page improvements. This realizes Karpathy's *"my own explorations and queries always 'add up' in the knowledge base."*

### Schema is enforced, not advisory

`schema/concept-schema.md` and `schema/source-schema.md` define required frontmatter fields, valid enum values, and required section headers. `wiki_lint` checks these on every run (severity: warning), and `kb lint --fix` runs an LLM auto-repair pass via `recompile_concept` for schema-noncompliant concepts. The schema text is also injected into compile-time prompts so the LLM is told the source-anchor invariant.

### Rethink Layer

A post-generation validation layer that runs automatically in brainstorm mode:

1. **Idea Parsing** — Extracts structured ideas from LLM output (EN/CN formats)
2. **Novelty Check** — Embeds each idea and queries ChromaDB for similar existing articles (threshold: 0.75)
3. **Quality Scoring** — Traceability (heuristic) + Coherence & Actionability (LLM-as-judge)
4. **Rethink Report** — Appended to output with per-idea scores and reasoning

### Agent Layer

The LangGraph ReAct agent provides 12 tools:

| Tool | Description |
|------|-------------|
| `ingest_article` | Ingest from URL (auto: WeChat / web / PDF), batch URLs, HTML file, PDF file, PDF URL |
| `enrich_articles` | LLM-powered structured enrichment (concurrent, with `limit` support) |
| `list_articles` | List articles by status (raw / reviewed / high_value); all live flat under `raw/` |
| `review_articles` | Show enriched articles ready for review |
| `set_article_status` | Update article status field in frontmatter |
| `embed_knowledge` | Build/update ChromaDB vector index over `raw/` + `wiki/` |
| `query_knowledge_base` | Wiki-first Q&A or brainstorm; both modes pull stable wiki concepts before vectors |
| `compile_wiki` | Compile/update wiki (incremental or rebuild); auto-runs lint |
| `audit_wiki` | Wiki health report: schema violations, stale concepts, unsupported claims, duplicates |
| `list_concepts` | List wiki concepts by status (stable / proposed / deprecated) |
| `set_concept_status` | Override: approve/deprecate/delete a concept (escape hatch) |
| `read_wiki` | Read INDEX.md / a concept article / a source summary |

## File Structure

```
QuantRAGForge/
├── kb.py                           # Unified CLI: ingest | query | lint | compile | embed
├── raw/                            # Incoming source articles, flat (one dir per article)
├── wiki/                           # LLM-built Markdown memory
│   ├── INDEX.md                    # auto-maintained TOC
│   ├── state.json                  # content hashes, concept scores, retrieval hints
│   ├── lint_report.json            # last health audit
│   ├── maintenance_report.md       # last `kb lint --maintain` output
│   ├── concepts/                   # one .md per concept
│   ├── sources/                    # one .md per raw article (mechanically derived)
│   └── queries/                    # one .md per filed `kb query` (Step 7 feedback log)
├── schema/                         # Rules followed by LLM and tools
│   ├── concept-schema.md
│   ├── source-schema.md
│   ├── wiki-structure.md
│   └── operations.md
├── agent/                          # LangGraph agent layer (12 tools)
│   ├── graph.py
│   ├── prompts.py
│   └── tools.py
├── _wechat.py                      # WeChat-specific extraction
├── _web_extract.py                 # Generic web extraction (trafilatura)
├── _pdf_extract.py                 # PDF extraction (pypdf)
├── _code_math.py                   # Code/math preservation utilities
├── ingest_source.py                # Unified ingest dispatcher
├── ingest_wechat_article.py        # WeChat-specific ingest
├── enrich_articles_with_llm.py     # LLM enrichment pipeline
├── kb_shared.py                    # Shared utilities, LLM HTTP client, paths, frontmatter
├── brainstorm_from_kb.py           # query (ask | brainstorm) — wiki-first retrieval
├── rethink_layer.py                # Post-generation novelty + quality validation
├── wiki_schemas.py                 # ConceptArticle / SourceSummary dataclasses
├── wiki_seed.py                    # Seed taxonomy + bootstrap
├── wiki_state.py                   # Machine state manifest + scoring (freshness decay etc.)
├── wiki_compile.py                 # compile_wiki orchestrator (schema-injected, soft-error)
├── wiki_compile_llm.py             # assign_concepts + recompile_concept LLM wrappers
├── wiki_index.py                   # INDEX.md generator
├── wiki_lint.py                    # Schema enforcement + health checks + auto_fix
├── wiki_maintain.py                # append_query_log + run_maintenance (Steps 6 + 7)
├── embed_knowledge_base.py         # ChromaDB substrate over raw/ + wiki/
├── agent_cli.py                    # Interactive ReAct agent CLI
├── templates/                      # Article markdown templates (research-note / strategy-note)
├── tests/                          # unittest suite (262 tests)
│   ├── robustness/                 # Edge-case tests (Layer 1–4)
│   ├── test_kb_cli.py              # kb.py CLI dispatch
│   ├── test_query_wiki_first_ask.py
│   ├── test_wiki_lint_schema.py    # Schema enforcement + auto_fix
│   ├── test_wiki_maintain.py       # Query feedback + maintenance
│   └── test_*.py                   # Per-module coverage
├── docs/                           # Design specs and usage guides
├── agent_cli.py                    # Interactive agent CLI
├── brainstorm_from_kb.py           # RAG Q&A and brainstorm engine
├── embed_knowledge_base.py         # ChromaDB vector indexing
├── enrich_articles_with_llm.py     # LLM enrichment pipeline
├── ingest_wechat_article.py        # Article ingestion (WeChat/HTML)
├── kb_shared.py                    # Shared utilities and config
├── rethink_layer.py                # Post-generation idea validation
├── sync_articles_by_status.py      # Article status-based file sync
├── llm_config.example.env          # Example LLM provider config
├── requirements.txt                # Python dependencies
└── README.md
```

## Quick Start

### 1. Clone and Setup

```bash
git clone https://github.com/jackwu321/QuantRAGForge.git
cd QuantRAGForge

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure LLM Provider

Copy the example config and fill in your API key:

```bash
cp llm_config.example.env .env
# Edit .env with your API key and provider settings
```

Or set environment variables directly:

```bash
export LLM_API_KEY="your-api-key"
export LLM_BASE_URL="https://open.bigmodel.cn/api/paas/v4"  # or any OpenAI-compatible endpoint
export LLM_MODEL="glm-4.7"  # or gpt-4, deepseek-chat, etc.
```

See [llm_config.example.env](llm_config.example.env) for provider-specific examples (DeepSeek, Moonshot, Qwen, OpenAI, Ollama).

### 3. Ingest, Compile, Embed (one command)

```bash
# Single URL — ingest + auto-compile + auto-embed
python3 kb.py ingest --url "https://mp.weixin.qq.com/s/..."

# Skip the auto compile/embed
python3 kb.py ingest --url "..." --no-compile

# Local PDF
python3 kb.py ingest --pdf-file paper.pdf

# Saved WeChat HTML
python3 kb.py ingest --html-file saved.html

# Batch from a list (one URL per line)
python3 kb.py ingest --url-list urls.txt
```

`enrich_articles_with_llm.py` remains a separate step (run before `kb compile` if your raw articles need LLM-derived metadata first):

```bash
python3 enrich_articles_with_llm.py                    # all raw articles (concurrent)
python3 enrich_articles_with_llm.py --limit 10         # first 10 only
python3 enrich_articles_with_llm.py --concurrency 5    # 5 parallel LLM requests
```

### 4. Query (wiki-first)

```bash
# Factual Q&A — wiki concepts first, RAG fallback only
python3 kb.py query --mode ask --query "What momentum factors are discussed?"

# Brainstorm new ideas (with Rethink Layer + query-feedback)
python3 kb.py query --mode brainstorm --query "Combine momentum and volatility timing for ETF rotation"

# Show retrieved context only (dry run)
python3 kb.py query --mode brainstorm --query "..." --dry-run

# Run a debug query without filing it back into wiki/queries/
python3 kb.py query --mode ask --query "..." --no-file-back
```

### 5. Lint + Maintain

```bash
# Schema + health audit
python3 kb.py lint

# LLM auto-repair of schema-noncompliant concepts
python3 kb.py lint --fix

# Gap analysis: unmapped sources, under-supported concepts, stale concepts
python3 kb.py lint --maintain

# Apply query-derived state updates (idempotent)
python3 kb.py lint --maintain --apply
```

## Agent Usage

The interactive agent manages the full pipeline through natural language:

```bash
# Interactive mode
python3 agent_cli.py

# Single command
python3 agent_cli.py --query "ingest this article: https://mp.weixin.qq.com/s/..."
python3 agent_cli.py --query "list all articles"
python3 agent_cli.py --query "brainstorm: combine factor timing with risk parity"
```

### Example Agent Workflow

```
You: ingest these articles: url1, url2, url3
Agent: Ingested 3/3 articles. Auto-compiled wiki and refreshed vector index.

You: enrich the first 3 raw articles
Agent: [1/3] ok  [2/3] ok  [3/3] ok — Enriched 3/3 articles.

You: review the new articles
Agent: [Shows enriched articles with content types and summaries]

You: set articles 1 and 3 as high_value, article 2 as rejected (low research value)
Agent: Updated 3 articles. Article 2 recorded as rejected (URL noted to prevent re-ingest).

You: ingest url2 again
Agent: WARNING — url2 was previously rejected: "文章标题" (reason: low research value).
       Use force=True to re-ingest.

You: brainstorm: how to combine momentum with volatility timing
Agent: [Wiki concepts surfaced first; complementary articles fill remaining slots]
       [LLM generates ideas; Rethink Layer scores novelty + quality]
       [Query filed back into wiki/queries/; cited concepts gain importance]
```

## Configuration

### LLM Provider

QuantRAGForge works with **any OpenAI-compatible API**. Configure via `.env` file (auto-loaded) or environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_API_KEY` | — | Your API key |
| `LLM_BASE_URL` | `https://open.bigmodel.cn/api/paas/v4` | API base URL |
| `LLM_MODEL` | `glm-4.7` | Chat model name |
| `LLM_EMBEDDING_MODEL` | `embedding-3` | Embedding model name |
| `LLM_CONNECT_TIMEOUT` | `10` | Connection timeout (seconds) |
| `LLM_READ_TIMEOUT` | `120` | Read timeout (seconds) |
| `LLM_MAX_RETRIES` | `2` | Max retry attempts |
| `LLM_CONCURRENCY` | `3` | Max parallel LLM requests for enrichment |

Legacy `ZHIPU_*` prefixed variables are also supported as fallbacks.

### Content Classification

Each article is classified with exactly one `content_type`:

| Type | Description |
|------|-------------|
| `methodology` | Research frameworks, models, factor logic |
| `strategy` | Trading logic with entry/exit rules and backtest |
| `allocation` | Portfolio construction, rotation, ETF allocation |
| `risk_control` | Risk management, drawdown control, volatility targeting |
| `market_review` | Market commentary, sector reviews |

### Article Status Lifecycle

All articles live flat under `raw/`. The frontmatter `status` field is the source of truth.

| Status | Description |
|--------|-------------|
| `raw` | Ingested, pending enrichment and review |
| `reviewed` | Human-reviewed; included in wiki compilation and vector index |
| `high_value` | High research value; included in wiki compilation and vector index |
| `rejected` | Low value — removed from KB, source URL recorded to prevent re-ingestion |

## Running Tests

### Unit Tests

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

### Robustness Tests

The `tests/robustness/` suite covers edge cases and failure modes across four layers:

| File | What it tests |
|------|---------------|
| `test_layer1_tool_robustness.py` | Agent tools with malformed/missing inputs |
| `test_layer2_workflow_integration.py` | End-to-end pipeline with bad data |
| `test_layer3_agent_routing.py` | Agent routing under unexpected queries |
| `test_layer4_llm_api_robustness.py` | LLM API timeouts, retries, and failures |

```bash
python3 -m unittest discover -s tests/robustness -p 'test_*.py' -v
```

## Design Principles

- **Wiki-first, RAG-as-substrate** — Both `kb query --mode ask` and `--mode brainstorm` retrieve stable wiki concepts before vectors. ChromaDB runs only as fallback when the wiki is empty/sparse or `audit_wiki` reports degradation.
- **Three durable verbs** — `kb ingest`, `kb query`, `kb lint` per Karpathy's prescription. `compile` and `embed` are internal operations auto-run by `ingest`.
- **Schema is enforced** — `schema/concept-schema.md` and `schema/source-schema.md` define required frontmatter fields, valid enums, and required section headers. `wiki_lint` checks these on every run; `kb lint --fix` runs an LLM auto-repair pass.
- **Inspiration over execution** — The knowledge base serves idea combination, not backtested trading signals.
- **Hybrid memory: Markdown + structured state** — Markdown is the inspectable interface; `wiki/state.json` and ChromaDB metadata are the operational substrate (scoring, freshness decay, conflict tracking).
- **Per-claim provenance** — Every bullet in a concept article ends with `[<source_basename>]`; un-anchored bullets fail lint and lower confidence.
- **Content-hash idempotency** — `kb compile` reruns produce zero LLM calls when source hashes are unchanged (no `mtime`, no date guessing).
- **Queries compound** — Every `kb query` files into `wiki/queries/` and bumps state.json scoring for cited concepts. `kb lint --maintain` distills the query log into proposed concept-page improvements.
- **Complementary retrieval** — Wiki concepts surface first, then complementary article chunks fill remaining slots (excluding sources already cited by concepts).
- **Graceful degradation** — Every component handles missing dependencies without crashing; `audit_wiki` errors push the wiki-first path to article-only fallback.
- **Self-healing vector store** — Automatic SQLite integrity check before each ChromaDB operation; corrupted stores are cleaned up and rebuilt transparently.

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Write tests for new functionality
4. Ensure all tests pass (`python3 -m unittest discover -s tests -p 'test_*.py'`)
5. Commit your changes
6. Open a Pull Request

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

## Disclaimer

QuantRAGForge is a research tool for generating investment strategy ideas. It does **not** produce trade-ready strategies or financial advice. All generated ideas require independent validation, backtesting, and risk assessment before any real-world application. Use at your own risk.
