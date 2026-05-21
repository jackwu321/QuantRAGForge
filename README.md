# Quant_LLM_Wiki

**English** | [简体中文](./README.zh-CN.md)

> A Karpathy-shaped wiki-first knowledge base for quantitative investment research.

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License">
  <img src="https://img.shields.io/badge/LLM-OpenAI_Compatible-orange.svg" alt="LLM">
  <img src="https://img.shields.io/badge/vector_store-ChromaDB-purple.svg" alt="ChromaDB">
</p>

Quant_LLM_Wiki turns WeChat articles, web pages, and research PDFs into an LLM-built Markdown knowledge base for quantitative research. It follows Andrej Karpathy's [LLM-built KB method](https://karpathy.bearblog.dev/): a `raw/` ingest layer, an LLM-compiled `wiki/` of concept articles, and a `schema/` that the LLM and tools both follow. Vector RAG is preserved as a fallback substrate, **not** the primary retrieval path. Three durable verbs — `ingest`, `query`, `lint` — drive everything. A built-in **Rethink Layer** scores novelty and quality of brainstormed ideas before output.

> The goal is **research inspiration and cross-document idea combination**, not producing trade-ready strategies.

## Features

- **Multi-source ingestion** — single URLs, batch URL lists, local HTML, or PDFs; warns on re-ingesting rejected sources
- **LLM enrichment** — extract idea blocks, transfer targets, combination hooks, failure modes; concurrent with configurable parallelism
- **Wiki-first retrieval** — both `ask` and `brainstorm` query stable concepts first; vector RAG runs only as fallback
- **Rethink Layer** — post-generation novelty (vector similarity) + quality (LLM-as-judge) scoring on brainstormed ideas
- **Schema-enforced wiki** — `wiki_lint` checks required frontmatter, sections, and source anchors on every run; `--fix` auto-repairs via LLM
- **Query → wiki feedback** — every `ask`/`brainstorm` logs back into the wiki; `lint --maintain` distills logs into gap-filling suggestions
- **Interactive agent** — LangGraph ReAct agent with 12 tools and real-time progress streaming
- **Provider-agnostic** — any OpenAI-compatible LLM (Zhipu GLM, DeepSeek, Moonshot, Qwen, OpenAI, Ollama, etc.)
- **Local-first** — all data as Markdown + ChromaDB on disk

For the full architecture, three-verb pipeline, retrieval invariants, and design principles, see [docs/architecture.md](docs/architecture.md).

## Quick start

Pick one install flow and stay in that column.

|                  | **A. pipx (end users)**                      | **B. git clone (developers)**             |
| ---------------- | -------------------------------------------- | ----------------------------------------- |
| When to use      | Just want to run `qlw` and build a personal KB. | Read/edit source, run tests, contribute.  |
| Repo locally?    | No                                           | Yes                                       |
| Workspace        | Any dir (or `$QLW_KB_ROOT`)                  | The clone itself by default               |
| `.env` location  | `<workspace>/.env` (auto-loaded from CWD)    | `<workspace>/.env` (auto-loaded from CWD) |
| `schema/`        | One-time fetch (below)                       | Already in the clone                      |

### 1. Install

```bash
# A. pipx (recommended)
pipx install quant-llm-wiki

# B. git clone + editable install
git clone https://github.com/jackwu321/Quant_LLM_Wiki.git
cd Quant_LLM_Wiki && python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

> **pipx ≥ 1.5 required** (older pipx ships pip 24.0 which mis-parses `langgraph`'s newer wheel metadata). If install fails with `ResolutionImpossible`, upgrade pipx first: `python3 -m pip install --user --upgrade --break-system-packages pipx && hash -r`.

### 2. Pick a workspace

`qlw` writes data under whichever directory it considers your **KB root**, resolved in this order: explicit `--kb-root` arg → `$QLW_KB_ROOT` → current working directory.

```bash
# pipx users — bootstrap a workspace and fetch schema/
mkdir -p ~/my-kb && cd ~/my-kb
export QLW_KB_ROOT="$PWD"
curl -fsSL https://github.com/jackwu321/Quant_LLM_Wiki/archive/refs/heads/main.tar.gz \
  | tar xz --strip=1 --wildcards "*/schema/*" "*/llm_config.example.env"

# clone users — the clone IS the workspace
cd Quant_LLM_Wiki
```

### 3. Configure the LLM

```bash
cp llm_config.example.env .env
# Edit .env with your API key and provider settings
```

`.env` is auto-loaded from `$QLW_KB_ROOT/.env` → `$(pwd)/.env` → the package directory. Or `export` directly in your shell. See [`llm_config.example.env`](llm_config.example.env) for provider examples.

### 4. Try the worked example (no real research data needed)

```bash
cd examples/tiny_kb
export QLW_KB_ROOT="$PWD"

