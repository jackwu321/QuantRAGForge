# Restructure Execution Progress

Updated as each task is reviewed and accepted.
If a future session needs to resume: read this file + `git log --oneline | head -20` to know exactly where we are.

**Plan:** [`2026-05-06-repo-restructure.md`](2026-05-06-repo-restructure.md)
**Spec:** [`../specs/2026-05-06-repo-restructure-design.md`](../specs/2026-05-06-repo-restructure-design.md)
**Branch:** `main`
**Pre-existing staged changes:** stashed as `stash@{0}` (`pre-restructure-pending-changes-2026-05-06`); recoverable via `git stash pop`. Untracked backup of 3 conflicting files: `/tmp/qlw-untracked-backup/`.

## Execution model

- Each task is dispatched to a **fresh Sonnet 4.6 subagent** with the plan path + the specific Task # to execute.
- Opus 4.7 (this session) reviews the resulting diff and the test output before approving the next task.
- Every task ends with a git commit, so progress is durable across context loss.

## Task ledger

| Task | Status | Commit SHA | Reviewed at | Notes |
|------|--------|------------|-------------|-------|
| Pre-flight | – | – | – | Baseline test counts captured (see below) |
| Task 1 — gitignore + pyproject skeleton + remove =1.0.0 | ✅ done | `df683d0` | 2026-05-06 | `=1.0.0` was untracked → removed via `rm` instead of `git rm` (no git impact); tests 262 + 72 OK |
| Task 2 — move shared + sync | ✅ done | `7e22c87` | 2026-05-06 | Verified by Opus on resume: 265+72 tests OK; smoke output matches baseline; no unaliased stale imports. Commit also touched additional wiki_*.py / kb.py / ingest_source.py files that import kb_shared (post-plan additions) — necessary scope expansion, all import-only. |
| Task 3 — move ingest_wechat | ✅ done | `fb67a6c` | 2026-05-06 | R099 rename detected. `ROOT = parent.parent.parent` adjusted for new depth (path anchor, not business logic). Scope-creep: `ingest_source.py` (lazy imports) + `tests/robustness/test_layer1_tool_robustness.py` (mock.patch targets) — both import-only. 265+72 OK. |
| Task 4 — move enrich + embed | ✅ done | `6abba98` | 2026-05-06 | 4× R100 renames. Path-anchor fix in `enrich.py` (`parent` → `parent.parent`); embed had none. Scope-creep: `kb.py`, `tests/robustness/conftest.py`, `tests/robustness/test_layer4_llm_api_robustness.py` — all import/alias/patch only. 265+72 OK. |
| Task 5 — move brainstorm + rethink (query/) | ✅ done | `9956980` | 2026-05-06 | 4× renames (R099/R100/R099/R090). No path-anchor fix needed (both derive paths via shared). Scope-creep: `kb.py`, `tests/test_brainstorm_with_wiki.py`, `tests/test_query_wiki_first_ask.py`, `tests/test_kb_cli.py`, `tests/robustness/conftest.py` — all import/alias/patch only. 265+72 OK. |
| Task 6 — move agent/ + wire qlw CLI | ✅ done | `9a26eb9` + fixup `19eb6f4` | 2026-05-06 | 5× R100 agent renames + new `cli.py` dispatcher + register/_run/main wrappers + pyproject scripts. Path-anchor fixes in 4 files (depth shift). Smoke parity diff = empty. **Note:** Sonnet's first commit `9a26eb9` excluded post-rename content edits (Task 4 had the same gap on `tests/test_embed.py`/`test_enrich.py`); fixup `19eb6f4` patches both. Scope-creep: 5 robustness test files (mock.patch + indented `from agent.tools` imports). Brainstorm dual-subcommand uses `args.command = "ask"/"brainstorm"` set inside each `_run_*` to keep body byte-identical. `_wechat.py` (root-level helper) needed `sys.path.insert` shim in `quant_llm_wiki/ingest/wechat.py`. 265+72 OK on committed state. |
| Task 7 — README + docs cleanup | ✅ done | `dca62cb` | 2026-05-06 | Executed by Opus directly (Sonnet rate-limited). Rewrote README File Structure block to reflect both `quant_llm_wiki/` package and unchanged `kb.py`/`wiki_*.py`. Added Command Renaming Table. sed-replaced every `python[3]? <script>.py` across README + 4 docs files (`docs/ingestion-workflow.md` had none). Pure-HEAD verify: 265+72 OK. |
| Post-flight | ✅ done | – | 2026-05-06 | All root scripts moved; `quant_llm_wiki/` package complete with `cli.py` dispatcher; `qlw --help` lists 7 subcommands; smoke `qlw ask` diff vs baseline = empty; tests 265+72 OK on pure HEAD. |

## Baseline (Pre-flight, captured 2026-05-06)

```
unittest tests/             : Ran 262 tests in 20.7s — OK
unittest tests/robustness/  : Ran 72 tests in 21.2s — OK
qlw smoke baseline          : /tmp/qlw_smoke_baseline.txt
                              "no candidate notes found after applying source/status/metadata filters"
                              (exit code 1; expected for this query against current data)
```

**Acceptance after every task:** `unittest tests/` still 262 OK, `unittest tests/robustness/` still 72 OK, smoke output identical to baseline.

## Resumption protocol

If returning from a `/usage` interruption or fresh session:

1. `git log --oneline | head -10` — find the last task-commit (commit messages start with `refactor:` / `chore:` / `docs:`).
2. Read this file's task ledger to identify the next pending task.
3. Read the plan file for that Task's full step list.
4. Dispatch a Sonnet subagent with: "Execute Task N from `docs/superpowers/plans/2026-05-06-repo-restructure.md`. Do NOT use `git add -A`/`.`; use the explicit pathspec in each commit step. Stop and report if any test fails for a non-import reason."
5. After review, append the row to this ledger and commit.
