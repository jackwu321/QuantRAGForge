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

- **Multi-source Ingestion** — Ingest from single URLs, batch URL lists, or local HTML files
- **LLM Enrichment** — Automatically extract structured fields: idea blocks, transfer targets, combination hooks, failure modes, and more
- **Hybrid RAG Retrieval** — Keyword + vector + RRF fusion retrieval across your knowledge base
- **Brainstorm Mode** — Generate new strategy ideas by combining insights from multiple articles
- **Rethink Layer** — Post-generation validation that checks idea novelty (via vector similarity) and scores quality (traceability, coherence, actionability)
- **Interactive Agent** — LangGraph ReAct agent with 8 tools for full pipeline management
- **Provider-Agnostic** — Works with any OpenAI-compatible LLM API (Zhipu GLM, DeepSeek, Moonshot, Qwen, OpenAI, Ollama, etc.)
- **Local-First** — All data stored locally as Markdown files + ChromaDB vectors

## Architecture

### Pipeline Flow

```
WeChat URLs / HTML Files
        |
        v
  [1. Ingest] ──> articles/raw/{dir}/article.md + source.json
        |
        v
  [2. Enrich] ──> LLM fills idea_blocks, transfer_targets, failure_modes, etc.
        |
        v
  [3. Review] ──> Human review via agent or Obsidian
        |
        v
  [4. Sync]   ──> Move to articles/reviewed/ or articles/high-value/
        |
        v
  [5. Embed]  ──> Build ChromaDB vector index (block-level chunking)
        |
        v
  [6. Query]  ──> RAG Q&A (ask) or Brainstorm (brainstorm)
        |
        v
  [7. Rethink] ──> Novelty check + Quality scoring + Rethink Report
```

### Agent Layer

The LangGraph ReAct agent provides 8 tools:

| Tool | Description |
|------|-------------|
| `ingest_article` | Ingest from URL, batch URLs, URL list file, or HTML file |
| `enrich_articles` | LLM-powered structured enrichment |
| `list_articles` | List articles by stage (raw/reviewed/high-value) |
| `review_articles` | Show detailed article metadata for review |
| `set_article_status` | Batch update article status |
| `sync_articles` | Move articles based on frontmatter status |
| `embed_knowledge` | Build/update ChromaDB vector index |
| `query_knowledge_base` | RAG Q&A or brainstorm with Rethink Layer |

### Rethink Layer

A post-generation validation layer that runs automatically in brainstorm mode:

1. **Idea Parsing** — Extracts structured ideas from LLM output (EN/CN formats)
2. **Novelty Check** — Embeds each idea and queries ChromaDB for similar existing articles (threshold: 0.75)
3. **Quality Scoring** — Traceability (heuristic) + Coherence & Actionability (LLM-as-judge)
4. **Rethink Report** — Appended to output with per-idea scores and reasoning

## File Structure

```
QuantRAGForge/
├── agent/                          # LangGraph agent layer
│   ├── __init__.py
│   ├── graph.py                    # Agent creation (ReAct pattern)
│   ├── prompts.py                  # System prompt
│   └── tools.py                    # 8 agent tools
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
python3 enrich_articles_with_llm.py           # all raw articles
python3 enrich_articles_with_llm.py --dry-run  # preview only
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

You: enrich all raw articles
Agent: Enriched 3 articles with LLM metadata.

You: review the new articles
Agent: [Shows detailed article list with content types and summaries]

You: set articles 1 and 3 as high_value, article 2 as reviewed
Agent: Updated status for 3 articles.

You: sync and rebuild the index
Agent: Synced articles. Rebuilt vector index: 3 new, 20 total.

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
- **Card + idea blocks** — Full articles preserved, with extracted reusable idea units
- **Complementary retrieval** — Brainstorm mode prioritizes complementary (not similar) content
- **Traceable ideas** — Every generated idea must cite which source articles inspired it
- **Graceful degradation** — Every component handles missing dependencies without crashing

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
