# Changelog

All notable changes to this project will be documented in this file.

## [0.7.0] - 2026-06-11

Multi-turn fuzzy strategy conversations: tell the agent a vague strategy direction and it clarifies, maps wiki coverage, proposes candidate ideas, refines over multiple turns, and converges into a strategy brief on disk. Process state lives in workflow memory; nothing conversation-born enters the wiki.

### Added

- **`strategy-brainstorm` package skill**: entry-routed 5-stage SOP (clarify → orient → propose → refine → converge). Stages are a state library, not a pipeline — the agent enters at the latest viable stage; memory state (decisions / notes / prior briefs) counts as completed prior stages. Clarification budget ≤1 round / ≤2 questions; direction notes are written only once a direction takes shape.
- **`save_strategy_brief` agent tool** (`ALL_TOOLS` 14 → 15): persists the converged brief to `outputs/brainstorms/<date>_<slug>_brief.md`; fires only on the user's explicit convergence instruction.
- **`set_note_status` agent tool** (7th memory tool): fold/park/reject research notes from conversation when the user settles their fate; CLI `qlw memory note-status` remains available.
- **`rejected` note status**: directions the user explicitly declined are excluded from open notes and recorded with the rejection decision.

### Changed

- System prompt: two tool lines, `save_strategy_brief` added to the write-authorization rule, memory rule 3 extended with the fold/reject-on-convergence flow.
- `save_strategy_brief` and `set_note_status` count as significant write actions for the workflow.md session-log gate.
- `append_query_log` gains `update_state` (default `True`): brief saves log the query but never mutate `state.json` — conversation-authored Retrieved Sources are not pipeline-trusted, so they get no importance bump or retrieval hints.
- Skill triggering hardened for fuzzy strategy openers (found in GLM-4.7 live smoke: the agent answered with `query_knowledge_base` directly and never consulted the skill registry): the `query_knowledge_base` tool docstring now routes fuzzy/directional strategy conversations to the strategy-brainstorm skill first, and system prompt skill rule 1 lists 模糊策略方向的多轮脑暴 among the known skill-shaped patterns.

### Fixed (pre-release adversarial review, Claude + Codex)

- Brief query logs no longer record `cited_concepts` at all: `run_maintenance(apply=True)` aggregates citations from every query log into `state.json` retrieval hints, which would have laundered the untrusted brief citations one maintenance run later.
- Re-converging on the same topic the same day no longer clobbers the earlier brief or its query log — filenames get `-2`/`-3` suffixes on collision.
- `set_note_status` (agent tool) is now thread-scoped: a hallucinated note id can no longer fold/reject another thread's notes. CLI `qlw memory note-status` keeps bare-id semantics (explicit user action).
- Control characters in a brief topic are sanitized (NUL previously crashed the tool; newlines could inject extra markdown into the brief header).
- Brief query-log write failures now warn on stderr instead of passing silently.
- `_latest_output_for(mode="brief")` no longer falls back to the latest brainstorm output (latent footgun for future callers omitting `output_path`).

### Known limitations

- `qlw agent --no-memory` still routes fuzzy strategy openers to the strategy-brainstorm SOP, whose steps reference memory tools that are not registered in stateless mode (tracked in TODOS.md, P2).

## [0.6.0] - 2026-06-10

Agent workflow memory: the agent now resumes prior context across sessions. Memory is workflow state (handoff, tasks, decisions, research notes, procedure drafts) and stays strictly separated from the wiki KB.

### Added

- **Two-substrate memory layer** (`agent/memory/`, stored under `<kb_root>/.qlw/memory/`): `workflow.md` — human-editable narrative (Current Handoff / Next Steps / Blockers / Recent Sessions; hand-edits always win, sha-guarded) — and `memory.sqlite` — tool-managed sessions / tasks / decisions / notes / events / threads with FTS5 search and automatic LIKE fallback.
- **Six memory agent tools** (registered only when memory is enabled; 14 → 20): `record_decision`, `add_task`, `complete_task`, `list_open_tasks`, `record_note`, `propose_procedure`.
- **Research-process notes**: `record_note(kind: hypothesis/direction/observation)` holds unstable research state — fuzzy strategy directions, hypotheses, observations — scoped per thread. This state never goes into the wiki (wiki is stable knowledge only). Multi-session strategy conversations = `--thread <name>` resume + notes + brainstorm.
- **Procedure draft pool → skill promotion**: `propose_procedure` saves conversational "以后按这个流程做" flows as inert drafts; `qlw memory promote-procedure <id>` generates a real `.qlw/skills/<name>.md` (validated through the skill registry loader). The skill registry remains the only runtime SOP system — there is no second "active procedures" tier.
- **Session-start preamble**: handoff/next-steps/blockers verbatim, recent sessions, open tasks, recent decisions, and open notes for the active thread (token-budgeted, `MEMORY_PREAMBLE_TOKEN_BUDGET`).
- **`qlw agent` flags**: `--thread <name>`, `--new`, `--summary` (opt-in LLM session summarizer), `--no-memory` (fully stateless, byte-identical memory dir).
- **`qlw memory` subcommand**: status / show / tasks / decisions / notes / note-status / recall / audit / clear-current / drafts / promote-procedure / reject-draft.

