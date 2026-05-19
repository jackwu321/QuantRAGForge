# Execution Arrangement — Track A (lint_wiki) + Track B (zhipu 429)

**Spec:** [`docs/superpowers/specs/2026-05-18-next-steps-lint-and-zhipu.md`](../superpowers/specs/2026-05-18-next-steps-lint-and-zhipu.md)
**Drafted:** 2026-05-19
**Pattern:** Sonnet implementer + Opus spec-reviewer + Opus code-quality-reviewer + Opus final reviewer.
**Order:** Track A in full → Track B in full. Two tracks, two feature branches.
**Baseline:** `main @ 9d3b3bc` (v0.4.5).

---

## Plan critique (raised before execution)

| # | Concern | Resolution before kickoff |
|---|---------|----------------------------|
| 1 | We're on `main`. | Create feature branch per track (`lint/measure-instrumentation` → Track A, `zhipu/429-rebase` → Track B). All Sonnet commits land there; main stays untouched until merge. |
| 2 | Phase 1 → Phase 2 decision is human-gated (A.1 vs A.2 vs A.3). | Hard stop after Phase 1; surface the measurement table; ask user. No auto-tier-selection. |
| 3 | Track B B.3 menu is human-gated. | Hard stop after B.2 review; surface review verdict + recommended B.3 picks; ask user. |
| 4 | `feedback_verify_sonnet_commits_against_pure_head` rule. | After every Sonnet commit, controller (Opus) verifies the **pure committed HEAD** in a throwaway `git worktree add /tmp/qlw-verify-<sha> <sha>` directory and runs the relevant test command there. **No `git stash` on the live worktree** — the live worktree has untracked plan/spec files that must not migrate. The throwaway worktree is removed after verification. Not delegated to Sonnet. |
| 5 | Hermetic-test fix in B.1 is non-trivial — patching the right symbol resolved at call site, not definition. | Treat the hermetic-test fix as its own task with its own spec-review (separate commit, bisectable). Reviewer must verify no `patch(...)` target resolves to a real HTTP method **and** that the robustness suite passes under hard network isolation (see B1c). |
| 6 | Untracked `docs/plan/2026-05-19-…md` + `docs/superpowers/specs/2026-05-18-next-steps-…md` live in the worktree; switching branches risks them migrating into feature commits. | Pre-kickoff housekeeping: commit both docs to `main` first (single docs commit), so feature branches inherit them as tracked-and-clean. Removes the stash/pop footgun and lets the throwaway-worktree verification be deterministic. |
| 7 | Release ops (version bump, tag, push) were attached to AFin/BFin in the prior draft, which would bypass G2/G4. | AFin and BFin do **review only**. Version bump / CHANGELOG / commit / tag-push happen in a separate "release" step that fires **after** G2 (Track A) or G4 (Track B), never as part of the final-review task. |
| 8 | B.3.c (per-endpoint gate) was in the G3 menu, but spec defers it pending B.3.a observability data. | G3 menu restricted to `{a, b, f}`. B.3.c moves to a post-ship follow-up gated on B.3.a data. |