qlw enrich            # LLM-enrich the pre-seeded sample articles
qlw embed             # build the vector index
qlw compile           # compile the wiki
qlw ask --query "What signals do these articles describe?"
qlw brainstorm --query "Combine momentum and sector ETF rotation"
```

See [examples/tiny_kb/README.md](examples/tiny_kb/README.md) for what gets produced and where to look.

### 5. Run on your own articles

```bash
qlw ingest --url "https://mp.weixin.qq.com/s/..."   # WeChat / web URL
qlw ingest --html-file saved.html                    # saved page
qlw ingest --pdf-file paper.pdf                      # research PDF
qlw ingest --url-list urls.txt                       # batch from a list

qlw enrich --limit 10
qlw embed
qlw ask --query "What momentum factors are discussed?"
qlw brainstorm --query "Combine momentum and volatility timing for ETF rotation"
```

Ingestion auto-runs `compile` and `embed` after success. Each URL has a 120 s ceiling; each LLM enrichment has 360 s. Override with `INGEST_URL_TIMEOUT` / `LLM_ARTICLE_TIMEOUT`.

### Wiki maintenance

```bash
qlw lint                       # schema + health audit
qlw lint --fix                 # LLM auto-repair of non-compliant concepts
qlw lint --maintain            # gap analysis: unmapped sources, under-supported, stale
qlw lint --maintain --apply    # apply query-derived state updates (idempotent)
```

## Agent mode

```bash
qlw agent                                       # interactive REPL
qlw agent --query "list all articles"           # one-shot
qlw agent --query "brainstorm: factor timing + risk parity"
```

The agent dispatches the 12 tools listed in [docs/architecture.md#agent-layer](docs/architecture.md#agent-layer) — ingest, enrich, list/review, embed, query, compile, audit, and read.

## Configuration

| Variable                     | Default                                | Description                                        |
| ---------------------------- | -------------------------------------- | -------------------------------------------------- |
| `LLM_API_KEY`                | —                                      | Your API key                                       |
| `LLM_BASE_URL`               | `https://open.bigmodel.cn/api/paas/v4` | OpenAI-compatible endpoint                         |
| `LLM_MODEL`                  | `glm-4.7`                              | Chat model                                         |
| `LLM_EMBEDDING_MODEL`        | `embedding-3`                          | Embedding model                                    |
| `LLM_CONNECT_TIMEOUT`        | `15`                                   | Connection timeout (s)                             |
| `LLM_READ_TIMEOUT`           | `180`                                  | Read timeout (s)                                   |
| `LLM_MAX_RETRIES`            | `4`                                    | Max retry attempts                                 |
| `LLM_MIN_INTERVAL_SECONDS`   | `2.0`                                  | Process-local minimum spacing before LLM requests  |
| `LLM_CONCURRENCY`            | `3`                                    | Worker parallelism for enrichment                  |

Legacy `ZHIPU_*` variables are also accepted as fallbacks. On HTTP 429, later requests in the same process honor a shared cooldown (`Retry-After` header when present).

Article status lifecycle and `content_type` classification are documented in [docs/metadata-schema.md](docs/metadata-schema.md).

## Documentation

- [docs/architecture.md](docs/architecture.md) — system architecture, three-verb pipeline, retrieval invariants, design principles
- [docs/metadata-schema.md](docs/metadata-schema.md) — article frontmatter fields and enums
- [docs/brainstorm-output-spec.md](docs/brainstorm-output-spec.md) — output contract for brainstorm runs
- [docs/releasing.md](docs/releasing.md) — release process for maintainers
- [`schema/`](schema/) — the contract enforced by `qlw lint`
- For CLI reference, `qlw <subcommand> --help` is the source of truth.

## Running tests

Tests live in the repo, not the wheel — run from a `git clone` checkout (install flow B).

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 -m unittest discover -s tests/robustness -p 'test_*.py' -v
```

The `tests/robustness/` suite covers Layer 1 (tool inputs), Layer 2 (workflow integration), Layer 3 (agent routing), and Layer 4 (LLM API timeouts/retries).

## Contributing

1. Fork and create a feature branch
2. Write tests for new functionality
3. Ensure `python3 -m unittest discover -s tests -p 'test_*.py'` passes
4. Open a Pull Request

## License

MIT — see [LICENSE](LICENSE).

## Disclaimer

Quant_LLM_Wiki is a research tool for generating investment strategy ideas. It does **not** produce trade-ready strategies or financial advice. All generated ideas require independent validation, backtesting, and risk assessment before any real-world application. Use at your own risk.
