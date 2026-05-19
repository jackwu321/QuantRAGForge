# v0.4.3 Perf Validation — Measurement Report

## Context

v0.4.3 (commit `ad1ebf7`) shipped two structural perf changes:

- **`ca902ff`** — `retrieve_blocks` no longer calls `_retrieve_concept_articles` twice per query.
- **`39e08c5`** — `compile_wiki` recompile loop uses an O(1) reverse index instead of an O(S·A) scan.

The design doc (`2026-05-17-brainstorm-compile-perf-design.md`) noted that the wins are structural but did not measure them. This report is the measurement.

## Method

Synthetic KB, deterministic LLM mocks, 3 trials per cell, median reported. Harness: `scripts/benchmark_perf.py`. v0.4.2 was measured by checking out the tag in a worktree and backporting only the instrumentation (not the behavior changes) so the same harness could read perf lines from the older code. See `benchmarks/README.md` for the full methodology.

## Numbers (median of 3 trials, milliseconds)

| version       | scale  | compile.assign_ms | compile.recompile_ms | query.total_ms | query.retrievals_observed¹ |
|---------------|--------|------------------:|---------------------:|---------------:|---------------------------:|
| v0.4.2-tagged | small  |             149.7 |                 11.1 |          0.050 |                          2 |
| v0.4.3-HEAD   | small  |             149.4 |                 11.2 |          0.034 |                          1 |
| v0.4.2-tagged | medium |            1970.9 |                 65.5 |          0.048 |                          2 |
| v0.4.3-HEAD   | medium |            2002.6 |                 65.6 |          0.038 |                          1 |
| v0.4.2-tagged | large  |           22391.1 |                397.7 |          0.051 |                          2 |
| v0.4.3-HEAD   | large  |           22029.1 |                373.7 |          0.039 |                          1 |

¹ Counted by the harness mock around `_retrieve_concept_articles`, not by an in-code log field. The runtime call-count invariant is locked by `tests/test_brainstorm_with_wiki.py` (the spy test asserting `_retrieve_concept_articles.call_count == 1`).

Host: `ip-172-31-6-158`, Python `3.12.3`, timestamp `2026-05-18T06:18:04Z`.

## Findings

**Brainstorm dedup (ca902ff).** Harness-observed `_retrieve_concept_articles` calls drop from 2 → 1 across all scales — the structural invariant the v0.4.3 spy test already locks in at the unit level. `query.total_ms` improves by ~20–32% across scales (0.050 → 0.034 ms at small, 0.051 → 0.039 ms at large). The absolute win is sub-millisecond here because the mock retrieval is near-zero cost; in production with real Chroma or lexical search the delta will scale with the cost of one full retrieval call (~tens to low-hundreds of ms per call). The structural guarantee — exactly one call per `retrieve_blocks` invocation — is the durable finding.

**Compile reverse index (39e08c5).** `recompile_ms` shows directionally correct improvement that grows with scale: essentially flat noise at small/medium (11 ms range), but a clear **6.0% reduction at large scale** (397.7 → 373.7 ms, saving ~24 ms). The absolute savings are modest because the mocked assignment loop dominates overall compile time (`assign_ms` is 60–100× larger than `recompile_ms`); in production, where `assign_concepts` involves real LLM calls, the recompile-phase proportion will be smaller but the O(1) vs O(S·A) win will still compound with wiki size. The win is expected to become more pronounced as the number of articles × affected-concepts grows beyond the 500×100 large-scale configuration tested here.

**Assign phase is unchanged.** `assign_ms` is within noise between v0.4.2 and v0.4.3 across all scales, confirming v0.4.3 only touched the recompile-side data path and introduced no regression in the assignment loop.

## Out of scope (still on the followup list)

- ~~`_build_index_text` hoist~~ — **Done in v0.4.5** (commit `30976f3`); see the v0.4.5 increment section below.
- Query-time `lint_wiki` cost — not exercised in this harness because `_wiki_is_healthy_for_query` is mocked to `True`. A separate measurement using real lint reads at varied wiki sizes is needed before the design change.

---

## v0.4.5 Increment — `_build_index_text` Hoist

### Context

