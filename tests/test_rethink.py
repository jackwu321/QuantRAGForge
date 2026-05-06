import unittest
from pathlib import Path

from quant_llm_wiki.query.rethink import BrainstormIdea, parse_ideas


class ParseIdeasTests(unittest.TestCase):
    WELL_FORMED = (
        "### Idea Title\n动量+波动率组合策略\n\n"
        "**Inspired By**\n[Context 1] 动量因子, [Context 2] 波动率择时\n\n"
        "**Core Combination Logic**\n将动量信号与波动率状态结合\n\n"
        "**What Is New**\n之前没有将两者在择时维度组合\n\n"
        "**Why It Might Make Sense**\n动量在低波时更稳定\n\n"
        "**What Could Break**\n高波环境下动量反转\n\n"
        "**Possible Variants**\n可以换成其他趋势信号\n"
    )

    TWO_IDEAS = (
        "### Idea Title\n想法A\n\n"
        "**Inspired By**\n来源A\n\n"
        "**Core Combination Logic**\n逻辑A\n\n"
        "**What Is New**\n新点A\n\n"
        "**Why It Might Make Sense**\n理由A\n\n"
        "**What Could Break**\n风险A\n\n"
        "**Possible Variants**\n变体A\n\n"
        "### Idea Title\n想法B\n\n"
        "**Inspired By**\n来源B\n\n"
        "**Core Combination Logic**\n逻辑B\n\n"
        "**What Is New**\n新点B\n\n"
        "**Why It Might Make Sense**\n理由B\n\n"
        "**What Could Break**\n风险B\n\n"
        "**Possible Variants**\n变体B\n"
    )

    def test_parse_single_idea(self) -> None:
        ideas = parse_ideas(self.WELL_FORMED)
        self.assertEqual(len(ideas), 1)
        self.assertEqual(ideas[0].title, "动量+波动率组合策略")
        self.assertEqual(ideas[0].inspired_by, "[Context 1] 动量因子, [Context 2] 波动率择时")
        self.assertEqual(ideas[0].core_logic, "将动量信号与波动率状态结合")
        self.assertEqual(ideas[0].what_is_new, "之前没有将两者在择时维度组合")

    def test_parse_multiple_ideas(self) -> None:
        ideas = parse_ideas(self.TWO_IDEAS)
        self.assertEqual(len(ideas), 2)
        self.assertEqual(ideas[0].title, "想法A")
        self.assertEqual(ideas[1].title, "想法B")

    def test_parse_empty_returns_empty(self) -> None:
        ideas = parse_ideas("")
        self.assertEqual(ideas, [])

    def test_parse_unstructured_returns_empty(self) -> None:
        ideas = parse_ideas("This is just a paragraph with no structure.")
        self.assertEqual(ideas, [])

    def test_parse_chinese_format(self) -> None:
        cn_output = (
            "## 💡 策略一：动量+波动率组合\n\n"
            "**核心逻辑：**\n将动量信号与波动率状态结合\n\n"
            "**创新点：**\n之前没有将两者组合\n\n"
            "**潜在风险：**\n高波环境下动量反转\n"
        )
        ideas = parse_ideas(cn_output)
        self.assertEqual(len(ideas), 1)
        self.assertEqual(ideas[0].title, "动量+波动率组合")
        self.assertEqual(ideas[0].core_logic, "将动量信号与波动率状态结合")
        self.assertEqual(ideas[0].what_is_new, "之前没有将两者组合")

    def test_parse_chinese_format_with_prefix(self) -> None:
        cn_output = (
            "## 💡 创新策略一：动量+波动率组合\n\n"
            "**核心逻辑：**\n将动量信号与波动率状态结合\n\n"
            "**创新点：**\n之前没有将两者组合\n\n"
            "**风险点：**\n高波环境下动量反转\n"
        )
        ideas = parse_ideas(cn_output)
        self.assertEqual(len(ideas), 1)
        self.assertEqual(ideas[0].title, "动量+波动率组合")

    def test_parse_chinese_multiple_ideas(self) -> None:
        cn_output = (
            "## 💡 策略一：策略A\n\n"
            "**核心逻辑：**\n逻辑A\n\n"
            "**创新点：**\n新点A\n\n"
            "**潜在风险：**\n风险A\n\n"
            "---\n\n"
            "## 💡 策略二：策略B\n\n"
            "**核心逻辑：**\n逻辑B\n\n"
            "**创新点：**\n新点B\n\n"
            "**潜在风险：**\n风险B\n"
        )
        ideas = parse_ideas(cn_output)
        self.assertEqual(len(ideas), 2)
        self.assertEqual(ideas[0].title, "策略A")
        self.assertEqual(ideas[1].title, "策略B")


from unittest.mock import patch, MagicMock
from quant_llm_wiki.query.rethink import NoveltyResult, check_novelty, NOVELTY_THRESHOLD


