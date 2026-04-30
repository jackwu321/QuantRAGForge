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

### Pipeline Flow

```
WeChat URL / Web URL / PDF / HTML
        |
        v
  [1. Ingest] ──> articles/raw/{dir}/article.md + source.json
        |         (auto-detects source type; warns on previously rejected URLs)
        v
  [2. Enrich] ──> LLM fills idea_blocks, transfer_targets, failure_modes, etc.
        |         (concurrent processing, configurable via LLM_CONCURRENCY)
        v
  [3. Review] ──> Human reviews raw materials only; agent maintains the wiki
        |
        v                              ┌──> rejected ──> recorded + deleted
  [4. Status] ──> reviewed / high_value / rejected
        |                              └──> reviewed or high_value
        v
  [5. Sync]   ──> Move to articles/reviewed/ or articles/high-value/
        |
        v
  [6. Compile Wiki] ──> wiki/concepts/<concept>.md, wiki/sources/<src>.md
        |              + wiki/state.json (hashes, scores, freshness)
        |              + wiki/lint_report.json (auto-run audit)
        v
  [7. Embed]  ──> ChromaDB index over articles + wiki entries
        |         (kb_layer + status + confidence/importance/freshness in metadata)
        v
  [8. Query]  ──> Brainstorm: Chroma-filtered concept retrieval first
        |         (where kb_layer=wiki_concept AND status=stable),
        |         reranked by state.json memory score,
        |         then complementary article chunks (excluding cited sources)
        v
  [9. Rethink] ──> Novelty check + Quality scoring + Rethink Report
```

### Product stance: agent-first wiki

The wiki layer is operational memory for the agent, not a notebook the human edits. The human role is:

1. Provide high-quality raw materials (URLs, PDFs, HTML).
2. Review brainstorm/research outputs.

The agent autonomously:
- compiles concept articles and source summaries (`compile_wiki`)
- maintains structured scoring metadata (`wiki/state.json`: confidence, importance, freshness, conflicts, retrieval hints)
- runs health audits (`audit_wiki` / auto-run after compile) and falls back to article-only retrieval when the wiki is unhealthy
- only surfaces *exceptions* to the human (proposed concepts, ambiguous merges, conflicts) — not routine concept approvals

Markdown remains the inspectable interface; `wiki/state.json` and ChromaDB metadata are the operational substrate.

### Agent Layer

The LangGraph ReAct agent provides 13 tools:

| Tool | Description |
|------|-------------|
| `ingest_article` | Ingest from URL (auto: WeChat / web / PDF), batch URLs, HTML file, PDF file, PDF URL |
| `enrich_articles` | LLM-powered structured enrichment (concurrent, with `limit` support) |
| `list_articles` | List articles by stage (raw/reviewed/high-value) |
| `review_articles` | Show enriched articles ready for review |
| `set_article_status` | Batch update article status (`reviewed`, `high_value`, `rejected`) |
| `sync_articles` | Move articles based on frontmatter status; delete rejected |
| `embed_knowledge` | Build/update ChromaDB vector index over articles + wiki |
| `query_knowledge_base` | RAG Q&A or brainstorm; brainstorm uses wiki concepts first |
| `compile_wiki` | Compile/update wiki (incremental or rebuild); auto-runs lint |
| `audit_wiki` | Wiki health report: stale concepts, unsupported claims, duplicates |
| `list_concepts` | List wiki concepts by status (stable / proposed / deprecated) |
| `set_concept_status` | Override: approve/deprecate/delete a concept (escape hatch) |
| `read_wiki` | Read INDEX.md / a concept article / a source summary |

### Rethink Layer

A post-generation validation layer that runs automatically in brainstorm mode:

1. **Idea Parsing** — Extracts structured ideas from LLM output (EN/CN formats)
2. **Novelty Check** — Embeds each idea and queries ChromaDB for similar existing articles (threshold: 0.75)
3. **Quality Scoring** — Traceability (heuristic) + Coherence & Actionability (LLM-as-judge)
4. **Rethink Report** — Appended to output with per-idea scores and reasoning

### Wiki Layer (agent operational memory)