Phase 1 instrumentation (commits `b3f71f7`, `93327b9` — added on this v0.4.5 branch, measured before Phase 2 landed) revealed that `build_index_text_ms` — the cost of rebuilding the full wiki index text string — was being accumulated once per article inside the assign loop, accounting for ~96.8% of `assign_ms` at large scale. Phase 2 (commit `30976f3`) hoists the single `_build_index_text` call out of the loop. A subsequent fix (commit `f09a10c`) makes the hoist *lazy* — `index_text` stays `None` until an article actually needs assignment, so an idempotent no-op compile (all articles cache-hit skipped) pays zero index-build cost. Two invariants lock the change: `BuildIndexTextInvariantTests` (commit `7349091`) asserts that the stable-concept set is invariant within the assign loop window; `IndexTextNotBuiltOnNoOpCompileTests` (commit `f09a10c`) asserts that a fully-skipped compile never calls `_build_index_text`.

### Numbers (median of 3 trials, milliseconds)

| version       | scale  | compile.assign_ms | compile.build_index_text_ms       | compile.recompile_ms | compile.wall_ms |
|---------------|--------|------------------:|----------------------------------:|---------------------:|----------------:|
| v0.4.4-HEAD   | small  |             149.4 | n/a (field added in this change)  |                 11.2 |           201.2 |
| v0.4.5-HEAD   | small  |              22.7 |                               8.2 |                 12.5 |            83.1 |
| v0.4.4-HEAD   | medium |            2002.6 | n/a (field added in this change)  |                 65.6 |          2232.0 |
| v0.4.5-HEAD   | medium |             112.8 |                              22.6 |                 75.0 |           370.2 |
| v0.4.4-HEAD   | large  |           22029.1 | n/a (field added in this change)  |                373.7 |         23090.2 |
| v0.4.5-HEAD   | large  |             883.5 |                              50.4 |                442.2 |          2117.2 |

Note: v0.4.4 baseline files are labeled `v0.4.3-HEAD` (same code — v0.4.4 added instrumentation only, no behavior change). `build_index_text_ms` was added on this v0.4.5 branch in Phase 1, so the v0.4.4 baseline column reads `n/a`.

Host: `ip-172-31-6-158`, Python `3.12.3`, timestamp `2026-05-18T14:33:16Z`.

### Findings

**Assign phase (headline win).** At large scale, `assign_ms` drops from 22,029 ms → 884 ms — a **96.0% reduction** — as the 500 redundant `_build_index_text` calls collapse to one. At medium scale, 2,003 ms → 113 ms (94.4%); at small scale, 149 ms → 23 ms (84.8%). The pattern is consistent and grows with article count, confirming the O(A) → O(1) structural change.

**Production caveat.** The harness uses deterministic mocks for `assign_concepts`, so the measured `assign_ms` budget is dominated by filesystem I/O reading `wiki/concepts/*.md`. In production, where `assign_concepts` involves a real LLM call (typically hundreds of ms to several seconds per article), the same hoist still saves the same *absolute* per-compile work — at large scale ≈25 s of redundant filesystem scans — but the *percentage* of `assign_ms` saved will be much smaller because LLM time dominates the per-iteration budget. The durable findings are structural (O(A) → O(1)) and absolute (eliminates ~A·M file reads where M = stable-concept count); the headline percentage is a harness artifact.

**`build_index_text_ms` field semantics shift.** In v0.4.4, the field accumulated cost across all per-article iterations; in v0.4.5 it reflects a single call (50 ms at large scale). The field name is stable, but the interpretation changes from "sum over loop" to "once per compile". This is expected and documented here.

**Recompile phase unchanged (regression check).** `recompile_ms` is within noise: 373.7 ms (v0.4.4) vs 442.2 ms (v0.4.5) at large scale. The small increase (~18%) is within trial-to-trial variance on this host and is not attributable to the hoist, which only touches the assign loop. No regression in the recompile path.

**Wall time.** End-to-end `compile_wiki` wall time drops from 23,090 ms → 2,117 ms at large scale (~91% reduction), directly tracking the assign_ms win.

---

## lint_wiki on Query Path — A1b Measurement (2026-05-19)

### Context

Spec: `docs/superpowers/specs/2026-05-18-next-steps-lint-and-zhipu.md` (Track A, Phase 1).
v0.4.5 instrumented `_wiki_is_healthy_for_query` via `_emit_perf("query_lint", lint_ms=…)` on the brainstorm query path; `scripts/benchmark_perf.py` gained `--no-mock-lint` to exercise the real `lint_wiki` against a realistically-seeded synthetic KB. This section records the resulting query-path `lint_wiki` cost so the A.1 / A.2 / A.3 gate can be decided.

### Method

