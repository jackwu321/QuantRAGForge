import tempfile
import unittest
from pathlib import Path

import wiki_index
import wiki_seed


class WikiIndexTests(unittest.TestCase):
    def test_generate_index_groups_concepts_by_content_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            wiki_seed.bootstrap_wiki(wiki_dir)
            text = wiki_index.generate_index(wiki_dir)
            self.assertIn("# Knowledge Base Index", text)
            self.assertIn("## Stable Concepts", text)
            self.assertIn("[[concepts/momentum-strategies]]", text)

    def test_generate_index_lists_proposed_concepts_separately(self) -> None:
        from wiki_schemas import ConceptArticle, serialize_concept
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            (wiki_dir / "concepts").mkdir(parents=True)
            (wiki_dir / "sources").mkdir(parents=True)
            proposed = ConceptArticle(
                title="Macro Momentum", slug="macro-momentum", aliases=[],
                status="proposed", related_concepts=[], sources=[],
                content_types=["methodology"], last_compiled="2026-04-28",
                compile_version=0, synthesis="d", definition="x",
                key_idea_blocks=[], variants=[], common_combinations=[],
                transfer_targets=[], failure_modes=[], open_questions=[],
                source_basenames=[],
            )
            (wiki_dir / "concepts" / "macro-momentum.md").write_text(
                serialize_concept(proposed), encoding="utf-8"
            )
            text = wiki_index.generate_index(wiki_dir)
            self.assertIn("## Proposed Concepts", text)
            self.assertIn("[[concepts/macro-momentum]]", text)

    def test_write_index_creates_file_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            wiki_seed.bootstrap_wiki(wiki_dir)
            path = wiki_index.write_index(wiki_dir)
            self.assertTrue(path.exists())
            self.assertEqual(path, wiki_dir / "INDEX.md")
            content = path.read_text(encoding="utf-8")
            self.assertIn("# Knowledge Base Index", content)


if __name__ == "__main__":
    unittest.main()
