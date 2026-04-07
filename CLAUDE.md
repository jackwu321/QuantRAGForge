# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A quantitative investment research knowledge base ("量化投研启发型知识库") that ingests WeChat articles and research reports, converts them to structured Markdown, enriches them with LLM-generated metadata, and supports RAG-based Q&A and brainstorming for new strategy ideas. The goal is research inspiration and cross-document idea combination, not producing trade-ready strategies.

## Key Commands

```bash
# Ingest articles from WeChat URLs
python3 ingest_wechat_article.py --url <URL>
python3 ingest_wechat_article.py --url-list "url list.txt"
python3 ingest_wechat_article.py --html-file saved.html --dry-run

# Enrich raw articles with LLM (Zhipu GLM API)
python3 enrich_articles_with_llm.py                          # all raw articles
python3 enrich_articles_with_llm.py --article-dir <path>     # single article
python3 enrich_articles_with_llm.py --dry-run

# Sync articles from raw/ to reviewed/ or high-value/ based on frontmatter status
python3 sync_articles_by_status.py --dry-run
python3 sync_articles_by_status.py

# Build/update ChromaDB vector index
python3 embed_knowledge_base.py --dry-run
python3 embed_knowledge_base.py --force   # re-index all

# RAG Q&A and brainstorming
python3 brainstorm_from_kb.py ask --query "..." [--retrieval keyword|vector|hybrid]
python3 brainstorm_from_kb.py brainstorm --query "..." --content-type methodology
python3 brainstorm_from_kb.py brainstorm --query "..." --dry-run  # show retrieved context only

# Run tests (unittest, no pytest)
cd /home/ubuntu/project/knowledge && .venv/bin/python3 -m unittest discover -s tests -p 'test_*.py'

# Agent CLI (requires .venv)
.venv/bin/python3 agent_cli.py                           # interactive mode
.venv/bin/python3 agent_cli.py --query "list all articles"  # single command
```

## Architecture

### Pipeline Flow

1. **Ingest** (`ingest_wechat_article.py`): Fetches HTML, extracts text/images/code, classifies `content_type`, writes to `articles/raw/<dir>/article.md` + `source.json` using templates
2. **Enrich** (`enrich_articles_with_llm.py`): Calls Zhipu GLM API to fill structured brainstorm fields (`idea_blocks`, `transfer_targets`, `combination_hooks`, `failure_modes`, etc.) into frontmatter and body sections
3. **Sync** (`sync_articles_by_status.py`): Moves articles from `raw/` to `reviewed/` or `high-value/` based on frontmatter `status` field
4. **Embed** (`embed_knowledge_base.py`): Builds ChromaDB vector index from `reviewed/` and `high-value/` articles, using block-level chunking
5. **Query** (`brainstorm_from_kb.py`): Two modes — `ask` (factual Q&A) and `brainstorm` (idea combination). Supports keyword, vector, and hybrid (RRF fusion) retrieval

### Agent Layer

`agent/` package wraps the pipeline into a LangGraph ReAct agent with 8 tools:
- `ingest_article`, `enrich_articles`, `list_articles`, `review_articles`, `set_article_status`, `sync_articles`, `embed_knowledge`, `query_knowledge_base`
- Uses `ChatZhipuAI` from `langchain-community` for agent routing
- Tool functions wrap existing script logic via imports (no code duplication)
- `agent_cli.py` provides interactive and single-command CLI modes
- Dependencies managed via `.venv/` (created with `python3 -m venv .venv`)

### Shared Module

`kb_shared.py` contains all shared logic: frontmatter parsing, note loading/filtering, block extraction, Zhipu API client (chat + embeddings), and configuration. All scripts import from here.

### Article Structure

Each article lives in its own directory with:
- `article.md` — Markdown with YAML frontmatter + templated sections
- `source.json` — raw extraction data and LLM enrichment metadata
- `images/` — downloaded article images

### Templates

- `templates/research-note-template.md` — for methodology, allocation, risk_control, market_review
- `templates/strategy-note-template.md` — for strategy (adds entry/exit rules, backtest metrics)

Both templates include brainstorm sections: Idea Blocks, Combination Hooks, Transfer Targets, Failure Modes, Follow-up Questions.

### Key Data Types

- `KnowledgeNote`: loaded article with parsed frontmatter and body
- `KnowledgeBlock`: chunk extracted from a note (summary, idea_blocks, main_content paragraphs, etc.), scored for retrieval

## LLM API

Supports any OpenAI-compatible API provider (Zhipu GLM, DeepSeek, Moonshot, Qwen, OpenAI, Ollama, etc.).

Configuration via `.env` file (auto-loaded by `python-dotenv`) or environment variables, with ZHIPU_* fallbacks:
- `LLM_API_KEY` / `ZHIPU_API_KEY` — API key (or put in `llm_api_key.txt`)
- `LLM_BASE_URL` / `ZHIPU_BASE_URL` — API base URL (default: Zhipu `https://open.bigmodel.cn/api/paas/v4`)
- `LLM_MODEL` / `ZHIPU_MODEL` — Chat model name (default: `glm-4.7`)
- `LLM_EMBEDDING_MODEL` / `ZHIPU_EMBEDDING_MODEL` — Embedding model (default: `embedding-3`)
- `LLM_CONNECT_TIMEOUT`, `LLM_READ_TIMEOUT`, `LLM_MAX_RETRIES` — Timeout settings

Copy `llm_config.example.env` to `.env` and fill in your provider's values. See that file for provider-specific examples (DeepSeek, Moonshot, Qwen, OpenAI, Ollama).

## Content Classification

`content_type` (exactly one per article): `methodology`, `strategy`, `allocation`, `risk_control`, `market_review`

Fixed vocabularies also exist for `market`, `asset_type`, and `strategy_type` — see README.md for the full word lists.

## Design Principles

- Prioritize readability over cleverness. Ask clarifying questions before making architectural changes.
- The knowledge base serves inspiration and idea combination, not backtested trading signals.
- Articles are stored as "card + idea blocks" — full article preserved, with extracted reusable idea units.
- Brainstorm mode prioritizes complementary (not similar) retrieval across multiple content types.
- `market_review` articles default to low `brainstorm_value` unless they contain strong framework insights.
