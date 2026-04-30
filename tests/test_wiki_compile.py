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


class AssignConceptsTests(unittest.TestCase):
    def test_assign_concepts_parses_existing_and_proposed(self) -> None:
        from unittest.mock import patch
        import wiki_compile_llm

        fake_response = """{
  "existing_concepts": ["momentum-strategies", "factor-timing"],
  "proposed_new_concepts": [
    {
      "slug": "macro-momentum",
      "title": "Macro Momentum",
      "aliases": ["宏观动量"],
      "rationale": "Article applies momentum to macro factors specifically.",
      "draft_synthesis": "Momentum applied across macro signals."
    }
  ]
}"""
        with patch("wiki_compile_llm.call_llm_chat", return_value=fake_response):
            result = wiki_compile_llm.assign_concepts(
                article_frontmatter={"title": "X", "content_type": "methodology", "idea_blocks": ["a", "b"]},
                index_text="- momentum-strategies — Trading rules using past returns.",
            )
        self.assertEqual(result.existing_concepts, ["momentum-strategies", "factor-timing"])
        self.assertEqual(len(result.proposed_new_concepts), 1)
        self.assertEqual(result.proposed_new_concepts[0].slug, "macro-momentum")

    def test_assign_concepts_handles_invalid_json(self) -> None:
        from unittest.mock import patch
        import wiki_compile_llm

        with patch("wiki_compile_llm.call_llm_chat", return_value="not json"):
            result = wiki_compile_llm.assign_concepts(
                article_frontmatter={"title": "X"},
                index_text="",
            )
        self.assertEqual(result.existing_concepts, [])
        self.assertEqual(result.proposed_new_concepts, [])


class RecompileConceptTests(unittest.TestCase):
    def test_recompile_returns_structured_sections(self) -> None:
        from unittest.mock import patch
        import wiki_compile_llm

        fake = """{
  "synthesis": "Momentum is best at 12-month horizons.",
  "definition": "Buy past winners.",
  "key_idea_blocks": ["12-1 momentum", "Risk-adjusted variant"],
  "variants": ["Time-series", "Cross-sectional"],
  "common_combinations": ["[[regime-detection]]", "[[risk-parity]]"],
  "transfer_targets": ["Crypto", "Fixed income"],
  "failure_modes": ["Reversals at long horizons"],
  "open_questions": ["Optimal lookback?"],
  "related_concepts": ["regime-detection", "risk-parity"]
}"""
        with patch("wiki_compile_llm.call_llm_chat", return_value=fake):
            r = wiki_compile_llm.recompile_concept(
                concept_slug="momentum-strategies",
                concept_title="Momentum Strategies",
                source_articles=[{"title": "S1", "idea_blocks": ["12-1"]}],
            )
        self.assertIn("12-month", r.synthesis)
        self.assertEqual(r.related_concepts, ["regime-detection", "risk-parity"])
        self.assertEqual(len(r.key_idea_blocks), 2)


