# Quant_LLM_Wiki Repo Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move 8 root-level Python scripts into a single `quant_llm_wiki/` package and expose a unified `qlw` CLI via `pyproject.toml`, with **zero changes to business logic**.

**Architecture:** A qlib-style namespace package containing functional sub-modules (`ingest/`, `query/`, `agent/`) and flat single-file modules (`shared.py`, `enrich.py`, `embed.py`, `sync.py`). One `qlw` console-script entry point dispatches to per-module `register(parser)` + `main(args)` pairs.

**Tech Stack:** Python 3.10+, argparse, setuptools, pyproject.toml, langchain/langgraph, ChromaDB.

**Spec:** [`docs/superpowers/specs/2026-05-06-repo-restructure-design.md`](../specs/2026-05-06-repo-restructure-design.md). Read its **Hard Invariants** section before doing anything else.

---

## Pre-flight

- [ ] **Pre-1: Confirm clean working state for new commits**

The index currently has ~61 pre-existing staged changes from earlier sessions. The user explicitly asked to leave them untouched. **Every commit step in this plan uses an explicit pathspec (`git add <specific paths>`); never run `git add -A` or `git add .`**. Verify before starting:

```bash
git diff --cached --name-only | wc -l       # expect ≈61
git log --oneline -3                         # newest should be the spec commit f59a4b2 or later
```

- [ ] **Pre-2: Capture baseline test result**

```bash
python3 -m unittest discover -s tests -p 'test_*.py' 2>&1 | tail -3
python3 -m unittest discover -s tests/robustness -p 'test_*.py' 2>&1 | tail -3
```

Record the pass/fail counts. Each task must end with these counts unchanged or improved.

- [ ] **Pre-3: Capture baseline smoke output (if data exists)**

If `vector_store/` and `articles/reviewed|high-value/` are non-empty, run a baseline brainstorm + ask and save the output for later comparison:

```bash
python3 brainstorm_from_kb.py ask --query "what factors are discussed" > /tmp/qlw_smoke_baseline.txt 2>&1 || echo "skipped"
```

If the dirs are empty, skip — just note "no baseline".

---

## File Structure (final state)

```
quant_llm_wiki/
├── __init__.py             # empty
├── cli.py                  # qlw dispatcher
├── shared.py               # was kb_shared.py (verbatim)
├── ingest/
│   ├── __init__.py         # empty
│   └── wechat.py           # was ingest_wechat_article.py
├── enrich.py               # was enrich_articles_with_llm.py
├── embed.py                # was embed_knowledge_base.py
├── sync.py                 # was sync_articles_by_status.py
├── query/
│   ├── __init__.py         # empty
│   ├── brainstorm.py       # was brainstorm_from_kb.py
│   └── rethink.py          # was rethink_layer.py
└── agent/
    ├── __init__.py         # was agent/__init__.py
    ├── cli.py              # was agent_cli.py
    ├── graph.py            # was agent/graph.py
    ├── prompts.py          # was agent/prompts.py
    └── tools.py            # was agent/tools.py
```

Tests stay at `tests/` (renamed: `test_kb_shared.py` etc. → keep) — only renames listed in Task 4–7.

`pyproject.toml` is created in Task 1 (no `[project.scripts]` yet) and finalized in Task 7 (entry point added).

---

## Task 1: Prep — `.gitignore`, `pyproject.toml` skeleton, cleanup

**Files:**
- Modify: `.gitignore` (append section)
- Create: `pyproject.toml`
- Delete: `=1.0.0` (empty spurious file)
- Test: re-run baseline tests to confirm no regression

- [ ] **Step 1: Append to `.gitignore`**

Add these lines at the end of `.gitignore`:

```
# Local API key store (never commit)
.api_management/

# Spurious file from accidental pip invocation
=1.0.0
```

- [ ] **Step 2: Delete the spurious empty file**

```bash
rm "=1.0.0"
```

- [ ] **Step 3: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "quant_llm_wiki"
version = "0.2.0"
description = "AI-powered quant research knowledge base & brainstorm agent"
readme = "README.md"
requires-python = ">=3.10"
license = {text = "MIT"}
authors = [{name = "jackwu321"}]
dependencies = [
    "requests>=2.28.0",
    "beautifulsoup4>=4.12.0",
    "chromadb>=0.4.0",
    "langgraph>=0.2.0",
    "langchain-core>=0.3.0",
    "langchain-community>=0.3.0",
    "langchain-openai>=0.3.0",
    "python-dotenv>=1.0.0",
]

# [project.scripts] is added in Task 7 once the package exists.

[tool.setuptools.packages.find]
include = ["quant_llm_wiki*"]
```

- [ ] **Step 4: Run unit tests to confirm no regression**

```bash
python3 -m unittest discover -s tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: same counts as Pre-2 baseline.

