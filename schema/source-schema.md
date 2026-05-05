# Source Summary Schema

Source summaries live at `wiki/sources/<article_basename>.md`.

Required frontmatter:

- `source_path`
- `title`
- `content_type`
- `brainstorm_value`
- `feeds_concepts`
- `ingested`
- `last_compiled`

Required sections:

- `One-line takeaway`
- `Idea Blocks`
- `Why it's in the KB`
- `Feeds concepts`

Rules:

- Source summaries are mechanically compiled from article frontmatter.
- Source summaries should not invent claims beyond the source article metadata.
- `feeds_concepts` must use concept slugs.
- Source links in concept pages use `[[source_basename]]`.
