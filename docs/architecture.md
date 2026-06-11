# Architecture

Quant_LLM_Wiki follows Andrej Karpathy's [LLM-built KB method](https://karpathy.bearblog.dev/): a `raw/` ingest layer, an LLM-compiled `wiki/` of concept articles, and a `schema/` that both the LLM and the tools follow. Vector RAG is preserved as a fallback substrate, not the primary retrieval path. Three durable verbs — `ingest`, `query`, `lint` — drive everything. A built-in **Rethink Layer** scores novelty and quality of brainstormed ideas before output.

## Layout

```
raw/      — incoming source articles (one dir per article: article.md + source.json + images/)
wiki/     — LLM-built Markdown memory (the primary query surface)
            ├── INDEX.md          — auto-maintained table of contents
            ├── state.json        — content hashes, concept scores, retrieval hints
            ├── lint_report.json  — last health audit
            ├── concepts/<slug>.md
            ├── sources/<basename>.md
            ├── queries/<date>_<slug>_<mode>.md   — query → wiki feedback log
            └── maintenance_report.md             — last `qlw lint --maintain` output
schema/   — rules the LLM and tools follow:
            concept-schema.md, source-schema.md, wiki-structure.md, operations.md
vector_store/  — ChromaDB substrate, used as fallback only
```

Articles live **flat** under `raw/`. The frontmatter `status` field (`raw`, `reviewed`, `high_value`, `rejected`) is the source of truth — there is no directory-as-status convention.

## Three operations

```
                                              ┌──> wiki/concepts/<slug>.md
                                              ├──> wiki/sources/<basename>.md
WeChat URL / Web URL / PDF / HTML             ├──> wiki/INDEX.md
        |                                     ├──> wiki/state.json
        v                                     │    (hashes, scores, freshness, retrieval hints)
  [qlw ingest] ──> raw/<dir>/article.md + source.json
        |                                     ▲
        v                                     │
  [qlw compile]  ── schema/-injected LLM ─────┘
  (auto after ingest)
        |
        v
  [qlw embed]  ── ChromaDB substrate over raw/ + wiki/
  (auto after compile)
        |
        v
  [qlw ask / qlw brainstorm]  ── wiki-first retrieval (INDEX → matched concepts → source summaries)
        |        RAG runs ONLY when wiki has no relevant concept or audit reports degradation
        |        (brainstorm runs Rethink Layer post-generation)
        |
        v
  ┌─ outputs/brainstorms/<date>_<slug>_<mode>.md
  └─ wiki/queries/<date>_<slug>_<mode>.md  ── append_query_log:
                                              cited concepts get importance bump
                                              + retrieval_hints append in state.json

  [qlw lint]              ── schema-compliance audit (frontmatter, sections, source anchors)
  [qlw lint --fix]        ── LLM auto-repair of schema-noncompliant concepts
  [qlw lint --maintain]   ── gap analysis: unmapped source clusters, under-supported concepts,
                            stale concepts → suggested ingestion queries / new brainstorm prompts
                            (writes wiki/maintenance_report.md)
  [qlw lint --maintain --apply]  ── apply query-derived state updates idempotently
```

## Wiki-first retrieval (load-bearing invariant)

`brainstorm_from_kb.retrieve_blocks` gates on `_should_use_wiki_memory(notes) and _wiki_is_healthy_for_query(kb_root)`. There is **no** `command == "brainstorm"` check — both `ask` and `brainstorm` pull `kb_layer=wiki_concept` blocks first (Chroma-filtered → state-score reranked → lexical fallback), then fill remaining slots with complementary article chunks excluding sources already cited by the surfaced concepts. Pure-vector retrieval is the fallback, not the default.

## Query → wiki feedback

Every `qlw ask` / `qlw brainstorm` run writes the answer to `outputs/brainstorms/` AND files a one-line query log at `wiki/queries/<YYYY-MM-DD>_<slug>_<mode>.md`. The log captures the query text, mode, output filename, and which concepts/sources were cited. `qlw lint --maintain` digests these logs to surface gaps — under-supported concepts, unmapped sources, and stale areas worth backfilling. Pass `--no-query-log` to opt out of filing.