LLM-written concept articles synthesized from your raw articles, plus structured scoring metadata:

- `wiki/concepts/<slug>.md` — concept articles (e.g. `momentum-strategies.md`). Each has `## Synthesis`, `## Definition`, and structured sections. **Bullets in structured sections must end with `[<source_basename>]` source anchors** so every claim is traceable.
- `wiki/sources/<article-id>.md` — short summaries of raw articles (mechanically derived from frontmatter).
- `wiki/INDEX.md` — auto-maintained TOC.
- `wiki/state.json` — machine-readable: per-source content hashes (idempotency), per-concept scores (confidence, importance, freshness, conflicts, retrieval hints).
- `wiki/lint_report.json` — last health audit.

**Lifecycle:**
- Seeded: 7 starter concepts (factor-models, factor-timing, regime-detection, momentum-strategies, etf-rotation, risk-parity, volatility-targeting).
- New articles either map to existing concepts (recompiled) or trigger an auto-proposed new concept. High-confidence proposals stabilize automatically; low-confidence/conflicting ones land as `proposed` exceptions.
- `compile_wiki` is content-hash idempotent: rerunning over unchanged articles produces zero LLM calls.
- `audit_wiki` blocks brainstorm only when an `error`-severity issue exists (e.g. unsupported claims, malformed concept).

**Brainstorm impact:** queries pull `wiki_concept` blocks from ChromaDB filtered to `status=stable`, reranked by memory score (vector similarity + confidence + importance + freshness − conflicts), then complementary article chunks (excluding sources already cited by the wiki concepts). Falls back to pure-vector retrieval when the wiki is empty/sparse or unhealthy.

## File Structure

```
QuantRAGForge/
├── agent/                          # LangGraph agent layer
│   ├── __init__.py
│   ├── graph.py                    # Agent creation (ReAct pattern)
│   ├── prompts.py                  # System prompt
│   └── tools.py                    # 13 agent tools
├── wiki/                           # LLM-maintained agent memory
│   ├── INDEX.md                    # auto-maintained TOC
│   ├── state.json                  # source hashes, concept scores
│   ├── lint_report.json            # last health audit
│   ├── concepts/                   # one .md per concept
│   └── sources/                    # one .md per raw article (short summary)
├── _wechat.py                      # WeChat-specific extraction
├── _web_extract.py                 # Generic web extraction (trafilatura)
├── _pdf_extract.py                 # PDF extraction (pypdf)
├── _code_math.py                   # Code/math preservation utilities
├── ingest_source.py                # Unified ingest dispatcher
├── wiki_schemas.py                 # Concept/source schemas; PyYAML frontmatter
├── wiki_seed.py                    # Seed taxonomy + bootstrap
├── wiki_state.py                   # Machine state manifest + scoring
├── wiki_compile.py                 # compile_wiki orchestrator
├── wiki_compile_llm.py             # assign_concepts, recompile_concept
├── wiki_index.py                   # INDEX.md generator
├── wiki_lint.py                    # Health checks + audit_wiki backend
├── templates/                      # Article markdown templates
│   ├── research-note-template.md
│   └── strategy-note-template.md
├── tests/                          # Test suite (unittest)
│   ├── robustness/                 # Robustness & edge-case tests
│   │   ├── conftest.py             # Shared fixtures and base classes
│   │   ├── test_layer1_tool_robustness.py
│   │   ├── test_layer2_workflow_integration.py
│   │   ├── test_layer3_agent_routing.py
│   │   └── test_layer4_llm_api_robustness.py
│   ├── test_agent_graph.py
│   ├── test_agent_tools.py
│   ├── test_brainstorm_from_kb.py
│   ├── test_build_catalog.py
│   ├── test_embed_knowledge_base.py
│   ├── test_enrich_articles_with_llm.py
│   ├── test_ingest_wechat_article.py
│   ├── test_rethink_layer.py
│   └── test_sync_articles_by_status.py
├── docs/                           # Design specs and usage guides
│   ├── brainstorm-cli-usage.md
│   ├── brainstorm-output-spec.md
│   ├── embed-knowledge-base-usage.md
│   ├── ingest-script-usage.md
│   ├── ingestion-workflow.md
│   ├── llm-enrichment-usage.md
│   └── metadata-schema.md
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

### 3. Ingest Your First Article

```bash
# Single URL
python3 ingest_wechat_article.py --url "https://mp.weixin.qq.com/s/..."

