# Changelog

All notable changes to this project will be documented in this file.

## [0.4.5] - 2026-05-18

### Performance

- **`_build_index_text` hoist** (`compile_wiki`): moved the single `_build_index_text` call out of the per-article assign loop so it runs once per compile rather than once per article. Structurally O(A) → O(1) in stable-concept-file reads. The mocked-LLM harness shows `assign_ms` dropping from ~22,000 ms to ~884 ms at large scale (96% in-harness reduction, ≈25 s of redundant filesystem scans eliminated per compile); production proportional saving will be smaller because real `assign_concepts` LLM time dominates the per-iteration budget, but the absolute per-compile saving is the same. The precondition that makes the hoist safe — that index-text output is stable across the assign loop — is locked by the Phase 0 invariant test (`BuildIndexTextInvariantTests`).
- **`build_index_text_ms` instrumentation**: `compile_wiki` now emits `build_index_text_ms` in its `[qlw-perf]` output, giving independent visibility into the cost of the single (post-hoist) index-text build separate from the rest of `assign_ms`.

### Documentation

- **v0.4.5 perf measurement addendum** (`docs/superpowers/specs/2026-05-17-perf-validation-report.md`): three-scale benchmark of the Phase 2 hoist across small/medium/large, comparing v0.4.4 baseline to v0.4.5-HEAD. Updated "Out of scope" to mark `_build_index_text` hoist as done; only `lint_wiki` staleness remains as a follow-up.

## [0.4.4] - 2026-05-18

### Added

- **Performance instrumentation** (`quant_llm_wiki/shared_perf.py`): env-gated `_emit_perf` helper emits `[qlw-perf]` lines to stderr when `QLW_PERF_DEBUG=1`; zero-cost when unset.
- **Timed `_retrieve_concept_articles`**: emits mode tag (`chroma`, `lexical`, or `empty`) and result count alongside elapsed ms, enabling production retrieval-path diagnosis.
- **Timed `retrieve_blocks`** wiki branch: emits `wiki_blocks`, `excluded_articles`, and `total_ms` per invocation.
- **Timed `compile_wiki`** phase split: emits `assign_ms` and `recompile_ms` separately, plus `reverse_index_size` and `affected_concepts`, so assignment-loop cost and recompile-loop cost can be tracked independently.
- **Benchmark harness** (`scripts/benchmark_perf.py`): synthetic KB builder + mocked-LLM trial runner that measures the two v0.4.3 structural wins (brainstorm dedup, reverse-index recompile) without API keys; JSON output lands in `benchmarks/` (gitignored).
- **Reverse-index contract test** (`tests/test_wiki_compile_reverse_index.py`): regression test locking the skip-branch + changed-branch multi-source contract so both unchanged and changed articles always feed recompile for the same concept.
- **Perf instrumentation tests** (`tests/test_perf_instrumentation.py`): 9 tests covering all three instrumented paths, chroma/empty/lexical modes, `_parse_event` edge cases, and zero-cost guard.
- **v0.4.3 perf validation report** (`docs/superpowers/specs/2026-05-17-perf-validation-report.md`): measured brainstorm dedup (2→1 `_retrieve_concept_articles` calls, ~20–32% query-time improvement) and reverse-index recompile win (6% at large scale, 397.7→373.7 ms).

### Changed

- `retrieve_blocks` no longer logs a hardcoded `concept_retrievals=1`; the call-count invariant is locked by the spy test in `tests/test_brainstorm_with_wiki.py` instead of a static log field.
- `benchmark_perf.py` auto-sets `QLW_PERF_DEBUG=1` when called via `main()` so the harness produces valid JSON without requiring the env var to be set manually.