This realizes Karpathy's *"my own explorations and queries always 'add up' in the knowledge base."*

## Schema is enforced, not advisory

`schema/concept-schema.md` and `schema/source-schema.md` define required frontmatter fields, valid enum values, and required section headers. `wiki_lint` checks these on every run (severity: warning), and `qlw lint --fix` runs an LLM auto-repair pass via `recompile_concept` for schema-noncompliant concepts. The schema text is also injected into compile-time prompts so the LLM is told the source-anchor invariant.

## Rethink Layer

A post-generation validation layer that runs automatically in brainstorm mode:

1. **Idea Parsing** — Extracts structured ideas from LLM output (EN/CN formats)
2. **Novelty Check** — Embeds each idea and queries ChromaDB for similar existing articles (threshold: 0.75)
3. **Quality Scoring** — Traceability (heuristic) + Coherence & Actionability (LLM-as-judge)
4. **Rethink Report** — Appended to output with per-idea scores and reasoning

## Agent Layer

The LangGraph ReAct agent provides 15 tools (plus 7 workflow-memory tools when memory is enabled, the default):

| Tool | Description |
|------|-------------|
| `ingest_article` | Ingest from URL (auto: WeChat / web / PDF), batch URLs, HTML file, PDF file, PDF URL |
| `enrich_articles` | LLM-powered structured enrichment (concurrent, with `limit` support) |
| `list_articles` | List articles by status (raw / reviewed / high_value); all live flat under `raw/` |
| `review_articles` | Show enriched articles ready for review |
| `set_article_status` | Update article status field in frontmatter |
| `embed_knowledge` | Build/update ChromaDB vector index over `raw/` + `wiki/` |
| `query_knowledge_base` | Wiki-first Q&A or brainstorm; both modes pull stable wiki concepts before vectors |
| `compile_wiki` | Compile/update wiki (incremental or rebuild); auto-runs lint |
| `audit_wiki` | Wiki health report: schema violations, stale concepts, unsupported claims, duplicates |
| `list_concepts` | List wiki concepts by status (stable / proposed / deprecated) |
| `set_concept_status` | Override: approve/deprecate/delete a concept (escape hatch) |
| `read_wiki` | Read INDEX.md / a concept article / a source summary |
| `save_strategy_brief` | Persist the converged brief of a multi-turn strategy conversation to `outputs/brainstorms/<date>_<slug>_brief.md`; fires only on the user's explicit convergence instruction. Its query log never mutates `wiki/state.json` — conversation-authored citations are not pipeline-trusted |
| `list_skills` | List registered skill SOPs (name / description / triggers / tools_used) |
| `read_skill` | Read one skill's full SOP markdown by name |

### Skills

Multi-step workflows are codified as SOP markdown files ("skills") with frontmatter (triggers, `tools_used`, `[PAUSE]` gates where the agent must stop for a user decision). Five ship inside the package (`quant_llm_wiki/agent/skills/`): `full-ingest`, `concept-review`, `kb-health-check`, `wiki-explanation`, `strategy-brainstorm`. KB-level skills in `<kb_root>/.qlw/skills/` override package skills by name; `qlw memory promote-procedure <id>` generates them from conversationally captured procedure drafts. The skill registry is the only runtime SOP system — the system prompt holds rules, not workflows.

`strategy-brainstorm` is an entry-routed 5-stage SOP (clarify → orient → propose → refine → converge): stages are a state library, not a pipeline — the agent enters at the latest viable stage, with memory state (decisions / open notes / prior briefs) counting as completed prior stages.

### Workflow memory

Enabled by default; `--no-memory` runs are fully stateless. Two substrates under `<kb_root>/.qlw/memory/`:

- `workflow.md` — human-editable narrative (Current Handoff / Next Steps / Blockers / Recent Sessions). Hand-edits always win; Recent Sessions only logs sessions with significant write actions.
- `memory.sqlite` — sessions, tasks, decisions, research notes (hypothesis / direction / observation, per thread), procedure drafts, with FTS5 search.