- [ ] **Step 5: Commit (explicit paths only)**

```bash
git add .gitignore pyproject.toml
git rm "=1.0.0"
git commit -m "$(cat <<'EOF'
chore: prep gitignore + pyproject skeleton for restructure

Adds .api_management/ to .gitignore (contains plaintext API keys)
and creates pyproject.toml without console_scripts. Source layout
unchanged this commit; the [project.scripts] entry is added in a
later commit once quant_llm_wiki/ exists.
EOF
)"
```

Verify the commit touched only those 3 paths:

```bash
git show --stat HEAD | head -10
```

---

## Task 2: Move `kb_shared.py` and `sync_articles_by_status.py` into the package

**Files:**
- Create: `quant_llm_wiki/__init__.py`, `quant_llm_wiki/ingest/__init__.py`, `quant_llm_wiki/query/__init__.py`
- Move: `kb_shared.py` → `quant_llm_wiki/shared.py`
- Move: `sync_articles_by_status.py` → `quant_llm_wiki/sync.py`
- Modify (callers): `brainstorm_from_kb.py`, `embed_knowledge_base.py`, `enrich_articles_with_llm.py`, `rethink_layer.py`, `agent/tools.py`, `agent/graph.py`
- Modify (tests): `tests/test_embed_knowledge_base.py`, `tests/test_enrich_articles_with_llm.py`, `tests/test_rethink_layer.py`, `tests/test_sync_articles_by_status.py`, `tests/test_agent_tools.py`, `tests/robustness/test_layer2_workflow_integration.py`, `tests/robustness/test_layer3_agent_routing.py`, `tests/robustness/test_layer4_llm_api_robustness.py`

- [ ] **Step 1: Create empty package init files**

```bash
mkdir -p quant_llm_wiki/ingest quant_llm_wiki/query
: > quant_llm_wiki/__init__.py
: > quant_llm_wiki/ingest/__init__.py
: > quant_llm_wiki/query/__init__.py
```

- [ ] **Step 2: Move `kb_shared.py` → `quant_llm_wiki/shared.py`**

```bash
git mv kb_shared.py quant_llm_wiki/shared.py
```

**Do NOT modify the file content.** It is a verbatim move.

- [ ] **Step 3: Move `sync_articles_by_status.py` → `quant_llm_wiki/sync.py`**

```bash
git mv sync_articles_by_status.py quant_llm_wiki/sync.py
```

Verbatim move.

- [ ] **Step 4: Update production callers' imports of `kb_shared`**

Replace exactly `from kb_shared import` → `from quant_llm_wiki.shared import` in these files (use `sed`):

```bash
sed -i 's|^from kb_shared import|from quant_llm_wiki.shared import|' \
    brainstorm_from_kb.py \
    embed_knowledge_base.py \
    enrich_articles_with_llm.py \
    rethink_layer.py \
    agent/tools.py \
    agent/graph.py
```

Verify each file changed (1 line each):

```bash
grep -n "quant_llm_wiki.shared\|kb_shared" \
    brainstorm_from_kb.py embed_knowledge_base.py enrich_articles_with_llm.py \
    rethink_layer.py agent/tools.py agent/graph.py
```

Expected: every hit references `quant_llm_wiki.shared`; no remaining `kb_shared` references.

- [ ] **Step 5: Update `agent/tools.py` lazy import of `sync_articles_by_status`**

Locate the line (around line 366):

```python
from sync_articles_by_status import sync_by_status, ARTICLES_DIR, DEFAULT_SOURCE_DIR
```

Replace with:

```python
from quant_llm_wiki.sync import sync_by_status, ARTICLES_DIR, DEFAULT_SOURCE_DIR
```

Verify:

```bash
grep -n "sync_articles_by_status\|quant_llm_wiki.sync" agent/tools.py
```

Expected: only `quant_llm_wiki.sync`, no `sync_articles_by_status`.

- [ ] **Step 6: Update test imports — `kb_shared` and `sync_articles_by_status`**

```bash
sed -i 's|^import kb_shared|import quant_llm_wiki.shared as kb_shared|' \
    tests/test_embed_knowledge_base.py \
    tests/test_enrich_articles_with_llm.py
```

```bash
sed -i 's|^from kb_shared import|from quant_llm_wiki.shared import|' \
    tests/test_rethink_layer.py
```

```bash
sed -i 's|^import sync_articles_by_status as mod|import quant_llm_wiki.sync as mod|' \
    tests/test_sync_articles_by_status.py
```

The aliasing form `import quant_llm_wiki.shared as kb_shared` is intentional: it preserves the local symbol `kb_shared` used inside the test bodies, so test source diffs stay minimal.

- [ ] **Step 7: Update `mock.patch` strings — `kb_shared.X` → `quant_llm_wiki.shared.X`**

