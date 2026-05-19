import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import quant_llm_wiki.query.brainstorm as mod


class BrainstormFromKbTests(unittest.TestCase):
    def make_note(self, article_dir: str = "a", source_dir: str = "reviewed", **frontmatter):
        base_frontmatter = {
            "status": "reviewed",
            "title": "行业轮动模型",
            "summary": "讨论行业轮动与风险预算",
            "idea_blocks": ["行业轮动和风险预算结合"],
            "combination_hooks": [],
            "transfer_targets": [],
            "failure_modes": [],
        }
        base_frontmatter.update(frontmatter)
        return mod.KnowledgeNote(
            article_dir=Path(article_dir),
            source_dir=source_dir,
            frontmatter=base_frontmatter,
            body="## Main Content\n\n行业轮动可以和风险预算结合。\n",
        )

    def test_parse_frontmatter_value_json_array(self) -> None:
        self.assertEqual(mod.parse_frontmatter_value('["a", "b"]'), ["a", "b"])

    def test_parse_frontmatter_parses_arrays(self) -> None:
        markdown = "---\nstatus: reviewed\nstrategy_type: [\"allocation_rotation\", \"cross_sectional\"]\nsummary: test\n---\n\n## Main Content\n\n正文\n"
        frontmatter, body = mod.parse_frontmatter(markdown)
        self.assertEqual(frontmatter["status"], "reviewed")
        self.assertEqual(frontmatter["strategy_type"], ["allocation_rotation", "cross_sectional"])
        self.assertIn("Main Content", body)

    def test_effective_status_derives_from_directory(self) -> None:
        note = mod.KnowledgeNote(
            article_dir=Path("x"),
            source_dir="high-value",
            frontmatter={"status": "raw", "title": "t"},
            body="",
        )
        self.assertEqual(note.effective_status, "high_value")

    def test_apply_filters_uses_metadata(self) -> None:
        notes = [
            self.make_note(
                article_dir="a",
                content_type="allocation",
                market=["a_share"],
                strategy_type=["allocation_rotation"],
                brainstorm_value="high",
                title="A",
            ),
            self.make_note(
                article_dir="b",
                content_type="strategy",
                market=["us_equity"],
                strategy_type=["factor_model"],
                brainstorm_value="medium",
                title="B",
            ),
        ]
        filtered = mod.apply_filters(
            notes,
            content_type="allocation",
            market="a_share",
            asset_type=None,
            strategy_type="allocation_rotation",
            brainstorm_value="high",
        )
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].title, "A")

    def test_retrieve_blocks_prefers_idea_blocks(self) -> None:
        from unittest.mock import patch
        note = self.make_note()
        # Isolate from any compiled wiki/ in the worktree — this test predates
        # the wiki layer and asserts on article-only retrieval.
        # Point QLW_KB_ROOT to a temp dir that has no wiki/concepts/ so the
        # wiki layer is skipped and only article-level blocks are returned.
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"QLW_KB_ROOT": tmp}):
                retrieved, mode, warning = mod.retrieve_blocks([note], "行业轮动 风险预算", 3, "brainstorm", "keyword")
        self.assertTrue(retrieved)
        self.assertEqual(retrieved[0].block_type, "idea_blocks")
        self.assertEqual(mode, "keyword")
        self.assertIsNone(warning)

    def test_hybrid_falls_back_to_keyword_on_vector_error(self) -> None:
        note = self.make_note()
        original = mod._vector_retrieve
        try:
            def raising(*args, **kwargs):
                raise RuntimeError("boom")
            mod._vector_retrieve = raising
            retrieved, mode, warning = mod.retrieve_blocks([note], "行业轮动 风险预算", 3, "brainstorm", "hybrid")
        finally:
            mod._vector_retrieve = original
        self.assertTrue(retrieved)
        self.assertEqual(mode, "keyword")
        self.assertIn("fell back to keyword", warning or "")

    def test_rrf_fusion_combines_keyword_and_vector(self) -> None:
        note = self.make_note()
        keyword_blocks = [
            mod.KnowledgeBlock(note=note, block_type="summary", text="行业轮动摘要", score=1.0),
            mod.KnowledgeBlock(note=note, block_type="idea_blocks", text="风险预算组合", score=0.9),
        ]
        vector_blocks = [
            mod.KnowledgeBlock(note=note, block_type="idea_blocks", text="风险预算组合", score=1.0),
            mod.KnowledgeBlock(note=note, block_type="transfer_targets", text="迁移到ETF", score=0.8),
        ]
        fused = mod._rrf_fusion(keyword_blocks, vector_blocks, 3)
        self.assertEqual(fused[0].text, "风险预算组合")
        self.assertEqual(len(fused), 3)

    def test_load_notes_from_reviewed_and_high_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reviewed_dir = root / "raw" / "note_a"
            high_value_dir = root / "raw" / "note_b"
            reviewed_dir.mkdir(parents=True)
            high_value_dir.mkdir(parents=True)
            reviewed_dir.joinpath("article.md").write_text(
                "---\nstatus: reviewed\ntitle: A\n---\n\n## Main Content\n\n内容\n",
                encoding="utf-8",
            )
            high_value_dir.joinpath("article.md").write_text(
                "---\nstatus: high_value\ntitle: B\n---\n\n## Main Content\n\n内容\n",
                encoding="utf-8",
            )
            notes = mod.load_notes(root, ["reviewed", "high-value"])
            self.assertEqual(len(notes), 2)
            self.assertEqual({note.title for note in notes}, {"A", "B"})


