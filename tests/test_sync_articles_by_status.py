import tempfile
import unittest
from pathlib import Path

import quant_llm_wiki.sync as mod


class SyncArticlesByStatusTests(unittest.TestCase):
    def test_parse_status_from_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            md = Path(tmpdir) / "article.md"
            md.write_text("---\nstatus: high_value\n---\n\nx", encoding="utf-8")
            self.assertEqual(mod.parse_status(md), "high_value")

    def test_sync_moves_reviewed_and_high_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "raw"
            source.mkdir(parents=True)
            reviewed = root / "reviewed"
            high_value = root / "high-value"

            a = source / "a"
            b = source / "b"
            c = source / "c"
            for d in (a, b, c):
                d.mkdir()
                (d / "article.md").write_text("---\nstatus: raw\n---\n", encoding="utf-8")
            (a / "article.md").write_text("---\nstatus: reviewed\n---\n", encoding="utf-8")
            (b / "article.md").write_text("---\nstatus: high_value\n---\n", encoding="utf-8")

            results = mod.sync_by_status(source, dry_run=False, kb_root=root)

            self.assertTrue((reviewed / "a").exists())
            self.assertTrue((high_value / "b").exists())
            self.assertTrue((source / "c").exists())
            self.assertEqual(sum(1 for r in results if r.moved), 2)

    def test_sync_dry_run_does_not_move(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "raw"
            source.mkdir(parents=True)
            d = source / "demo"
            d.mkdir()
            (d / "article.md").write_text("---\nstatus: reviewed\n---\n", encoding="utf-8")

            results = mod.sync_by_status(source, dry_run=True, kb_root=root)

            self.assertTrue((source / "demo").exists())
            self.assertEqual(sum(1 for r in results if r.moved), 1)


if __name__ == "__main__":
    unittest.main()