### Changed

- **System prompt**: adds a compact Memory rules section (same style as the skill rules — role, tool groups, skill rules, memory rules; no SOPs in the prompt). Interaction principles: skills never auto-write memory; PAUSE progress may be recorded deliberately for cross-session continuity; `propose_procedure` is the sole conversational entrance to the draft pool; notes are research state, never wiki content.

### Notes

- **workflow.md anti-churn gate**: only *significant* sessions (any write-action tool ran, or `--summary`) append to Recent Sessions, which is capped at 10 entries (`MEMORY_RECENT_SESSIONS_KEEP`; full history stays in SQLite). Read-only Q&A leaves workflow.md byte-identical — frequent `qlw agent --query` runs cannot turn it into a click log.
- Memory never touches `wiki/`, `vector_store/`, `raw/`, `schema/` — pinned by a sha256 regression test.
- A corrupt `memory.sqlite` disables memory for the run with a warning instead of breaking the agent.

## [0.5.0] - 2026-06-10

Agent skills refactor: known multi-step workflows move out of the system prompt into a filesystem skill registry.

### Added

- **Built-in skill registry with KB-level overrides** (`agent/skill_registry.py`): skills are SOP markdown files with YAML frontmatter (`name` / `description` / `triggers` / `requires_user_decision` / `tools_used`). Package built-ins ship in the wheel and load via `importlib.resources`; `<kb_root>/.qlw/skills/*.md` extends or overrides them by name. Invalid files are reported in `_errors` without blocking valid skills.
- **Two new agent tools** — `list_skills` and `read_skill` (ALL_TOOLS 12 → 14). `read_skill` resolves names against the registry keyset only; traversal-style names (`../x`, absolute paths, `foo.md`) return structured `skill_not_found`.
- **Four core skills**: `full-ingest`, `concept-review`, `wiki-explanation`, `kb-health-check`. Skills with `requires_user_decision: true` carry explicit `[PAUSE]` review points where the agent must stop and hand the decision to the user.

### Changed

- **Agent system prompt routes repeated workflows through skills**: inline workflow walkthroughs are replaced by a grouped 1-line tool listing plus skill-system rules (trigger matching, `[PAUSE]` stop/resume semantics, write-action authorization). The prompt no longer grows with skill count.
- **PyYAML is now an explicit dependency** (previously transitive).

### Fixed

- **Empty agent replies on Zhipu GLM-4.7**: thinking mode could return the final answer only in `reasoning_content` with an empty `content` (reproducible on skill registry queries). The agent now disables thinking via `extra_body` when talking to Zhipu; other OpenAI-compatible providers are unaffected.

### Notes

- The agent-level `ingest_article` tool intentionally does **not** auto compile+embed (unlike CLI `qlw ingest`); the `full-ingest` skill runs `compile_wiki` / `embed_knowledge` as explicit post-review steps. A regression test pins this invariant.

## [0.4.6] - 2026-05-19

Bundle release: Track A (lint/brainstorm mtime cache + observability) and Track B (Zhipu 429 hardening + Retry-After HTTP-date + rate-gate observability).

### Performance