class QueryLogWiringTests(unittest.TestCase):
    """Verify ask/brainstorm wire append_query_log() with --no-query-log opt-out."""

    def _setup_kb_with_one_note(self, root: Path) -> None:
        """Bootstrap wiki and write a single reviewed article whose body tokens
        will match the query keyword used in the tests ("momentum")."""
        from quant_llm_wiki.wiki.seed import bootstrap_wiki
        bootstrap_wiki(root / "wiki")
        article_dir = root / "raw" / "note_momentum"
        article_dir.mkdir(parents=True)
        (article_dir / "article.md").write_text(
            "---\n"
            "status: reviewed\n"
            "title: Momentum Strategy\n"
            "summary: momentum factor backtest\n"
            "idea_blocks:\n"
            "  - momentum can combine with mean reversion\n"
            "combination_hooks: []\n"
            "transfer_targets: []\n"
            "failure_modes: []\n"
            "---\n\n"
            "## Main Content\n\n"
            "Momentum factor is a well-known anomaly.\n",
            encoding="utf-8",
        )

    def test_run_ask_writes_query_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._setup_kb_with_one_note(root)
            with patch("quant_llm_wiki.query.brainstorm.call_zhipu_chat", return_value="fake answer"):
                rc = mod.run_ask(
                    root,
                    query="momentum",
                    retrieval="keyword",
                    write_query_log=True,
                )
            self.assertEqual(rc, 0)
            queries_dir = root / "wiki" / "queries"
            log_files = list(queries_dir.glob("*_momentum_ask.md"))
            self.assertEqual(len(log_files), 1, f"Expected 1 log file, found: {list(queries_dir.glob('*.md'))}")

    def test_run_brainstorm_writes_query_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._setup_kb_with_one_note(root)
            with patch("quant_llm_wiki.query.brainstorm.call_zhipu_chat", return_value="fake brainstorm"), \
                 patch("quant_llm_wiki.query.brainstorm.rethink", side_effect=lambda result, *a, **kw: result):
                rc = mod.run_brainstorm(
                    root,
                    query="momentum",
                    retrieval="keyword",
                    write_query_log=True,
                )
            self.assertEqual(rc, 0)
            queries_dir = root / "wiki" / "queries"
            log_files = list(queries_dir.glob("*_momentum_brainstorm.md"))
            self.assertEqual(len(log_files), 1, f"Expected 1 log file, found: {list(queries_dir.glob('*.md'))}")

    def test_no_query_log_flag_suppresses_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._setup_kb_with_one_note(root)
            with patch("quant_llm_wiki.query.brainstorm.call_zhipu_chat", return_value="fake answer"):
                rc = mod.run_ask(
                    root,
                    query="momentum",
                    retrieval="keyword",
                    write_query_log=False,
                )
            self.assertEqual(rc, 0)
            queries_dir = root / "wiki" / "queries"
            log_files = list(queries_dir.glob("*.md")) if queries_dir.exists() else []
            self.assertEqual(len(log_files), 0, f"Expected no log files, found: {log_files}")