```bash
grep -rln 'patch("kb_shared\.' tests/ | xargs sed -i 's|patch("kb_shared\.|patch("quant_llm_wiki.shared.|g'
```

Verify zero hits remain:

```bash
grep -rn 'patch("kb_shared\.' tests/
```

Expected: no output.

- [ ] **Step 8: Run all tests**

```bash
python3 -m unittest discover -s tests -p 'test_*.py' 2>&1 | tail -3
python3 -m unittest discover -s tests/robustness -p 'test_*.py' 2>&1 | tail -3
```

Expected: same counts as Pre-2 baseline (no regression).

If a test fails for a reason other than a missed import path, **stop, do `git reset --hard`, and re-do this task more carefully**. Do not edit assertions.

- [ ] **Step 9: Commit**

```bash
git add quant_llm_wiki/__init__.py quant_llm_wiki/ingest/__init__.py quant_llm_wiki/query/__init__.py \
        quant_llm_wiki/shared.py quant_llm_wiki/sync.py \
        brainstorm_from_kb.py embed_knowledge_base.py enrich_articles_with_llm.py rethink_layer.py \
        agent/tools.py agent/graph.py \
        tests/test_embed_knowledge_base.py tests/test_enrich_articles_with_llm.py \
        tests/test_rethink_layer.py tests/test_sync_articles_by_status.py \
        tests/test_agent_tools.py \
        tests/robustness/test_layer2_workflow_integration.py \
        tests/robustness/test_layer3_agent_routing.py \
        tests/robustness/test_layer4_llm_api_robustness.py
# git mv from steps 2-3 already staged the deletions+adds; the line above only adds modifications.
git status --short                  # verify only intended files in index
git commit -m "refactor: move kb_shared + sync into quant_llm_wiki package

Verbatim moves; updates all import paths and mock.patch targets.
No business-logic changes."
```

---

## Task 3: Move `ingest_wechat_article.py` → `quant_llm_wiki/ingest/wechat.py`

**Files:**
- Move: `ingest_wechat_article.py` → `quant_llm_wiki/ingest/wechat.py`
- Modify: `agent/tools.py` (lazy import line 58)
- Modify: `tests/test_ingest_wechat_article.py` → rename to `tests/test_ingest_wechat.py`, update import
- Modify: `tests/test_agent_tools.py` (mock.patch target)
- Modify: `tests/robustness/test_layer3_agent_routing.py` (mock.patch target)

- [ ] **Step 1: Move the file**

```bash
git mv ingest_wechat_article.py quant_llm_wiki/ingest/wechat.py
```

- [ ] **Step 2: Update `agent/tools.py` lazy import**

Find the line (around 58):

```python
from ingest_wechat_article import (
```

Replace with:

```python
from quant_llm_wiki.ingest.wechat import (
```

Use:

```bash
sed -i 's|^    from ingest_wechat_article import (|    from quant_llm_wiki.ingest.wechat import (|' agent/tools.py
sed -i 's|^from ingest_wechat_article import |from quant_llm_wiki.ingest.wechat import |' agent/tools.py
```

Verify zero hits remain:

```bash
grep -n "ingest_wechat_article" agent/tools.py
```

Expected: no output.

- [ ] **Step 3: Rename the test file**

```bash
git mv tests/test_ingest_wechat_article.py tests/test_ingest_wechat.py
```

- [ ] **Step 4: Update test imports**

```bash
sed -i 's|^import ingest_wechat_article as mod|import quant_llm_wiki.ingest.wechat as mod|' \
    tests/test_ingest_wechat.py
```

- [ ] **Step 5: Update all `mock.patch` strings referencing `ingest_wechat_article`**

```bash
grep -rln '"ingest_wechat_article\.' tests/ | xargs -r sed -i 's|"ingest_wechat_article\.|"quant_llm_wiki.ingest.wechat.|g'
```

Verify:

```bash
grep -rn 'ingest_wechat_article' tests/
```

Expected: no output.

- [ ] **Step 6: Run all tests**

```bash
python3 -m unittest discover -s tests -p 'test_*.py' 2>&1 | tail -3
python3 -m unittest discover -s tests/robustness -p 'test_*.py' 2>&1 | tail -3
```

Expected: counts unchanged.

- [ ] **Step 7: Commit**

```bash
git add agent/tools.py tests/test_agent_tools.py tests/robustness/test_layer3_agent_routing.py
git status --short
git commit -m "refactor: move ingest_wechat_article into quant_llm_wiki.ingest.wechat

Verbatim move; updates lazy import in agent/tools.py and patch targets
in tests. No business-logic changes."
```

---

## Task 4: Move `enrich_articles_with_llm.py` and `embed_knowledge_base.py`

