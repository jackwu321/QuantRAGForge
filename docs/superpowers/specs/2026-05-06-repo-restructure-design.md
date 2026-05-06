# Repo Restructure: qlib-style layout for Quant_LLM_Wiki

**Date:** 2026-05-06
**Status:** Spec — pending user approval
**Owner:** jackwu321
**Scope:** Layout & CLI reorganization only — no business-logic changes

## Why

Today the repo root holds 8 standalone Python scripts (`agent_cli.py`, `brainstorm_from_kb.py`, `embed_knowledge_base.py`, `enrich_articles_with_llm.py`, `ingest_wechat_article.py`, `kb_shared.py`, `rethink_layer.py`, `sync_articles_by_status.py`) plus the `agent/` sub-package. New contributors and the GitHub home page see a wall of scripts with no signal of what is library code, what is an entry point, and what is glue. Mature Python repos like `qlib`, `langchain`, `llama_index` colocate all source under a single namespace package and expose CLI entry points through `pyproject.toml`. We adopt the same layout.

The user also flagged that the local `.api_management/` directory contains plaintext API keys (`deepseek_api_key.txt`, `github_api_key.txt`, `zhipu_api_key.txt`) and is currently untracked but **not** in `.gitignore` — a single accidental `git add .` would leak them.

## Hard Invariants (Non-Negotiable)

This refactor is **layout-only**. The following must hold at every commit:

1. **Business logic is byte-for-byte preserved** in the moved files. Function bodies, control flow, prompts, thresholds, timeouts, concurrency limits, retry policy, chunking strategy, embedding dimensions, ChromaDB collection names, frontmatter schema, and file-naming rules — all unchanged.
2. **Allowed change types (whitelist):**
   - File moves and renames.
   - `from X import Y` path replacements.
   - Splitting each script's existing `if __name__ == "__main__"` + `argparse` block into two functions, `register(parser)` and `main(args)`. The body is not modified — only relocated.
   - Adding `pyproject.toml` and a new `quant_llm_wiki/cli.py` dispatcher.
   - Updating README and `docs/*.md` command examples and import paths.
3. **Data compatibility:** existing `articles/raw|reviewed|high-value/`, frontmatter, `source.json`, `rejected_sources.json`, and `vector_store/` collections must continue to work without rebuild.
4. **Test assertions are preserved.** Only `import` paths and `mock.patch` target paths in tests may change. If a non-import test failure appears, **revert the migration step** rather than edit the assertion.
5. **CLI behavior is preserved.** Every existing flag and default value is kept; stdout/stderr formatting is byte-identical.
6. **Acceptance:**
   - `python -m unittest discover -s tests -p 'test_*.py'` passes.
   - `python -m unittest discover -s tests/robustness -p 'test_*.py'` passes.
   - On the user's existing `articles/` + `vector_store/` data, `qlw ask --query "..."` returns the same result as the pre-refactor `python3 brainstorm_from_kb.py ask --query "..."`.

## Target Layout

```
Quant_LLM_Wiki/
├── README.md                      # rewritten: new commands + structure
├── LICENSE
├── pyproject.toml                 # NEW: project metadata + qlw entry point
├── requirements.txt               # kept as-is for users not running pip install -e .
├── llm_config.example.env
├── .gitignore                     # APPENDED: .api_management/, =1.0.0
├── quant_llm_wiki/                # ← single source-code package (qlib-style)
│   ├── __init__.py
│   ├── cli.py                     # qlw entry point; argparse subparsers
│   ├── shared.py                  # was kb_shared.py
│   ├── ingest/                    # sub-package — leaves room for future sources
│   │   ├── __init__.py
│   │   └── wechat.py              # was ingest_wechat_article.py
│   ├── enrich.py                  # was enrich_articles_with_llm.py
│   ├── embed.py                   # was embed_knowledge_base.py
│   ├── sync.py                    # was sync_articles_by_status.py
│   ├── query/                     # sub-package — brainstorm + rethink coupled
│   │   ├── __init__.py
│   │   ├── brainstorm.py          # was brainstorm_from_kb.py
│   │   └── rethink.py             # was rethink_layer.py
│   └── agent/                     # was agent/ at repo root
│       ├── __init__.py
│       ├── cli.py                 # was agent_cli.py
│       ├── graph.py
│       ├── prompts.py
│       └── tools.py
├── tests/                         # stays at repo root
│   ├── robustness/                # untouched layout
│   ├── test_ingest_wechat.py      # renamed from test_ingest_wechat_article.py
│   ├── test_enrich.py             # renamed from test_enrich_articles_with_llm.py
│   ├── test_embed.py              # renamed from test_embed_knowledge_base.py
│   ├── test_brainstorm.py         # renamed from test_brainstorm_from_kb.py
│   ├── test_rethink.py            # renamed from test_rethink_layer.py
│   ├── test_sync.py               # renamed from test_sync_articles_by_status.py
│   ├── test_build_catalog.py
│   ├── test_agent_graph.py
│   └── test_agent_tools.py
├── docs/                          # updated: command examples + import paths
│   └── superpowers/               # untouched
├── articles/                      # gitignored runtime data
├── sources/                       # gitignored runtime data
├── outputs/                       # gitignored runtime data
├── vector_store/                  # gitignored runtime data
├── templates/                     # source-referenced markdown templates
└── .api_management/               # gitignored (NEW)
```

