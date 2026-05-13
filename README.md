# Quant_LLM_Wiki: A Karpathy-shaped wiki-first knowledge base for quant research

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

**Quant_LLM_Wiki** turns WeChat articles, web pages, and research PDFs into an LLM-built Markdown knowledge base for quantitative investment research. It follows Andrej Karpathy's [LLM-built KB method](https://karpathy.bearblog.dev/): a `raw/` ingest layer, an LLM-compiled `wiki/` of concept articles, and a `schema/` that the LLM and tools both follow. Vector RAG is preserved as a fallback substrate, **not** the primary retrieval path. Three durable verbs — `ingest`, `query`, `lint` — drive everything. A built-in **Rethink Layer** scores novelty and quality of brainstormed ideas before output.

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

The system has three durable layers and three operational verbs. Vector RAG is preserved as supporting substrate, not the primary retrieval path.

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
            └── maintenance_report.md             — last `qlw lint --maintain` output
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
  [qlw ingest] ──> raw/<dir>/article.md + source.json
        |                                     ▲
        v                                     │
  [qlw compile]  ── schema/-injected LLM ─────┘
  (auto after ingest)
        |
        v
  [qlw embed]  ── ChromaDB substrate over raw/ + wiki/
  (auto after compile)
        |
        v
  [qlw ask / qlw brainstorm]  ── wiki-first retrieval (INDEX → matched concepts → source summaries)
        |        RAG runs ONLY when wiki has no relevant concept or audit reports degradation
        |        (brainstorm runs Rethink Layer post-generation)
        |
        v
  ┌─ outputs/brainstorms/<date>_<slug>_<mode>.md
  └─ wiki/queries/<date>_<slug>_<mode>.md  ── append_query_log:
                                              cited concepts get importance bump
                                              + retrieval_hints append in state.json

  [qlw lint]              ── schema-compliance audit (frontmatter, sections, source anchors)
  [qlw lint --fix]        ── LLM auto-repair of schema-noncompliant concepts
  [qlw lint --maintain]   ── gap analysis: unmapped source clusters, under-supported concepts,
                            stale concepts → suggested ingestion queries / new brainstorm prompts
                            (writes wiki/maintenance_report.md)
  [qlw lint --maintain --apply]  ── apply query-derived state updates idempotently
