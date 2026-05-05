"""Tests for Step 5 schema-enforcement additions to wiki_lint."""
import tempfile
import unittest
from pathlib import Path

import wiki_lint
from wiki_seed import bootstrap_wiki


class SchemaSectionEnforcementTests(unittest.TestCase):
    def _bootstrap(self, root: Path) -> Path:
        bootstrap_wiki(root / "wiki")
        return root / "wiki"

    def test_concept_missing_required_section_raises_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wiki_dir = self._bootstrap(root)
            # mutilate: remove the Definition header from a seed concept
            target = wiki_dir / "concepts" / "momentum-strategies.md"
            text = target.read_text(encoding="utf-8")
            text = text.replace("## Definition\n", "## Definitionx\n", 1)
            target.write_text(text, encoding="utf-8")
            report = wiki_lint.lint_wiki(root)
            kinds = {i.kind for i in report.issues}
            self.assertIn("schema_missing_section", kinds)

    def test_invalid_brainstorm_value_enum_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wiki_dir = self._bootstrap(root)
            sources_dir = wiki_dir / "sources"
            sources_dir.mkdir(exist_ok=True)
            (sources_dir / "weird.md").write_text(
                "---\n"
                "source_path: raw/weird/article.md\n"
                "title: Weird Source\n"
                "content_type: methodology\n"
                "brainstorm_value: bananas\n"
                "feeds_concepts: []\n"
                "ingested: 2026-05-04\n"
                "last_compiled: 2026-05-04\n"
                "---\n\n"
                "**One-line takeaway:** test\n"
                "\n**Idea Blocks (top 3):**\n\n- a\n\n"
                "**Why it's in the KB:** for testing\n\n"
                "**Feeds concepts:** _none_\n",
                encoding="utf-8",
            )
            report = wiki_lint.lint_wiki(root)
            self.assertTrue(any(
                i.kind == "schema_invalid_enum" and "bananas" in i.message
                for i in report.issues
            ))

    def test_clean_seed_wiki_has_no_schema_violations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._bootstrap(root)
            report = wiki_lint.lint_wiki(root)
            schema_kinds = {
                "schema_missing_section",
                "schema_empty_synthesis",
                "schema_empty_definition",
                "schema_invalid_enum",
            }
            offenders = [i for i in report.issues if i.kind in schema_kinds]
            self.assertEqual(offenders, [])


class AutoFixApiTests(unittest.TestCase):
    def test_auto_fix_returns_zero_when_no_offenders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bootstrap_wiki(root / "wiki")
            report = wiki_lint.lint_wiki(root)
            n = wiki_lint.auto_fix(root, report)
            self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
