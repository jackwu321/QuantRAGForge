# Perf Validation Data — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce real timing data that validates the two v0.4.3 perf wins (brainstorm concept-retrieval dedup, compile reverse-index lookup) and establishes a baseline for the two larger follow-up items (`_build_index_text` hoist, query-time `lint_wiki` staleness).

**Architecture:** Three small pieces. (1) Upgrade the existing `QLW_PERF_DEBUG` log lines from count-only to count+timing — `perf_counter` deltas wrapped around the already-instrumented paths, emitting structured `key=value` pairs. (2) A self-contained benchmark harness `scripts/benchmark_perf.py` that builds a deterministic synthetic KB, mocks the LLM calls (`assign_concepts`, `recompile_concept`, `_retrieve_concept_articles`) so we measure only the in-process structural work that actually changed, runs compile + brainstorm at configurable scale, and writes a JSON record under `benchmarks/`. (3) A comparison report committed to `docs/superpowers/specs/` that diffs v0.4.2 (checked out in a throwaway worktree with the instrumentation backported, never committed there) against v0.4.3 (HEAD).

**Tech Stack:** Python 3, `unittest`, `time.perf_counter`, `json`, `unittest.mock.patch`, `git worktree`. No new third-party deps. All deterministic, no API keys required.

**Scope note:** Mocking is deliberate. The v0.4.3 wins are in-process algorithmic — removing one redundant retrieval call, replacing an O(S·A) scan with O(1) lookup. Measuring through real Chroma + real LLM calls would dwarf the signal in network noise. The benchmark proves the **structural** change does what the design doc claimed; it does not claim to model production latency.

**Plan location convention:** Per the repo's prior practice (see siblings `2026-05-06-repo-restructure-design.md`, `2026-05-17-brainstorm-compile-perf-design.md`), planning + design documents live under `docs/superpowers/specs/`. This plan and the eventual validation report both go there.

---

## File Structure

**Modified (instrumentation upgrades — small, focused edits):**
- `quant_llm_wiki/query/brainstorm.py` — wrap `_retrieve_concept_articles` with timing, extend the `retrieve_blocks` debug line.
- `quant_llm_wiki/wiki/compile.py` — split the existing single debug line into assign-phase + recompile-phase timings.