```

### Wiki-first retrieval (load-bearing invariant)

`brainstorm_from_kb.retrieve_blocks` gates on `_should_use_wiki_memory(notes) and _wiki_is_healthy_for_query(kb_root)`. There is **no** `command == "brainstorm"` check — both `ask` and `brainstorm` pull `kb_layer=wiki_concept` blocks first (Chroma-filtered → state-score reranked → lexical fallback), then fill remaining slots with complementary article chunks excluding sources already cited by the surfaced concepts. Pure-vector retrieval is the fallback, not the default.

### Query → wiki feedback

Every `qlw ask` / `qlw brainstorm` run writes the answer to `outputs/brainstorms/` AND files a one-line query log at `wiki/queries/<YYYY-MM-DD>_<slug>_<mode>.md`. The log captures the query text, mode, output filename, and which concepts/sources were cited. `qlw lint --maintain` digests these logs to surface gaps — under-supported concepts, unmapped sources, and stale areas worth backfilling. Pass `--no-query-log` to opt out of filing.

This realizes Karpathy's *"my own explorations and queries always 'add up' in the knowledge base."*

### Schema is enforced, not advisory

`schema/concept-schema.md` and `schema/source-schema.md` define required frontmatter fields, valid enum values, and required section headers. `wiki_lint` checks these on every run (severity: warning), and `qlw lint --fix` runs an LLM auto-repair pass via `recompile_concept` for schema-noncompliant concepts. The schema text is also injected into compile-time prompts so the LLM is told the source-anchor invariant.

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
Quant_LLM_Wiki/
├── pyproject.toml                  # Package metadata + `qlw` console_script entry point
├── requirements.txt                # Python dependencies (kept for non-pip-install users)
├── llm_config.example.env          # Example LLM provider config
├── README.md
├── LICENSE
├── quant_llm_wiki/                 # Installable Python package (all functionality here)
│   ├── __init__.py
│   ├── cli.py                      # `qlw` dispatcher (9 subcommands)
│   ├── shared.py                   # Shared utilities, LLM HTTP client, frontmatter
│   ├── paths.py                    # KB root resolution (resolve_kb_root)
│   ├── enrich.py                   # LLM enrichment pipeline
│   ├── embed.py                    # ChromaDB substrate over raw/ + wiki/
│   ├── sync.py                     # Article status-based file sync
│   ├── ingest/
│   │   ├── source.py               # Unified ingest dispatcher (WeChat / web / PDF / HTML)
│   │   ├── wechat.py               # WeChat-specific ingest
│   │   ├── _wechat.py              # WeChat HTML extraction internals
│   │   ├── web.py                  # Generic web extraction (trafilatura)
│   │   ├── pdf.py                  # PDF extraction (pypdf + pdfplumber)
│   │   └── code_math.py            # Code/math preservation utilities
│   ├── wiki/
│   │   ├── compile.py              # compile_wiki orchestrator (schema-injected, soft-error)
│   │   ├── compile_llm.py          # assign_concepts + recompile_concept LLM wrappers
│   │   ├── index.py                # INDEX.md generator
│   │   ├── lint.py                 # Schema enforcement + health checks + auto_fix
│   │   ├── maintain.py             # append_query_log + run_maintenance (Steps 6 + 7)
│   │   ├── schemas.py              # ConceptArticle / SourceSummary dataclasses
│   │   ├── seed.py                 # Seed taxonomy + bootstrap
│   │   └── state.py                # Machine state manifest + scoring (freshness decay etc.)
│   ├── query/
│   │   ├── brainstorm.py           # query (ask | brainstorm) — wiki-first retrieval
│   │   └── rethink.py              # Post-generation novelty + quality validation
│   └── agent/                      # LangGraph agent layer
│       ├── cli.py                  # Interactive ReAct agent CLI
│       ├── graph.py
│       ├── prompts.py
│       └── tools.py
├── raw/                            # Incoming source articles, flat (one dir per article)
├── wiki/                           # LLM-built Markdown memory
│   ├── INDEX.md                    # auto-maintained TOC
│   ├── state.json                  # content hashes, concept scores, retrieval hints
│   ├── lint_report.json            # last health audit
│   ├── maintenance_report.md       # last `qlw lint --maintain` output
│   ├── concepts/                   # one .md per concept
│   ├── sources/                    # one .md per raw article (mechanically derived)
│   └── queries/                    # one .md per filed `qlw ask`/`qlw brainstorm` (Step 7 feedback log)
├── schema/                         # Rules followed by LLM and tools
│   ├── concept-schema.md
│   ├── source-schema.md
│   ├── wiki-structure.md
│   └── operations.md
├── templates/                      # Article markdown templates (research-note / strategy-note)
├── tests/                          # unittest suite
│   ├── robustness/                 # Edge-case tests (Layer 1–4)
│   ├── test_qlw_cli.py             # qlw CLI dispatch
│   ├── test_query_wiki_first_ask.py
│   ├── test_wiki_lint_schema.py    # Schema enforcement + auto_fix
│   ├── test_wiki_maintain.py       # Query feedback + maintenance
│   └── test_*.py                   # Per-module coverage
└── docs/                           # Design specs and usage guides
```