**Files:**
- Move: `enrich_articles_with_llm.py` → `quant_llm_wiki/enrich.py`
- Move: `embed_knowledge_base.py` → `quant_llm_wiki/embed.py`
- Modify: `agent/tools.py` (two lazy imports, lines 165 and 391)
- Rename + modify: `tests/test_enrich_articles_with_llm.py` → `tests/test_enrich.py`
- Rename + modify: `tests/test_embed_knowledge_base.py` → `tests/test_embed.py`

- [ ] **Step 1: Move the two files**

```bash
git mv enrich_articles_with_llm.py quant_llm_wiki/enrich.py
git mv embed_knowledge_base.py quant_llm_wiki/embed.py
```

- [ ] **Step 2: Update `agent/tools.py` lazy imports**

Replace:

```python
from enrich_articles_with_llm import (
```

with:

```python
from quant_llm_wiki.enrich import (
```

And:

```python
from embed_knowledge_base import (
```

with:

```python
from quant_llm_wiki.embed import (
```

```bash
sed -i 's|from enrich_articles_with_llm import|from quant_llm_wiki.enrich import|g' agent/tools.py
sed -i 's|from embed_knowledge_base import|from quant_llm_wiki.embed import|g' agent/tools.py
grep -n "enrich_articles_with_llm\|embed_knowledge_base" agent/tools.py
```

Expected: no output.

- [ ] **Step 3: Rename test files**

```bash
git mv tests/test_enrich_articles_with_llm.py tests/test_enrich.py
git mv tests/test_embed_knowledge_base.py tests/test_embed.py
```

- [ ] **Step 4: Update test imports**

```bash
sed -i 's|^import enrich_articles_with_llm as mod|import quant_llm_wiki.enrich as mod|' tests/test_enrich.py
sed -i 's|^import embed_knowledge_base as mod|import quant_llm_wiki.embed as mod|' tests/test_embed.py
```

- [ ] **Step 5: Update mock.patch targets (if any)**

```bash
grep -rln '"enrich_articles_with_llm\.\|"embed_knowledge_base\.' tests/ | xargs -r sed -i \
    -e 's|"enrich_articles_with_llm\.|"quant_llm_wiki.enrich.|g' \
    -e 's|"embed_knowledge_base\.|"quant_llm_wiki.embed.|g'

grep -rn "enrich_articles_with_llm\|embed_knowledge_base" tests/
```

Expected: no output.

- [ ] **Step 6: Run all tests**

```bash
python3 -m unittest discover -s tests -p 'test_*.py' 2>&1 | tail -3
python3 -m unittest discover -s tests/robustness -p 'test_*.py' 2>&1 | tail -3
```

Expected: unchanged counts.

- [ ] **Step 7: Commit**

```bash
git add agent/tools.py
git status --short
git commit -m "refactor: move enrich + embed into quant_llm_wiki package

Verbatim moves; updates lazy imports and test patch targets. No
business-logic changes."
```

---

## Task 5: Move `brainstorm_from_kb.py` and `rethink_layer.py` into `query/` sub-package

**Files:**
- Move: `brainstorm_from_kb.py` → `quant_llm_wiki/query/brainstorm.py`
- Move: `rethink_layer.py` → `quant_llm_wiki/query/rethink.py`
- Modify: `quant_llm_wiki/query/brainstorm.py` (one internal import: `from rethink_layer import rethink`)
- Modify: `agent/tools.py` (lazy import line 482)
- Rename + modify: `tests/test_brainstorm_from_kb.py` → `tests/test_brainstorm.py`
- Rename + modify: `tests/test_rethink_layer.py` → `tests/test_rethink.py`

- [ ] **Step 1: Move the two files**

```bash
git mv brainstorm_from_kb.py quant_llm_wiki/query/brainstorm.py
git mv rethink_layer.py quant_llm_wiki/query/rethink.py
```

- [ ] **Step 2: Fix `brainstorm.py`'s internal import of `rethink_layer`**

Replace:

```python
from rethink_layer import rethink
```

with:

```python
from quant_llm_wiki.query.rethink import rethink
```

```bash
sed -i 's|^from rethink_layer import rethink$|from quant_llm_wiki.query.rethink import rethink|' \
    quant_llm_wiki/query/brainstorm.py
grep -n "rethink_layer\|quant_llm_wiki.query.rethink" quant_llm_wiki/query/brainstorm.py
```

Expected: only `quant_llm_wiki.query.rethink`.

- [ ] **Step 3: Update `agent/tools.py` lazy import**

Replace `from brainstorm_from_kb import (` with `from quant_llm_wiki.query.brainstorm import (`:

```bash
sed -i 's|from brainstorm_from_kb import|from quant_llm_wiki.query.brainstorm import|g' agent/tools.py
grep -n "brainstorm_from_kb\|rethink_layer" agent/tools.py
```

Expected: no output.

- [ ] **Step 4: Rename test files**