class CompileOrchestratorTests(unittest.TestCase):
    def _setup_corpus(self, root: Path) -> None:
        from wiki_seed import bootstrap_wiki
        bootstrap_wiki(root / "wiki")
        article_dir = root / "articles" / "reviewed" / "2026-03-22_test_article"
        article_dir.mkdir(parents=True, exist_ok=True)
        (article_dir / "article.md").write_text(
            "---\n"
            "title: Test Article\n"
            "content_type: methodology\n"
            "brainstorm_value: high\n"
            "core_hypothesis: Momentum predicts.\n"
            "idea_blocks: [Idea A, Idea B]\n"
            "summary: A study.\n"
            "status: reviewed\n"
            "---\n\n## Main Content\n\nBody.\n",
            encoding="utf-8",
        )

    def test_incremental_compile_writes_source_summary(self) -> None:
        from unittest.mock import patch
        import wiki_compile
        import wiki_compile_llm

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._setup_corpus(root)

            assignment = wiki_compile_llm.ConceptAssignment(
                existing_concepts=["momentum-strategies"],
                proposed_new_concepts=[],
            )
            recompile = wiki_compile_llm.RecompileResult(
                synthesis="S", definition="D",
                key_idea_blocks=["k"], variants=[], common_combinations=[],
                transfer_targets=[], failure_modes=[], open_questions=[],
                related_concepts=[],
            )
            with patch("wiki_compile.assign_concepts", return_value=assignment), \
                 patch("wiki_compile.recompile_concept", return_value=recompile):
                report = wiki_compile.compile_wiki(
                    kb_root=root,
                    mode="incremental",
                )
            self.assertGreaterEqual(report.sources_written, 1)
            summary_path = root / "wiki" / "sources" / "2026-03-22_test_article.md"
            self.assertTrue(summary_path.exists())
            momentum_path = root / "wiki" / "concepts" / "momentum-strategies.md"
            text = momentum_path.read_text(encoding="utf-8")
            self.assertIn("articles/reviewed/2026-03-22_test_article/article.md", text)

    def test_incremental_idempotent_skips_unchanged(self) -> None:
        from unittest.mock import patch
        import wiki_compile
        import wiki_compile_llm

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._setup_corpus(root)
            assignment = wiki_compile_llm.ConceptAssignment(["momentum-strategies"], [])
            recompile = wiki_compile_llm.RecompileResult("S", "D", [], [], [], [], [], [], [])
            with patch("wiki_compile.assign_concepts", return_value=assignment) as ma, \
                 patch("wiki_compile.recompile_concept", return_value=recompile) as mr:
                wiki_compile.compile_wiki(kb_root=root, mode="incremental")
                first_calls = ma.call_count + mr.call_count

                # Run again — nothing changed
                wiki_compile.compile_wiki(kb_root=root, mode="incremental")
                second_calls = ma.call_count + mr.call_count - first_calls
                self.assertEqual(second_calls, 0)

    def test_orphan_article_is_skipped_on_rerun(self) -> None:
        """Articles for which assign_concepts returned empty (orphans) must still
        be skipped on a rerun — otherwise we burn LLM calls re-trying the same
        content that already produced no assignment."""
        from unittest.mock import patch
        import wiki_compile
        import wiki_compile_llm

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._setup_corpus(root)
            empty = wiki_compile_llm.ConceptAssignment([], [])  # orphan: no concepts assigned
            with patch("wiki_compile.assign_concepts", return_value=empty) as ma, \
                 patch("wiki_compile.recompile_concept") as mr:
                wiki_compile.compile_wiki(kb_root=root, mode="incremental")
                first = ma.call_count + mr.call_count

                wiki_compile.compile_wiki(kb_root=root, mode="incremental")
                second = ma.call_count + mr.call_count - first
                self.assertEqual(second, 0, "orphan article should not re-call assign_concepts on unchanged content")

    def test_content_hash_change_triggers_recompile(self) -> None:
        """Editing the source article must invalidate the cache and trigger LLM calls again."""
        from unittest.mock import patch
        import wiki_compile
        import wiki_compile_llm

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._setup_corpus(root)
            assignment = wiki_compile_llm.ConceptAssignment(["momentum-strategies"], [])
            recompile = wiki_compile_llm.RecompileResult("S", "D", [], [], [], [], [], [], [])
            with patch("wiki_compile.assign_concepts", return_value=assignment) as ma, \
                 patch("wiki_compile.recompile_concept", return_value=recompile) as mr:
                wiki_compile.compile_wiki(kb_root=root, mode="incremental")
                base = ma.call_count + mr.call_count

                # Modify the article — content hash changes
                article_md = root / "articles" / "reviewed" / "2026-03-22_test_article" / "article.md"
                article_md.write_text(
                    article_md.read_text(encoding="utf-8") + "\nNew paragraph.\n",
                    encoding="utf-8",
                )

                wiki_compile.compile_wiki(kb_root=root, mode="incremental")
                after_edit = ma.call_count + mr.call_count - base
                self.assertGreater(after_edit, 0, "edited article should retrigger LLM calls")

    def test_state_json_written_after_compile(self) -> None:
        from unittest.mock import patch
        import wiki_compile
        import wiki_compile_llm
        import wiki_state

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._setup_corpus(root)
            assignment = wiki_compile_llm.ConceptAssignment(["momentum-strategies"], [])
            recompile = wiki_compile_llm.RecompileResult("S", "D", [], [], [], [], [], [], [])
            with patch("wiki_compile.assign_concepts", return_value=assignment), \
                 patch("wiki_compile.recompile_concept", return_value=recompile):
                wiki_compile.compile_wiki(kb_root=root, mode="incremental")
            state_path = root / "wiki" / "state.json"
            self.assertTrue(state_path.exists())
            state = wiki_state.load_wiki_state(state_path)
            self.assertIn("momentum-strategies", state.concepts)
            article_md = str(root / "articles" / "reviewed" / "2026-03-22_test_article" / "article.md")
            self.assertIn(article_md, state.sources)
            self.assertEqual(
                state.sources[article_md].feeds_concepts,
                ["momentum-strategies"],
            )

    def test_proposed_concept_lands_with_status_proposed(self) -> None:
        from unittest.mock import patch
        import wiki_compile
        import wiki_compile_llm
        from wiki_schemas import parse_concept

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._setup_corpus(root)
            proposed = wiki_compile_llm.ProposedConcept(
                slug="macro-momentum", title="Macro Momentum",
                aliases=["宏观动量"], rationale="r", draft_synthesis="ds",
            )
            assignment = wiki_compile_llm.ConceptAssignment([], [proposed])
            recompile = wiki_compile_llm.RecompileResult("S", "D", [], [], [], [], [], [], [])
            with patch("wiki_compile.assign_concepts", return_value=assignment), \
                 patch("wiki_compile.recompile_concept", return_value=recompile):
                wiki_compile.compile_wiki(kb_root=root, mode="incremental")
            path = root / "wiki" / "concepts" / "macro-momentum.md"
            self.assertTrue(path.exists())
            concept = parse_concept(path.read_text(encoding="utf-8"))
            self.assertEqual(concept.status, "proposed")


if __name__ == "__main__":
    unittest.main()
