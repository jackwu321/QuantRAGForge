import tempfile
import unittest
import unittest.mock
from pathlib import Path

from quant_llm_wiki.wiki import compile as compile_mod
from quant_llm_wiki.wiki.compile_llm import ConceptAssignment, RecompileResult

# Concept slugs must satisfy SLUG_RE = r"^[a-z0-9]+(-[a-z0-9]+)*$"
# (hyphens only, no underscores).
_CONCEPT_SLUG = "topic-alpha"


def _write_article(kb_root: Path, slug: str, body: str) -> Path:
    """Articles must live under raw/ — _list_articles scans kb_root/raw/."""
    ad = kb_root / "raw" / slug
    ad.mkdir(parents=True, exist_ok=True)
    (ad / "article.md").write_text(
        f"---\ntitle: {slug}\ncontent_type: paper\nmain_topic: {_CONCEPT_SLUG}\nidea_blocks: [Idea]\n---\n{body}\n",
        encoding="utf-8",
    )
    return ad


def _seed_concept(kb_root: Path, slug: str) -> None:
    cd = kb_root / "wiki" / "concepts"
    cd.mkdir(parents=True, exist_ok=True)
    (cd / f"{slug}.md").write_text(
        f"---\ntitle: {slug}\nslug: {slug}\nstatus: stable\naliases: []\n"
        f"related_concepts: []\nsources: []\ncontent_types: [paper]\n"
        f"last_compiled: 2026-01-01\ncompile_version: 0\nsource_basenames: []\n---\n"
        f"prior definition of {slug}\n",
        encoding="utf-8",
    )


class ReverseIndexMultiSourceTests(unittest.TestCase):
    def test_skipped_and_changed_articles_both_feed_recompile(self):
        """
        Two articles feed 'topic-alpha'. First compile establishes state.json
        (hash records). Between compiles the concept file is re-seeded with
        sources:[] so that art-a can only reach the second recompile via the
        reverse-index skip-branch registration at compile.py:L288 — NOT via
        the persisted concept.sources list from the first compile.

        Second compile changes art-b only: art-a takes the incremental skip
        branch, art-b takes the changed branch. The recompile for topic-alpha
        must receive BOTH paths exactly once.

        Mutation check: temporarily replacing the skip-branch call with
        _register_article_concepts(article_dir, []) must cause this test to
        fail with 'art-a not in sources', confirming the test pins the real
        regression class.
        """
        with tempfile.TemporaryDirectory() as tmp:
            kb_root = Path(tmp)
            _seed_concept(kb_root, _CONCEPT_SLUG)
            a = _write_article(kb_root, "art-a", body="content A v1")
            b = _write_article(kb_root, "art-b", body="content B v1")

            assign_result = ConceptAssignment(
                existing_concepts=[_CONCEPT_SLUG],
                proposed_new_concepts=[],
                error="",
            )
            recompile_calls: list[dict] = []

            def fake_recompile(*, concept_slug, concept_title, source_articles, schema_text=None):
                recompile_calls.append({
                    "slug": concept_slug,
                    "sources": [sa.get("source_basename") for sa in source_articles],
                })
                return RecompileResult(
                    synthesis="s", definition="d", related_concepts=[],
                    key_idea_blocks=[], variants=[], common_combinations=[],
                    transfer_targets=[], failure_modes=[], open_questions=[],
                    error="",
                )

            with unittest.mock.patch.object(compile_mod, "assign_concepts", return_value=assign_result), \
                 unittest.mock.patch.object(compile_mod, "recompile_concept", side_effect=fake_recompile):
                # First compile: establishes state.json (hash records for art-a and art-b).
                compile_mod.compile_wiki(
                    kb_root=kb_root, source_dirs=["raw"],
                    mode="incremental", dry_run=False,
                )

                # Re-seed the concept file with sources:[] so that in the second
                # compile art-a can only appear in source_dicts via the reverse-index
                # skip-branch registration (compile.py:L288), not via concept.sources
                # persisted from the first compile.
                _seed_concept(kb_root, _CONCEPT_SLUG)

                # Modify art-b → its content hash changes
                (b / "article.md").write_text(
                    f"---\ntitle: art-b\ncontent_type: paper\nmain_topic: {_CONCEPT_SLUG}\nidea_blocks: [Idea]\n"
                    "---\ncontent B v2 — CHANGED\n",
                    encoding="utf-8",
                )

                recompile_calls.clear()

                # Second compile: incremental.
                # art-a unchanged → skip branch at compile.py:L288.
                # art-b changed   → assign/register branch at compile.py:L330.
                # concept.sources is now [] (re-seeded), so both articles must
                # reach recompile solely via concept_to_articles registrations.
                compile_mod.compile_wiki(
                    kb_root=kb_root, source_dirs=["raw"],
                    mode="incremental", dry_run=False,
                )

            alpha = [c for c in recompile_calls if c["slug"] == _CONCEPT_SLUG]
            self.assertEqual(len(alpha), 1,
                             f"{_CONCEPT_SLUG} should recompile exactly once, got {alpha}")
            sources = alpha[0]["sources"]
            self.assertIn("art-a", sources, "skipped article must still feed recompile")
            self.assertIn("art-b", sources, "changed article must feed recompile")
            self.assertEqual(len(sources), len(set(sources)),
                             f"no duplicates expected, got {sources}")


if __name__ == "__main__":
    unittest.main()
