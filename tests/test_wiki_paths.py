import unittest
from pathlib import Path

import kb_shared


class WikiPathsTests(unittest.TestCase):
    def test_wiki_dir_constant(self) -> None:
        self.assertEqual(kb_shared.WIKI_DIR, kb_shared.ROOT / "wiki")

    def test_wiki_concepts_dir_constant(self) -> None:
        self.assertEqual(kb_shared.WIKI_CONCEPTS_DIR, kb_shared.ROOT / "wiki" / "concepts")

    def test_wiki_sources_dir_constant(self) -> None:
        self.assertEqual(kb_shared.WIKI_SOURCES_DIR, kb_shared.ROOT / "wiki" / "sources")

    def test_wiki_index_path_constant(self) -> None:
        self.assertEqual(kb_shared.WIKI_INDEX_PATH, kb_shared.ROOT / "wiki" / "INDEX.md")


if __name__ == "__main__":
    unittest.main()