```bash
git mv tests/test_brainstorm_from_kb.py tests/test_brainstorm.py
git mv tests/test_rethink_layer.py tests/test_rethink.py
```

- [ ] **Step 5: Update test imports**

```bash
sed -i 's|^import brainstorm_from_kb as mod|import quant_llm_wiki.query.brainstorm as mod|' \
    tests/test_brainstorm.py

sed -i 's|^from rethink_layer import|from quant_llm_wiki.query.rethink import|' \
    tests/test_rethink.py
```

- [ ] **Step 6: Update mock.patch targets**

```bash
grep -rln '"brainstorm_from_kb\.\|"rethink_layer\.' tests/ | xargs -r sed -i \
    -e 's|"brainstorm_from_kb\.|"quant_llm_wiki.query.brainstorm.|g' \
    -e 's|"rethink_layer\.|"quant_llm_wiki.query.rethink.|g'

grep -rn "brainstorm_from_kb\|rethink_layer" tests/
```

Expected: no output.

- [ ] **Step 7: Run all tests**

```bash
python3 -m unittest discover -s tests -p 'test_*.py' 2>&1 | tail -3
python3 -m unittest discover -s tests/robustness -p 'test_*.py' 2>&1 | tail -3
```

Expected: unchanged counts.

- [ ] **Step 8: Commit**

```bash
git add agent/tools.py quant_llm_wiki/query/brainstorm.py
git status --short
git commit -m "refactor: move brainstorm + rethink into quant_llm_wiki.query

Verbatim moves; updates internal cross-import (brainstorm imports
rethink), agent lazy import, and test patch targets. No business-
logic changes."
```

---

## Task 6: Move `agent/` into the package and wire up the `qlw` CLI dispatcher

**Files:**
- Move: `agent/__init__.py`, `agent/graph.py`, `agent/prompts.py`, `agent/tools.py` → `quant_llm_wiki/agent/`
- Move: `agent_cli.py` → `quant_llm_wiki/agent/cli.py`
- Modify: `quant_llm_wiki/agent/__init__.py` (one import line)
- Modify: `quant_llm_wiki/agent/graph.py` (two imports: `from agent.prompts`, `from agent.tools`)
- Modify: `quant_llm_wiki/agent/cli.py` (the `from agent import create_agent` line)
- Add `register/main` wrapper to each module that has CLI logic
- Create: `quant_llm_wiki/cli.py` (dispatcher)
- Modify: `pyproject.toml` (add `[project.scripts]`)
- Modify: `tests/test_agent_graph.py`, `tests/test_agent_tools.py` (mock.patch targets and imports)

- [ ] **Step 1: Move the agent package**

```bash
git mv agent/__init__.py quant_llm_wiki/agent/__init__.py
git mv agent/graph.py    quant_llm_wiki/agent/graph.py
git mv agent/prompts.py  quant_llm_wiki/agent/prompts.py
git mv agent/tools.py    quant_llm_wiki/agent/tools.py
git mv agent_cli.py      quant_llm_wiki/agent/cli.py
rmdir agent              # was: agent/__pycache__ may exist, ignore if rmdir fails
rm -rf agent/__pycache__ 2>/dev/null && rmdir agent 2>/dev/null || true
```

- [ ] **Step 2: Fix internal imports inside the moved agent package**

In `quant_llm_wiki/agent/__init__.py`, change `from agent.graph import create_agent` → `from quant_llm_wiki.agent.graph import create_agent`:

```bash
sed -i 's|^from agent\.graph import|from quant_llm_wiki.agent.graph import|' quant_llm_wiki/agent/__init__.py
```

In `quant_llm_wiki/agent/graph.py`, replace two imports:

```bash
sed -i \
    -e 's|^from agent\.prompts import|from quant_llm_wiki.agent.prompts import|' \
    -e 's|^from agent\.tools import|from quant_llm_wiki.agent.tools import|' \
    quant_llm_wiki/agent/graph.py
```

In `quant_llm_wiki/agent/cli.py`, the existing `from agent import create_agent` (around line 87) becomes:

```bash
sed -i 's|from agent import create_agent|from quant_llm_wiki.agent import create_agent|' quant_llm_wiki/agent/cli.py
```

Verify no stray `from agent` left in the package:

```bash
grep -rn "^from agent\b\|^import agent\b" quant_llm_wiki/
```

Expected: no output.

- [ ] **Step 3: Add `register(parser)` + `_run(args)` wrappers — `quant_llm_wiki/sync.py`**

Read the existing structure. Currently:

```python
def main() -> int:
    parser = argparse.ArgumentParser(...)
    parser.add_argument(...)
    ...
    args = parser.parse_args()
    # ... body ...
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

Refactor to (uniform pattern used by every module in this refactor):

```python
def register(parser: argparse.ArgumentParser) -> None:
    """Attach this module's CLI flags to `parser`. Called by quant_llm_wiki.cli."""
    # paste the parser.add_argument(...) calls verbatim from the old main()
    parser.add_argument(...)
    ...
    parser.set_defaults(func=_run)


