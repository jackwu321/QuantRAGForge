# Wiki LLM KB Integration — Manual Acceptance Checklist

Run after implementation is complete and `python3 -m unittest discover -s tests -p 'test_*.py'` passes (the pre-existing `test_build_catalog` error is unrelated). Each item produces a real artifact you can inspect.

## Setup
- [ ] `.venv/bin/pip install -r requirements.txt` succeeds (PyYAML, trafilatura, readability-lxml, pypdf, pdfplumber installed)
- [ ] `python3 -m unittest discover -s tests -p 'test_*.py' -v` — only the pre-existing `test_build_catalog` error remains

## 1. Bootstrap wiki (no LLM calls)
- [ ] Run: `python3 -c "from wiki_seed import bootstrap_wiki; from kb_shared import WIKI_DIR; bootstrap_wiki(WIKI_DIR)"`
- [ ] Verify: `ls wiki/concepts/` shows 7 .md files
- [ ] Verify: each stub has `status: stable`, `compile_version: 0`, empty `sources:`

## 2. Compile wiki over existing corpus
- [ ] Run: `python3 -c "import wiki_compile; r = wiki_compile.compile_wiki(); print(r.summary()); print(r.lint_summary)"`
- [ ] Verify: ≥ 5 of 7 seed concepts have non-empty `## Synthesis` sections
- [ ] Verify: ≥ 80% of `articles/{reviewed,high-value}/` articles produce `wiki/sources/<basename>.md`
- [ ] Verify: `wiki/state.json` exists with non-empty `sources` and `concepts` sections
- [ ] Verify: `wiki/lint_report.json` exists; opening it shows `issues` array
- [ ] Verify: each new concept's bullets in `## Key Idea Blocks` etc. end with `[<source_basename>]`
- [ ] Verify: `INDEX.md` lists concepts grouped by content_type

## 3. Idempotency proof (X-post-aligned)
- [ ] Run `compile_wiki` again with no article changes
- [ ] Verify: `report.skipped` equals article count; `concepts_assigned` and `concepts_recompiled` are 0
- [ ] Edit any article (add a sentence) — content hash changes
- [ ] Run `compile_wiki` again
- [ ] Verify: only the affected concept(s) recompile, others are skipped

## 4. New web URL ingest
- [ ] Pick a non-WeChat blog post about momentum (arxiv abstract page, quant blog, etc.)
- [ ] Run: `python3 ingest_source.py --url "<URL>"`
- [ ] Verify: `articles/raw/<dir>/article.md` with `source_type: web` in frontmatter
- [ ] Run agent flow: `enrich_articles → set_article_status → sync_articles → compile_wiki`
- [ ] Verify: the new article is in `momentum-strategies.md`'s `sources:` list

## 5. PDF ingest
- [ ] Pick a broker report PDF (or `tests/fixtures/sample.pdf`)
- [ ] Run: `python3 ingest_source.py --pdf-file <path>`
- [ ] Verify: `articles/raw/<dir>/article.md` with `source_type: pdf`
- [ ] Verify: `has_code` and `has_math` set appropriately
- [ ] Verify: `source.pdf` preserved alongside

## 6. Brainstorm uses concept memory first
- [ ] Run: `python3 brainstorm_from_kb.py brainstorm --query "How to combine momentum factor with regime detection for ETF rotation?"`
- [ ] Verify the retrieved context labels include `[Wiki Concept]` markers
- [ ] Verify ≥ 2 wiki concept articles cited in `Inspired By`
- [ ] Verify rethink layer still produces novelty + quality scores
- [ ] Compare token count to article-only retrieval — wiki version should be smaller per match

## 7. Wiki health audit
- [ ] Run: `python3 -c "from wiki_lint import lint_wiki; r = lint_wiki(); print(r.summary())"`
- [ ] Verify: with a clean corpus, output ends in "ok (0 issues)" or only `info`/`warning` items
- [ ] Manually corrupt `wiki/concepts/momentum-strategies.md` (drop the frontmatter) and re-run audit
- [ ] Verify: `error` severity issue surfaces; `ok_for_brainstorm()` returns False
- [ ] Restore the file

## 8. Anti-hallucination via lint
- [ ] Manually edit a concept article: add a bullet without an anchor, e.g. `- A bold claim with no citation`
- [ ] Run `audit_wiki` (or call `lint_wiki()` directly)
- [ ] Verify: `unsupported_bullets` warning surfaces with the offending bullet
- [ ] Run `compile_wiki` — concept gets recompiled and the LLM should re-emit the bullet *with* an anchor

## 9. Auto-stabilization vs. exception queue
- [ ] Ingest an outlier article (e.g. options volatility surface)
- [ ] Run compile_wiki
- [ ] If high-confidence: concept lands as `status: stable` and is used by brainstorm
- [ ] If low-confidence: concept lands as `status: proposed`; `list_concepts(status='proposed')` shows it
- [ ] Verify: brainstorm does NOT cite proposed concepts
- [ ] Use `set_concept_status(slug, status='stable', reason='...')` to override (only if needed)

## 10. Stale-source detection
- [ ] Edit an article that's already cited by a concept; do NOT run compile_wiki
- [ ] Run `audit_wiki`
- [ ] Verify: `stale_concepts` warning surfaces for the affected source
- [ ] Run `compile_wiki` — affected concepts recompile, warning clears on next audit

## 11. Hybrid memory: Markdown vs. state.json
- [ ] Inspect `wiki/concepts/momentum-strategies.md` — readable to a human in any text editor
- [ ] Inspect `wiki/state.json` — agent's substrate; numbers + hashes
- [ ] Confirm both round-trip: edit `state.json` (don't), edit a concept (do) — only the concept content goes through `compile_wiki`; `state.json` is regenerated
