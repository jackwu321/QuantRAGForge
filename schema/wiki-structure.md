# Wiki Structure

The knowledge base has three durable layers:

- `raw/`: canonical incoming source material for new ingestion flows.
- `wiki/`: LLM-built Markdown memory used as the primary query layer.
- `schema/`: rules that tell the LLM and tools how the wiki is organized.

Existing `articles/raw/`, `articles/reviewed/`, and `articles/high-value/` paths remain supported for compatibility. Query and brainstorm should prefer `wiki/` memory before consulting article chunks or vector retrieval.

`wiki/` contains:

- `INDEX.md`: compact routing index for agents and humans.
- `state.json`: source hashes, concept state, scores, and retrieval hints.
- `lint_report.json`: latest health report.
- `concepts/<slug>.md`: stable, proposed, or deprecated concept pages.
- `sources/<article_basename>.md`: source summaries compiled from article frontmatter.