def _run(args) -> int:
    """The module's command body. Receives parsed args from the dispatcher."""
    # paste the rest of the original main() body verbatim, but remove the
    # top `parser = ArgumentParser(...)` line and the `args = parser.parse_args()`
    # line (args is already supplied)
    ...
    return 0


def main() -> int:
    """Standalone entry: python -m quant_llm_wiki.sync ..."""
    parser = argparse.ArgumentParser(description="...")  # paste original description
    register(parser)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
```

**Critical:** the `_run(args)` body is byte-for-byte the original `main()` body minus the parser construction and `parse_args()` line. Do not refactor anything else.

- [ ] **Step 4: Apply the same `register` / `_run` / `main` pattern to:**

  - `quant_llm_wiki/enrich.py`
  - `quant_llm_wiki/embed.py`
  - `quant_llm_wiki/ingest/wechat.py`

For each: extract argparse setup into `register`, set `parser.set_defaults(func=_run)`, body unchanged.

- [ ] **Step 5: Apply the dual-subcommand pattern to `quant_llm_wiki/query/brainstorm.py`**

The original `brainstorm_from_kb.py` declares its own `add_subparsers` with two commands `ask` and `brainstorm`, sharing flags via `parents=[common]`. The new shape: **two top-level register functions**, each adds the shared flags to its given parser via a small helper. No private API.

```python
def _add_common_args(parser: argparse.ArgumentParser) -> None:
    """Attach the shared --query/--top-k/... flags. Called by both register_*."""
    # paste each `common.add_argument(...)` from the original `common` parser,
    # changing `common` to `parser`. Verbatim otherwise.
    parser.add_argument("--query", ...)
    parser.add_argument("--top-k", ...)
    ...


def register_ask(parser: argparse.ArgumentParser) -> None:
    _add_common_args(parser)
    parser.set_defaults(func=_run_ask)


def register_brainstorm(parser: argparse.ArgumentParser) -> None:
    _add_common_args(parser)
    # paste any brainstorm-only flags here (e.g. --dry-run) verbatim
    parser.add_argument("--dry-run", action="store_true", ...)
    parser.set_defaults(func=_run_brainstorm)


def _run_ask(args) -> int:
    # paste the original `ask`-branch body verbatim
    ...


def _run_brainstorm(args) -> int:
    # paste the original `brainstorm`-branch body verbatim
    ...


def main() -> int:
    """Standalone entry: python -m quant_llm_wiki.query.brainstorm ask|brainstorm ..."""
    parser = argparse.ArgumentParser(description="...")  # paste original description
    sub = parser.add_subparsers(dest="command", required=True)
    register_ask(sub.add_parser("ask"))
    register_brainstorm(sub.add_parser("brainstorm"))
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
```

`_run_ask` and `_run_brainstorm` bodies are byte-for-byte the original branch handlers. Read the original around line 95 (where the `ask`/`brainstorm` subparsers split) and around `def main()` (~line 371) to see exactly which body goes where; the original `if args.command == "ask": ...` block is `_run_ask`, the `elif args.command == "brainstorm": ...` block is `_run_brainstorm`.

- [ ] **Step 6: Add `register(parser)` + `_run(args)` to `quant_llm_wiki/agent/cli.py`**

Original `agent_cli.py:main` (line 84) builds an `argparse.ArgumentParser` (line 25), parses `--query` and optional flags, then runs the agent loop. Refactor to the same pattern as Task 6 Step 3:

```python
def register(parser: argparse.ArgumentParser) -> None:
    # paste add_argument calls verbatim from old main()
    parser.add_argument("--query", ...)
    ...
    parser.set_defaults(func=_run)


def _run(args) -> int:
    # paste original main() body (line 84+) verbatim, minus the parser
    # construction at line 25 and the parse_args() call
    ...


def main() -> int:
    parser = argparse.ArgumentParser(description="Knowledge base agent CLI")
    register(parser)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 7: Create `quant_llm_wiki/cli.py` dispatcher**

