# Next Steps After v0.4.5 — Plan

> **Status:** plan only, do not execute. User-approved order: Track A first, then Track B.

## Context

After v0.4.5 (lazy `_build_index_text` hoist, tag pushed 2026-05-18 at commit `9d3b3bc`), two unfinished tracks remain:

1. **lint_wiki query-path cost** — flagged as Out-of-Scope in both `2026-05-17-brainstorm-compile-perf-design.md` and `2026-05-18-compile-index-text-hoist-design.md`. The hot query path (`brainstorm.py:789`) calls `_wiki_is_healthy_for_query` → `lint_wiki` → full filesystem scan of every `wiki/concepts/*.md` + write of `wiki/lint_report.json`. Magnitude **never measured** — the v0.4.4/v0.4.5 benchmarks mocked it to `True`.
2. **Zhipu 429 rate-limit hardening** — `docs/plan/2026-05-17-zhipu-429-rate-limit-hardening.md` was drafted; **implementation already exists on remote branch `origin/zhipu-429-rate-limit-hardening`** as a single commit `34ae568`, based on `v0.4.3 (ad1ebf7)`. It implements the plan end-to-end (process-wide LLM cooldown, `Retry-After` honoring, default `MIN_INTERVAL_SECONDS=2.0`, 162 lines of new robustness tests).

This plan covers both tracks. Track A is measurement-first with a refined three-tier gate. Track B is integration-first: rebase the existing remote branch onto current main, then layer on additional optimizations identified during review.

---

## Track A — `lint_wiki` Query-Path Cost (Measurement First)

### Same gated pattern that worked for v0.4.5

Phase 0 (instrumentation) → Phase 1 (measurement) → branching Phase 2 based on a **three-tier gate**. Each tier has its own scope; the decision is data-driven, not aspirational.

### Phase 0 — Instrument the query path

**Code change** (`quant_llm_wiki/query/brainstorm.py:754–789` area):

Wrap `_wiki_is_healthy_for_query(kb_root)` with a perf accumulator gated by `QLW_PERF_DEBUG`:

```python
def _wiki_is_healthy_for_query(kb_root: Path) -> bool:
    _t = time.perf_counter()
    try:
        from quant_llm_wiki.wiki.lint import lint_wiki
        result = lint_wiki(kb_root).ok_for_brainstorm()
    except Exception:
        return False
    finally:
        _emit_perf("query_lint", lint_ms=(time.perf_counter() - _t) * 1000.0)
    return result
```

Also instrument `lint_wiki` itself in `quant_llm_wiki/wiki/lint.py:340` so we can attribute cost between "concept-file scan" and "lint-report.json write" (the side-effect write is a separate optimization opportunity even if the scan is fast).

**Test**: add a unit test to `tests/test_perf_instrumentation.py` that locks the `query_lint` perf-line format end-to-end — pattern after the existing `compile_wiki` / `retrieve_blocks` line-format tests in that file. Without this, the benchmark harness regex can silently break if the emitted field names drift (we hit exactly this risk during v0.4.4 — the harness parses lines by regex, no schema enforcement otherwise). The test should:

