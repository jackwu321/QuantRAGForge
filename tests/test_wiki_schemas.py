import unittest

import wiki_schemas


class ConceptArticleSchemaTests(unittest.TestCase):
    def test_serialize_concept_minimal(self) -> None:
        concept = wiki_schemas.ConceptArticle(
            title="Momentum Factor",
            slug="momentum-factor",
            aliases=["momentum", "动量因子"],
            status="stable",
            related_concepts=["factor-timing"],
            sources=["articles/reviewed/2026-03-22_华泰_趋势.../article.md"],
            content_types=["methodology"],
            last_compiled="2026-04-28",
            compile_version=1,
            synthesis="One paragraph synthesis.",
            definition="Canonical definition.",
            key_idea_blocks=["Idea 1"],
            variants=["Variant 1"],
            common_combinations=["[[factor-timing]]"],
            transfer_targets=["Crypto"],
            failure_modes=["Trend reversals"],
            open_questions=["Is residual momentum better?"],
            source_basenames=["2026-03-22_华泰_趋势"],
        )
        text = wiki_schemas.serialize_concept(concept)
        self.assertIn("title: Momentum Factor", text)
        self.assertIn("slug: momentum-factor", text)
        self.assertIn("status: stable", text)
        self.assertIn("## Synthesis", text)
        self.assertIn("## Sources", text)
        self.assertIn("[[2026-03-22_华泰_趋势]]", text)

    def test_round_trip_concept(self) -> None:
        original = wiki_schemas.ConceptArticle(
            title="Risk Parity",
            slug="risk-parity",
            aliases=["风险平价"],
            status="stable",
            related_concepts=[],
            sources=[],
            content_types=["allocation"],
            last_compiled="2026-04-28",
            compile_version=2,
            synthesis="S",
            definition="D",
            key_idea_blocks=[],
            variants=[],
            common_combinations=[],
            transfer_targets=[],
            failure_modes=[],
            open_questions=[],
            source_basenames=[],
        )
        text = wiki_schemas.serialize_concept(original)
        parsed = wiki_schemas.parse_concept(text)
        self.assertEqual(parsed.title, "Risk Parity")
        self.assertEqual(parsed.slug, "risk-parity")
        self.assertEqual(parsed.status, "stable")
        self.assertEqual(parsed.compile_version, 2)
        self.assertEqual(parsed.aliases, ["风险平价"])
        self.assertEqual(parsed.content_types, ["allocation"])

    def test_invalid_status_rejected(self) -> None:
        with self.assertRaises(ValueError):
            wiki_schemas.ConceptArticle(
                title="X", slug="x", aliases=[], status="invalid",
                related_concepts=[], sources=[], content_types=[],
                last_compiled="2026-04-28", compile_version=1,
                synthesis="", definition="", key_idea_blocks=[],
                variants=[], common_combinations=[], transfer_targets=[],
                failure_modes=[], open_questions=[], source_basenames=[],
            )

    def test_slug_must_be_kebab_case(self) -> None:
        with self.assertRaises(ValueError):
            wiki_schemas.ConceptArticle(
                title="X", slug="Bad_Slug", aliases=[], status="stable",
                related_concepts=[], sources=[], content_types=[],
                last_compiled="2026-04-28", compile_version=1,
                synthesis="", definition="", key_idea_blocks=[],
                variants=[], common_combinations=[], transfer_targets=[],
                failure_modes=[], open_questions=[], source_basenames=[],
            )


class SourceSummarySchemaTests(unittest.TestCase):
    def test_serialize_source_summary(self) -> None:
        summary = wiki_schemas.SourceSummary(
            source_path="articles/reviewed/2026-03-22_华泰_趋势/article.md",
            title="基于趋势和拐点的市值因子择时模型",
            content_type="methodology",
            brainstorm_value="high",
            feeds_concepts=["factor-timing", "momentum-factor"],
            ingested="2026-03-22",
            last_compiled="2026-04-28",
            takeaway="市值因子可基于趋势拐点择时。",
            top_idea_blocks=["趋势识别", "拐点过滤"],
            why_in_kb="High brainstorm value methodology.",
        )
        text = wiki_schemas.serialize_source_summary(summary)
        self.assertIn("title: 基于趋势和拐点的市值因子择时模型", text)
        self.assertIn("[[factor-timing]]", text)
        self.assertIn("**One-line takeaway:**", text)

    def test_round_trip_source_summary(self) -> None:
        original = wiki_schemas.SourceSummary(
            source_path="articles/high-value/x/article.md",
            title="X",
            content_type="strategy",
            brainstorm_value="medium",
            feeds_concepts=["etf-rotation"],
            ingested="2026-04-01",
            last_compiled="2026-04-28",
            takeaway="T",
            top_idea_blocks=["A", "B", "C"],
            why_in_kb="W",
        )
        text = wiki_schemas.serialize_source_summary(original)
        parsed = wiki_schemas.parse_source_summary(text)
        self.assertEqual(parsed.title, "X")
        self.assertEqual(parsed.feeds_concepts, ["etf-rotation"])
        self.assertEqual(parsed.top_idea_blocks, ["A", "B", "C"])


if __name__ == "__main__":
    unittest.main()
