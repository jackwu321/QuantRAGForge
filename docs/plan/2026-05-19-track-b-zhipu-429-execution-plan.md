# Track B Execution Plan — Zhipu 429 Hardening Rebase + Extensions

**Drafted:** 2026-05-19 (after Track A landed on `lint/measure-instrumentation`).
**Supersedes the Track B section of:** [`2026-05-19-execution-arrangement-lint-and-zhipu.md`](2026-05-19-execution-arrangement-lint-and-zhipu.md) (use this file for Track B; that one stays canonical for Track A and the shared per-task subagent contract).
**Source spec:** [`docs/superpowers/specs/2026-05-18-next-steps-lint-and-zhipu.md`](../superpowers/specs/2026-05-18-next-steps-lint-and-zhipu.md)
**Remote branch under review:** `origin/zhipu-429-rate-limit-hardening` @ `34ae568` (single commit, based on `v0.4.3 / ad1ebf7`).
**Local feature branch to create:** `zhipu/429-rebase`.

---

## 1. Pre-rebase audit (done)

This section is the audit output from 2026-05-19, not an action item. Subsequent tasks below act on these findings.

### 1.1 Behavior changes vs `main`

**Observable behavior:**

- `LLM_MIN_INTERVAL_SECONDS` default `0.5 → 2.0` (4× slower pacing — conservative tilt).
- `DEFAULT_CONNECT_TIMEOUT` `10 → 15`, `DEFAULT_READ_TIMEOUT` `120 → 180`, `DEFAULT_MAX_RETRIES` `2 → 4`.
- **New process-wide 429 cooldown gate**: any worker that receives a 429 sets a shared `_llm_cooldown_until`; every subsequent `post_llm_json` call in the process sleeps until the cooldown lapses before issuing its request.
- `Retry-After` header is honored ahead of exponential backoff, capped at 60 s.
- The 429-retry path no longer calls `time.sleep(wait)` inside the retry loop; the wait is converted into a cooldown that the next attempt's `_enforce_llm_rate_gate` consumes (avoids double-sleep).
- `[llm-retry]` stderr line is enriched with `global cooldown` / `Retry-After honored` flags.

**Implementation details:**

- New `_llm_cooldown_until: float` module-level state, reusing the existing `_llm_call_lock`.
- `_enforce_min_interval` is renamed to `_enforce_llm_rate_gate`; `wait = max(min_interval_wait, cooldown_wait)`.
- `_set_llm_cooldown(wait)` uses `max(_llm_cooldown_until, now + wait)` so concurrent 429s extend rather than overwrite the cooldown.

### 1.2 Rebase risk assessment

- The merge-base of `origin/zhipu-429-rate-limit-hardening` and `main` is `ad1ebf7` (the `v0.4.3` tag commit). The branch is **not** based on current `main`; it was authored from `v0.4.3`.
- However, `git log ad1ebf7..main` shows **no commits** modify any of the five files the branch touches: `quant_llm_wiki/shared.py`, `llm_config.example.env`, `README.md`, `tests/test_kb_root_resolution.py`, `tests/robustness/test_layer4_llm_api_robustness.py`.
- Therefore a rebase of `34ae568` onto current `main` is expected to be a clean fast-forward of the single commit — the merge-base moves from `ad1ebf7` to current `main` without any 3-way merging because no overlapping edits exist. Conflicts are not anticipated.

### 1.3 What must be fixed before extensions — vs spec's claims