class WikiHealthCacheTests(unittest.TestCase):
    """Test the mtime-based short-circuit in _wiki_is_healthy_for_query."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    _STATE_V1 = "v1"

    def _make_kb(self, tmp: str) -> Path:
        """Create a minimal KB layout with concepts, sources, state.json, and an article."""
        root = Path(tmp)
        (root / "wiki" / "concepts").mkdir(parents=True)
        (root / "wiki" / "sources").mkdir(parents=True)
        (root / "raw" / "x").mkdir(parents=True)
        # concept
        (root / "wiki" / "concepts" / "foo.md").write_text("# foo\n", encoding="utf-8")
        # source summary
        (root / "wiki" / "sources" / "bar.md").write_text("# bar\n", encoding="utf-8")
        # article referenced by state.sources
        article = root / "raw" / "x" / "article.md"
        article.write_text("content\n", encoding="utf-8")
        # state.json pointing at the article
        import json as _json
        state = {
            "schema_version": self._STATE_V1,
            "sources": {
                str(article): {"content_hash": "abc", "last_seen": "", "feeds_concepts": []},
            },
            "concepts": {},
        }
        (root / "wiki" / "state.json").write_text(
            _json.dumps(state), encoding="utf-8"
        )
        return root

    def _write_lint_report(self, root: Path, *, has_error: bool = False) -> Path:
        """Write a lint_report.json and return its path."""
        import json as _json
        issues = []
        if has_error:
            issues.append({"severity": "error", "kind": "malformed_concept",
                           "path": "x", "message": "bad"})
        report = {"issues": issues}
        p = root / "wiki" / "lint_report.json"
        p.write_text(_json.dumps(report), encoding="utf-8")
        return p

    def _set_mtime(self, path: Path, t: float) -> None:
        os.utime(str(path), (t, t))

    def _set_all_inputs_older(self, root: Path, cache_mtime: float) -> None:
        old = cache_mtime - 10.0
        for p in [
            root / "wiki" / "concepts" / "foo.md",
            root / "wiki" / "sources" / "bar.md",
            root / "wiki" / "state.json",
            root / "raw" / "x" / "article.md",
        ]:
            self._set_mtime(p, old)

    # ------------------------------------------------------------------
    # Test 1 — cache hit: report newer than all inputs
    # ------------------------------------------------------------------

    def test_cache_hit_returns_cached_value_without_lint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_kb(tmp)
            cache_path = self._write_lint_report(root, has_error=False)
            now = 1_700_000_100.0
            self._set_mtime(cache_path, now)
            self._set_all_inputs_older(root, now)

            with patch("quant_llm_wiki.wiki.lint.lint_wiki") as mock_lint:
                result = mod._wiki_is_healthy_for_query(root)

            self.assertTrue(result)
            mock_lint.assert_not_called()

    # ------------------------------------------------------------------
    # Test 2 — cache miss: no lint_report.json
    # ------------------------------------------------------------------

    def test_cache_miss_no_report_calls_fresh_lint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_kb(tmp)
            # no lint_report.json written

            with patch("quant_llm_wiki.query.brainstorm.lint_wiki") as mock_lint:
                mock_lint.return_value = type("R", (), {"ok_for_brainstorm": lambda self: True})()
                result = mod._wiki_is_healthy_for_query(root)

            mock_lint.assert_called_once_with(root)

    # ------------------------------------------------------------------
    # Test 3 — cache miss: concept newer than cache
    # ------------------------------------------------------------------

    def test_cache_miss_concept_newer_calls_fresh_lint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_kb(tmp)
            cache_path = self._write_lint_report(root)
            base = 1_700_000_100.0
            self._set_mtime(cache_path, base)
            self._set_all_inputs_older(root, base)
            # Make concept newer
            self._set_mtime(root / "wiki" / "concepts" / "foo.md", base + 5.0)

            with patch("quant_llm_wiki.query.brainstorm.lint_wiki") as mock_lint:
                mock_lint.return_value = type("R", (), {"ok_for_brainstorm": lambda self: True})()
                mod._wiki_is_healthy_for_query(root)

            mock_lint.assert_called_once_with(root)

    # ------------------------------------------------------------------
    # Test 4 — cache miss: source summary newer than cache
    # ------------------------------------------------------------------

    def test_cache_miss_source_newer_calls_fresh_lint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_kb(tmp)
            cache_path = self._write_lint_report(root)
            base = 1_700_000_100.0
            self._set_mtime(cache_path, base)
            self._set_all_inputs_older(root, base)
            # Make source summary newer
            self._set_mtime(root / "wiki" / "sources" / "bar.md", base + 5.0)

            with patch("quant_llm_wiki.query.brainstorm.lint_wiki") as mock_lint:
                mock_lint.return_value = type("R", (), {"ok_for_brainstorm": lambda self: True})()
                mod._wiki_is_healthy_for_query(root)

            mock_lint.assert_called_once_with(root)

    # ------------------------------------------------------------------
    # Test 5 — cache miss: state.json newer than cache
    # ------------------------------------------------------------------

    def test_cache_miss_state_newer_calls_fresh_lint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_kb(tmp)
            cache_path = self._write_lint_report(root)
            base = 1_700_000_100.0
            self._set_mtime(cache_path, base)
            self._set_all_inputs_older(root, base)
            # Make state.json newer
            self._set_mtime(root / "wiki" / "state.json", base + 5.0)

            with patch("quant_llm_wiki.query.brainstorm.lint_wiki") as mock_lint:
                mock_lint.return_value = type("R", (), {"ok_for_brainstorm": lambda self: True})()
                mod._wiki_is_healthy_for_query(root)

            mock_lint.assert_called_once_with(root)

    # ------------------------------------------------------------------
    # Test 6 — cache miss: referenced article newer than cache (spec-gap fix)
    # ------------------------------------------------------------------

    def test_cache_miss_article_newer_calls_fresh_lint(self) -> None:
        """Article files referenced by state.sources are input #4; touching one
        must invalidate the cache even when concepts/sources/state.json are older."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_kb(tmp)
            cache_path = self._write_lint_report(root)
            base = 1_700_000_100.0
            self._set_mtime(cache_path, base)
            self._set_all_inputs_older(root, base)
            # Make the referenced article newer (spec-gap case)
            self._set_mtime(root / "raw" / "x" / "article.md", base + 5.0)

            with patch("quant_llm_wiki.query.brainstorm.lint_wiki") as mock_lint:
                mock_lint.return_value = type("R", (), {"ok_for_brainstorm": lambda self: True})()
                mod._wiki_is_healthy_for_query(root)

            mock_lint.assert_called_once_with(root)


if __name__ == "__main__":
    unittest.main()