class CheckNoveltyTests(unittest.TestCase):
    def _make_idea(self, title="Test Idea", core_logic="some logic", what_is_new="something new"):
        return BrainstormIdea(
            title=title,
            inspired_by="source",
            core_logic=core_logic,
            what_is_new=what_is_new,
            why_it_might_work="reason",
            what_could_break="risk",
            possible_variants="variant",
            raw_text="raw",
        )

    def test_novel_idea_returns_is_novel_true(self) -> None:
        idea = self._make_idea()
        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "ids": [["id1"]],
            "documents": [["some doc"]],
            "metadatas": [[{"article_dir": "/path/a", "block_type": "summary"}]],
            "distances": [[0.5]],  # score = 0.5, below threshold
        }
        with patch("quant_llm_wiki.query.rethink.embed_text", return_value=[0.1] * 10):
            with patch("quant_llm_wiki.query.rethink._open_rethink_collection", return_value=mock_collection):
                results = check_novelty([idea])
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].is_novel)

    def test_similar_idea_returns_is_novel_false(self) -> None:
        idea = self._make_idea()
        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "ids": [["id1"]],
            "documents": [["very similar doc"]],
            "metadatas": [[{"article_dir": "/path/a", "block_type": "idea_blocks"}]],
            "distances": [[0.1]],  # score = 0.9, above threshold
        }
        with patch("quant_llm_wiki.query.rethink.embed_text", return_value=[0.1] * 10):
            with patch("quant_llm_wiki.query.rethink._open_rethink_collection", return_value=mock_collection):
                results = check_novelty([idea])
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].is_novel)
        self.assertGreaterEqual(results[0].top_match_score, NOVELTY_THRESHOLD)

    def test_no_vector_store_returns_novel_with_empty_matches(self) -> None:
        idea = self._make_idea()
        with patch("quant_llm_wiki.query.rethink._open_rethink_collection", side_effect=RuntimeError("no store")):
            results = check_novelty([idea])
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].is_novel)
        self.assertEqual(results[0].all_matches, [])


from quant_llm_wiki.query.rethink import score_traceability, QualityScore
from quant_llm_wiki.shared import KnowledgeNote, KnowledgeBlock


class ScoreTraceabilityTests(unittest.TestCase):
    def _make_idea(self, inspired_by="", core_logic=""):
        return BrainstormIdea(
            title="Test",
            inspired_by=inspired_by,
            core_logic=core_logic,
            what_is_new="new",
            why_it_might_work="reason",
            what_could_break="risk",
            possible_variants="variant",
            raw_text="raw",
        )

    def _make_block(self, title="Article A", article_dir="a"):
        note = KnowledgeNote(
            article_dir=Path(article_dir),
            source_dir="reviewed",
            frontmatter={"title": title, "status": "reviewed"},
            body="",
        )
        return KnowledgeBlock(note=note, block_type="summary", text="content", score=0.5)

    def test_full_traceability_scores_1(self) -> None:
        blocks = [self._make_block(title="Article A"), self._make_block(title="Article B", article_dir="b")]
        idea = self._make_idea(
            inspired_by="Article A, Article B",
            core_logic="combining Article A and Article B",
        )
        score = score_traceability(idea, blocks)
        self.assertAlmostEqual(score, 1.0)

    def test_empty_inspired_by_scores_0(self) -> None:
        blocks = [self._make_block()]
        idea = self._make_idea(inspired_by="", core_logic="no references")
        score = score_traceability(idea, blocks)
        self.assertAlmostEqual(score, 0.0)

    def test_partial_traceability(self) -> None:
        blocks = [self._make_block(title="Article A")]
        idea = self._make_idea(
            inspired_by="Article A",
            core_logic="only one source",
        )
        score = score_traceability(idea, blocks)
        self.assertGreater(score, 0.0)
        self.assertLess(score, 1.0)


import json
from quant_llm_wiki.query.rethink import score_coherence_actionability


class ScoreCoherenceActionabilityTests(unittest.TestCase):
    def _make_idea(self, title="Test", core_logic="logic", what_is_new="new"):
        return BrainstormIdea(
            title=title,
            inspired_by="source",
            core_logic=core_logic,
            what_is_new=what_is_new,
            why_it_might_work="reason",
            what_could_break="risk",
            possible_variants="variant",
            raw_text="raw",
        )

    def test_returns_scores_for_each_idea(self) -> None:
        ideas = [self._make_idea(title="A"), self._make_idea(title="B")]
        mock_response = json.dumps([
            {"idea_index": 0, "coherence": 0.8, "actionability": 0.7, "coherence_reasoning": "ok", "actionability_reasoning": "ok"},
            {"idea_index": 1, "coherence": 0.6, "actionability": 0.9, "coherence_reasoning": "so-so", "actionability_reasoning": "great"},
        ])
        with patch("quant_llm_wiki.query.rethink.call_llm_chat", return_value=mock_response):
            results = score_coherence_actionability(ideas)
        self.assertEqual(len(results), 2)
        self.assertAlmostEqual(results[0]["coherence"], 0.8)
        self.assertAlmostEqual(results[1]["actionability"], 0.9)

    def test_llm_failure_returns_defaults(self) -> None:
        ideas = [self._make_idea()]
        with patch("quant_llm_wiki.query.rethink.call_llm_chat", side_effect=RuntimeError("API down")):
            results = score_coherence_actionability(ideas)
        self.assertEqual(len(results), 1)
        self.assertAlmostEqual(results[0]["coherence"], 0.5)
        self.assertAlmostEqual(results[0]["actionability"], 0.5)

    def test_malformed_json_returns_defaults(self) -> None:
        ideas = [self._make_idea()]
        with patch("quant_llm_wiki.query.rethink.call_llm_chat", return_value="not json"):
            results = score_coherence_actionability(ideas)
        self.assertEqual(len(results), 1)
        self.assertAlmostEqual(results[0]["coherence"], 0.5)