| Concern (per spec / original arrangement) | Audit finding | Action |
|---|---|---|
| **B.1c hermetic-test fix** — spec claimed some `patch` targets in `tests/robustness/test_layer4_llm_api_robustness.py` miss the actual symbol used by `post_llm_json` (`requests.post` vs `Session.post`, wrong module path). | **Concern is unfounded.** `post_llm_json` (`quant_llm_wiki/shared.py:481`) calls `requests.post(...)` directly, not via a session. All new tests on the branch patch `quant_llm_wiki.shared.requests.post` and `quant_llm_wiki.shared.time.sleep` — both targets resolve correctly. The `https://fake.url/v4` strings only appear inside mocked `get_llm_config` return values; the outer callers (`post_llm_json`, `call_llm_chat`, `embed_text`) are themselves mocked at the wrapper level in tests under `TestToolAPIFailures`, so the URL is never sent. Branch-as-is robustness suite: `78 tests in 21.6 s OK`; same suite under `unshare -rn` hard network isolation: `78 tests in 21.9 s OK` (same wall, no DNS hang). | **Skip B.1c entirely.** Hermeticity is real, not coincidental. Record the verification log in the eventual PR description / release notes — **do not create a "hermetic verified" note commit**, because nothing in the repo actually changed. |
| Cooldown `time.sleep(wait)` happens inside `_llm_call_lock` | This is pre-existing v0.4.3 behavior (`_enforce_min_interval` already slept inside the lock). N concurrent workers waiting on the same cooldown sleep serially (`N × cooldown_seconds` wall time), not concurrently. Not a regression introduced by this branch. | **Out of scope** for this iteration. Note as a follow-up if real concurrent enrichment workloads show degradation. |
| `_llm_cooldown_until = 0.0` reset inside the gate | Semantically correct — only the first thread to observe a positive cooldown clears it; later threads see `cooldown_wait <= 0` and pass through. The explicit reset after sleep is cosmetic. | No change. |
| **Retry-After parsing gaps (B.3.f)** | Real gap. `_retry_after_seconds` in `quant_llm_wiki/shared.py:398-415` only handles plain-seconds; the inline comment acknowledges "HTTP-date format is rare from LLM providers; skip rather than parse." Negative values are clamped by `max(0.0, ...)` but there is no test that exercises 0 / negative / very-large / HTTP-date. | **Do B.3.f.** Add `email.utils.parsedate_to_datetime` fallback + edge-value tests. |

### 1.4 B.3 picks — recommended

| Item | Decision | Rationale |
|---|---|---|
| **B.3.a** — observability `_emit_perf("llm_rate_gate", cooldowns_applied=N, total_wait_ms=T)` | **Do.** ~30 LoC + 1 test, `QLW_PERF_DEBUG`-gated (zero runtime cost when off). Provides the data on which any future B.3.c per-endpoint decision would be gated. |
| **B.3.b** — verify jitter on backoff | **Do (verify-only).** `_backoff_seconds` (`shared.py:418-433`) already adds `random.uniform(0, base)` — full jitter is implemented. Add a distribution test that asserts the value is in `[base * 2^N, base * 2^N + base]` and is non-degenerate over 20 calls. Zero production-code change, only a new test locking the invariant. |
| **B.3.f** — Retry-After robustness | **Do.** See 1.3 above. |
| **B.3.c** — per-endpoint gate | **Defer.** Spec defers explicitly until B.3.a data shows hotspot endpoints. |
| **B.3.d** — token-budget tracking | **Out of scope.** Spec-deferred. |
| **B.3.e** — cross-process cooldown | **Out of scope.** Spec-deferred. |

**Default G3 menu, per this audit:** `{B.3.a, B.3.b, B.3.f}`.

---

## 2. Task plan (action items)

Each row follows the per-task subagent contract from the original arrangement doc (§ "Per-task subagent contract") unless explicitly noted. Sonnet implementer → throwaway `git worktree add /tmp/qlw-verify-<sha>` HEAD verification (controller, not delegated) → Opus spec-review on substantive code/test changes only.

