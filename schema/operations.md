# Operations

## ingest

Ingest normalizes new material into `raw/` or compatible `articles/raw/` article directories. It preserves raw source artifacts when available, then produces `article.md` with frontmatter suitable for wiki compilation.

## query

Query reads `wiki/INDEX.md`, stable concept pages, and source summaries first. Article chunks and vector retrieval are supplements used for extra evidence or fallback when wiki memory is missing, unhealthy, or too sparse.

## lint

Lint verifies that wiki memory is safe to query. It checks parseability, source support, source freshness, orphaned concepts/sources, duplicate aliases, oversized concepts, and index health.

## compile

Compile is the LLM-maintenance operation that transforms source articles into source summaries, concept updates, `INDEX.md`, and `state.json`. Compile must preserve traceability from every concept claim back to sources.
