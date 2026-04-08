import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import enrich_articles_with_llm as mod
import kb_shared


class EnrichArticlesWithLlmTests(unittest.TestCase):
    def test_validate_enhancement_data_non_strategy_clears_trade_fields(self) -> None:
        data = {
            "reusability": "adaptable",
            "idea_blocks": ["a", "b", "c"],
            "source_claim_strength": "moderate",
            "brainstorm_value": "high",
            "entry_rule": "buy when x",
            "exit_rule": "sell when y",
            "risk_control": ["stop loss"],
            "backtest_metrics": {"sharpe": 1.2},
            "rebalance_logic": "monthly",
            "confidence": 2,
        }
        normalized = mod.validate_enhancement_data(data, "methodology")
        self.assertEqual(normalized["entry_rule"], "")
        self.assertEqual(normalized["exit_rule"], "")
        self.assertEqual(normalized["risk_control"], [])
        self.assertEqual(normalized["backtest_metrics"], {})
        self.assertEqual(normalized["rebalance_logic"], "")
        self.assertEqual(normalized["confidence"], 1.0)

    def test_validate_enhancement_data_filters_unknown_taxonomy_values(self) -> None:
        data = {
            "strategy_type": ["risk_control", "unknown_tag"],
            "market": ["general", "mars_market"],
            "asset_type": ["general_time_series", "unknown_asset"],
        }
        normalized = mod.validate_enhancement_data(data, "risk_control")
        self.assertEqual(normalized["strategy_type"], ["risk_control"])
        self.assertEqual(normalized["market"], ["general"])
        self.assertEqual(normalized["asset_type"], ["general_time_series"])

    def test_parse_json_response_supports_fenced_json(self) -> None:
        raw = "```json\n{\"summary\": \"x\"}\n```"
        parsed = mod.parse_json_response(raw)
        self.assertEqual(parsed["summary"], "x")

    def test_apply_markdown_updates_replaces_sections(self) -> None:
        markdown = """---
summary:
research_question:
core_hypothesis:
signal_framework:
---

## Summary

待生成。

## Research Question

待补充。

## Core Hypothesis

待补充。

## Signal Framework / Decision Framework

待补充。

## Idea Blocks

待补充。
"""
        enhancement = {
            "summary": "摘要",
            "research_question": "研究问题",
            "core_hypothesis": "核心假设",
            "signal_framework": "信号框架",
            "application_scope": "",
            "constraints": [],
            "idea_blocks": ["想法1", "想法2"],
            "combination_hooks": [],
            "transfer_targets": [],
            "contrast_points": [],
            "failure_modes": [],
            "followup_questions": [],
        }
        updated = mod.apply_markdown_updates(markdown, enhancement, "methodology")
        self.assertIn("摘要", updated)
        self.assertIn("研究问题", updated)
        self.assertIn("核心假设", updated)
        self.assertIn("信号框架", updated)
        self.assertIn("- 想法1", updated)

    def test_build_prompt_payload_applies_limits(self) -> None:
        old_main = mod.os.environ.get("ZHIPU_MAIN_CONTENT_LIMIT")
        old_block_limit = mod.os.environ.get("ZHIPU_CODE_BLOCK_LIMIT")
        old_char_limit = mod.os.environ.get("ZHIPU_CODE_BLOCK_CHAR_LIMIT")
        try:
            mod.os.environ["ZHIPU_MAIN_CONTENT_LIMIT"] = "10"
            mod.os.environ["ZHIPU_CODE_BLOCK_LIMIT"] = "1"
            mod.os.environ["ZHIPU_CODE_BLOCK_CHAR_LIMIT"] = "5"
            body = "## Main Content\n\n1234567890abcdef\n"
            source_json = {"code_blocks": [{"language": "python", "content": "abcdefghi"}, {"language": "python", "content": "zzzzz"}]}
            payload = mod.build_prompt_payload({"title": "t", "content_type": "methodology"}, body, source_json)
            self.assertEqual(payload["main_content"], "1234567890")
            self.assertIn("abcde", payload["code_blocks"])
            self.assertNotIn("zzzzz", payload["code_blocks"])
        finally:
            if old_main is None:
                mod.os.environ.pop("ZHIPU_MAIN_CONTENT_LIMIT", None)
            else:
                mod.os.environ["ZHIPU_MAIN_CONTENT_LIMIT"] = old_main
            if old_block_limit is None:
                mod.os.environ.pop("ZHIPU_CODE_BLOCK_LIMIT", None)
            else:
                mod.os.environ["ZHIPU_CODE_BLOCK_LIMIT"] = old_block_limit
            if old_char_limit is None:
                mod.os.environ.pop("ZHIPU_CODE_BLOCK_CHAR_LIMIT", None)
            else:
                mod.os.environ["ZHIPU_CODE_BLOCK_CHAR_LIMIT"] = old_char_limit

    @patch("enrich_articles_with_llm.get_llm_config")
    def test_update_source_json_sets_llm_metadata(self, mock_config) -> None:
        mock_config.return_value = ("key", "https://api.example.com/v1", "test-model")
        updated = mod.update_source_json({}, {"summary": "x"}, "{\"summary\":\"x\"}")
        self.assertEqual(updated["llm_provider"], "https://api.example.com/v1")
        self.assertEqual(updated["llm_model"], "test-model")
        self.assertTrue(updated["llm_enriched"])
        self.assertEqual(updated["summary"], "x")


    def test_classify_llm_error(self) -> None:
        self.assertEqual(mod.classify_llm_error("Read timed out"), "timeout")
        self.assertEqual(mod.classify_llm_error("Expecting value: line 1 column 1 (char 0) json decode error"), "json_parse_error")
        self.assertEqual(mod.classify_llm_error("401 Client Error"), "api_error")

    def test_write_llm_failures(self) -> None:
        original_path = mod.LLM_FAILURES_PATH
        with tempfile.TemporaryDirectory() as tmpdir:
            mod.LLM_FAILURES_PATH = Path(tmpdir) / "llm_failures.txt"
            results = [
                mod.ProcessResult(article_dir="a", success=False, error="Read timed out"),
                mod.ProcessResult(article_dir="b", success=False, error="Expecting value: line 1 column 1 (char 0) json decode error"),
                mod.ProcessResult(article_dir="c", success=True),
            ]
            try:
                output = mod.write_llm_failures(results)
                content = output.read_text(encoding="utf-8")
            finally:
                mod.LLM_FAILURES_PATH = original_path
            self.assertIn("a	timeout	Read timed out", content)
            self.assertIn("b	json_parse_error	Expecting value: line 1 column 1 (char 0) json decode error", content)

if __name__ == "__main__":
    unittest.main()