> **Repo / package / command names.** Repo: `Quant_LLM_Wiki`. Package: `quant_llm_wiki`. Console command: `qlw` (installed via `pipx install quant-llm-wiki` or `pip install -e .`). All 9 subcommands — `ingest`, `enrich`, `embed`, `sync`, `ask`, `brainstorm`, `agent`, `lint`, `compile` — are unified under `qlw`. pipx users get the full CLI surface; for best wiki-compile/lint quality they should also fetch `schema/` and `templates/` into their workspace (see [Quick Start §2](#2-pick-a-workspace)).

### Command Renaming (vs. previous versions)

The standalone scripts at the repo root have moved into `quant_llm_wiki/` and are dispatched through a single `qlw` CLI:

| Old | New |
|-----|-----|
| `qlw ingest --url X` | `qlw ingest --url X` |
| `qlw enrich --limit 10` | `qlw enrich --limit 10` |
| `qlw embed` | `qlw embed` |
| `qlw sync` | `qlw sync` |
| `qlw ask --query Q` | `qlw ask --query Q` |
| `qlw brainstorm --query Q` | `qlw brainstorm --query Q` |
| `qlw agent` | `qlw agent` |

Install with `pip install -e .` to put `qlw` on PATH; otherwise use `python -m quant_llm_wiki.cli <subcmd>`.

## Quick Start

Quant_LLM_Wiki supports two install flows. **Pick one and follow that column** — the rest of the docs use the same `qlw <subcmd>` commands regardless.

| | **A. pipx (end-users)** | **B. git clone (developers)** |
|---|---|---|
| When to use | You just want to run `qlw` and build a personal KB. | You want to read/edit the source, run tests, contribute. |
| Repo files locally? | No | Yes (full tree under your clone) |
| Workspace = | Any dir you `cd` into (or `$QLW_KB_ROOT`) | The clone itself by default |
| `.env` location | `<workspace>/.env` (auto-loaded from CWD) | `<workspace>/.env` (auto-loaded from CWD) |
| `schema/` + `templates/` | Need a one-time fetch (below) | Already present in the clone |

### 1. Install

#### A. pipx (recommended for end-users)

[`pipx`](https://pipx.pypa.io/) gives you the `qlw` command globally without polluting your system Python and without requiring you to activate a venv:

```bash
# From PyPI
pipx install quant-llm-wiki

# Or directly from GitHub (always tracks main)
pipx install git+https://github.com/jackwu321/Quant_LLM_Wiki.git
```

After install, `qlw` is on your PATH from any shell. Upgrade later with `pipx upgrade quant-llm-wiki`.

> **Requires `pipx` ≥ 1.5 (pip ≥ 25).** Older pipx (e.g. 1.4.3 shipped by Ubuntu 24.04 apt) bundles pip 24.0, which mis-parses `langgraph`'s newer wheel metadata and fails with `ResolutionImpossible: no matching distributions available for your environment: langgraph`. If you hit that, upgrade pipx first:
>
> ```bash
> sudo apt install python3-pip                                          # if pip is missing
> python3 -m pip install --user --upgrade --break-system-packages pipx  # PEP 668 systems
> hash -r
> pipx install quant-llm-wiki
> ```

#### B. git clone + editable install (for development)

```bash
git clone https://github.com/jackwu321/Quant_LLM_Wiki.git
cd Quant_LLM_Wiki

python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Clone-installed users have `schema/`, `templates/`, `llm_config.example.env`, and the test suite available locally.

### 2. Pick a workspace

`qlw` writes data under whichever directory it considers your **KB root**, resolved in this order: explicit `--kb-root` arg → `$QLW_KB_ROOT` env var → current working directory. The same dir holds your `.env`, `raw/`, `wiki/`, `vector_store/`, etc.

#### A. pipx — bootstrap a workspace

```bash
mkdir -p ~/my-kb && cd ~/my-kb         # or any dir you want
export QLW_KB_ROOT="$PWD"              # optional but recommended; add to ~/.bashrc

# One-time fetch: download schema/ + templates/ + llm_config.example.env from the repo.
# Without these, compile/lint still run but skip schema injection — quality is degraded.
curl -fsSL https://github.com/jackwu321/Quant_LLM_Wiki/archive/refs/heads/main.tar.gz \
  | tar xz --strip=1 --wildcards "*/schema/*" "*/templates/*" "*/llm_config.example.env"
```

#### B. git clone — clone IS the workspace

Run `qlw` from inside the clone, or `export QLW_KB_ROOT="$(pwd)"` once. `schema/`, `templates/`, and `llm_config.example.env` are already there — no fetch needed.

### 3. Configure LLM Provider

Quant_LLM_Wiki auto-loads `.env` from these locations (first hit wins): `$QLW_KB_ROOT/.env` → `$(pwd)/.env` → the package directory. The cleanest path for both install flows is to put a `.env` in your workspace.

#### A. pipx workspace

You should have `llm_config.example.env` in your workspace after step 2 (the `curl` line above). Otherwise grab it on demand:

```bash
curl -fsSL https://raw.githubusercontent.com/jackwu321/Quant_LLM_Wiki/main/llm_config.example.env -o llm_config.example.env
cp llm_config.example.env .env
# Edit .env with your API key and provider settings
```

#### B. clone workspace

```bash
cp llm_config.example.env .env
# Edit .env with your API key and provider settings
```

#### Either flow: shell `export` (no .env needed)

```bash
export LLM_API_KEY="your-api-key"
export LLM_BASE_URL="https://open.bigmodel.cn/api/paas/v4"  # or any OpenAI-compatible endpoint
export LLM_MODEL="glm-4.7"                                  # or gpt-4o, deepseek-chat, etc.
```

Persist these in `~/.bashrc` / `~/.zshrc` so every shell sees them. See [llm_config.example.env](llm_config.example.env) for provider-specific examples (DeepSeek, Moonshot, Qwen, OpenAI, Ollama).

### 4. Ingest

Run from your workspace directory (or set `--kb-root` / `$QLW_KB_ROOT`). All output lands under the resolved KB root.

```bash
# Single URL (WeChat / web)
qlw ingest --url "https://mp.weixin.qq.com/s/..."

# Saved WeChat HTML
qlw ingest --html-file saved.html

# Batch from a list (one URL per line)
qlw ingest --url-list urls.txt
```

Each URL has a hard 120 s ceiling; on hit, ingest prints `TIMEOUT <url>: exceeded 120s` and (in batch mode) continues with the next URL. Override via `INGEST_URL_TIMEOUT=<seconds>`. Note: a timed-out URL may leave a partial `raw/<date>_*/` directory behind (same as ordinary `FAILED` cases).

### 5. Enrich + Embed

```bash
qlw enrich                    # all raw articles (concurrent)
qlw enrich --limit 10         # first 10 only
qlw enrich --concurrency 5    # 5 parallel LLM requests

qlw embed                     # build/update ChromaDB vector index
```

Each article enrichment has a hard 360 s ceiling; on hit, the article is recorded as `failed: timeout: exceeded Ns` and the batch continues. Override via `LLM_ARTICLE_TIMEOUT=<seconds>`. Start / done / TIMEOUT / `[llm-retry]` events are printed to **stderr** (separate from the per-completion `[i/N] ... ok|failed` lines on stdout) so you can see what's happening even when the LLM API is slow or backing off.

### 6. Query (wiki-first)

```bash
# Factual Q&A — wiki concepts first, RAG fallback only
qlw ask --query "What momentum factors are discussed?"

# Brainstorm new ideas (with Rethink Layer + query-feedback)
qlw brainstorm --query "Combine momentum and volatility timing for ETF rotation"

# Show retrieved context only (dry run)
qlw brainstorm --query "..." --dry-run
```

### Wiki maintenance commands

> **v0.3.0 migration note.** v0.3.0 unified `kb.py` into `qlw`. If you previously ran `python3 kb.py <cmd>`, run `qlw <cmd>` instead. The `kb query` mode has been split into `qlw ask` and `qlw brainstorm`.
>
> If your repo still uses the legacy `articles/raw/` layout, pass `qlw enrich --articles-root articles/raw` (or move articles into `raw/`) — v0.3.0 unified all subcommands on `<kb-root>/raw/`.

All wiki maintenance commands are available via `qlw` from either install flow (pipx or clone). Pipx users should have fetched `schema/` into their workspace first (see [Quick Start §2](#2-pick-a-workspace)) so `lint`/`compile` get full schema context:

```bash
# Ingest from URL (auto-compile + auto-embed in one shot)
qlw ingest --url "https://mp.weixin.qq.com/s/..."

# Ingest from a local PDF file
qlw ingest --pdf-file paper.pdf

# Ingest from a PDF at a URL
qlw ingest --pdf-url "https://example.com/paper.pdf"

# Schema + health audit
qlw lint
qlw lint --fix                # LLM auto-repair of schema-noncompliant concepts
qlw lint --maintain           # gap analysis: unmapped sources, under-supported, stale
qlw lint --maintain --apply   # apply query-derived state updates (idempotent)

# Manual wiki compile
qlw compile

# Query (ask mode) — outputs land in outputs/brainstorms/ AND a query log goes to wiki/queries/.
# Use --no-query-log to skip the log entry.
qlw ask --query "..."
```

## Agent Usage

The interactive agent manages the full pipeline through natural language:

```bash
# Interactive mode
qlw agent

# Single command
qlw agent --query "ingest this article: https://mp.weixin.qq.com/s/..."
qlw agent --query "list all articles"
qlw agent --query "brainstorm: combine factor timing with risk parity"
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

Quant_LLM_Wiki works with **any OpenAI-compatible API**. Configure via `.env` file (auto-loaded) or environment variables:

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

> Tests live in the repo, not the wheel. Run them from a `git clone` checkout (install path **B**), not from a pipx install.

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

- **Wiki-first, RAG-as-substrate** — Both `qlw ask` and `qlw brainstorm` retrieve stable wiki concepts before vectors. ChromaDB runs only as fallback when the wiki is empty/sparse or `audit_wiki` reports degradation.
- **Three durable verbs** — `qlw ingest`, `qlw ask`/`qlw brainstorm`, `qlw lint` per Karpathy's prescription. `compile` and `embed` are internal operations auto-run by `ingest`.
- **Schema is enforced** — `schema/concept-schema.md` and `schema/source-schema.md` define required frontmatter fields, valid enums, and required section headers. `wiki_lint` checks these on every run; `qlw lint --fix` runs an LLM auto-repair pass.
- **Inspiration over execution** — The knowledge base serves idea combination, not backtested trading signals.
- **Hybrid memory: Markdown + structured state** — Markdown is the inspectable interface; `wiki/state.json` and ChromaDB metadata are the operational substrate (scoring, freshness decay, conflict tracking).
- **Per-claim provenance** — Every bullet in a concept article ends with `[<source_basename>]`; un-anchored bullets fail lint and lower confidence.
- **Content-hash idempotency** — `qlw compile` reruns produce zero LLM calls when source hashes are unchanged (no `mtime`, no date guessing).
- **Queries compound** — Every `qlw ask`/`qlw brainstorm` files into `wiki/queries/` and bumps state.json scoring for cited concepts. `qlw lint --maintain` distills the query log into proposed concept-page improvements.
- **Complementary retrieval** — Wiki concepts surface first, then complementary article chunks fill remaining slots (excluding sources already cited by concepts).
- **Graceful degradation** — Every component handles missing dependencies without crashing; `audit_wiki` errors push the wiki-first path to article-only fallback.
- **Self-healing vector store** — Automatic SQLite integrity check before each ChromaDB operation; corrupted stores are cleaned up and rebuilt transparently.

## Releasing (maintainers)

This repo publishes to PyPI automatically when a `v*.*.*` tag is pushed. The workflow is defined in [`.github/workflows/publish.yml`](.github/workflows/publish.yml) and uses [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/) (OIDC) — no API token is stored in GitHub secrets.

### One-time PyPI setup

Before the first release, configure a "pending publisher" on PyPI:

1. Log in to https://pypi.org/manage/account/publishing/
2. Add a pending publisher with:
   - **PyPI Project Name:** `quant-llm-wiki`
   - **Owner:** `jackwu321`
   - **Repository name:** `Quant_LLM_Wiki`
   - **Workflow filename:** `publish.yml`
   - **Environment name:** `pypi`
3. In GitHub repo settings → Environments, create an environment named `pypi` (no secrets needed; OIDC handles auth).

### Cutting a release

```bash
# 1. Bump version in pyproject.toml (e.g. 0.2.0 -> 0.2.1)
# 2. Commit
git commit -am "release: v0.2.1"
# 3. Tag and push
git tag v0.2.1
git push origin main --tags
```

The workflow will:
1. Verify the tag matches `project.version` in `pyproject.toml`
2. Build sdist + wheel
3. Upload to PyPI via Trusted Publishing

Users then upgrade with `pipx upgrade quant-llm-wiki`.

> **Versioning.** Follow [SemVer](https://semver.org/): bump patch for fixes, minor for new features, major for breaking changes. The tag `v0.2.1` must match `version = "0.2.1"` in `pyproject.toml` exactly, or the workflow aborts before publishing.

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

Quant_LLM_Wiki is a research tool for generating investment strategy ideas. It does **not** produce trade-ready strategies or financial advice. All generated ideas require independent validation, backtesting, and risk assessment before any real-world application. Use at your own risk.