| ID | Task | Files touched | Verify | Model | Gate |
|----|------|---------------|--------|-------|------|
| **B1a** | `git fetch origin && git checkout -b zhipu/429-rebase origin/zhipu-429-rate-limit-hardening && git rebase main`. Confirm 0 conflicts (expected per 1.2). | git only | `git log --oneline main..HEAD` shows the single rebased commit; `git status` clean. | sonnet or controller | none |
| **B1b** | Run full `tests/` and `tests/robustness/` against the rebased branch in a throwaway worktree. **No isolation flag needed** — branch is hermetic per audit 1.3. Capture results for the PR description. | none | `Ran … OK` for both suites. **No commit produced** by this step. | controller | none |
| **B2** | Independent review of rebased branch (Opus + optionally `/codex review`). Confirms: (a) cooldown threading + monotonic clock correctness, (b) ordering of `_set_llm_cooldown` vs `attempt >= max_retries` (currently sets cooldown even on last attempt → correct, future calls should still honor it), (c) `Retry-After` handling is plain-seconds-only (matches audit 1.3 finding for B.3.f), (d) hermetic verification is real. | — | Review verdict. | opus + codex | **G3 — HARD STOP. User confirms B.3 picks.** Default `{a, b, f}`. |
| **B3.a** | Add `_emit_perf("llm_rate_gate", cooldowns_applied=N, total_wait_ms=T)` at end of each `post_llm_json` call. Counter is per-call: increment inside `_enforce_llm_rate_gate` (passed back via thread-local or per-call accumulator). Add 1 test asserting the line emits with `QLW_PERF_DEBUG=1` and is silent without it. | `quant_llm_wiki/shared.py`, `tests/test_perf_instrumentation.py` | New test + full suite green. | sonnet | per-task. |
| **B3.b** | Verify jitter distribution. Add a test that calls `_backoff_seconds(attempt=N, status=429, response=None)` 20 times, asserts every result lies in `[base * 2^N, base * 2^N + base]` and that the unique value count is > 1 (non-degenerate). No production change. Commit body must say "verify-only: jitter already implemented in `_backoff_seconds`". | `tests/robustness/test_layer4_llm_api_robustness.py` | New test green. | sonnet | per-task. |
| **B3.f** | Extend `_retry_after_seconds` (`shared.py:398-415`) to: (i) parse HTTP-date via `email.utils.parsedate_to_datetime` and convert to seconds from now (clamped to `max(0.0, ...)`); (ii) keep plain-seconds path as-is; (iii) keep `None` on unparseable. Add tests for plain seconds, HTTP-date (`Wed, 21 Oct 2026 07:28:00 GMT`), 0, negative ("`-5`"), very large ("`86400`"). | `quant_llm_wiki/shared.py`, `tests/robustness/test_layer4_llm_api_robustness.py` | New tests + full suite green. | sonnet | per-task. |
| **BFin** | Final code review of full Track B diff (rebased commit + B.3.a/b/f). **No release ops here.** | — | Opus reviewer verdict. | opus | On ✅ → **G4** (Track B + Track A ship/version decision). |
| **BRel** | Release after G4 chooses version. Bump `pyproject.toml`, update `CHANGELOG.md`, single commit, tag, push. Combines Track A (already merged on `lint/measure-instrumentation`) and Track B if G2 was "bundle". | `pyproject.toml`, `CHANGELOG.md` | `git tag` exists; tag pushed; CI release workflow triggers. | opus orchestration | post-G4. |

### 2.1 Gates

| Gate | When | Question | Effect |
|------|------|----------|--------|
| **G3** | After B2 review | "Confirm `{B.3.a, B.3.b, B.3.f}` — override?" | Selects which B3.x tasks run. |
| **G4** | After BFin approves | "Version: v0.4.6 (bundles Track A + Track B; Track A's mtime cache is user-visible enough to warrant a patch release) / v0.5.0 (only if Track B's default-MIN_INTERVAL change of 0.5→2.0 counts as a behavior break worth a minor)?" | Selects BRel version string. |

### 2.2 Commit-vs-log policy (from user feedback 2026-05-19)

- **Do not commit "verification ran clean" notes** when nothing in the repo changed. Test runs, isolation reruns, and timing snapshots belong in: the task log within this session, the PR description, or the release notes — never as a standalone repo commit.
- Commit only when there is a real diff to the repo (code, doc, test). The reverse is also true: if a real bug fix or doc clarification falls out of verification, that becomes its own bisectable commit.

---

## 3. Out of scope for Track B

- v0.4.2 tag-push housekeeping verification.
- Production-mode (non-mock) benchmark of the cooldown gate against a real provider — would require live API budget; defer to user.
- B.3.c (per-endpoint gate) — gated on B.3.a data.
- B.3.d (token-budget tracking) — spec-deferred.
- B.3.e (cross-process cooldown via filesystem) — spec-deferred.
- Refactoring the lock-held `time.sleep` in `_enforce_llm_rate_gate` to release the lock during sleep (pre-existing behavior; not a regression; needs its own spec).

---

## 4. State at this plan's drafting

- Branch `lint/measure-instrumentation` carries Track A's 4 commits ahead of `main`:
  ```
  cf54f2f docs(perf): A2.2 cached lint_report short-circuit measurement
  5d14ce6 test(query/brainstorm): fix cache-hit test patch target
  f8fb327 perf(query/brainstorm): cache lint_report on query path via mtime short-circuit
  5faf77a docs(perf): A1b lint_wiki query-path measurement (small/medium/large)
  ```
  Pure HEAD verified 342 tests OK. Tier A.2 chosen at G1.
- Track B audit (this document) is the only output of the pre-rebase audit step; no code or doc commit was produced because no fix was needed.
- Next action when resumed: **B1a** (create `zhipu/429-rebase` from remote branch, rebase onto current `main`).
