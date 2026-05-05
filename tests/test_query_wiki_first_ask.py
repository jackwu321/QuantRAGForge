"""Step 4: ask mode must use wiki concepts first, like brainstorm.

This is a contract test on retrieve_blocks: when notes have absolute
article_dir paths and the wiki is healthy, wiki concepts surface even when
command='ask'.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import brainstorm_from_kb as mod
from kb_shared import KnowledgeNote
from wiki_seed import bootstrap_wiki


class WikiFirstAskTests(unittest.TestCase):
    def test_ask_mode_pulls_wiki_concepts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bootstrap_wiki(root / "wiki")
            note = KnowledgeNote(
                article_dir=(root / "raw" / "x").resolve(),
                source_dir="reviewed",
                frontmatter={"title": "X", "status": "reviewed"},
                body="ETF rotation under regime shifts.",
            )
            with patch.object(mod, "_concepts_to_blocks", return_value=[
                mod.KnowledgeBlock(
                    note=KnowledgeNote(
                        article_dir=root / "wiki" / "concepts" / "etf-rotation.md",
                        source_dir="wiki_concepts",
                        frontmatter={"title": "ETF Rotation"},
                        body="",
                    ),
                    block_type="wiki_concept",
                    text="ETF rotation block",
                    score=0.9,
                ),
            ]) as mock_concepts:
                blocks, _, _ = mod.retrieve_blocks(
                    [note],
                    "What is etf rotation?",
                    top_k=3,
                    command="ask",
                    retrieval_mode="hybrid",
                    kb_root=root,
                )
            mock_concepts.assert_called()
            self.assertTrue(any(b.block_type == "wiki_concept" for b in blocks))


if __name__ == "__main__":
    unittest.main()