No blocking gaps. Ready to dispatch once pre-kickoff housekeeping (concern #6) lands.

---

## Branch / worktree layout

```
main (untouched until merges land)
├── lint/measure-instrumentation   ← Track A all tasks
└── zhipu/429-rebase               ← Track B all tasks (rebase of origin/zhipu-429-rate-limit-hardening)
```

Track A is sequential and small; one branch in the live worktree is fine. Track B rebases an existing remote branch — create the local branch from `origin/zhipu-429-rate-limit-hardening` and rebase onto `main`.

---

## Task breakdown

Each row = one Sonnet implementer dispatch → one Opus spec-review → one Opus code-quality-review → controller verifies pure HEAD in a throwaway `git worktree`.

### Track A — lint_wiki measurement (gated)

| ID | Task | Files touched | Verify | Model | Gate |
|----|------|---------------|--------|-------|------|
| A0 | **Single commit, both halves together.** (a) Wrap `_wiki_is_healthy_for_query` with `QLW_PERF_DEBUG`-gated `_emit_perf("query_lint", lint_ms=...)`; also instrument inside `lint_wiki` to attribute scan-vs-write cost. (b) Add line-format lock test in `tests/test_perf_instrumentation.py` (regex match for `query_lint: lint_ms=…`), pattern after existing `compile_wiki`/`retrieve_blocks` tests. Merged because a Phase 0 commit without the lock test still lets the benchmark regex silently drift. | `quant_llm_wiki/query/brainstorm.py`, `quant_llm_wiki/wiki/lint.py`, `tests/test_perf_instrumentation.py` | New format-lock test + full `unittest discover tests/` green in the throwaway HEAD-worktree. | sonnet | none |
| A1a | Extend `scripts/benchmark_perf.py` with `--no-mock-lint` flag; remove the `unittest.mock.patch.object(brainstorm_mod, "_wiki_is_healthy_for_query", return_value=True)` only on this code path. Seed synthetic KB with realistic concept files (status=stable, sources/related_concepts/key_idea_blocks populated). | `scripts/benchmark_perf.py` | Harness runs at `--scale small/medium/large` and emits `query_lint` lines parseable by the regex locked in A0. | sonnet | none |
| A1b | Run 5-trial benchmark at small/medium/large with `--no-mock-lint`; aggregate `query_lint.lint_ms` median per scale; record in a tracked perf-validation update. Spot-check on user's real wiki. | `docs/superpowers/specs/2026-05-17-perf-validation-report.md` (append) | Three medians + linear-growth check. | sonnet | **G1 — HARD STOP. User picks A.1 / A.2 / A.3.** |
| A2.1 | (A.1 path) Mark spec Out-of-Scope item as "measured, not worth it at current scale; revisit at Nx". No code beyond A0/A1a. | `docs/superpowers/specs/2026-05-18-next-steps-lint-and-zhipu.md` (status note) + perf report | Tests still green. | sonnet | n/a — exit Track A. |
| A2.2 | (A.2 path) Implement cached `lint_report.json` short-circuit covering `wiki/concepts/*.md` + `wiki/sources/*.md` + `wiki/state.json` mtimes (re-grep `wiki/lint.py` for any other inputs before commit). 5 new tests per spec. | `quant_llm_wiki/query/brainstorm.py`, `tests/test_brainstorm.py` | New 5 tests + full suite green. Phase 2 measurement re-run shows `lint_ms` drops to single-digit ms on cached path. | sonnet | none (no release yet). |
| A2.3 | (A.3 path) Out-of-scope for this iteration — requires a fresh brainstorm session (staleness model + degradation strategy choice). | — | — | — | Stop Track A; open follow-up plan. |
| AFin | **Final code review only.** Opus reviews the full Track A diff. **No version bump, no commit, no tag, no push at this step.** | — | Opus reviewer verdict. | opus | On ✅ → **G2** (Track A ship/bundle decision). |
| ARel | **Release step — only fires after G2 chooses "ship Track A now".** Bump `pyproject.toml` version (A.1 → no bump or `+perf-measurement`; A.2 → v0.4.6), update CHANGELOG, single commit, tag, push. Skipped if G2 chooses "bundle with Track B". | `pyproject.toml`, `CHANGELOG.md` | `git tag` exists; tag pushed; CI release workflow triggers. | opus (no implementation, just orchestration) | post-G2. |

### Track B — zhipu 429 rebase + extensions (gated)

| ID | Task | Files touched | Verify | Model | Gate |
|----|------|---------------|--------|-------|------|
| B1a | `git fetch origin`; create `zhipu/429-rebase` from `origin/zhipu-429-rate-limit-hardening`; `git rebase main`. Verify clean rebase. | git only | `git status` clean; `git log --oneline main..HEAD` shows single rebased commit. | sonnet | none |
| B1b | **Advisory smoke only** (gate is post-B1c). Run `tests/` and `tests/robustness/` with a hard **per-test timeout of 20 s** (e.g., `python3 -m unittest discover … -t .` wrapped in `timeout 600` plus a per-test `@unittest.skipIf` wrapper if needed). Report results as informational — used only to compare pre/post B1c. **If robustness suite hangs on `fake.url` DNS or fails on network**, that is the expected pre-hermetic-fix state; jump immediately to B1c. | — | Report observed pass/fail/hang per test class. No gating. | sonnet | none (advisory). |
| B1c | **Hermetic-test fix** — grep every `patch(`/`patch.object(` target in `tests/robustness/test_layer4_llm_api_robustness.py`, cross-check each against the symbol resolved at the call site in `quant_llm_wiki/shared.py:post_llm_json`, replace any wrong target. Land as separate bisectable commit. | `tests/robustness/test_layer4_llm_api_robustness.py` | **Hard network-isolation verification (one required, in priority order):** (i) if `unshare -rn` is available on host, run `unshare -rn python3 -m unittest tests.robustness.test_layer4_llm_api_robustness -v` and confirm green; OR (ii) install a `conftest.py`-level fixture / explicit `setUp` that monkey-patches `socket.socket`, `socket.create_connection`, and `socket.getaddrinfo` to raise immediately, then run the suite and confirm green. **Inspection-only is NOT sufficient.** Whichever method is used, the verification log goes in the PR/commit body. | sonnet | Spec-review extra-strict: reviewer confirms hard-isolation log present. |
| B1d | **Robustness suite as full gate** — re-run `tests/` and `tests/robustness/` (no special isolation needed now; the mocks block real network themselves). | — | `Ran … OK` for both, no timeouts. | sonnet | If fail → halt, diagnose, do not proceed to B2. |
| B2 | Independent Codex (and Opus) review of rebased branch + hermetic fix. | — | Review verdict: covers plan; correctness of cooldown/threading; hermetic fix complete (hard-isolation log present); B.3 candidate list with recommended picks. | opus + codex | **G3 — HARD STOP. User picks subset of `{B.3.a, B.3.b, B.3.f}`.** Default recommendation: all three (low-risk, real value). |
| B3.a | (if chosen) Add `_emit_perf("llm_rate_gate", cooldowns_applied=N, total_wait_ms=T)` at end of each `post_llm_json` call. ~20 LoC + 1 test. | `quant_llm_wiki/shared.py`, `tests/test_perf_instrumentation.py` | New test + full suite green. | sonnet | per-task. |
| B3.b | (if chosen) **Verify**, not add. Inspect existing tests in `tests/robustness/test_layer4_llm_api_robustness.py` for jitter-range coverage; add a distribution test if missing (assert `[0, base(N)]` bounded and non-degenerate over 20 calls). | `tests/robustness/test_layer4_llm_api_robustness.py` (likely) | New test green; document "verified, no production code change" in commit. | sonnet | per-task. |
| B3.f | (if chosen) Retry-After parser handles plain seconds (existing), HTTP-date fallback via `email.utils.parsedate_to_datetime`, edge values (0/negative/very large). ~10 LoC + tests. | `quant_llm_wiki/shared.py`, robustness tests | New tests cover plain-seconds, HTTP-date, edge values. | sonnet | per-task. |
| BFin | **Final code review only.** Opus reviews full Track B diff (rebased commit + hermetic fix + chosen B.3 items). **No version bump, no commit, no tag, no push at this step.** | — | Opus reviewer verdict. | opus | On ✅ → **G4** (Track B ship/version decision). |
| BRel | **Release step — only fires after G4 picks a version.** Bump `pyproject.toml` version (v0.4.6 / v0.4.7 / v0.5.0), update CHANGELOG, single commit, tag, push. | `pyproject.toml`, `CHANGELOG.md` | `git tag` exists; tag pushed; CI release workflow triggers. | opus (no implementation, just orchestration) | post-G4. |

**Spec-deferred / out of G3 menu** (will not be picked here; surfaced as follow-ups):

- **B.3.c — per-endpoint rate-gate**: gated on B.3.a observability data; revisit only if 429s consistently hit one endpoint.
- **B.3.d — token-budget tracking**: out of scope; revisit if B.3.a shows request-rate pacing isn't enough.
- **B.3.e — cross-process cooldown**: out of scope; existing spec defers it.

---

## Per-task subagent contract

Each Sonnet implementer dispatch receives, verbatim:

1. **Goal** — the row's "Task" cell.
2. **Files in scope** — the "Files touched" cell.
3. **Verification command** — the "Verify" cell + the global `python3 -m unittest discover -s tests -p 'test_*.py'` floor.
4. **TDD requirement** — write the failing test first when the task adds behavior; refactor only after green. (Skill: `superpowers:test-driven-development`.)
5. **Commit boundaries** — one logical change per commit; message in repo's existing style.
6. **Self-review** — implementer reports DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED.

After each Sonnet commit the controller (this Opus session):

1. Capture the commit SHA on the feature branch.
2. **No `git stash` on the live worktree.** Create a throwaway worktree: `git worktree add /tmp/qlw-verify-<sha> <sha>`.
3. `cd /tmp/qlw-verify-<sha>` and re-run the verify command there against the pure committed HEAD. (Per `feedback_verify_sonnet_commits_against_pure_head`.) The live worktree's untracked `docs/plan/…` files are unaffected.
4. Capture stdout/stderr to the task log; remove the throwaway worktree via `git worktree remove /tmp/qlw-verify-<sha>` once verification finishes (pass or fail).
5. Dispatch **Opus spec-reviewer** with the row's spec excerpt + the diff.
6. On spec-reviewer ✅, dispatch **Opus code-quality-reviewer**.
7. On both ✅, mark task complete in TodoWrite.
8. On either ❌, dispatch Sonnet fixer + re-review.

---

## Decision gates (where I will pause for you)

| Gate | When | Question to user | Effect |
|------|------|------------------|--------|
| G1 — Track A tier | After A1b benchmark medians land | "lint_ms median at large = X ms; small/medium/large trajectory = Y/Z/X. Tier A.1 / A.2 / A.3?" | Selects which of A2.1 / A2.2 / A2.3 runs next. |
| G2 — Track A ship | After AFin approves | "Ship Track A now (run ARel, tag v0.4.6 or +perf-measurement) or bundle with Track B (skip ARel, hold for Track B's BRel)?" **Default for tier A.1 = bundle / no standalone release** unless user explicitly picks patch release. | Decides whether ARel fires. |
| G3 — Track B B.3 picks | After B2 review verdict | "Default `{a, b, f}` — override?" Menu restricted to `{a, b, f}`. B.3.c/d/e remain follow-ups, **not selectable here**. | Decides which B3.x tasks run. |
| G4 — Track B ship/version | After BFin approves | "Version: v0.4.6 (if Track A bundled) / v0.4.7 (Track A already shipped) / v0.5.0 (minor — only if user-visible behavior shifted enough)?" | Selects ARel-or-not + BRel version string. |

---

## Out of scope for this execution

- v0.4.2 tag-push housekeeping verification.
- Production-mode (non-mock) benchmark of v0.4.5 hoist on real wiki.
- LLM-driven `run_maintenance()` (v0.5.0+ item).
- Optimizing `lint_wiki` itself (faster parse, smaller report).
- A.3 staleness-model design (deferred to fresh brainstorm if A1b lands us there).
- B.3.d (token-budget) and B.3.e (cross-process cooldown) — spec-deferred.

---

## Pre-kickoff housekeeping (must land first)

The live worktree currently has two untracked files that would migrate if we branch as-is:

- `docs/plan/2026-05-19-execution-arrangement-lint-and-zhipu.md` (this doc)
- `docs/superpowers/specs/2026-05-18-next-steps-lint-and-zhipu.md` (the spec)

**Action:** commit both to `main` as a single docs commit *before* creating either feature branch. Suggested message:

```
docs(plan): execution arrangement + spec for lint_wiki measurement and zhipu 429 rebase
```

After this commit, `main` is clean; feature branches inherit the docs as tracked baseline; throwaway-worktree verification is deterministic.

## Kickoff checklist

- [ ] User approves this revised arrangement.
- [ ] Pre-kickoff docs commit lands on `main` (untracked plan/spec → tracked).
- [ ] User confirms branch names: `lint/measure-instrumentation`, `zhipu/429-rebase`.
- [ ] Controller creates Track A branch and dispatches **A0** Sonnet implementer (instrumentation + format-lock test in a single commit).