# Batch from a file (one URL per line)
python3 ingest_wechat_article.py --url-list urls.txt

# From a saved HTML file
python3 ingest_wechat_article.py --html-file saved.html
```

### 4. Enrich with LLM

```bash
python3 enrich_articles_with_llm.py                    # all raw articles (concurrent)
python3 enrich_articles_with_llm.py --limit 10         # first 10 only
python3 enrich_articles_with_llm.py --concurrency 5    # 5 parallel LLM requests
python3 enrich_articles_with_llm.py --dry-run           # preview only
```

### 5. Build Vector Index

```bash
python3 embed_knowledge_base.py
```

### 6. Query and Brainstorm

```bash
# Factual Q&A
python3 brainstorm_from_kb.py ask --query "What momentum factors are discussed?"

# Brainstorm new ideas (with Rethink Layer)
python3 brainstorm_from_kb.py brainstorm --query "How to combine momentum and volatility timing for ETF rotation?"

# Show retrieved context only (dry run)
python3 brainstorm_from_kb.py brainstorm --query "..." --dry-run
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
Agent: Ingested 3/3 articles successfully.

You: enrich the first 3 raw articles
Agent: [1/3] ok  [2/3] ok  [3/3] ok — Enriched 3/3 articles.

You: review the new articles
Agent: [Shows enriched articles with content types and summaries]

You: set articles 1 and 3 as high_value, article 2 as rejected (low research value)
Agent: Updated 3 articles. Article 2 recorded as rejected.

You: sync and rebuild the index
Agent: Synced — 2 moved, 1 rejected (deleted). Rebuilt vector index.

You: ingest url2 again
Agent: WARNING — url2 was previously rejected: "文章标题" (reason: low research value).
       Use force=True to re-ingest.

You: brainstorm: how to combine momentum with volatility timing
Agent: [Generates ideas + Rethink Report with novelty/quality scores]
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

| Status | Directory | Description |
|--------|-----------|-------------|
| `raw` | `articles/raw/` | Ingested, pending enrichment and review |
| `reviewed` | `articles/reviewed/` | Human-reviewed, included in vector index |
| `high_value` | `articles/high-value/` | High research value, included in vector index |
| `rejected` | *(deleted)* | Low value — removed from KB, source URL recorded to prevent re-ingestion |

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

- **Inspiration over execution** — The knowledge base serves idea combination, not backtested trading signals
- **Agent-first wiki** — Routine wiki maintenance is the agent's job, not the human's. The human curates raw materials and reviews brainstorm output
- **Hybrid memory: Markdown + structured state** — Markdown is the inspectable interface; `wiki/state.json` and ChromaDB metadata are the operational substrate (selective injection, scoring, freshness decay, conflict tracking)
- **Per-claim provenance** — Every bullet in a concept article ends with `[<source_basename>]`; un-anchored bullets fail lint and lower confidence
- **Content-hash idempotency** — `compile_wiki` reruns produce zero LLM calls when source hashes are unchanged (no `mtime` or date guessing)
- **Card + idea blocks** — Full articles preserved, with extracted reusable idea units
- **Complementary retrieval** — Brainstorm mode prioritizes complementary (not similar) content; wiki concepts surface first, complementary article chunks fill in
- **Traceable ideas** — Every generated idea must cite which source articles inspired it
- **Graceful degradation** — Every component handles missing dependencies without crashing; `audit_wiki` errors push brainstorm to article-only fallback
- **CLI-first ingest** — Web URLs, WeChat URLs, local HTML, local PDFs, and remote PDFs all ingest via the same dispatcher. No Obsidian Web Clipper required
- **Self-healing vector store** — Automatic SQLite integrity check before each ChromaDB operation; corrupted stores are cleaned up and rebuilt transparently

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
