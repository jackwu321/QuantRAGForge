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

- `_build_index_text` hoist — would reduce `assign_ms` at large scale by rebuilding the index text once per compile rather than once per article; the design doc flagged a semantic risk (later articles can't see concepts proposed by earlier articles in the same run). Worth measuring once a decision is made.
- Query-time `lint_wiki` cost — not exercised in this harness because `_wiki_is_healthy_for_query` is mocked to `True`. A separate measurement using real lint reads at varied wiki sizes is needed before the design change.

## How to reproduce

    QLW_PERF_DEBUG=1 python3 scripts/benchmark_perf.py --scale medium --trials 3 --label myrun

Raw JSON lands in `benchmarks/` (gitignored). See `benchmarks/README.md`.
