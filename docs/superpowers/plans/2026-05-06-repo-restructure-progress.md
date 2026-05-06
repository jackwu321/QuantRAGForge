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
| Task 2 — move shared + sync | pending | – | – | |
| Task 3 — move ingest_wechat | pending | – | – | |
| Task 4 — move enrich + embed | pending | – | – | |
| Task 5 — move brainstorm + rethink (query/) | pending | – | – | |
| Task 6 — move agent/ + wire qlw CLI | pending | – | – | |
| Task 7 — README + docs cleanup | pending | – | – | |
| Post-flight | – | – | – | |

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
