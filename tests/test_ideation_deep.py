from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quant_llm_wiki.ideation import deep as deep_mod  # noqa: E402
from quant_llm_wiki.shared import KnowledgeBlock, KnowledgeNote  # noqa: E402
from quant_llm_wiki.verdicts import VerdictRecord, save_verdict  # noqa: E402

GEN_OUTPUT = """Idea Title
低波+趋势过滤
Inspired By
A文章
Core Combination Logic
低波选股叠加趋势过滤
What Is New
双因子串联
Why It Might Make Sense
防御+择时
What Could Break
牛市踏空
Possible Variants
换ETF"""

CRIT_OUTPUT = json.dumps([{"attack_query": "q", "text": "有风险 [E1]",
                           "severity": "minor", "evidence_indexes": [1]}])
REFINE_OUTPUT = json.dumps({"action": "defend", "response": "[E1] 已考虑"})
JUDGE_OUTPUT = json.dumps([{"idea_index": 0, "coherence": 0.8, "actionability": 0.8,
                            "coherence_reasoning": "", "actionability_reasoning": ""}])


def _fake_block(tmp_path) -> KnowledgeBlock:
    note = KnowledgeNote(article_dir=tmp_path / "articles" / "a",
                         source_dir="reviewed",
                         frontmatter={"title": "A文章"}, body="")
    return KnowledgeBlock(note=note, block_type="failure_modes",
                          text="低波在牛市大幅跑输", score=0.9)


@pytest.fixture
def kb(tmp_path, monkeypatch):
    monkeypatch.setenv("QLW_KB_ROOT", str(tmp_path))
    save_verdict(tmp_path, VerdictRecord(
        id="v-lowvol", date="2026-07-03", direction="纯低波选股",
        hypothesis="低波占优", verdict="被证伪", failure_summary="均负"))
    return tmp_path


def _llm_router(messages, temperature=0.2):
    system = messages[0]["content"]
    if "红队" in system:
        return CRIT_OUTPUT
    if "精炼" in system:
        return REFINE_OUTPUT
    if "评审员" in system:
        return JUDGE_OUTPUT
    return GEN_OUTPUT


class TestRunDeepBrainstorm:
    def test_end_to_end_with_fakes(self, kb, tmp_path):
        blocks = [_fake_block(tmp_path)]
        with patch.object(deep_mod, "call_llm_chat", side_effect=_llm_router), \
             patch.object(deep_mod, "_load_context_blocks",
                          return_value=(blocks, "hybrid", None)), \
             patch.object(deep_mod, "_gather_candidate_evidence") as mock_ev, \
             patch("quant_llm_wiki.query.rethink.check_novelty") as mock_nov, \
             patch("quant_llm_wiki.query.rethink.call_llm_chat",
                   return_value=JUDGE_OUTPUT):
            from quant_llm_wiki.ideation.models import Evidence
            from quant_llm_wiki.query.rethink import NoveltyResult
            mock_ev.return_value = [Evidence("block", "articles/a",
                                             "failure_modes", "牛市跑输", 0.8)]
            mock_nov.return_value = [NoveltyResult(is_novel=True)]
            result = deep_mod.run_deep_brainstorm("低波方向", kb_root=kb, rounds=2)

        assert result.md_path.exists() and result.json_path.exists()
        assert result.log.survivors(), "defend 成功应有幸存者"
        assert result.log.stopped_reason == "收敛稳定（本轮无修订）"
        md = result.md_path.read_text(encoding="utf-8")
        assert "演化日志" in md and "低波+趋势过滤" in md
        assert "低波方向" in result.summary_text()

    def test_generation_prompt_injects_falsified_list(self, kb, tmp_path):
        seen = {}
        def llm(messages, temperature=0.2):
            if "红队" not in messages[0]["content"] and "评审员" not in messages[0]["content"] \
                    and "精炼" not in messages[0]["content"]:
                seen["gen_prompt"] = messages[-1]["content"]
            return _llm_router(messages)
        with patch.object(deep_mod, "call_llm_chat", side_effect=llm), \
             patch.object(deep_mod, "_load_context_blocks",
                          return_value=([_fake_block(tmp_path)], "keyword", None)), \
             patch.object(deep_mod, "_gather_candidate_evidence", return_value=[]), \
             patch("quant_llm_wiki.query.rethink.check_novelty") as mock_nov, \
             patch("quant_llm_wiki.query.rethink.call_llm_chat",
                   return_value=JUDGE_OUTPUT):
            from quant_llm_wiki.query.rethink import NoveltyResult
            mock_nov.return_value = [NoveltyResult(is_novel=True)]
            deep_mod.run_deep_brainstorm("低波方向", kb_root=kb, rounds=1)
        assert "纯低波选股" in seen["gen_prompt"]      # 已证伪清单注入
        assert "不要原样重提" in seen["gen_prompt"]

    def test_degraded_notes_when_no_verdicts_and_keyword_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setenv("QLW_KB_ROOT", str(tmp_path))
        with patch.object(deep_mod, "call_llm_chat", side_effect=_llm_router), \
             patch.object(deep_mod, "_load_context_blocks",
                          return_value=([_fake_block(tmp_path)], "keyword",
                                        "hybrid retrieval fell back to keyword")), \
             patch.object(deep_mod, "_gather_candidate_evidence", return_value=[]), \
             patch("quant_llm_wiki.query.rethink.check_novelty") as mock_nov, \
             patch("quant_llm_wiki.query.rethink.call_llm_chat",
                   return_value=JUDGE_OUTPUT):
            from quant_llm_wiki.query.rethink import NoveltyResult
            mock_nov.return_value = [NoveltyResult(is_novel=True)]
            result = deep_mod.run_deep_brainstorm("低波方向", kb_root=tmp_path, rounds=1)
        joined = " ".join(result.log.degraded_notes)
        assert "verdict 层为空" in joined
        assert "keyword" in joined