- **`lint_report` query-path mtime short-circuit** (`query/brainstorm`, #6): repeat queries against an unchanged KB skip the full lint scan. First query primes the cache; subsequent queries within the same process reuse it until any source file's mtime advances. Strict win — no API change, no env knob required.

### Added

- **Process-wide 429 cooldown gate** (`shared.py`, #7): when any worker receives an HTTP 429, every subsequent `post_llm_json` call in the same process honors a shared cooldown before issuing its next request. `_set_llm_cooldown(wait)` uses `max(existing, now + wait)` so concurrent 429s extend rather than overwrite the cooldown. Honors `Retry-After` ahead of exponential backoff, capped at 60 s.
- **Retry-After HTTP-date support** (`shared.py`, #7): `_retry_after_seconds` now parses RFC 7231 HTTP-date via `email.utils.parsedate_to_datetime` in addition to the existing delta-seconds path. Past dates and negative deltas clamp to 0.0.
- **`[qlw-perf] llm_rate_gate` line** (`shared.py`, #7): once per `post_llm_json` call, emits `cooldowns_applied=N total_wait_ms=T` under `QLW_PERF_DEBUG`. Zero overhead when the env var is unset.
- **`[qlw-perf] query_lint` and `[qlw-perf] lint_wiki` lines** (`query/brainstorm`, `wiki/lint`, #6): per-call timing with `lint_ms` and `scan_ms`/`write_ms`/`total_ms` respectively, gated on `QLW_PERF_DEBUG`.
- **Benchmark harness enhancements** (`scripts/benchmark_perf.py`, #6): `--no-mock-lint` flag and realistic concept seeding for the synthetic KB, plus a regex smoke test for the harness parser.

### Changed

- **`LLM_MIN_INTERVAL_SECONDS` default `0.5` → `2.0`** (`shared.py`, #7): more conservative pacing for batch enrichment. Restore the old default with `LLM_MIN_INTERVAL_SECONDS=0.5` in `.env` if needed.
- **`LLM_CONNECT_TIMEOUT` default `10` → `15`**, **`LLM_READ_TIMEOUT` `120` → `180`**, **`LLM_MAX_RETRIES` `2` → `4`** (`shared.py`, #7): better tolerance for slow provider regions.
- **429 retry path no longer calls `time.sleep(wait)` inside the retry loop** (`shared.py`, #7): the wait is converted into a cooldown that the next attempt's `_enforce_llm_rate_gate` consumes, avoiding double-sleep.
- **`[llm-retry]` stderr line enriched with `global cooldown` / `Retry-After honored` flags** (`shared.py`, #7).

### Documentation

- **README**: documents the new `LLM_MIN_INTERVAL_SECONDS` knob, the updated timeout/retry defaults, and the 429 cooldown behavior.
- **`llm_config.example.env`**: adds `LLM_MIN_INTERVAL_SECONDS=2.0` and updates `LLM_MAX_RETRIES=4`.
- **Plan & spec docs** (#6, #7): execution arrangement for the lint + Zhipu tracks, the Track B execution plan with pre-rebase audit, and the v0.4.5 perf validation addendum.

### Known limitations (deferred — own spec)

- **Lock held during `_enforce_llm_rate_gate` sleep**: pre-existing v0.4.3 behavior. With concurrent enrichment workers, in-flight requests cannot enter `_set_llm_cooldown()` while another worker is sleeping in the gate, leaving a small window where a request can slip through after the provider rate-limited but before the cooldown is recorded. Strictly improved over no-cooldown baseline; full fix requires releasing the lock during sleep and needs its own spec to preserve `_last_llm_call_ts` race safety.
- **Naive HTTP-date Retry-After** (`-0000` obsolete form): `parsedate_to_datetime` returns a naive datetime, which the code compares using `datetime.now()` in local time. LLM providers in practice send `GMT` (tz-aware UTC), so the practical impact is zero; can be tightened in a 1-line follow-up if it ever surfaces.

## [0.4.5] - 2026-05-18

### Performance

- **`_build_index_text` lazy hoist** (`compile_wiki`): moved the `_build_index_text` call out of the per-article assign loop and deferred it past the cache-hit skip path. Idempotent no-op compiles (all articles cache-hit skipped) now pay zero index-build cost; otherwise the build runs at most once per compile. Structurally O(A) → O(1) in stable-concept-file reads. The mocked-LLM harness shows `assign_ms` dropping from ~22,000 ms to ~884 ms at large scale (96% in-harness reduction, ≈25 s of redundant filesystem scans eliminated per compile); production proportional saving will be smaller because real `assign_concepts` LLM time dominates the per-iteration budget, but the absolute per-compile saving is the same. Two invariants lock the change: `BuildIndexTextInvariantTests` (stable-set is invariant within the assign-loop window) and `IndexTextNotBuiltOnNoOpCompileTests` (fully-skipped compile never builds the index).
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
