import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import brainstorm_from_kb


class ConceptRetrievalLexicalFallbackTests(unittest.TestCase):
    def test_retrieve_concepts_lexical_finds_seed_match(self) -> None:
        from wiki_seed import bootstrap_wiki

        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            bootstrap_wiki(wiki_dir)
            # No Chroma store, so falls back to lexical
            with patch.object(brainstorm_from_kb, "WIKI_DIR", wiki_dir), \
                 patch.object(brainstorm_from_kb, "WIKI_STATE_PATH", wiki_dir / "state.json"), \
                 patch.object(brainstorm_from_kb, "VECTOR_STORE_DIR", Path(tmp) / "no-store"):
                concepts = brainstorm_from_kb._retrieve_concept_articles(
                    "How to combine momentum and regime detection?",
                    top_k=2,
                )
            self.assertGreater(len(concepts), 0)
            slugs = [c["slug"] for c in concepts]
            self.assertTrue(
                "momentum-strategies" in slugs or "regime-detection" in slugs,
                f"expected momentum/regime hits in {slugs}",
            )

    def test_retrieve_concepts_returns_empty_when_wiki_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(brainstorm_from_kb, "WIKI_DIR", Path(tmp) / "no-wiki"):
                concepts = brainstorm_from_kb._retrieve_concept_articles("query", top_k=3)
            self.assertEqual(concepts, [])

    def test_concepts_to_blocks_marks_wiki_concept(self) -> None:
        from wiki_seed import bootstrap_wiki
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            bootstrap_wiki(wiki_dir)
            with patch.object(brainstorm_from_kb, "WIKI_DIR", wiki_dir), \
                 patch.object(brainstorm_from_kb, "WIKI_STATE_PATH", wiki_dir / "state.json"), \
                 patch.object(brainstorm_from_kb, "VECTOR_STORE_DIR", Path(tmp) / "no-store"):
                blocks = brainstorm_from_kb._concepts_to_blocks("momentum risk", top_k=2)
            self.assertGreater(len(blocks), 0)
            self.assertEqual(blocks[0].block_type, "wiki_concept")


class FormatContextTests(unittest.TestCase):
    def test_format_context_distinguishes_wiki_from_article(self) -> None:
        from quant_llm_wiki.shared import KnowledgeBlock, KnowledgeNote
        wiki_block = KnowledgeBlock(
            note=KnowledgeNote(
                article_dir=Path("wiki/concepts/momentum.md"),
                source_dir="wiki_concepts",
                frontmatter={"title": "Momentum"},
                body="",
            ),
            block_type="wiki_concept", text="t", score=0.0,
        )
        article_block = KnowledgeBlock(
            note=KnowledgeNote(
                article_dir=Path("articles/reviewed/x"),
                source_dir="reviewed",
                frontmatter={"title": "X"},
                body="",
            ),
            block_type="idea_blocks", text="t", score=0.0,
        )
        ctx = brainstorm_from_kb.format_context([wiki_block, article_block])
        self.assertIn("[Wiki Concept]", ctx)
        self.assertIn("[Article]", ctx)


class StateScoreRerankTests(unittest.TestCase):
    def test_high_score_concept_outranks_low_score(self) -> None:
        """When state.json has both high-confidence and low-confidence concepts
        matching a query lexically, the high-confidence one should rank first."""
        import wiki_state
        from wiki_seed import bootstrap_wiki

        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            bootstrap_wiki(wiki_dir)
            state = wiki_state.WikiState()
            # Both seed concepts are present; assign very different scores
            state.concepts["momentum-strategies"] = wiki_state.ConceptEntry(
                status="stable", confidence=0.9, importance=0.8, freshness=0.95,
                source_count=8, last_compiled="2026-04-30",
                retrieval_hints=["momentum", "动量"],
            )
            state.concepts["risk-parity"] = wiki_state.ConceptEntry(
                status="stable", confidence=0.1, importance=0.1, freshness=0.1,
                source_count=1, last_compiled="2026-04-30",
                retrieval_hints=["momentum"],  # same hint, low score
            )
            wiki_state.save_wiki_state(state, wiki_dir / "state.json")

            with patch.object(brainstorm_from_kb, "WIKI_DIR", wiki_dir), \
                 patch.object(brainstorm_from_kb, "WIKI_STATE_PATH", wiki_dir / "state.json"), \
                 patch.object(brainstorm_from_kb, "VECTOR_STORE_DIR", Path(tmp) / "no-store"):
                concepts = brainstorm_from_kb._retrieve_concept_articles("momentum", top_k=2)
            slugs = [c["slug"] for c in concepts]
            # momentum-strategies should outrank risk-parity (despite both having "momentum" hint)
            if "momentum-strategies" in slugs and "risk-parity" in slugs:
                self.assertLess(slugs.index("momentum-strategies"), slugs.index("risk-parity"))


class BrainstormFlowTests(unittest.TestCase):
    def test_brainstorm_falls_back_to_pure_vector_when_wiki_empty(self) -> None:
        """When no wiki/concepts/ dir, _concepts_to_blocks returns []."""
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(brainstorm_from_kb, "WIKI_DIR", Path(tmp) / "no-wiki"):
                blocks = brainstorm_from_kb._concepts_to_blocks("q", top_k=3)
            self.assertEqual(blocks, [])


if __name__ == "__main__":
    unittest.main()