**Placement principles:**
- Single-file features (`enrich`, `embed`, `sync`) become package-level modules — no over-packaging.
- Multi-file or extension-anticipated features (`ingest/`, `query/`, `agent/`) become sub-packages.
- Runtime data (`articles/`, `sources/`, `outputs/`, `vector_store/`), `templates/`, `tests/`, and `docs/` stay at the repo root, matching qlib's convention.

## CLI Design

`pyproject.toml` exposes one command, `qlw`. All functionality is reached via subparsers.

```toml
# pyproject.toml (excerpt)
[project]
name = "quant_llm_wiki"
version = "0.2.0"
description = "AI-powered quant research knowledge base & brainstorm agent"
requires-python = ">=3.10"
license = {text = "MIT"}
readme = "README.md"
dependencies = [
    # synced from requirements.txt (no version bumps in this refactor)
]

[project.scripts]
qlw = "quant_llm_wiki.cli:main"

[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["quant_llm_wiki*"]
```

Subcommand-to-module mapping (every existing flag is preserved):

| Command | Module | Replaces |
|---------|--------|----------|
| `qlw ingest --url ... / --url-list f / --html-file f / --force` | `quant_llm_wiki.ingest.wechat` | `python3 ingest_wechat_article.py ...` |
| `qlw enrich [--limit N] [--concurrency N] [--dry-run]` | `quant_llm_wiki.enrich` | `python3 enrich_articles_with_llm.py ...` |
| `qlw embed` | `quant_llm_wiki.embed` | `python3 embed_knowledge_base.py` |
| `qlw sync` | `quant_llm_wiki.sync` | `python3 sync_articles_by_status.py` |
| `qlw ask --query "..."` | `quant_llm_wiki.query.brainstorm` | `python3 brainstorm_from_kb.py ask ...` |
| `qlw brainstorm --query "..." [--dry-run]` | `quant_llm_wiki.query.brainstorm` | `python3 brainstorm_from_kb.py brainstorm ...` |
| `qlw agent [--query "..."]` | `quant_llm_wiki.agent.cli` | `python3 agent_cli.py ...` |

**Dispatcher pattern.** Each module exposes two functions, `register(parser)` and `main(args)`. The dispatcher only wires them — it never knows about flags:

```python
# quant_llm_wiki/cli.py
import argparse
from quant_llm_wiki import enrich, embed, sync
from quant_llm_wiki.ingest import wechat
from quant_llm_wiki.query import brainstorm
from quant_llm_wiki.agent import cli as agent_cli

def main(argv=None):
    parser = argparse.ArgumentParser(prog="qlw")
    sub = parser.add_subparsers(dest="cmd", required=True)
    wechat.register(sub.add_parser("ingest"))
    enrich.register(sub.add_parser("enrich"))
    embed.register(sub.add_parser("embed"))
    sync.register(sub.add_parser("sync"))
    brainstorm.register_ask(sub.add_parser("ask"))
    brainstorm.register_brainstorm(sub.add_parser("brainstorm"))
    agent_cli.register(sub.add_parser("agent"))
    args = parser.parse_args(argv)
    return args.func(args)
```

Each `register(parser)` migrates the existing `argparse.ArgumentParser(...)` block from the old script verbatim, and calls `parser.set_defaults(func=main)` where `main(args)` runs the existing top-level body. **No flag is renamed; no default changes.**

Install and use:

```bash
pip install -e .
qlw ingest --url "..."
qlw brainstorm --query "..."
qlw agent
```

`python -m quant_llm_wiki.cli ingest --url "..."` works as a fallback for users who skip `pip install -e .`.

## Migration Plan (6 Commits)

Each commit must leave `unittest` green.

