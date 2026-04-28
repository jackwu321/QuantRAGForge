import tempfile
import unittest
from pathlib import Path

import wiki_seed
import wiki_schemas


class WikiSeedTests(unittest.TestCase):
    def test_seed_taxonomy_has_seven_concepts(self) -> None:
        slugs = [seed.slug for seed in wiki_seed.SEED_CONCEPTS]
        self.assertEqual(len(slugs), 7)
        self.assertEqual(len(set(slugs)), 7)

    def test_seed_slugs_are_kebab_case(self) -> None:
        for seed in wiki_seed.SEED_CONCEPTS:
            self.assertRegex(seed.slug, r"^[a-z0-9]+(-[a-z0-9]+)*$")

    def test_bootstrap_creates_seed_stubs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp) / "wiki"
            wiki_seed.bootstrap_wiki(wiki_root)
            self.assertTrue((wiki_root / "concepts").is_dir())
            self.assertTrue((wiki_root / "sources").is_dir())
            for seed in wiki_seed.SEED_CONCEPTS:
                stub_path = wiki_root / "concepts" / f"{seed.slug}.md"
                self.assertTrue(stub_path.exists(), f"missing stub: {stub_path}")
                concept = wiki_schemas.parse_concept(stub_path.read_text(encoding="utf-8"))
                self.assertEqual(concept.status, "stable")
                self.assertEqual(concept.sources, [])

    def test_bootstrap_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp) / "wiki"
            wiki_seed.bootstrap_wiki(wiki_root)
            stub = wiki_root / "concepts" / wiki_seed.SEED_CONCEPTS[0].slug
            stub_path = stub.with_suffix(".md")
            mtime_first = stub_path.stat().st_mtime_ns
            # Run again — should not overwrite existing stub
            wiki_seed.bootstrap_wiki(wiki_root)
            self.assertEqual(stub_path.stat().st_mtime_ns, mtime_first)


if __name__ == "__main__":
    unittest.main()
