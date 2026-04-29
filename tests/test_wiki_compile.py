import tempfile
import unittest
from pathlib import Path

import wiki_compile


class SourceSummaryGenerationTests(unittest.TestCase):
    def _make_article(self, root: Path, dir_name: str, frontmatter: dict, body: str = "") -> Path:
        article_dir = root / "articles" / "reviewed" / dir_name
        article_dir.mkdir(parents=True, exist_ok=True)
        fm_lines = ["---"]
        for k, v in frontmatter.items():
            if isinstance(v, list):
                fm_lines.append(f"{k}: [{', '.join(str(x) for x in v)}]")
            else:
                fm_lines.append(f"{k}: {v}")
        fm_lines.append("---")
        (article_dir / "article.md").write_text("\n".join(fm_lines) + "\n\n" + body, encoding="utf-8")
        return article_dir

    def test_source_summary_generated_from_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            article_dir = self._make_article(root, "2026-03-22_test_article", {
                "title": "Test Article",
                "content_type": "methodology",
                "brainstorm_value": "high",
                "core_hypothesis": "Momentum predicts returns.",
                "summary": "A study of momentum factors.",
                "idea_blocks": ["Idea1", "Idea2", "Idea3"],
            })
            wiki_dir = root / "wiki"
            (wiki_dir / "sources").mkdir(parents=True)
            wiki_compile.write_source_summary(
                article_dir=article_dir,
                wiki_dir=wiki_dir,
                feeds_concepts=["momentum-strategies", "factor-models"],
            )
            summary_path = wiki_dir / "sources" / "2026-03-22_test_article.md"
            self.assertTrue(summary_path.exists())
            text = summary_path.read_text(encoding="utf-8")
            self.assertIn("title: Test Article", text)
            self.assertIn("Momentum predicts returns.", text)
            self.assertIn("[[momentum-strategies]]", text)
            self.assertIn("brainstorm_value: high", text)


if __name__ == "__main__":
    unittest.main()
