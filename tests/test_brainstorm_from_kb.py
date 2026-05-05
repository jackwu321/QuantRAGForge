import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import brainstorm_from_kb as mod


class BrainstormFromKbTests(unittest.TestCase):
    def make_note(self, article_dir: str = "a", source_dir: str = "reviewed", **frontmatter):
        base_frontmatter = {
            "status": "reviewed",
            "title": "行业轮动模型",
            "summary": "讨论行业轮动与风险预算",
            "idea_blocks": ["行业轮动和风险预算结合"],
            "combination_hooks": [],
            "transfer_targets": [],
            "failure_modes": [],
        }
        base_frontmatter.update(frontmatter)
        return mod.KnowledgeNote(
            article_dir=Path(article_dir),
            source_dir=source_dir,
            frontmatter=base_frontmatter,
            body="## Main Content\n\n行业轮动可以和风险预算结合。\n",
        )

    def test_parse_frontmatter_value_json_array(self) -> None:
        self.assertEqual(mod.parse_frontmatter_value('["a", "b"]'), ["a", "b"])

    def test_parse_frontmatter_parses_arrays(self) -> None:
        markdown = "---\nstatus: reviewed\nstrategy_type: [\"allocation_rotation\", \"cross_sectional\"]\nsummary: test\n---\n\n## Main Content\n\n正文\n"
        frontmatter, body = mod.parse_frontmatter(markdown)
        self.assertEqual(frontmatter["status"], "reviewed")
        self.assertEqual(frontmatter["strategy_type"], ["allocation_rotation", "cross_sectional"])
        self.assertIn("Main Content", body)

    def test_effective_status_derives_from_directory(self) -> None:
        note = mod.KnowledgeNote(
            article_dir=Path("x"),
            source_dir="high-value",
            frontmatter={"status": "raw", "title": "t"},
            body="",
        )
        self.assertEqual(note.effective_status, "high_value")

    def test_apply_filters_uses_metadata(self) -> None:
        args = Namespace(
            content_type="allocation",
            market="a_share",
            asset_type=None,
            strategy_type="allocation_rotation",
            brainstorm_value="high",
        )
        notes = [
            self.make_note(
                article_dir="a",
                content_type="allocation",
                market=["a_share"],
                strategy_type=["allocation_rotation"],
                brainstorm_value="high",
                title="A",
            ),
            self.make_note(
                article_dir="b",
                content_type="strategy",
                market=["us_equity"],
                strategy_type=["factor_model"],
                brainstorm_value="medium",
                title="B",
            ),
        ]
        filtered = mod.apply_filters(notes, args)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].title, "A")

    def test_retrieve_blocks_prefers_idea_blocks(self) -> None:
        from unittest.mock import patch
        from pathlib import Path
        import tempfile
        note = self.make_note()
        # Isolate from any compiled wiki/ in the worktree — this test predates
        # the wiki layer and asserts on article-only retrieval.
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(mod, "WIKI_DIR", Path(tmp) / "no-wiki"):
                retrieved, mode, warning = mod.retrieve_blocks([note], "行业轮动 风险预算", 3, "brainstorm", "keyword")
        self.assertTrue(retrieved)
        self.assertEqual(retrieved[0].block_type, "idea_blocks")
        self.assertEqual(mode, "keyword")
        self.assertIsNone(warning)

    def test_hybrid_falls_back_to_keyword_on_vector_error(self) -> None:
        note = self.make_note()
        original = mod._vector_retrieve
        try:
            def raising(*args, **kwargs):
                raise RuntimeError("boom")
            mod._vector_retrieve = raising
            retrieved, mode, warning = mod.retrieve_blocks([note], "行业轮动 风险预算", 3, "brainstorm", "hybrid")
        finally:
            mod._vector_retrieve = original
        self.assertTrue(retrieved)
        self.assertEqual(mode, "keyword")
        self.assertIn("fell back to keyword", warning or "")

    def test_rrf_fusion_combines_keyword_and_vector(self) -> None:
        note = self.make_note()
        keyword_blocks = [
            mod.KnowledgeBlock(note=note, block_type="summary", text="行业轮动摘要", score=1.0),
            mod.KnowledgeBlock(note=note, block_type="idea_blocks", text="风险预算组合", score=0.9),
        ]
        vector_blocks = [
            mod.KnowledgeBlock(note=note, block_type="idea_blocks", text="风险预算组合", score=1.0),
            mod.KnowledgeBlock(note=note, block_type="transfer_targets", text="迁移到ETF", score=0.8),
        ]
        fused = mod._rrf_fusion(keyword_blocks, vector_blocks, 3)
        self.assertEqual(fused[0].text, "风险预算组合")
        self.assertEqual(len(fused), 3)

    def test_load_notes_from_reviewed_and_high_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reviewed_dir = root / "raw" / "note_a"
            high_value_dir = root / "raw" / "note_b"
            reviewed_dir.mkdir(parents=True)
            high_value_dir.mkdir(parents=True)
            reviewed_dir.joinpath("article.md").write_text(
                "---\nstatus: reviewed\ntitle: A\n---\n\n## Main Content\n\n内容\n",
                encoding="utf-8",
            )
            high_value_dir.joinpath("article.md").write_text(
                "---\nstatus: high_value\ntitle: B\n---\n\n## Main Content\n\n内容\n",
                encoding="utf-8",
            )
            notes = mod.load_notes(root, ["reviewed", "high-value"])
            self.assertEqual(len(notes), 2)
            self.assertEqual({note.title for note in notes}, {"A", "B"})


if __name__ == "__main__":
    unittest.main()
