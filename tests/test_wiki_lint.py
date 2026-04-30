import json
import tempfile
import unittest
from pathlib import Path

import wiki_lint
import wiki_seed
import wiki_state
from wiki_schemas import ConceptArticle, SourceSummary, serialize_concept, serialize_source_summary


def _write_concept(wiki_dir: Path, **overrides) -> Path:
    defaults = dict(
        title="Test Concept",
        slug="test-concept",
        aliases=[],
        status="stable",
        related_concepts=[],
        sources=["articles/reviewed/test/article.md"],
        content_types=["methodology"],
        last_compiled="2026-04-30",
        compile_version=1,
        synthesis="Synthesis prose here.",
        definition="A test concept.",
        key_idea_blocks=[],
        variants=[],
        common_combinations=[],
        transfer_targets=[],
        failure_modes=[],
        open_questions=[],
        source_basenames=["test"],
    )
    defaults.update(overrides)
    c = ConceptArticle(**defaults)
    path = wiki_dir / "concepts" / f"{c.slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_concept(c), encoding="utf-8")
    return path


class UnsupportedBulletsTests(unittest.TestCase):
    def test_anchored_bullet_no_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            wiki_seed.bootstrap_wiki(wiki_dir)
            _write_concept(
                wiki_dir,
                slug="anchored",
                key_idea_blocks=["12-month minus 1-month return [src1]"],
            )
            report = wiki_lint.lint_wiki(Path(tmp))
            unsupported = [i for i in report.issues if i.kind == "unsupported_bullets" and "anchored" in i.path]
            self.assertEqual(unsupported, [])

    def test_unanchored_bullet_emits_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            wiki_seed.bootstrap_wiki(wiki_dir)
            _write_concept(
                wiki_dir,
                slug="unanchored",
                key_idea_blocks=["A claim with no source"],
            )
            report = wiki_lint.lint_wiki(Path(tmp))
            unsupported = [i for i in report.issues if i.kind == "unsupported_bullets" and "unanchored" in i.path]
            self.assertGreater(len(unsupported), 0)
            self.assertEqual(unsupported[0].severity, "warning")

    def test_proposed_concept_skipped(self) -> None:
        """Bullets in proposed concepts aren't checked — they're not used by brainstorm yet."""
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            wiki_seed.bootstrap_wiki(wiki_dir)
            _write_concept(
                wiki_dir,
                slug="proposed-thing",
                status="proposed",
                key_idea_blocks=["Unanchored draft idea"],
            )
            report = wiki_lint.lint_wiki(Path(tmp))
            unsupported = [i for i in report.issues if i.kind == "unsupported_bullets" and "proposed-thing" in i.path]
            self.assertEqual(unsupported, [])


class StaleSourceTests(unittest.TestCase):
    def test_changed_source_hash_emits_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            wiki_seed.bootstrap_wiki(wiki_dir)
            article = Path(tmp) / "articles" / "reviewed" / "x" / "article.md"
            article.parent.mkdir(parents=True)
            article.write_text("v1", encoding="utf-8")

            state = wiki_state.WikiState()
            wiki_state.update_source_entry(state, article, feeds_concepts=["momentum-strategies"])
            wiki_state.save_wiki_state(state, wiki_dir / "state.json")

            article.write_text("v2", encoding="utf-8")  # change content
            report = wiki_lint.lint_wiki(Path(tmp))
            stale = [i for i in report.issues if i.kind == "stale_concepts"]
            self.assertGreater(len(stale), 0)


class UnsupportedClaimsTests(unittest.TestCase):
    def test_synthesis_with_no_sources_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            wiki_seed.bootstrap_wiki(wiki_dir)
            _write_concept(
                wiki_dir,
                slug="ungrounded",
                synthesis="A bold claim with no sources.",
                sources=[],
                source_basenames=[],
                compile_version=2,  # not a seed stub
            )
            report = wiki_lint.lint_wiki(Path(tmp))
            errors = [i for i in report.issues if i.kind == "unsupported_claims" and "ungrounded" in i.path]
            self.assertGreater(len(errors), 0)
            self.assertFalse(report.ok_for_brainstorm())


class DuplicateAliasTests(unittest.TestCase):
    def test_two_concepts_sharing_alias_emit_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            wiki_seed.bootstrap_wiki(wiki_dir)
            _write_concept(
                wiki_dir,
                slug="trend-following",
                aliases=["momentum"],  # collides with momentum-strategies seed alias
            )
            report = wiki_lint.lint_wiki(Path(tmp))
            dups = [i for i in report.issues if i.kind == "duplicate_aliases"]
            self.assertGreater(len(dups), 0)


class OkForBrainstormTests(unittest.TestCase):
    def test_clean_wiki_is_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            wiki_seed.bootstrap_wiki(wiki_dir)
            report = wiki_lint.lint_wiki(Path(tmp))
            self.assertTrue(report.ok_for_brainstorm())

    def test_lint_report_json_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            wiki_seed.bootstrap_wiki(wiki_dir)
            wiki_lint.lint_wiki(Path(tmp))
            report_path = wiki_dir / "lint_report.json"
            self.assertTrue(report_path.exists())
            data = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertIn("issues", data)


if __name__ == "__main__":
    unittest.main()
