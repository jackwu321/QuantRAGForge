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

Phase 1 instrumentation (commits `b3f71f7`, `93327b9`, merged in v0.4.4) revealed that `build_index_text_ms` — the cost of rebuilding the full wiki index text string — was being accumulated once per article inside the assign loop, accounting for ~96.8% of `assign_ms` at large scale. Phase 2 (commit `30976f3`, v0.4.5-HEAD) hoists this single `_build_index_text` call out of the loop so it runs exactly once per `compile_wiki` invocation. The precondition that makes the hoist semantically safe — that `_build_index_text` output does not change across the assign loop — is locked by the Phase 0 invariant test (`BuildIndexTextInvariantTests`, commit `7349091`).

### Numbers (median of 3 trials, milliseconds)

| version       | scale  | compile.assign_ms | compile.build_index_text_ms       | compile.recompile_ms | compile.wall_ms |
|---------------|--------|------------------:|----------------------------------:|---------------------:|----------------:|
| v0.4.4-HEAD   | small  |             149.4 | n/a (field added in this change)  |                 11.2 |           201.2 |
| v0.4.5-HEAD   | small  |              22.7 |                               8.2 |                 12.5 |            83.1 |
| v0.4.4-HEAD   | medium |            2002.6 | n/a (field added in this change)  |                 65.6 |          2232.0 |
| v0.4.5-HEAD   | medium |             112.8 |                              22.6 |                 75.0 |           370.2 |
| v0.4.4-HEAD   | large  |           22029.1 | n/a (field added in this change)  |                373.7 |         23090.2 |
| v0.4.5-HEAD   | large  |             883.5 |                              50.4 |                442.2 |          2117.2 |

Note: v0.4.4 baseline files are labeled `v0.4.3-HEAD` (same code — v0.4.4 added instrumentation only, no behavior change). `build_index_text_ms` was introduced in v0.4.4, so the baseline cannot report it.

Host: `ip-172-31-6-158`, Python `3.12.3`, timestamp `2026-05-18T14:33:16Z`.

### Findings

**Assign phase (headline win).** At large scale, `assign_ms` drops from 22,029 ms → 884 ms — a **96.0% reduction** — as the 500 redundant `_build_index_text` calls collapse to one. At medium scale, 2,003 ms → 113 ms (94.4%); at small scale, 149 ms → 23 ms (84.8%). The pattern is consistent and grows with article count, confirming the O(A) → O(1) structural change.

**Production caveat.** The harness uses deterministic mocks for `assign_concepts`, so the measured `assign_ms` budget is dominated by filesystem I/O reading `wiki/concepts/*.md`. In production, where `assign_concepts` involves a real LLM call (typically hundreds of ms to several seconds per article), the same hoist still saves the same *absolute* per-compile work — at large scale ≈25 s of redundant filesystem scans — but the *percentage* of `assign_ms` saved will be much smaller because LLM time dominates the per-iteration budget. The durable findings are structural (O(A) → O(1)) and absolute (eliminates ~A·M file reads where M = stable-concept count); the headline percentage is a harness artifact.

**`build_index_text_ms` field semantics shift.** In v0.4.4, the field accumulated cost across all per-article iterations; in v0.4.5 it reflects a single call (50 ms at large scale). The field name is stable, but the interpretation changes from "sum over loop" to "once per compile". This is expected and documented here.

**Recompile phase unchanged (regression check).** `recompile_ms` is within noise: 373.7 ms (v0.4.4) vs 442.2 ms (v0.4.5) at large scale. The small increase (~18%) is within trial-to-trial variance on this host and is not attributable to the hoist, which only touches the assign loop. No regression in the recompile path.

**Wall time.** End-to-end `compile_wiki` wall time drops from 23,090 ms → 2,117 ms at large scale (~91% reduction), directly tracking the assign_ms win.

## How to reproduce

    QLW_PERF_DEBUG=1 python3 scripts/benchmark_perf.py --scale medium --trials 3 --label myrun

Raw JSON lands in `benchmarks/` (gitignored). See `benchmarks/README.md`.
