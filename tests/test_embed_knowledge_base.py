import tempfile
import unittest
from pathlib import Path

import embed_knowledge_base as mod
import kb_shared


class EmbedKnowledgeBaseTests(unittest.TestCase):
    def test_make_block_id_includes_source_path_uniqueness(self) -> None:
        note_a = kb_shared.KnowledgeNote(
            article_dir=Path("articles/reviewed/same"),
            source_dir="reviewed",
            frontmatter={"title": "A"},
            body="",
        )
        note_b = kb_shared.KnowledgeNote(
            article_dir=Path("articles/high-value/same"),
            source_dir="high-value",
            frontmatter={"title": "B"},
            body="",
        )
        block_a = kb_shared.KnowledgeBlock(note=note_a, block_type="summary", text="x", score=0.0)
        block_b = kb_shared.KnowledgeBlock(note=note_b, block_type="summary", text="x", score=0.0)
        kb_root = Path("articles").parent
        self.assertNotEqual(mod.make_block_id(kb_root, block_a, 0), mod.make_block_id(kb_root, block_b, 0))

    def test_manifest_key_uses_relative_path(self) -> None:
        kb_root = Path("D:/kb")
        note = kb_shared.KnowledgeNote(
            article_dir=kb_root / "articles" / "reviewed" / "note_a",
            source_dir="reviewed",
            frontmatter={"title": "A"},
            body="",
        )
        self.assertEqual(mod.manifest_key(kb_root, note), "articles/reviewed/note_a")

    def test_block_metadata_is_minimal_and_stable(self) -> None:
        note = kb_shared.KnowledgeNote(
            article_dir=Path("a"),
            source_dir="reviewed",
            frontmatter={
                "content_type": "allocation",
                "brainstorm_value": "high",
                "market": ["a_share"],
                "strategy_type": ["allocation_rotation"],
            },
            body="",
        )
        block = kb_shared.KnowledgeBlock(note=note, block_type="idea_blocks", text="内容", score=0.0)
        metadata = mod.block_metadata(block)
        self.assertEqual(set(metadata.keys()), {"article_dir", "source_dir", "content_type", "brainstorm_value", "block_type"})

    def test_load_manifest_resets_on_schema_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "index_manifest.json"
            path.write_text('{"schema_version":"old","articles":{"x":{}}}', encoding="utf-8")
            manifest = mod.load_manifest(path)
            self.assertEqual(manifest["schema_version"], mod.INDEX_SCHEMA_VERSION)
            self.assertEqual(manifest["articles"], {})


if __name__ == "__main__":
    unittest.main()