**Created:**
- `scripts/benchmark_perf.py` — harness. Builds synthetic KB, mocks LLM, runs compile + brainstorm at requested scale, writes JSON.
- `benchmarks/.gitignore` — keep raw `.json` records local (they're noisy and machine-specific); the durable artifact is the report markdown.
- `benchmarks/README.md` — one-pager: how to run, how to interpret, what's in/out of scope.
- `tests/test_perf_instrumentation.py` — locks the `[qlw-perf]` line format so future refactors don't silently break the harness's parser.
- `tests/test_benchmark_perf.py` — integration test that runs the harness at a tiny scale end-to-end (catches import/wiring regressions; doesn't assert on numbers).
- `docs/superpowers/specs/2026-05-17-perf-validation-report.md` — the deliverable. Written in Task 9 after both runs complete.

**No changes to public CLI surface.** `QLW_PERF_DEBUG` stays an env-gated diagnostic; the benchmark script invokes the library API directly.

---

## Decisions Locked Before Implementation

| Decision | Choice | Reason |
|---|---|---|
| LLM during benchmark | Mocked | Measure only the in-process change; remove API-key + network variance |
| Real KB or synthetic | Synthetic, deterministic builder | Reproducible across machines and across the v0.4.2 ↔ v0.4.3 comparison |
| Default scale | 100 articles × 40 concepts × ~4 feeds/article | Big enough that the compile reverse-index win is visible (~4000 list ops avoided), small enough to run in <10s |
| Optional larger scale | `--scale large` → 500a × 100c | For the report's "does it stay linear?" plot |
| Trials per scale | 3, report median | Cheap insurance against GC/cache outliers |
| Where raw JSON lives | `benchmarks/` (gitignored) | Per-machine artifacts, not part of the repo's durable record |
| Where the report lives | `docs/superpowers/specs/2026-05-17-perf-validation-report.md` | Durable; matches the existing perf design doc's location |
| Comparison method for v0.4.2 | Throwaway worktree with instrumentation backported (uncommitted) | v0.4.2 has no instrumentation; backporting the diff is cleaner than maintaining two harnesses |
| Test framework | `unittest` | Repo convention — every existing `tests/test_*.py` uses it |

---

## Task 1: Add timing to `_retrieve_concept_articles`

**Files:**
- Modify: `quant_llm_wiki/query/brainstorm.py` around L666–L690 (the body of `_retrieve_concept_articles`).
- Test: `tests/test_perf_instrumentation.py` (new file).

The existing function dispatches to `_retrieve_concepts_via_chroma` then falls back to `_retrieve_concepts_via_lexical`. Both have meaningful per-call cost. We want a `[qlw-perf]` line that records which path served the result and how long it took.

- [ ] **Step 1: Write the failing test**

Create `tests/test_perf_instrumentation.py`:

```python
import io
import os
import re
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stderr
from pathlib import Path

from quant_llm_wiki.query import brainstorm as brainstorm_mod


PERF_LINE_RE = re.compile(r"^\[qlw-perf\] ([a-z_]+): (.+)$")


def parse_perf_lines(stderr: str) -> list[dict]:
    """Return a list of {event, fields} dicts, one per [qlw-perf] line."""
    out = []
    for line in stderr.splitlines():
        m = PERF_LINE_RE.match(line)
        if not m:
            continue
        event = m.group(1)
        fields = {}
        for kv in m.group(2).split():
            if "=" in kv:
                k, v = kv.split("=", 1)
                fields[k] = v
        out.append({"event": event, "fields": fields})
    return out


class RetrieveConceptArticlesTimingTests(unittest.TestCase):
    def test_emits_timing_line_with_mode_and_ms(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            (wiki_dir / "concepts").mkdir(parents=True)
            buf = io.StringIO()
            with unittest.mock.patch.dict(os.environ, {"QLW_PERF_DEBUG": "1"}):
                with redirect_stderr(buf):
                    brainstorm_mod._retrieve_concept_articles(
                        "anything", top_k=3, wiki_dir=wiki_dir,
                    )
            events = parse_perf_lines(buf.getvalue())
            timing = [e for e in events if e["event"] == "_retrieve_concept_articles"]
            self.assertEqual(len(timing), 1, f"expected exactly 1 timing line, got {buf.getvalue()!r}")
            f = timing[0]["fields"]
            self.assertIn("ms", f)
            self.assertIn("mode", f)
            self.assertIn("results", f)
            self.assertIn(f["mode"], {"chroma", "lexical", "empty"})
            self.assertGreaterEqual(float(f["ms"]), 0.0)
            self.assertEqual(f["results"], "0")  # empty wiki → no concepts


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_perf_instrumentation.RetrieveConceptArticlesTimingTests -v`

Expected: FAIL — no `[qlw-perf] _retrieve_concept_articles:` line is emitted yet.

- [ ] **Step 3: Add timing instrumentation to `_retrieve_concept_articles`**

In `quant_llm_wiki/query/brainstorm.py`, change the function body from:

```python
def _retrieve_concept_articles(
    query: str,
    top_k: int = DEFAULT_CONCEPT_TOP_K,
    vector_store_dir: Path | None = None,
    wiki_dir: Path | None = None,
) -> list[dict]:
    """..."""
    resolved_wiki_dir = wiki_dir or (resolve_kb_root(None) / "wiki")
    if not (resolved_wiki_dir / "concepts").exists():
        return []
    store = vector_store_dir or (resolve_kb_root(None) / "vector_store")
    via_chroma = _retrieve_concepts_via_chroma(query, top_k, store, resolved_wiki_dir)
    if via_chroma:
        return via_chroma
    return _retrieve_concepts_via_lexical(query, top_k, resolved_wiki_dir)
```

to:

```python
def _retrieve_concept_articles(
    query: str,
    top_k: int = DEFAULT_CONCEPT_TOP_K,
    vector_store_dir: Path | None = None,
    wiki_dir: Path | None = None,
) -> list[dict]:
    """..."""
    import time
    t0 = time.perf_counter()
    resolved_wiki_dir = wiki_dir or (resolve_kb_root(None) / "wiki")
    if not (resolved_wiki_dir / "concepts").exists():
        _emit_perf("_retrieve_concept_articles", ms=(time.perf_counter() - t0) * 1000.0, mode="empty", results=0)
        return []
    store = vector_store_dir or (resolve_kb_root(None) / "vector_store")
    via_chroma = _retrieve_concepts_via_chroma(query, top_k, store, resolved_wiki_dir)
    if via_chroma:
        _emit_perf("_retrieve_concept_articles", ms=(time.perf_counter() - t0) * 1000.0, mode="chroma", results=len(via_chroma))
        return via_chroma
    via_lex = _retrieve_concepts_via_lexical(query, top_k, resolved_wiki_dir)
    _emit_perf("_retrieve_concept_articles", ms=(time.perf_counter() - t0) * 1000.0, mode="lexical", results=len(via_lex))
    return via_lex
```

And add this helper near the top of the file, just after the existing imports of `os` / `sys` (search for `import os` and place it nearby):

```python
def _emit_perf(event: str, **fields) -> None:
    """Emit a single [qlw-perf] line when QLW_PERF_DEBUG is set. Zero-cost when off."""
    if not os.environ.get("QLW_PERF_DEBUG"):
        return
    parts = []
    for k, v in fields.items():
        if isinstance(v, float):
            parts.append(f"{k}={v:.3f}")
        else:
            parts.append(f"{k}={v}")
    print(f"[qlw-perf] {event}: {' '.join(parts)}", file=sys.stderr)
```

Make sure `import sys` is present at the top of the file. (`sys` is already imported — verify before adding.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest tests.test_perf_instrumentation.RetrieveConceptArticlesTimingTests -v`

Expected: PASS — one line matching `_retrieve_concept_articles: ms=… mode=empty results=0`.

- [ ] **Step 5: Commit**

```bash
git add quant_llm_wiki/query/brainstorm.py tests/test_perf_instrumentation.py
git commit -m "perf(instrument): time _retrieve_concept_articles + mode tagging

Adds per-call timing and chroma/lexical/empty mode tagging to the
QLW_PERF_DEBUG output, with a shared _emit_perf helper. Zero cost
when the env var is unset."
```

---

## Task 2: Extend `retrieve_blocks` wiki-branch debug line

**Files:**
- Modify: `quant_llm_wiki/query/brainstorm.py` L794–L799.
- Test: `tests/test_perf_instrumentation.py` (append a class).

The current line only emits `concept_retrievals=1 wiki_blocks=N`. Add the wall-clock time of the wiki branch.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_perf_instrumentation.py`:

```python
class RetrieveBlocksTimingTests(unittest.TestCase):
    def test_retrieve_blocks_emits_total_ms(self):
        from quant_llm_wiki.query.brainstorm import retrieve_blocks
        from quant_llm_wiki.shared import KnowledgeNote

        with tempfile.TemporaryDirectory() as tmp:
            kb_root = Path(tmp)
            (kb_root / "wiki" / "concepts").mkdir(parents=True)
            (kb_root / "wiki" / "INDEX.md").write_text("# index\n", encoding="utf-8")
            # Note with absolute article_dir → triggers wiki branch
            note = KnowledgeNote(
                article_dir=kb_root / "articles" / "x" / "article.md",
                source_dir="articles",
                frontmatter={"title": "x", "content_type": ""},
                body="hello world",
            )
            buf = io.StringIO()
            with unittest.mock.patch.dict(os.environ, {"QLW_PERF_DEBUG": "1"}), \
                 unittest.mock.patch(
                     "quant_llm_wiki.query.brainstorm._wiki_is_healthy_for_query",
                     return_value=True,
                 ):
                with redirect_stderr(buf):
                    retrieve_blocks(
                        [note], "any query", top_k=3,
                        command="brainstorm", retrieval_mode="keyword",
                        kb_root=kb_root,
                    )
            events = parse_perf_lines(buf.getvalue())
            rb = [e for e in events if e["event"] == "retrieve_blocks"]
            self.assertEqual(len(rb), 1)
            f = rb[0]["fields"]
            # Log emits real measurements only. The "concept_retrievals == 1"
            # invariant is locked by tests/test_brainstorm_with_wiki.py's
            # spy test, not by a hardcoded log field — printing a constant
            # would silently lie if a future refactor adds fallback retrieval.
            self.assertNotIn("concept_retrievals", f)
            self.assertIn("wiki_blocks", f)
            self.assertIn("excluded_articles", f)
            self.assertIn("total_ms", f)
            self.assertGreaterEqual(float(f["total_ms"]), 0.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_perf_instrumentation.RetrieveBlocksTimingTests -v`

Expected: FAIL — the existing line has no `total_ms`.

- [ ] **Step 3: Extend the debug emission**

In `quant_llm_wiki/query/brainstorm.py` `retrieve_blocks`, change the wiki-branch start from:

```python
    wiki_blocks: list[KnowledgeBlock] = []
    excluded_articles: set[str] = set()
    if _should_use_wiki_memory(notes) and _wiki_is_healthy_for_query(resolved_kb_root):
        wiki_blocks, wiki_concepts = _retrieve_concepts_and_blocks(
```

to (note the `import time` + `t_wiki` capture):

```python
    wiki_blocks: list[KnowledgeBlock] = []
    excluded_articles: set[str] = set()
    if _should_use_wiki_memory(notes) and _wiki_is_healthy_for_query(resolved_kb_root):
        import time
        t_wiki = time.perf_counter()
        wiki_blocks, wiki_concepts = _retrieve_concepts_and_blocks(
```

Then replace the existing emission block:

```python
        if os.environ.get("QLW_PERF_DEBUG"):
            print(
                f"[qlw-perf] retrieve_blocks: concept_retrievals=1 "
                f"wiki_blocks={len(wiki_blocks)}",
                file=sys.stderr,
            )
```

with:

```python
        _emit_perf(
            "retrieve_blocks",
            wiki_blocks=len(wiki_blocks),
            excluded_articles=len(excluded_articles),
            total_ms=(time.perf_counter() - t_wiki) * 1000.0,
        )
```

> Deliberately **not** emitting `concept_retrievals=1`. The dedup invariant ("retrieve_blocks calls `_retrieve_concept_articles` exactly once") is locked by the spy test in `tests/test_brainstorm_with_wiki.py` — that test will fail if a future refactor reintroduces a second call. A log field that prints `1` regardless of reality would be worse than no field at all: it would survive a regression while silently lying. If the call count ever needs to be observed at runtime, wrap the call site with an actual counter, don't reach for the literal.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest tests.test_perf_instrumentation.RetrieveBlocksTimingTests -v`

Expected: PASS.

- [ ] **Step 5: Run the spy test that locks the call-count invariant**

This is the test that *actually* enforces `_retrieve_concept_articles` is called exactly once per `retrieve_blocks` invocation. The log line dropped the hardcoded `concept_retrievals=1`; this test is now the sole guardian of that contract.

Run: `python3 -m unittest tests.test_brainstorm_with_wiki -v`

Expected: all tests pass. If `RetrieveBlocksCallCountTests` is not present (the v0.4.3 plan called for it but it might have been merged elsewhere), grep `tests/` for `spy.call_count` / `assert_called_once` around `_retrieve_concept_articles`; if no such assertion exists anywhere, add one before continuing — without it, the invariant has no enforcement.

- [ ] **Step 6: Commit**

```bash
git add quant_llm_wiki/query/brainstorm.py tests/test_perf_instrumentation.py
git commit -m "perf(instrument): time retrieve_blocks wiki branch with real values

Emits wiki_blocks, excluded_articles, total_ms — drops the hardcoded
concept_retrievals=1 (it asserted an invariant rather than measuring
one). The call-count invariant stays locked by the spy test in
tests/test_brainstorm_with_wiki.py."
```

---

## Task 3: Split `compile_wiki` debug line into phase timings

**Files:**
- Modify: `quant_llm_wiki/wiki/compile.py` around L270 (start of assign loop), L333 (start of recompile loop), L401–L407 (current debug emission).
- Test: `tests/test_perf_instrumentation.py` (append a class).

The current line emits `articles=N affected_concepts=M reverse_index_size=K`. Split into `assign_ms` (the assign loop wall time) + `recompile_ms` (the recompile loop wall time). These are the two phases that v0.4.3's reverse-index change affects.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_perf_instrumentation.py`:

```python
class CompileWikiTimingTests(unittest.TestCase):
    def test_compile_emits_phase_timings(self):
        # Build a minimal KB: 1 article, mock the LLM calls so we don't need keys.
        from quant_llm_wiki.wiki import compile as compile_mod
        from quant_llm_wiki.wiki.types import AssignmentResult, RecompileResult

        with tempfile.TemporaryDirectory() as tmp:
            kb_root = Path(tmp)
            (kb_root / "wiki").mkdir()
            article_dir = kb_root / "articles" / "a1"
            article_dir.mkdir(parents=True)
            (article_dir / "article.md").write_text(
                "---\ntitle: A1\ncontent_type: paper\n---\nhello\n",
                encoding="utf-8",
            )

            fake_assign = AssignmentResult(
                existing_concepts=[],
                proposed_new_concepts=[],
                error=None,
            )
            fake_recompile = RecompileResult(
                synthesis="s", definition="d", related_concepts=[],
                key_idea_blocks=[], variants=[], common_combinations=[],
                transfer_targets=[], failure_modes=[], open_questions=[],
                error=None,
            )

            buf = io.StringIO()
            with unittest.mock.patch.dict(os.environ, {"QLW_PERF_DEBUG": "1"}), \
                 unittest.mock.patch.object(compile_mod, "assign_concepts", return_value=fake_assign), \
                 unittest.mock.patch.object(compile_mod, "recompile_concept", return_value=fake_recompile):
                with redirect_stderr(buf):
                    compile_mod.compile_wiki(
                        kb_root=kb_root,
                        source_dirs=["articles"],
                        mode="full",
                        dry_run=True,
                    )
            events = parse_perf_lines(buf.getvalue())
            cw = [e for e in events if e["event"] == "compile_wiki"]
            self.assertEqual(len(cw), 1, f"got {buf.getvalue()!r}")
            f = cw[0]["fields"]
            for key in ("articles", "affected_concepts", "reverse_index_size", "assign_ms", "recompile_ms"):
                self.assertIn(key, f, f"missing {key} in {f}")
            self.assertGreaterEqual(float(f["assign_ms"]), 0.0)
            self.assertGreaterEqual(float(f["recompile_ms"]), 0.0)
```

> Verify the import paths before running. If `AssignmentResult` / `RecompileResult` are defined elsewhere (e.g. in `quant_llm_wiki.wiki.assign` and `quant_llm_wiki.wiki.recompile` rather than `types`), adjust the imports in the test to point at the actual modules — grep for `class AssignmentResult` and `class RecompileResult` and use whatever path appears. Same for `compile_mod.assign_concepts` / `compile_mod.recompile_concept` (they must be the names bound in `wiki/compile.py`'s import surface for `patch.object` to work). Use `grep -n "^from .* import\|^import" quant_llm_wiki/wiki/compile.py` to confirm.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_perf_instrumentation.CompileWikiTimingTests -v`

Expected: FAIL — no `assign_ms` / `recompile_ms` in the current output.

- [ ] **Step 3: Add phase timing**

In `quant_llm_wiki/wiki/compile.py`, just before the assign loop (`for article_index, article_dir in enumerate(articles, start=1):` at L270), add:

```python
    import time
    _t_assign_start = time.perf_counter()
```

Just after the assign loop and `if not dry_run: save_wiki_state(...)` block (right before `# Recompile each affected concept` at L333), add:

```python
    _assign_ms = (time.perf_counter() - _t_assign_start) * 1000.0
    _t_recompile_start = time.perf_counter()
```

Right after the recompile loop ends (immediately before the existing `if os.environ.get("QLW_PERF_DEBUG"):` block at L401), add:

```python
    _recompile_ms = (time.perf_counter() - _t_recompile_start) * 1000.0
```

Then replace the existing emission:

```python
    if os.environ.get("QLW_PERF_DEBUG"):
        print(
            f"[qlw-perf] compile_wiki: articles={len(articles)} "
            f"affected_concepts={len(sorted_slugs)} "
            f"reverse_index_size={len(concept_to_articles)}",
            file=sys.stderr,
        )
```

with (use the same `_emit_perf` helper — import it from brainstorm or duplicate the 6 lines locally; pick whichever is simpler):

```python
    from quant_llm_wiki.query.brainstorm import _emit_perf
    _emit_perf(
        "compile_wiki",
        articles=len(articles),
        affected_concepts=len(sorted_slugs),
        reverse_index_size=len(concept_to_articles),
        assign_ms=_assign_ms,
        recompile_ms=_recompile_ms,
    )
```

> If the cross-module import feels wrong (it does — `wiki/` shouldn't depend on `query/`), promote `_emit_perf` into a shared utility instead: create `quant_llm_wiki/shared_perf.py` with the helper and have both files import from there. Cost: one extra file, three lines per call site change. Do this on the first refactor and remove the inter-module dependency.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest tests.test_perf_instrumentation.CompileWikiTimingTests -v`

Expected: PASS.

- [ ] **Step 5: Run the broader compile test suite to confirm no regression**

Run: `python3 -m unittest tests.test_wiki_compile -v`

Expected: all tests pass — the timing wrap is read-only.

- [ ] **Step 6: Commit**

```bash
git add quant_llm_wiki/wiki/compile.py tests/test_perf_instrumentation.py
git commit -m "perf(instrument): split compile_wiki debug line into phase timings

Adds assign_ms and recompile_ms alongside the existing count fields.
The recompile phase is where v0.4.3's reverse-index win lives, and
splitting the phases lets the benchmark harness attribute speedup."
```

---

## Task 4: Lock the reverse-index multi-source contract

**Files:**
- Create: `tests/test_wiki_compile_reverse_index.py`.

The v0.4.3 reverse index in `compile.py` (`concept_to_articles`, L260) gets populated from **two** branches inside the assign loop: the skip branch at L288 (`_register_article_concepts(article_dir, list(prior_entry.feeds_concepts))`) and the post-LLM changed branch at L326 (`_register_article_concepts(article_dir, feeds)`). The end-to-end tests in `tests/test_wiki_compile.py` exercise the happy path but don't pin the **interleaved** case: in a single incremental compile, one contributing article is skipped (content-hash match) while another is changed. If a future refactor stops registering on the skip branch, the recompile prompt for that concept would silently lose half its sources — and end-to-end tests likely won't catch it because recompile output is LLM-generated and content equality is loose.

This task adds a focused regression test that locks the contract.

- [ ] **Step 1: Write the test**

Create `tests/test_wiki_compile_reverse_index.py`:

```python
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from quant_llm_wiki.wiki import compile as compile_mod
# Adjust this import if classes live elsewhere — grep "class AssignmentResult"
from quant_llm_wiki.wiki.types import AssignmentResult, RecompileResult


def _write_article(kb_root: Path, slug: str, body: str, topic: str = "topic_alpha") -> Path:
    ad = kb_root / "articles" / slug
    ad.mkdir(parents=True, exist_ok=True)
    (ad / "article.md").write_text(
        f"---\ntitle: {slug}\ncontent_type: paper\nmain_topic: {topic}\n---\n{body}\n",
        encoding="utf-8",
    )
    return ad


def _seed_concept(kb_root: Path, slug: str) -> None:
    cd = kb_root / "wiki" / "concepts"
    cd.mkdir(parents=True, exist_ok=True)
    (cd / f"{slug}.md").write_text(
        f"---\ntitle: {slug}\nslug: {slug}\nstatus: stable\naliases: []\n"
        f"related_concepts: []\nsources: []\ncontent_types: [paper]\n"
        f"last_compiled: 2026-01-01\ncompile_version: 0\nsource_basenames: []\n---\n"
        f"prior definition of {slug}\n",
        encoding="utf-8",
    )


class ReverseIndexMultiSourceTests(unittest.TestCase):
    def test_skipped_and_changed_articles_both_feed_recompile(self):
        """
        Two articles feed 'topic_alpha'. First compile establishes state;
        second compile changes article B only — article A takes the
        incremental skip branch, article B takes the changed branch.
        The recompile for topic_alpha must receive BOTH paths exactly once.
        """
        with tempfile.TemporaryDirectory() as tmp:
            kb_root = Path(tmp)
            _seed_concept(kb_root, "topic_alpha")
            a = _write_article(kb_root, "art_a", body="content A v1")
            b = _write_article(kb_root, "art_b", body="content B v1")

            assign_result = AssignmentResult(
                existing_concepts=["topic_alpha"],
                proposed_new_concepts=[],
                error=None,
            )
            recompile_calls: list[dict] = []

            def fake_recompile(*, concept_slug, concept_title, source_articles, schema_text=None):
                recompile_calls.append({
                    "slug": concept_slug,
                    "sources": [sa.get("source_basename") for sa in source_articles],
                })
                return RecompileResult(
                    synthesis="s", definition="d", related_concepts=[],
                    key_idea_blocks=[], variants=[], common_combinations=[],
                    transfer_targets=[], failure_modes=[], open_questions=[],
                    error=None,
                )

            with unittest.mock.patch.object(compile_mod, "assign_concepts", return_value=assign_result), \
                 unittest.mock.patch.object(compile_mod, "recompile_concept", side_effect=fake_recompile):
                # First compile: full mode, establish state
                compile_mod.compile_wiki(
                    kb_root=kb_root, source_dirs=["articles"],
                    mode="full", dry_run=False,
                )

                # Modify article B → its content hash changes
                (b / "article.md").write_text(
                    "---\ntitle: art_b\ncontent_type: paper\nmain_topic: topic_alpha\n"
                    "---\ncontent B v2 — CHANGED\n",
                    encoding="utf-8",
                )

                recompile_calls.clear()

                # Second compile: incremental.
                # A is unchanged → skip branch at compile.py:L288.
                # B is changed   → changed branch at compile.py:L326.
                # Both must end up in the reverse index, and the recompile
                # for topic_alpha must see both.
                compile_mod.compile_wiki(
                    kb_root=kb_root, source_dirs=["articles"],
                    mode="incremental", dry_run=False,
                )

            alpha = [c for c in recompile_calls if c["slug"] == "topic_alpha"]
            self.assertEqual(len(alpha), 1,
                             f"topic_alpha should recompile exactly once, got {alpha}")
            sources = alpha[0]["sources"]
            self.assertIn("art_a", sources, "skipped article must still feed recompile")
            self.assertIn("art_b", sources, "changed article must feed recompile")
            self.assertEqual(len(sources), len(set(sources)),
                             f"no duplicates expected, got {sources}")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run on current HEAD (v0.4.3) — must pass**

Run: `python3 -m unittest tests.test_wiki_compile_reverse_index -v`

Expected: PASS. v0.4.3 already implements both branches; this test locks them.

- [ ] **Step 3: Mutation-check the test is meaningful**

To gain confidence the test isn't a tautology, temporarily break the skip branch in `quant_llm_wiki/wiki/compile.py` L288. Change:

```python
            _register_article_concepts(article_dir, list(prior_entry.feeds_concepts))
            continue
```

to (do not commit — this is a one-shot canary):

```python
            # canary: simulate forgetting to register skipped articles
            _register_article_concepts(article_dir, [])
            continue
```

Re-run: `python3 -m unittest tests.test_wiki_compile_reverse_index -v`

Expected: FAIL with `"art_a not in sources"`. This confirms the test catches the exact regression class.

Revert: `git checkout quant_llm_wiki/wiki/compile.py`

Re-run: PASS.

- [ ] **Step 4: Run the broader compile suite**

Run: `python3 -m unittest tests.test_wiki_compile tests.test_wiki_compile_reverse_index -v`

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add tests/test_wiki_compile_reverse_index.py
git commit -m "test(wiki/compile): lock reverse-index multi-source contract

Regression test for 39e08c5: in an incremental compile, two articles
feeding the same concept must both reach recompile_concept exactly
once — even when one takes the content-hash skip branch and the other
takes the changed/re-assigned branch. End-to-end tests don't pin this
interleaving because recompile output is LLM-generated."
```

---

## Task 5: Create benchmark harness skeleton + synthetic KB builder

**Files:**
- Create: `scripts/benchmark_perf.py` (skeleton only this task — KB builder + arg parsing).
- Create: `benchmarks/.gitignore` and `benchmarks/README.md`.

Mocks, the harness loop, and JSON output all come in Task 6. Keep this task purely structural so the next one is a pure-content addition.

- [ ] **Step 1: Create `benchmarks/.gitignore`**

```
*.json
*.log
!README.md
```

- [ ] **Step 2: Create `benchmarks/README.md`**

```markdown
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
```

- [ ] **Step 3: Create `scripts/benchmark_perf.py` with KB builder only**

```python
#!/usr/bin/env python3
"""Benchmark harness for v0.4.3 perf wins. See benchmarks/README.md."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

SCALES = {
    "small":  {"articles": 20,  "concepts": 10,  "feeds": 3},
    "medium": {"articles": 100, "concepts": 40,  "feeds": 4},
    "large":  {"articles": 500, "concepts": 100, "feeds": 5},
}


def build_synthetic_kb(root: Path, n_articles: int, n_concepts: int, feeds_per_article: int) -> None:
    """Lay out a deterministic KB at `root` ready for compile_wiki."""
    articles_root = root / "articles"
    articles_root.mkdir(parents=True, exist_ok=True)
    for i in range(n_articles):
        ad = articles_root / f"a{i:04d}"
        ad.mkdir()
        body_topic_id = i % max(n_concepts, 1)
        (ad / "article.md").write_text(
            f"---\ntitle: Article {i}\ncontent_type: paper\nmain_topic: topic_{body_topic_id:04d}\n---\n"
            f"body for article {i} about topic {body_topic_id}.\n",
            encoding="utf-8",
        )

    wiki_root = root / "wiki"
    (wiki_root / "concepts").mkdir(parents=True, exist_ok=True)
    for j in range(n_concepts):
        slug = f"topic_{j:04d}"
        (wiki_root / "concepts" / f"{slug}.md").write_text(
            f"---\ntitle: Topic {j}\nslug: {slug}\nstatus: stable\naliases: []\nrelated_concepts: []\n"
            f"sources: []\ncontent_types: [paper]\nlast_compiled: 2026-01-01\ncompile_version: 0\n"
            f"source_basenames: []\n---\nDefinition for topic {j}.\n",
            encoding="utf-8",
        )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--scale", choices=list(SCALES), default="medium")
    p.add_argument("--trials", type=int, default=3)
    p.add_argument("--out", type=Path, default=Path("benchmarks"))
    p.add_argument("--label", type=str, default=None,
                   help="Free-form label embedded in the JSON record (e.g. 'v0.4.3-HEAD').")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    scale = SCALES[args.scale]
    print(f"[benchmark] scale={args.scale} {scale}", file=sys.stderr)
    # TODO Task 6: run trials, capture perf lines, write JSON.
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Smoke-test the skeleton**

Run:

```bash
chmod +x scripts/benchmark_perf.py
python3 scripts/benchmark_perf.py --scale small
```

Expected: prints `[benchmark] scale=small {'articles': 20, 'concepts': 10, 'feeds': 3}` to stderr and exits 0.

Also verify the KB builder works standalone with a quick check:

```bash
python3 -c "
from pathlib import Path
import tempfile, sys
sys.path.insert(0, 'scripts')
from benchmark_perf import build_synthetic_kb
with tempfile.TemporaryDirectory() as tmp:
    build_synthetic_kb(Path(tmp), 5, 3, 2)
    print(sorted(p.name for p in (Path(tmp) / 'articles').iterdir()))
    print(sorted(p.name for p in (Path(tmp) / 'wiki' / 'concepts').iterdir()))
"
```

Expected: 5 article dirs, 3 concept files.

- [ ] **Step 5: Commit**

```bash
git add scripts/benchmark_perf.py benchmarks/.gitignore benchmarks/README.md
git commit -m "perf(bench): scaffold benchmark_perf.py + synthetic KB builder

Skeleton with arg parsing and a deterministic KB builder. Trials,
mocks, JSON output land in follow-up commits."
```

---

## Task 6: Wire the harness — mock LLM, run compile + brainstorm, capture perf lines

**Files:**
- Modify: `scripts/benchmark_perf.py` (everything below the `# TODO Task 6` marker).
- Create: `tests/test_benchmark_perf.py`.

- [ ] **Step 1: Write a small integration test that runs the harness end-to-end**

Create `tests/test_benchmark_perf.py`:

```python
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


class BenchmarkPerfSmokeTest(unittest.TestCase):
    def test_small_scale_one_trial_writes_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            proc = subprocess.run(
                [sys.executable, "scripts/benchmark_perf.py",
                 "--scale", "small", "--trials", "1",
                 "--out", str(out_dir), "--label", "smoke"],
                cwd=REPO_ROOT,
                capture_output=True, text=True,
                env={**os.environ, "QLW_PERF_DEBUG": "1"},
                timeout=60,
            )
            self.assertEqual(proc.returncode, 0, msg=f"stderr:\n{proc.stderr}")
            json_files = list(out_dir.glob("*.json"))
            self.assertEqual(len(json_files), 1, f"got {json_files}")
            rec = json.loads(json_files[0].read_text())
            self.assertEqual(rec["label"], "smoke")
            self.assertEqual(rec["scale"], "small")
            self.assertEqual(len(rec["trials"]), 1)
            t0 = rec["trials"][0]
            self.assertIn("compile_wiki", t0)
            self.assertIn("retrieve_blocks", t0)
            self.assertGreaterEqual(t0["compile_wiki"]["assign_ms"], 0.0)
            self.assertGreaterEqual(t0["compile_wiki"]["recompile_ms"], 0.0)
            self.assertGreaterEqual(t0["retrieve_blocks"]["total_ms"], 0.0)
            # Harness-observed call count (the v0.4.3 dedup invariant)
            self.assertEqual(t0["retrieve_blocks"]["concept_retrievals_observed"], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_benchmark_perf -v`

Expected: FAIL — no JSON is written yet (harness body is a stub).

- [ ] **Step 3: Implement the harness body**

Replace the body of `main()` in `scripts/benchmark_perf.py` (from `# TODO Task 6` onward) with:

```python
def _run_trial(scale: dict) -> dict:
    """Run one compile + brainstorm pair, return parsed perf timings."""
    import io
    import unittest.mock
    from contextlib import redirect_stderr

    # Lazy imports so --help works without the repo on PYTHONPATH
    from quant_llm_wiki.wiki import compile as compile_mod
    from quant_llm_wiki.query import brainstorm as brainstorm_mod
    from quant_llm_wiki.shared import KnowledgeNote
    # Adjust these two imports if AssignmentResult / RecompileResult live elsewhere
    from quant_llm_wiki.wiki.types import AssignmentResult, RecompileResult

    with tempfile.TemporaryDirectory() as tmp:
        kb_root = Path(tmp)
        build_synthetic_kb(kb_root, scale["articles"], scale["concepts"], scale["feeds"])

        # Mock LLM: assignment picks `feeds` existing concepts deterministically per article.
        def fake_assign(*, article_frontmatter, index_text, schema_text=None):
            topic = article_frontmatter.get("main_topic", "topic_0000")
            base = int(topic.split("_")[-1])
            slugs = [f"topic_{(base + k) % scale['concepts']:04d}" for k in range(scale["feeds"])]
            return AssignmentResult(existing_concepts=slugs, proposed_new_concepts=[], error=None)

        def fake_recompile(*, concept_slug, concept_title, source_articles, schema_text=None):
            return RecompileResult(
                synthesis=f"s for {concept_slug}",
                definition=f"d for {concept_slug}",
                related_concepts=[], key_idea_blocks=[], variants=[],
                common_combinations=[], transfer_targets=[],
                failure_modes=[], open_questions=[], error=None,
            )

        # Mock concept retrieval: return scale["feeds"] deterministic dicts.
        # The harness owns the call counter — we observe the v0.4.2→v0.4.3
        # dedup invariant externally instead of relying on an in-code log
        # field that could go stale or lie after a refactor.
        retrieve_call_count = [0]

        def fake_retrieve_concepts(query, top_k=None, vector_store_dir=None, wiki_dir=None):
            retrieve_call_count[0] += 1
            n = min(top_k or 5, scale["concepts"])
            return [
                {
                    "slug": f"topic_{k:04d}",
                    "title": f"Topic {k}",
                    "body_text": f"body for topic {k}",
                    "sources": [],
                }
                for k in range(n)
            ]

        buf_compile = io.StringIO()
        buf_query = io.StringIO()

        with unittest.mock.patch.object(compile_mod, "assign_concepts", side_effect=fake_assign), \
             unittest.mock.patch.object(compile_mod, "recompile_concept", side_effect=fake_recompile):
            t_compile = time.perf_counter()
            with redirect_stderr(buf_compile):
                compile_mod.compile_wiki(
                    kb_root=kb_root,
                    source_dirs=["articles"],
                    mode="full",
                    dry_run=False,
                )
            wall_compile_ms = (time.perf_counter() - t_compile) * 1000.0

        # Brainstorm: drive retrieve_blocks with the wiki we just compiled.
        note = KnowledgeNote(
            article_dir=kb_root / "articles" / "a0000" / "article.md",
            source_dir="articles",
            frontmatter={"title": "a0", "content_type": "paper"},
            body="hello",
        )
        with unittest.mock.patch.object(
                brainstorm_mod, "_retrieve_concept_articles",
                side_effect=fake_retrieve_concepts), \
             unittest.mock.patch.object(
                brainstorm_mod, "_wiki_is_healthy_for_query", return_value=True):
            t_query = time.perf_counter()
            with redirect_stderr(buf_query):
                brainstorm_mod.retrieve_blocks(
                    [note], "any query", top_k=5,
                    command="brainstorm", retrieval_mode="keyword",
                    kb_root=kb_root,
                )
            wall_query_ms = (time.perf_counter() - t_query) * 1000.0

    rb = _parse_event(buf_query.getvalue(), "retrieve_blocks", wall_ms=wall_query_ms)
    rb["concept_retrievals_observed"] = retrieve_call_count[0]
    return {
        "compile_wiki": _parse_event(buf_compile.getvalue(), "compile_wiki",
                                     wall_ms=wall_compile_ms),
        "retrieve_blocks": rb,
        "_retrieve_concept_articles": _parse_event(buf_query.getvalue(),
                                                   "_retrieve_concept_articles",
                                                   default={"calls": 0}),
    }


def _parse_event(stderr: str, event: str, wall_ms: float | None = None, default: dict | None = None) -> dict:
    """Pull the named [qlw-perf] event from stderr; return numeric-cast fields."""
    import re
    line_re = re.compile(rf"^\[qlw-perf\] {re.escape(event)}: (.+)$")
    out = {}
    calls = 0
    for line in stderr.splitlines():
        m = line_re.match(line)
        if not m:
            continue
        calls += 1
        for kv in m.group(1).split():
            if "=" not in kv:
                continue
            k, v = kv.split("=", 1)
            try:
                out[k] = float(v) if "." in v else int(v)
            except ValueError:
                out[k] = v
    if calls == 0 and default is not None:
        return default
    if calls > 1:
        out["calls"] = calls
    else:
        out["calls"] = calls
    if wall_ms is not None:
        out["wall_ms"] = wall_ms
    return out


def main() -> int:
    args = parse_args()
    scale_cfg = SCALES[args.scale]
    args.out.mkdir(parents=True, exist_ok=True)
    trials = []
    for i in range(args.trials):
        print(f"[benchmark] trial {i + 1}/{args.trials}", file=sys.stderr)
        trials.append(_run_trial(scale_cfg))
    record = {
        "label": args.label or "unlabeled",
        "scale": args.scale,
        "scale_cfg": scale_cfg,
        "trials": trials,
        "host": os.uname().nodename if hasattr(os, "uname") else "unknown",
        "python": sys.version.split()[0],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe_label = (args.label or "unlabeled").replace("/", "_").replace(" ", "_")
    out_path = args.out / f"{stamp}-{args.scale}-{safe_label}.json"
    out_path.write_text(json.dumps(record, indent=2))
    print(f"[benchmark] wrote {out_path}", file=sys.stderr)
    return 0
```

> Note `time` is already imported at the top of the file from Task 5; if not, add `import time`.

- [ ] **Step 4: Run the integration test**

Run: `python3 -m unittest tests.test_benchmark_perf -v`

Expected: PASS — one JSON record written, all required keys present, all timings ≥ 0.

If `AssignmentResult` / `RecompileResult` import fails, grep for the actual class location and fix the import in both `_run_trial` and `tests/test_perf_instrumentation.py`. If `KnowledgeNote` lives somewhere other than `quant_llm_wiki.shared`, adjust similarly.

- [ ] **Step 5: Run the full test suite to confirm nothing regressed**

Run: `python3 -m unittest discover -s tests -p 'test_*.py'`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/benchmark_perf.py tests/test_benchmark_perf.py
git commit -m "perf(bench): wire harness — mock LLM, drive compile+brainstorm, emit JSON

Each trial runs compile_wiki + retrieve_blocks against a synthetic KB
with deterministic LLM mocks, parses the [qlw-perf] lines, and writes
one JSON record per invocation under benchmarks/."
```

---

## Task 7: Capture the v0.4.3 baseline

**Files:**
- None modified or created in source. Produces local `benchmarks/*.json` files (gitignored).

- [ ] **Step 1: Confirm you're on a clean v0.4.3 working tree**

Run:

```bash
git status
git log --oneline -1
```

Expected: clean tree, HEAD at or after `ad1ebf7` (v0.4.3 release). If there are uncommitted instrumentation changes from Tasks 1–6, those are fine — they're additive and only fire under `QLW_PERF_DEBUG=1`.

- [ ] **Step 2: Run benchmark at small + medium scale**

```bash
python3 scripts/benchmark_perf.py --scale small  --trials 3 --label "v0.4.3-HEAD"
python3 scripts/benchmark_perf.py --scale medium --trials 3 --label "v0.4.3-HEAD"
```

Expected: two JSON files under `benchmarks/`. Each prints `[benchmark] wrote …`.

- [ ] **Step 3: (Optional) Run at large scale**

```bash
python3 scripts/benchmark_perf.py --scale large --trials 3 --label "v0.4.3-HEAD"
```

Expected: completes in roughly under 60s. If it's painfully slow, that's signal in itself — note the wall time and continue; large-scale is for the "does it stay linear?" plot, not a blocker.

- [ ] **Step 4: Sanity-check the records**

```bash
python3 -c "
import json, glob
for path in sorted(glob.glob('benchmarks/*v0.4.3-HEAD.json')):
    rec = json.loads(open(path).read())
    print(path, rec['scale'])
    for i, t in enumerate(rec['trials']):
        c = t['compile_wiki']; r = t['retrieve_blocks']
        print(f'  trial {i}: compile assign_ms={c[\"assign_ms\"]:.2f} recompile_ms={c[\"recompile_ms\"]:.2f}  query total_ms={r[\"total_ms\"]:.2f} retrievals_observed={r[\"concept_retrievals_observed\"]}')
"
```

Confirm `concept_retrievals_observed == 1` on every trial (the v0.4.3 dedup invariant, counted by the harness mock — not by an in-code log). If it's 2 in v0.4.3, either the dedup regressed or the harness mocked the wrong function; the spy test in `tests/test_brainstorm_with_wiki.py` will independently catch the former.

- [ ] **Step 5: No commit**

The raw JSON is gitignored. Move to Task 8.

---

## Task 8: Capture the v0.4.2 baseline via worktree + backported instrumentation

**Files:**
- None permanent. A throwaway worktree at `../knowledge-v042-bench` gets the instrumentation patches applied locally; nothing is committed there.

- [ ] **Step 1: Create the worktree at v0.4.2**

```bash
git worktree add ../knowledge-v042-bench v0.4.2
cd ../knowledge-v042-bench
git log --oneline -1
```

Expected: HEAD at `c1a2c8a` (v0.4.2 release).

- [ ] **Step 2: Apply the instrumentation diff from HEAD onto v0.4.2**

Generate a patch of just the instrumentation commits from the main checkout, then apply it. From the v0.4.2 worktree:

```bash
git -C /home/ubuntu/.project/knowledge format-patch v0.4.3..HEAD -- \
    quant_llm_wiki/query/brainstorm.py \
    quant_llm_wiki/wiki/compile.py \
    scripts/benchmark_perf.py \
    benchmarks/ \
    --stdout > /tmp/perf-bench.patch
git apply --3way /tmp/perf-bench.patch || git apply --reject /tmp/perf-bench.patch
```

If `git apply` rejects hunks (likely — v0.4.2 source diverges from v0.4.3 around the brainstorm changes), inspect the `.rej` files and hand-apply just the instrumentation pieces (the `_emit_perf` helper + the three wrapping blocks + the entire `scripts/benchmark_perf.py` file). The instrumentation is read-only and additive; it does not depend on any v0.4.3 logic change.

> **Important:** do **not** apply the *behavior* changes from v0.4.3 (the dedup wrapper, the reverse-index lookup). We want to measure v0.4.2's actual behavior. If the patch tries to introduce `_retrieve_concepts_and_blocks` or `concept_to_articles`, drop those hunks. The reverse-index code in particular must be absent so we measure the O(S·A·K) scan.

- [ ] **Step 3: Sanity-check that v0.4.2 still has the slow paths**

```bash
grep -n "_retrieve_concept_articles" quant_llm_wiki/query/brainstorm.py | head
grep -n "concept_to_articles\|article_to_concepts" quant_llm_wiki/wiki/compile.py | head
```

Expected: brainstorm calls `_retrieve_concept_articles` **twice** in `retrieve_blocks` (once inside `_concepts_to_blocks`, once for the exclusion paths); compile.py has `article_to_concepts` but no `concept_to_articles` reverse index. If these match v0.4.3's state, the patch leaked behavior changes — revert and reapply more carefully.

- [ ] **Step 4: Run the same benchmarks**

```bash
python3 scripts/benchmark_perf.py --scale small  --trials 3 --label "v0.4.2-tagged"
python3 scripts/benchmark_perf.py --scale medium --trials 3 --label "v0.4.2-tagged"
python3 scripts/benchmark_perf.py --scale large  --trials 3 --label "v0.4.2-tagged"
```

Expected: 3 JSON records. For `retrieve_blocks`, `concept_retrievals_observed` should now be **2** — the harness mock observes that v0.4.2 calls `_retrieve_concept_articles` twice from `retrieve_blocks`. For `compile_wiki`, `recompile_ms` should grow super-linearly with article count vs v0.4.3's records (because v0.4.2 lacks the reverse index and re-scans `articles` per affected slug).

- [ ] **Step 5: Copy the JSONs back to the main checkout**

```bash
cp benchmarks/*v0.4.2-tagged.json /home/ubuntu/.project/knowledge/benchmarks/
```

- [ ] **Step 6: Verify and dispose of the worktree**

```bash
cd /home/ubuntu/.project/knowledge
ls benchmarks/*v0.4.2-tagged.json
git worktree remove ../knowledge-v042-bench --force
```

Expected: 3 JSON files visible in the main checkout's `benchmarks/`. Worktree is gone.

- [ ] **Step 7: No commit**

JSON is gitignored. Move to Task 9.

---

## Task 9: Write the validation report

**Files:**
- Create: `docs/superpowers/specs/2026-05-17-perf-validation-report.md`.

This is the durable artifact. The raw JSON evaporates; this stays.

- [ ] **Step 1: Compute the comparison**

Run a one-liner to extract medians (already have the JSONs from Tasks 7 & 8):

```bash
python3 << 'EOF'
import json, glob, statistics

def med(xs): return statistics.median(xs) if xs else float('nan')

groups = {}
for p in sorted(glob.glob('benchmarks/*.json')):
    r = json.loads(open(p).read())
    key = (r['label'], r['scale'])
    bag = groups.setdefault(key, {'assign': [], 'recompile': [], 'query_total': [], 'concept_retrievals': []})
    for t in r['trials']:
        bag['assign'].append(t['compile_wiki']['assign_ms'])
        bag['recompile'].append(t['compile_wiki']['recompile_ms'])
        bag['query_total'].append(t['retrieve_blocks']['total_ms'])
        bag['concept_retrievals'].append(t['retrieve_blocks']['concept_retrievals'])

print(f"{'label':<20}{'scale':<10}{'assign_ms':>12}{'recompile_ms':>14}{'query_ms':>12}{'concept_retr':>14}")
for (label, scale), bag in sorted(groups.items()):
    print(f"{label:<20}{scale:<10}{med(bag['assign']):>12.2f}{med(bag['recompile']):>14.2f}{med(bag['query_total']):>12.2f}{med(bag['concept_retrievals']):>14.1f}")
EOF
```

Capture the output — these numbers go into the report.

- [ ] **Step 2: Write `docs/superpowers/specs/2026-05-17-perf-validation-report.md`**

Use this template, filling in numbers from Step 1 (replace `<…>` placeholders only — keep all surrounding prose):

```markdown
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
| v0.4.2-tagged | small  |         <fill>    |              <fill>  |        <fill>  |                       <2.0> |
| v0.4.3-HEAD   | small  |         <fill>    |              <fill>  |        <fill>  |                       <1.0> |
| v0.4.2-tagged | medium |         <fill>    |              <fill>  |        <fill>  |                       <2.0> |
| v0.4.3-HEAD   | medium |         <fill>    |              <fill>  |        <fill>  |                       <1.0> |
| v0.4.2-tagged | large  |         <fill>    |              <fill>  |        <fill>  |                       <2.0> |
| v0.4.3-HEAD   | large  |         <fill>    |              <fill>  |        <fill>  |                       <1.0> |

¹ Counted by the harness mock around `_retrieve_concept_articles`, not by an in-code log field. The runtime call-count invariant is locked by `tests/test_brainstorm_with_wiki.py` (the spy test asserting `_retrieve_concept_articles.call_count == 1`).

Host: `<uname -n>`, Python `<version>`, timestamp `<…>`.

## Findings

**Brainstorm dedup (ca902ff).** Harness-observed `_retrieve_concept_articles` calls drop from 2 → 1 across all scales (the structural invariant the v0.4.3 spy test already locks in at the unit level). `query.total_ms` improves by **<X>%** at medium scale and **<Y>%** at large scale. The absolute win is small here because the mock retrieval is near-zero cost; in production with real Chroma the delta will scale with the cost of one full vector lookup (~tens to low-hundreds of ms).

**Compile reverse index (39e08c5).** `recompile_ms` is the key cell. v0.4.2 scales <quasi-linearly | super-linearly> with article count (small → medium → large: <…> → <…> → <…> ms). v0.4.3 stays <…>. At the large scale the win is **<Z>%** (<… ms saved out of … ms>).

**Assign phase is unchanged.** Both versions are within noise on `assign_ms` across all scales, confirming v0.4.3 only touched the recompile-side data path.

## Out of scope (still on the followup list)

- `_build_index_text` hoist — would mostly reduce `assign_ms` at large scale; the design doc flagged the semantic risk. Worth measuring once a decision is made.
- Query-time `lint_wiki` cost — not exercised in this harness because `_wiki_is_healthy_for_query` is mocked to `True`. A separate measurement using real lint reads at varied wiki sizes is needed before the design change.

## How to reproduce

    QLW_PERF_DEBUG=1 python3 scripts/benchmark_perf.py --scale medium --trials 3 --label myrun

Raw JSON lands in `benchmarks/` (gitignored). See `benchmarks/README.md`.
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-05-17-perf-validation-report.md
git commit -m "docs(specs): v0.4.3 perf validation — measurement report

Numbers from scripts/benchmark_perf.py at small/medium/large scales,
comparing v0.4.2-tagged (worktree, instrumentation backported) vs
v0.4.3-HEAD. Confirms the brainstorm dedup invariant and the compile
reverse-index speedup."
```

---

## Task 10: Final verification

**Files:** none.

- [ ] **Step 1: Run the full test suite**

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Expected: all green, including the three new instrumentation tests + the benchmark integration test.

- [ ] **Step 2: Run robustness suite if it exists**

```bash
python3 -m unittest discover -s tests/robustness -p 'test_*.py' -v
```

Expected: green.

- [ ] **Step 3: Confirm zero-cost when `QLW_PERF_DEBUG` is unset**

```bash
python3 -c "
import os, sys
os.environ.pop('QLW_PERF_DEBUG', None)
from quant_llm_wiki.query.brainstorm import _emit_perf
import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stderr(buf):
    for _ in range(10000):
        _emit_perf('x', a=1, b=2.5, c='hi')
assert buf.getvalue() == '', 'leaked output when QLW_PERF_DEBUG unset'
print('ok')
"
```

Expected: prints `ok`. The instrumentation cannot leak to stderr when the env var is unset.

- [ ] **Step 4: Confirm the report renders**

```bash
ls -la docs/superpowers/specs/2026-05-17-perf-validation-report.md
head -40 docs/superpowers/specs/2026-05-17-perf-validation-report.md
```

Expected: file exists, header + first table row are populated with real numbers (no remaining `<fill>` placeholders).

- [ ] **Step 5: Tidy**

```bash
git status
```

Expected: clean working tree (or only `benchmarks/*.json` showing as untracked, which is correct — they're gitignored).

---

## Spec coverage check

| Out-of-scope item in `2026-05-17-brainstorm-compile-perf-design.md` | Addressed here? |
|---|---|
| Validate the two v0.4.3 wins with real data | ✅ Tasks 7–9 |
| Lock the reverse-index multi-source contract beyond end-to-end | ✅ Task 4 (skip-branch + changed-branch interleaving) |
| `_build_index_text` hoist (compile.py:278/L291) | ❌ Explicitly out of scope; report notes it remains on the followup list |
| Query-time `lint_wiki` → stale-report design change | ❌ Explicitly out of scope; report notes the harness mocks `_wiki_is_healthy_for_query`, so a separate measurement is needed before that design lands |

Both deferrals are intentional — both are design changes, and this plan is measurement-only.

## Risks & dependencies

| Risk | Mitigation |
|---|---|
| `AssignmentResult` / `RecompileResult` import path drift | Tasks 3, 4, and 6 explicitly tell the implementer to grep and fix |
| Cross-module import `wiki/compile → query/brainstorm` for `_emit_perf` is awkward | Inline note in Task 3 Step 3 — promote to `quant_llm_wiki/shared_perf.py` on first refactor |
| `git apply` rejects in Task 8 | Step 2 instructs hand-applying the instrumentation hunks; behavior hunks must stay out |
| Mocked LLM = numbers are not production latency | Explicit in the report's "Method" section and in `benchmarks/README.md`; the report claims a structural win, not a wall-clock SLO |
| Synthetic KB doesn't exercise some corner of compile (e.g. proposed-new-concepts path) | Acceptable for this round — `proposed_new_concepts=[]` in the mock keeps the assign loop on its main branch, which is what the reverse-index change touched. Task 4's regression test covers the skip+changed interleaving on the existing-concepts branch separately |
| `article_to_concepts` forward map no longer exists in HEAD | The `39e08c5` implementation eliminated the forward map entirely rather than keeping it in lockstep with the reverse index (despite what the earlier design doc implied). Current code's single source of truth is `concept_to_articles` (compile.py:260). Tasks 3 and 4 do not reintroduce a forward map — if a future change adds one, do not silently maintain lockstep; pick one as authoritative and derive the other on read |

