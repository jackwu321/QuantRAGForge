# Benchmark records

Raw `.json` runs land here and are gitignored — they're per-machine, per-checkout, noisy. The durable artifact lives in `docs/superpowers/specs/2026-05-17-perf-validation-report.md`.

## Running

    QLW_PERF_DEBUG=1 python3 scripts/benchmark_perf.py --scale medium --trials 3

## Scales

| name   | articles | concepts | feeds/article |
|--------|----------|----------|---------------|
| small  | 20       | 10       | 3             |
| medium | 100      | 40       | 4             |
| large  | 500      | 100      | 5             |

## What's measured

- `compile_wiki` end-to-end wall time + assign/recompile phase split (from `[qlw-perf] compile_wiki:` line).
- `retrieve_blocks` wiki-branch wall time + `_retrieve_concept_articles` call count and time (from `[qlw-perf]` lines).

## What's mocked

LLM calls (`assign_concepts`, `recompile_concept`) and concept retrieval (`_retrieve_concept_articles`) are mocked to deterministic near-zero-cost stubs. The benchmark measures the in-process structural work that changed in v0.4.3, not the LLM/embedding cost that dominates a real run.
