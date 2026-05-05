# Concept Page Schema

Concept pages live at `wiki/concepts/<slug>.md`.

Required frontmatter:

- `title`
- `slug`
- `aliases`
- `status`: `stable`, `proposed`, or `deprecated`
- `related_concepts`
- `sources`
- `content_types`
- `last_compiled`
- `compile_version`

Required sections:

- `Synthesis`
- `Definition`
- `Key Idea Blocks`
- `Variants & Implementations`
- `Common Combinations`
- `Transfer Targets`
- `Failure Modes`
- `Open Questions`
- `Sources`

Rules:

- Stable concepts are queryable.
- Proposed concepts are exception-queue memory and should not drive answers.
- Deprecated concepts stay on disk for traceability but are excluded from `INDEX.md`.
- Structured bullets must end with source anchors such as `[source_basename]`.
- Concept links use `[[concept-slug]]`.