```python
"""qlw CLI entry point — dispatches to per-module register/main pairs."""
from __future__ import annotations

import argparse

from quant_llm_wiki import enrich, embed, sync
from quant_llm_wiki.ingest import wechat
from quant_llm_wiki.query import brainstorm
from quant_llm_wiki.agent import cli as agent_cli


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="qlw")
    sub = parser.add_subparsers(dest="cmd", required=True)

    wechat.register(sub.add_parser("ingest", help="Ingest WeChat articles or HTML files."))
    enrich.register(sub.add_parser("enrich", help="Enrich raw articles with LLM-generated metadata."))
    embed.register(sub.add_parser("embed", help="Build/update the ChromaDB vector index."))
    sync.register(sub.add_parser("sync", help="Move articles based on frontmatter status."))
    brainstorm.register_ask(sub.add_parser("ask", help="RAG Q&A over the knowledge base."))
    brainstorm.register_brainstorm(sub.add_parser("brainstorm", help="Generate brainstorm ideas with Rethink validation."))
    agent_cli.register(sub.add_parser("agent", help="Run the LangGraph agent (interactive or one-shot)."))

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 8: Add `[project.scripts]` to `pyproject.toml`**

Insert after the `[project]` block:

```toml
[project.scripts]
qlw = "quant_llm_wiki.cli:main"
```

- [ ] **Step 9: Update test imports + patch targets for `agent.X` → `quant_llm_wiki.agent.X`**

```bash
sed -i \
    -e 's|"agent\.graph\.|"quant_llm_wiki.agent.graph.|g' \
    -e 's|"agent\.tools\.|"quant_llm_wiki.agent.tools.|g' \
    tests/test_agent_graph.py tests/test_agent_tools.py
sed -i 's|^from agent\b|from quant_llm_wiki.agent|' tests/test_agent_graph.py tests/test_agent_tools.py
sed -i 's|^import agent\b|import quant_llm_wiki.agent as agent|' tests/test_agent_graph.py tests/test_agent_tools.py

grep -rn '"agent\.\|^from agent\b\|^import agent\b' tests/
```

Expected: no output.

- [ ] **Step 10: Install in editable mode and run smoke**

```bash
pip install -e . 2>&1 | tail -5
qlw --help
qlw ingest --help
qlw ask --help
qlw brainstorm --help
qlw agent --help
```

Expected: each `--help` prints the subcommand's options.

If `vector_store/` and articles exist, also run:

```bash
qlw ask --query "what factors are discussed" 2>&1 | tee /tmp/qlw_smoke_after.txt
diff /tmp/qlw_smoke_baseline.txt /tmp/qlw_smoke_after.txt   # expect identical (or both empty)
```

If the diff shows a meaningful change (different answer text, different retrieval), **stop and revert** — that's a business-logic regression.

- [ ] **Step 11: Run all tests**

```bash
python3 -m unittest discover -s tests -p 'test_*.py' 2>&1 | tail -3
python3 -m unittest discover -s tests/robustness -p 'test_*.py' 2>&1 | tail -3
```

Expected: unchanged counts.

- [ ] **Step 12: Commit**

```bash
git add quant_llm_wiki/ pyproject.toml tests/test_agent_graph.py tests/test_agent_tools.py
git status --short
git commit -m "refactor: move agent/ into package + wire qlw CLI dispatcher

- agent/ + agent_cli.py → quant_llm_wiki/agent/{,cli.py}
- Each module gains register(parser)+main(args) (argparse block lifted
  verbatim; bodies unchanged)
- New quant_llm_wiki/cli.py dispatches to all subcommands
- pyproject.toml exposes qlw entry point

Verified: pip install -e . succeeds; qlw --help and per-subcommand
--help work; existing tests pass; smoke 'qlw ask' on existing
vector_store returns identical output to pre-refactor."
```

---

## Task 7: Update README and `docs/`

**Files:**
- Modify: `README.md` (sections: File Structure, Quick Start, Agent Usage, Running Tests, plus a new Command Renaming Table)
- Modify: `docs/brainstorm-cli-usage.md`, `docs/embed-knowledge-base-usage.md`, `docs/ingest-script-usage.md`, `docs/llm-enrichment-usage.md`, `docs/ingestion-workflow.md` (replace every `python3 X.py ...` example with `qlw <subcmd> ...`)

- [ ] **Step 1: Replace the `## File Structure` block in `README.md`**

Locate the block starting at `## File Structure` (~line 94) and ending at the closing ` ``` ` (~line 141). Replace with the layout from the spec:

```
QuantRAGForge/
├── pyproject.toml
├── requirements.txt
├── llm_config.example.env
├── README.md
├── LICENSE
├── quant_llm_wiki/
│   ├── __init__.py
│   ├── cli.py                  # qlw entry point
│   ├── shared.py
│   ├── ingest/
│   │   └── wechat.py
│   ├── enrich.py
│   ├── embed.py
│   ├── sync.py
│   ├── query/
│   │   ├── brainstorm.py
│   │   └── rethink.py
│   └── agent/
│       ├── cli.py
│       ├── graph.py
│       ├── prompts.py
│       └── tools.py
├── templates/
├── tests/
│   ├── test_*.py
│   └── robustness/
└── docs/
```

- [ ] **Step 2: Add a "Command Renaming Table" section right after `## Quick Start` heading (or before it)**