### Commit 1 — Prep
- Append to `.gitignore`: `.api_management/`, `=1.0.0`.
- Delete the spurious empty file `=1.0.0`.
- Add `pyproject.toml` (without `[project.scripts]` yet — package directory does not exist).
- Tests: unchanged, all green.

### Commit 2 — Create skeleton; move `shared` and `sync`
- Create `quant_llm_wiki/__init__.py`, `quant_llm_wiki/ingest/__init__.py`, `quant_llm_wiki/query/__init__.py`.
- Move `kb_shared.py` → `quant_llm_wiki/shared.py`.
- Move `sync_articles_by_status.py` → `quant_llm_wiki/sync.py`.
- Update every `from kb_shared import` and `from sync_articles_by_status import` (callers: `agent/tools.py`, `brainstorm_from_kb.py`, `embed_knowledge_base.py`, `enrich_articles_with_llm.py`, `rethink_layer.py`, plus tests).
- Update `mock.patch("kb_shared.…")` → `mock.patch("quant_llm_wiki.shared.…")` in tests.
- Tests: green.

### Commit 3 — Move `ingest`, `enrich`, `embed`
- `ingest_wechat_article.py` → `quant_llm_wiki/ingest/wechat.py`.
- `enrich_articles_with_llm.py` → `quant_llm_wiki/enrich.py`.
- `embed_knowledge_base.py` → `quant_llm_wiki/embed.py`.
- Update `agent/tools.py` lazy imports.
- Rename test files (`test_ingest_wechat_article.py` → `test_ingest_wechat.py`, etc.) and update their imports + `mock.patch` targets.
- Tests: green.

### Commit 4 — Move `query` sub-package
- `brainstorm_from_kb.py` → `quant_llm_wiki/query/brainstorm.py`.
- `rethink_layer.py` → `quant_llm_wiki/query/rethink.py`.
- Update cross-references (`brainstorm` imports `rethink`), `agent/tools.py`, tests.
- Tests: green.

### Commit 5 — Move `agent` package; wire up `qlw` CLI
- Move `agent/` → `quant_llm_wiki/agent/`.
- Move `agent_cli.py` → `quant_llm_wiki/agent/cli.py`.
- Add `register(parser)` + `main(args)` to each module by lifting the existing argparse block — function bodies untouched.
- Create `quant_llm_wiki/cli.py` dispatcher.
- Add `[project.scripts] qlw = "quant_llm_wiki.cli:main"` to `pyproject.toml`.
- `pip install -e .`; smoke: `qlw --help`, `qlw ask --query "..."` against existing `vector_store/`.
- Tests: green.

### Commit 6 — Docs cleanup
- Rewrite `README.md`: `File Structure`, `Quick Start`, `Agent Usage`, `Running Tests` sections all use `qlw <subcmd>` and the new paths.
- Add a "Command renaming table" near the top mapping every old `python3 X.py` invocation to its `qlw` equivalent.
- Update `docs/*.md` references.
- Note in README: repo is `Quant_LLM_Wiki`; package is `quant_llm_wiki`; command is `qlw`.
- Tests: green.

**Rollback rule.** If tests fail after a commit and the cause is anything other than a missed import path, run `git reset --hard HEAD~1` and redo the step. **Never** change a test assertion or business function to make tests pass.

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| `agent/tools.py` uses lazy imports — a missed path surfaces only at runtime | Run `qlw agent --query "list raw articles"` smoke at end of commits 3–5 |
| Test `mock.patch` strings still reference old module paths | After each commit: `grep -rn "patch.*\(kb_shared\|ingest_wechat_article\|enrich_articles_with_llm\|embed_knowledge_base\|brainstorm_from_kb\|rethink_layer\|sync_articles_by_status\)" tests/` should return no hits |
| User's notes / shell history use old `python3 X.py` commands | README "Command renaming table" maps every old form to `qlw <subcmd>` |
| ChromaDB collection name is hardcoded; reading existing `vector_store/` after refactor | Constant remains in `quant_llm_wiki/shared.py`; smoke `qlw ask` against existing data |
| `.api_management/` committed by accident | Commit 1 puts it in `.gitignore` first; check `git status` before any `git add` |
| Repo name `Quant_LLM_Wiki` vs package `quant_llm_wiki` casing confusion | README explains both names explicitly |

## Out of Scope

- Changes to ingestion logic, enrichment prompt, embedding chunking, brainstorm or rethink algorithms, agent graph behavior.
- Dependency upgrades (versions in `requirements.txt` and the new `pyproject.toml` match exactly).
- New features, new sub-commands, new tests (beyond renames).
- Switching from `argparse` to Typer / Click.
- `src/` layout (deferred; can be revisited after this refactor settles).