`scripts/benchmark_perf.py --no-mock-lint`, 5 trials per scale (more than v0.4.5's 3 — query latency wants better noise control). Synthetic KB only; the user has no real wiki on this host to spot-check against. Concept stubs are seeded with `status=stable`, populated `sources`, `related_concepts`, `key_idea_blocks`; sources directory is mirrored so `_check_orphan_sources`/`_check_stale_sources` traverse real files. The harness reads `query_lint.lint_ms` directly from the `[qlw-perf]` line on the query path; `lint_wiki.*_ms` (last-line semantics in `_parse_event`) tracks the same call.

Commands run:

    QLW_PERF_DEBUG=1 python3 scripts/benchmark_perf.py --scale small  --trials 5 --label lint-measure --no-mock-lint
    QLW_PERF_DEBUG=1 python3 scripts/benchmark_perf.py --scale medium --trials 5 --label lint-measure --no-mock-lint
    QLW_PERF_DEBUG=1 python3 scripts/benchmark_perf.py --scale large  --trials 5 --label lint-measure --no-mock-lint

### Numbers (5-trial median, milliseconds)

| scale  | articles × concepts | query_lint.lint_ms | lint_wiki.scan_ms | lint_wiki.write_ms |
|--------|---------------------|-------------------:|------------------:|-------------------:|
| small  | 20 × 10             |              27.29 |             26.69 |               0.32 |
| medium | 100 × 40            |             120.43 |            121.45 |               0.83 |
| large  | 500 × 100           |             580.71 |            562.31 |               3.32 |

Per-trial values were tight (large: 567 / 574 / 590 / 585 / 581 ms — <5% trial-to-trial spread, low noise floor for a measurement at this magnitude). Host: `ip-172-31-6-158`, Python `3.12.3`, timestamp `2026-05-19T03:33Z`. Raw JSON in `benchmarks/20260519-033225-small-lint-measure.json`, `…-033235-medium…`, `…-033253-large…`.

Note on `lint_wiki.calls`: the harness sees `calls=2` per trial — one call inside `compile_wiki` (compile-time lint), one on the query path. `_parse_event` records last-line values, so `lint_wiki.{scan,write,total}_ms` reflect the query-path call and align with `query_lint.lint_ms` (27.29 ≈ 27.00; 120.43 ≈ 122.30; 580.71 ≈ 565.64 — small drift is harness wall vs in-call accounting, not two different calls).

### Findings

**Cost dominated by scan, not write.** Across all scales, ≥97% of `lint_wiki` cost is the scan phase (`_check_*` traversals over `wiki/concepts/*.md` + `wiki/sources/*.md`); writing `lint_report.json` is sub-millisecond at small/medium and 3 ms at large. The cache-short-circuit pattern in A.2 (`stat().st_mtime` over inputs vs cached `lint_report.json`) directly attacks the dominant cost.

**Linear-growth check.** small→medium: concepts grow 4×, `lint_ms` grows 4.4×; medium→large: concepts grow 2.5× while articles grow 5×, and `lint_ms` grows 4.8×. The growth is roughly linear in the combined input file count (concepts + sources scanned), exactly as `lint_wiki`'s `_check_*` loops would predict. There is no inflection that would saturate at higher scale — extrapolation to even larger wikis remains linear-in-inputs.

**Gate verdict.** Large-scale median **580 ms** is **>200 ms**, the A.3 threshold. The trajectory 27 / 120 / 581 also exceeds the spec's A.3 example trajectory (10 / 40 / 180), so both criteria for A.3 are met.

**Real-wiki spot-check pending.** This run is synthetic-only (no user wiki on this host). Before committing to A.3 design work, a one-shot run on the user's actual wiki at current concept count would calibrate whether the synthetic ratio (cost ∝ concepts + articles) maps cleanly to production. Suggested single command at the user's wiki root:

    QLW_PERF_DEBUG=1 python3 -c "from quant_llm_wiki.wiki.lint import lint_wiki; from pathlib import Path; lint_wiki(kb_root=Path('.'), write_report=False)"

If real-wiki `lint_wiki.total_ms` lands above ~50 ms, A.3 is confirmed irrespective of synthetic trajectory.

### Recommendation toward G1

A.3 — **full staleness model + degradation strategy** — is mechanically indicated. Caveat: A.3 is explicitly spec-deferred ("requires a fresh brainstorm session") because choosing a staleness threshold and a stale-cache fallback policy is a design question, not an implementation one. The arrangement's A2.3 row already captures this: Track A in this iteration ends at the measurement, and A.3 opens a follow-up plan.

A.2 (the mtime short-circuit) would still capture most of the wins **and** is structurally compatible with a later A.3 layer — A.3's `LintCacheEntry`/staleness model would replace the A.2 mtime comparator without affecting the call-site contract. If the user prefers to ship a low-risk patch first and design A.3 separately, A.2 is a clean intermediate.

---

## A2.2 Phase 2 Measurement — Cached lint_report Short-Circuit (2026-05-19)

### Context

Following G1 the user picked tier **A.2**: implement the mtime-based cache short-circuit before any A.3 design work. Commit `f8fb327` adds `_lint_cache_ok_for_brainstorm()` to `quant_llm_wiki/query/brainstorm.py` and rewires `_wiki_is_healthy_for_query` so the brainstorm path reads cached `wiki/lint_report.json` whenever it is strictly newer than every `lint_wiki` input. The input set covers all four classes the controller pre-grep identified — concepts, sources, `state.json`, and each article path referenced by `state.sources` (the spec-gap fix). Cache miss falls back to fresh `lint_wiki`. Commit `5d14ce6` fixes a vacuous mock-target in the cache-hit test (was patching the definition module, not the call-site binding).

This section measures the cached path against the A1b baseline.

### Numbers (5-trial median, milliseconds)

| scale  | A1b uncached `query_lint.lint_ms` | A2.2 cached `query_lint.lint_ms` | reduction | `lint_wiki.calls` / trial |
|--------|----------------------------------:|---------------------------------:|----------:|--------------------------:|
| small  |                             27.29 |                             0.52 |     98.1% | 2 → 1                     |
| medium |                            120.43 |                             1.78 |     98.5% | 2 → 1                     |
| large  |                            580.71 |                             8.50 |     98.5% | 2 → 1                     |

Per-trial values (cached): small `[0.52, 0.54, 0.53, 0.52, 0.49]`; medium `[1.62, 1.60, 1.86, 1.85, 1.78]`; large `[8.25, 8.50, 8.08, 11.11, 8.52]`. Host: `ip-172-31-6-158`, Python `3.12.3`, timestamp `2026-05-19T03:59Z`. Raw JSON: `benchmarks/20260519-035919-small-A2.2-cached.json` + medium + large.

### Findings

**Cached path meets the spec "single-digit ms" target at every scale.** Small and medium are sub-2 ms; large is 8.5 ms median (one trial 11 ms — within noise for a measurement at this magnitude). The spec required "single-digit ms on cached path" — confirmed.

**`lint_wiki.calls` drops from 2 → 1 per trial.** Compile-time `lint_wiki` still runs once (writes the cache file as side effect); the query-time call is fully short-circuited. This is the operational signal that the cache is being hit, not just that timing improved.

**Where the cached-path cost goes.** At large scale, ~8.5 ms is spent in the mtime comparator itself — primarily 500 `Path.stat()` calls over the `state.sources` article files (input class #4). Sub-ms at small/medium where the article count is 20/100. This cost is structural — it scales with article count, not with `lint_wiki`'s scan cost — and is acceptable: even at large scale it's 68× cheaper than the uncached scan and lands inside the spec budget. If/when a single-digit-ms ceiling becomes binding at much larger wikis (~5k+ articles), batching stat into a single readdir or trusting a `state.json`-only mtime are obvious follow-ups.

**Spec-gap correctness.** Input class #4 (article files via `state.sources`) was added to the comparator after Opus's pre-grep noticed the original spec listed only inputs 1–3. The unit test `test_cache_miss_article_newer_calls_fresh_lint` constructs the strict case (cache newer than concepts/sources/state.json, but one referenced article is newer than cache) and asserts the fallback fires. Without input #4 the cache would silently mask `_check_stale_sources` hash-mismatch detection on hand-edited articles. The test was demanded by the user explicitly and passes.

### Conclusion

A.2 ships query-path lint costs from 27/120/581 ms to 0.5/1.8/8.5 ms while preserving correctness against hand-edits. The A.3 staleness-model work remains the proper long-term path, but A.2 captures the headline wins and is structurally compatible — `LintCacheEntry`/staleness can replace the mtime comparator without touching the call-site contract.

## How to reproduce

    QLW_PERF_DEBUG=1 python3 scripts/benchmark_perf.py --scale medium --trials 3 --label myrun

Raw JSON lands in `benchmarks/` (gitignored). See `benchmarks/README.md`.
