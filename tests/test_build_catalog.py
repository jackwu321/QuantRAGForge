import json
import tempfile
import unittest
from pathlib import Path

import build_catalog as mod


class BuildCatalogTests(unittest.TestCase):
    def test_build_catalog_entry_merges_frontmatter_and_source_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            article_dir = root / "articles" / "reviewed" / "demo"
            article_dir.mkdir(parents=True)
            (article_dir / "article.md").write_text(
                "---\n"
                "title: Demo\n"
                "source_url: https://example.com\n"
                "source_type: wechat_mp\n"
                "account: acct\n"
                "author: auth\n"
                "publish_date: 2026-03-24\n"
                "ingested_at: 2026-03-25\n"
                "status: reviewed\n"
                "content_type: allocation\n"
                "market: [\"a_share\"]\n"
                "asset_type: [\"etf\"]\n"
                "strategy_type: [\"allocation_rotation\"]\n"
                "summary: hello\n"
                "---\n\n## Main Content\n\nx\n",
                encoding="utf-8",
            )
            (article_dir / "source.json").write_text(
                json.dumps(
                    {
                        "llm_enriched": True,
                        "llm_model": "glm-4.7",
                        "images": [{"path": "a.png"}],
                        "code_blocks": [{"content": "print(1)"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            entry = mod.build_catalog_entry(root, "reviewed", article_dir)
            self.assertEqual(entry["title"], "Demo")
            self.assertEqual(entry["article_dir"], "articles/reviewed/demo")
            self.assertEqual(entry["market"], ["a_share"])
            self.assertTrue(entry["llm_enriched"])
            self.assertEqual(entry["image_count"], 1)
            self.assertEqual(entry["code_block_count"], 1)


if __name__ == "__main__":
    unittest.main()