Seven agent tools (`record_decision`, `add_task`, `complete_task`, `list_open_tasks`, `record_note`, `set_note_status`, `propose_procedure`) and the `qlw memory` CLI manage it. Sessions open with a token-budgeted preamble (handoff, open tasks, recent decisions, open notes for the active thread). Research notes hold unstable process state and never enter the wiki; the wiki holds stable knowledge only.

## File structure

```
Quant_LLM_Wiki/
├── pyproject.toml                  # Package metadata + `qlw` console_script entry point
├── requirements.txt                # Python dependencies (kept for non-pip-install users)
├── llm_config.example.env          # Example LLM provider config
├── README.md / README.zh-CN.md
├── LICENSE
├── quant_llm_wiki/                 # Installable Python package (all functionality here)
│   ├── cli.py                      # `qlw` dispatcher (10 subcommands)
│   ├── shared.py                   # Shared utilities, LLM HTTP client, frontmatter
│   ├── paths.py                    # KB root resolution (resolve_kb_root)
│   ├── enrich.py                   # LLM enrichment pipeline
│   ├── embed.py                    # ChromaDB substrate over raw/ + wiki/
│   ├── sync.py                     # Article status-based file sync
│   ├── ingest/                     # WeChat / web / PDF / HTML extractors
│   ├── wiki/                       # compile, lint, maintain, schemas, state, index, seed
│   ├── query/                      # brainstorm (wiki-first retrieval) + rethink
│   ├── agent/                      # LangGraph ReAct agent (tools, skills/ SOPs, memory/)
│   └── templates/                  # research-note / strategy-note article templates
├── raw/                            # Incoming source articles (gitignored — user data)
├── wiki/                           # LLM-built Markdown memory (gitignored — user data)
├── vector_store/                   # ChromaDB substrate (gitignored — derivable)
├── schema/                         # Rules followed by LLM and tools (tracked)
├── examples/tiny_kb/               # Tiny worked example (tracked)
├── tests/                          # unittest suite, including tests/robustness/
└── docs/                           # User docs + this file
```

## Design principles

- **Wiki-first, RAG-as-substrate** — Both `qlw ask` and `qlw brainstorm` retrieve stable wiki concepts before vectors. ChromaDB runs only as fallback when the wiki is empty/sparse or `audit_wiki` reports degradation.
- **Three durable verbs** — `qlw ingest`, `qlw ask`/`qlw brainstorm`, `qlw lint` per Karpathy's prescription. `compile` and `embed` are internal operations auto-run by `ingest`.
- **Schema is enforced** — required frontmatter fields, valid enums, and required section headers. `wiki_lint` checks these on every run; `qlw lint --fix` runs an LLM auto-repair pass.
- **Inspiration over execution** — The knowledge base serves idea combination, not backtested trading signals.
- **Hybrid memory: Markdown + structured state** — Markdown is the inspectable interface; `wiki/state.json` and ChromaDB metadata are the operational substrate (scoring, freshness decay, conflict tracking).
- **Per-claim provenance** — Every bullet in a concept article ends with `[<source_basename>]`; un-anchored bullets fail lint and lower confidence.
- **Content-hash idempotency** — `qlw compile` reruns produce zero LLM calls when source hashes are unchanged (no `mtime`, no date guessing).
- **Queries compound** — Every `qlw ask`/`qlw brainstorm` files into `wiki/queries/` and bumps state.json scoring for cited concepts. `qlw lint --maintain` distills the query log into proposed concept-page improvements.
- **Complementary retrieval** — Wiki concepts surface first, then complementary article chunks fill remaining slots (excluding sources already cited by concepts).
- **Graceful degradation** — Every component handles missing dependencies without crashing; `audit_wiki` errors push the wiki-first path to article-only fallback.
- **Self-healing vector store** — Automatic SQLite integrity check before each ChromaDB operation; corrupted stores are cleaned up and rebuilt transparently.