- Invoke `_wiki_is_healthy_for_query` with `QLW_PERF_DEBUG=1` and `redirect_stderr`.
- Assert the stderr line matches `^\[qlw-perf\] query_lint: lint_ms=\d+\.\d+$` (or whatever the project's existing line format is).
- Assert the field is parseable as a float.

Also: existing tests must still pass.

**Commit pattern**: matches v0.4.5 Phase 1 style.

### Phase 1 — Measure on realistic wiki scales

Extend `scripts/benchmark_perf.py` to run a NEW measurement mode that does NOT mock `_wiki_is_healthy_for_query`. Two harness changes:

1. Remove the `unittest.mock.patch.object(brainstorm_mod, "_wiki_is_healthy_for_query", return_value=True)` for this measurement (keep the existing mocked-bench as a separate code path).
2. Seed the synthetic KB's `wiki/concepts/` with realistic concept files (status=stable, with `sources`, `related_concepts`, `key_idea_blocks` populated — `lint_wiki` does a thorough scan, an empty stub concept may underestimate cost).

Run at scales:

```
QLW_PERF_DEBUG=1 python3 scripts/benchmark_perf.py --scale small  --trials 5 --label lint-measure --no-mock-lint
QLW_PERF_DEBUG=1 python3 scripts/benchmark_perf.py --scale medium --trials 5 --label lint-measure --no-mock-lint
QLW_PERF_DEBUG=1 python3 scripts/benchmark_perf.py --scale large  --trials 5 --label lint-measure --no-mock-lint
```

5 trials (more than v0.4.5's 3) because we're measuring query latency and want better noise control. Read `query_lint.lint_ms` median per scale.

Also: spot-check on the **user's real wiki** (not just synthetic) at whatever concept count they have today. Production fingerprint can differ from synthetic.

### Phase 2 gate — three-tier decision

Based on the **large-scale median** of `query_lint.lint_ms`:

| Tier | Threshold (large-scale median) | Action |
|---|---|---|
| **A.1 — Negligible** | <50 ms | **No redesign.** Keep the Phase 0 instrumentation in tree (it's zero-cost when `QLW_PERF_DEBUG` is unset) for future re-evaluation. Mark the design-doc Out-of-Scope item as "measured, not worth doing at current wiki scale; revisit when concepts > Nx current". Ship as a `perf-measurement-only` patch (no version bump or as part of next release). |
| **A.2 — Moderate** | 50–200 ms | **Low-risk optimization only.** Implement "read `wiki/lint_report.json` if newer than every input `lint_wiki` consumes, else fall back to running fresh `lint_wiki`". Mtime comparison must cover **all** of `lint_wiki`'s real inputs — not just concepts. Per `quant_llm_wiki/wiki/lint.py:340`+, the function reads `wiki/concepts/*.md` (L361), `wiki/sources/*.md` (L383), and `wiki/state.json` (L351); the cache is only valid if `lint_report.json` is newer than the max mtime across all three. Also: before implementing, re-grep `wiki/lint.py` for any schema/template reads (`quant_llm_wiki/templates/*.md`, etc.) — if lint pulls from package data or other dirs, those must enter the comparison too, or be ruled out as immutable-at-runtime. No staleness model, no degradation strategy — just `Path.stat().st_mtime` comparison over the full input set. Falling back to fresh lint preserves correctness if anyone hand-edits any input and forgets to recompile. |
| **A.3 — Significant** | >200 ms OR clearly linear in concept count across scales | **Full staleness model + degradation strategy.** This is the original spec direction. Design a `LintCacheEntry` with `compile_version` + `wiki_state_hash`, define a staleness threshold (e.g., 24h since last compile = stale), and a fallback policy when stale (default to "trust but warn" or "degrade to lint-disabled brainstorm with a one-line note to user"). Requires a brainstormed design doc before implementation. |

**Linear growth check**: if `lint_ms` at small/medium/large is e.g. 10/40/180 ms, that's near-linear-in-concept-count — pushes A.3 even if large is still <200 ms, because the trajectory says it'll cross 200 ms soon.

### Phase 2 implementations (sketches — flesh out only when the tier is decided)

#### A.1 implementation

- Single commit: `perf(query/brainstorm): instrument lint_wiki on query path` (already done in Phase 0).
- Update `2026-05-17-perf-validation-report.md` with measurement and decision rationale.
- No version bump unless bundled.

#### A.2 implementation

- `quant_llm_wiki/query/brainstorm.py:_wiki_is_healthy_for_query`:
  ```python
  def _wiki_is_healthy_for_query(kb_root: Path) -> bool:
      wiki_dir = kb_root / "wiki"
      lint_report_path = wiki_dir / "lint_report.json"
      try:
          report_mtime = lint_report_path.stat().st_mtime
          input_mtimes = [
              p.stat().st_mtime for p in (wiki_dir / "concepts").glob("*.md")
          ]
          input_mtimes += [
              p.stat().st_mtime for p in (wiki_dir / "sources").glob("*.md")
          ]
          state_json = wiki_dir / "state.json"
          if state_json.exists():
              input_mtimes.append(state_json.stat().st_mtime)
          # Re-check wiki/lint.py before implementing — add any other inputs found
          newest_input_mtime = max(input_mtimes) if input_mtimes else 0.0
      except (FileNotFoundError, ValueError):
          return _fresh_lint_ok(kb_root)
      if report_mtime < newest_input_mtime:
          return _fresh_lint_ok(kb_root)
      # Cached report is newer than every input — trust it
      data = json.loads(lint_report_path.read_text(encoding="utf-8"))
      return bool(data.get("ok_for_brainstorm", False))
  ```
- New test `tests/test_brainstorm.py::WikiHealthCachedReportTests`:
  - `test_uses_cached_report_when_newer_than_all_inputs` — touch report mtime forward, assert no fresh lint_wiki call.
  - `test_falls_back_to_fresh_lint_when_concept_newer` — touch a concept's mtime forward, assert fresh lint runs.
  - `test_falls_back_to_fresh_lint_when_source_newer` — touch a `wiki/sources/*.md` mtime forward, assert fresh lint runs.
  - `test_falls_back_to_fresh_lint_when_state_json_newer` — touch `wiki/state.json` mtime forward, assert fresh lint runs.
  - `test_falls_back_to_fresh_lint_when_report_missing` — delete report, assert fresh lint runs.
- Phase 2 measurement: re-run the Phase 1 bench; expect `lint_ms` to drop to single-digit ms for the cached path.
- Ship as v0.4.6 (patch).

#### A.3 implementation

- Out-of-scope for this plan — requires a fresh brainstorm/design session because the staleness model has multiple plausible shapes:
  - **Time-based**: stale after T hours since last compile.
  - **Version-based**: stale if `wiki/state.json` is newer than `lint_report.json`.
  - **Hash-based**: lint report records the hash of every concept file it covered; if any file's current hash differs, stale.
- Degradation strategy choices:
  - **Trust but warn**: use cached even if stale, surface a one-line note to user.
  - **Degrade to no-lint**: skip the healthy check; let brainstorm proceed without the wiki branch.
  - **Block**: refuse query, instruct user to run `qlw compile`.
- Bundle with v0.5.0 (minor bump) because user-visible behavior changes.

### Out of scope for Track A

- Optimizing `lint_wiki` itself (faster concept parsing, smaller report) — different effort.
- Killing the side-effect write of `lint_report.json` on every query — already addressed by the A.2/A.3 paths (cache reads it instead of overwriting it).
- Async/lazy lint — feasible but the gate decides whether it's needed.

---

## Track B — Zhipu 429 Branch Integration + Extensions

### What's already done on `origin/zhipu-429-rate-limit-hardening`

Single commit `34ae568`, based on `v0.4.3 (ad1ebf7)`. Implements `docs/plan/2026-05-17-zhipu-429-rate-limit-hardening.md` end-to-end:

- `quant_llm_wiki/shared.py`:
  - `DEFAULT_MIN_INTERVAL_SECONDS`: `0.5 → 2.0`.
  - New `_llm_cooldown_until` module-level state + `_set_llm_cooldown(wait)`.
  - `_enforce_min_interval` → `_enforce_llm_rate_gate`: now honors BOTH the per-call minimum interval AND the process-wide cooldown.
  - On 429: compute backoff, honor `Retry-After`, set process-wide cooldown so other workers pause before sending.
  - 500/network errors: per-call retry backoff only, NOT process-wide.
  - `[llm-retry]` stderr enriched with cooldown / Retry-After flags.
- `llm_config.example.env`: updated defaults.
- `README.md`: 11-line docs update (defaults + LLM_CONCURRENCY clarification).
- `tests/robustness/test_layer4_llm_api_robustness.py`: +162 lines covering the new cooldown logic, mocked 429 + Retry-After, concurrent-thread shared-cooldown observation.
- `tests/test_kb_root_resolution.py`: 3-line tweak (likely a setUp resetting the new `_llm_cooldown_until` global).

This is exactly the plan, executed. No design gaps in the existing branch.

### Conflict surface vs current main

Verified by `git log ad1ebf7..9d3b3bc -- quant_llm_wiki/shared.py tests/robustness/test_layer4_llm_api_robustness.py tests/test_kb_root_resolution.py llm_config.example.env README.md` — **empty**. No commits between v0.4.3 and v0.4.5 touched any of these files. Rebase will be conflict-free.

### Step B.1 — Rebase + sanity test + hermetic-test fix

```
git fetch origin
git checkout -b zhipu/429-rebase origin/zhipu-429-rate-limit-hardening
git rebase main
# Expect: clean rebase, no conflicts.

python3 -m unittest discover -s tests -p 'test_*.py' 2>&1 | grep -E "^Ran|^OK|^FAIL"
python3 -m unittest discover -s tests/robustness -p 'test_*.py' 2>&1 | grep -E "^Ran|^OK|^FAIL"
# Expect: all green. v0.4.5 changes are compile-side, zhipu changes are shared.py — orthogonal.
```

If anything fails: stop, diagnose. **Do not** proceed to B.2 until B.1 is clean.

**Required hermetic-test fix (must land in this step, before B.2/B.3 work):** the new robustness tests on the branch use a placeholder URL like `https://fake.url` and mock the HTTP layer, but at least some of the `unittest.mock.patch` targets miss the actual symbol used by `post_llm_json` (e.g., patching `requests.post` when the code calls `requests.Session().post`, or patching at the wrong module path). The symptom is that the test attempts a real DNS resolution / HTTP connect to `fake.url` and either hangs on DNS or only "passes" because the network error happens to fall into the retry path being tested — both are bad (slow + flaky + environment-dependent). Action items, inside B.1:

- Grep `tests/robustness/test_layer4_llm_api_robustness.py` for every `patch(`/`patch.object(` target.
- Cross-check each target against the actual call site in `quant_llm_wiki/shared.py:post_llm_json` and surroundings. The right patch target is **the name as resolved at the call site**, not the original definition module.
- Replace any wrong targets so the HTTP call never escapes the test process. After the fix, the test suite must run successfully **with the network disabled** (sanity-check: `unshare -rn python3 -m unittest tests.robustness.test_layer4_llm_api_robustness` or equivalent, if available on the host; otherwise verify by inspection that no patch target resolves to a real HTTP method).
- Land this as a small, separate commit on the rebased branch before any B.3 additions, so the fix is bisectable and reviewable on its own.

This is non-negotiable: leaving hermeticity broken means every later test run is potentially network-dependent and the B.3 additions will pile noise on top of an already-flaky baseline.

### Step B.2 — Independent review of what's there

Spawn a Codex (or Opus) review of the rebased branch (post-hermetic-test fix) with the framing:

> Branch implements the rate-limit hardening plan and a hermetic-test fix on top. Confirm against the plan that the implementation covers everything; flag any gaps; check for correctness of the threading + cooldown logic (race conditions, monotonic clock usage, double-cooldown). Confirm the hermetic-test fix is complete (all `patch` targets in `tests/robustness/test_layer4_llm_api_robustness.py` resolve to in-process mocks, nothing escapes to real network). Also look for **what the plan did not cover but probably should** — additional optimizations worth layering on before shipping; explicitly note that `_backoff_seconds` already applies full jitter, so jitter is not a gap.

This is the "trust but verify" step before extending the work.

### Step B.3 — Candidate additional optimizations

User explicitly wants "基于这个branch再做一些优化". Below is a candidate list — **pick during planning, do not auto-implement**:

#### B.3.a — Observability for cooldown events (recommended)

The branch logs `[llm-retry]` lines when retries happen, but cooldown events are not aggregated. Add a `QLW_PERF_DEBUG`-gated `_emit_perf("llm_rate_gate", cooldowns_applied=N, total_wait_ms=T)` at the end of each `post_llm_json` call (or batched per worker). Lets production users see how often 429s are firing without grepping stderr.

**Cost**: ~20 LoC, one new test. Low risk.

#### B.3.b — Verify jitter behavior on backoff (verify, not add)

**Update from disk check (2026-05-19):** the rebased branch's `_backoff_seconds` already applies `jitter = random.uniform(0, base)` (full-jitter form, AWS-style), so **do not** plan to "add jitter" — that work is done. What's still owed:

- Confirm the existing tests in `tests/robustness/test_layer4_llm_api_robustness.py` actually exercise jitter range (not just exact values via `random` mock).
- If they don't, add a test that runs `_backoff_seconds(attempt=N)` many times and asserts the distribution is bounded by `[0, base(N)]` and is non-degenerate (min != max across, say, 20 calls with a real `random`).
- Verify multi-worker scenario: with `LLM_CONCURRENCY=3`, three workers entering backoff at the same attempt level should produce three different wait times in practice. Spot-check via a tiny scripted experiment if uncertain; document as "verified, no change" or as a follow-up if a real gap is found.

**Cost**: 0–10 LoC depending on what tests exist. Low risk. Documenting verification matters because the next reviewer should not waste a cycle "adding jitter that's already there".

#### B.3.c — Per-endpoint rate-gate (defer)

Currently a single `_llm_cooldown_until` covers all LLM calls. Zhipu's chat completion and embeddings endpoints may have separate rate buckets. A per-endpoint gate (`_cooldown_by_path: dict[str, float]`) would let one endpoint's 429 not pause the other.

**Cost**: ~40 LoC, threading complexity grows slightly. Medium risk. **Defer until B.3.a observability data shows it's worth doing** — if 429s only hit one endpoint in practice, this is over-engineering.

#### B.3.d — Token-budget tracking (defer / out of scope)

Zhipu and similar providers may rate-limit by **tokens-per-minute**, not requests-per-minute. The current gate is request-rate only. If user hits 429s after only a few large requests, request-rate pacing won't help. Real fix: track output_tokens consumed in a sliding window and gate on that too.

**Cost**: high — needs token-counting on every response, sliding window state, new env vars. **Out of scope for this iteration** unless observability data (B.3.a) shows token-rate hits are the dominant 429 cause.

#### B.3.e — Cross-process cooldown via filesystem (defer / out of scope)

Existing plan explicitly out-of-scoped this. With multiple `qlw` invocations in parallel (e.g., user runs `qlw enrich` in two terminals on the same KB), the cooldown is per-process — they'd still hammer the provider. A `kb_root/.qlw_cooldown` file with a fcntl lock could share state. Out of scope; flag in plan.

#### B.3.f — Robustness of `Retry-After` parsing (verify)

Existing branch parses `Retry-After`. Verify it handles:
- Plain seconds: `Retry-After: 7` ✓ (probably)
- HTTP-date: `Retry-After: Wed, 21 Oct 2026 07:28:00 GMT` (rare but in the RFC)
- Edge values: 0, negative, very large (>1h)

If it doesn't handle HTTP-date, add a `try: int(value) except: parsedate_to_datetime(value)` fallback. Defensive.

**Cost**: ~10 LoC + tests. Low risk.

### Step B.4 — Decide scope, ship

After B.2 + B.3 review:

- **Minimum ship**: just the rebased branch as-is. Release as v0.4.6.
- **Recommended ship**: rebased branch + B.3.a (observability) + B.3.b (jitter) + B.3.f (Retry-After robustness). Three small additions, all low-risk, all add real value. Release as v0.4.6 or v0.5.0 depending on whether B.3.a's perf field counts as a public API change (it's stderr-only, so v0.4.6 is fine).
- **Ambitious ship**: include B.3.c (per-endpoint gate) — only if B.3.a's observability data demonstrates need. Requires a measurement gate just like Track A.

### Test plan for the integrated branch

```
# Existing tests on rebased branch
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 -m unittest discover -s tests/robustness -p 'test_*.py' -v

# New tests for whatever B.3 items land
# Sketch only — fleshed out at implementation time:
# - test_perf_instrumentation::test_llm_rate_gate_emits_cooldown_count
# - test_layer4_llm_api_robustness::test_backoff_has_jitter_within_range
# - test_layer4_llm_api_robustness::test_retry_after_accepts_http_date

# Smoke test: actual qlw enrich on a small batch with a mocked 429 injected
# at request N to verify the cooldown logic fires end-to-end.
```

### Risks for Track B

| Risk | Level | Mitigation |
|---|---|---|
| Rebase reveals hidden conflicts | Low | Verified empty conflict surface above; if it fails, halt. |
| New cooldown global breaks parallel tests | Low | Branch already adds `setUp` resets in `tests/robustness/`; verify no other test files set up state independently. |
| Jitter (B.3.b) breaks deterministic tests | Low | Tests assert ranges, not exact values; mock `random` if needed. |
| Token-budget pressure not solved by request-rate fix | Medium | Observability (B.3.a) will surface this; document as known limitation and defer to B.3.d. |

---

## Order of execution

1. **Track A first**: Phase 0 → Phase 1 measurement → tier decision → tier-specific Phase 2 → ship.
2. **Then Track B**: B.1 rebase → B.2 independent review → B.3 pick + implement chosen additions → B.4 ship.

Both tracks can ship as patch releases (v0.4.6, v0.4.7) or be bundled into a minor (v0.5.0) — call to make at ship time.

## Cross-cutting

- Both tracks reuse the gated-phase + subagent-driven workflow that worked for v0.4.5 (Phase 0 invariant lock → Phase 1 measurement gate → Phase 2 implementation only if gate passes → independent post-review).
- For Track A specifically: **do not commit to A.3's design until A.1/A.2 thresholds are confirmed insufficient**. The lazy hoist was a 96.8% measurement; we proceeded because the data said so. Same discipline here.
- Both tracks should respect `feedback_verify_sonnet_commits_against_pure_head` — stash + re-test after every implementer commit, regardless of how confident the report sounds.

## Followups not addressed by this plan

- v0.4.2 tag-push status verification (housekeeping; not blocking).
- Production-mode (non-mock) perf benchmark of v0.4.5 hoist on a real wiki — useful but separable.
- LLM-driven `run_maintenance()` (v0.5.0+ item, listed in `project_qlw_cli_unification_pending`).