```markdown
### Command Renaming (vs. previous versions)

| Old | New |
|-----|-----|
| `python3 ingest_wechat_article.py --url X` | `qlw ingest --url X` |
| `python3 enrich_articles_with_llm.py --limit 10` | `qlw enrich --limit 10` |
| `python3 embed_knowledge_base.py` | `qlw embed` |
| `python3 sync_articles_by_status.py` | `qlw sync` |
| `python3 brainstorm_from_kb.py ask --query Q` | `qlw ask --query Q` |
| `python3 brainstorm_from_kb.py brainstorm --query Q` | `qlw brainstorm --query Q` |
| `python3 agent_cli.py` | `qlw agent` |

Repo name: `Quant_LLM_Wiki`. Package name: `quant_llm_wiki`. Command name: `qlw`.

Install with `pip install -e .` to get the `qlw` command on PATH; otherwise use `python -m quant_llm_wiki.cli <subcmd>`.
```

- [ ] **Step 3: Replace command examples in remaining README sections**

In `## Quick Start` and `## Agent Usage`, replace every instance:

| Old | New |
|-----|-----|
| `python3 ingest_wechat_article.py` | `qlw ingest` |
| `python3 enrich_articles_with_llm.py` | `qlw enrich` |
| `python3 embed_knowledge_base.py` | `qlw embed` |
| `python3 brainstorm_from_kb.py ask` | `qlw ask` |
| `python3 brainstorm_from_kb.py brainstorm` | `qlw brainstorm` |
| `python3 agent_cli.py` | `qlw agent` |

```bash
sed -i \
    -e 's|python3 ingest_wechat_article\.py|qlw ingest|g' \
    -e 's|python3 enrich_articles_with_llm\.py|qlw enrich|g' \
    -e 's|python3 embed_knowledge_base\.py|qlw embed|g' \
    -e 's|python3 sync_articles_by_status\.py|qlw sync|g' \
    -e 's|python3 brainstorm_from_kb\.py ask|qlw ask|g' \
    -e 's|python3 brainstorm_from_kb\.py brainstorm|qlw brainstorm|g' \
    -e 's|python3 agent_cli\.py|qlw agent|g' \
    README.md docs/brainstorm-cli-usage.md docs/embed-knowledge-base-usage.md \
    docs/ingest-script-usage.md docs/llm-enrichment-usage.md docs/ingestion-workflow.md

grep -rn "python3 \(ingest_wechat\|enrich_articles\|embed_knowledge\|sync_articles\|brainstorm_from\|agent_cli\)" README.md docs/
```

Expected: no output.

- [ ] **Step 4: Verify README rendering**

Open `README.md` in any markdown previewer (or `cat README.md | head -50`) and confirm:
- File Structure block matches the new layout
- Command examples all use `qlw`
- Command Renaming Table is present

- [ ] **Step 5: Run tests one last time as a sanity check (no code changes here)**

```bash
python3 -m unittest discover -s tests -p 'test_*.py' 2>&1 | tail -3
python3 -m unittest discover -s tests/robustness -p 'test_*.py' 2>&1 | tail -3
```

Expected: unchanged counts.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/brainstorm-cli-usage.md docs/embed-knowledge-base-usage.md \
        docs/ingest-script-usage.md docs/llm-enrichment-usage.md docs/ingestion-workflow.md
git status --short
git commit -m "docs: update README + docs to qlw CLI and new package layout

- File Structure block reflects quant_llm_wiki/ tree
- Adds Command Renaming Table (old python3 ... → qlw ...)
- Replaces every python3 <script>.py example across README and docs/

Layout-only refactor complete."
```

---

## Post-flight

- [ ] **Post-1: Final state check**

```bash
ls *.py 2>&1                                 # expect: no output (all root scripts moved)
ls quant_llm_wiki/                           # expect: package tree
qlw --help                                   # works
git log --oneline | head -10                 # 7 new commits beyond the spec commit
git diff --cached --name-only | wc -l        # still ≈61 (pre-existing staged changes untouched)
```

- [ ] **Post-2: Reference output check**

```bash
python3 -m unittest discover -s tests -p 'test_*.py' 2>&1 | tail -3
python3 -m unittest discover -s tests/robustness -p 'test_*.py' 2>&1 | tail -3
```

Counts equal to Pre-2 baseline.

- [ ] **Post-3: Smoke parity check (if data exists)**

```bash
qlw ask --query "what factors are discussed" > /tmp/qlw_smoke_after.txt 2>&1 || true
diff /tmp/qlw_smoke_baseline.txt /tmp/qlw_smoke_after.txt
```

Expected: identical (or both empty / both errored the same way).

---

## Rollback

If any task's tests fail for a reason other than a missed import path:

```bash
git reset --hard HEAD~1     # undo the broken task's commit
```

Then re-do the task more carefully. **Never modify a test assertion** or business-function body to make tests pass — that violates the Hard Invariants in the spec.