from quant_llm_wiki.query.rethink import build_rethink_report


class BuildRethinkReportTests(unittest.TestCase):
    def _make_idea(self, title="Test Idea"):
        return BrainstormIdea(
            title=title, inspired_by="src", core_logic="logic",
            what_is_new="new", why_it_might_work="reason",
            what_could_break="risk", possible_variants="variant",
            raw_text="raw",
        )

    def test_report_contains_section_header(self) -> None:
        ideas = [self._make_idea()]
        novelty = [NoveltyResult(is_novel=True)]
        quality = [QualityScore(traceability=0.8, coherence=0.9, actionability=0.7,
                                composite=0.8, coherence_reasoning="good", actionability_reasoning="concrete")]
        report = build_rethink_report(ideas, novelty, quality)
        self.assertIn("## Rethink Report", report)

    def test_novel_idea_shows_checkmark(self) -> None:
        ideas = [self._make_idea()]
        novelty = [NoveltyResult(is_novel=True)]
        quality = [QualityScore(traceability=0.8, coherence=0.9, actionability=0.7,
                                composite=0.8, coherence_reasoning="good", actionability_reasoning="ok")]
        report = build_rethink_report(ideas, novelty, quality)
        self.assertIn("Novel", report)
        self.assertNotIn("Similar to existing", report)

    def test_similar_idea_shows_warning(self) -> None:
        ideas = [self._make_idea()]
        novelty = [NoveltyResult(is_novel=False, top_match_title="existing-idea",
                                 top_match_path="/path/to/article", top_match_score=0.82)]
        quality = [QualityScore(traceability=0.5, coherence=0.6, actionability=0.4,
                                composite=0.5, coherence_reasoning="weak", actionability_reasoning="vague")]
        report = build_rethink_report(ideas, novelty, quality)
        self.assertIn("Similar to existing", report)
        self.assertIn("existing-idea", report)
        self.assertIn("0.82", report)

    def test_empty_ideas_returns_empty_report(self) -> None:
        report = build_rethink_report([], [], [])
        self.assertEqual(report, "")


from quant_llm_wiki.query.rethink import rethink


class RethinkEntryPointTests(unittest.TestCase):
    BRAINSTORM_OUTPUT = (
        "### Idea Title\n动量+波动率组合策略\n\n"
        "**Inspired By**\nArticle A, Article B\n\n"
        "**Core Combination Logic**\n将Article A和Article B的方法结合\n\n"
        "**What Is New**\n之前没有将两者组合\n\n"
        "**Why It Might Make Sense**\n互补逻辑\n\n"
        "**What Could Break**\n市场环境变化\n\n"
        "**Possible Variants**\n可替换信号\n"
    )

    def _make_blocks(self):
        note = KnowledgeNote(
            article_dir=Path("a"), source_dir="reviewed",
            frontmatter={"title": "Article A", "status": "reviewed"}, body="",
        )
        return [KnowledgeBlock(note=note, block_type="summary", text="content", score=0.5)]

    def test_rethink_appends_report_to_output(self) -> None:
        blocks = self._make_blocks()
        mock_judge = json.dumps([
            {"idea_index": 0, "coherence": 0.8, "actionability": 0.7,
             "coherence_reasoning": "ok", "actionability_reasoning": "ok"},
        ])
        with patch("quant_llm_wiki.query.rethink._open_rethink_collection", side_effect=RuntimeError("no store")):
            with patch("quant_llm_wiki.query.rethink.call_llm_chat", return_value=mock_judge):
                result = rethink(self.BRAINSTORM_OUTPUT, blocks, "test query")
        self.assertIn("## Rethink Report", result)
        self.assertIn("动量+波动率组合策略", result)

    def test_rethink_returns_original_on_parse_failure(self) -> None:
        blocks = self._make_blocks()
        unstructured = "This is just plain text with no ideas."
        result = rethink(unstructured, blocks, "test query")
        self.assertEqual(result, unstructured)

    def test_rethink_returns_original_on_empty_output(self) -> None:
        blocks = self._make_blocks()
        result = rethink("", blocks, "test query")
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
